"""Track P experiment: run WS-1.1 end to end on real consumer-credit applications.

    python -m lending_hub.scoring.experiment \\
        --path "datasets/home-credit-default-risk/application_train.csv" \\
        --out reports/trackP_p1_home_credit.json

ADR-0010 selects Home Credit for this run. What it can and cannot demonstrate is
fixed by that ADR and restated in the output, because a JSON file full of AUCs
outlives the conversation that produced it:

* It **can** show the pipeline survives real missingness, real class imbalance
  (~8% bad), real sentinel encodings and 54 real features — the things fixtures
  cannot test because a fixture has the defects its author thought of.
* It **cannot** produce out-of-time evidence. The source has no clock (registry:
  ``point_in_time_unsafe``), so the holdout is random and every metric is stamped
  ``out_of_time=false``.
* It **cannot** produce Appendix A numbers. The label is the vendor's.
* It is **not gate evidence** for anything (ADR-0004).

Nothing here is a Track B run with different data. It is the same code paths,
which is the whole point of running it.

Workstream: WS-1.1 (all steps) · ADR-0004, ADR-0010
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from datetime import date

from lending_hub.definitions import DEFINITIONS_VERSION, fingerprint
from lending_hub.sources.homecredit import (
    CATEGORICAL_FEATURES,
    DERIVED_FEATURES,
    NUMERIC_FEATURES,
    SOURCE_ID,
    TARGET_DEFINITION,
    load,
    to_applications,
)

from .binning import fit_binning
from .calibration import CalibrationSource, fit_calibration
from .explain import explain_gbm, global_importance
from .fairness import assess
from .features import PROTECTED_NAMES, ProtectedAttributeAccess, ScreenVerdict
from .gbm import MonotoneConstraints, fit_gbm
from .rejects import memo_when_unavailable
from .scorecard import fit_scorecard, negative_coefficients
from .splits import Part, holdout_without_time_axis, manifest
from .target import LabelProvenance, build_target_table
from .validation import monotonicity_spot_check, sensitivity, swap_sets, validate

#: One cohort, because the source has no time axis. Named so the vintage split
#: refuses it rather than producing a fake ordering.
SINGLE_COHORT = "no-time-axis"

#: How many binned characteristics the scorecard keeps, highest IV first.
#: A scorecard is a document a credit officer reads; twenty characteristics is
#: already at the edge of that, and the marginal IV past the top handful is
#: mostly correlated with what is already in.
SCORECARD_CHARACTERISTICS = 15


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def run(path: str, *, limit: int | None, seed: int, trees: int) -> dict:
    started = time.time()

    _log(f"loading {path} ...")
    rows, labels, protected, load_summary = load(path, limit=limit)
    _log(f"  {load_summary.kept} rows, base rate {load_summary.base_rate:.4f}")

    applications = to_applications(
        rows, labels, decided_at=date(2018, 1, 1), vintage=SINGLE_COHORT
    )
    table = build_target_table(
        applications,
        dataset=SOURCE_ID,
        provenance=LabelProvenance.VENDOR,
        label_note=TARGET_DEFINITION,
        # This source carries none of the three Phase 1 exclusion flags — it is a
        # public extract, not a bank CBS. Accepted deliberately and recorded, per
        # WS-1.1 Step 1; the limitation goes on the model card.
        require_enforceable=False,
    )

    splits = holdout_without_time_axis(table, source_id=SOURCE_ID, seed=seed)
    split_manifest = manifest(table, splits)
    _log(f"  split {split_manifest.sizes} (out_of_time={splits.out_of_time})")

    by_id = {row["application_id"]: row for row in rows}

    def design(part: Part):
        part_rows = splits.trainable(part)
        return (
            [by_id[row.application_id] for row in part_rows],
            [row.y for row in part_rows],
            [row.application_id for row in part_rows],
        )

    train_rows, train_y, _ = design(Part.TRAIN)
    validation_rows, validation_y, _ = design(Part.VALIDATION)
    test_rows, test_y, test_ids = design(Part.TEST)

    candidates = (
        list(NUMERIC_FEATURES)
        + list(DERIVED_FEATURES)
        + [f"{name}_missing" for name in NUMERIC_FEATURES]
        + [
            name
            for name in load_summary.feature_names
            if any(name.startswith(f"{c}=") for c in CATEGORICAL_FEATURES)
        ]
    )

    # ---- WS-1.1 Step 3: bin, screen, and keep what survives ------------------
    _log(f"binning {len(candidates)} candidate features on {len(train_rows)} rows ...")
    screened: list[dict] = []
    binnings = []
    for name in candidates:
        try:
            binning = fit_binning(
                [row.get(name) for row in train_rows], train_y, feature=name
            )
        except Exception as exc:  # noqa: BLE001 - a feature that cannot bin is a finding
            screened.append({"feature": name, "verdict": "unbinnable", "note": str(exc)})
            continue
        verdict, note = binning.screen()
        screened.append(
            {
                "feature": name,
                "iv": binning.iv,
                "verdict": verdict.value,
                "note": note,
                "n_bins": len(binning.bins),
                "direction": binning.direction.value,
                "direction_source": binning.direction_source,
            }
        )
        if verdict is ScreenVerdict.PASS:
            binnings.append(binning)

    binnings.sort(key=lambda b: -b.iv)
    kept = binnings[:SCORECARD_CHARACTERISTICS]
    _log(f"  {len(binnings)} passed the IV screen; scorecard keeps {len(kept)}")

    # ---- WS-1.1 Step 3: the champion ----------------------------------------
    _log("fitting the WOE scorecard ...")
    scorecard = fit_scorecard(train_rows, train_y, kept, epochs=15, seed=seed)

    # ---- WS-1.1 Step 4: the challenger --------------------------------------
    challenger_features = [b.feature for b in binnings]
    constraints = MonotoneConstraints.for_experiment(
        challenger_features,
        reason=(
            "the ratified monotonicity direction list is [POLICY: Credit Risk Head] "
            "and does not exist (LH-202). This model is a Track P experiment and is "
            "not promotable."
        ),
    )
    _log(f"fitting the challenger on {len(challenger_features)} features ...")
    challenger = fit_gbm(
        train_rows,
        train_y,
        challenger_features,
        constraints,
        n_trees=trees,
        max_depth=3,
        max_bins=32,
        validation=(validation_rows, validation_y),
        early_stopping_rounds=15,
        seed=seed,
    )
    _log(f"  {len(challenger.trees)} trees, best iteration {challenger.best_iteration}")

    # ---- WS-1.1 Step 5: calibration -----------------------------------------
    _log("calibrating ...")
    scorecard_validation = scorecard.predict_all(validation_rows)
    challenger_validation = challenger.predict_all(validation_rows)

    scorecard_calibration = fit_calibration(
        scorecard_validation, validation_y,
        source=CalibrationSource.VALIDATION, model_selected_on_these_rows=False,
    )
    challenger_calibration = fit_calibration(
        challenger_validation, validation_y,
        source=CalibrationSource.VALIDATION,
        # The challenger's early stopping ran on these rows. Phase 1 §4 Steps 4
        # and 5 use the same set; the flag records what that costs rather than
        # overruling the phase file.
        model_selected_on_these_rows=True,
    )

    # Calibrate *both* sides of every later comparison. The first version of this
    # run reported a train-to-test score PSI of 4.7 on a random split of one
    # population — an impossible number, and the cause was comparing raw training
    # scores against calibrated test scores. PSI does not know it is being handed
    # two different scales; it just returns a large number, and a large PSI in a
    # gate pack reads as a finding about the population rather than a defect in
    # the harness.
    scorecard_test = scorecard_calibration.calibrator.predict_all(
        scorecard.predict_all(test_rows)
    )
    challenger_test = challenger_calibration.calibrator.predict_all(
        challenger.predict_all(test_rows)
    )
    scorecard_train = scorecard_calibration.calibrator.predict_all(
        scorecard.predict_all(train_rows)
    )
    challenger_train = challenger_calibration.calibrator.predict_all(
        challenger.predict_all(train_rows)
    )

    # ---- WS-1.1 Step 9: validation ------------------------------------------
    _log("validating ...")
    checks = []
    for binning in kept[:5]:
        grid = sorted(
            {
                b.lower
                for b in binning.bins
                if not b.is_missing and b.lower is not None
            }
        )
        if len(grid) < 2:
            continue
        base = dict(test_rows[0])
        checks.append(
            monotonicity_spot_check(
                challenger.predict, base, binning.feature, grid,
                expect_increasing=binning.direction.value == "increasing",
            )
        )

    sensitivity_results = sensitivity(
        challenger.predict, test_rows[:400], [b.feature for b in kept[:8]]
    )

    # The comparator is the *champion scorecard*, not a rebuilt legacy scorecard:
    # this bank has no legacy model and this dataset has no incumbent. The §7
    # criterion stays unevaluated for that reason and because the split is not
    # out of time.
    median = sorted(scorecard_test)[len(scorecard_test) // 2]
    swap = swap_sets(
        [1 if p <= median else 0 for p in scorecard_test],
        [1 if p <= median else 0 for p in challenger_test],
        test_y,
        [protected[i]["age_band"] or "unknown" for i in test_ids],
    )

    scorecard_report = validate(
        model="champion_woe_scorecard",
        train_labels=train_y, train_scores=scorecard_train,
        test_labels=test_y, test_scores=scorecard_test,
        out_of_time=splits.out_of_time, dataset=SOURCE_ID, track="P",
    )
    challenger_report = validate(
        model="challenger_gbm",
        train_labels=train_y, train_scores=challenger_train,
        test_labels=test_y, test_scores=challenger_test,
        out_of_time=splits.out_of_time, dataset=SOURCE_ID, track="P",
        legacy_test_scores=scorecard_test,
        monotonicity=checks, sensitivity_results=sensitivity_results, swap_set=swap,
    )

    # ---- WS-1.1 Step 7: fairness --------------------------------------------
    _log("measuring fairness ...")
    access = ProtectedAttributeAccess(protected)
    approvals = [1 if p <= median else 0 for p in challenger_test]
    fairness = assess(
        test_ids, approvals, access,
        model="challenger_gbm", labels=test_y,
        attributes=tuple(sorted(PROTECTED_NAMES)),
    )

    # ---- WS-1.1 Step 6: explainability --------------------------------------
    _log("computing global SHAP importance ...")
    importance = global_importance(challenger, test_rows, limit=200)
    riskiest = max(test_rows, key=challenger.predict)
    local = explain_gbm(challenger, riskiest)

    return {
        "run": {
            "dataset": SOURCE_ID,
            "track": "P",
            "seed": seed,
            "seconds": round(time.time() - started, 1),
            "definitions_version": DEFINITIONS_VERSION,
            "definitions_fingerprint": fingerprint(),
        },
        "limitations": [
            "Track P: real applications, not this bank's portfolio. Not gate "
            "evidence for any Phase 1 exit criterion (ADR-0004).",
            "The label is the vendor's, not Master Appendix A. " + TARGET_DEFINITION,
            "The source is declared point_in_time_unsafe: no vintage exists, the "
            "holdout is random, and no metric here is out-of-time evidence.",
            "The challenger is fitted without monotone constraints because the "
            "ratified direction list does not exist (LH-202). It is not promotable.",
            "The comparator for the uplift figure is the champion scorecard fitted "
            "in this same run, not a rebuilt legacy scorecard. The Phase 1 §7 "
            "criterion is not addressed by it.",
            "No Phase 1 exclusion flag (fraud-tagged, staff loan, restructure) "
            "exists in this extract, so all three exclusions are unenforceable and "
            "were accepted deliberately.",
        ],
        "load": load_summary.to_dict(),
        "target": table.manifest(),
        "split": split_manifest.to_dict(),
        "feature_screen": sorted(
            screened, key=lambda item: -(item.get("iv") or 0.0)
        ),
        "scorecard": {
            **scorecard.to_dict(),
            "characteristics_kept": [b.feature for b in kept],
            "negative_coefficients": negative_coefficients(scorecard),
            "calibration": scorecard_calibration.to_dict(),
        },
        "challenger": {
            **challenger.to_dict(),
            "calibration": challenger_calibration.to_dict(),
            "global_shap_importance": [
                {"feature": name, "mean_abs_shap": value} for name, value in importance
            ],
            "shap_sample_size": min(200, len(test_rows)),
            "worst_case_explanation": local.to_dict(),
        },
        "validation": {
            "champion": scorecard_report.to_dict(),
            "challenger": challenger_report.to_dict(),
        },
        "fairness": fairness.to_dict(),
        "reject_inference": memo_when_unavailable(
            "challenger_gbm",
            reason=(
                "no declined applications exist in this extract — Home Credit's "
                "previous_application.csv was not supplied (ADR-0010)"
            ),
        ).to_dict(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Track P Phase 1 scoring experiment")
    parser.add_argument(
        "--path",
        default="datasets/home-credit-default-risk/application_train.csv",
        help="Home Credit application_train.csv",
    )
    parser.add_argument("--out", default="reports/trackP_p1_home_credit.json")
    parser.add_argument("--limit", type=int, default=60_000, help="rows to read")
    parser.add_argument("--seed", type=int, default=20260901)
    parser.add_argument("--trees", type=int, default=120)
    args = parser.parse_args(argv)

    if not pathlib.Path(args.path).exists():
        _log(
            f"{args.path} not found. Track P data is gitignored — see "
            "docs/phase0/DATA_SOURCING.md for how to obtain it."
        )
        return 2

    report = run(args.path, limit=args.limit, seed=args.seed, trees=args.trees)

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    _log(f"wrote {out}")

    challenger = report["validation"]["challenger"]
    print(
        f"champion  Gini {report['validation']['champion']['test']['gini_points']:.2f} · "
        f"challenger Gini {challenger['test']['gini_points']:.2f} · "
        f"uplift {challenger['gini_uplift_points']:.2f} pts "
        f"(out_of_time={challenger['out_of_time']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

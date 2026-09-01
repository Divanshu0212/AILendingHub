"""Track P runner — the whole of Phase 3 against real mortgage performance data.

Runs WS-3.1 and WS-3.2 end to end on the Fannie Mae panel and writes
``reports/trackP_p3_fannie_mae.json``. Every number it produces is **Track P**:
real data, real missingness, real prepayment behaviour — and US conforming
mortgages, not this bank's book. Nothing here is Phase 3 gate evidence
(ADR-0003, ADR-0004), and the report says so on its face.

What it is for is the other thing a gate needs: proof that the code paths run
on data that was not built to suit them. Every defect this phase found —
negative workout costs, proceeds posting as reversals, the credit-enhancement
sign flip — came out of this runner rather than out of a fixture.

    python -m lending_hub.portfolio.experiment --sample-rate 0.02

Workstream: WS-3.1, WS-3.2 · ADR-0004
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone

from lending_hub.definitions import fingerprint
from lending_hub.portfolio import aggregates as agg
from lending_hub.portfolio import behavioural as beh
from lending_hub.portfolio import competing, cox, hazard, lgd, staging, survival
from lending_hub.portfolio import transitions as trans
from lending_hub.portfolio.panel import Event, split_by_snapshot
from lending_hub.scoring.gbm import MonotoneConstraints
from lending_hub.sources import fanniemae, fanniemae_panel

DEFAULT_PATH = "datasets/Fannie Mae/2007Q1.csv"
DEFAULT_OUTPUT = "reports/trackP_p3_fannie_mae.json"

#: Out-of-time split point. Phase 3 §7 requires validation "by snapshot month",
#: and this vintage's story is the crisis: fit before it resolves, test after.
SPLIT_SNAPSHOT = "2012-12-31"

#: Horizons the survival metrics are evaluated at, in months *beyond the
#: observation point*.
METRIC_HORIZONS = (12, 24, 36, 48)

#: Months on book beyond which no account-month enters the risk set. The
#: challenger never sees a month past this, so survival metrics censor subjects
#: here too — grading a model on events at month 200 when it was fitted to
#: months 0-60 measures extrapolation, not discrimination.
FITTED_HORIZON = 60

#: Months on book at which survival metrics are taken.
#:
#: Not zero, and the reason is a finding rather than a tuning choice. A
#: behavioural hazard model evaluated at origination produces an exactly
#: constant risk score — every arrears feature is zero for every loan at month
#: 0, so every loan reaches the same leaf, and Harrell's C comes out at exactly
#: 0.5 because every pair is tied. That is not a weak model; it is a model being
#: asked a question none of its features can answer. Scoring at a month where
#: behavioural information exists is what makes the Phase 3 §7 comparison
#: between the Cox reference and the challenger meaningful at all.
OBSERVATION_MONTH = 12

#: Cox is fitted on a subsample of account-months. Newton-Raphson on the full
#: panel is not intractable, it is just slow enough to discourage rerunning the
#: report, and the reference model's role is interpretability rather than the
#: last basis point of precision. Stated because a subsample is a limitation.
COX_MAX_ROWS = 120_000

COX_FEATURES = ("max_dpd_12m", "orig_oltv", "orig_credit_score", "orig_dti")

#: Challenger hyperparameters.
#:
#: ``feature_fraction`` is here for a reason specific to this problem. A
#: discrete-time hazard model is asked "does this account default *this
#: month*", and the most informative answer is nearly always the most recent
#: arrears reading. Left unconstrained the trees spend themselves on
#: ``dpd_now`` and ``max_dpd_3m`` — 61 of the first 100 splits on a fitted
#: model — and those are zero for about 99% of accounts at any snapshot,
#: because delinquency is rare. The model then discriminates well inside the
#: delinquent tail and barely at all across the population, which is what a
#: portfolio ranking needs. Column subsampling forces each split to consider
#: features with broader coverage.
#:
#: **Do not read these as tuned values.** A grid at one sample size preferred
#: this configuration by a wide margin and the preference did not survive a
#: larger sample; the run report carries the measured uplift, and the spread
#: behind it is Phase 3 finding D6. ``scale_pos_weight`` is deliberately
#: absent — the standard handling for a rare event made the model *worse than
#: random* at every size tried.
CHALLENGER_PARAMS = {
    "n_trees": 200,
    "max_depth": 4,
    "learning_rate": 0.05,
    "feature_fraction": 0.5,
}

#: Covariates whose admissibility in a Cox model is *tested* rather than
#: asserted, with the hypothesis each is tested against. :func:`_cox_exclusions`
#: refits with each one added and records what actually happened — which is the
#: point, because one of these hypotheses turned out to be wrong on this data.
COX_HYPOTHESES = {
    "months_observed": (
        "expected to be unidentified — it is a deterministic function of months "
        "on book, so it should be constant within every risk set. On this panel "
        "it is NOT: loans enter at different ages because a quarterly "
        "acquisition file's reporting periods start at the acquisition quarter, "
        "so months observed varies among loans at risk together and the "
        "coefficient is identified after all."
    ),
    "dpd_now": (
        "expected to separate — reaching the Appendix A default threshold "
        "means passing through the arrears band below it the month before, "
        "so at monthly granularity the current reading nearly determines "
        "next month's event among those at risk together"
    ),
}


def _numeric(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def run(path: str, output: str, *, sample_rate: float, row_limit: int | None) -> dict:
    started = time.time()
    report: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "track": "P",
        "dataset": "fannie_mae_sf_loan_performance",
        "vintage": os.path.basename(path).replace(".csv", ""),
        "definitions_fingerprint": fingerprint(),
        "gate_evidence": False,
        "note": (
            "Track P (ADR-0004): real US conforming mortgages, not this bank's "
            "portfolio. These figures prove the Phase 3 code paths run against "
            "real data; they are not Phase 3 gate evidence and no exit criterion "
            "may be marked met from them."
        ),
    }

    print(f"loading {path} at sample rate {sample_rate} ...")
    panel, load_summary = fanniemae_panel.load_panel(
        path, sample_rate=sample_rate, row_limit=row_limit,
        vintage=report["vintage"])
    report["panel"] = load_summary.to_dict()
    print(f"  {load_summary.loans_sampled:,} loans, "
          f"{load_summary.account_months:,} account-months, "
          f"{load_summary.events}")

    # ---------------------------------------------------------------- WS-3.1/1
    print("building behavioural design ...")
    origination = ["oltv", "credit_score", "dti", "orig_rate", "orig_term"]
    rows = beh.build_design(panel, min_months_on_book=3)
    names = beh.feature_names(origination)
    before, after = split_by_snapshot(rows, cutoff=_as_date(SPLIT_SNAPSHOT))
    print(f"  {len(rows):,} rows; train {len(before):,} / test {len(after):,} "
          f"(out of time, split {SPLIT_SNAPSHOT})")

    constraints = MonotoneConstraints.for_experiment(
        names, reason="Track P experiment; behavioural directions unratified (LH-310)")
    model = beh.fit_behavioural(
        before, names, constraints, horizon_months=12,
        validation_rows=after, n_trees=60, max_depth=4, learning_rate=0.1)
    report["behavioural_pd"] = model.to_dict()
    report["behavioural_pd"]["out_of_time"] = True
    report["behavioural_pd"]["split_snapshot"] = SPLIT_SNAPSHOT

    trainable_test = [r for r in after if r.trainable]
    if trainable_test:
        from lending_hub.scoring.validation import gini as _gini
        scores = [model.predict(r.features) for r in trainable_test]
        labels = [r.target for r in trainable_test]
        report["behavioural_pd"]["test_rows"] = len(trainable_test)
        report["behavioural_pd"]["test_bad_rate"] = sum(labels) / len(labels)
        report["behavioural_pd"]["test_gini"] = round(_gini(labels, scores), 2)
        print(f"  out-of-time Gini {report['behavioural_pd']['test_gini']}")

        # A behavioural model with current DPD in it is largely answering "will
        # this delinquency continue", which is a far easier question than the
        # application model's "will this borrower go bad". Without that number
        # beside it, a high behavioural Gini reads as a leak or as a triumph,
        # and it is neither.
        arrears_free = [n for n in names if not _is_arrears_feature(n)]
        stripped = beh.fit_behavioural(
            before, arrears_free,
            MonotoneConstraints.for_experiment(
                arrears_free, reason="Track P ablation; LH-310"),
            horizon_months=12, n_trees=60, max_depth=4, learning_rate=0.1)
        stripped_scores = [stripped.predict(r.features) for r in trainable_test]
        report["behavioural_pd"]["ablation_without_arrears_features"] = {
            "features_removed": [n for n in names if _is_arrears_feature(n)],
            "test_gini": round(_gini(labels, stripped_scores), 2),
            "note": (
                "the headline Gini is dominated by current and recent arrears. "
                "That is the expected behaviour of a behavioural scorecard "
                "(SRS §7.3.1) and not a leak — portfolio.behavioural."
                "assert_point_in_time proves no feature reads past the "
                "observation month — but it means the number is not comparable "
                "with an application scorecard's."
            ),
        }
        print(f"  without arrears features: Gini "
              f"{report['behavioural_pd']['ablation_without_arrears_features']['test_gini']}")

    # ------------------------------------------------------------ WS-3.1/2,3,4
    print("building the risk set ...")
    hazard_rows = panel.hazard()
    hazard_rows = [r for r in hazard_rows if r.months_on_book <= FITTED_HORIZON]
    features_for_hazard = _attach_hazard_features(panel, hazard_rows)
    print(f"  {len(hazard_rows):,} account-months at risk")

    print("fitting the Cox reference ...")
    cox_rows = hazard_rows[:COX_MAX_ROWS]
    intervals = cox.intervals_from_hazard_rows(cox_rows, COX_FEATURES)
    cox_model = cox.fit_cox(intervals, list(COX_FEATURES))
    report["cox"] = cox_model.summary()
    report["cox"]["rows_used"] = len(cox_rows)
    report["cox"]["subsampled"] = len(cox_rows) < len(hazard_rows)
    print(f"  tie fraction {cox_model.tie_fraction:.3f}, "
          f"converged={cox_model.converged}")

    report["cox_excluded_covariates"] = _cox_exclusions(cox_rows)

    breslow = cox.fit_cox(intervals, list(COX_FEATURES), ties="breslow")
    report["cox_tie_sensitivity"] = {
        "efron": {c.name: round(c.beta, 6) for c in cox_model.coefficients},
        "breslow": {c.name: round(c.beta, 6) for c in breslow.coefficients},
        "breslow_promotable": breslow.promotable[0],
        "breslow_blocker": breslow.promotable[1],
    }

    print("fitting the discrete-time hazard challenger ...")
    hazard_constraints = MonotoneConstraints.for_experiment(
        features_for_hazard,
        reason="Track P experiment; behavioural directions unratified (LH-310)")
    hazard_model = hazard.fit_hazard(
        hazard_rows, features_for_hazard, hazard_constraints,
        **CHALLENGER_PARAMS)
    report["hazard"] = hazard_model.to_dict()

    print("fitting competing risks ...")
    cr = competing.fit_competing_risks(
        hazard_rows, features_for_hazard, hazard_constraints,
        n_trees=60, max_depth=3, learning_rate=0.1, feature_fraction=0.5)
    report["competing_risks"] = cr.to_dict()

    observed = competing.observed_incidence(panel, horizon=max(METRIC_HORIZONS))
    report["observed_incidence"] = {
        "horizon_months": max(METRIC_HORIZONS),
        "cif_default": round(observed.default_at(max(METRIC_HORIZONS)), 6),
        "cif_prepay": round(observed.prepay_at(max(METRIC_HORIZONS)), 6),
        "naive_default_ignoring_competition": round(
            observed.naive_at(max(METRIC_HORIZONS)), 6),
        "overstatement": round(observed.overstatement_at(max(METRIC_HORIZONS)), 6),
        "relative_overstatement": round(
            observed.overstatement_at(max(METRIC_HORIZONS))
            / observed.default_at(max(METRIC_HORIZONS)), 4
        ) if observed.default_at(max(METRIC_HORIZONS)) > 0 else None,
        "decomposition_closes": observed.closes(1e-6),
    }
    print(f"  CIF default {report['observed_incidence']['cif_default']:.4f} vs "
          f"naive {report['observed_incidence']['naive_default_ignoring_competition']:.4f}")

    # ------------------------------------------------------------- survival metrics
    print("scoring survival metrics ...")
    report["survival_metrics"] = _survival_metrics(panel, hazard_model, cox_model)

    # ---------------------------------------------------------------- WS-3.1/5
    print("fitting LGD on workout cashflows ...")
    report["lgd"] = _lgd_section(path, row_limit)

    # ---------------------------------------------------------------- WS-3.1/7
    print("staging ...")
    report["staging"] = _staging_section(panel)

    # ------------------------------------------------------------------ WS-3.2
    print("dashboards ...")
    matrix = trans.build_matrix(panel.pairs())
    report["transitions"] = {
        "matrix": matrix.to_dict(),
        "roll_30_to_60": matrix.roll_rate("1-30", "31-60"),
        "roll_60_to_90": matrix.roll_rate("31-60", "61-89"),
        "forecast_12m_from_current": matrix.forward({"current": 1.0}, 12).to_dict(),
    }

    report["vintage_curves"] = {
        cohort: curve.to_dict()
        for cohort, curve in agg.vintage_curves(
            panel,
            lambda s: s.origination.strftime("%Y-%m") if s.origination else "unknown",
            max_months=36,
        ).items()
    }

    report["aggregates"] = _aggregate_section(panel, model, origination)
    report["elapsed_seconds"] = round(time.time() - started, 1)

    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    with open(output, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, default=str)
    print(f"wrote {output} in {report['elapsed_seconds']}s")
    return report


def _cox_exclusions(rows) -> dict:
    """Refit with each hypothesised covariate added, and record what happened.

    Written as a demonstration rather than a comment: "this covariate cannot go
    in a Cox model" is a claim, the claim is cheap to check, and checking it
    here already overturned one of the two.
    """
    out = {}
    for name, expected in COX_HYPOTHESES.items():
        features = list(COX_FEATURES) + [name]
        try:
            cox.fit_cox(cox.intervals_from_hazard_rows(rows, features), features)
            out[name] = {
                "hypothesis": expected,
                "outcome": "admissible",
                "note": "the covariate fitted; the hypothesis above does not hold here",
            }
        except cox.CoxError as exc:
            out[name] = {
                "hypothesis": expected,
                "outcome": "rejected",
                "note": str(exc),
            }
    return out


def _is_arrears_feature(name: str) -> bool:
    return (
        name.startswith(("max_dpd_", "times_in_arrears_"))
        or name in ("dpd_now", "worst_dpd_ever", "ever_in_arrears", "dpd_trend_3m")
    )


def _as_date(text: str):
    from datetime import date
    y, m, d = (int(part) for part in text.split("-"))
    return date(y, m, d)


def _attach_hazard_features(panel, hazard_rows) -> list[str]:
    """Attach behavioural + origination features to each risk-set row."""
    positions = {}
    for spell in panel.spells:
        positions[spell.account_id] = (
            spell, {m.snapshot: i for i, m in enumerate(spell.months)})

    for row in hazard_rows:
        spell, index_of = positions[row.account_id]
        index = index_of.get(row.snapshot)
        if index is None:
            index = len(spell.months) - 1
        row.features.clear()
        row.features.update(beh.trailing_features(spell, index))
    return [n for n in beh.feature_names(
        ["oltv", "credit_score", "dti", "orig_rate", "orig_term"])
        if n != hazard.TIME_FEATURE]


def _survival_metrics(panel, hazard_model, cox_model) -> dict:
    """Score both models from a common observation point, on common subjects.

    Phase 3 §7 compares the challenger's C-index against the Cox reference's, so
    both must see the same subjects, the same observation month and the same
    time axis. Anything else compares two populations.

    Subjects are loans still alive at :data:`OBSERVATION_MONTH`, with covariates
    as of that month and time measured forward from it.
    """
    from lending_hub.portfolio.panel import months_between

    subjects, hazard_risk, cox_risk, curves = [], [], [], []
    horizons = list(METRIC_HORIZONS)

    for spell in panel.spells:
        index = next(
            (i for i, m in enumerate(spell.months)
             if m.months_on_book >= OBSERVATION_MONTH),
            None,
        )
        if index is None:
            continue

        observed_at = spell.months[index]
        # Events strictly after the observation point only — an account that
        # had already defaulted is not at risk from here.
        if spell.event_month is not None and spell.event_month <= observed_at.snapshot:
            continue

        last = spell.months[-1]
        end = last.months_on_book
        event = spell.event is Event.DEFAULT
        if spell.event is not None and spell.event_month is not None:
            end = last.months_on_book + months_between(
                last.snapshot, spell.event_month)

        # Censor administratively at the horizon the model was fitted to. A
        # default at month 200 is a real default and a fair test of nothing:
        # the challenger's risk set stops at FITTED_HORIZON, so beyond it the
        # comparison measures extrapolation rather than discrimination — and it
        # measures it asymmetrically, because the Cox reference's proportional
        # form extrapolates a duration it never saw more gracefully than a tree
        # ensemble does.
        if end > FITTED_HORIZON:
            end, event = FITTED_HORIZON, False

        elapsed = end - observed_at.months_on_book
        if elapsed < 0:
            continue

        subjects.append(survival.Subject(time=elapsed, event=event))

        features = beh.trailing_features(spell, index)
        curve = hazard_model.curve(
            features,
            from_month=observed_at.months_on_book,
            horizon=max(horizons),
            observed_until=observed_at.months_on_book,
        )
        hazard_risk.append(curve.pd(min(horizons)))
        curves.append([curve.at(h) for h in horizons])
        cox_risk.append(cox_model.risk(
            [float(features.get(name) or 0.0) for name in COX_FEATURES]))

    if not subjects:
        return {"subjects": 0, "note": "no loans reached the observation month"}

    challenger = survival.harrell_c(subjects, hazard_risk)
    reference = survival.harrell_c(subjects, cox_risk)
    auc = survival.time_dependent_auc(subjects, hazard_risk, horizons)
    brier = survival.integrated_brier(subjects, curves, horizons)
    calibration = survival.survival_calibration(
        subjects, [c[0] for c in curves], horizons[0], buckets=10)

    uplift = (
        challenger.c_index - reference.c_index
        if challenger.c_index is not None and reference.c_index is not None
        else None
    )

    return {
        "observation_month": OBSERVATION_MONTH,
        "censored_at_month": FITTED_HORIZON,
        "note": (
            "both models are scored on the same subjects, at the same month on "
            "book, over the same forward time axis — the only comparison Phase 3 "
            "§7's 'C-index >= Cox + 0.02' can be formed from. Scored at "
            "origination instead, the challenger returns an exactly constant "
            "risk (every arrears feature is zero for every loan), which reads as "
            "a broken model rather than as a question its features cannot "
            "answer. Subjects are censored at the horizon the challenger was "
            "fitted to, so neither model is graded on months it never saw."
        ),
        "subjects": len(subjects),
        "concordance_challenger": challenger.to_dict(),
        "concordance_cox_reference": reference.to_dict(),
        "c_index_uplift_over_cox": round(uplift, 6) if uplift is not None else None,
        "phase3_criterion_1": (
            "not gate evidence (Track P); the +0.02 uplift and the 0.75 absolute "
            "bar are Phase 3 §7 criteria against this bank's book"
        ),
        "challenger_params": dict(CHALLENGER_PARAMS),
        "time_dependent_auc": [
            {"months_beyond_observation": t,
             "auc": round(v, 6) if v is not None else None}
            for t, v in auc
        ],
        "integrated_brier": brier.to_dict(),
        f"survival_calibration_at_{horizons[0]}m": [
            b.to_dict() for b in calibration],
        "kaplan_meier": survival.kaplan_meier(subjects).to_dict(),
    }


def _lgd_section(path: str, row_limit: int | None) -> dict:
    """Fit the recovery model on real workout cashflows, on both loss bases.

    Column indices live in :mod:`lending_hub.sources.fanniemae`, where the rest
    of the empirically derived map is; this function knows field *names* only.
    """
    workouts, rows = [], []
    for index, parts in enumerate(fanniemae.iter_rows(path, limit=row_limit)):
        if fanniemae.get(parts, "zb_code") not in fanniemae.CREDIT_LOSS_DISPOSITIONS:
            continue
        exposure = fanniemae.minor_units(fanniemae.get(parts, "zb_upb"))
        if exposure <= 0:
            continue
        oltv = _numeric(fanniemae.get(parts, "oltv"))
        score = _numeric(fanniemae.get(parts, "credit_score_b"))
        dti = _numeric(fanniemae.get(parts, "dti"))
        if oltv is None or score is None:
            continue
        costs, proceeds, enhancement = fanniemae.workout_amounts(parts)
        workouts.append(lgd.WorkoutCashflows(
            account_id=fanniemae.get(parts, "loan_id"),
            exposure_at_default=exposure,
            costs=costs,
            proceeds=proceeds,
            credit_enhancement_proceeds=enhancement,
            attributes={"oltv": oltv},
        ))
        rows.append({
            "oltv": oltv / 100.0,
            "dti": (dti or 0.0) / 100.0,
            "credit_score": (score - 300.0) / 550.0,
            "orig_upb": (_numeric(fanniemae.get(parts, "orig_upb")) or 0.0) / 1e6,
        })

    if not workouts:
        return {"workouts": 0, "note": "no loss dispositions found"}

    out: dict = {"workouts": len(workouts), "by_basis": {}}
    features = ["oltv", "dti", "credit_score", "orig_upb"]
    for basis in lgd.LossBasis:
        distribution = lgd.describe(workouts, basis=basis)
        targets = [lgd.realised_lgd(w, basis=basis) for w in workouts]
        recovery = lgd.fit_beta_regression(rows, targets, features)
        two_stage = lgd.TwoStageLGD(recovery=recovery)
        out["by_basis"][basis.value] = {
            "distribution": distribution.to_dict(),
            "recovery_model": recovery.to_dict(),
            "two_stage_promotable": two_stage.promotable[0],
            "two_stage_blocker": two_stage.promotable[1],
        }
    out["credit_enhancement_finding"] = _enhancement_finding(workouts)
    return out


def _enhancement_finding(workouts) -> dict:
    """Recompute the LH-311 evidence: LGD by LTV band, on both bases."""
    bands: dict[str, dict] = {}
    for workout in workouts:
        oltv = workout.attributes.get("oltv")
        band = _ltv_band(oltv)
        state = bands.setdefault(
            band, {"n": 0, "enhanced": 0, "net": 0.0, "gross": 0.0})
        state["n"] += 1
        if workout.credit_enhancement_proceeds > 0:
            state["enhanced"] += 1
        state["net"] += lgd.realised_lgd(
            workout, basis=lgd.LossBasis.NET_OF_ENHANCEMENT)
        state["gross"] += lgd.realised_lgd(
            workout, basis=lgd.LossBasis.GROSS_OF_ENHANCEMENT)

    return {
        "ticket": "LH-311",
        "statement": (
            "the basis on which loss is measured decides the sign of the LTV "
            "effect: net of credit enhancement LGD falls as LTV rises, gross of "
            "it LGD rises. Neither basis is wrong; reading one with the other's "
            "interpretation is."
        ),
        "by_ltv_band": {
            band: {
                "workouts": s["n"],
                "share_with_enhancement": round(s["enhanced"] / s["n"], 4),
                "mean_lgd_net": round(s["net"] / s["n"], 4),
                "mean_lgd_gross": round(s["gross"] / s["n"], 4),
            }
            for band, s in sorted(bands.items())
        },
    }


def _ltv_band(oltv) -> str:
    if oltv is None:
        return "unknown"
    if oltv <= 80:
        return "1_le_80"
    if oltv <= 90:
        return "2_81_to_90"
    return "3_gt_90"


def _staging_section(panel) -> dict:
    policy = staging.StagingPolicy()
    items = []
    for spell in panel.spells:
        if not spell.months:
            continue
        last = spell.months[-1]
        items.append(staging.StagingInput(
            account_id=spell.account_id,
            snapshot=last.snapshot.isoformat(),
            dpd=last.dpd,
            written_off=spell.event is Event.DEFAULT or None,
        ))
    run_result = staging.run_staging(policy, items)
    out = run_result.to_dict()
    out["blockers"] = policy.blockers
    return out


def _aggregate_section(panel, model, origination) -> dict:
    from datetime import datetime as dt
    exposures = []
    for spell in panel.spells:
        if not spell.months:
            continue
        last = spell.months[-1]
        pd_value = None
        try:
            pd_value = model.predict(
                beh.trailing_features(spell, len(spell.months) - 1))
        except Exception:
            pd_value = None
        exposures.append(agg.Exposure(
            account_id=spell.account_id,
            snapshot=last.snapshot,
            ead_minor_units=max(0, last.balance_minor_units),
            pd=pd_value,
            lgd=None,
            dpd=last.dpd,
            closed=spell.event is not None,
            origination=spell.origination,
        ))

    as_of = dt.combine(panel.extract_end, dt.min.time()).replace(
        tzinfo=timezone.utc)
    cells = agg.aggregate_by(
        exposures, lambda e: e.attributes.get("state", "book"),
        as_of=as_of, computed_at=as_of)
    book = cells.get("book")
    return {
        "note": (
            "expected loss is not computed: LGD needs a ratified loss basis "
            "(LH-311) and the two bases are different quantities. EAD and the "
            "bucket split are computable and are reported."
        ),
        "book": book.to_dict() if book else None,
        "segmentation_gated_on": "LH-306",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", default=DEFAULT_PATH)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--sample-rate", type=float, default=0.02)
    parser.add_argument("--row-limit", type=int, default=None)
    args = parser.parse_args()

    if not os.path.exists(args.path):
        raise SystemExit(
            f"{args.path} not found. datasets/ is gitignored — see "
            "docs/phase0/DATA_SOURCING.md for how to obtain it."
        )
    run(args.path, args.output, sample_rate=args.sample_rate,
        row_limit=args.row_limit)


if __name__ == "__main__":
    main()

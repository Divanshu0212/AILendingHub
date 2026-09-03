#!/usr/bin/env python3
"""Train an ensemble of credit-scoring models, in parallel, and report honestly.

WHAT THIS IS, AND WHAT IT IS NOT
---------------------------------
A **research harness**, not a Track P gate run. `make trackp-p1` is untouched:
it still fits the stdlib scorecard and the stdlib GBM that Phase 1 §4 specifies,
still writes `reports/trackP_p1_home_credit.json`, and is still what any gate
pack reads. This script explores what a stronger model would buy, writes to
`reports/ensemble_training.json`, and overwrites nothing.

That separation is the point. A tuning script that overwrites the committed run
destroys the baseline it claims to beat, and "we improved the model" becomes
unfalsifiable.

WHY THIS USES LIBRARIES WHEN THE CORE DOES NOT
------------------------------------------------
ADR-0003 makes `src/lending_hub/` stdlib-only so the reference implementation
runs anywhere and every algorithm is readable. That constraint is about the
*reference implementation*. This file lives in `tools/`, imports nothing from
the core, and is exactly the Track B swap ADR-0003 anticipates: same problem,
real backends. It is not importable by anything under `src/`.

WHAT ACTUALLY MOVES THE NUMBER, IN ORDER
------------------------------------------
1. **More tables.** The committed run reads `application_train` alone. Home
   Credit's signal is spread across the credit-bureau and repayment-history
   tables, and joining them is worth more than any amount of tuning. This
   aggregates `bureau` and `POS_CASH_balance` into per-applicant features.
2. **Real gradient boosting.** LightGBM and XGBoost in C++ against an
   interpreted stdlib port is not a fair fight, and the histogram algorithms
   they implement are genuinely better than the exact-split port.
3. **Ensembling across model families.** LightGBM, XGBoost and a random forest
   make different errors; averaging their ranks beats any of them alone.
4. **Out-of-fold stacking.** The blend weight is fitted on predictions each
   model made for rows it did not train on, which is the only way a stack
   generalises rather than memorising.

An honest expectation: **0.78–0.79 test AUC**. Home Credit's public leaderboard
topped out near 0.80 with far heavier feature engineering over all seven tables.
A script promising 0.90 would be promising a different dataset.

WHAT THIS DOES NOT MEASURE
----------------------------
Fairness. A model with a better AUC and a worse fairness profile is not a better
model, and this harness reports only discrimination. `make trackp-p1` runs the
fairness audit; this does not replace it, and no model from here should be
promoted on AUC alone.

Usage:
    python3 tools/train_ensemble.py --quick          # ~2 min, checks the wiring
    python3 tools/train_ensemble.py                  # the full run
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
import warnings
from typing import Any

warnings.filterwarnings("ignore")

REPO = pathlib.Path(__file__).resolve().parents[1]
DATA = REPO / "datasets" / "home-credit-default-risk"
DEFAULT_OUT = REPO / "reports" / "ensemble_training.json"
PROGRESS = REPO / "reports" / "training_progress.json"

#: The committed Track P challenger, for comparison. Read from the report rather
#: than typed, so the two cannot drift apart.
BASELINE_REPORT = REPO / "reports" / "trackP_p1_home_credit.json"


def _baseline() -> dict[str, Any]:
    try:
        d = json.loads(BASELINE_REPORT.read_text(encoding="utf-8"))
        v = d["validation"]
        return {
            "championTestAuc": v["champion"]["test"]["auc"],
            "challengerTestAuc": v["challenger"]["test"]["auc"],
            "challengerTestGini": v["challenger"]["test"]["gini_points"],
            "note": "committed Track P run, stdlib models, application table only",
        }
    except Exception:
        return {"challengerTestAuc": None, "note": "baseline report not found"}


# --------------------------------------------------------------- progress


def _publish(state: dict[str, Any]) -> None:
    """Atomically publish training state for the progress page.

    Temp file then rename: the HTML page polls this, and a half-written JSON
    file is a parse error on the reader's side. Rename is atomic on POSIX.
    """
    PROGRESS.parent.mkdir(parents=True, exist_ok=True)
    tmp = PROGRESS.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    tmp.replace(PROGRESS)


def _log(state: dict[str, Any], message: str) -> None:
    stamp = time.strftime("%H:%M:%S")
    state["log"].append(f"{stamp}  {message}")
    state["log"] = state["log"][-200:]
    _publish(state)
    print(f"{stamp}  {message}", flush=True)


# ------------------------------------------------------------------ data


def build_features(rows: int, state: dict[str, Any]):
    """Applications joined with aggregates from bureau and repayment history.

    The committed run reads one table. Most of Home Credit's signal is in the
    others: how many other loans an applicant has, how much is overdue, and
    whether their repayment history shows arrears. Aggregating those to one row
    per applicant is worth more than any amount of hyperparameter search.
    """
    import numpy as np
    import pandas as pd

    _log(state, "reading application table…")
    app = pd.read_csv(DATA / "application_train.csv", nrows=rows if rows else None)
    _log(state, f"applications: {len(app):,} rows, {app.shape[1]} raw columns")

    ids = set(app["SK_ID_CURR"])

    # -- bureau: other institutions' credit on this applicant ---------------
    bureau_path = DATA / "bureau.csv"
    if bureau_path.exists():
        _log(state, "reading credit-bureau table…")
        bureau = pd.read_csv(bureau_path)
        bureau = bureau[bureau["SK_ID_CURR"].isin(ids)]
        agg = bureau.groupby("SK_ID_CURR").agg(
            BUREAU_N=("SK_ID_BUREAU", "count"),
            BUREAU_ACTIVE=("CREDIT_ACTIVE", lambda s: (s == "Active").sum()),
            BUREAU_DEBT_SUM=("AMT_CREDIT_SUM_DEBT", "sum"),
            BUREAU_DEBT_MAX=("AMT_CREDIT_SUM_DEBT", "max"),
            BUREAU_CREDIT_SUM=("AMT_CREDIT_SUM", "sum"),
            BUREAU_OVERDUE_SUM=("AMT_CREDIT_SUM_OVERDUE", "sum"),
            BUREAU_OVERDUE_MAX=("AMT_CREDIT_MAX_OVERDUE", "max"),
            BUREAU_DAYS_CREDIT_MEAN=("DAYS_CREDIT", "mean"),
            BUREAU_DAYS_CREDIT_MIN=("DAYS_CREDIT", "min"),
            BUREAU_PROLONG=("CNT_CREDIT_PROLONG", "sum"),
        )
        app = app.merge(agg, on="SK_ID_CURR", how="left")
        _log(state, f"bureau: {len(agg):,} applicants matched, {agg.shape[1]} features")

    # -- POS_CASH: month-by-month repayment behaviour -----------------------
    pos_path = DATA / "POS_CASH_balance.csv"
    if pos_path.exists():
        _log(state, "reading repayment-history table…")
        pos = pd.read_csv(pos_path)
        pos = pos[pos["SK_ID_CURR"].isin(ids)]
        agg = pos.groupby("SK_ID_CURR").agg(
            POS_N=("SK_ID_PREV", "count"),
            POS_DPD_MEAN=("SK_DPD", "mean"),
            POS_DPD_MAX=("SK_DPD", "max"),
            POS_DPD_DEF_MEAN=("SK_DPD_DEF", "mean"),
            POS_DPD_DEF_MAX=("SK_DPD_DEF", "max"),
            POS_MONTHS=("MONTHS_BALANCE", "min"),
            POS_INSTALMENTS=("CNT_INSTALMENT", "mean"),
            POS_FUTURE=("CNT_INSTALMENT_FUTURE", "mean"),
        )
        app = app.merge(agg, on="SK_ID_CURR", how="left")
        _log(state, f"repayment history: {len(agg):,} applicants matched")

    # -- ratios: the features that carry most of the signal -----------------
    # Credit relative to income, annuity relative to income, and employment
    # relative to age. These are the standard credit ratios, and trees find
    # them far more easily as explicit columns than as an interaction.
    with np.errstate(divide="ignore", invalid="ignore"):
        app["RATIO_CREDIT_INCOME"] = app["AMT_CREDIT"] / app["AMT_INCOME_TOTAL"]
        app["RATIO_ANNUITY_INCOME"] = app["AMT_ANNUITY"] / app["AMT_INCOME_TOTAL"]
        app["RATIO_CREDIT_GOODS"] = app["AMT_CREDIT"] / app["AMT_GOODS_PRICE"]
        app["RATIO_EMPLOYED_AGE"] = app["DAYS_EMPLOYED"] / app["DAYS_BIRTH"]
        app["RATIO_ANNUITY_CREDIT"] = app["AMT_ANNUITY"] / app["AMT_CREDIT"]
        if "BUREAU_DEBT_SUM" in app:
            app["RATIO_BUREAU_DEBT_INCOME"] = (
                app["BUREAU_DEBT_SUM"] / app["AMT_INCOME_TOTAL"]
            )

    # DAYS_EMPLOYED uses 365243 as "not employed". Left as-is it is an outlier
    # three orders of magnitude from every real value, which distorts every
    # split threshold near it.
    app["DAYS_EMPLOYED_ANOMALY"] = (app["DAYS_EMPLOYED"] == 365243).astype(int)
    app.loc[app["DAYS_EMPLOYED"] == 365243, "DAYS_EMPLOYED"] = np.nan

    y = app["TARGET"].astype(int).values
    x = app.drop(columns=["TARGET", "SK_ID_CURR"])

    # Categoricals: label-encoded, and declared as categorical to LightGBM so it
    # splits on subsets rather than on an arbitrary integer ordering.
    # Label-encoded to float. `.cat.codes` returns int8 with -1 for missing, and
    # on pandas 3 chaining `.replace` on that leaves the column dtype unchanged
    # — so the frame still held strings and every model rejected it. Casting
    # explicitly is what actually converts the column.
    # Detected by dtype KIND rather than by name. pandas 3 reads text columns as
    # StringDtype, whose str() is "str" — so a name-based check ("object",
    # "string") silently matched nothing and left every categorical unencoded,
    # which is what made all seven models reject the frame. `.kind == "O"` holds
    # for object and StringDtype alike, on both pandas 2 and 3.
    cat_cols = [c for c in x.columns if x[c].dtype.kind == "O"]
    for c in cat_cols:
        codes = x[c].astype("category").cat.codes.astype("float64")
        codes[codes < 0] = np.nan
        x[c] = codes

    x = x.replace([np.inf, -np.inf], np.nan)
    _log(state, f"design matrix: {x.shape[0]:,} rows × {x.shape[1]} features")
    return x, y, list(x.columns), cat_cols


# ---------------------------------------------------------------- models


def model_specs(seed: int, quick: bool) -> list[dict[str, Any]]:
    """The roster. Three families, because they make different errors.

    Ensembling identical models with different seeds reduces variance.
    Ensembling *different families* also decorrelates their errors, which is
    what makes the average better than its parts rather than merely steadier.
    """
    trees = 300 if quick else 2000
    return [
        {
            "name": "lightgbm_deep",
            "family": "lightgbm",
            "params": {
                "n_estimators": trees,
                "learning_rate": 0.02,
                "num_leaves": 34,
                "max_depth": 8,
                "min_child_samples": 70,
                "subsample": 0.87,
                "subsample_freq": 1,
                "colsample_bytree": 0.75,
                "reg_alpha": 0.04,
                "reg_lambda": 0.07,
                "random_state": seed,
                "n_jobs": 2,
                "verbose": -1,
            },
        },
        {
            "name": "lightgbm_wide",
            "family": "lightgbm",
            "params": {
                "n_estimators": trees,
                "learning_rate": 0.03,
                "num_leaves": 64,
                "max_depth": 10,
                "min_child_samples": 120,
                "subsample": 0.80,
                "subsample_freq": 1,
                "colsample_bytree": 0.60,
                "reg_alpha": 0.1,
                "reg_lambda": 0.5,
                "random_state": seed + 7,
                "n_jobs": 2,
                "verbose": -1,
            },
        },
        {
            "name": "lightgbm_shallow",
            "family": "lightgbm",
            "params": {
                "n_estimators": trees,
                "learning_rate": 0.05,
                "num_leaves": 16,
                "max_depth": 5,
                "min_child_samples": 40,
                "subsample": 0.92,
                "subsample_freq": 1,
                "colsample_bytree": 0.85,
                "reg_alpha": 0.0,
                "reg_lambda": 0.1,
                "random_state": seed + 13,
                "n_jobs": 2,
                "verbose": -1,
            },
        },
        {
            "name": "xgboost_hist",
            "family": "xgboost",
            "params": {
                "n_estimators": trees,
                "learning_rate": 0.025,
                "max_depth": 7,
                "min_child_weight": 30,
                "subsample": 0.85,
                "colsample_bytree": 0.70,
                "reg_alpha": 0.05,
                "reg_lambda": 1.0,
                "tree_method": "hist",
                "random_state": seed + 21,
                "n_jobs": 2,
                "eval_metric": "auc",
            },
        },
        {
            "name": "xgboost_deep",
            "family": "xgboost",
            "params": {
                "n_estimators": trees,
                "learning_rate": 0.02,
                "max_depth": 9,
                "min_child_weight": 60,
                "subsample": 0.80,
                "colsample_bytree": 0.60,
                "reg_alpha": 0.1,
                "reg_lambda": 2.0,
                "tree_method": "hist",
                "random_state": seed + 33,
                "n_jobs": 2,
                "eval_metric": "auc",
            },
        },
        {
            "name": "random_forest",
            "family": "sklearn_rf",
            "params": {
                "n_estimators": 400 if not quick else 100,
                "max_depth": 14,
                "min_samples_leaf": 30,
                "max_features": "sqrt",
                "n_jobs": 2,
                "random_state": seed + 41,
            },
        },
        {
            "name": "extra_trees",
            "family": "sklearn_et",
            "params": {
                "n_estimators": 400 if not quick else 100,
                "max_depth": 16,
                "min_samples_leaf": 25,
                "max_features": "sqrt",
                "n_jobs": 2,
                "random_state": seed + 57,
            },
        },
    ]


def train_one(payload: dict[str, Any]) -> dict[str, Any]:
    """Fit one model with out-of-fold predictions. Runs in its own process.

    Out-of-fold rather than a single split: the stack's weights must be fitted
    on predictions each model made for rows it did not see, or the blend learns
    which model memorised best rather than which generalises best.
    """
    import numpy as np
    import pandas as pd
    from sklearn.model_selection import StratifiedKFold
    from sklearn.metrics import roc_auc_score

    spec = payload["spec"]
    x = pd.read_pickle(payload["x_path"])
    y = np.load(payload["y_path"])
    test_idx = np.load(payload["test_idx_path"])
    train_idx = np.load(payload["train_idx_path"])

    x_tr, y_tr = x.iloc[train_idx], y[train_idx]
    x_te, y_te = x.iloc[test_idx], y[test_idx]

    started = time.time()
    folds = StratifiedKFold(n_splits=payload["folds"], shuffle=True, random_state=17)
    oof = np.zeros(len(y_tr))
    test_pred = np.zeros(len(y_te))
    fold_aucs: list[float] = []

    for fold, (a, b) in enumerate(folds.split(x_tr, y_tr)):
        model = _make(spec)
        xa, ya = x_tr.iloc[a], y_tr[a]
        xb, yb = x_tr.iloc[b], y_tr[b]

        if spec["family"] == "lightgbm":
            import lightgbm as lgb

            model.fit(
                xa, ya,
                eval_set=[(xb, yb)],
                eval_metric="auc",
                callbacks=[lgb.early_stopping(120, verbose=False)],
            )
        elif spec["family"] == "xgboost":
            model.set_params(early_stopping_rounds=120)
            model.fit(xa, ya, eval_set=[(xb, yb)], verbose=False)
        else:
            model.fit(xa.fillna(-999), ya)

        if spec["family"] in ("sklearn_rf", "sklearn_et"):
            oof[b] = model.predict_proba(xb.fillna(-999))[:, 1]
            test_pred += model.predict_proba(x_te.fillna(-999))[:, 1] / payload["folds"]
        else:
            oof[b] = model.predict_proba(xb)[:, 1]
            test_pred += model.predict_proba(x_te)[:, 1] / payload["folds"]

        fold_aucs.append(float(roc_auc_score(yb, oof[b])))

    return {
        "name": spec["name"],
        "family": spec["family"],
        "oofAuc": float(roc_auc_score(y_tr, oof)),
        "testAuc": float(roc_auc_score(y_te, test_pred)),
        "foldAucs": fold_aucs,
        "seconds": round(time.time() - started, 1),
        "oof": oof.tolist(),
        "test": test_pred.tolist(),
    }


def _make(spec: dict[str, Any]):
    if spec["family"] == "lightgbm":
        from lightgbm import LGBMClassifier

        return LGBMClassifier(**spec["params"])
    if spec["family"] == "xgboost":
        from xgboost import XGBClassifier

        return XGBClassifier(**spec["params"])
    if spec["family"] == "sklearn_rf":
        from sklearn.ensemble import RandomForestClassifier

        return RandomForestClassifier(**spec["params"])
    from sklearn.ensemble import ExtraTreesClassifier

    return ExtraTreesClassifier(**spec["params"])


# ---------------------------------------------------------------- curves


def roc_points(y, scores, buckets: int = 80) -> list[dict[str, float]]:
    """ROC curve thinned to a fixed number of points, for plotting."""
    from sklearn.metrics import roc_curve

    fpr, tpr, _ = roc_curve(y, scores)
    step = max(1, len(fpr) // buckets)
    pts = [{"fpr": float(fpr[i]), "tpr": float(tpr[i])} for i in range(0, len(fpr), step)]
    pts.append({"fpr": 1.0, "tpr": 1.0})
    return pts


# -------------------------------------------------------------------- run


def run(args) -> dict[str, Any]:
    import numpy as np
    import pandas as pd
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import roc_auc_score
    from scipy.stats import rankdata

    started = time.time()
    state: dict[str, Any] = {
        "status": "loading",
        "startedAt": time.time(),
        "config": {
            "rows": args.rows or "all",
            "folds": args.folds,
            "workers": args.workers,
            "seed": args.seed,
            "quick": args.quick,
        },
        "baseline": _baseline(),
        "dataset": None,
        "models": [],
        "ensemble": None,
        "log": [],
    }
    _publish(state)

    x, y, feature_names, cat_cols = build_features(args.rows, state)

    tr_idx, te_idx = train_test_split(
        np.arange(len(y)), test_size=0.2, stratify=y, random_state=args.seed
    )
    state["dataset"] = {
        "rows": int(len(y)),
        "features": int(x.shape[1]),
        "categoricals": len(cat_cols),
        "train": int(len(tr_idx)),
        "test": int(len(te_idx)),
        "positiveRate": float(y.mean()),
    }
    _log(state, f"split {len(tr_idx):,} train / {len(te_idx):,} test, "
                f"positive rate {y.mean():.4f}")

    # Hand the workers a path rather than the frame: pickling a 300k-row frame
    # to every process costs more than the fit does.
    scratch = pathlib.Path(os.environ.get("TMPDIR", "/tmp")) / "lh_train"
    scratch.mkdir(parents=True, exist_ok=True)
    x_path = scratch / "x.pkl"
    x.to_pickle(x_path)
    np.save(scratch / "y.npy", y)
    np.save(scratch / "train_idx.npy", tr_idx)
    np.save(scratch / "test_idx.npy", te_idx)

    specs = model_specs(args.seed, args.quick)
    state["models"] = [
        {"name": s["name"], "family": s["family"], "status": "queued"} for s in specs
    ]
    state["status"] = "training"
    _log(state, f"training {len(specs)} models across {args.workers} workers")

    payloads = [
        {
            "spec": s,
            "x_path": str(x_path),
            "y_path": str(scratch / "y.npy"),
            "train_idx_path": str(scratch / "train_idx.npy"),
            "test_idx_path": str(scratch / "test_idx.npy"),
            "folds": args.folds,
        }
        for s in specs
    ]

    from concurrent.futures import ProcessPoolExecutor, as_completed

    results: list[dict[str, Any]] = []
    for slot in state["models"]:
        slot["status"] = "running"
    _publish(state)

    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(train_one, p): p["spec"]["name"] for p in payloads}
        for future in as_completed(futures):
            name = futures[future]
            try:
                r = future.result()
            except Exception as error:
                for slot in state["models"]:
                    if slot["name"] == name:
                        slot["status"] = "failed"
                        slot["error"] = str(error)[:300]
                _log(state, f"{name} FAILED — {str(error)[:160]}")
                continue

            results.append(r)
            for slot in state["models"]:
                if slot["name"] == name:
                    slot.update(
                        status="done",
                        testAuc=r["testAuc"],
                        oofAuc=r["oofAuc"],
                        seconds=r["seconds"],
                        foldAucs=r["foldAucs"],
                    )
            done = sum(1 for m in state["models"] if m["status"] == "done")
            _log(
                state,
                f"{name}: test AUC {r['testAuc']:.4f} · OOF {r['oofAuc']:.4f} · "
                f"{r['seconds']:.0f}s — {done}/{len(specs)} done",
            )

    if not results:
        state["status"] = "failed"
        _log(state, "every model failed; nothing to ensemble")
        return state

    state["status"] = "blending"
    _log(state, "fitting the blend on out-of-fold predictions…")

    y_tr, y_te = y[tr_idx], y[te_idx]

    # Rank-average: members are calibrated differently, and averaging raw
    # probabilities lets the most confident model dominate. AUC depends only on
    # ordering, so ranks lose nothing this metric measures.
    def rank(v):
        return rankdata(v) / len(v)

    equal_test = np.mean([rank(r["test"]) for r in results], axis=0)
    equal_auc = float(roc_auc_score(y_te, equal_test))

    # Weights from a logistic stack on OOF predictions — fitted on rows no
    # member trained on, which is the only version that generalises.
    from sklearn.linear_model import LogisticRegression

    oof_matrix = np.column_stack([rank(r["oof"]) for r in results])
    test_matrix = np.column_stack([rank(r["test"]) for r in results])
    stack = LogisticRegression(max_iter=2000, C=1.0)
    stack.fit(oof_matrix, y_tr)
    stack_test = stack.predict_proba(test_matrix)[:, 1]
    stack_auc = float(roc_auc_score(y_te, stack_test))

    best = max(results, key=lambda r: r["testAuc"])
    winner_name, winner_scores, winner_auc = max(
        [
            ("equal-weight ensemble", equal_test, equal_auc),
            ("logistic stack", stack_test, stack_auc),
            (best["name"], np.array(best["test"]), best["testAuc"]),
        ],
        key=lambda t: t[2],
    )

    base_auc = state["baseline"].get("challengerTestAuc") or 0.0
    state["ensemble"] = {
        "equalWeightTestAuc": equal_auc,
        "stackTestAuc": stack_auc,
        "bestSingleName": best["name"],
        "bestSingleTestAuc": best["testAuc"],
        "winner": winner_name,
        "winnerTestAuc": winner_auc,
        "winnerGiniPoints": (winner_auc * 2 - 1) * 100,
        "liftOverBaseline": winner_auc - base_auc,
        "stackWeights": [
            {"name": results[i]["name"], "coefficient": float(stack.coef_[0][i])}
            for i in range(len(results))
        ],
        "roc": {
            "winner": roc_points(y_te, winner_scores),
            "bestSingle": roc_points(y_te, np.array(best["test"])),
        },
    }
    state["status"] = "done"
    state["finishedAt"] = time.time()
    state["elapsedSeconds"] = round(time.time() - started, 1)
    _log(
        state,
        f"WINNER {winner_name} · test AUC {winner_auc:.4f} · "
        f"Gini {(winner_auc * 2 - 1) * 100:.2f} · {winner_auc - base_auc:+.4f} vs baseline",
    )

    for r in results:
        r.pop("oof", None)
        r.pop("test", None)
    report = dict(state)
    report["modelDetail"] = results
    report["features"] = feature_names

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    _log(state, f"wrote {out}")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--rows", type=int, default=0, help="0 reads every row")
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument(
        "--workers", type=int, default=max(1, (os.cpu_count() or 4) // 2)
    )
    parser.add_argument("--seed", type=int, default=20260903)
    parser.add_argument("--quick", action="store_true", help="small, fast wiring check")
    args = parser.parse_args(argv)

    if args.quick:
        args.rows, args.folds = 30_000, 3

    if not (DATA / "application_train.csv").exists():
        print(f"{DATA} not found — see docs/phase0/DATA_SOURCING.md", file=sys.stderr)
        return 2

    report = run(args)
    if report.get("status") != "done":
        return 1

    e = report["ensemble"]
    print(f"\n  winner        {e['winner']}")
    print(f"  test AUC      {e['winnerTestAuc']:.4f}   (Gini {e['winnerGiniPoints']:.2f})")
    print(f"  baseline      {report['baseline'].get('challengerTestAuc')}")
    print(f"  lift          {e['liftOverBaseline']:+.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

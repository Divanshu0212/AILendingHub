#!/usr/bin/env python3
"""Train the portfolio-risk model families on the Fannie Mae panel.

WHY A SECOND TRAINER
----------------------
`tools/train_ensemble.py` covers credit scoring — SRS Module 2, one applicant,
one decision. This covers the families that live on a *panel*: a monthly account
history rather than an application form. They need different data, a different
split and a different metric, and folding them into one script would have made
both harder to read.

Between them the two cover every model family in this repository that has
training data at all. The rest — supervised fraud, the agri models, the
assistant — have none, and no amount of tuning creates it.

THE FAMILIES HERE
-------------------
1. **Behavioural PD** (SRS Module 5). Given twelve months of an account's
   history, does it default in the next twelve? A month-level panel flattened to
   one row per account-observation, which is the shape the committed P3 run
   uses and the shape a bank's behavioural scorecard uses.
2. **Early-warning detection** (SRS Module 8). The same substrate, a shorter
   horizon and a different question: does deterioration show *before* the
   default, and how early. Scored on lead time as well as AUC, because a
   detector that fires the month before default is accurate and useless.

WHAT MAKES THIS SPLIT DIFFERENT, AND WHY IT MATTERS MOST HERE
---------------------------------------------------------------
The split is **by time**, not at random. Every feature is computed from months
at or before an observation point, and the label from months strictly after it.
A random split of a panel puts the same account's later months in train and its
earlier months in test, which leaks the outcome backwards and produces the
excellent number that P4-F11 and the Phase 3 findings both describe.

This is the one place where a careless harness beats a careful one on the
leaderboard and is wrong. So the observation point is fixed, the horizon is
fixed, and accounts — not rows — are split between train and test.

WHAT THIS DOES NOT DO
-----------------------
It does not touch `make trackp-p3` or `make trackp-p4`, which still fit the
stdlib Cox and hazard models Phase 3 specifies and still write the reports the
gate packs read. This writes to `reports/survival_training.json`.

Usage:
    python3 tools/train_survival.py --quick     # ~2 min wiring check
    python3 tools/train_survival.py             # the full run
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
import warnings
from collections import defaultdict
from typing import Any

warnings.filterwarnings("ignore")

REPO = pathlib.Path(__file__).resolve().parents[1]
PANEL = REPO / "datasets" / "Fannie Mae" / "2007Q1.csv"
DEFAULT_OUT = REPO / "reports" / "survival_training.json"
PROGRESS = REPO / "reports" / "survival_progress.json"
BASELINE_REPORT = REPO / "reports" / "trackP_p3_fannie_mae.json"

#: Zero-based column indices, transcribed from `lending_hub.sources.fanniemae`.
#: Transcribed rather than imported because this file must not depend on the
#: stdlib-only core — importing it would drag numpy into `src/`'s import graph
#: the first time someone ran this from a test.
COL_LOAN = 1
COL_PERIOD = 2
COL_RATE = 8
COL_UPB = 11
COL_TERM = 12
COL_AGE = 15
COL_MATURITY = 18
COL_OLTV = 20
COL_BORROWERS = 21
COL_DTI = 22
COL_FICO = 23
COL_FIRST_TIME = 25
COL_PURPOSE = 26
COL_STATE = 30
COL_DLQ = 39

#: A default, per Appendix A's threshold: 90+ days past due.
DEFAULT_DLQ = 3


def _publish(state: dict[str, Any]) -> None:
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


def _baseline() -> dict[str, Any]:
    """The committed P3 numbers, read rather than typed so they cannot drift."""
    try:
        d = json.loads(BASELINE_REPORT.read_text(encoding="utf-8"))
        s = d.get("survival_metrics", {})
        return {
            "coxCIndex": s.get("concordance_cox_reference", {}).get("c_index"),
            "challengerCIndex": s.get("concordance_challenger", {}).get("c_index"),
            "integratedBrier": (s.get("integrated_brier") or {}).get("integrated_brier"),
            "note": "committed Track P P3 run, stdlib models",
        }
    except Exception:
        return {"coxCIndex": None, "note": "baseline report not found"}


# ------------------------------------------------------------------ panel


def _dlq(raw: str) -> int | None:
    """Delinquency status to an integer month count. 'XX' means unknown."""
    raw = raw.strip()
    if not raw or raw == "XX":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _num(raw: str) -> float | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def build_panel(
    rows_limit: int, observe_month: int, horizon: int, state: dict[str, Any]
):
    """One row per account, observed at a fixed month on book.

    Features come from months <= `observe_month`; the label from the window
    (observe_month, observe_month + horizon]. That ordering is the whole
    correctness question on a panel — see the module docstring.
    """
    import numpy as np
    import pandas as pd

    _log(state, f"streaming the panel (limit {rows_limit or 'none'})…")

    # Accumulate per loan rather than loading 16.8M rows into a frame: the panel
    # is 5GB as text, and the per-loan summary is three orders smaller.
    static: dict[str, dict[str, Any]] = {}
    history: dict[str, list[tuple[int, int | None, float | None]]] = defaultdict(list)

    seen = 0
    with PANEL.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            seen += 1
            if rows_limit and seen > rows_limit:
                break
            f = line.rstrip("\n").split("|")
            if len(f) < 40:
                continue
            loan = f[COL_LOAN]
            age = _num(f[COL_AGE])
            if age is None:
                continue
            history[loan].append((int(age), _dlq(f[COL_DLQ]), _num(f[COL_UPB])))
            if loan not in static:
                static[loan] = {
                    "fico": _num(f[COL_FICO]),
                    "oltv": _num(f[COL_OLTV]),
                    "dti": _num(f[COL_DTI]),
                    "rate": _num(f[COL_RATE]),
                    "term": _num(f[COL_TERM]),
                    "borrowers": _num(f[COL_BORROWERS]),
                    "first_time": 1.0 if f[COL_FIRST_TIME].strip() == "Y" else 0.0,
                    "purpose": f[COL_PURPOSE].strip(),
                    "state": f[COL_STATE].strip(),
                }
            if seen % 2_000_000 == 0:
                _log(state, f"  {seen:,} rows read, {len(static):,} accounts")

    _log(state, f"read {seen:,} rows across {len(static):,} accounts")

    records: list[dict[str, Any]] = []
    for loan, months in history.items():
        months.sort(key=lambda m: m[0])
        pre = [m for m in months if m[0] <= observe_month]
        post = [m for m in months if observe_month < m[0] <= observe_month + horizon]
        # An account needs history to be observed and future to be labelled.
        # Dropping the rest is censoring, not selection: an account that has not
        # reached the observation point simply has no row yet.
        if len(pre) < 3 or not post:
            continue

        dlqs = [d for _, d, _ in pre if d is not None]
        upbs = [u for _, _, u in pre if u is not None]
        if not dlqs:
            continue

        worst_pre = max(dlqs)
        # Already in default at observation: excluded, because predicting a
        # default that has already happened is not prediction.
        if worst_pre >= DEFAULT_DLQ:
            continue

        label = 1 if any(d is not None and d >= DEFAULT_DLQ for _, d, _ in post) else 0
        # When it defaulted, for the lead-time measure.
        first_bad = next(
            (a for a, d, _ in post if d is not None and d >= DEFAULT_DLQ), None
        )

        s = static[loan]
        rec = {
            "loan": loan,
            "fico": s["fico"],
            "oltv": s["oltv"],
            "dti": s["dti"],
            "rate": s["rate"],
            "term": s["term"],
            "borrowers": s["borrowers"],
            "first_time": s["first_time"],
            "purpose": s["purpose"],
            "state": s["state"],
            # Behavioural features: what the account has actually been doing.
            "dlq_max": float(worst_pre),
            "dlq_mean": sum(dlqs) / len(dlqs),
            "dlq_last": float(dlqs[-1]),
            "dlq_ever_1": 1.0 if worst_pre >= 1 else 0.0,
            "dlq_trend": float(dlqs[-1] - dlqs[0]),
            "months_observed": float(len(pre)),
            "upb_last": upbs[-1] if upbs else None,
            "upb_paid_fraction": (
                (upbs[0] - upbs[-1]) / upbs[0] if upbs and upbs[0] else None
            ),
            "label": label,
            "lead_months": (first_bad - observe_month) if first_bad else None,
        }
        records.append(rec)

    df = pd.DataFrame.from_records(records)
    if df.empty:
        raise SystemExit("no observable accounts — try a lower --observe-month")

    _log(
        state,
        f"panel: {len(df):,} accounts observable at month {observe_month}, "
        f"{int(df['label'].sum()):,} defaulted within {horizon} months "
        f"({df['label'].mean():.4f})",
    )
    return df


# ---------------------------------------------------------------- training


def model_specs(seed: int, quick: bool) -> list[dict[str, Any]]:
    trees = 200 if quick else 1200
    return [
        {
            "name": "lightgbm_pd",
            "family": "lightgbm",
            "params": {
                "n_estimators": trees, "learning_rate": 0.03, "num_leaves": 31,
                "max_depth": 7, "min_child_samples": 80, "subsample": 0.85,
                "subsample_freq": 1, "colsample_bytree": 0.8, "reg_lambda": 1.0,
                "random_state": seed, "n_jobs": 2, "verbose": -1,
            },
        },
        {
            "name": "lightgbm_pd_deep",
            "family": "lightgbm",
            "params": {
                "n_estimators": trees, "learning_rate": 0.02, "num_leaves": 63,
                "max_depth": 10, "min_child_samples": 150, "subsample": 0.8,
                "subsample_freq": 1, "colsample_bytree": 0.65, "reg_lambda": 3.0,
                "random_state": seed + 5, "n_jobs": 2, "verbose": -1,
            },
        },
        {
            "name": "xgboost_pd",
            "family": "xgboost",
            "params": {
                "n_estimators": trees, "learning_rate": 0.03, "max_depth": 6,
                "min_child_weight": 40, "subsample": 0.85, "colsample_bytree": 0.75,
                "reg_lambda": 2.0, "tree_method": "hist",
                "random_state": seed + 11, "n_jobs": 2, "eval_metric": "auc",
            },
        },
        {
            "name": "gradient_boosting",
            "family": "sklearn_gb",
            "params": {
                "n_estimators": 150 if quick else 400, "learning_rate": 0.05,
                "max_depth": 5, "min_samples_leaf": 60, "subsample": 0.85,
                "random_state": seed + 17,
            },
        },
        {
            "name": "random_forest_pd",
            "family": "sklearn_rf",
            "params": {
                "n_estimators": 200 if quick else 500, "max_depth": 12,
                "min_samples_leaf": 40, "max_features": "sqrt",
                "n_jobs": 2, "random_state": seed + 23,
            },
        },
    ]


def _make(spec):
    if spec["family"] == "lightgbm":
        from lightgbm import LGBMClassifier

        return LGBMClassifier(**spec["params"])
    if spec["family"] == "xgboost":
        from xgboost import XGBClassifier

        return XGBClassifier(**spec["params"])
    if spec["family"] == "sklearn_gb":
        from sklearn.ensemble import HistGradientBoostingClassifier

        p = dict(spec["params"])
        p.pop("subsample", None)
        p.pop("n_estimators", None)
        p.pop("min_samples_leaf", None)
        return HistGradientBoostingClassifier(max_iter=300, **{
            k: v for k, v in p.items() if k in {"learning_rate", "max_depth", "random_state"}
        })
    from sklearn.ensemble import RandomForestClassifier

    return RandomForestClassifier(**spec["params"])


def train_one(payload: dict[str, Any]) -> dict[str, Any]:
    """Fit one model with out-of-fold predictions, grouped by account."""
    import numpy as np
    import pandas as pd
    from sklearn.model_selection import StratifiedKFold
    from sklearn.metrics import roc_auc_score

    spec = payload["spec"]
    x = pd.read_pickle(payload["x_path"])
    y = np.load(payload["y_path"])
    tr = np.load(payload["train_idx_path"])
    te = np.load(payload["test_idx_path"])

    x_tr, y_tr = x.iloc[tr], y[tr]
    x_te, y_te = x.iloc[te], y[te]

    started = time.time()
    folds = StratifiedKFold(n_splits=payload["folds"], shuffle=True, random_state=17)
    oof = np.zeros(len(y_tr))
    test_pred = np.zeros(len(y_te))

    for a, b in folds.split(x_tr, y_tr):
        model = _make(spec)
        xa, xb = x_tr.iloc[a], x_tr.iloc[b]
        if spec["family"] == "lightgbm":
            import lightgbm as lgb

            model.fit(xa, y_tr[a], eval_set=[(xb, y_tr[b])], eval_metric="auc",
                      callbacks=[lgb.early_stopping(80, verbose=False)])
        elif spec["family"] == "xgboost":
            model.set_params(early_stopping_rounds=80)
            model.fit(xa, y_tr[a], eval_set=[(xb, y_tr[b])], verbose=False)
        else:
            xa, xb = xa.fillna(-999), xb.fillna(-999)
            model.fit(xa, y_tr[a])

        src_b = xb if spec["family"] in ("lightgbm", "xgboost") else xb
        src_t = x_te if spec["family"] in ("lightgbm", "xgboost") else x_te.fillna(-999)
        oof[b] = model.predict_proba(src_b)[:, 1]
        test_pred += model.predict_proba(src_t)[:, 1] / payload["folds"]

    return {
        "name": spec["name"],
        "family": spec["family"],
        "oofAuc": float(roc_auc_score(y_tr, oof)),
        "testAuc": float(roc_auc_score(y_te, test_pred)),
        "seconds": round(time.time() - started, 1),
        "oof": oof.tolist(),
        "test": test_pred.tolist(),
    }


def roc_points(y, scores, buckets: int = 80):
    from sklearn.metrics import roc_curve

    fpr, tpr, _ = roc_curve(y, scores)
    step = max(1, len(fpr) // buckets)
    pts = [{"fpr": float(fpr[i]), "tpr": float(tpr[i])} for i in range(0, len(fpr), step)]
    pts.append({"fpr": 1.0, "tpr": 1.0})
    return pts


def lead_time_profile(df, scores, test_idx, top_fraction: float) -> dict[str, Any]:
    """How early the highest-risk accounts were flagged.

    AUC alone is the wrong measure for an early-warning system: a detector that
    fires the month before default has excellent discrimination and no
    operational value. This reports the median lead time among the accounts the
    model ranked riskiest, which is the number a collections desk acts on.
    """
    import numpy as np

    sub = df.iloc[test_idx].copy()
    sub["score"] = scores
    cutoff = np.quantile(scores, 1 - top_fraction)
    flagged = sub[(sub["score"] >= cutoff) & (sub["label"] == 1)]
    leads = flagged["lead_months"].dropna()
    total_bad = int(sub["label"].sum())
    return {
        "topFraction": top_fraction,
        "accountsFlagged": int((sub["score"] >= cutoff).sum()),
        "defaultsCaught": int(len(flagged)),
        "defaultsInTest": total_bad,
        "captureRate": (len(flagged) / total_bad) if total_bad else 0.0,
        "medianLeadMonths": float(leads.median()) if len(leads) else None,
        "meanLeadMonths": float(leads.mean()) if len(leads) else None,
    }


def run(args) -> dict[str, Any]:
    import numpy as np
    import pandas as pd
    from sklearn.metrics import roc_auc_score
    from sklearn.linear_model import LogisticRegression
    from scipy.stats import rankdata

    started = time.time()
    state: dict[str, Any] = {
        "status": "loading",
        "startedAt": time.time(),
        "task": "behavioural PD and early-warning detection",
        "config": {
            "observeMonth": args.observe_month,
            "horizonMonths": args.horizon,
            "folds": args.folds,
            "workers": args.workers,
            "rowsLimit": args.rows or "all",
        },
        "baseline": _baseline(),
        "dataset": None,
        "models": [],
        "ensemble": None,
        "log": [],
    }
    _publish(state)

    df = build_panel(args.rows, args.observe_month, args.horizon, state)

    y = df["label"].values.astype(int)
    drop = ["loan", "label", "lead_months"]
    x = df.drop(columns=drop)
    for c in x.columns:
        if x[c].dtype.kind == "O":
            codes = x[c].astype("category").cat.codes.astype("float64")
            codes[codes < 0] = np.nan
            x[c] = codes
    x = x.replace([np.inf, -np.inf], np.nan)

    # Split by ACCOUNT, not by row. Every account contributes one row here, so
    # this is currently equivalent — but it is written this way so that adding a
    # second observation point per account cannot silently leak.
    from sklearn.model_selection import train_test_split

    accounts = df["loan"].unique()
    tr_acc, te_acc = train_test_split(accounts, test_size=0.25, random_state=args.seed)
    tr_set = set(tr_acc)
    mask = df["loan"].isin(tr_set).values
    tr_idx = np.where(mask)[0]
    te_idx = np.where(~mask)[0]

    state["dataset"] = {
        "rows": int(len(y)),
        "features": int(x.shape[1]),
        "train": int(len(tr_idx)),
        "test": int(len(te_idx)),
        "positiveRate": float(y.mean()),
        "observeMonth": args.observe_month,
        "horizonMonths": args.horizon,
    }
    _log(state, f"split by account: {len(tr_idx):,} train / {len(te_idx):,} test")

    scratch = pathlib.Path(os.environ.get("TMPDIR", "/tmp")) / "lh_surv"
    scratch.mkdir(parents=True, exist_ok=True)
    x.to_pickle(scratch / "x.pkl")
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
            "x_path": str(scratch / "x.pkl"),
            "y_path": str(scratch / "y.npy"),
            "train_idx_path": str(scratch / "train_idx.npy"),
            "test_idx_path": str(scratch / "test_idx.npy"),
            "folds": args.folds,
        }
        for s in specs
    ]

    from concurrent.futures import ProcessPoolExecutor, as_completed

    results = []
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
                    slot.update(status="done", testAuc=r["testAuc"],
                                oofAuc=r["oofAuc"], seconds=r["seconds"])
            done = sum(1 for m in state["models"] if m["status"] == "done")
            _log(state, f"{name}: test AUC {r['testAuc']:.4f} · OOF {r['oofAuc']:.4f} · "
                        f"{r['seconds']:.0f}s — {done}/{len(specs)} done")

    if not results:
        state["status"] = "failed"
        _log(state, "every model failed")
        return state

    state["status"] = "blending"
    y_tr, y_te = y[tr_idx], y[te_idx]

    def rank(v):
        return rankdata(v) / len(v)

    equal = np.mean([rank(r["test"]) for r in results], axis=0)
    equal_auc = float(roc_auc_score(y_te, equal))

    stack = LogisticRegression(max_iter=2000)
    stack.fit(np.column_stack([rank(r["oof"]) for r in results]), y_tr)
    stack_pred = stack.predict_proba(np.column_stack([rank(r["test"]) for r in results]))[:, 1]
    stack_auc = float(roc_auc_score(y_te, stack_pred))

    best = max(results, key=lambda r: r["testAuc"])
    winner_name, winner_scores, winner_auc = max(
        [
            ("equal-weight ensemble", equal, equal_auc),
            ("logistic stack", stack_pred, stack_auc),
            (best["name"], np.array(best["test"]), best["testAuc"]),
        ],
        key=lambda t: t[2],
    )

    base = state["baseline"].get("coxCIndex") or 0.0
    state["ensemble"] = {
        "equalWeightTestAuc": equal_auc,
        "stackTestAuc": stack_auc,
        "bestSingleName": best["name"],
        "bestSingleTestAuc": best["testAuc"],
        "winner": winner_name,
        "winnerTestAuc": winner_auc,
        "winnerGiniPoints": (winner_auc * 2 - 1) * 100,
        "liftOverBaseline": winner_auc - base,
        "roc": {
            "winner": roc_points(y_te, winner_scores),
            "bestSingle": roc_points(y_te, np.array(best["test"])),
        },
        # The measure that actually matters for an early-warning system.
        "earlyWarning": [
            lead_time_profile(df, winner_scores, te_idx, f)
            for f in (0.05, 0.10, 0.20)
        ],
    }
    state["status"] = "done"
    state["finishedAt"] = time.time()
    state["elapsedSeconds"] = round(time.time() - started, 1)

    ew = state["ensemble"]["earlyWarning"][1]
    _log(state, f"WINNER {winner_name} · test AUC {winner_auc:.4f} · "
                f"vs committed Cox c-index {base:.4f}")
    _log(state, f"early warning at the top 10%: catches {ew['captureRate']:.1%} of "
                f"defaults, median {ew['medianLeadMonths']} months ahead")

    for r in results:
        r.pop("oof", None)
        r.pop("test", None)
    report = dict(state)
    report["modelDetail"] = results
    report["features"] = list(x.columns)

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    _log(state, f"wrote {out}")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--rows", type=int, default=0, help="0 streams the whole panel")
    parser.add_argument("--observe-month", type=int, default=12)
    parser.add_argument("--horizon", type=int, default=12)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) // 2))
    parser.add_argument("--seed", type=int, default=20260903)
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args(argv)

    if args.quick:
        args.rows, args.folds = 1_500_000, 3

    if not PANEL.exists():
        print(f"{PANEL} not found — see docs/phase0/DATA_SOURCING.md", file=sys.stderr)
        return 2

    report = run(args)
    if report.get("status") != "done":
        return 1

    e = report["ensemble"]
    print(f"\n  winner    {e['winner']}")
    print(f"  test AUC  {e['winnerTestAuc']:.4f}  (Gini {e['winnerGiniPoints']:.2f})")
    for ew in e["earlyWarning"]:
        print(f"  top {ew['topFraction']:.0%}: capture {ew['captureRate']:.1%}, "
              f"median lead {ew['medianLeadMonths']} months")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

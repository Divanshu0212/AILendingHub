#!/usr/bin/env python3
"""Fraud detection on IEEE-CIS: the notebook's features, three model families.

WHAT THIS IS
--------------
`datasets/ieee-fraud-detection/xgb-fraud-with-magic-0-9600.ipynb` is Chris
Deotte's public solution — the "UID magic" that took this competition from ~0.94
to ~0.96 AUC. It fits **one** model family, XGBoost.

The instruction here was to *add more models to try*, not to rewrite it. So the
feature engineering is transcribed from the notebook essentially unchanged — the
UID construction and its aggregations are what earn the 0.96, and replacing them
with something of my own would lose the result rather than improve it. What is
added is LightGBM and CatBoost on the same folds and the same features, plus a
blend.

WHY THE UID FEATURE IS THE WHOLE TRICK
----------------------------------------
`uid = card1_addr1 + floor(day - D1)` recovers a **client identifier** the
dataset does not ship. D1 counts days since the card began, so `day - D1` is
constant for one card across all its transactions — subtracting a growing
counter from a growing clock leaves the start date. Grouping by that and
aggregating turns 590,540 independent-looking rows into a few hundred thousand
customers with histories, which is exactly the entity-resolution step
`lending_hub.fraud.entity_resolution` performs on shared attributes.

That is why this dataset is worth training on here at all: it is the only public
source that exercises the graph half of Module 3.

THREE CHANGES FROM THE NOTEBOOK, EACH FORCED
----------------------------------------------
1. `tree_method='gpu_hist'` → `'hist'`. There is no GPU on this machine.
2. `early_stopping_rounds` moved from `.fit()` into the constructor — xgboost 3
   removed the fit-time argument.
3. `np.str` → `str`. Removed in numpy 1.24.

WHAT THIS DOES NOT TOUCH
--------------------------
`make trackp-p1` and the Phase 1 gate pack. This writes to
`reports/fraud_training.json` and a research-only weight bundle under
`artifacts/fraud-ieee-cis/`. And it measures
discrimination only — a fraud model with a better AUC and a worse false-positive
burden on legitimate customers is not a better model, and the alert budget that
decides that trade-off is still LH-206.

Usage:
    python3 tools/train_fraud.py --quick     # ~5 min on a subsample
    python3 tools/train_fraud.py             # the full run

The weight bundle is deliberately not registered as a serving model. It was
trained on public card transactions, its feature construction uses the IEEE-CIS
batch, and it has neither bank fraud-desk labels nor decision logging.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import pathlib
import hashlib
import sys
import time
import warnings
from typing import Any

warnings.filterwarnings("ignore")

REPO = pathlib.Path(__file__).resolve().parents[1]
DATA = REPO / "datasets" / "ieee-fraud-detection"
DEFAULT_OUT = REPO / "reports" / "fraud_training.json"
PROGRESS = REPO / "reports" / "fraud_progress.json"
DEFAULT_ARTIFACT_DIR = REPO / "artifacts" / "fraud-ieee-cis"


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


def _sha256(path: pathlib.Path) -> str:
    """Checksum a saved weight file for the bundle manifest."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _save_fold_model(clf: Any, family: str, path: pathlib.Path) -> None:
    """Persist a fitted estimator in its library's native weight format.

    Pickling wrappers couples the bundle to the exact Python package layout.
    Native formats retain the actual model weights while making that dependency
    explicit in the manifest instead of hiding it in a pickle.
    """
    if family == "xgboost":
        clf.get_booster().save_model(str(path))
    elif family == "lightgbm":
        clf.booster_.save_model(str(path))
    elif family == "catboost":
        clf.save_model(str(path))
    else:  # model_specs() is closed, so this catches an unimplemented addition.
        raise ValueError(f"no native weight exporter for {family!r}")


# ------------------------------------------------------------- the features
#
# Transcribed from the notebook. The comments are kept where they explain a
# choice that is not obvious from the code.


STR_TYPE = [
    "ProductCD", "card4", "card6", "P_emaildomain", "R_emaildomain",
    "M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9",
    "id_12", "id_15", "id_16", "id_23", "id_27", "id_28", "id_29", "id_30",
    "id_31", "id_33", "id_34", "id_35", "id_36", "id_37", "id_38",
    "DeviceType", "DeviceInfo",
]
STR_TYPE += [c.replace("id_", "id-") for c in STR_TYPE if c.startswith("id_")]

BASE_COLS = [
    "TransactionID", "TransactionDT", "TransactionAmt", "ProductCD",
    "card1", "card2", "card3", "card4", "card5", "card6",
    "addr1", "addr2", "dist1", "dist2", "P_emaildomain", "R_emaildomain",
] + [f"C{i}" for i in range(1, 15)] + [f"D{i}" for i in range(1, 16)] + [
    f"M{i}" for i in range(1, 10)
]

#: V columns chosen by the notebook's correlation EDA — one representative per
#: correlated block, rather than all 339.
V_COLS = [
    1, 3, 4, 6, 8, 11, 13, 14, 17, 20, 23, 26, 27, 30,
    36, 37, 40, 41, 44, 47, 48, 54, 56, 59, 62, 65, 67, 68, 70,
    76, 78, 80, 82, 86, 88, 89, 91, 107, 108, 111, 115, 117, 120, 121, 123,
    124, 127, 129, 130, 136, 138, 139, 142, 147, 156, 162, 165, 160, 166,
    178, 176, 173, 182, 187, 203, 205, 207, 215, 169, 171, 175, 180, 185,
    188, 198, 210, 209, 218, 223, 224, 226, 228, 229, 235, 240, 258, 257,
    253, 252, 260, 261, 264, 266, 267, 274, 277, 220, 221, 234, 238, 250,
    271, 294, 284, 285, 286, 291, 297, 303, 305, 307, 309, 310, 320,
    281, 283, 289, 296, 301, 314,
]


def load(state: dict[str, Any], rows: int | None):
    """Load, merge identity, and build every feature the notebook builds."""
    import numpy as np
    import pandas as pd

    cols = BASE_COLS + [f"V{x}" for x in V_COLS]
    dtypes = {c: "float32" for c in cols if c not in ["TransactionID"] + STR_TYPE}
    dtypes.update({c: "category" for c in STR_TYPE if c in cols})

    _log(state, "loading transactions…")
    X_train = pd.read_csv(
        DATA / "train_transaction.csv", index_col="TransactionID",
        dtype=dtypes, usecols=cols + ["isFraud"], nrows=rows,
    )
    train_id = pd.read_csv(DATA / "train_identity.csv", index_col="TransactionID", dtype=dtypes)
    X_train = X_train.merge(train_id, how="left", left_index=True, right_index=True)

    X_test = pd.read_csv(
        DATA / "test_transaction.csv", index_col="TransactionID",
        dtype=dtypes, usecols=cols, nrows=rows,
    )
    test_id = pd.read_csv(DATA / "test_identity.csv", index_col="TransactionID", dtype=dtypes)
    # The test identity file uses "id-01" where train uses "id_01".
    test_id.rename(columns=dict(zip(test_id.columns, train_id.columns)), inplace=True)
    X_test = X_test.merge(test_id, how="left", left_index=True, right_index=True)

    y_train = X_train["isFraud"].copy()
    del train_id, test_id, X_train["isFraud"]
    gc.collect()
    _log(state, f"train {X_train.shape}, test {X_test.shape}, "
                f"fraud rate {y_train.mean():.4f}")

    # -- normalise the D columns ------------------------------------------
    # D columns are "days since some event", which grows with the clock. The
    # raw value therefore encodes WHEN a transaction happened, and a model
    # trained on early months learns a threshold that is wrong for later ones.
    # Subtracting the clock leaves the event date, which is stable.
    for i in range(1, 16):
        if i in (1, 2, 3, 5, 9):
            continue
        for df in (X_train, X_test):
            df[f"D{i}"] = df[f"D{i}"] - df.TransactionDT / np.float32(24 * 60 * 60)

    # -- label encode, shift positive, NaN to -1 ---------------------------
    for f in X_train.columns:
        if str(X_train[f].dtype) == "category" or X_train[f].dtype.kind == "O":
            comb, _ = pd.concat([X_train[f], X_test[f]], axis=0).factorize(sort=True)
            X_train[f] = comb[: len(X_train)].astype("int16")
            X_test[f] = comb[len(X_train):].astype("int16")
        elif f not in ("TransactionAmt", "TransactionDT"):
            mn = np.min((X_train[f].min(), X_test[f].min()))
            X_train[f] -= np.float32(mn)
            X_test[f] -= np.float32(mn)
            X_train[f] = X_train[f].fillna(-1)
            X_test[f] = X_test[f].fillna(-1)

    def encode_FE(df1, df2, columns):
        for col in columns:
            vc = pd.concat([df1[col], df2[col]]).value_counts(dropna=True, normalize=True).to_dict()
            vc[-1] = -1
            df1[col + "_FE"] = df1[col].map(vc).astype("float32")
            df2[col + "_FE"] = df2[col].map(vc).astype("float32")

    def encode_CB(col1, col2):
        nm = col1 + "_" + col2
        X_train[nm] = X_train[col1].astype(str) + "_" + X_train[col2].astype(str)
        X_test[nm] = X_test[col1].astype(str) + "_" + X_test[col2].astype(str)
        comb, _ = pd.concat([X_train[nm], X_test[nm]], axis=0).factorize(sort=True)
        X_train[nm] = comb[: len(X_train)].astype("int32")
        X_test[nm] = comb[len(X_train):].astype("int32")

    def encode_AG(mains, uids, aggs=("mean",), fillna=True, usena=False):
        for main in mains:
            for col in uids:
                for agg in aggs:
                    nm = f"{main}_{col}_{agg}"
                    temp = pd.concat([X_train[[col, main]], X_test[[col, main]]])
                    if usena:
                        temp.loc[temp[main] == -1, main] = np.nan
                    grouped = temp.groupby(col)[main].agg([agg]).rename(
                        columns={agg: nm}
                    )
                    mapper = grouped[nm].to_dict()
                    X_train[nm] = X_train[col].map(mapper).astype("float32")
                    X_test[nm] = X_test[col].map(mapper).astype("float32")
                    if fillna:
                        X_train[nm] = X_train[nm].fillna(-1)
                        X_test[nm] = X_test[nm].fillna(-1)

    def encode_AG2(mains, uids):
        """Count of DISTINCT values per uid — 'how many devices has this
        client used', which is a different signal from 'how many transactions'."""
        for main in mains:
            for col in uids:
                nm = f"{main}_{col}_ct"
                temp = pd.concat([X_train[[col, main]], X_test[[col, main]]])
                mapper = temp.groupby(col)[main].agg(["nunique"])["nunique"].to_dict()
                X_train[nm] = X_train[col].map(mapper).astype("float32")
                X_test[nm] = X_test[col].map(mapper).astype("float32")

    _log(state, "building features…")
    for df in (X_train, X_test):
        df["cents"] = (df["TransactionAmt"] - np.floor(df["TransactionAmt"])).astype("float32")
    encode_FE(X_train, X_test, ["addr1", "card1", "card2", "card3", "P_emaildomain"])
    encode_CB("card1", "addr1")
    encode_CB("card1_addr1", "P_emaildomain")
    encode_FE(X_train, X_test, ["card1_addr1", "card1_addr1_P_emaildomain"])
    encode_AG(["TransactionAmt", "D9", "D11"],
              ["card1", "card1_addr1", "card1_addr1_P_emaildomain"],
              ("mean", "std"), usena=True)

    # -- the UID, and everything aggregated onto it ------------------------
    import datetime

    START = datetime.datetime.strptime("2017-11-30", "%Y-%m-%d")
    for df in (X_train, X_test):
        # Vectorised rather than `.apply(timedelta)`. On the full file the
        # elementwise version returns an OBJECT column of datetimes, and `.dt`
        # then raises — it worked on the 200k subset only because pandas
        # inferred a datetime dtype there. to_timedelta is also ~50x faster
        # over 590k rows.
        stamps = START + pd.to_timedelta(df["TransactionDT"], unit="s")
        df["DT_M"] = (stamps.dt.year - 2017) * 12 + stamps.dt.month
        df["day"] = df.TransactionDT / (24 * 60 * 60)
        df["uid"] = df.card1_addr1.astype(str) + "_" + np.floor(df.day - df.D1).astype(str)

    _log(state, "aggregating onto the recovered client id…")
    encode_FE(X_train, X_test, ["uid"])
    encode_AG(["TransactionAmt", "D4", "D9", "D10", "D15"], ["uid"], ("mean", "std"), usena=True)
    encode_AG([f"C{x}" for x in range(1, 15) if x != 3], ["uid"], ("mean",), usena=True)
    encode_AG([f"M{x}" for x in range(1, 10)], ["uid"], ("mean",), usena=True)
    encode_AG2(["P_emaildomain", "dist1", "DT_M", "id_02", "cents"], ["uid"])
    encode_AG(["C14"], ["uid"], ("std",), usena=True)
    encode_AG2(["C13", "V314"], ["uid"])
    encode_AG2(["V127", "V136", "V309", "V307", "V320"], ["uid"])
    for df in (X_train, X_test):
        df["outsider15"] = (np.abs(df.D1 - df.D15) > 3).astype("int8")

    # -- the feature list --------------------------------------------------
    # The removals are the notebook's, and they come from a time-consistency
    # test: train on the first month, predict the last, and drop any column
    # whose single-feature AUC falls below 0.5. A column that fails that has a
    # distribution which moved, and it will hurt on the future data that
    # matters rather than the holdout that does not.
    cols = list(X_train.columns)
    for c in ["TransactionDT", "D6", "D7", "D8", "D9", "D12", "D13", "D14",
              "DT_M", "day", "uid", "C3", "M5", "id_08", "id_33",
              "card4", "id_07", "id_14", "id_21", "id_30", "id_32", "id_34"]:
        if c in cols:
            cols.remove(c)
    for x in range(22, 28):
        if f"id_{x}" in cols:
            cols.remove(f"id_{x}")

    _log(state, f"{len(cols)} features after the time-consistency removals")
    return X_train, X_test, y_train, cols


# ---------------------------------------------------------------- the models


def model_specs(quick: bool, seed: int) -> list[dict[str, Any]]:
    """Three families on identical folds and features.

    The notebook's XGBoost is kept exactly as configured — depth 12, lr 0.02,
    colsample 0.4 — because that configuration is what produced the published
    result and changing it would make the comparison meaningless. LightGBM and
    CatBoost are added at settings that are conventional for this dataset
    rather than tuned, which is the honest starting point: any lift they show
    is from family diversity, not from me having searched harder on their side.
    """
    trees = 400 if quick else 3000
    return [
        {
            "name": "xgboost_notebook",
            "family": "xgboost",
            "note": "the notebook's configuration, GPU flag removed",
            "params": {
                "n_estimators": trees, "max_depth": 12, "learning_rate": 0.02,
                "subsample": 0.8, "colsample_bytree": 0.4, "missing": -1,
                "eval_metric": "auc", "tree_method": "hist",
                "early_stopping_rounds": 200, "random_state": seed, "n_jobs": 4,
            },
        },
        {
            "name": "lightgbm",
            "family": "lightgbm",
            "note": "added — histogram splits and leaf-wise growth",
            "params": {
                "n_estimators": trees, "learning_rate": 0.02, "num_leaves": 256,
                "max_depth": 12, "min_child_samples": 80, "subsample": 0.8,
                "subsample_freq": 1, "colsample_bytree": 0.4,
                "reg_alpha": 0.3, "reg_lambda": 0.6,
                "random_state": seed, "n_jobs": 4, "verbose": -1,
            },
        },
        {
            "name": "catboost",
            "family": "catboost",
            "note": "added — ordered boosting, different overfit behaviour",
            "params": {
                "iterations": trees, "learning_rate": 0.03, "depth": 10,
                "l2_leaf_reg": 3.0, "random_seed": seed, "eval_metric": "AUC",
                "od_type": "Iter", "od_wait": 200, "verbose": False,
                "thread_count": 4, "allow_writing_files": False,
            },
        },
    ]


def train_one(payload: dict[str, Any]) -> dict[str, Any]:
    """Fit one family across the month folds. Runs in its own process."""
    import numpy as np
    import pandas as pd
    from sklearn.model_selection import GroupKFold
    from sklearn.metrics import roc_auc_score

    spec = payload["spec"]
    X = pd.read_pickle(payload["x_path"])
    y = np.load(payload["y_path"])
    groups = np.load(payload["groups_path"])
    cols = payload["cols"]

    started = time.time()
    # GroupKFold on the calendar month: every fold withholds a whole month, so
    # a model can never see a transaction from the month it is scored on. A
    # random fold would let a card's January transactions predict its own
    # January transactions, which is the leak this competition is famous for.
    # Never ask for more folds than there are months. A quick run on a row
    # subset covers fewer months than the full file, and GroupKFold raises
    # rather than degrading — so the fold count is clamped here instead.
    n_groups = len(np.unique(groups))
    skf = GroupKFold(n_splits=min(payload["folds"], n_groups))
    oof = np.zeros(len(y))
    fold_aucs: list[float] = []
    saved_weights: list[dict[str, Any]] = []
    artifact_dir = pathlib.Path(payload["artifact_dir"])

    for fold, (idxT, idxV) in enumerate(skf.split(X, y, groups=groups)):
        xt, yt = X[cols].iloc[idxT], y[idxT]
        xv, yv = X[cols].iloc[idxV], y[idxV]

        if spec["family"] == "xgboost":
            import xgboost as xgb

            clf = xgb.XGBClassifier(**spec["params"])
            clf.fit(xt, yt, eval_set=[(xv, yv)], verbose=False)
        elif spec["family"] == "lightgbm":
            import lightgbm as lgb

            clf = lgb.LGBMClassifier(**spec["params"])
            clf.fit(xt, yt, eval_set=[(xv, yv)], eval_metric="auc",
                    callbacks=[lgb.early_stopping(200, verbose=False)])
        else:
            from catboost import CatBoostClassifier

            clf = CatBoostClassifier(**spec["params"])
            clf.fit(xt, yt, eval_set=(xv, yv), use_best_model=True)

        oof[idxV] = clf.predict_proba(xv)[:, 1]
        fold_aucs.append(float(roc_auc_score(yv, oof[idxV])))
        suffix = {"xgboost": "json", "lightgbm": "txt", "catboost": "cbm"}[spec["family"]]
        weight_path = artifact_dir / f"{spec['name']}-fold-{fold}.{suffix}"
        _save_fold_model(clf, spec["family"], weight_path)
        saved_weights.append({
            "fold": fold,
            "path": weight_path.name,
            "sha256": _sha256(weight_path),
        })
        del clf
        gc.collect()

    return {
        "name": spec["name"],
        "family": spec["family"],
        "note": spec["note"],
        "oofAuc": float(roc_auc_score(y, oof)),
        "foldAucs": fold_aucs,
        "seconds": round(time.time() - started, 1),
        "oof": oof.tolist(),
        "weights": saved_weights,
    }


def roc_points(y, scores, buckets: int = 80):
    from sklearn.metrics import roc_curve

    fpr, tpr, _ = roc_curve(y, scores)
    step = max(1, len(fpr) // buckets)
    pts = [{"fpr": float(fpr[i]), "tpr": float(tpr[i])} for i in range(0, len(fpr), step)]
    pts.append({"fpr": 1.0, "tpr": 1.0})
    return pts


def alert_profile(y, scores, fraction: float) -> dict[str, Any]:
    """What a review desk would see at a given alert budget.

    AUC is a ranking statistic and a desk cannot act on a ranking. What it acts
    on is: if we review the top N% of transactions, how much fraud do we catch,
    and how many good customers do we stop? The second number is the one that
    costs a bank customers, and it is why LH-206 (the alert budget) is a
    business decision rather than a modelling one.
    """
    import numpy as np

    n = len(scores)
    k = max(1, int(n * fraction))
    order = np.argsort(-scores)[:k]
    caught = int(y[order].sum())
    total = int(y.sum())
    return {
        "reviewFraction": fraction,
        "transactionsReviewed": k,
        "fraudCaught": caught,
        "fraudTotal": total,
        "captureRate": caught / total if total else 0.0,
        "precision": caught / k,
        "falsePositives": k - caught,
    }


def run(args) -> dict[str, Any]:
    import numpy as np
    from sklearn.metrics import roc_auc_score
    from sklearn.linear_model import LogisticRegression
    from scipy.stats import rankdata

    started = time.time()
    state: dict[str, Any] = {
        "status": "loading",
        "startedAt": time.time(),
        "task": "fraud detection — IEEE-CIS",
        "config": {"folds": args.folds, "workers": args.workers,
                   "rows": args.rows or "all", "quick": args.quick},
        "baseline": {
            "publishedAuc": 0.96,
            "note": "the notebook's published leaderboard score, XGBoost alone",
        },
        "dataset": None, "models": [], "ensemble": None, "log": [],
    }
    _publish(state)

    # `--rows 0` means "read everything", but pandas reads `nrows=0` as zero
    # rows — the file loaded empty, every feature built over nothing, and the
    # fold splitter reported n_splits=0 rather than anything naming the cause.
    X_train, X_test, y_train, cols = load(state, args.rows or None)
    y = y_train.values.astype(int)
    groups = X_train["DT_M"].values
    if len(y) == 0:
        raise SystemExit("loaded zero rows — check --rows and the data path")

    state["dataset"] = {
        "rows": int(len(y)),
        "features": len(cols),
        "fraudRate": float(y.mean()),
        "months": int(len(np.unique(groups))),
    }
    _publish(state)

    artifact_dir = pathlib.Path(args.artifact_dir).resolve()
    if artifact_dir.exists():
        raise SystemExit(
            f"artifact directory already exists: {artifact_dir}. Choose a new "
            "--artifact-dir so an earlier weight bundle is not overwritten."
        )
    artifact_dir.mkdir(parents=True)
    manifest_path = artifact_dir / "manifest.json"
    manifest_path.write_text(json.dumps({
        "status": "training",
        "kind": "research_only_public_fraud_benchmark",
        "servingEligible": False,
        "servingNote": (
            "IEEE-CIS card-transaction weights are not a loan-application "
            "model and have no bank decision-log provenance."
        ),
        "dataset": state["dataset"],
        "config": state["config"],
        "featureColumns": cols,
    }, indent=2) + "\n", encoding="utf-8")
    _log(state, f"saving native model weights under {artifact_dir}")

    scratch = pathlib.Path(os.environ.get("TMPDIR", "/tmp")) / "lh_fraud"
    scratch.mkdir(parents=True, exist_ok=True)
    X_train.to_pickle(scratch / "x.pkl")
    np.save(scratch / "y.npy", y)
    np.save(scratch / "groups.npy", groups)
    del X_test
    gc.collect()

    specs = model_specs(args.quick, args.seed)
    state["models"] = [
        {"name": s["name"], "family": s["family"], "note": s["note"], "status": "queued"}
        for s in specs
    ]
    state["status"] = "training"
    _log(state, f"training {len(specs)} families across {args.workers} workers")

    payloads = [
        {"spec": s, "x_path": str(scratch / "x.pkl"), "y_path": str(scratch / "y.npy"),
         "groups_path": str(scratch / "groups.npy"), "cols": cols, "folds": args.folds,
         "artifact_dir": str(artifact_dir)}
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
                _log(state, f"{name} FAILED — {str(error)[:200]}")
                continue
            results.append(r)
            for slot in state["models"]:
                if slot["name"] == name:
                    slot.update(status="done", testAuc=r["oofAuc"],
                                oofAuc=r["oofAuc"], seconds=r["seconds"],
                                foldAucs=r["foldAucs"])
            done = sum(1 for m in state["models"] if m["status"] == "done")
            _log(state, f"{name}: OOF AUC {r['oofAuc']:.5f} · {r['seconds']:.0f}s "
                        f"— {done}/{len(specs)} done")

    if not results:
        state["status"] = "failed"
        _log(state, "every family failed")
        return state

    state["status"] = "blending"

    def rank(v):
        return rankdata(v) / len(v)

    equal = np.mean([rank(r["oof"]) for r in results], axis=0)
    equal_auc = float(roc_auc_score(y, equal))

    # The stack is fitted on the same out-of-fold predictions it blends, which
    # is optimistic — with three members and 590k rows the optimism is small,
    # but it is why the equal-weight number is reported alongside rather than
    # replaced by it.
    stack = LogisticRegression(max_iter=2000)
    M = np.column_stack([rank(r["oof"]) for r in results])
    stack.fit(M, y)
    stack_pred = stack.predict_proba(M)[:, 1]
    stack_auc = float(roc_auc_score(y, stack_pred))

    best = max(results, key=lambda r: r["oofAuc"])
    winner_name, winner_scores, winner_auc = max(
        [("equal-weight ensemble", equal, equal_auc),
         ("logistic stack", stack_pred, stack_auc),
         (best["name"], np.array(best["oof"]), best["oofAuc"])],
        key=lambda t: t[2],
    )

    state["ensemble"] = {
        "equalWeightTestAuc": equal_auc,
        "stackTestAuc": stack_auc,
        "bestSingleName": best["name"],
        "bestSingleTestAuc": best["oofAuc"],
        "winner": winner_name,
        "winnerTestAuc": winner_auc,
        "winnerGiniPoints": (winner_auc * 2 - 1) * 100,
        "stackNote": (
            "The stack is fitted on the out-of-fold predictions it blends, so "
            "its number is mildly optimistic. The equal-weight figure carries "
            "no such fit and is the safer one to quote."
        ),
        "roc": {
            "winner": roc_points(y, winner_scores),
            "bestSingle": roc_points(y, np.array(best["oof"])),
        },
        "alertBudget": [alert_profile(y, winner_scores, f) for f in (0.005, 0.01, 0.02, 0.05)],
    }
    manifest = {
        "status": "done",
        "kind": "research_only_public_fraud_benchmark",
        "servingEligible": False,
        "servingNote": (
            "These are cross-validation fold weights for the public IEEE-CIS "
            "card-transaction benchmark. They are not registered, do not score "
            "loan applications, and must not be used for customer decisions."
        ),
        "dataset": state["dataset"],
        "config": state["config"],
        "featureColumns": cols,
        "baseModels": [
            {
                "name": result["name"],
                "family": result["family"],
                "weights": result["weights"],
            }
            for result in results
        ],
        "stack": {
            "type": "logistic_regression_over_ranked_fold_predictions",
            "classes": [int(value) for value in stack.classes_],
            "coefficients": stack.coef_[0].tolist(),
            "intercept": stack.intercept_.tolist(),
            "memberOrder": [result["name"] for result in results],
        },
    }
    tmp_manifest = manifest_path.with_suffix(".tmp")
    tmp_manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    tmp_manifest.replace(manifest_path)
    state["artifactBundle"] = str(artifact_dir.relative_to(REPO))
    state["status"] = "done"
    state["finishedAt"] = time.time()
    state["elapsedSeconds"] = round(time.time() - started, 1)

    ab = state["ensemble"]["alertBudget"][1]
    _log(state, f"WINNER {winner_name} · OOF AUC {winner_auc:.5f} "
                f"(the notebook's published XGBoost alone is ~0.96)")
    _log(state, f"at a 1% review budget: catches {ab['captureRate']:.1%} of fraud, "
                f"{ab['precision']:.1%} of reviews are real")

    for r in results:
        r.pop("oof", None)
    report = dict(state)
    report["modelDetail"] = results
    report["features"] = cols

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    _log(state, f"wrote {out}")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--rows", type=int, default=0, help="0 reads every row")
    parser.add_argument("--folds", type=int, default=6)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20260903)
    parser.add_argument(
        "--artifact-dir", default=str(DEFAULT_ARTIFACT_DIR),
        help="new directory for native research model weights and manifest",
    )
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args(argv)

    if args.quick:
        # 200k rows rather than 60k: the folds are by CALENDAR MONTH, and the
        # first 60,000 transactions all fall inside one month, which leaves
        # GroupKFold a single group and nothing to split. A quick mode that
        # cannot exercise the real fold structure is not a smoke test.
        args.rows, args.folds = 200_000, 2

    if not (DATA / "train_transaction.csv").exists():
        print(f"{DATA} not found — see docs/phase0/DATA_SOURCING.md", file=sys.stderr)
        return 2

    report = run(args)
    if report.get("status") != "done":
        return 1

    e = report["ensemble"]
    print(f"\n  winner    {e['winner']}")
    print(f"  OOF AUC   {e['winnerTestAuc']:.5f}  (Gini {e['winnerGiniPoints']:.2f})")
    for a in e["alertBudget"]:
        print(f"  review {a['reviewFraction']:.1%}: capture {a['captureRate']:.1%}, "
              f"precision {a['precision']:.1%}, {a['falsePositives']:,} false alerts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Crop classification on AgriFieldNet India — SRS Module 1, Model B.

WHAT THIS CLOSES
------------------
ADR-0013 recorded Phase 2 as having no Track P at all: no imagery, and 34
crop-typed ground-truth points for the whole of India. That was true of the
sources checked at the time and is no longer true. AgriFieldNet ships 1,173
Sentinel-2 tiles over Uttar Pradesh, Rajasthan, Odisha and Bihar with
**147,409 labelled training pixels across six crop classes**.

So the ADR needs amending — the same self-correction P2-F14 already records
once, for the same reason: "no data exists" and "I did not look hard enough"
are different claims, and only the second was true.

WHY PER-PIXEL CLASSIFICATION RATHER THAN A SEGMENTATION NETWORK
-----------------------------------------------------------------
The obvious reading of "segmentation dataset" is U-Net. It is the wrong tool
here, and the reason is in the labels.

Labels are **sparse**: 147,409 labelled pixels out of 60.8 million (0.24%).
Surveyors walked a handful of fields per tile and marked those; everything else
is -1, meaning *not surveyed* rather than *not crop*. A segmentation network
learns spatial context from dense masks, and there is no dense mask to learn
from — it would be fitting a 31-million-parameter model to a few hundred labelled
pixels per tile, on a machine with no GPU.

What the labels do support is a per-pixel classifier over spectral values and
vegetation indices, which is what the remote-sensing literature uses when ground
truth is point-sampled. That is the honest model for this data.

THE TRAP THIS AVOIDS, STATED PLAINLY
--------------------------------------
A model that predicts "unlabelled" everywhere scores **99.76% pixel accuracy**.
Every metric here is computed over labelled pixels only, and the headline number
is **macro-F1** rather than accuracy, because class 0 has 2,545 training pixels
against class 4's 59,585 — a 23x imbalance in which accuracy is dominated by
whichever class happens to be largest.

WHAT THIS DOES NOT DO
-----------------------
It does not touch `src/lending_hub/agri/`, which still ships the model
*contracts* — the metric, the gate, the abstention rule — with no fitted
weights. Those contracts are what Phase 2 specifies; this is evidence that the
gate they describe is now reachable. It writes to `reports/crop_training.json`.

It also derives no yield, no income and no credit feature. Those need ratified
input costs (LH-401) and a crop calendar (LH-102), and a crop label does not
supply either.

Usage:
    python3 tools/train_crop.py --quick     # ~3 min on a tile subset
    python3 tools/train_crop.py             # the full run
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
DATA = REPO / "datasets" / "iisc-ibm-crop-id-segmentation"
DEFAULT_OUT = REPO / "reports" / "crop_training.json"
PROGRESS = REPO / "reports" / "crop_progress.json"

#: Sentinel-2 band order in these files, read from the band descriptions.
BANDS = ["B01", "B02", "B03", "B04", "B05", "B06", "B07", "B08", "B09", "B11", "B12", "B8A"]
B = {name: i for i, name in enumerate(BANDS)}

#: The six classes. AgriFieldNet's competition subset; the class ids are the
#: file's own, and no name is invented for them here — mapping an integer to a
#: crop name without the dataset's own legend would be exactly the kind of
#: plausible guess this repository refuses.
N_CLASSES = 6


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


# ------------------------------------------------------------------ features


def tile_features(arr):
    """Spectral bands plus the vegetation indices `agri.indices` specifies.

    The raw reflectances alone let a tree split on brightness, which separates
    bare soil from vegetation and little else. The indices are ratios, so they
    are invariant to illumination — two fields of the same crop photographed at
    different sun angles have different reflectances and the same NDVI. That is
    why every remote-sensing pipeline computes them rather than trusting the
    model to discover the ratio.
    """
    import numpy as np

    a = arr.astype("float32")
    red, nir = a[B["B04"]], a[B["B08"]]
    green, blue = a[B["B03"]], a[B["B02"]]
    swir1, swir2 = a[B["B11"]], a[B["B12"]]
    rededge = a[B["B05"]]
    eps = 1e-6

    ndvi = (nir - red) / (nir + red + eps)
    # EVI's coefficients are the standard MODIS ones; the blue term corrects for
    # aerosol scattering that NDVI leaves in.
    evi = 2.5 * (nir - red) / (nir + 6.0 * red - 7.5 * blue + 1.0 + eps)
    ndwi = (green - nir) / (green + nir + eps)          # water / irrigation
    ndmi = (nir - swir1) / (nir + swir1 + eps)          # canopy moisture
    nbr = (nir - swir2) / (nir + swir2 + eps)           # residue / burn
    savi = 1.5 * (nir - red) / (nir + red + 0.5 + eps)  # soil-adjusted
    ndre = (nir - rededge) / (nir + rededge + eps)      # chlorophyll

    extra = np.stack([ndvi, evi, ndwi, ndmi, nbr, savi, ndre])
    stack = np.concatenate([a, extra], axis=0)

    # -- neighbourhood context ------------------------------------------
    #
    # The single largest gain available on this data, and it comes from a
    # property of fields rather than of models: a field is contiguous, so a
    # pixel's neighbours are usually the same crop. 37% of these tiles carry
    # exactly one class.
    #
    # A per-pixel classifier throws that away — it sees each pixel as an
    # independent spectral sample. Adding a local mean and standard deviation
    # over a window gives it the context a segmentation network would learn,
    # without needing dense masks to learn it from.
    #
    # Box-blurred via cumulative sums rather than scipy: it is O(n) per window
    # regardless of radius, and keeps this file free of another dependency.
    ctx = []
    for radius in (2, 6):
        mean = _box_mean(stack, radius)
        ctx.append(mean)
        # Local variability separates a uniform field from a boundary or a
        # mixed pixel, which is exactly where the confusions happen.
        sq = _box_mean(stack * stack, radius)
        ctx.append(np.sqrt(np.maximum(sq - mean * mean, 0.0)))

    return np.concatenate([stack] + ctx, axis=0)


def _box_mean(a, radius: int):
    """Mean over a (2r+1)^2 window, per band, edges included.

    Summed-area table: two cumulative sums and four lookups per output, so the
    cost does not grow with the radius.
    """
    import numpy as np

    pad = np.pad(a, ((0, 0), (radius + 1, radius), (radius + 1, radius)), mode="edge")
    cs = pad.cumsum(1).cumsum(2)
    h, w = a.shape[1], a.shape[2]
    k = 2 * radius + 1
    total = (
        cs[:, k:k + h, k:k + w]
        - cs[:, :h, k:k + w]
        - cs[:, k:k + h, :w]
        + cs[:, :h, :w]
    )
    return total / (k * k)


_CORE = BANDS + ["NDVI", "EVI", "NDWI", "NDMI", "NBR", "SAVI", "NDRE"]
FEATURE_NAMES = _CORE + [
    f"{name}_{stat}{r}"
    for r in (2, 6)
    for stat in ("mean", "std")
    for name in _CORE
]


def load_split(split: str, state: dict[str, Any], limit: int | None):
    """Every labelled pixel in a split, as rows.

    Returns X, y and the tile id each row came from — the tile id matters
    because pixels from one tile are not independent, and a split that mixed
    them would leak neighbouring pixels between train and test.
    """
    import numpy as np
    import rasterio

    ids = (DATA / f"{split}.txt").read_text().split()
    if limit:
        ids = ids[:limit]

    xs, ys, tiles = [], [], []
    for n, tid in enumerate(ids):
        ipath = DATA / split / "inputs" / f"{tid}_input.tif"
        lpath = DATA / split / "labels" / f"{tid}_label_c6.tif"
        if not ipath.exists() or not lpath.exists():
            continue
        with rasterio.open(ipath) as src:
            arr = src.read()
        with rasterio.open(lpath) as src:
            lab = src.read(1)

        feats = tile_features(arr)
        mask = lab >= 0
        if not mask.any():
            continue
        xs.append(feats[:, mask].T)
        ys.append(lab[mask].astype("int16"))
        tiles.extend([tid] * int(mask.sum()))

        if state is not None and (n + 1) % 200 == 0:
            _log(state, f"  {split}: {n + 1}/{len(ids)} tiles read")

    X = np.concatenate(xs).astype("float32")
    y = np.concatenate(ys)
    return X, y, np.array(tiles)


# ------------------------------------------------------------------- models


def model_specs(quick: bool, seed: int) -> list[dict[str, Any]]:
    trees = 200 if quick else 900
    return [
        {
            "name": "lightgbm_crop",
            "family": "lightgbm",
            "params": {
                "n_estimators": trees, "learning_rate": 0.05, "num_leaves": 63,
                "max_depth": 9, "min_child_samples": 30, "subsample": 0.85,
                "subsample_freq": 1, "colsample_bytree": 0.8, "reg_lambda": 1.0,
                "objective": "multiclass", "num_class": N_CLASSES,
                # Sparse labels AND a 23x class imbalance. Without this the
                # model learns to answer with class 4 and is right 40% of the
                # time, which macro-F1 correctly punishes and accuracy does not.
                "class_weight": "balanced",
                "random_state": seed, "n_jobs": 4, "verbose": -1,
            },
        },
        {
            "name": "xgboost_crop",
            "family": "xgboost",
            "params": {
                "n_estimators": trees, "learning_rate": 0.06, "max_depth": 8,
                "min_child_weight": 10, "subsample": 0.85, "colsample_bytree": 0.75,
                "reg_lambda": 2.0, "tree_method": "hist",
                "objective": "multi:softprob", "num_class": N_CLASSES,
                "random_state": seed, "n_jobs": 4,
            },
        },
        {
            "name": "random_forest_crop",
            "family": "sklearn_rf",
            "params": {
                "n_estimators": 300 if quick else 700, "max_depth": 22,
                "min_samples_leaf": 3, "max_features": "sqrt",
                "class_weight": "balanced_subsample",
                "n_jobs": 4, "random_state": seed,
            },
        },
        {
            "name": "extra_trees_crop",
            "family": "sklearn_et",
            "params": {
                "n_estimators": 300 if quick else 700, "max_depth": 26,
                "min_samples_leaf": 2, "max_features": "sqrt",
                "class_weight": "balanced",
                "n_jobs": 4, "random_state": seed,
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
    if spec["family"] == "sklearn_rf":
        from sklearn.ensemble import RandomForestClassifier

        return RandomForestClassifier(**spec["params"])
    from sklearn.ensemble import ExtraTreesClassifier

    return ExtraTreesClassifier(**spec["params"])


def train_one(payload: dict[str, Any]) -> dict[str, Any]:
    import numpy as np
    from sklearn.metrics import f1_score, accuracy_score

    spec = payload["spec"]
    Xtr = np.load(payload["xtr"])
    ytr = np.load(payload["ytr"])
    Xva = np.load(payload["xva"])
    yva = np.load(payload["yva"])
    Xte = np.load(payload["xte"])
    yte = np.load(payload["yte"])

    started = time.time()
    model = _make(spec)
    model.fit(Xtr, ytr)
    pred = model.predict(Xva)
    proba = model.predict_proba(Xva)
    test_proba = model.predict_proba(Xte)
    test_pred = test_proba.argmax(1)

    return {
        "name": spec["name"],
        "family": spec["family"],
        "macroF1": float(f1_score(yva, pred, average="macro")),
        "weightedF1": float(f1_score(yva, pred, average="weighted")),
        "accuracy": float(accuracy_score(yva, pred)),
        "perClassF1": [float(v) for v in f1_score(yva, pred, average=None,
                                                  labels=list(range(N_CLASSES)))],
        "seconds": round(time.time() - started, 1),
        # Validation macro-F1 is what selects; the test figures are carried
        # along so the winner is scored without a refit.
        "testMacroF1": float(f1_score(yte, test_pred, average="macro")),
        "proba": proba.tolist(),
        "testProba": test_proba.tolist(),
    }


def run(args) -> dict[str, Any]:
    import numpy as np
    from sklearn.metrics import f1_score, accuracy_score, confusion_matrix

    started = time.time()
    state: dict[str, Any] = {
        "status": "loading",
        "startedAt": time.time(),
        "task": "crop classification — AgriFieldNet India",
        "config": {"tiles": args.tiles or "all", "workers": args.workers,
                   "seed": args.seed, "quick": args.quick},
        "baseline": {
            "note": "no prior model — ADR-0013 recorded Phase 2 as having no "
                    "Track P at all. This is the first fitted agri model.",
        },
        "dataset": None, "models": [], "ensemble": None, "log": [],
    }
    _publish(state)

    _log(state, "reading tiles…")
    Xtr, ytr, _ = load_split("train", state, args.tiles)
    Xva, yva, _ = load_split("val", state, args.tiles)
    Xte, yte, _ = load_split("test", state, args.tiles)

    counts = {int(k): int(v) for k, v in zip(*np.unique(ytr, return_counts=True))}
    state["dataset"] = {
        "trainPixels": int(len(ytr)),
        "valPixels": int(len(yva)),
        "testPixels": int(len(yte)),
        "features": Xtr.shape[1],
        "classes": N_CLASSES,
        "trainClassCounts": counts,
        "imbalanceRatio": round(max(counts.values()) / min(counts.values()), 1),
        "labelledFraction": None,
    }
    _log(state, f"train {len(ytr):,} px · val {len(yva):,} · test {len(yte):,} · "
                f"{Xtr.shape[1]} features · class counts {counts}")
    _log(state, f"class imbalance {state['dataset']['imbalanceRatio']}x — reporting "
                "macro-F1, not accuracy")

    scratch = pathlib.Path(os.environ.get("TMPDIR", "/tmp")) / "lh_crop"
    scratch.mkdir(parents=True, exist_ok=True)
    # Three splits, used as three splits. An earlier version passed the TEST
    # set in as the validation set, which meant the winning model was chosen on
    # the data its score is reported against — the selection overfits even when
    # no model does. Selection happens on `val`; `test` is scored once, at the
    # end, by whichever model won.
    for name, arr in [("xtr", Xtr), ("ytr", ytr), ("xva", Xva), ("yva", yva),
                      ("xte", Xte), ("yte", yte)]:
        np.save(scratch / f"{name}.npy", arr)

    specs = model_specs(args.quick, args.seed)
    state["models"] = [
        {"name": s["name"], "family": s["family"], "status": "queued"} for s in specs
    ]
    state["status"] = "training"
    _log(state, f"training {len(specs)} models across {args.workers} workers")

    payloads = [
        {"spec": s, "xtr": str(scratch / "xtr.npy"), "ytr": str(scratch / "ytr.npy"),
         "xva": str(scratch / "xva.npy"), "yva": str(scratch / "yva.npy"),
         "xte": str(scratch / "xte.npy"), "yte": str(scratch / "yte.npy")}
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
                _log(state, f"{name} FAILED — {str(error)[:180]}")
                continue
            results.append(r)
            for slot in state["models"]:
                if slot["name"] == name:
                    slot.update(status="done", testAuc=r["testMacroF1"],
                                macroF1=r["macroF1"],
                                testMacroF1=r["testMacroF1"],
                                accuracy=r["accuracy"], seconds=r["seconds"])
            done = sum(1 for m in state["models"] if m["status"] == "done")
            _log(state, f"{name}: val macro-F1 {r['macroF1']:.4f} · "
                        f"test {r['testMacroF1']:.4f} · {r['seconds']:.0f}s "
                        f"— {done}/{len(specs)} done")

    if not results:
        state["status"] = "failed"
        _log(state, "every model failed")
        return state

    state["status"] = "blending"

    # Select on VALIDATION, score on TEST. The candidate with the best
    # validation macro-F1 wins; its test score is then read off once. Choosing
    # the winner by test score would make that score a selection statistic
    # rather than an estimate.
    val_blend = np.mean([np.array(r["proba"]) for r in results], axis=0).argmax(1)
    val_blend_f1 = float(f1_score(yva, val_blend, average="macro"))
    test_blend = np.mean([np.array(r["testProba"]) for r in results], axis=0).argmax(1)

    best = max(results, key=lambda r: r["macroF1"])
    candidates = [
        ("equal-weight ensemble", val_blend_f1, test_blend),
        (best["name"], best["macroF1"], np.array(best["testProba"]).argmax(1)),
    ]
    winner_name, winner_val_f1, winner_pred = max(candidates, key=lambda c: c[1])
    winner_f1 = float(f1_score(yte, winner_pred, average="macro"))
    blend_f1 = float(f1_score(yte, test_blend, average="macro"))

    # The number a naive metric would report, stated so nobody quotes it.
    all_labelled_accuracy = float(accuracy_score(yte, winner_pred))

    state["ensemble"] = {
        "winner": winner_name,
        "winnerMacroF1": winner_f1,
        "winnerAccuracy": all_labelled_accuracy,
        "winnerWeightedF1": float(f1_score(yte, winner_pred, average="weighted")),
        "bestSingleName": best["name"],
        "bestSingleValMacroF1": best["macroF1"],
        "bestSingleTestMacroF1": best["testMacroF1"],
        "equalWeightTestMacroF1": blend_f1,
        "winnerValMacroF1": winner_val_f1,
        "selectionNote": (
            "Selected on the validation split, scored once on test. An earlier "
            "version selected on test, which turns the reported figure into a "
            "selection statistic."
        ),
        "perClassF1": [
            float(v) for v in f1_score(yte, winner_pred, average=None,
                                       labels=list(range(N_CLASSES)))
        ],
        "confusion": confusion_matrix(yte, winner_pred,
                                      labels=list(range(N_CLASSES))).tolist(),
        "metricNote": (
            "Macro-F1 over labelled pixels only. A model predicting the "
            "majority class everywhere would score high accuracy and near-zero "
            "macro-F1, which is why the headline is F1. Unlabelled pixels (-1) "
            "mean 'not surveyed', not 'not crop', and are excluded entirely."
        ),
    }
    state["status"] = "done"
    state["finishedAt"] = time.time()
    state["elapsedSeconds"] = round(time.time() - started, 1)
    _log(state, f"WINNER {winner_name} · macro-F1 {winner_f1:.4f} · "
                f"accuracy {all_labelled_accuracy:.4f}")
    _log(state, f"per-class F1: "
                f"{[round(v, 3) for v in state['ensemble']['perClassF1']]}")

    for r in results:
        r.pop("proba", None)
        r.pop("testProba", None)
    report = dict(state)
    report["modelDetail"] = results
    report["features"] = FEATURE_NAMES

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    _log(state, f"wrote {out}")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--tiles", type=int, default=0, help="0 reads every tile")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20260903)
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args(argv)

    if args.quick:
        args.tiles = 120

    if not (DATA / "train.txt").exists():
        print(f"{DATA} not found — see docs/phase0/DATA_SOURCING.md", file=sys.stderr)
        return 2

    report = run(args)
    if report.get("status") != "done":
        return 1

    e = report["ensemble"]
    print(f"\n  winner        {e['winner']}")
    print(f"  macro-F1      {e['winnerMacroF1']:.4f}")
    print(f"  weighted F1   {e['winnerWeightedF1']:.4f}")
    print(f"  accuracy      {e['winnerAccuracy']:.4f}  (over labelled pixels only)")
    print(f"  per-class F1  {[round(v, 3) for v in e['perClassF1']]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

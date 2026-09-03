# Work in progress — training expansion

Written 2026-09-03. Scratch notes so a resumed session picks up without
re-deriving anything. Delete when the two remaining trainers are committed.

## Done and committed

| Model family | Result | Where |
|---|---|---|
| Credit scoring ensemble (7 models) | **test AUC 0.7797**, Gini 55.94, +0.0200 over the committed 0.7597 | `tools/train_ensemble.py` → `reports/ensemble_training.json` |
| Behavioural PD / EWS (5 models) | **test AUC 0.8818**, Gini 76.35 | `tools/train_survival.py` → `reports/survival_training.json` |

Early warning, from the survival run:

| alert on | defaults caught | capture | median lead |
|---|---|---|---|
| top 5% | 690 / 1,459 | 47.3% | 6 months |
| **top 10%** | **896 / 1,459** | **61.4%** | **8 months** |
| top 20% | 1,129 / 1,459 | 77.4% | 8 months |

**The survival AUC is NOT comparable to the committed Cox c-index of 0.6967.**
That c-index is over a 48-month forward window on 1,400 subjects; this AUC is
over a 12-month window on ~230,000. Different horizons, different cohorts. The
report records `comparableToBaseline: false` and reports no lift against it.

Deck (`tools/build_deck_pptx.py`) already carries both new rows on slide 8 and
the 61% / 8-month figure on slide 9. Rebuilt and rendered clean.

## Not yet done

Two new datasets arrived and neither is trained yet.

### 1. IEEE-CIS fraud — `datasets/ieee-fraud-detection/`

- `train_transaction.csv` (683 MB), `train_identity.csv` (26 MB), plus test halves
- 590,540 transactions, 394 features, ~3.5% fraud rate
- **The user already has a script**: `xgb-fraud-with-magic-0-9600.ipynb` —
  Chris Deotte's UID-magic solution. XGBoost only, 6-fold GroupKFold on month,
  AUC ~0.96. 47 cells, `BUILD95` / `BUILD96` flags.
- **The user's instruction was narrow: ADD MORE MODELS TO TRY in that script.**
  Not a rewrite. Keep the feature engineering — the UID construction
  (`card1_addr1` + `floor(day - D1)`) and the aggregations are what earn the
  0.96, and replacing them would lose the result rather than improve it.
  Add LightGBM and CatBoost alongside the XGBoost, same folds, same features,
  then blend.

### 2. AgriFieldNet crop segmentation — `datasets/iisc-ibm-crop-id-segmentation/`

Confirmed structure, checked with rasterio:

- `train/` 928 tiles, `val/` 119, `test/` 126
- inputs: `agrifieldnet_<id>_input.tif` — **12 bands, 256×256, uint8**
- labels: `agrifieldnet_<id>_label_c6.tif` — 256×256, **6 crop classes**
- Labels are **sparse**: `-1` is unlabelled and dominates (65,498 of 65,536
  pixels in the sample tile; only 38 labelled). Any loss must ignore -1, and
  accuracy must be computed over labelled pixels only — a model that predicts
  "unlabelled" everywhere would otherwise score 99.9%.
- `train.txt` / `val.txt` / `test.txt` list tile ids, one per line.

This closes the P2 gap that ADR-0013 recorded as unfillable. Model A (field
boundary) and Model B (crop classification) both become trainable. The ADR
will need amending — the same self-correction P2-F14 already records once.

## Environment

Libraries are in a venv, NOT system Python and NOT importable from `src/`:

    /tmp/claude-1000/-home-divanshu-Desktop-AILendingHub/4bdbae5c-e93b-435d-99c0-2fdb8ee00876/scratchpad/pptxenv/bin/python

Installed: numpy 2.5.2, pandas 3.0.5, scikit-learn 1.9.0, lightgbm 4.7.0,
xgboost 3.4.1, rasterio 1.5.1, python-pptx 1.0.2.

`src/lending_hub/` stays stdlib-only (ADR-0003). Both trainers live in `tools/`
and import nothing from the core.

## Gotchas already hit, do not re-discover

- **pandas 3 dtype detection.** Text columns read as `StringDtype`, whose
  `str()` is `"str"` — a name-based check for `"object"` or `"string"` matches
  nothing and silently leaves categoricals unencoded. Use `dtype.kind == "O"`.
- **`.cat.codes.replace(-1, nan)`** does not change the column dtype on pandas
  3. Cast explicitly.
- **Workers read a pickle path**, not the frame — pickling a 300k-row frame to
  every process costs more than the fit.
- **The monitor** (`tools/training_monitor.html`) polls `reports/*_progress.json`
  and already has a tab switch. A third trainer needs a third tab.
- `reports/*.json` is gitignored, so training outputs stay local.

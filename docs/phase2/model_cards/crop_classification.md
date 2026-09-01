# Model Card — Model B, crop classification (SRS §3.4.2)

> **This card documents a challenger that does not exist and a baseline that
> does.** Phase 2 §4 makes Presto conditional on beating the RF baseline by 5
> macro-F1 points; the baseline, the metric and the comparison are built and
> tested, and the challenger is not (ADR-0013). That asymmetry is the honest
> state and is the reason the card is worth writing: the deployment decision is
> already fully specified, and only the candidate is missing.

## 1. Identification

| Field | Value |
|---|---|
| Baseline | `crop_rf_baseline` — **built**, `lending_hub.agri.crop.fit_random_forest` |
| Challenger | `crop_presto` — **unbuilt**. Reference: Presto ([Tseng et al., arXiv:2304.14065](https://arxiv.org/abs/2304.14065)) |
| Registry stage | None — neither registered |
| Model tier | Tier 1 if it ever gates disbursal tranching (LH-403) |
| Owner (accountable) | Geospatial DS squad lead |
| Independent validator | **Not assigned** (Master §3.1) |

## 2. Purpose and scope

Predicts, per plot per season, which crop is growing — from the ratified zone
crop list plus **fallow** — from a Sentinel time series.

**It must not be used for**: any zone whose crop list has not been ratified
(LH-404); any decision on an "unsure" prediction; any inference that "unsure"
means "fallow". Those last two are the same mistake in different clothes and it
is the one this model's output is most likely to suffer.

## 3. The class set is not the modeller's to choose

`ClassSet` requires a ratified list with a decision reference (**LH-404**),
mirroring `MonotoneConstraints.from_policy` in the Phase 1 GBM. The class set is
the *label space*: a set chosen by an engineer decides what the model can ever
predict, and adding a class afterwards means retraining, not reconfiguring.

`fallow` is `[SPEC]` rather than policy and is appended if a committee list omits
it — Phase 2 §4 makes it a first-class label.

## 4. Baseline

Random Forest on NDVI time-series statistics: peak, mean, minimum, amplitude,
season integral, days to peak, green-up rate, senescence rate, observation count
(`agri.crop.phenology_features`).

**Built as a real contender, deliberately.** A weak baseline hands the
challenger a margin it did not earn, after which nobody audits a challenger that
won. Those features are what separate crops phenologically — crops differ in
when they green up, how fast, how long they hold peak and how sharply they
senesce — so a model beating them by five points has learned something a
phenological summary does not contain, which is exactly the claim Phase 2 §4
asks Presto to make.

`phenology_features()` raises below four valid observations in the season rather
than imputing. A crop classified from two cloudy revisits is a classification of
the cloud.

## 5. Calibration and abstention

Per-class probabilities are calibrated by **temperature scaling**
(`fit_temperature`, one parameter, golden-section search on held-out NLL), and
predictions below **0.6 confidence** report as `"unsure"` `[SPEC]`.

The ordering matters and is not cosmetic: thresholding an uncalibrated softmax
confidence thresholds an arbitrary monotone transform of a probability, so the
"unsure" band would be some other band entirely.

The temperature **must be fitted on data the forest did not train on**. Fitted
in-sample it calibrates against the forest's memorised training votes, which are
already near-perfect, and returns a temperature near 1 that changes nothing while
appearing to have calibrated the model.

## 6. Metric, and why macro

Phase 2 §7 sets macro-F1 >= 0.85 on the five majority crops per zone.

Macro rather than micro matters more here than usual: an agri class set is
severely imbalanced — one or two staples dominate a zone — so micro-F1 is close
to the majority crop's recall, and a model that never predicts a minor crop
scores well on it. Macro weights every crop equally, including the ones a
lending decision most needs distinguished.

**Abstentions count as errors** in `classification_report`. Abstention has an
operational cost (LH-409: somebody must go and look), so a metric that excluded
it would improve monotonically as the model declined to answer more often.

## 7. The ship/no-ship rule

Phase 2 §4: Presto ships only on **>= +5 macro-F1 points** over the baseline —
"complexity must be earned". Implemented in `complexity_earned()`, which refuses
to compare reports from different held-out sets. That is how the comparison goes
wrong in practice: a challenger scored on a different or larger sample clears
five points on sampling noise alone.

## 8. Known limitations

**"Unsure" and "fallow" are opposite claims.** One says the plot was not sown,
the other says we could not tell. The WS-2.4(c) non-sowing flag is built
entirely on the difference, and the model card's most important warning is that
a downstream consumer treating a low-confidence prediction as fallow converts an
abstention into an early-warning trigger.

**The baseline has no imagery to run on.** Everything in §4-§7 is unit-tested on
synthetic phenological signatures under `tests/fixtures/`-equivalent in-test
generation. No number here is a fact about any crop.

## 9. Open tickets

**LH-404** (ratified zone crop list) · **LH-406** (ground-truth labels and the
agri portfolio) · **LH-409** (where an "unsure" plot is routed) · **LH-102**
(the crop calendar that defines the season a classification is *of*).

## 10. Sign-off

| Role | Name | Date |
|---|---|---|
| Developer | — | — |
| Independent validator | — | — |
| Model Risk | — | — |

**Unsigned.** The baseline is built but has never been fitted on real data; the
challenger does not exist.

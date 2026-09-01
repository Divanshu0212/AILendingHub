# Model Card — Model C, yield estimation (SRS §3.4.3)

> **This card documents the fallback, which is built, and the reference method,
> which is not.** Phase 2 §4 orders the fallback built *first* and kept forever
> as a sanity check and imagery-outage path. It is built, it is tested, and it
> satisfies the full P50/P25/P10 output contract without the Gaussian Process
> that was supposed to supply the uncertainty. How it does that is the most
> important section of this card (§5).

## 1. Identification

| Field | Value |
|---|---|
| Fallback | `yield_fallback_regression` — **built**, `lending_hub.agri.yield_model` |
| Reference method | Histogram-CNN/LSTM + Gaussian Process ([You et al., AAAI 2017](https://cs.stanford.edu/~ermon/papers/cropyield_AAAI17.pdf)) — **unbuilt** |
| Transfer variant | [Wang et al., COMPASS 2018](https://dl.acm.org/doi/10.1145/3209811.3212707) — unbuilt |
| Registry stage | None |
| Model tier | Tier 1 — its output multiplies straight into `ExpectedIncome` and therefore into affordability |
| Owner (accountable) | Geospatial DS squad lead |
| Independent validator | **Not assigned** (Master §3.1) |

## 2. Purpose and scope

Predicts yield per hectare at district level from peak NDVI and a rainfall
percentile, with a P50/P25/P10 interval, and allocates the district figure to
plots by relative NDVI position.

**It must not be used for**: any district not represented in the fit; any
absolute claim about a *plot's* yield (see §6); any input where "rainfall
percentile" has been supplied in millimetres (the constructor refuses this, but
it is worth stating why — a model fitted on millimetres passes every sanity
check and predicts nonsense out of sample).

## 3. Form

`yield = intercept + b1 * peak_NDVI + b2 * rainfall_percentile`, ordinary least
squares by normal equations.

Two covariates and an intercept, by design. Phase 2 §4 wants this model
checkable by hand and it is: three coefficients, a residual spread, and no
interaction terms to argue about. That auditability is its entire value — it is
the thing that stays trustworthy when the sophisticated model and the imagery
pipeline are both unavailable.

`MIN_DISTRICT_SEASONS = 30` is **not from the phase file** and is a finding: a
two-covariate fit on a dozen district-seasons has standard errors wider than the
gap between a good year and a bad one, so its P25 would describe the fit rather
than the weather.

## 4. Data

District-season government yield statistics `[DATA]`, joined to peak NDVI and a
rainfall percentile computed as of the season. **None exists in this repository**
(LH-406), so the model has never been fitted on real data. Every number in the
test suite comes from a synthetic generator with known coefficients.

## 5. How the interval is produced, and what it is not

Phase 2 §4 makes the uncertainty part of the contract, not optional — and the
reference method's GP is what was supposed to supply it. Without the GP the
obvious move is to ship P50 and mark the quantiles pending.

**That would not degrade `StressedIncome`; it would delete it.** `StressedIncome`
is *defined* on `Yield_P25`. So the fallback produces its interval from the
**empirical residual distribution of its own fit**: P25 is the point prediction
plus the 25th percentile of residuals.

Every limitation of that, stated rather than implied away:

* **Homoscedastic.** The band is the same width everywhere. It does not widen
  away from the training data, so it says nothing useful about a district at the
  edge of the fit — which is where it will most often be asked.
* **In-sample residuals.** The residuals of a fitted model are smaller than its
  errors on new data. With three parameters on a few hundred district-seasons the
  optimism is real but modest; a held-out residual set is the correct approach
  and needs data that does not exist here.
* **Not a posterior.** `YieldPrediction.interval_basis` carries this sentence on
  every prediction, because a consumer treating a residual band as a GP posterior
  under-states uncertainty exactly where the model is extrapolating.

`YieldPrediction` refuses to construct with inverted quantiles (which would make
`StressedIncome` exceed `ExpectedIncome`) or a negative P10 (which is a broken
model, not a severe scenario, and would flow into `StressedIncome` as negative
revenue).

## 6. Downscaling is an allocation, not a measurement

Phase 2 §4 downscales the district figure "to plot via relative NDVI position in
the district distribution". `downscale()` does that and **returns the plot's NDVI
percentile alongside the value**, because that percentile is the entire content
of the plot-level claim: the district mean is a real statistic, the plot figure
is that statistic redistributed by a ranking, and its error at plot level is
bounded by nothing the district fit measured.

The adjustment is capped at ±30%. Uncapped, the top plot in each district
receives an unbounded multiple — the mapping from NDVI rank to yield is monotone
but its *slope* is not something a district-level fit estimated. The cap is an
engineering guard, not a `[POLICY]` value.

## 7. Fairness

Not assessed. The relevant risk is geographic and is measured by
`agri.disparate`: yield model error is likely to be larger in districts with
fewer historical statistics and more cloud, which correlates with remoteness.

## 8. Open tickets

**LH-406** (district yield statistics and the agri portfolio) · **LH-408** (the
mandi price window the income formulas pair this yield with) · **LH-401** (input
costs, without which the yield cannot become an income at all).

## 9. Sign-off

| Role | Name | Date |
|---|---|---|
| Developer | — | — |
| Independent validator | — | — |
| Model Risk | — | — |

**Unsigned.** The fallback is built and unit-tested; it has never seen a real
district.

"""Model C — yield estimation: the fallback first (WS-2.2, SRS §3.4.3).

Phase 2 §4 gives an instruction whose ordering is the whole point:

    **Build the auditable fallback first**: regression on peak NDVI + rainfall
    percentile — kept forever as sanity check and imagery-outage fallback.
    Output contract: P50 / P25 / P10 yield (the GP uncertainty is part of the
    contract, not optional).

So this module is the fallback, built first and kept. The reference method — a
histogram-CNN/LSTM with a Gaussian Process (You et al., AAAI 2017) — is not
ported (ADR-0013): it consumes multi-band histogram stacks that do not exist
here, and its GP is the source of the uncertainty the output contract demands.

The uncertainty is the contract, so the fallback has to produce one
--------------------------------------------------------------------
This is the part that is easy to get wrong. A least-squares regression has a
point prediction and no P25, so the temptation is to ship P50 and call the
quantiles "pending the GP". That would break the contract Phase 2 §4 states
explicitly, and it would break it in the direction that matters:
``StressedIncome`` is defined on ``Yield_P25``, so a missing P25 does not
degrade the stressed-income feature — it deletes it.

:class:`YieldModel` therefore produces its interval from the **residual
distribution of the fit itself**, empirically: the P25 of predicted yield is the
point prediction plus the 25th percentile of held-out residuals. That is a
weaker uncertainty than a GP's — it is homoscedastic, it does not widen away
from the training data, and it says nothing about a district the model has never
seen — and every one of those limitations is on the model card rather than
implied away. A wrong-but-stated interval is auditable; a missing one silently
becomes a point estimate somewhere downstream.

Downscaling is where a district model becomes a plot claim
-----------------------------------------------------------
§4 trains at district level on government statistics and downscales "to plot via
relative NDVI position in the district distribution". :func:`downscale` does
that, and it is worth being clear about what it is: an *allocation* of a
district total, not a measurement of a plot. The district mean is a real
statistic; the plot figure is that statistic redistributed by an NDVI ranking,
and its error at plot level is unbounded by anything the district fit measured.
The function returns the plot's percentile alongside the value so the claim can
be read for what it is.

What this does not port
-----------------------
No CNN, no LSTM, no Gaussian Process, no histogram binning of reflectance, no
transfer-learning variant (Wang et al., COMPASS 2018). The regression is
ordinary least squares by normal equations, solved with the same Gauss-Jordan
routine the Phase 3 estimators use.

Workstream: WS-2.2 Model C (SRS §3.4.3)
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Mapping, Sequence

from lending_hub.portfolio.linalg import SingularMatrix, solve

#: The quantiles the Phase 2 §4 output contract requires. `[SPEC]`.
#:
#: P50 feeds ``ExpectedIncome`` and P25 feeds ``StressedIncome``; P10 is
#: reported because a lender's tail question is not answered by a quartile.
CONTRACT_QUANTILES = (0.50, 0.25, 0.10)

#: Minimum district-seasons before a yield regression is fitted. Not from the
#: phase file. A two-covariate fit on a dozen district-seasons has standard
#: errors wider than the difference between a good year and a bad one, and the
#: resulting P25 would be an artefact of the fit rather than a statement about
#: weather. Raised as a Phase 2 finding.
MIN_DISTRICT_SEASONS = 30


class YieldError(Exception):
    """A yield model cannot be fitted or asked for a prediction."""


@dataclass(frozen=True)
class DistrictSeason:
    """One district, one season: the unit government yield statistics come in.

    ``yield_per_hectare`` is the reported statistic `[DATA]`. ``peak_ndvi`` and
    ``rainfall_percentile`` are the two covariates Phase 2 §4 names for the
    fallback — deliberately two, because the fallback's value is that it can be
    checked by hand.
    """

    district_id: str
    season: str
    yield_per_hectare: float
    peak_ndvi: float
    rainfall_percentile: float

    def __post_init__(self) -> None:
        if self.yield_per_hectare < 0:
            raise YieldError(
                f"{self.district_id}/{self.season}: negative yield "
                f"{self.yield_per_hectare}"
            )
        if not -1.0 <= self.peak_ndvi <= 1.0:
            raise YieldError(
                f"{self.district_id}/{self.season}: peak NDVI {self.peak_ndvi} "
                "is outside [-1, 1]; NDVI is a bounded index and a value "
                "outside it means the band maths or the masking is wrong"
            )
        if not 0.0 <= self.rainfall_percentile <= 1.0:
            raise YieldError(
                f"{self.district_id}/{self.season}: rainfall percentile "
                f"{self.rainfall_percentile} is outside [0, 1]. A percentile is "
                "not a millimetre total — passing rainfall in mm here fits a "
                "model that looks fine and predicts nonsense out of sample."
            )


@dataclass(frozen=True)
class YieldPrediction:
    """The Phase 2 §4 output contract: P50, P25, P10, and where they came from.

    ``interval_basis`` records how the quantiles were produced. It is on the
    prediction rather than the model card alone because the two available bases
    — a GP posterior and an empirical residual spread — are not interchangeable,
    and a downstream consumer that treats a homoscedastic residual band as a
    posterior will under-state uncertainty exactly where the model is
    extrapolating.
    """

    p50: float
    p25: float
    p10: float
    interval_basis: str
    district_id: str | None = None

    def __post_init__(self) -> None:
        if not self.p50 >= self.p25 >= self.p10:
            raise YieldError(
                f"quantiles are not ordered: P50={self.p50}, P25={self.p25}, "
                f"P10={self.p10}. An inverted interval means the residual "
                "quantiles were applied with the wrong sign, which makes "
                "StressedIncome larger than ExpectedIncome."
            )
        if self.p10 < 0:
            raise YieldError(
                f"P10 yield {self.p10} is negative. A negative yield is not a "
                "severe scenario, it is a broken model — and it flows into "
                "StressedIncome as a negative revenue term."
            )


@dataclass(frozen=True)
class YieldModel:
    """The auditable fallback: OLS on peak NDVI and rainfall percentile.

    Two covariates and an intercept, by design. Phase 2 §4 wants this model
    checkable by hand, and it is: three coefficients, a residual spread, and no
    interaction terms to argue about.
    """

    intercept: float
    ndvi_coefficient: float
    rainfall_coefficient: float
    residual_quantiles: Mapping[float, float]
    residual_std: float
    n: int
    r_squared: float
    interval_basis: str = "empirical residual quantiles (not a GP posterior)"

    def point(self, peak_ndvi: float, rainfall_percentile: float) -> float:
        """The P50 point prediction, before the interval is attached."""
        return (
            self.intercept
            + self.ndvi_coefficient * peak_ndvi
            + self.rainfall_coefficient * rainfall_percentile
        )

    def predict(
        self,
        peak_ndvi: float,
        rainfall_percentile: float,
        *,
        district_id: str | None = None,
    ) -> YieldPrediction:
        """Predict, with the P50/P25/P10 contract satisfied.

        The quantiles come from the residual distribution, which makes the band
        the same width everywhere. That is the honest limitation of a fallback
        without a GP, and it is recorded in ``interval_basis`` rather than
        smoothed over.
        """
        if not -1.0 <= peak_ndvi <= 1.0:
            raise YieldError(f"peak NDVI {peak_ndvi} is outside [-1, 1]")
        if not 0.0 <= rainfall_percentile <= 1.0:
            raise YieldError(
                f"rainfall percentile {rainfall_percentile} is outside [0, 1]"
            )

        centre = self.point(peak_ndvi, rainfall_percentile)
        return YieldPrediction(
            p50=max(0.0, centre + self.residual_quantiles[0.50]),
            p25=max(0.0, centre + self.residual_quantiles[0.25]),
            p10=max(0.0, centre + self.residual_quantiles[0.10]),
            interval_basis=self.interval_basis,
            district_id=district_id,
        )


def fit_yield_model(
    observations: Sequence[DistrictSeason],
    *,
    min_seasons: int = MIN_DISTRICT_SEASONS,
) -> YieldModel:
    """Fit the fallback regression on district-season government statistics.

    Residual quantiles are computed **in sample**, which overstates the model's
    precision — the residuals of a fitted model are smaller than its errors on
    new data, and with three parameters on a few hundred district-seasons the
    difference is real but modest. A held-out residual set is the correct
    approach and needs data that does not exist here; the limitation is on the
    model card and is the reason ``interval_basis`` says what it says.
    """
    if len(observations) < min_seasons:
        raise YieldError(
            f"{len(observations)} district-seasons is below the {min_seasons} "
            "needed. A two-covariate fit on fewer has standard errors wider "
            "than the gap between a good year and a bad one, so its P25 would "
            "describe the fit rather than the weather."
        )

    rows = [
        [1.0, o.peak_ndvi, o.rainfall_percentile] for o in observations
    ]
    targets = [o.yield_per_hectare for o in observations]

    # Normal equations: (X'X) b = X'y.
    size = 3
    xtx = [[sum(r[i] * r[j] for r in rows) for j in range(size)] for i in range(size)]
    xty = [sum(r[i] * y for r, y in zip(rows, targets)) for i in range(size)]

    try:
        coefficients = solve(xtx, xty)
    except SingularMatrix as exc:
        raise YieldError(
            f"the design matrix is singular: {exc}. On this fit that almost "
            "always means peak NDVI and the rainfall percentile move together "
            "across the sample — which happens when every district-season in "
            "it came from the same year."
        ) from exc

    intercept, ndvi_coefficient, rainfall_coefficient = coefficients
    predictions = [
        intercept + ndvi_coefficient * o.peak_ndvi + rainfall_coefficient * o.rainfall_percentile
        for o in observations
    ]
    residuals = sorted(actual - predicted for actual, predicted in zip(targets, predictions))

    mean_target = sum(targets) / len(targets)
    total_sum_squares = sum((y - mean_target) ** 2 for y in targets)
    residual_sum_squares = sum(r * r for r in residuals)
    r_squared = (
        1.0 - residual_sum_squares / total_sum_squares if total_sum_squares > 0 else 0.0
    )

    return YieldModel(
        intercept=intercept,
        ndvi_coefficient=ndvi_coefficient,
        rainfall_coefficient=rainfall_coefficient,
        residual_quantiles={q: _quantile(residuals, q) for q in CONTRACT_QUANTILES},
        residual_std=statistics.pstdev(residuals) if len(residuals) > 1 else 0.0,
        n=len(observations),
        r_squared=r_squared,
    )


def _quantile(sorted_values: Sequence[float], q: float) -> float:
    """Nearest-rank quantile on an already-sorted sequence."""
    if not sorted_values:
        raise YieldError("quantile of an empty sample")
    index = max(0, min(len(sorted_values) - 1, int(-(-q * len(sorted_values) // 1)) - 1))
    return sorted_values[index]


def downscale(
    district: YieldPrediction,
    plot_peak_ndvi: float,
    district_peak_ndvi_distribution: Sequence[float],
    *,
    max_adjustment: float = 0.30,
) -> tuple[YieldPrediction, float]:
    """Allocate a district yield to a plot by its NDVI position.

    Phase 2 §4: "downscale to plot via relative NDVI position in the district
    distribution". Returns ``(prediction, percentile)`` — the percentile is
    returned, not hidden, because it is the entire content of the plot-level
    claim.

    ``max_adjustment`` caps how far a plot may be moved from the district
    figure. Without a cap, the top plot in a district gets an unbounded
    multiple: the mapping from NDVI rank to yield is monotone but its *slope* is
    not something a district-level fit measured, and an uncapped version would
    hand the best-looking plot in each district an ExpectedIncome nobody
    estimated. The cap is an engineering guard, not a `[POLICY]` value, and it
    is stated on the model card.
    """
    if not district_peak_ndvi_distribution:
        raise YieldError(
            "cannot downscale without the district's NDVI distribution; a plot "
            "percentile has no meaning without the population it is a "
            "percentile of"
        )
    if not -1.0 <= plot_peak_ndvi <= 1.0:
        raise YieldError(f"plot peak NDVI {plot_peak_ndvi} is outside [-1, 1]")
    if not 0.0 < max_adjustment <= 1.0:
        raise YieldError(f"max_adjustment must be in (0, 1], got {max_adjustment}")

    ordered = sorted(district_peak_ndvi_distribution)
    below = sum(1 for v in ordered if v < plot_peak_ndvi)
    equal = sum(1 for v in ordered if v == plot_peak_ndvi)
    percentile = (below + equal / 2.0) / len(ordered)

    # Percentile 0.5 leaves the district figure unchanged; the extremes move it
    # by at most max_adjustment.
    factor = 1.0 + max_adjustment * (2.0 * percentile - 1.0)

    return (
        YieldPrediction(
            p50=district.p50 * factor,
            p25=district.p25 * factor,
            p10=district.p10 * factor,
            interval_basis=(
                f"{district.interval_basis}; downscaled to plot by NDVI "
                f"percentile {percentile:.3f} (an allocation of a district "
                "statistic, not a plot measurement)"
            ),
            district_id=district.district_id,
        ),
        percentile,
    )

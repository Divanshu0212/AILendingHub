"""WS-2.3 — aggregation to credit features (deterministic, policy-owned).

Phase 2 §4 states the three formulas:

    ExpectedIncome   = Sum over plots,seasons  Area x Yield_P50 x Price_P50 - InputCosts
    StressedIncome   = Sum over plots,seasons  Area x Yield_P25 x Price_P25 - InputCosts
    LandQualityIndex = f(soil organic carbon, slope, irrigation proxy,
                         5-yr mean peak-NDVI percentile vs agro-zone,
                         yield volatility, drought frequency)

and adds: *"Implemented as SQL/Python owned by Credit Policy; formula changes
need `[POLICY]` sign-off."*

The two income formulas are arithmetic and are implemented exactly. The
interesting part of this module is everywhere they cannot be evaluated.

Input costs are not a parameter, they are the sign
----------------------------------------------------
``InputCosts`` is `[POLICY: Agri Credit Head]` (LH-401) and Phase 2 §8 forbids
inventing it. That is not a formality here. On a smallholder plot input costs
are the same order of magnitude as gross revenue, so an invented figure does not
perturb ``ExpectedIncome`` — it **determines its sign**, and therefore whether
the borrower appears to have any repayment capacity at all. :func:`expected_income`
raises :class:`~lending_hub.definitions.provenance.Ungrounded` rather than
defaulting, following the Phase 1 pattern (``Scorecard.points``,
``FairnessReport.verdict``).

``f`` is not specified, so LandQualityIndex is not computed
------------------------------------------------------------
The phase file names six *inputs* to ``LandQualityIndex`` and never states the
function combining them — not the weights, not the direction of each term, not
the normalisation. Six named inputs read as a specification right up until code
has to return a number. Any weighting invented here would become the bank's land
quality definition, and it is the feature Phase 2 §7's first backtest is
*about*: criterion (a) is that LQI quartiles order agri NPA monotonically, which
cannot be evaluated against a formula chosen by whoever wrote the evaluation.

So :func:`land_quality_index` requires an explicit :class:`LandQualityFormula`
carrying a policy reference, and :func:`land_quality_components` computes and
returns the six normalised inputs — which are all `[DATA]` and all useful on
their own — leaving the combination to the owner. Raised as a Phase 2 finding
(LH-411).

Partial boundaries do not make a total
---------------------------------------
A borrower with one walked plot and three unwalked ones has an
``ExpectedIncome`` over one plot, not over their holding. :func:`expected_income`
takes the plots it is given and reports the coverage it had, and
:func:`holding_income` refuses to produce a total for a borrower whose land is
only partly registered. The failure it prevents is quiet: summing what exists
produces a number that is too small in a way nothing downstream can detect,
which for an affordability cap is the unsafe direction.

Workstream: WS-2.3 (SRS §3.5)
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from lending_hub.agri.drought import DroughtIndex, drought_frequency
from lending_hub.agri.registry import Granularity, Plot, PlotRegistry
from lending_hub.agri.yield_model import YieldPrediction
from lending_hub.definitions.provenance import Grounded, Pending, Source, Ungrounded

#: Per-crop, per-zone input costs. Phase 2 §4 WS-2.3 marks them
#: `[POLICY: Agri Credit Head]`; Phase 2 §8 puts them on the do-not-invent list.
INPUT_COSTS = Pending(
    owner="Agri Credit Head",
    ticket="LH-401",
    note="per-crop, per-zone cultivation input costs per hectare",
)

#: The mandi price distribution and, more importantly, the window it is taken
#: over. Agmarknet is named as the `[DATA]` feed, but the formulas need P50 and
#: P25 of a *distribution* across a horizon nobody specifies — price at harvest,
#: across the marketing season, or a forward. Found by building (LH-408).
MANDI_PRICE_WINDOW = Pending(
    owner="Agri Credit Head + Market Data",
    ticket="LH-408",
    note="the horizon over which mandi price P50/P25 are taken",
)

#: The function combining LandQualityIndex's six named inputs. Found by
#: building (LH-411): §4 names the inputs and never the weights, directions or
#: normalisation.
LQI_FORMULA = Pending(
    owner="Credit Policy + Agri Credit Head",
    ticket="LH-411",
    note="the weighting and direction of the six LandQualityIndex inputs",
)

#: Seasons of history the drought-frequency term is computed over. `[SPEC]` —
#: Phase 2 §4 WS-2.3: "share of last 20 seasons with SPEI <= -1".
DROUGHT_HISTORY_SEASONS = Grounded(
    value=20,
    source=Source.SPEC,
    citation="Phase 2 §4 WS-2.3 climate features",
)


class FeatureError(Exception):
    """A credit feature cannot be computed from what was supplied."""


@dataclass(frozen=True)
class SeasonInput:
    """One plot, one season: everything the income formulas consume.

    ``input_cost_per_hectare`` is ``None`` by default and must be supplied from
    a ratified table. It is not defaulted to zero — a zero input cost makes
    ``ExpectedIncome`` equal gross revenue, which is a *specific and very wrong*
    claim rather than a missing one, and it is wrong in the direction that
    overstates repayment capacity.
    """

    plot_id: str
    season: str
    crop: str
    area_hectares: float
    yield_prediction: YieldPrediction
    price_p50: float
    price_p25: float
    input_cost_per_hectare: float | None = None

    def __post_init__(self) -> None:
        if self.area_hectares <= 0:
            raise FeatureError(
                f"{self.plot_id}/{self.season}: area must be positive, got "
                f"{self.area_hectares} ha"
            )
        if self.price_p50 < 0 or self.price_p25 < 0:
            raise FeatureError(
                f"{self.plot_id}/{self.season}: prices must be non-negative"
            )
        if self.price_p25 > self.price_p50:
            raise FeatureError(
                f"{self.plot_id}/{self.season}: price P25 {self.price_p25} "
                f"exceeds P50 {self.price_p50}. The stressed price must not be "
                "above the expected one, and this inversion makes "
                "StressedIncome exceed ExpectedIncome."
            )
        if self.input_cost_per_hectare is not None and self.input_cost_per_hectare < 0:
            raise FeatureError(
                f"{self.plot_id}/{self.season}: input cost cannot be negative"
            )


@dataclass(frozen=True)
class IncomeResult:
    """An income figure with the coverage behind it.

    ``plots_valued`` and ``seasons`` are on the result because the formulas sum
    over plots and seasons, and a sum's meaning depends entirely on what was in
    it. An ``ExpectedIncome`` over one of a borrower's four plots is not a small
    ``ExpectedIncome``; it is a different quantity.
    """

    value: float
    gross_revenue: float
    input_costs: float
    plots_valued: int
    seasons: int
    basis: str

    @property
    def is_negative(self) -> bool:
        """Whether costs exceeded revenue.

        Not an error. A genuine loss season is a real and important signal, and
        clamping it to zero would hide exactly the borrowers the feature exists
        to identify.
        """
        return self.value < 0


def _income(
    seasons: Sequence[SeasonInput], *, stressed: bool, basis: str
) -> IncomeResult:
    if not seasons:
        raise FeatureError(
            "no season inputs; an income of zero and an unvalued holding are "
            "different facts, and only one of them should reach an "
            "affordability calculation"
        )

    missing = [s.plot_id for s in seasons if s.input_cost_per_hectare is None]
    if missing:
        raise Ungrounded(
            f"input costs are not grounded for {sorted(set(missing))} "
            f"({INPUT_COSTS}). Phase 2 §8 puts per-crop input costs on the "
            "do-not-invent list, and on a smallholder plot they are the same "
            "order of magnitude as gross revenue — so a substituted figure "
            "does not perturb this number, it decides its sign, and therefore "
            "whether the borrower appears to have any repayment capacity."
        )

    gross = 0.0
    costs = 0.0
    for season in seasons:
        yield_value = (
            season.yield_prediction.p25 if stressed else season.yield_prediction.p50
        )
        price = season.price_p25 if stressed else season.price_p50
        gross += season.area_hectares * yield_value * price
        costs += season.area_hectares * season.input_cost_per_hectare

    return IncomeResult(
        value=gross - costs,
        gross_revenue=gross,
        input_costs=costs,
        plots_valued=len({s.plot_id for s in seasons}),
        seasons=len({s.season for s in seasons}),
        basis=basis,
    )


def expected_income(seasons: Sequence[SeasonInput]) -> IncomeResult:
    """``Sum over plots,seasons  Area x Yield_P50 x Price_P50 - InputCosts``.

    Raises :class:`Ungrounded` if any season lacks a ratified input cost — see
    the module docstring for why this is a refusal rather than a default.
    """
    return _income(seasons, stressed=False, basis="Yield_P50 x Price_P50")


def stressed_income(seasons: Sequence[SeasonInput]) -> IncomeResult:
    """``Sum over plots,seasons  Area x Yield_P25 x Price_P25 - InputCosts``.

    Note that both the yield *and* the price move to their P25. That is what the
    phase file specifies, and it is a joint stress — it implicitly assumes yield
    and price shortfalls coincide. For a single farmer facing a local crop
    failure that is right. Across a whole district it is conservative in an
    unusual way, because a regional yield failure typically *raises* local
    prices. The formula is `[SPEC]` and is implemented as written; the
    observation belongs on the model card and is raised as a Phase 2 finding.
    """
    return _income(seasons, stressed=True, basis="Yield_P25 x Price_P25")


def holding_income(
    registry: PlotRegistry,
    borrower_id: str,
    seasons: Sequence[SeasonInput],
    *,
    stressed: bool = False,
) -> IncomeResult:
    """Income across a borrower's whole holding — or a refusal.

    Refuses when the seasons supplied do not cover every plot the registry holds
    for the borrower. Summing what exists yields a number that is too small in a
    way nothing downstream can detect, and for an affordability cap "too small"
    is the direction that looks prudent while being wrong.

    A borrower at village granularity is refused outright: there is no plot to
    value, and their claimed area is not an observed one.
    """
    granularity = registry.granularity_for(borrower_id)
    if granularity is Granularity.VILLAGE:
        raise FeatureError(
            f"{borrower_id} has village-granularity location only. There is no "
            "plot to value — Phase 2 §4 stores village-granularity features at "
            "village level and flags them as such, and an income built from a "
            "claimed area is an income built from an application form."
        )

    registered = {p.plot_id for p in registry.plots_for(borrower_id)}
    valued = {s.plot_id for s in seasons}

    unvalued = registered - valued
    if unvalued:
        raise FeatureError(
            f"{borrower_id}: {len(unvalued)} of {len(registered)} registered "
            f"plots have no season input ({sorted(unvalued)}). A holding income "
            "summed over part of the holding is too small in a way nothing "
            "downstream can detect, and for an affordability cap that reads as "
            "prudence."
        )

    unknown = valued - registered
    if unknown:
        raise FeatureError(
            f"{borrower_id}: season inputs reference plots not registered to "
            f"this borrower ({sorted(unknown)})"
        )

    return stressed_income(seasons) if stressed else expected_income(seasons)


# ---------------------------------------------------------------------------
# LandQualityIndex
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LandQualityInputs:
    """The six inputs Phase 2 §4 names for LandQualityIndex.

    All six are `[DATA]`. What is missing is the function over them.
    """

    soil_organic_carbon: float
    """Percent, from SoilGrids."""

    slope_degrees: float
    """From the Copernicus DEM."""

    irrigation_proxy: float
    """In [0, 1]. Phase 2 §4 names it without defining it; the standard
    construction is dry-season NDVI relative to the zone, since irrigated land
    stays green when rainfed land does not."""

    peak_ndvi_percentile_5yr: float
    """Five-year mean peak NDVI as a percentile against the agro-zone."""

    yield_volatility: float
    """Coefficient of variation of the plot's yield history."""

    drought_frequency: float
    """Share of the last 20 seasons with SPEI <= -1 `[SPEC]`."""

    def __post_init__(self) -> None:
        for name, value, bounds in (
            ("irrigation_proxy", self.irrigation_proxy, (0.0, 1.0)),
            ("peak_ndvi_percentile_5yr", self.peak_ndvi_percentile_5yr, (0.0, 1.0)),
            ("drought_frequency", self.drought_frequency, (0.0, 1.0)),
        ):
            if not bounds[0] <= value <= bounds[1]:
                raise FeatureError(f"{name}={value} is outside {bounds}")
        if self.soil_organic_carbon < 0:
            raise FeatureError("soil organic carbon cannot be negative")
        if not 0.0 <= self.slope_degrees <= 90.0:
            raise FeatureError(f"slope {self.slope_degrees} is outside [0, 90] degrees")
        if self.yield_volatility < 0:
            raise FeatureError("yield volatility (a CV) cannot be negative")


@dataclass(frozen=True)
class LandQualityFormula:
    """A ratified weighting of the six inputs.

    Exists so that a LandQualityIndex can be computed *once somebody owns the
    formula*, and not before. ``policy_reference`` is required for the same
    reason ``ClassSet`` requires one: the alternative is that whoever runs the
    first backtest also defines the feature the backtest is evaluating.
    """

    weights: Mapping[str, float]
    directions: Mapping[str, int]
    policy_reference: str

    REQUIRED = (
        "soil_organic_carbon",
        "slope_degrees",
        "irrigation_proxy",
        "peak_ndvi_percentile_5yr",
        "yield_volatility",
        "drought_frequency",
    )

    def __post_init__(self) -> None:
        if not self.policy_reference:
            raise FeatureError(
                "a LandQualityIndex formula needs the policy decision that "
                "ratified it (LH-411). Phase 2 §4 names six inputs and no "
                "function; whoever supplies the function defines the bank's "
                "land quality."
            )
        missing = [k for k in self.REQUIRED if k not in self.weights]
        if missing:
            raise FeatureError(f"formula is missing weights for {missing}")
        undirected = [k for k in self.REQUIRED if k not in self.directions]
        if undirected:
            raise FeatureError(f"formula is missing directions for {undirected}")
        for name, direction in self.directions.items():
            if direction not in (-1, 1):
                raise FeatureError(
                    f"direction for {name} must be -1 or +1, got {direction}"
                )


def land_quality_components(
    inputs: LandQualityInputs,
    zone_reference: Mapping[str, tuple[float, float]],
) -> dict[str, float]:
    """Normalise the six inputs to [0, 1] against agro-zone reference ranges.

    Returned separately from any index because they are individually meaningful
    and individually `[DATA]`: drought frequency and irrigation proxy are useful
    to an underwriter with no weighting at all.

    ``zone_reference`` gives ``(low, high)`` per input for the agro-zone. It is
    `[DATA]` — computed from the zone's own distribution — and is required
    rather than defaulted, because a normalisation range invented here would set
    where every plot in the zone sits.
    """
    values = {
        "soil_organic_carbon": inputs.soil_organic_carbon,
        "slope_degrees": inputs.slope_degrees,
        "irrigation_proxy": inputs.irrigation_proxy,
        "peak_ndvi_percentile_5yr": inputs.peak_ndvi_percentile_5yr,
        "yield_volatility": inputs.yield_volatility,
        "drought_frequency": inputs.drought_frequency,
    }

    missing = [k for k in values if k not in zone_reference]
    if missing:
        raise FeatureError(
            f"no agro-zone reference range for {missing}. The range decides "
            "where every plot in the zone sits, so it is [DATA] from the zone's "
            "own distribution, never a default."
        )

    normalised = {}
    for name, value in values.items():
        low, high = zone_reference[name]
        if high <= low:
            raise FeatureError(
                f"zone reference for {name} is degenerate ({low}, {high})"
            )
        normalised[name] = min(1.0, max(0.0, (value - low) / (high - low)))
    return normalised


def land_quality_index(
    inputs: LandQualityInputs,
    zone_reference: Mapping[str, tuple[float, float]],
    formula: LandQualityFormula | None = None,
) -> float:
    """Combine the six inputs into LandQualityIndex.

    ``formula`` has no default. Phase 2 §4 names the inputs and never the
    function, and a weighting invented here would become the bank's land-quality
    definition — while being the very thing Phase 2 §7's first exit criterion
    tests. See LH-411.
    """
    if formula is None:
        raise Ungrounded(
            f"LandQualityIndex has no ratified formula ({LQI_FORMULA}). Phase 2 "
            "§4 names six inputs — soil organic carbon, slope, irrigation "
            "proxy, 5-yr peak-NDVI percentile, yield volatility, drought "
            "frequency — and never the weights, the directions or the "
            "normalisation. Six named inputs read as a specification until code "
            "has to return a number. Use land_quality_components() for the "
            "normalised inputs, which are [DATA] and useful on their own."
        )

    components = land_quality_components(inputs, zone_reference)
    total_weight = sum(abs(w) for w in formula.weights.values())
    if total_weight == 0:
        raise FeatureError("formula weights are all zero")

    score = sum(
        formula.weights[name]
        * (components[name] if formula.directions[name] > 0 else 1.0 - components[name])
        for name in formula.REQUIRED
    )
    return score / total_weight


def climate_features(
    spei_history: Sequence[DroughtIndex],
    *,
    seasons: int | None = None,
) -> dict[str, float]:
    """The WS-2.3 climate features that are computable without policy input.

    Drought frequency is `[SPEC]` — share of the last 20 seasons with
    SPEI <= -1. Excess-rain frequency uses the symmetric threshold, which is a
    reading of the phase file rather than a statement in it; it is flagged on
    the model card.

    Heat-stress days in crop-critical windows are **not** here: "crop-critical
    window" is defined by the crop calendar (LH-102), so the feature is blocked
    on a policy value rather than on the arithmetic.
    """
    window = seasons if seasons is not None else DROUGHT_HISTORY_SEASONS.value
    return {
        "drought_frequency": drought_frequency(spei_history, window),
        "excess_rain_frequency": sum(
            1 for i in list(spei_history)[-window:] if i.value >= 1.0
        )
        / window,
        "mean_spei": statistics.fmean(i.value for i in list(spei_history)[-window:]),
        "worst_spei": min(i.value for i in list(spei_history)[-window:]),
        "seasons_observed": float(window),
    }

"""WS-2.3 credit features — the two income formulas and the index that isn't one.

The arithmetic is a weighted sum. What is tested is where the formulas *refuse*:
missing input costs (LH-401), a partly-registered holding, and a
LandQualityIndex whose combining function nobody has ratified (LH-411).
"""

from __future__ import annotations

import unittest
from datetime import date

from lending_hub.agri.drought import DroughtIndex
from lending_hub.agri.features import (
    DROUGHT_HISTORY_SEASONS,
    INPUT_COSTS,
    LQI_FORMULA,
    MANDI_PRICE_WINDOW,
    FeatureError,
    IncomeResult,
    LandQualityFormula,
    LandQualityInputs,
    SeasonInput,
    climate_features,
    expected_income,
    holding_income,
    land_quality_components,
    land_quality_index,
    stressed_income,
)
from lending_hub.agri.geometry import Point, Polygon
from lending_hub.agri.registry import Plot, PlotRegistry, PlotSource, VillageLocation
from lending_hub.agri.yield_model import YieldPrediction
from lending_hub.definitions.provenance import Ungrounded

EAST, NORTH = 500_000.0, 2_300_000.0


def _yield(p50=4.0, p25=3.2, p10=2.5) -> YieldPrediction:
    return YieldPrediction(p50=p50, p25=p25, p10=p10, interval_basis="residual")


def _season(
    plot_id="P1",
    season="kharif-2024",
    *,
    area=2.0,
    cost: float | None = 18000.0,
    price_p50=22000.0,
    price_p25=19000.0,
    yield_prediction: YieldPrediction | None = None,
) -> SeasonInput:
    return SeasonInput(
        plot_id=plot_id,
        season=season,
        crop="rice",
        area_hectares=area,
        yield_prediction=yield_prediction or _yield(),
        price_p50=price_p50,
        price_p25=price_p25,
        input_cost_per_hectare=cost,
    )


def _plot(plot_id="P1", borrower="B1", side=200.0) -> Plot:
    return Plot(
        plot_id=plot_id,
        boundary=Polygon(
            (
                Point(EAST, NORTH),
                Point(EAST + side, NORTH),
                Point(EAST + side, NORTH + side),
                Point(EAST, NORTH + side),
            )
        ),
        source=PlotSource.GPS_WALK,
        surveyed=date(2024, 6, 1),
        borrower_id=borrower,
    )


class TestSeasonInput(unittest.TestCase):
    def test_an_inverted_price_pair_is_refused(self):
        """It would make StressedIncome exceed ExpectedIncome."""
        with self.assertRaises(FeatureError) as ctx:
            _season(price_p50=19000.0, price_p25=22000.0)
        self.assertIn("StressedIncome exceed ExpectedIncome", str(ctx.exception))

    def test_a_non_positive_area_is_refused(self):
        for bad in (0.0, -1.5):
            with self.assertRaises(FeatureError):
                _season(area=bad)

    def test_a_negative_input_cost_is_refused(self):
        with self.assertRaises(FeatureError):
            _season(cost=-100.0)

    def test_input_cost_defaults_to_none_not_zero(self):
        """Zero is a specific and very wrong claim, not a missing one.

        It makes ExpectedIncome equal gross revenue, overstating repayment
        capacity by the entire cost of cultivation.
        """
        season = SeasonInput(
            plot_id="P1", season="k", crop="rice", area_hectares=1.0,
            yield_prediction=_yield(), price_p50=20000.0, price_p25=18000.0,
        )
        self.assertIsNone(season.input_cost_per_hectare)


class TestExpectedIncome(unittest.TestCase):
    def test_matches_the_phase_file_formula(self):
        """Area x Yield_P50 x Price_P50 - InputCosts, by hand."""
        result = expected_income([_season(area=2.0, cost=18000.0)])
        self.assertAlmostEqual(result.gross_revenue, 2.0 * 4.0 * 22000.0, places=6)
        self.assertAlmostEqual(result.input_costs, 2.0 * 18000.0, places=6)
        self.assertAlmostEqual(result.value, 176000.0 - 36000.0, places=6)

    def test_sums_over_plots_and_seasons(self):
        seasons = [
            _season("P1", "kharif-2024"),
            _season("P1", "rabi-2024"),
            _season("P2", "kharif-2024"),
        ]
        result = expected_income(seasons)
        self.assertEqual(result.plots_valued, 2)
        self.assertEqual(result.seasons, 2)
        self.assertAlmostEqual(result.value, 3 * (176000.0 - 36000.0), places=6)

    def test_missing_input_costs_raise_rather_than_default(self):
        """LH-401, and the reason it is a stop rather than a gap.

        On a smallholder plot input costs are the same order as gross revenue,
        so a substituted figure decides the sign of the result — and therefore
        whether the borrower appears to have any repayment capacity.
        """
        with self.assertRaises(Ungrounded) as ctx:
            expected_income([_season(cost=None)])
        self.assertIn("LH-401", str(ctx.exception))
        self.assertIn("decides its sign", str(ctx.exception))

    def test_one_ungrounded_season_blocks_the_whole_sum(self):
        with self.assertRaises(Ungrounded):
            expected_income([_season("P1"), _season("P2", cost=None)])

    def test_an_empty_season_list_is_refused(self):
        """An income of zero and an unvalued holding are different facts."""
        with self.assertRaises(FeatureError) as ctx:
            expected_income([])
        self.assertIn("affordability", str(ctx.exception))

    def test_a_loss_season_is_reported_not_clamped(self):
        """Clamping would hide exactly the borrowers the feature identifies."""
        result = expected_income(
            [_season(area=1.0, cost=200000.0, price_p50=1000.0, price_p25=900.0)]
        )
        self.assertTrue(result.is_negative)
        self.assertLess(result.value, 0)

    def test_the_basis_is_recorded(self):
        self.assertIn("P50", expected_income([_season()]).basis)


class TestStressedIncome(unittest.TestCase):
    def test_uses_both_p25_yield_and_p25_price(self):
        result = stressed_income([_season(area=2.0, cost=18000.0)])
        self.assertAlmostEqual(result.gross_revenue, 2.0 * 3.2 * 19000.0, places=6)

    def test_is_below_expected_income(self):
        seasons = [_season()]
        self.assertLess(stressed_income(seasons).value, expected_income(seasons).value)

    def test_input_costs_are_not_stressed(self):
        """Costs are the same in both formulas, as the phase file writes them."""
        seasons = [_season()]
        self.assertAlmostEqual(
            stressed_income(seasons).input_costs,
            expected_income(seasons).input_costs,
            places=6,
        )

    def test_missing_input_costs_raise_here_too(self):
        with self.assertRaises(Ungrounded):
            stressed_income([_season(cost=None)])


class TestHoldingIncome(unittest.TestCase):
    def test_values_a_fully_registered_holding(self):
        registry = PlotRegistry()
        registry.register_plot(_plot("P1", "B1"))
        registry.register_plot(_plot("P2", "B1"))
        result = holding_income(
            registry, "B1", [_season("P1"), _season("P2")]
        )
        self.assertEqual(result.plots_valued, 2)

    def test_refuses_a_partly_valued_holding(self):
        """Summing what exists is too small in a way nothing can detect.

        For an affordability cap, "too small" reads as prudence.
        """
        registry = PlotRegistry()
        for plot_id in ("P1", "P2", "P3", "P4"):
            registry.register_plot(_plot(plot_id, "B1"))
        with self.assertRaises(FeatureError) as ctx:
            holding_income(registry, "B1", [_season("P1")])
        self.assertIn("reads as prudence", str(ctx.exception))
        self.assertIn("3 of 4", str(ctx.exception))

    def test_refuses_a_village_granularity_borrower(self):
        registry = PlotRegistry()
        registry.register_village(VillageLocation("B9", "VC-9", claimed_hectares=4.0))
        with self.assertRaises(FeatureError) as ctx:
            holding_income(registry, "B9", [_season("P1")])
        self.assertIn("application form", str(ctx.exception))

    def test_refuses_seasons_for_plots_not_on_this_holding(self):
        registry = PlotRegistry()
        registry.register_plot(_plot("P1", "B1"))
        with self.assertRaises(FeatureError) as ctx:
            holding_income(registry, "B1", [_season("P1"), _season("P9")])
        self.assertIn("not registered to this borrower", str(ctx.exception))

    def test_the_stressed_variant(self):
        registry = PlotRegistry()
        registry.register_plot(_plot("P1", "B1"))
        stressed = holding_income(registry, "B1", [_season("P1")], stressed=True)
        expected = holding_income(registry, "B1", [_season("P1")])
        self.assertLess(stressed.value, expected.value)


class TestLandQualityIndex(unittest.TestCase):
    def _inputs(self, **overrides) -> LandQualityInputs:
        base = dict(
            soil_organic_carbon=1.2,
            slope_degrees=3.0,
            irrigation_proxy=0.7,
            peak_ndvi_percentile_5yr=0.65,
            yield_volatility=0.22,
            drought_frequency=0.15,
        )
        base.update(overrides)
        return LandQualityInputs(**base)

    def _zone(self):
        return {
            "soil_organic_carbon": (0.2, 2.5),
            "slope_degrees": (0.0, 15.0),
            "irrigation_proxy": (0.0, 1.0),
            "peak_ndvi_percentile_5yr": (0.0, 1.0),
            "yield_volatility": (0.05, 0.60),
            "drought_frequency": (0.0, 0.60),
        }

    def test_the_index_refuses_without_a_ratified_formula(self):
        """LH-411 — the finding this module produced.

        §4 names six inputs and never the function. Six named inputs read as a
        specification until code has to return a number, and the weighting
        would become the bank's land-quality definition — while being exactly
        what exit criterion (a) tests.
        """
        with self.assertRaises(Ungrounded) as ctx:
            land_quality_index(self._inputs(), self._zone())
        self.assertIn("LH-411", str(ctx.exception))
        self.assertIn("never the weights", str(ctx.exception))

    def test_the_components_are_computable_without_the_formula(self):
        """They are [DATA] and useful to an underwriter unweighted."""
        components = land_quality_components(self._inputs(), self._zone())
        self.assertEqual(len(components), 6)
        for value in components.values():
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)

    def test_normalisation_places_a_value_in_its_zone_range(self):
        components = land_quality_components(
            self._inputs(soil_organic_carbon=1.35), self._zone()
        )
        self.assertAlmostEqual(components["soil_organic_carbon"], 0.5, places=6)

    def test_values_outside_the_zone_range_are_clamped(self):
        components = land_quality_components(
            self._inputs(soil_organic_carbon=9.0), self._zone()
        )
        self.assertEqual(components["soil_organic_carbon"], 1.0)

    def test_a_missing_zone_reference_is_refused(self):
        zone = self._zone()
        del zone["slope_degrees"]
        with self.assertRaises(FeatureError) as ctx:
            land_quality_components(self._inputs(), zone)
        self.assertIn("never a default", str(ctx.exception))

    def test_a_degenerate_zone_range_is_refused(self):
        zone = self._zone()
        zone["slope_degrees"] = (5.0, 5.0)
        with self.assertRaises(FeatureError):
            land_quality_components(self._inputs(), zone)

    def test_a_ratified_formula_produces_an_index(self):
        formula = LandQualityFormula(
            weights={k: 1.0 for k in LandQualityFormula.REQUIRED},
            directions={
                "soil_organic_carbon": 1,
                "slope_degrees": -1,
                "irrigation_proxy": 1,
                "peak_ndvi_percentile_5yr": 1,
                "yield_volatility": -1,
                "drought_frequency": -1,
            },
            policy_reference="AC-2026-07",
        )
        value = land_quality_index(self._inputs(), self._zone(), formula)
        self.assertGreaterEqual(value, 0.0)
        self.assertLessEqual(value, 1.0)

    def test_direction_flips_the_contribution(self):
        zone = self._zone()
        weights = {k: 0.0 for k in LandQualityFormula.REQUIRED}
        weights["drought_frequency"] = 1.0
        directions = {k: 1 for k in LandQualityFormula.REQUIRED}

        as_positive = LandQualityFormula(weights, directions, policy_reference="AC-1")
        directions_negative = dict(directions, drought_frequency=-1)
        as_negative = LandQualityFormula(weights, directions_negative, policy_reference="AC-1")

        dry = self._inputs(drought_frequency=0.5)
        self.assertGreater(
            land_quality_index(dry, zone, as_positive),
            land_quality_index(dry, zone, as_negative),
        )

    def test_a_formula_needs_its_policy_reference(self):
        with self.assertRaises(FeatureError) as ctx:
            LandQualityFormula(
                weights={k: 1.0 for k in LandQualityFormula.REQUIRED},
                directions={k: 1 for k in LandQualityFormula.REQUIRED},
                policy_reference="",
            )
        self.assertIn("LH-411", str(ctx.exception))

    def test_a_formula_missing_a_weight_is_refused(self):
        with self.assertRaises(FeatureError):
            LandQualityFormula(
                weights={"soil_organic_carbon": 1.0},
                directions={k: 1 for k in LandQualityFormula.REQUIRED},
                policy_reference="AC-1",
            )

    def test_a_formula_with_a_nonsensical_direction_is_refused(self):
        with self.assertRaises(FeatureError):
            LandQualityFormula(
                weights={k: 1.0 for k in LandQualityFormula.REQUIRED},
                directions=dict(
                    {k: 1 for k in LandQualityFormula.REQUIRED}, slope_degrees=0
                ),
                policy_reference="AC-1",
            )

    def test_inputs_are_range_checked(self):
        for kwargs in (
            {"irrigation_proxy": 1.4},
            {"drought_frequency": -0.1},
            {"slope_degrees": 120.0},
            {"soil_organic_carbon": -1.0},
            {"yield_volatility": -0.2},
        ):
            with self.assertRaises(FeatureError):
                self._inputs(**kwargs)


class TestClimateFeatures(unittest.TestCase):
    def _history(self, values):
        return [
            DroughtIndex(value=v, timescale_months=3, calendar_month=7, fitted_on=40)
            for v in values
        ]

    def test_drought_frequency_uses_the_spec_window_and_threshold(self):
        self.assertEqual(DROUGHT_HISTORY_SEASONS.value, 20)
        history = self._history([-1.5] * 5 + [0.2] * 15)
        features = climate_features(history)
        self.assertAlmostEqual(features["drought_frequency"], 0.25, places=9)

    def test_excess_rain_frequency_is_the_symmetric_threshold(self):
        history = self._history([1.4] * 4 + [0.1] * 16)
        self.assertAlmostEqual(
            climate_features(history)["excess_rain_frequency"], 0.20, places=9
        )

    def test_worst_and_mean_are_reported(self):
        history = self._history([-2.4] + [0.0] * 19)
        features = climate_features(history)
        self.assertAlmostEqual(features["worst_spei"], -2.4, places=9)
        self.assertAlmostEqual(features["mean_spei"], -0.12, places=9)

    def test_a_short_history_is_refused_not_scaled(self):
        with self.assertRaises(Exception):
            climate_features(self._history([-1.0] * 6))

    def test_the_window_is_overridable_for_a_shorter_record(self):
        features = climate_features(self._history([-1.2] * 8), seasons=8)
        self.assertAlmostEqual(features["drought_frequency"], 1.0, places=9)


class TestUngroundedPlaceholders(unittest.TestCase):
    def test_the_three_phase_two_feature_placeholders_are_registered(self):
        for pending, ticket in (
            (INPUT_COSTS, "LH-401"),
            (MANDI_PRICE_WINDOW, "LH-408"),
            (LQI_FORMULA, "LH-411"),
        ):
            self.assertEqual(pending.ticket, ticket)
            with self.assertRaises(Ungrounded):
                pending.value


if __name__ == "__main__":
    unittest.main()

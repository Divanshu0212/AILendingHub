"""Model C's auditable fallback — WS-2.2 (SRS §3.4.3).

Phase 2 §4 orders the fallback built *first* and kept forever. The reference
histogram-CNN + GP is not ported (ADR-0013), so the tests that matter are the
ones proving the fallback still satisfies the output contract the GP was
supposed to supply — P50/P25/P10 — and that the interval says what kind of
interval it is.
"""

from __future__ import annotations

import random
import unittest

from lending_hub.agri.yield_model import (
    CONTRACT_QUANTILES,
    MIN_DISTRICT_SEASONS,
    DistrictSeason,
    YieldError,
    YieldModel,
    YieldPrediction,
    downscale,
    fit_yield_model,
)

TRUE_INTERCEPT, TRUE_NDVI, TRUE_RAIN = 1.2, 3.4, 0.9


def _observations(n: int = 200, seed: int = 4, noise: float = 0.25):
    rng = random.Random(seed)
    out = []
    for i in range(n):
        ndvi = rng.uniform(0.35, 0.90)
        rain = rng.uniform(0.0, 1.0)
        yield_ha = TRUE_INTERCEPT + TRUE_NDVI * ndvi + TRUE_RAIN * rain
        out.append(
            DistrictSeason(
                district_id=f"D{i % 12}",
                season=f"S{i // 12}",
                yield_per_hectare=max(0.0, yield_ha + rng.gauss(0, noise)),
                peak_ndvi=ndvi,
                rainfall_percentile=rain,
            )
        )
    return out


class TestDistrictSeason(unittest.TestCase):
    def test_rejects_ndvi_outside_the_index_range(self):
        """A value outside [-1, 1] means the band maths or masking is wrong."""
        with self.assertRaises(YieldError) as ctx:
            DistrictSeason("D1", "S1", 3.0, peak_ndvi=1.4, rainfall_percentile=0.5)
        self.assertIn("bounded index", str(ctx.exception))

    def test_rejects_rainfall_in_millimetres(self):
        """The mistake that fits fine and predicts nonsense out of sample.

        A percentile is not a millimetre total, and 850 mm passed where a
        percentile belongs produces a model with a tiny rainfall coefficient
        that looks perfectly reasonable.
        """
        with self.assertRaises(YieldError) as ctx:
            DistrictSeason("D1", "S1", 3.0, peak_ndvi=0.7, rainfall_percentile=850.0)
        self.assertIn("not a millimetre total", str(ctx.exception))

    def test_rejects_a_negative_yield(self):
        with self.assertRaises(YieldError):
            DistrictSeason("D1", "S1", -0.5, peak_ndvi=0.7, rainfall_percentile=0.5)


class TestFit(unittest.TestCase):
    def test_recovers_known_coefficients(self):
        model = fit_yield_model(_observations(400, seed=11, noise=0.15))
        self.assertAlmostEqual(model.intercept, TRUE_INTERCEPT, delta=0.15)
        self.assertAlmostEqual(model.ndvi_coefficient, TRUE_NDVI, delta=0.20)
        self.assertAlmostEqual(model.rainfall_coefficient, TRUE_RAIN, delta=0.15)

    def test_reports_r_squared_and_sample_size(self):
        model = fit_yield_model(_observations(300, seed=12, noise=0.2))
        self.assertGreater(model.r_squared, 0.7)
        self.assertEqual(model.n, 300)

    def test_refuses_a_sample_too_small_to_estimate_a_quartile_from(self):
        with self.assertRaises(YieldError) as ctx:
            fit_yield_model(_observations(12, seed=13))
        self.assertIn("good year and a bad one", str(ctx.exception))

    def test_the_minimum_is_the_documented_one(self):
        self.assertEqual(MIN_DISTRICT_SEASONS, 30)
        self.assertIsNotNone(fit_yield_model(_observations(MIN_DISTRICT_SEASONS, seed=14)))

    def test_collinear_covariates_are_reported_not_regularised(self):
        """Every district-season from one year: NDVI and rainfall move together."""
        observations = [
            DistrictSeason(f"D{i}", "S1", 2.0 + 0.1 * i, peak_ndvi=0.4 + i * 0.01,
                           rainfall_percentile=min(1.0, 0.2 + i * 0.01))
            for i in range(40)
        ]
        with self.assertRaises(YieldError) as ctx:
            fit_yield_model(observations)
        self.assertIn("same year", str(ctx.exception))

    def test_residual_quantiles_cover_the_contract(self):
        model = fit_yield_model(_observations(200, seed=15))
        self.assertEqual(set(model.residual_quantiles), set(CONTRACT_QUANTILES))


class TestOutputContract(unittest.TestCase):
    """Phase 2 §4: the uncertainty is part of the contract, not optional."""

    def setUp(self):
        self.model = fit_yield_model(_observations(300, seed=21))

    def test_predict_returns_all_three_quantiles_ordered(self):
        prediction = self.model.predict(0.75, 0.40)
        self.assertGreaterEqual(prediction.p50, prediction.p25)
        self.assertGreaterEqual(prediction.p25, prediction.p10)

    def test_the_fallback_still_produces_an_interval_without_a_gp(self):
        """The failure this module exists to avoid.

        A least-squares fit has no P25, so the temptation is to ship P50 and
        call the quantiles pending. StressedIncome is *defined* on Yield_P25, so
        a missing P25 does not degrade that feature — it deletes it.
        """
        prediction = self.model.predict(0.7, 0.5)
        self.assertLess(prediction.p25, prediction.p50)
        self.assertLess(prediction.p10, prediction.p25)

    def test_the_interval_declares_what_kind_of_interval_it_is(self):
        prediction = self.model.predict(0.7, 0.5)
        self.assertIn("not a GP posterior", prediction.interval_basis)

    def test_an_inverted_interval_is_refused(self):
        with self.assertRaises(YieldError) as ctx:
            YieldPrediction(p50=2.0, p25=3.0, p10=1.0, interval_basis="test")
        self.assertIn("StressedIncome larger than ExpectedIncome", str(ctx.exception))

    def test_a_negative_p10_is_a_broken_model_not_a_severe_scenario(self):
        with self.assertRaises(YieldError) as ctx:
            YieldPrediction(p50=1.0, p25=0.5, p10=-0.2, interval_basis="test")
        self.assertIn("broken model", str(ctx.exception))

    def test_predictions_are_floored_at_zero(self):
        """A very poor plot must yield 0, never a negative revenue term."""
        model = YieldModel(
            intercept=0.05,
            ndvi_coefficient=0.1,
            rainfall_coefficient=0.1,
            residual_quantiles={0.50: 0.0, 0.25: -0.5, 0.10: -1.0},
            residual_std=0.4,
            n=100,
            r_squared=0.5,
        )
        prediction = model.predict(0.05, 0.0)
        self.assertGreaterEqual(prediction.p10, 0.0)

    def test_higher_ndvi_predicts_a_higher_yield(self):
        low = self.model.predict(0.45, 0.5)
        high = self.model.predict(0.85, 0.5)
        self.assertGreater(high.p50, low.p50)

    def test_higher_rainfall_percentile_predicts_a_higher_yield(self):
        dry = self.model.predict(0.7, 0.1)
        wet = self.model.predict(0.7, 0.9)
        self.assertGreater(wet.p50, dry.p50)

    def test_out_of_range_inputs_are_refused(self):
        with self.assertRaises(YieldError):
            self.model.predict(1.5, 0.5)
        with self.assertRaises(YieldError):
            self.model.predict(0.7, 1.5)

    def test_the_point_prediction_is_checkable_by_hand(self):
        """The reason §4 wants two covariates: three numbers and a sum."""
        expected = (
            self.model.intercept
            + self.model.ndvi_coefficient * 0.8
            + self.model.rainfall_coefficient * 0.3
        )
        self.assertAlmostEqual(self.model.point(0.8, 0.3), expected, places=12)


class TestDownscaling(unittest.TestCase):
    def setUp(self):
        self.district = YieldPrediction(
            p50=4.0, p25=3.5, p10=3.0, interval_basis="residual", district_id="D1"
        )
        self.distribution = [0.30 + 0.01 * i for i in range(61)]  # 0.30 .. 0.90

    def test_the_median_plot_gets_the_district_figure(self):
        prediction, percentile = downscale(self.district, 0.60, self.distribution)
        self.assertAlmostEqual(percentile, 0.5, delta=0.02)
        self.assertAlmostEqual(prediction.p50, 4.0, delta=0.05)

    def test_a_top_plot_is_scaled_up_and_a_bottom_plot_down(self):
        top, top_percentile = downscale(self.district, 0.90, self.distribution)
        bottom, bottom_percentile = downscale(self.district, 0.30, self.distribution)
        self.assertGreater(top_percentile, bottom_percentile)
        self.assertGreater(top.p50, 4.0)
        self.assertLess(bottom.p50, 4.0)

    def test_the_adjustment_is_capped(self):
        """An uncapped version hands the best plot in each district an income
        nobody estimated: the NDVI-rank-to-yield slope is not something a
        district-level fit measured."""
        top, _ = downscale(self.district, 0.90, self.distribution, max_adjustment=0.30)
        self.assertLessEqual(top.p50, 4.0 * 1.30 + 1e-9)

    def test_downscaling_preserves_the_quantile_ordering(self):
        prediction, _ = downscale(self.district, 0.88, self.distribution)
        self.assertGreaterEqual(prediction.p50, prediction.p25)
        self.assertGreaterEqual(prediction.p25, prediction.p10)

    def test_the_result_says_it_is_an_allocation_not_a_measurement(self):
        prediction, _ = downscale(self.district, 0.75, self.distribution)
        self.assertIn("not a plot measurement", prediction.interval_basis)

    def test_the_percentile_is_returned_not_hidden(self):
        """It is the entire content of the plot-level claim."""
        _, percentile = downscale(self.district, 0.85, self.distribution)
        self.assertGreater(percentile, 0.8)

    def test_downscaling_without_a_district_distribution_is_refused(self):
        with self.assertRaises(YieldError) as ctx:
            downscale(self.district, 0.7, [])
        self.assertIn("percentile of", str(ctx.exception))

    def test_rejects_an_out_of_range_plot_ndvi(self):
        with self.assertRaises(YieldError):
            downscale(self.district, 1.4, self.distribution)

    def test_rejects_a_nonsensical_cap(self):
        for bad in (0.0, 1.5, -0.2):
            with self.assertRaises(YieldError):
                downscale(self.district, 0.7, self.distribution, max_adjustment=bad)

    def test_the_district_id_survives_downscaling(self):
        prediction, _ = downscale(self.district, 0.7, self.distribution)
        self.assertEqual(prediction.district_id, "D1")


if __name__ == "__main__":
    unittest.main()

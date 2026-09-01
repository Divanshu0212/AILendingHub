"""Vegetation and backscatter series — WS-2.1 Step 3.

The assertions that matter here are not about the arithmetic of NDVI, which is a
subtraction over a sum. They are about the two decisions in the module docstring:
masked observations are *kept and counted* rather than dropped, and an
interpolated value is labelled as one. Both are the difference between a series
that can be shown to an underwriter as evidence and one that cannot.
"""

from __future__ import annotations

import math
import unittest
from datetime import date, timedelta

from lending_hub.agri.indices import (
    EVI_GAIN,
    UNUSABLE_SCENE_CLASSES,
    IndexSeries,
    SceneClass,
    VegetationIndexError,
    backscatter_db,
    evi,
    interpolate,
    mask_scene,
    ndvi,
    revisit_completeness,
    temporal_max_composite,
)
from lending_hub.agri.ports import Observation


def _obs(day: int, value: float, valid: bool = True, plot: str = "P1") -> Observation:
    return Observation(
        plot_id=plot,
        acquired=date(2024, 1, 1) + timedelta(days=day),
        value=value,
        valid=valid,
        sensor="S2",
    )


def _series(pairs, plot: str = "P1", name: str = "ndvi") -> IndexSeries:
    return IndexSeries(
        plot_id=plot,
        index_name=name,
        observations=tuple(_obs(d, v, valid, plot) for d, v, valid in pairs),
    )


class TestNdvi(unittest.TestCase):
    def test_dense_vegetation_is_near_one(self):
        self.assertAlmostEqual(ndvi(nir=0.5, red=0.05), 0.8181818, places=6)

    def test_bare_soil_is_near_zero(self):
        self.assertAlmostEqual(ndvi(nir=0.22, red=0.20), 0.047619, places=6)

    def test_water_is_negative(self):
        self.assertLess(ndvi(nir=0.02, red=0.06), 0)

    def test_is_bounded_in_minus_one_to_one(self):
        for nir_value in (0.0, 0.1, 0.5, 1.0):
            for red_value in (0.01, 0.2, 1.0):
                self.assertLessEqual(abs(ndvi(nir_value, red_value)), 1.0)

    def test_no_data_pixel_raises_rather_than_returning_zero(self):
        """0.0 is a real NDVI for bare soil, so it cannot double as no-data."""
        with self.assertRaises(VegetationIndexError) as ctx:
            ndvi(nir=0.0, red=0.0)
        self.assertIn("bare soil", str(ctx.exception))


class TestEvi(unittest.TestCase):
    def test_matches_the_published_formula(self):
        nir, red, blue = 0.40, 0.10, 0.05
        expected = EVI_GAIN * (nir - red) / (nir + 6.0 * red - 7.5 * blue + 1.0)
        self.assertAlmostEqual(evi(nir, red, blue), expected, places=12)

    def test_saturates_less_than_ndvi_over_dense_canopy(self):
        """EVI's reason for existing, as an assertion.

        Two dense-canopy states that NDVI barely separates. EVI must separate
        them by more, because NDVI's asymptote is what EVI's denominator terms
        were introduced to correct.
        """
        a = dict(nir=0.45, red=0.030, blue=0.020)
        b = dict(nir=0.60, red=0.025, blue=0.018)
        ndvi_gap = abs(ndvi(a["nir"], a["red"]) - ndvi(b["nir"], b["red"]))
        evi_gap = abs(evi(**a) - evi(**b))
        self.assertGreater(evi_gap, ndvi_gap)

    def test_zero_denominator_raises(self):
        # Choose reflectances that drive nir + 6r - 7.5b + 1 to exactly zero.
        blue = (0.2 + 6.0 * 0.1 + 1.0) / 7.5
        with self.assertRaises(VegetationIndexError):
            evi(nir=0.2, red=0.1, blue=blue)


class TestBackscatter(unittest.TestCase):
    def test_decibel_conversion(self):
        self.assertAlmostEqual(backscatter_db(1.0), 0.0, places=12)
        self.assertAlmostEqual(backscatter_db(0.1), -10.0, places=12)
        self.assertAlmostEqual(backscatter_db(0.01), -20.0, places=12)

    def test_non_positive_power_is_a_calibration_failure(self):
        for bad in (0.0, -0.5):
            with self.assertRaises(VegetationIndexError) as ctx:
                backscatter_db(bad)
            self.assertIn("calibration", str(ctx.exception))


class TestSceneClasses(unittest.TestCase):
    def test_the_published_scl_codes_are_used(self):
        self.assertEqual(SceneClass.VEGETATION, 4)
        self.assertEqual(SceneClass.CLOUD_HIGH_PROBABILITY, 9)
        self.assertEqual(SceneClass.SNOW_ICE, 11)

    def test_vegetation_and_bare_soil_are_usable(self):
        self.assertNotIn(SceneClass.VEGETATION, UNUSABLE_SCENE_CLASSES)
        self.assertNotIn(SceneClass.NOT_VEGETATED, UNUSABLE_SCENE_CLASSES)

    def test_medium_probability_cloud_is_excluded(self):
        """The marginal call, pinned so a later change is deliberate.

        Thin cloud depresses NDVI, which reads as crop stress and fires a
        distress flag on a healthy plot. That is the more expensive error than
        losing a revisit.
        """
        self.assertIn(SceneClass.CLOUD_MEDIUM_PROBABILITY, UNUSABLE_SCENE_CLASSES)


class TestMasking(unittest.TestCase):
    def test_masked_observations_are_kept_not_dropped(self):
        observations = [_obs(0, 0.7), _obs(5, 0.2), _obs(10, 0.75)]
        masked = mask_scene(
            observations,
            [SceneClass.VEGETATION, SceneClass.CLOUD_HIGH_PROBABILITY, SceneClass.VEGETATION],
        )
        self.assertEqual(len(masked), 3)
        self.assertEqual([o.valid for o in masked], [True, False, True])

    def test_masking_never_revalidates_an_invalid_observation(self):
        """An upstream invalid stays invalid whatever the scene class says."""
        masked = mask_scene([_obs(0, 0.7, valid=False)], [SceneClass.VEGETATION])
        self.assertFalse(masked[0].valid)

    def test_length_mismatch_is_refused(self):
        with self.assertRaises(VegetationIndexError) as ctx:
            mask_scene([_obs(0, 0.7)], [SceneClass.VEGETATION, SceneClass.WATER])
        self.assertIn("different acquisitions", str(ctx.exception))

    def test_values_survive_masking_unchanged(self):
        masked = mask_scene([_obs(0, 0.33)], [SceneClass.CLOUD_SHADOWS])
        self.assertEqual(masked[0].value, 0.33)


class TestIndexSeries(unittest.TestCase):
    def test_out_of_order_observations_are_refused(self):
        with self.assertRaises(VegetationIndexError) as ctx:
            IndexSeries(
                plot_id="P1",
                index_name="ndvi",
                observations=(_obs(10, 0.5), _obs(2, 0.4)),
            )
        self.assertIn("ascending", str(ctx.exception))

    def test_valid_fraction_counts_the_cloud_census(self):
        series = _series([(0, 0.7, True), (5, 0.2, False), (10, 0.8, True), (15, 0.3, False)])
        self.assertEqual(series.valid_fraction, 0.5)

    def test_valid_fraction_of_an_empty_series_is_zero(self):
        self.assertEqual(_series([]).valid_fraction, 0.0)

    def test_longest_gap_uses_valid_observations_only(self):
        """The point of keeping invalid observations.

        Revisits every 5 days, but the middle four are clouded. The gap in the
        *usable* record is 25 days, and a series that had dropped the invalid
        rows would report the same 25 — while a series that counted all rows as
        observed would report 5 and hide the outage.
        """
        series = _series(
            [(0, 0.7, True), (5, 0.1, False), (10, 0.1, False), (15, 0.1, False),
             (20, 0.1, False), (25, 0.8, True)]
        )
        self.assertEqual(series.longest_gap_days, 25)

    def test_a_single_observation_has_no_gap(self):
        with self.assertRaises(VegetationIndexError) as ctx:
            _series([(0, 0.7, True)]).longest_gap_days
        self.assertIn("has no series", str(ctx.exception))

    def test_peak_ignores_masked_observations(self):
        """A cloud-contaminated high value must not become the peak."""
        series = _series([(0, 0.5, True), (5, 0.99, False), (10, 0.6, True)])
        self.assertEqual(series.peak().value, 0.6)

    def test_peak_respects_the_window(self):
        series = _series([(0, 0.9, True), (30, 0.5, True), (60, 0.7, True)])
        peak = series.peak(start=date(2024, 1, 20), end=date(2024, 3, 15))
        self.assertEqual(peak.value, 0.7)

    def test_peak_of_an_unobserved_window_raises(self):
        series = _series([(0, 0.9, True)])
        with self.assertRaises(VegetationIndexError) as ctx:
            series.peak(start=date(2024, 6, 1), end=date(2024, 7, 1))
        self.assertIn("not observed", str(ctx.exception))

    def test_mean_uses_valid_observations_only(self):
        series = _series([(0, 0.4, True), (5, 1.0, False), (10, 0.6, True)])
        self.assertAlmostEqual(series.mean(), 0.5, places=12)

    def test_amplitude_separates_a_cropped_plot_from_a_static_one(self):
        cropped = _series([(0, 0.15, True), (60, 0.85, True), (120, 0.20, True)])
        orchard = _series([(0, 0.60, True), (60, 0.65, True), (120, 0.62, True)])
        self.assertAlmostEqual(cropped.mean(), orchard.mean(), delta=0.24)
        self.assertGreater(cropped.amplitude(), orchard.amplitude())

    def test_amplitude_needs_two_observations(self):
        with self.assertRaises(VegetationIndexError):
            _series([(0, 0.5, True)]).amplitude()


class TestInterpolation(unittest.TestCase):
    def test_an_exact_observation_is_reported_as_observed(self):
        series = _series([(0, 0.4, True), (20, 0.8, True)])
        value, observed = interpolate(series, date(2024, 1, 1))
        self.assertEqual(value, 0.4)
        self.assertTrue(observed)

    def test_an_interpolated_value_is_reported_as_not_observed(self):
        """The flag is the whole point of the function.

        A caller that unpacks only the value has silently converted a model
        output into an observation, and the crop-verification stream's
        evidential standing rests on the difference.
        """
        series = _series([(0, 0.4, True), (20, 0.8, True)])
        value, observed = interpolate(series, date(2024, 1, 11))
        self.assertAlmostEqual(value, 0.6, places=12)
        self.assertFalse(observed)

    def test_extrapolation_is_refused(self):
        series = _series([(10, 0.4, True), (20, 0.8, True)])
        for target in (date(2024, 1, 5), date(2024, 2, 20)):
            with self.assertRaises(VegetationIndexError) as ctx:
                interpolate(series, target)
            self.assertIn("invents phenology", str(ctx.exception))

    def test_a_gap_longer_than_the_limit_is_refused(self):
        series = _series([(0, 0.2, True), (90, 0.9, True)])
        with self.assertRaises(VegetationIndexError) as ctx:
            interpolate(series, date(2024, 2, 15), max_gap_days=30)
        self.assertIn("erasure", str(ctx.exception))

    def test_masked_observations_do_not_bracket_an_interpolation(self):
        series = _series([(0, 0.4, True), (10, 0.99, False), (20, 0.8, True)])
        value, _ = interpolate(series, date(2024, 1, 11))
        self.assertAlmostEqual(value, 0.6, places=12)

    def test_no_valid_observations_raises(self):
        series = _series([(0, 0.4, False)])
        with self.assertRaises(VegetationIndexError):
            interpolate(series, date(2024, 1, 1))


class TestComposite(unittest.TestCase):
    def test_max_value_composite_rejects_the_depressed_observations(self):
        series = _series([(0, 0.31, True), (10, 0.78, True), (20, 0.35, True)])
        self.assertEqual(
            temporal_max_composite(series, date(2024, 1, 1), date(2024, 1, 25)), 0.78
        )

    def test_inverted_window_is_refused(self):
        series = _series([(0, 0.5, True)])
        with self.assertRaises(VegetationIndexError):
            temporal_max_composite(series, date(2024, 3, 1), date(2024, 1, 1))


class TestRevisitCompleteness(unittest.TestCase):
    def test_a_full_stack_is_complete(self):
        series = _series([(d, 0.5, True) for d in range(0, 30, 5)])
        got = revisit_completeness(series, date(2024, 1, 1), date(2024, 1, 26), 5)
        self.assertAlmostEqual(got, 1.0, places=12)

    def test_masked_revisits_count_as_missing(self):
        series = _series(
            [(0, 0.5, True), (5, 0.5, False), (10, 0.5, False),
             (15, 0.5, True), (20, 0.5, True), (25, 0.5, True)]
        )
        got = revisit_completeness(series, date(2024, 1, 1), date(2024, 1, 26), 5)
        self.assertAlmostEqual(got, 4 / 6, places=12)

    def test_revisit_interval_is_a_parameter_not_a_constant(self):
        """Sentinel-1B failed and the constellation revisit changed.

        A monitor with a hard-coded interval would have reported a fleet-wide
        mission change as a data-quality collapse across every plot at once.
        """
        series = _series([(d, 0.5, True) for d in range(0, 30, 12)])
        self.assertAlmostEqual(
            revisit_completeness(series, date(2024, 1, 1), date(2024, 1, 25), 12),
            1.0,
            places=12,
        )

    def test_rejects_a_nonsensical_interval(self):
        series = _series([(0, 0.5, True)])
        with self.assertRaises(VegetationIndexError):
            revisit_completeness(series, date(2024, 1, 1), date(2024, 1, 26), 0)

    def test_rejects_an_inverted_window(self):
        series = _series([(0, 0.5, True)])
        with self.assertRaises(VegetationIndexError):
            revisit_completeness(series, date(2024, 3, 1), date(2024, 1, 1), 5)


if __name__ == "__main__":
    unittest.main()

"""WS-3.2 Steps 3 and 5 — drift, ADWIN, calibration CUSUM, and S-H-ESD."""

import math
import random
import unittest

from lending_hub.portfolio import health as H
from lending_hub.portfolio import opsanomaly as A


class BinningTests(unittest.TestCase):
    def test_proportions_sum_to_one(self):
        p = H.bin_proportions([1, 2, 3, 4, 5], [2, 4])
        self.assertAlmostEqual(sum(p), 1.0)
        self.assertEqual(len(p), 3)

    def test_reference_edges_are_used_not_recomputed(self):
        """PSI over self-computed quantiles is zero by construction."""
        reference = list(range(100))
        shifted = [v + 500 for v in reference]
        reading = H.drift("x", reference, shifted, [25, 50, 75])
        self.assertGreater(reading.psi, H.PSI_ACT)

    def test_identical_samples_have_near_zero_psi(self):
        sample = [float(i % 10) for i in range(200)]
        self.assertLess(H.drift("x", sample, sample, [2, 5, 8]).psi, 1e-9)

    def test_unsorted_edges_rejected(self):
        with self.assertRaises(H.HealthError):
            H.bin_proportions([1, 2], [5, 1])

    def test_empty_sample_rejected(self):
        with self.assertRaises(H.HealthError):
            H.bin_proportions([], [1])

    def test_verdict_uses_the_shared_thresholds(self):
        reading = H.drift("x", list(range(100)), list(range(100)), [50])
        self.assertEqual(reading.to_dict()["alert_threshold"], H.PSI_ALERT)
        self.assertEqual(reading.to_dict()["act_threshold"], H.PSI_ACT)


class AdwinTests(unittest.TestCase):
    def test_detects_a_regime_change_near_the_true_point(self):
        rng = random.Random(1)
        adwin = H.Adwin(delta=0.002)
        first = None
        for i in range(400):
            rate = 0.1 if i < 200 else 0.4
            change = adwin.update(1.0 if rng.random() < rate else 0.0)
            if change and first is None:
                first = change
        self.assertIsNotNone(first)
        self.assertAlmostEqual(first.index, 200, delta=25)
        self.assertGreater(first.shift, 0.15)

    def test_stationary_stream_raises_no_change(self):
        rng = random.Random(7)
        adwin = H.Adwin(delta=0.002)
        for _ in range(400):
            adwin.update(1.0 if rng.random() < 0.1 else 0.0)
        self.assertEqual(adwin.changes, [])

    def test_window_shrinks_to_the_new_regime(self):
        rng = random.Random(1)
        adwin = H.Adwin(delta=0.002)
        for i in range(400):
            adwin.update(1.0 if rng.random() < (0.1 if i < 200 else 0.4) else 0.0)
        self.assertLess(adwin.width, 400)
        self.assertGreater(adwin.mean, 0.25)

    def test_delta_is_required_and_bounded(self):
        with self.assertRaises(TypeError):
            H.Adwin()
        with self.assertRaises(H.HealthError):
            H.Adwin(delta=0.0)
        with self.assertRaises(H.HealthError):
            H.Adwin(delta=1.0)

    def test_mean_of_an_empty_window_raises(self):
        with self.assertRaises(H.HealthError):
            H.Adwin(delta=0.002).mean

    def test_paper_delta_is_a_citation_not_a_default(self):
        self.assertIn("LH-307", H.ADWIN_PAPER_DELTA.citation)
        self.assertEqual(H.ADWIN_PAPER_DELTA.value, 0.002)


class CalibrationDriftTests(unittest.TestCase):
    def test_well_calibrated_series_never_alarms(self):
        series = [(f"m{i}", 0.05, 50, 1000) for i in range(24)]
        result = H.calibration_drift(series, reference_shift=0.5,
                                     decision_interval=5.0)
        self.assertIsNone(result.first_alarm)

    def test_under_prediction_alarms_upward(self):
        series = [(f"m{i}", 0.05, 50, 1000) for i in range(6)]
        series += [(f"m{6 + i}", 0.05, 100, 1000) for i in range(12)]
        result = H.calibration_drift(series, reference_shift=0.5,
                                     decision_interval=5.0)
        self.assertEqual(result.first_alarm[1], "under_predicting")

    def test_over_prediction_alarms_too(self):
        """A one-sided chart would stay silent through this for years."""
        series = [(f"m{i}", 0.10, 20, 1000) for i in range(18)]
        result = H.calibration_drift(series, reference_shift=0.5,
                                     decision_interval=5.0)
        self.assertEqual(result.first_alarm[1], "over_predicting")

    def test_parameters_are_required(self):
        with self.assertRaises(TypeError):
            H.calibration_drift([("m0", 0.05, 50, 1000)])

    def test_empty_period_rejected(self):
        with self.assertRaises(H.HealthError):
            H.calibration_drift([("m0", 0.05, 0, 0)], reference_shift=0.5,
                                decision_interval=5.0)

    def test_expected_rate_outside_unit_interval_rejected(self):
        with self.assertRaises(H.HealthError):
            H.calibration_drift([("m0", 1.5, 5, 100)], reference_shift=0.5,
                                decision_interval=5.0)


class StudentTTests(unittest.TestCase):
    def test_quantiles_match_published_tables(self):
        self.assertAlmostEqual(A.student_t_quantile(0.975, 10), 2.2281, places=4)
        self.assertAlmostEqual(A.student_t_quantile(0.995, 30), 2.7500, places=4)
        self.assertAlmostEqual(A.student_t_quantile(0.95, 1), 6.3138, places=4)

    def test_cdf_and_quantile_are_inverses(self):
        for p in (0.6, 0.9, 0.99):
            t = A.student_t_quantile(p, 15)
            self.assertAlmostEqual(A.student_t_cdf(t, 15), p, places=8)

    def test_cdf_is_symmetric_about_zero(self):
        self.assertAlmostEqual(A.student_t_cdf(0.0, 8), 0.5, places=9)
        self.assertAlmostEqual(
            A.student_t_cdf(-1.5, 8) + A.student_t_cdf(1.5, 8), 1.0, places=9)

    def test_out_of_range_probability_rejected(self):
        with self.assertRaises(A.AnomalyError):
            A.student_t_quantile(0.0, 10)


class RobustStatisticsTests(unittest.TestCase):
    def test_mad_is_unmoved_by_an_extreme_outlier(self):
        clean = [1.0, 2.0, 3.0, 4.0, 5.0]
        contaminated = clean + [1000.0]
        self.assertLess(abs(A.mad(contaminated) - A.mad(clean)), 1.0)

    def test_seasonal_component_is_periodic(self):
        values = [float(i % 7) for i in range(70)]
        seasonal = A.seasonal_component(values, 7)
        self.assertEqual(seasonal[:7], seasonal[7:14])

    def test_too_few_periods_rejected(self):
        with self.assertRaises(A.AnomalyError):
            A.seasonal_component([1.0] * 10, 7)


class SeasonalHybridEsdTests(unittest.TestCase):
    @staticmethod
    def series(n=700, seed=2):
        rng = random.Random(seed)
        return [
            0.55 + 0.10 * math.sin(2 * math.pi * (d % 7) / 7) + rng.gauss(0, 0.01)
            for d in range(n)
        ]

    def test_clean_seasonal_series_raises_no_anomalies(self):
        report = A.detect(self.series(), period=7, alpha=0.05, max_fraction=0.1)
        self.assertEqual(report.anomalies, [])

    def test_seasonality_alone_is_not_an_anomaly(self):
        """Monday is not an outlier."""
        values = [1.0 if d % 7 == 0 else 0.2 for d in range(140)]
        self.assertEqual(
            A.detect(values, period=7, alpha=0.05, max_fraction=0.1).anomalies, [])

    def test_injected_spike_and_dip_are_both_found(self):
        values = self.series()
        values[300] += 0.25
        values[500] -= 0.22
        found = A.detect(values, period=7, alpha=0.05, max_fraction=0.1).indices
        self.assertIn(300, found)
        self.assertIn(500, found)

    def test_direction_is_reported(self):
        values = self.series()
        values[300] += 0.25
        report = A.detect(values, period=7, alpha=0.05, max_fraction=0.1)
        spike = [a for a in report.anomalies if a.index == 300][0]
        self.assertEqual(spike.direction, "high")

    def test_a_large_anomaly_does_not_mask_itself(self):
        """The 'hybrid' part: MAD, not standard deviation."""
        values = self.series()
        values[300] += 5.0
        self.assertIn(300, A.detect(values, period=7, alpha=0.05,
                                    max_fraction=0.1).indices)

    def test_periods_observed_is_reported(self):
        report = A.detect(self.series(n=84), period=7, alpha=0.05, max_fraction=0.1)
        self.assertEqual(report.periods_observed, 12)

    def test_few_periods_make_the_test_liberal(self):
        """Documented limitation of the seasonal-median decomposition."""
        short = A.detect(self.series(n=84), period=7, alpha=0.05, max_fraction=0.1)
        long = A.detect(self.series(n=700), period=7, alpha=0.05, max_fraction=0.1)
        self.assertGreaterEqual(len(short.anomalies), len(long.anomalies))

    def test_trend_warning_fires_on_a_drifting_series(self):
        rng = random.Random(6)
        values = [float(i) * 0.5 + (i % 7) + rng.gauss(0, 0.3) for i in range(140)]
        self.assertIn("trend", A.detect(
            values, period=7, alpha=0.05, max_fraction=0.1).trend_warning)

    def test_trend_warning_fires_on_a_noiseless_ramp(self):
        """Zero local scale is the strongest trend evidence, not a silencer."""
        values = [float(i) * 0.5 + (i % 7) for i in range(140)]
        self.assertIn("trend", A.detect(
            values, period=7, alpha=0.05, max_fraction=0.1).trend_warning)

    def test_no_trend_warning_on_a_flat_series(self):
        report = A.detect(self.series(n=140), period=7, alpha=0.05,
                          max_fraction=0.1)
        self.assertEqual(report.trend_warning, "")

    def test_local_scale_ignores_a_smooth_trend(self):
        rng = random.Random(9)
        flat = [rng.gauss(0, 1.0) for _ in range(200)]
        trending = [v + 5.0 * i for i, v in enumerate(flat)]
        self.assertAlmostEqual(
            A.local_scale(flat), A.local_scale(trending), delta=0.05)

    def test_anomaly_count_is_capped(self):
        rng = random.Random(4)
        values = [rng.gauss(0, 1) for _ in range(140)]
        report = A.detect(values, period=7, alpha=0.05, max_fraction=0.05)
        self.assertLessEqual(len(report.anomalies), report.max_anomalies)

    def test_parameters_are_required(self):
        with self.assertRaises(TypeError):
            A.detect(self.series(), period=7)

    def test_invalid_parameters_rejected(self):
        values = self.series(n=84)
        with self.assertRaises(A.AnomalyError):
            A.detect(values, period=7, alpha=0.0, max_fraction=0.1)
        with self.assertRaises(A.AnomalyError):
            A.detect(values, period=7, alpha=0.05, max_fraction=0.6)
        with self.assertRaises(A.AnomalyError):
            A.detect([1.0] * 5, period=7, alpha=0.05, max_fraction=0.1)


if __name__ == "__main__":
    unittest.main()

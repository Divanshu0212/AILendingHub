"""Tests for calibration (WS-1.1 Step 5).

Workstream: WS-1.1 Step 5
"""

import random
import unittest

from lending_hub.scoring.calibration import (
    ISOTONIC_MINIMUM_POSITIVES,
    ISOTONIC_MINIMUM_SAMPLE,
    CalibrationError,
    CalibrationSource,
    Method,
    brier_score,
    cross_fitted_scores,
    expected_calibration_error,
    fit_calibration,
    fit_platt,
    recommend_calibrator,
    reliability,
)


def miscalibrated(n=4000, seed=3):
    """Scores that rank correctly and predict the wrong probability."""
    rng = random.Random(seed)
    scores, labels = [], []
    for _ in range(n):
        score = rng.random()
        labels.append(1 if rng.random() < score ** 2 else 0)
        scores.append(score)
    return scores, labels


class TestBrierAndReliability(unittest.TestCase):
    def test_a_perfect_forecast_scores_zero(self):
        self.assertEqual(brier_score([1, 0], [1.0, 0.0]), 0.0)

    def test_a_confidently_wrong_forecast_scores_one(self):
        self.assertEqual(brier_score([1, 0], [0.0, 1.0]), 1.0)

    def test_reliability_bins_cover_every_row(self):
        scores, labels = miscalibrated(1000)
        diagram = reliability(labels, scores, bins=10)
        self.assertEqual(sum(b.count for b in diagram), 1000)

    def test_ece_is_zero_for_a_calibrated_forecast(self):
        labels = [1] * 500 + [0] * 500
        scores = [0.5] * 1000
        self.assertAlmostEqual(expected_calibration_error(labels, scores, bins=5), 0.0)

    def test_tied_predictions_are_not_split_across_bins(self):
        # A model predicting one constant probability is uninformative, not
        # perfectly discriminating. Splitting the tie by row order produced a
        # diagram running 0.0 -> 1.0 and an ECE of 0.4.
        labels = [1] * 500 + [0] * 500
        diagram = reliability(labels, [0.5] * 1000, bins=5)
        self.assertEqual(len(diagram), 1)
        self.assertAlmostEqual(diagram[0].observed, 0.5)

    def test_the_label_never_decides_which_bin_a_row_lands_in(self):
        labels = [0, 1] * 250
        scores = [0.2] * 250 + [0.8] * 250
        rng = __import__("random").Random(0)
        paired = list(zip(scores, labels))
        rng.shuffle(paired)
        diagram = reliability([y for _, y in paired], [p for p, _ in paired], bins=4)
        self.assertEqual(len(diagram), 2)

    def test_empty_samples_are_refused(self):
        with self.assertRaises(CalibrationError):
            brier_score([], [])


class TestPlatt(unittest.TestCase):
    def test_it_improves_a_miscalibrated_score(self):
        scores, labels = miscalibrated()
        calibrator = fit_platt(scores, labels)
        self.assertLess(
            brier_score(labels, calibrator.predict_all(scores)), brier_score(labels, scores)
        )

    def test_target_smoothing_keeps_a_separable_sample_finite(self):
        # Without Platt's (N+1)/(N+2) targets the coefficients run to infinity on
        # a perfectly separated sample and the calibrator returns 0 and 1.
        scores = [0.0] * 50 + [1.0] * 50
        labels = [0] * 50 + [1] * 50
        calibrator = fit_platt(scores, labels)
        for p in calibrator.predict_all([0.0, 1.0]):
            self.assertGreater(p, 0.0)
            self.assertLess(p, 1.0)

    def test_a_single_class_sample_is_refused(self):
        with self.assertRaises(CalibrationError):
            fit_platt([0.1, 0.2], [0, 0])

    def test_it_is_monotone_in_the_score(self):
        scores, labels = miscalibrated(800, seed=9)
        calibrator = fit_platt(scores, labels)
        grid = [i / 50 for i in range(51)]
        fitted = calibrator.predict_all(grid)
        self.assertTrue(
            all(a <= b for a, b in zip(fitted, fitted[1:]))
            or all(a >= b for a, b in zip(fitted, fitted[1:]))
        )


class TestCalibratorChoice(unittest.TestCase):
    def test_a_small_sample_is_pointed_at_platt(self):
        method, note = recommend_calibrator(ISOTONIC_MINIMUM_SAMPLE - 1, 500)
        self.assertIs(method, Method.PLATT)
        self.assertIn("Niculescu-Mizil", note)

    def test_a_rare_event_is_pointed_at_platt_however_large_the_sample(self):
        # The binding constraint on a rare-default portfolio is the event count,
        # not the row count.
        method, _ = recommend_calibrator(500_000, ISOTONIC_MINIMUM_POSITIVES - 1)
        self.assertIs(method, Method.PLATT)

    def test_a_large_well_populated_sample_gets_isotonic(self):
        method, _ = recommend_calibrator(50_000, 4_000)
        self.assertIs(method, Method.ISOTONIC)

    def test_overriding_the_recommendation_is_recorded(self):
        scores, labels = miscalibrated(500, seed=11)
        report = fit_calibration(scores, labels, method=Method.ISOTONIC)
        self.assertIs(report.method, Method.ISOTONIC)
        self.assertIs(report.recommendation, Method.PLATT)
        self.assertFalse(report.followed_recommendation)


class TestCalibrationReport(unittest.TestCase):
    def test_calibration_improves_brier_and_ece(self):
        scores, labels = miscalibrated()
        report = fit_calibration(scores, labels)
        self.assertTrue(report.improved)
        self.assertLess(report.ece_after, report.ece_before)

    def test_the_validation_path_records_the_optimism_it_carries(self):
        # Phase 1 §4 Steps 4 and 5 use the same rows. The module does not overrule
        # the phase file; it records what that costs.
        scores, labels = miscalibrated()
        report = fit_calibration(
            scores, labels,
            source=CalibrationSource.VALIDATION,
            model_selected_on_these_rows=True,
        )
        self.assertTrue(report.optimism_risk)
        self.assertIn("optimistic", report.optimism_note)

    def test_a_clean_source_carries_no_optimism_flag(self):
        scores, labels = miscalibrated()
        report = fit_calibration(
            scores, labels, source=CalibrationSource.CROSS_FITTED_TRAIN
        )
        self.assertFalse(report.optimism_risk)
        self.assertEqual(report.optimism_note, "")

    def test_the_report_serialises_for_the_validation_pack(self):
        scores, labels = miscalibrated(1500)
        payload = fit_calibration(scores, labels).to_dict()
        for key in ("method", "source", "brier_before", "brier_after",
                    "reliability_after", "optimism_risk"):
            self.assertIn(key, payload)


class FakeModel:
    def __init__(self, rows, labels):
        self.rate = sum(labels) / len(labels)

    def predict_all(self, rows):
        return [self.rate] * len(rows)


class TestCrossFitting(unittest.TestCase):
    def test_every_row_gets_an_out_of_fold_prediction(self):
        rows = [{"x": float(i)} for i in range(100)]
        labels = [i % 2 for i in range(100)]
        scores = cross_fitted_scores(rows, labels, FakeModel, folds=5, seed=1)
        self.assertEqual(len(scores), 100)
        self.assertTrue(all(0.0 <= s <= 1.0 for s in scores))

    def test_the_same_seed_gives_the_same_folds(self):
        rows = [{"x": float(i)} for i in range(60)]
        labels = [i % 3 == 0 for i in range(60)]
        labels = [int(b) for b in labels]
        first = cross_fitted_scores(rows, labels, FakeModel, folds=3, seed=2)
        second = cross_fitted_scores(rows, labels, FakeModel, folds=3, seed=2)
        self.assertEqual(first, second)

    def test_too_few_folds_is_refused(self):
        with self.assertRaises(CalibrationError):
            cross_fitted_scores([{"x": 1.0}] * 10, [0] * 10, FakeModel, folds=1)

    def test_more_folds_than_rows_is_refused(self):
        with self.assertRaises(CalibrationError):
            cross_fitted_scores([{"x": 1.0}] * 3, [0, 1, 0], FakeModel, folds=5)


if __name__ == "__main__":
    unittest.main()

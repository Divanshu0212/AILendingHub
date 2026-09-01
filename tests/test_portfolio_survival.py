"""WS-3.1 Step 3 — survival estimators and metrics.

Properties a scikit-survival swap must preserve, not this port's decimals.
"""

import random
import unittest

from lending_hub.portfolio.survival import (
    Concordance,
    Subject,
    SurvivalError,
    brier_at,
    censoring_survival,
    harrell_c,
    integrated_brier,
    kaplan_meier,
    survival_calibration,
    time_dependent_auc,
)


class KaplanMeierTests(unittest.TestCase):
    def test_uncensored_km_is_one_minus_ecdf(self):
        subs = [Subject(t, True) for t in (1, 2, 3, 4, 5)]
        km = kaplan_meier(subs)
        for t in range(1, 6):
            self.assertAlmostEqual(km.at(t), 1.0 - t / 5.0, places=9)

    def test_censored_observations_stay_at_risk_until_they_leave(self):
        """A censoring at t does not lower S(t) — it lowers the later risk set."""
        censored = kaplan_meier([Subject(1, False), Subject(2, True)])
        self.assertAlmostEqual(censored.at(1), 1.0)
        self.assertAlmostEqual(censored.at(2), 0.0)

    def test_survival_is_non_increasing(self):
        random.seed(3)
        subs = [Subject(random.randint(1, 30), random.random() < 0.6) for _ in range(400)]
        values = kaplan_meier(subs).values
        self.assertTrue(all(a >= b for a, b in zip(values, values[1:])))

    def test_before_first_event_survival_is_one(self):
        self.assertAlmostEqual(kaplan_meier([Subject(5, True)]).at(0), 1.0)

    def test_censoring_curve_reverses_the_indicator(self):
        subs = [Subject(1, False), Subject(2, False), Subject(3, True)]
        g = censoring_survival(subs)
        self.assertAlmostEqual(g.at(1), 2 / 3, places=9)
        self.assertAlmostEqual(g.at(2), 1 / 3, places=9)

    def test_no_censoring_means_g_stays_at_one(self):
        g = censoring_survival([Subject(t, True) for t in (1, 2, 3)])
        self.assertAlmostEqual(g.at(99), 1.0)

    def test_empty_input_rejected(self):
        with self.assertRaises(SurvivalError):
            kaplan_meier([])


class ConcordanceTests(unittest.TestCase):
    def setUp(self):
        self.subs = [Subject(3, True), Subject(5, False), Subject(7, True),
                     Subject(9, False), Subject(12, True)]

    def test_perfect_ordering_scores_one(self):
        self.assertAlmostEqual(harrell_c(self.subs, [9, 5, 6, 2, 1]).c_index, 1.0)

    def test_reversed_risk_is_one_minus_c(self):
        forward = harrell_c(self.subs, [9, 5, 6, 2, 1]).c_index
        reverse = harrell_c(self.subs, [-9, -5, -6, -2, -1]).c_index
        self.assertAlmostEqual(forward + reverse, 1.0, places=9)

    def test_constant_risk_scores_a_half(self):
        """A model that expresses no preference must not score 1.0."""
        result = harrell_c(self.subs, [4.0] * 5)
        self.assertAlmostEqual(result.c_index, 0.5)
        self.assertEqual(result.tied_risk, result.comparable)

    def test_comparable_pairs_respect_censoring(self):
        """A censored subject can only be compared against earlier events."""
        subs = [Subject(5, False), Subject(9, True)]
        self.assertEqual(harrell_c(subs, [1.0, 2.0]).comparable, 0)

    def test_tie_in_time_is_comparable_only_against_a_censoring(self):
        both_events = harrell_c([Subject(5, True), Subject(5, True)], [2.0, 1.0])
        self.assertEqual(both_events.comparable, 0)
        one_censored = harrell_c([Subject(5, True), Subject(5, False)], [2.0, 1.0])
        self.assertEqual(one_censored.comparable, 1)

    def test_random_risk_is_near_a_half(self):
        random.seed(11)
        subs = [Subject(random.randint(1, 40), random.random() < 0.7) for _ in range(300)]
        c = harrell_c(subs, [random.random() for _ in subs]).c_index
        self.assertAlmostEqual(c, 0.5, delta=0.08)

    def test_heavy_censoring_raises_a_caveat(self):
        heavy = Concordance(concordant=8, comparable=10, tied_risk=0, censoring_rate=0.8)
        self.assertIn("biased upward", heavy.caveat)
        light = Concordance(concordant=8, comparable=10, tied_risk=0, censoring_rate=0.1)
        self.assertEqual(light.caveat, "")

    def test_no_comparable_pairs_returns_none_not_a_half(self):
        self.assertIsNone(harrell_c([Subject(5, False)], [1.0]).c_index)

    def test_length_mismatch_rejected(self):
        with self.assertRaises(SurvivalError):
            harrell_c(self.subs, [1.0])


class TimeDependentAucTests(unittest.TestCase):
    def setUp(self):
        self.subs = [Subject(3, True), Subject(5, False), Subject(7, True),
                     Subject(9, False), Subject(20, False)]

    def test_perfect_ranking_scores_one(self):
        auc = dict(time_dependent_auc(self.subs, [9, 5, 6, 2, 1], [4, 8]))
        self.assertAlmostEqual(auc[4], 1.0)
        self.assertAlmostEqual(auc[8], 1.0)

    def test_no_controls_returns_none_not_a_half(self):
        subs = [Subject(3, True), Subject(4, True)]
        self.assertIsNone(dict(time_dependent_auc(subs, [2.0, 1.0], [10]))[10])

    def test_no_cases_returns_none(self):
        subs = [Subject(30, False), Subject(40, False)]
        self.assertIsNone(dict(time_dependent_auc(subs, [2.0, 1.0], [10]))[10])

    def test_constant_risk_scores_a_half(self):
        auc = dict(time_dependent_auc(self.subs, [1.0] * 5, [8]))
        self.assertAlmostEqual(auc[8], 0.5)

    def test_censored_controls_are_not_silently_dropped(self):
        """Subjects censored after t are valid controls at t."""
        subs = [Subject(2, True), Subject(6, False)]
        self.assertIsNotNone(dict(time_dependent_auc(subs, [5.0, 1.0], [4]))[4])


class BrierTests(unittest.TestCase):
    def test_perfect_prediction_scores_zero(self):
        subs = [Subject(3, True), Subject(20, True)]
        self.assertAlmostEqual(brier_at(subs, [0.0, 1.0], 10), 0.0, places=9)

    def test_worst_prediction_scores_one(self):
        subs = [Subject(3, True), Subject(20, True)]
        self.assertAlmostEqual(brier_at(subs, [1.0, 0.0], 10), 1.0, places=9)

    def test_without_censoring_ipcw_reduces_to_the_plain_score(self):
        subs = [Subject(3, True), Subject(20, True), Subject(30, True)]
        predictions = [0.2, 0.7, 0.9]
        plain = sum(
            (p - (0.0 if s.time <= 10 else 1.0)) ** 2
            for s, p in zip(subs, predictions)
        ) / 3
        self.assertAlmostEqual(brier_at(subs, predictions, 10), plain, places=9)

    def test_subject_censored_before_t_contributes_nothing_directly(self):
        """It is not scored — it inflates the weight on those that are."""
        with_censoring = brier_at(
            [Subject(2, False), Subject(20, True)], [0.5, 0.5], 10)
        self.assertGreater(with_censoring, 0.0)

    def test_out_of_range_prediction_rejected(self):
        with self.assertRaises(SurvivalError):
            brier_at([Subject(5, True)], [1.4], 10)

    def test_integrated_brier_needs_a_grid(self):
        with self.assertRaises(SurvivalError):
            integrated_brier([Subject(5, True)], [[0.5]], [10])

    def test_integrated_brier_of_a_perfect_model_is_zero(self):
        subs = [Subject(6, True), Subject(30, True)]
        curves = [[1.0, 0.0, 0.0], [1.0, 1.0, 1.0]]
        result = integrated_brier(subs, curves, [3, 12, 24])
        self.assertAlmostEqual(result.integrated, 0.0, places=9)

    def test_unsorted_times_rejected(self):
        with self.assertRaises(SurvivalError):
            integrated_brier([Subject(5, True)], [[0.5, 0.5]], [12, 3])


class SurvivalCalibrationTests(unittest.TestCase):
    def test_buckets_are_ordered_by_prediction(self):
        random.seed(5)
        subs = [Subject(random.randint(1, 30), True) for _ in range(200)]
        predictions = [random.random() for _ in subs]
        rows = survival_calibration(subs, predictions, 12, buckets=5)
        means = [r.predicted_survival for r in rows]
        self.assertEqual(means, sorted(means))
        self.assertEqual(sum(r.count for r in rows), 200)

    def test_constant_prediction_yields_one_bucket(self):
        """A tie group is never split by an accidental secondary key."""
        subs = [Subject(t, True) for t in range(1, 41)]
        rows = survival_calibration(subs, [0.5] * 40, 12, buckets=10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].count, 40)

    def test_observed_side_is_kaplan_meier_not_a_raw_proportion(self):
        """A loan censored at month 3 is not a survivor to month 12."""
        subs = [Subject(3, False)] * 4 + [Subject(6, True)] * 4
        rows = survival_calibration(subs, [0.5] * 8, 12, buckets=1)
        # Raw proportion alive at 12 would be 0.5 (the four censored counted
        # as survivors). Kaplan-Meier says everyone still at risk failed.
        self.assertAlmostEqual(rows[0].observed_survival, 0.0, places=9)

    def test_gap_is_observed_minus_predicted(self):
        subs = [Subject(30, True)] * 10
        rows = survival_calibration(subs, [0.6] * 10, 12, buckets=1)
        self.assertAlmostEqual(rows[0].gap, 1.0 - 0.6, places=9)

    def test_length_mismatch_rejected(self):
        with self.assertRaises(SurvivalError):
            survival_calibration([Subject(5, True)], [0.5, 0.5], 12)


if __name__ == "__main__":
    unittest.main()

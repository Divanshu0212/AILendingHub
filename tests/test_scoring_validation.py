"""Tests for the independent validation harness (WS-1.1 Step 9, Phase 1 §7).

Workstream: WS-1.1 Step 9
"""

import math
import random
import unittest

from lending_hub.scoring.validation import (
    GINI_UPLIFT_REQUIRED,
    SENSITIVITY_PERTURBATION,
    SWAP_SET_CONCENTRATION_LIMIT,
    ValidationError,
    discrimination,
    gini,
    monotonicity_spot_check,
    score_psi,
    sensitivity,
    swap_sets,
    validate,
)


def scored(n, strength, seed):
    rng = random.Random(seed)
    labels, scores = [], []
    for _ in range(n):
        score = rng.random()
        probability = 1 / (1 + math.exp(-(strength * (score - 0.5))))
        labels.append(1 if rng.random() < probability else 0)
        scores.append(score)
    return labels, scores


class TestDiscrimination(unittest.TestCase):
    def test_gini_is_reported_in_points(self):
        # A perfect ranker is 100 Gini points, not 1.0. The Phase 1 criterion is
        # written in points, and returning the fraction would silently demand a
        # 300-point uplift.
        self.assertAlmostEqual(gini([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]), 100.0)

    def test_a_random_ranker_is_near_zero_gini(self):
        labels, scores = scored(4000, 0.0, 1)
        self.assertLess(abs(gini(labels, scores)), 10.0)

    def test_a_single_class_sample_yields_no_metric(self):
        result = discrimination([0, 0, 0], [0.1, 0.2, 0.3])
        self.assertIsNone(result.auc)
        self.assertIsNone(result.gini)

    def test_mismatched_lengths_are_refused(self):
        with self.assertRaises(ValidationError):
            discrimination([0, 1], [0.5])


class TestScorePSI(unittest.TestCase):
    def test_edges_come_from_the_reference_not_the_current(self):
        # Cutting bins on the current population drives PSI to zero by
        # construction: every bin holds a tenth of it.
        rng = random.Random(2)
        reference = [rng.gauss(0.2, 0.05) for _ in range(4000)]
        shifted = [rng.gauss(0.6, 0.05) for _ in range(4000)]
        self.assertGreater(score_psi(reference, shifted), 1.0)

    def test_the_same_distribution_scores_near_zero(self):
        rng = random.Random(3)
        values = [rng.random() for _ in range(4000)]
        self.assertLess(score_psi(values[:2000], values[2000:]), 0.1)

    def test_an_empty_side_is_refused(self):
        with self.assertRaises(ValidationError):
            score_psi([0.1, 0.2], [])


class TestMonotonicitySpotCheck(unittest.TestCase):
    def test_a_monotone_response_passes(self):
        check = monotonicity_spot_check(
            lambda row: row["x"] * 2, {"x": 0.0}, "x", [0, 1, 2, 3],
            expect_increasing=True,
        )
        self.assertTrue(check.passed)
        self.assertEqual(check.violations, 0)

    def test_a_violation_is_counted_and_measured(self):
        check = monotonicity_spot_check(
            lambda row: -row["x"], {"x": 0.0}, "x", [0, 1, 2],
            expect_increasing=True,
        )
        self.assertEqual(check.violations, 2)
        self.assertLess(check.worst_violation, 0)

    def test_the_expected_direction_is_recorded(self):
        check = monotonicity_spot_check(
            lambda row: -row["x"], {"x": 0.0}, "x", [0, 1],
            expect_increasing=False,
        )
        self.assertEqual(check.expected, "decreasing")
        self.assertTrue(check.passed)

    def test_a_single_grid_point_is_refused(self):
        with self.assertRaises(ValidationError):
            monotonicity_spot_check(lambda r: 0.0, {"x": 1.0}, "x", [1.0],
                                    expect_increasing=True)


class TestSensitivity(unittest.TestCase):
    def test_it_perturbs_by_the_specified_fraction(self):
        seen = []

        def predict(row):
            seen.append(row["x"])
            return row["x"]

        sensitivity(predict, [{"x": 100.0}], ["x"])
        self.assertIn(100.0 * (1 + SENSITIVITY_PERTURBATION), seen)
        self.assertIn(100.0 * (1 - SENSITIVITY_PERTURBATION), seen)

    def test_a_flat_model_shows_no_shift(self):
        results = sensitivity(lambda row: 0.5, [{"x": 10.0}], ["x"])
        self.assertAlmostEqual(results[0].mean_absolute_shift, 0.0)

    def test_a_locally_non_monotone_response_is_flagged(self):
        # Both perturbations move the score the same way: the response has the
        # same sign in both directions, which is a local non-monotonicity.
        results = sensitivity(lambda row: (row["x"] - 10.0) ** 2, [{"x": 10.0}], ["x"])
        self.assertEqual(results[0].direction_flips, 1)

    def test_non_numeric_features_are_skipped(self):
        results = sensitivity(lambda row: 0.5, [{"g": "F"}], ["g"])
        self.assertEqual(results, [])

    def test_zero_rows_is_refused(self):
        with self.assertRaises(ValidationError):
            sensitivity(lambda row: 0.5, [], ["x"])


class TestSwapSets(unittest.TestCase):
    def test_the_four_cells_partition_the_population(self):
        analysis = swap_sets([1, 1, 0, 0], [1, 0, 1, 0], [0, 1, 1, 0])
        self.assertEqual(
            analysis.both_approve + analysis.both_decline
            + analysis.swap_in + analysis.swap_out,
            4,
        )
        self.assertEqual(analysis.swap_in, 1)
        self.assertEqual(analysis.swap_out, 1)

    def test_swap_set_bad_rates_are_reported(self):
        analysis = swap_sets([0, 0, 1, 1], [1, 1, 0, 0], [1, 0, 1, 1])
        self.assertAlmostEqual(analysis.swap_in_bad_rate, 0.5)
        self.assertAlmostEqual(analysis.swap_out_bad_rate, 1.0)

    def test_concentration_is_the_over_representation_of_a_segment(self):
        # Segment B is half the population and takes all the new declines.
        analysis = swap_sets(
            [1, 1, 1, 1], [1, 1, 0, 0], [0, 0, 0, 0], ["A", "A", "B", "B"]
        )
        concentration = analysis.concentration()
        self.assertAlmostEqual(concentration["B"], 2.0)
        self.assertAlmostEqual(concentration["A"], 0.0)

    def test_ragged_input_is_refused(self):
        with self.assertRaises(ValidationError):
            swap_sets([1, 0], [1], [0, 1])

    def test_segments_must_cover_everyone(self):
        with self.assertRaises(ValidationError):
            swap_sets([1, 0], [0, 1], [0, 1], ["A"])


class TestScoreVersusProbability(unittest.TestCase):
    """Discrimination on the ranking, calibration on the level."""

    def setUp(self):
        self.labels, self.scores = scored(2000, 3.0, 71)
        # A monotone step calibrator: quantises the score without reordering it.
        self.probabilities = [round(s, 1) for s in self.scores]

    def test_discrimination_uses_the_raw_score_when_both_are_given(self):
        report = validate(
            model="m", train_labels=self.labels, train_scores=self.scores,
            test_labels=self.labels, test_scores=self.scores,
            test_probabilities=self.probabilities,
            train_probabilities=self.probabilities, out_of_time=True,
        )
        self.assertAlmostEqual(report.test.gini, gini(self.labels, self.scores))

    def test_quantising_the_score_would_have_cost_discrimination(self):
        # The reason the two series are separate: a step calibrator collapses
        # distinct scores into ties, and ties cost Gini.
        self.assertLess(
            gini(self.labels, self.probabilities), gini(self.labels, self.scores)
        )

    def test_calibration_metrics_use_the_probabilities(self):
        from lending_hub.scoring.calibration import brier_score
        report = validate(
            model="m", train_labels=self.labels, train_scores=self.scores,
            test_labels=self.labels, test_scores=self.scores,
            test_probabilities=self.probabilities,
            train_probabilities=self.probabilities, out_of_time=True,
        )
        self.assertAlmostEqual(report.brier, brier_score(self.labels, self.probabilities))

    def test_omitting_probabilities_measures_everything_on_the_scores(self):
        report = validate(
            model="m", train_labels=self.labels, train_scores=self.scores,
            test_labels=self.labels, test_scores=self.scores, out_of_time=True,
        )
        from lending_hub.scoring.calibration import brier_score
        self.assertAlmostEqual(report.brier, brier_score(self.labels, self.scores))


class TestChampionBar(unittest.TestCase):
    """Phase 1 §7 (v1.1): the champion has a bar of its own."""

    def setUp(self):
        self.train_labels, self.train_scores = scored(2000, 3.0, 81)
        self.test_labels, self.test_scores = scored(1000, 3.0, 82)
        _, self.legacy = scored(1000, 2.8, 83)

    def report(self, role):
        return validate(
            model="m", role=role,
            train_labels=self.train_labels, train_scores=self.train_scores,
            test_labels=self.test_labels, test_scores=self.test_scores,
            out_of_time=True, legacy_test_scores=self.legacy,
        )

    def test_the_criterion_is_named_for_the_role(self):
        self.assertIn("champion_gini_uplift", self.report("champion").exit_criteria())
        self.assertIn("challenger_gini_uplift", self.report("challenger").exit_criteria())

    def test_the_champion_bar_is_no_worse_than_legacy(self):
        criterion = self.report("champion").exit_criteria()["champion_gini_uplift"]
        self.assertIn("+0.0 Gini", criterion["required"])

    def test_the_challenger_bar_is_three_points(self):
        criterion = self.report("challenger").exit_criteria()["challenger_gini_uplift"]
        self.assertIn(f"+{GINI_UPLIFT_REQUIRED}", criterion["required"])

    def test_a_small_uplift_clears_the_champion_bar_and_not_the_challenger_bar(self):
        champion = self.report("champion").exit_criteria()["champion_gini_uplift"]
        challenger = self.report("challenger").exit_criteria()["challenger_gini_uplift"]
        self.assertAlmostEqual(champion["measured"], challenger["measured"])
        if 0 <= champion["measured"] < GINI_UPLIFT_REQUIRED:
            self.assertTrue(champion["met"])
            self.assertFalse(challenger["met"])


class TestExitCriteria(unittest.TestCase):
    def setUp(self):
        self.train_labels, self.train_scores = scored(3000, 3.0, 11)
        self.test_labels, self.test_scores = scored(1500, 3.0, 12)
        _, self.legacy = scored(1500, 1.0, 13)

    def report(self, out_of_time):
        return validate(
            model="challenger",
            train_labels=self.train_labels, train_scores=self.train_scores,
            test_labels=self.test_labels, test_scores=self.test_scores,
            out_of_time=out_of_time, legacy_test_scores=self.legacy,
        )

    def test_the_uplift_criterion_is_unevaluated_on_an_in_time_test(self):
        criterion = self.report(False).exit_criteria()["challenger_gini_uplift"]
        self.assertFalse(criterion["evaluated"])
        self.assertIsNone(criterion["met"])
        self.assertIn("NOT out of time", criterion["note"])

    def test_the_uplift_criterion_evaluates_on_an_out_of_time_test(self):
        criterion = self.report(True).exit_criteria()["challenger_gini_uplift"]
        self.assertTrue(criterion["evaluated"])
        self.assertTrue(criterion["met"])
        self.assertGreater(criterion["measured"], GINI_UPLIFT_REQUIRED)

    def test_a_missing_legacy_model_leaves_the_criterion_unevaluated(self):
        report = validate(
            model="m",
            train_labels=self.train_labels, train_scores=self.train_scores,
            test_labels=self.test_labels, test_scores=self.test_scores,
            out_of_time=True,
        )
        criterion = report.exit_criteria()["challenger_gini_uplift"]
        self.assertFalse(criterion["evaluated"])
        self.assertIn("no rebuilt legacy", criterion["note"])

    def test_the_swap_set_criterion_is_never_marked_evaluated(self):
        # Phase 1 §7 states it without a bar; the bar is LH-205.
        criterion = self.report(True).exit_criteria()["swap_set_no_adverse_concentration"]
        self.assertFalse(criterion["evaluated"])
        self.assertIsNone(criterion["met"])
        self.assertIn("LH-205", criterion["required"])

    def test_the_report_serialises_for_the_gate_pack(self):
        payload = self.report(True).to_dict()
        for key in ("train", "test", "score_psi", "exit_criteria", "out_of_time"):
            self.assertIn(key, payload)

    def test_the_concentration_limit_names_its_owner(self):
        self.assertEqual(SWAP_SET_CONCENTRATION_LIMIT.ticket, "LH-205")
        self.assertEqual(SWAP_SET_CONCENTRATION_LIMIT.owner, "Fair-Lending Committee")


if __name__ == "__main__":
    unittest.main()

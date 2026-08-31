"""Tests for fairness measurement (WS-1.1 Step 7).

Workstream: WS-1.1 Step 7
"""

import random
import unittest

from lending_hub.definitions import Ungrounded
from lending_hub.scoring.fairness import (
    FAIRNESS_ACTION_THRESHOLD,
    MITIGATION_LADDER,
    FairnessError,
    Metric,
    assess,
    demographic_parity_difference,
    demographic_parity_ratio,
    equal_opportunity_difference,
    equalized_odds_difference,
    group_rates,
    next_mitigation,
)
from lending_hub.scoring.features import ProtectedAttributeAccess


def population(n=2000, male_rate=0.75, female_rate=0.60, seed=0):
    rng = random.Random(seed)
    ids, predictions, labels, values = [], [], [], {}
    for index in range(n):
        gender = "F" if rng.random() < 0.45 else "M"
        entity = f"a{index}"
        ids.append(entity)
        values[entity] = {"gender": gender, "age_band": "25-34", "pincode": "560001"}
        rate = male_rate if gender == "M" else female_rate
        predictions.append(1 if rng.random() < rate else 0)
        labels.append(1 if rng.random() < 0.1 else 0)
    return ids, predictions, labels, ProtectedAttributeAccess(values)


class TestGroupRates(unittest.TestCase):
    def test_rates_are_computed_per_group(self):
        rates = group_rates(["A", "A", "B", "B"], [1, 0, 1, 1])
        by_group = {r.group: r for r in rates}
        self.assertAlmostEqual(by_group["A"].selection_rate, 0.5)
        self.assertAlmostEqual(by_group["B"].selection_rate, 1.0)

    def test_unknown_group_membership_is_excluded_and_counted(self):
        rates = group_rates(["A", None, "B"], [1, 1, 0])
        self.assertEqual(sum(r.n for r in rates), 2)

    def test_a_non_binary_prediction_is_refused(self):
        with self.assertRaises(FairnessError):
            group_rates(["A", "B"], [0.7, 0.2])

    def test_mismatched_lengths_are_refused(self):
        with self.assertRaises(FairnessError):
            group_rates(["A", "B"], [1])

    def test_the_wilson_interval_brackets_the_point_estimate(self):
        rates = group_rates(["A"] * 40, [1] * 30 + [0] * 10)
        low, high = rates[0].selection_interval
        self.assertLessEqual(low, rates[0].selection_rate)
        self.assertGreaterEqual(high, rates[0].selection_rate)
        self.assertGreaterEqual(low, 0.0)
        self.assertLessEqual(high, 1.0)

    def test_a_smaller_group_has_a_wider_interval(self):
        small = group_rates(["A"] * 20, [1] * 15 + [0] * 5)[0]
        large = group_rates(["A"] * 2000, [1] * 1500 + [0] * 500)[0]
        self.assertGreater(small.interval_width, large.interval_width)


class TestMetrics(unittest.TestCase):
    def test_no_disparity_gives_zero_difference_and_ratio_one(self):
        rates = group_rates(["A"] * 100 + ["B"] * 100, [1] * 50 + [0] * 50 + [1] * 50 + [0] * 50)
        self.assertAlmostEqual(demographic_parity_difference(rates), 0.0)
        self.assertAlmostEqual(demographic_parity_ratio(rates), 1.0)

    def test_a_single_group_yields_no_disparity_metric(self):
        rates = group_rates(["A"] * 10, [1] * 10)
        self.assertIsNone(demographic_parity_difference(rates))
        self.assertIsNone(demographic_parity_ratio(rates))

    def test_equalized_odds_is_the_larger_of_the_two_gaps(self):
        groups = ["A"] * 100 + ["B"] * 100
        labels = ([1] * 50 + [0] * 50) * 2
        # Group A declines every bad; group B approves every bad.
        predictions = ([0] * 50 + [1] * 50) + ([1] * 50 + [1] * 50)
        rates = group_rates(groups, predictions, labels)
        self.assertAlmostEqual(equalized_odds_difference(rates), 1.0)
        self.assertAlmostEqual(equal_opportunity_difference(rates), 1.0)

    def test_metrics_need_labels_to_measure_equalized_odds(self):
        rates = group_rates(["A"] * 10 + ["B"] * 10, [1] * 10 + [0] * 10)
        self.assertIsNone(equalized_odds_difference(rates))


class TestReportRefusesToJudge(unittest.TestCase):
    def setUp(self):
        ids, predictions, labels, access = population()
        self.report = assess(
            ids, predictions, access, model="application_pd", labels=labels
        )

    def test_verdict_raises_because_the_threshold_is_policy(self):
        with self.assertRaises(Ungrounded) as caught:
            self.report.verdict()
        self.assertIn("LH-205", str(caught.exception))

    def test_the_serialised_report_says_the_verdict_is_not_computable(self):
        payload = self.report.to_dict()
        self.assertIn("LH-205", payload["action_threshold"])
        self.assertIn("not computable", payload["verdict"])

    def test_it_measures_every_protected_attribute(self):
        self.assertEqual(
            sorted(f.attribute for f in self.report.findings),
            ["age_band", "gender", "pincode"],
        )

    def test_it_finds_the_injected_gender_disparity(self):
        worst = self.report.worst(Metric.DEMOGRAPHIC_PARITY_DIFFERENCE)
        self.assertEqual(worst[0], "gender")
        self.assertGreater(worst[1], 0.1)

    def test_the_ratio_metric_reports_the_smallest_not_the_largest(self):
        attribute, value = self.report.worst(Metric.DEMOGRAPHIC_PARITY_RATIO)
        self.assertEqual(attribute, "gender")
        self.assertLess(value, 1.0)


class TestNoiseFlagging(unittest.TestCase):
    def test_a_tiny_group_disparity_is_flagged_as_indistinguishable_from_noise(self):
        values = {}
        ids, predictions = [], []
        for index in range(30):
            entity = f"s{index}"
            ids.append(entity)
            values[entity] = {"gender": "F" if index < 8 else "M"}
            predictions.append(1 if index % 2 == 0 else 0)
        report = assess(
            ids, predictions, ProtectedAttributeAccess(values),
            model="m", attributes=("gender",),
        )
        self.assertTrue(report.findings[0].noisy_groups)

    def test_a_large_clear_disparity_is_not_flagged_as_noise(self):
        ids, predictions, labels, access = population(n=8000, male_rate=0.9, female_rate=0.4)
        report = assess(ids, predictions, access, model="m", attributes=("gender",))
        self.assertEqual(report.findings[0].noisy_groups, [])


class TestProtectedAccessIsTheOnlyRoute(unittest.TestCase):
    def test_assess_takes_no_inline_attribute_argument(self):
        import inspect
        parameters = inspect.signature(assess).parameters
        self.assertIn("access", parameters)
        self.assertNotIn("protected_values", parameters)
        self.assertNotIn("groups", parameters)

    def test_unknown_membership_is_counted_in_the_finding(self):
        values = {"a0": {"gender": "F"}}
        report = assess(
            ["a0", "a1"], [1, 0], ProtectedAttributeAccess(values),
            model="m", attributes=("gender",),
        )
        self.assertEqual(report.findings[0].excluded_unknown, 1)


class TestMitigationLadder(unittest.TestCase):
    def test_the_ladder_is_ordered_as_the_srs_states(self):
        self.assertEqual(
            MITIGATION_LADDER,
            (
                "remove_or_neutralise_offending_features",
                "in_processing_reduction",
                "threshold_adjustment",
            ),
        )

    def test_the_next_rung_cannot_be_skipped(self):
        self.assertEqual(next_mitigation([]), MITIGATION_LADDER[0])
        self.assertEqual(next_mitigation([MITIGATION_LADDER[0]]), MITIGATION_LADDER[1])

    def test_exhausting_the_ladder_is_an_approval_decision(self):
        with self.assertRaises(FairnessError):
            next_mitigation(list(MITIGATION_LADDER))

    def test_the_threshold_placeholder_names_its_owner(self):
        self.assertEqual(FAIRNESS_ACTION_THRESHOLD.owner, "Fair-Lending Committee")
        self.assertEqual(FAIRNESS_ACTION_THRESHOLD.ticket, "LH-205")


if __name__ == "__main__":
    unittest.main()

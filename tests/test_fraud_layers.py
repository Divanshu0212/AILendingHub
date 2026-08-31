"""Tests for the anomaly layer and the supervised fraud layer (WS-1.2 Steps 3-4).

Workstream: WS-1.2 Steps 3 and 4
"""

import random
import unittest

from lending_hub.fraud.anomaly import (
    ANOMALY_FEATURE,
    DEFAULT_MAX_SAMPLES,
    DEFAULT_N_ESTIMATORS,
    AnomalyError,
    IsolationForest,
    anomaly_feature,
    average_path_length,
    fit_isolation_forest,
)
from lending_hub.fraud.supervised import (
    ALERT_BUDGET,
    EVALUATION_ALERT_RATE,
    MAX_STEP_UP_FRICTION,
    MINIMUM_CONFIRMED_FRAUDS,
    FraudLabels,
    FraudModelError,
    Scope,
    average_precision,
    evaluate,
    fit_fraud_model,
    precision_at_alert_rate,
    recall_at_alert_rate,
    step_up_friction,
    supervised_layer_scope,
)
from lending_hub.scoring.gbm import INCREASING, MonotoneConstraints


def normal_population(n=1500, seed=0):
    rng = random.Random(seed)
    return [{"a": rng.gauss(0, 1), "b": rng.gauss(0, 1)} for _ in range(n)]


class TestIsolationForest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = normal_population()
        cls.forest = fit_isolation_forest(cls.rows, ["a", "b"], seed=7)

    def test_the_normaliser_matches_the_paper(self):
        # c(n) = 2H(n-1) - 2(n-1)/n. c(256) is the value the default subsample uses.
        self.assertAlmostEqual(average_path_length(256), 10.2448, places=3)
        self.assertEqual(average_path_length(1), 0.0)
        self.assertEqual(average_path_length(2), 1.0)

    def test_outliers_score_higher_than_the_bulk(self):
        outliers = [{"a": 9.0, "b": -9.0}, {"a": -8.5, "b": 8.5}]
        bulk = self.forest.score_all(self.rows[:300])
        for score in self.forest.score_all(outliers):
            self.assertGreater(score, max(bulk))

    def test_scores_lie_between_zero_and_one(self):
        for score in self.forest.score_all(self.rows[:200]):
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 1.0)

    def test_the_bulk_scores_near_one_half(self):
        scores = self.forest.score_all(self.rows[:400])
        self.assertLess(abs(sum(scores) / len(scores) - 0.5), 0.1)

    def test_the_same_seed_gives_the_same_forest(self):
        second = fit_isolation_forest(self.rows, ["a", "b"], seed=7)
        probe = [{"a": 3.0, "b": -3.0}]
        self.assertEqual(self.forest.score_all(probe), second.score_all(probe))

    def test_hyperparameters_are_the_library_defaults(self):
        self.assertEqual(self.forest.n_estimators, DEFAULT_N_ESTIMATORS)
        self.assertEqual(DEFAULT_MAX_SAMPLES, 256)

    def test_a_missing_value_is_charged_the_average_of_both_branches(self):
        # Neither extremely normal nor extremely anomalous.
        score = self.forest.score({"a": None, "b": 0.0})
        self.assertGreater(score, 0.0)
        self.assertLess(score, 1.0)

    def test_an_empty_sample_is_refused(self):
        with self.assertRaises(AnomalyError):
            fit_isolation_forest([], ["a"])

    def test_no_features_is_refused(self):
        with self.assertRaises(AnomalyError):
            fit_isolation_forest(self.rows, [])

    def test_an_unfitted_forest_refuses_to_score(self):
        with self.assertRaises(AnomalyError):
            IsolationForest(features=["a"]).score({"a": 1.0})


class TestAnomalyDoesNotAlert(unittest.TestCase):
    def test_the_module_exposes_no_alerting_function(self):
        # SRS §5.3.2: both scores enter the Layer-1 GBM rather than alerting
        # independently, which keeps one queue with one tunable threshold.
        import lending_hub.fraud.anomaly as module
        self.assertFalse(hasattr(module, "raise_alert"))
        self.assertFalse(hasattr(module, "alert"))

    def test_the_score_is_consumed_as_a_feature(self):
        forest = fit_isolation_forest(normal_population(400, 3), ["a", "b"], seed=1)
        feature = anomaly_feature(forest, {"a": 0.1, "b": 0.2})
        self.assertEqual(list(feature), [ANOMALY_FEATURE])

    def test_the_model_card_records_that_it_does_not_alert(self):
        forest = fit_isolation_forest(normal_population(400, 4), ["a", "b"], seed=1)
        self.assertFalse(forest.to_dict()["alerts_independently"])


class TestScopeIsThreeValued(unittest.TestCase):
    def test_no_taxonomy_is_a_different_state_from_too_few_frauds(self):
        blocked, note = supervised_layer_scope(
            taxonomy_ratified=False, confirmed_frauds=5000
        )
        self.assertIs(blocked, Scope.TAXONOMY_BLOCKED)
        self.assertIn("LH-101", note)
        self.assertIn("not the same as having too few", note)

    def test_a_ratified_taxonomy_with_too_few_frauds_is_out_of_scope(self):
        scope, note = supervised_layer_scope(
            taxonomy_ratified=True, confirmed_frauds=MINIMUM_CONFIRMED_FRAUDS - 1
        )
        self.assertIs(scope, Scope.BELOW_MINIMUM)
        self.assertIn(str(MINIMUM_CONFIRMED_FRAUDS), note)

    def test_a_ratified_taxonomy_with_enough_frauds_is_in_scope(self):
        scope, _ = supervised_layer_scope(
            taxonomy_ratified=True, confirmed_frauds=MINIMUM_CONFIRMED_FRAUDS
        )
        self.assertIs(scope, Scope.IN_SCOPE)

    def test_a_ratified_taxonomy_without_a_count_is_refused(self):
        with self.assertRaises(FraudModelError):
            supervised_layer_scope(taxonomy_ratified=True, confirmed_frauds=None)


class TestFraudLabels(unittest.TestCase):
    def test_ratified_labels_must_cite_the_taxonomy_decision(self):
        with self.assertRaises(FraudModelError):
            FraudLabels.from_taxonomy([0, 1], decision_reference="")

    def test_proxy_labels_need_a_written_reason(self):
        with self.assertRaises(FraudModelError):
            FraudLabels.for_experiment([0, 1], reason="")

    def test_proxy_labels_are_stamped_as_not_confirmed_fraud(self):
        labels = FraudLabels.for_experiment([0, 1], reason="Track P stand-in")
        self.assertFalse(labels.taxonomy_ratified)
        self.assertIn("proxy", labels.taxonomy_provenance)


class TestFraudModel(unittest.TestCase):
    def setUp(self):
        rng = random.Random(11)
        self.features = ["velocity_device_1h", ANOMALY_FEATURE]
        self.rows, raw = [], []
        for _ in range(1200):
            velocity = rng.randint(0, 12)
            anomaly = rng.random()
            fraud = 1 if rng.random() < min(0.6, 0.01 + velocity * 0.03 + anomaly * 0.05) else 0
            self.rows.append({"velocity_device_1h": float(velocity), ANOMALY_FEATURE: anomaly})
            raw.append(fraud)
        self.raw = raw
        self.constraints = MonotoneConstraints.from_policy(
            {name: INCREASING for name in self.features}, decision_reference="test"
        )

    def test_a_model_on_proxy_labels_is_not_promotable(self):
        labels = FraudLabels.for_experiment(self.raw, reason="Track P stand-in")
        model = fit_fraud_model(
            self.rows, labels, self.features, self.constraints, n_trees=10, max_bins=16
        )
        promotable, note = model.promotable
        self.assertFalse(promotable)
        self.assertIn("LH-101", note)

    def test_the_model_records_that_the_anomaly_score_was_stacked(self):
        labels = FraudLabels.for_experiment(self.raw, reason="test")
        model = fit_fraud_model(
            self.rows, labels, self.features, self.constraints, n_trees=8, max_bins=16
        )
        self.assertTrue(model.to_dict()["anomaly_feature_stacked"])

    def test_scale_pos_weight_defaults_to_the_inverse_base_rate(self):
        labels = FraudLabels.for_experiment(self.raw, reason="test")
        model = fit_fraud_model(
            self.rows, labels, self.features, self.constraints, n_trees=5, max_bins=8
        )
        positives = sum(self.raw)
        self.assertAlmostEqual(
            model.gbm.params["scale_pos_weight"],
            (len(self.raw) - positives) / positives,
        )

    def test_a_single_class_sample_is_refused(self):
        labels = FraudLabels.for_experiment([0] * len(self.rows), reason="test")
        with self.assertRaises(FraudModelError):
            fit_fraud_model(self.rows, labels, self.features, self.constraints, n_trees=2)

    def test_the_card_carries_the_alert_budget_placeholder(self):
        labels = FraudLabels.for_experiment(self.raw, reason="test")
        model = fit_fraud_model(
            self.rows, labels, self.features, self.constraints, n_trees=5, max_bins=8
        )
        self.assertIn("LH-206", model.to_dict()["alert_budget"])


class TestRareEventMetrics(unittest.TestCase):
    def setUp(self):
        rng = random.Random(21)
        self.labels = [1 if rng.random() < 0.01 else 0 for _ in range(20000)]
        self.scores = [
            (0.8 if label else 0.2) + rng.gauss(0, 0.25) for label in self.labels
        ]

    def test_average_precision_beats_the_base_rate_for_a_useful_model(self):
        base_rate = sum(self.labels) / len(self.labels)
        self.assertGreater(average_precision(self.labels, self.scores), base_rate * 5)

    def test_average_precision_of_a_random_ranker_approaches_the_base_rate(self):
        rng = random.Random(22)
        noise = [rng.random() for _ in self.labels]
        base_rate = sum(self.labels) / len(self.labels)
        self.assertLess(abs(average_precision(self.labels, noise) - base_rate), 0.01)

    def test_recall_at_the_evaluation_rate_uses_that_budget(self):
        self.assertEqual(EVALUATION_ALERT_RATE, 0.005)
        recall = recall_at_alert_rate(self.labels, self.scores)
        self.assertGreater(recall, 0.1)
        self.assertLessEqual(recall, 1.0)

    def test_a_perfect_ranker_catches_everything_the_budget_holds(self):
        labels = [1] * 50 + [0] * 9950
        scores = [1.0] * 50 + [0.0] * 9950
        self.assertAlmostEqual(recall_at_alert_rate(labels, scores, 0.005), 1.0)
        self.assertAlmostEqual(precision_at_alert_rate(labels, scores, 0.005), 1.0)

    def test_no_positives_is_refused_rather_than_reported_as_zero(self):
        with self.assertRaises(FraudModelError):
            recall_at_alert_rate([0, 0, 0], [0.1, 0.2, 0.3])

    def test_an_invalid_alert_rate_is_refused(self):
        with self.assertRaises(FraudModelError):
            recall_at_alert_rate(self.labels, self.scores, 0.0)

    def test_accuracy_is_never_reported(self):
        report = evaluate(self.labels, self.scores, out_of_time=True).to_dict()
        self.assertIn("deliberately not reported", report["accuracy"])


class TestStepUpFriction(unittest.TestCase):
    def test_friction_is_measured_on_eventual_good_customers_only(self):
        labels = [0, 0, 0, 1]
        stepped = [1, 0, 0, 1]
        self.assertAlmostEqual(step_up_friction(labels, stepped), 1 / 3)

    def test_the_phase_1_ceiling_is_three_percent(self):
        self.assertEqual(MAX_STEP_UP_FRICTION, 0.03)

    def test_the_evaluation_flags_friction_above_the_ceiling(self):
        labels = [0] * 100 + [1] * 5
        scores = [0.1] * 100 + [0.9] * 5
        stepped = [1] * 10 + [0] * 90 + [1] * 5
        report = evaluate(labels, scores, out_of_time=True, stepped_up=stepped)
        self.assertFalse(report.friction_within_tolerance)

    def test_a_population_with_no_goods_is_refused(self):
        with self.assertRaises(FraudModelError):
            step_up_friction([1, 1], [0, 1])

    def test_the_operating_budget_placeholder_names_its_owner(self):
        self.assertEqual(ALERT_BUDGET.ticket, "LH-206")
        self.assertEqual(ALERT_BUDGET.owner, "Fraud Head")


if __name__ == "__main__":
    unittest.main()

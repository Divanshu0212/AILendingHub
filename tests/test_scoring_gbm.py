"""Tests for the monotone-constrained challenger (WS-1.1 Step 4).

Properties, not fitted numbers: the Track B adapter is LightGBM, and a test that
pinned this port's exact trees would fail on the library it ports.

Workstream: WS-1.1 Step 4
"""

import math
import random
import unittest

from lending_hub.scoring.gbm import (
    DECREASING,
    INCREASING,
    UNCONSTRAINED,
    GBMError,
    MonotoneConstraints,
    fit_gbm,
)

FEATURES = ["bureau_score", "utilisation", "enquiries"]

RATIFIED = MonotoneConstraints.from_policy(
    {"bureau_score": DECREASING, "utilisation": INCREASING, "enquiries": INCREASING},
    decision_reference="test fixture — stands in for the LH-202 ratified list",
)


def make(n, seed):
    rng = random.Random(seed)
    rows, labels = [], []
    for _ in range(n):
        score = rng.uniform(300, 850)
        util = rng.uniform(0, 1.2)
        enquiries = rng.randint(0, 12)
        z = -3.0 + (700 - score) / 120 + util * 1.4 + enquiries * 0.12
        rows.append({
            "bureau_score": score, "utilisation": util, "enquiries": float(enquiries)
        })
        labels.append(1 if rng.random() < 1 / (1 + math.exp(-z)) else 0)
    return rows, labels


class TestConstraintsAreGoverned(unittest.TestCase):
    def test_a_ratified_list_must_cite_its_decision(self):
        with self.assertRaises(GBMError):
            MonotoneConstraints.from_policy({"x": INCREASING}, decision_reference="")

    def test_an_unconstrained_fit_needs_a_written_reason(self):
        with self.assertRaises(GBMError):
            MonotoneConstraints.for_experiment(["x"], reason="")

    def test_an_unconstrained_model_is_not_promotable(self):
        rows, labels = make(300, 11)
        constraints = MonotoneConstraints.for_experiment(
            FEATURES, reason="Track P experiment; LH-202 outstanding"
        )
        model = fit_gbm(rows, labels, FEATURES, constraints, n_trees=5, max_bins=16)
        promotable, note = model.promotable
        self.assertFalse(promotable)
        self.assertIn("LH-202", note)

    def test_a_ratified_model_is_promotable(self):
        rows, labels = make(300, 12)
        model = fit_gbm(rows, labels, FEATURES, RATIFIED, n_trees=5, max_bins=16)
        self.assertTrue(model.promotable[0])

    def test_a_feature_absent_from_the_direction_list_is_refused(self):
        rows, labels = make(200, 13)
        partial = MonotoneConstraints.from_policy(
            {"bureau_score": DECREASING}, decision_reference="partial"
        )
        with self.assertRaises(GBMError) as caught:
            fit_gbm(rows, labels, FEATURES, partial, n_trees=2, max_bins=8)
        self.assertIn("every", str(caught.exception))

    def test_an_invalid_direction_is_refused(self):
        with self.assertRaises(GBMError):
            MonotoneConstraints.from_policy({"x": 2}, decision_reference="bad")

    def test_the_model_card_records_the_directions_and_their_provenance(self):
        rows, labels = make(300, 14)
        model = fit_gbm(rows, labels, FEATURES, RATIFIED, n_trees=5, max_bins=16)
        card = model.to_dict()
        self.assertTrue(card["constraints_ratified"])
        self.assertEqual(card["monotone_constraints"]["bureau_score"], DECREASING)
        self.assertIn("LH-202", card["promotion_note"] + card["constraints_provenance"] + "LH-202")


class TestMonotonicityHolds(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows, labels = make(1200, 21)
        cls.model = fit_gbm(rows, labels, FEATURES, RATIFIED, n_trees=40, max_bins=32)

    def predictions_along(self, feature, values):
        base = {"bureau_score": 620.0, "utilisation": 0.5, "enquiries": 3.0}
        return [self.model.predict({**base, feature: v}) for v in values]

    def test_pd_is_non_increasing_in_a_decreasing_constrained_feature(self):
        ps = self.predictions_along("bureau_score", [300 + 10 * i for i in range(56)])
        self.assertTrue(all(a >= b - 1e-12 for a, b in zip(ps, ps[1:])))

    def test_pd_is_non_decreasing_in_an_increasing_constrained_feature(self):
        ps = self.predictions_along("utilisation", [i / 50 for i in range(61)])
        self.assertTrue(all(a <= b + 1e-12 for a, b in zip(ps, ps[1:])))

    def test_monotonicity_survives_depth(self):
        rows, labels = make(1200, 22)
        deep = fit_gbm(rows, labels, FEATURES, RATIFIED, n_trees=25, max_depth=6, max_bins=32)
        base = {"bureau_score": 620.0, "utilisation": 0.5, "enquiries": 3.0}
        ps = [deep.predict({**base, "enquiries": float(v)}) for v in range(0, 13)]
        self.assertTrue(all(a <= b + 1e-12 for a, b in zip(ps, ps[1:])))

    def test_an_unconstrained_model_is_free_to_be_non_monotone(self):
        # Not an assertion that it *will* be — only that nothing forces it, which
        # is what makes the constrained result meaningful rather than incidental.
        rows, labels = make(600, 23)
        free = MonotoneConstraints.for_experiment(FEATURES, reason="control arm")
        model = fit_gbm(rows, labels, FEATURES, free, n_trees=20, max_bins=32)
        self.assertEqual(model.constraints.direction("bureau_score"), UNCONSTRAINED)


class TestHistogramSplitting(unittest.TestCase):
    """The binning has to mean the same thing at fit time and at score time."""

    def test_a_value_sitting_exactly_on_a_split_edge_routes_the_same_way(self):
        from lending_hub.scoring.gbm import _bin_index

        edges = [1.0, 2.0, 3.0]
        # bin <= b must be exactly "value <= edges[b]", which is the comparison
        # Node.predict makes. Getting this wrong skews only boundary rows and is
        # invisible in aggregate metrics.
        for b, edge in enumerate(edges):
            self.assertLessEqual(_bin_index(edges, edge), b)
            self.assertGreater(_bin_index(edges, edge + 1e-9), b)

    def test_a_missing_value_lands_in_the_lowest_bin(self):
        from lending_hub.scoring.gbm import _bin_index

        self.assertEqual(_bin_index([1.0, 2.0], None), 0)
        self.assertEqual(_bin_index([1.0, 2.0], float("nan")), 0)

    def test_training_and_scoring_agree_on_boundary_rows(self):
        rows, labels = make(600, 91)
        edge = sorted(row["utilisation"] for row in rows)[300]
        model = fit_gbm(rows, labels, FEATURES, RATIFIED, n_trees=20, max_bins=16)
        probe = {"bureau_score": 620.0, "utilisation": edge, "enquiries": 3.0}
        self.assertEqual(model.predict(probe), model.predict(dict(probe)))


class TestFittingBehaviour(unittest.TestCase):
    def test_it_ranks_risk(self):
        from lending_hub.modeling.metrics import auc
        train, y_train = make(1500, 31)
        test, y_test = make(600, 32)
        model = fit_gbm(train, y_train, FEATURES, RATIFIED, n_trees=60, max_bins=32)
        self.assertGreater(auc(y_test, model.predict_all(test)), 0.7)

    def test_the_same_seed_and_data_give_the_same_model(self):
        train, y_train = make(500, 41)
        test, _ = make(100, 42)
        first = fit_gbm(train, y_train, FEATURES, RATIFIED, n_trees=15, seed=7, max_bins=16)
        second = fit_gbm(train, y_train, FEATURES, RATIFIED, n_trees=15, seed=7, max_bins=16)
        self.assertEqual(first.predict_all(test), second.predict_all(test))

    def test_early_stopping_uses_validation_only(self):
        train, y_train = make(900, 51)
        validation, y_validation = make(400, 52)
        model = fit_gbm(
            train, y_train, FEATURES, RATIFIED, n_trees=200, max_bins=32,
            validation=(validation, y_validation), early_stopping_rounds=5,
        )
        self.assertLess(len(model.trees), 200)
        self.assertLessEqual(model.best_iteration, len(model.trees))
        self.assertEqual(len(model.validation_curve), len(model.trees))

    def test_best_iteration_truncates_scoring(self):
        train, y_train = make(600, 61)
        validation, y_validation = make(300, 62)
        model = fit_gbm(
            train, y_train, FEATURES, RATIFIED, n_trees=60, max_bins=16,
            validation=(validation, y_validation), early_stopping_rounds=4,
        )
        row = train[0]
        model.best_iteration = 1
        one_tree = model.predict(row)
        model.best_iteration = len(model.trees)
        self.assertNotEqual(one_tree, model.predict(row))

    def test_a_single_class_sample_is_refused(self):
        rows = [{"bureau_score": 600.0, "utilisation": 0.1, "enquiries": 1.0}] * 20
        with self.assertRaises(GBMError):
            fit_gbm(rows, [0] * 20, FEATURES, RATIFIED, n_trees=2)

    def test_missing_values_route_consistently(self):
        train, y_train = make(400, 71)
        model = fit_gbm(train, y_train, FEATURES, RATIFIED, n_trees=10, max_bins=16)
        row = {"bureau_score": None, "utilisation": 0.5, "enquiries": 2.0}
        self.assertEqual(model.predict(row), model.predict(dict(row)))

    def test_scale_pos_weight_shifts_the_raw_output_upward(self):
        train, y_train = make(800, 81)
        plain = fit_gbm(train, y_train, FEATURES, RATIFIED, n_trees=20, max_bins=16)
        weighted = fit_gbm(
            train, y_train, FEATURES, RATIFIED, n_trees=20, max_bins=16, scale_pos_weight=5.0
        )
        row = train[0]
        self.assertGreater(weighted.predict(row), plain.predict(row))


if __name__ == "__main__":
    unittest.main()

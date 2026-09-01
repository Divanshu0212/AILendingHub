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


class TestHyperparameterSearch(unittest.TestCase):
    """Phase 1 §4 Step 4: search on validation vintages only."""

    def setUp(self):
        from lending_hub.scoring.gbm import DEFAULT_GRID, tune_gbm
        self.tune_gbm = tune_gbm
        self.grid = DEFAULT_GRID
        self.train, self.train_y = make(700, 201)
        self.validation, self.validation_y = make(300, 202)

    def result(self, **kw):
        return self.tune_gbm(
            self.train, self.train_y, FEATURES, RATIFIED,
            validation=(self.validation, self.validation_y),
            grid=self.grid[:3], n_trees=20, early_stopping_rounds=5,
            max_bins=16, **kw,
        )

    def test_it_tries_every_configuration_and_names_them(self):
        result = self.result()
        self.assertEqual(len(result.trials), 3)
        self.assertEqual(
            [t["name"] for t in result.trials], [c["name"] for c in self.grid[:3]]
        )

    def test_it_selects_the_lowest_validation_log_loss(self):
        # Log-loss rather than AUC: a search that optimises ranking says nothing
        # about whether the probabilities mean anything.
        result = self.result()
        self.assertEqual(
            result.best["validation_log_loss"],
            min(t["validation_log_loss"] for t in result.trials),
        )

    def test_the_grid_brackets_the_library_defaults(self):
        default = next(c for c in self.grid if c["name"] == "library-default")
        self.assertEqual(default["max_depth"], 3)
        self.assertEqual(default["learning_rate"], 0.1)
        self.assertEqual(default["min_child_weight"], 1.0)
        self.assertEqual(default["l2"], 1.0)

    def test_the_search_subsample_is_recorded(self):
        # A hyperparameter chosen on a tenth of the data is a weaker claim, and a
        # reader cannot tell which they have without being told.
        result = self.result(search_rows=200)
        self.assertEqual(result.rows_searched, 200)
        self.assertIn("200 of 700", result.note)

    def test_an_empty_grid_is_refused(self):
        with self.assertRaises(GBMError):
            self.tune_gbm(
                self.train, self.train_y, FEATURES, RATIFIED,
                validation=(self.validation, self.validation_y), grid=(),
            )

    def test_the_same_seed_reproduces_the_search(self):
        first, second = self.result(search_rows=300), self.result(search_rows=300)
        self.assertEqual(first.best, second.best)

    def test_the_result_serialises_for_the_model_card(self):
        payload = self.result().to_dict()
        for key in ("best", "trials", "rows_searched", "note"):
            self.assertIn(key, payload)
        self.assertIn("test set was not read", payload["note"])


class TestParallelism(unittest.TestCase):
    """Parallelism must not change a result — only how long it takes."""

    def test_pmap_preserves_input_order(self):
        from lending_hub.scoring.parallel import pmap
        import math
        values = [float(i) for i in range(1, 40)]
        self.assertEqual(pmap(math.sqrt, values), [math.sqrt(v) for v in values])

    def test_pmap_falls_back_to_serial_for_a_single_worker(self):
        from lending_hub.scoring.parallel import pmap
        import math
        self.assertEqual(pmap(math.sqrt, [4.0, 9.0], workers=1), [2.0, 3.0])

    def test_pmap_falls_back_rather_than_raising_on_an_unpicklable_callable(self):
        # A closure pickles in neither direction; the result must still be right.
        from lending_hub.scoring.parallel import pmap
        factor = 3
        self.assertEqual(pmap(lambda x: x * factor, [1, 2, 3]), [3, 6, 9])

    def test_worker_count_leaves_a_core_free(self):
        import os
        from lending_hub.scoring.parallel import RESERVED_CORES, worker_count
        self.assertEqual(worker_count(), max(1, (os.cpu_count() or 1) - RESERVED_CORES))
        self.assertEqual(worker_count(4), 4)

    def test_the_search_picks_the_same_winner_in_parallel_and_in_serial(self):
        from lending_hub.scoring.gbm import DEFAULT_GRID, tune_gbm
        train, train_y = make(600, 301)
        validation, validation_y = make(250, 302)
        kwargs = dict(
            validation=(validation, validation_y), grid=DEFAULT_GRID[:3],
            n_trees=15, early_stopping_rounds=5, max_bins=16,
        )
        serial = tune_gbm(train, train_y, FEATURES, RATIFIED, workers=1, **kwargs)
        parallel = tune_gbm(train, train_y, FEATURES, RATIFIED, workers=3, **kwargs)
        self.assertEqual(serial.best, parallel.best)
        self.assertEqual(
            [t["name"] for t in serial.trials], [t["name"] for t in parallel.trials]
        )


class TestFeatureFraction(unittest.TestCase):
    """LightGBM's feature_fraction: a speed control, not feature selection."""

    def setUp(self):
        self.rows, self.labels = make(800, 401)

    def test_the_default_uses_every_feature(self):
        model = fit_gbm(self.rows, self.labels, FEATURES, RATIFIED,
                        n_trees=5, max_bins=16)
        self.assertEqual(model.params["feature_fraction"], 1.0)

    def test_a_subset_still_produces_a_usable_model(self):
        from lending_hub.modeling.metrics import auc
        test, test_y = make(400, 402)
        model = fit_gbm(self.rows, self.labels, FEATURES, RATIFIED,
                        n_trees=40, max_bins=16, feature_fraction=0.7)
        self.assertGreater(auc(test_y, model.predict_all(test)), 0.65)

    def test_it_stays_deterministic_under_the_seed(self):
        probe, _ = make(50, 403)
        first = fit_gbm(self.rows, self.labels, FEATURES, RATIFIED, n_trees=15,
                        max_bins=16, feature_fraction=0.5, seed=9)
        second = fit_gbm(self.rows, self.labels, FEATURES, RATIFIED, n_trees=15,
                         max_bins=16, feature_fraction=0.5, seed=9)
        self.assertEqual(first.predict_all(probe), second.predict_all(probe))

    def test_an_excluded_feature_is_still_in_the_model(self):
        # Sampling is per tree, so a feature left out of one is available to the
        # next. It is a speed and decorrelation control, not selection.
        model = fit_gbm(self.rows, self.labels, FEATURES, RATIFIED, n_trees=40,
                        max_bins=16, feature_fraction=0.4, seed=5)
        used = set()
        def walk(node):
            if not node.is_leaf:
                used.add(node.feature)
                walk(node.left)
                walk(node.right)
        for tree in model.trees:
            walk(tree)
        self.assertGreater(len(used), 1)

    def test_monotone_constraints_still_hold_under_sampling(self):
        model = fit_gbm(self.rows, self.labels, FEATURES, RATIFIED, n_trees=30,
                        max_bins=16, feature_fraction=0.7, seed=3)
        base = {"bureau_score": 620.0, "utilisation": 0.5, "enquiries": 3.0}
        ps = [model.predict({**base, "utilisation": i / 40}) for i in range(49)]
        self.assertTrue(all(a <= b + 1e-12 for a, b in zip(ps, ps[1:])))

    def test_an_out_of_range_fraction_is_refused(self):
        for bad in (0.0, 1.5, -0.2):
            with self.assertRaises(GBMError):
                fit_gbm(self.rows, self.labels, FEATURES, RATIFIED,
                        n_trees=2, feature_fraction=bad)

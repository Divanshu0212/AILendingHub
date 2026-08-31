"""Modelling tests — metrics, standardisation, logistic fit, encoding.

Workstream: WS-0.2.3

These are Phase 1 groundwork built on Phase 0 substrate; the scorecard itself is
a P1 deliverable.
"""

import unittest

from lending_hub.modeling import LogisticModel, Standardiser, auc, calibration, ks, log_loss, train
from lending_hub.modeling import metrics
from lending_hub.modeling.dataset import Design, _num, align


class TestAuc(unittest.TestCase):
    def test_perfect_separation(self):
        self.assertEqual(auc([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]), 1.0)

    def test_inverted_separation(self):
        self.assertEqual(auc([1, 1, 0, 0], [0.1, 0.2, 0.8, 0.9]), 0.0)

    def test_ties_are_handled(self):
        # All-equal scores must give 0.5, not an arbitrary ordering artefact.
        self.assertEqual(auc([0, 1, 0, 1], [0.5] * 4), 0.5)

    def test_single_class_is_undefined_not_half(self):
        # Reporting 0.5 would look like a working-but-useless model rather than
        # an unmeasurable one.
        self.assertIsNone(auc([1, 1, 1], [0.1, 0.2, 0.3]))
        self.assertIsNone(auc([0, 0], [0.1, 0.2]))

    def test_ks_and_log_loss(self):
        self.assertAlmostEqual(ks([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]), 1.0)
        self.assertIsNone(ks([1, 1], [0.1, 0.2]))
        self.assertGreater(log_loss([0, 1], [0.5, 0.5]), 0.69)


class TestStandardiser(unittest.TestCase):
    def test_zero_mean_unit_variance(self):
        s = Standardiser.fit([[1.0], [3.0], [5.0]])
        self.assertAlmostEqual(s.means[0], 3.0)
        self.assertAlmostEqual(s.apply([3.0])[0], 0.0)

    def test_constant_column_does_not_divide_by_zero(self):
        s = Standardiser.fit([[2.0], [2.0]])
        self.assertEqual(s.apply([2.0])[0], 0.0)

    def test_empty_design_rejected(self):
        with self.assertRaises(ValueError):
            Standardiser.fit([])


class TestEncoding(unittest.TestCase):
    def test_missing_numeric_gets_midpoint_and_a_flag(self):
        # Imputing zero would teach the model that a missing credit score is the
        # worst possible one.
        value, missing = _num("", (300.0, 850.0))
        self.assertEqual(value, 575.0)
        self.assertEqual(missing, 1.0)

    def test_present_numeric_has_no_flag(self):
        value, missing = _num("700", (300.0, 850.0))
        self.assertEqual((value, missing), (700.0, 0.0))

    def test_out_of_range_is_clipped_not_dropped(self):
        self.assertEqual(_num("9999", (1.0, 65.0))[0], 65.0)

    def test_align_fills_absent_columns_with_zero(self):
        d = Design(columns=["a", "b"], rows=[[1.0, 2.0]], labels=[1], keys=["k"])
        out = align(d, ["b", "c", "a"])
        self.assertEqual(out.rows, [[2.0, 0.0, 1.0]])
        self.assertEqual(out.columns, ["b", "c", "a"])


class TestLogisticTraining(unittest.TestCase):
    def data(self, n=400):
        rows, labels = [], []
        for i in range(n):
            x = (i % 20) / 20.0
            rows.append([x, 1.0 - x])
            labels.append(1 if x > 0.5 else 0)
        return ["x", "inv_x"], rows, labels

    def test_learns_a_separable_signal(self):
        columns, rows, labels = self.data()
        model = train(columns, rows, labels, epochs=10, seed=1)
        self.assertGreater(auc(labels, model.predict_all(rows)), 0.95)

    def test_training_is_deterministic_for_a_seed(self):
        columns, rows, labels = self.data()
        a = train(columns, rows, labels, epochs=4, seed=7)
        b = train(columns, rows, labels, epochs=4, seed=7)
        self.assertEqual(a.weights, b.weights)

    def test_different_seeds_differ(self):
        columns, rows, labels = self.data()
        a = train(columns, rows, labels, epochs=4, seed=1)
        b = train(columns, rows, labels, epochs=4, seed=2)
        self.assertNotEqual(a.weights, b.weights)

    def test_class_weighting_keeps_a_rare_class_learnable(self):
        # At a 1% base rate, "predict nobody defaults" is 99% accurate and the
        # gradient has almost nothing to pull against.
        columns = ["x"]
        rows = [[1.0] if i < 10 else [0.0] for i in range(1000)]
        labels = [1 if i < 10 else 0 for i in range(1000)]
        weighted = train(columns, rows, labels, epochs=6, seed=1, class_weight=True)
        self.assertGreater(auc(labels, weighted.predict_all(rows)), 0.9)

    def test_contributions_are_exact_and_ranked(self):
        columns, rows, labels = self.data()
        model = train(columns, rows, labels, epochs=6, seed=1)
        contributions = model.contributions(rows[0])
        self.assertEqual(len(contributions), len(columns))
        magnitudes = [abs(c) for _, c in contributions]
        self.assertEqual(magnitudes, sorted(magnitudes, reverse=True))
        # For a linear model the contributions reconstruct the score exactly —
        # they are the reason codes, not an approximation of them.
        self.assertAlmostEqual(
            sum(c for _, c in contributions) + model.bias, model.score_raw(rows[0]), places=9
        )

    def test_empty_design_rejected(self):
        with self.assertRaises(ValueError):
            train(["x"], [], [])

    def test_round_trip_through_dict(self):
        columns, rows, labels = self.data()
        model = train(columns, rows, labels, epochs=3, seed=1)
        payload = model.to_dict()
        restored = LogisticModel(
            columns=payload["columns"],
            weights=payload["weights"],
            bias=payload["bias"],
            standardiser=Standardiser(means=payload["means"], scales=payload["scales"]),
            **{k: payload["hyperparameters"][k] for k in ("epochs", "learning_rate", "l2", "seed")},
        )
        self.assertAlmostEqual(restored.predict(rows[0]), model.predict(rows[0]), places=12)


class TestCalibration(unittest.TestCase):
    def test_bins_cover_every_row(self):
        labels = [i % 2 for i in range(100)]
        scores = [i / 100 for i in range(100)]
        bins = calibration(labels, scores, bins=10)
        self.assertEqual(sum(b.count for b in bins), 100)

    def test_empty_input(self):
        self.assertEqual(calibration([], []), [])


if __name__ == "__main__":
    unittest.main()


class TestTiesDoNotFlatterTheMetrics(unittest.TestCase):
    """Regression tests for a defect found while building WS-1.1 Step 5.

    Both functions sorted ``(score, label)`` tuples, which lets the *outcome*
    order rows whenever scores tie. Every negative of a tie group then walked past
    every positive, and the metric reported what a strict ordering would have
    given. It flatters exactly the models most likely to tie — shallow trees, and
    anything predicting a constant.
    """

    def test_a_constant_score_has_no_separation(self):
        labels = [1] * 100 + [0] * 100
        self.assertAlmostEqual(metrics.ks(labels, [0.5] * 200), 0.0)

    def test_a_constant_score_gives_one_calibration_bin(self):
        labels = [1] * 100 + [0] * 100
        table = metrics.calibration(labels, [0.5] * 200, bins=10)
        self.assertEqual(len(table), 1)
        self.assertAlmostEqual(table[0].observed, 0.5)

    def test_ks_matches_auc_ordering_on_a_tied_model(self):
        # Two leaf values, half the population in each. KS is bounded by the real
        # separation between the two groups, not by the row order inside them.
        labels = [1] * 30 + [0] * 70 + [1] * 10 + [0] * 90
        scores = [0.6] * 100 + [0.2] * 100
        self.assertAlmostEqual(metrics.ks(labels, scores), abs(30 / 40 - 70 / 160))

    def test_untied_scores_are_unaffected(self):
        labels = [0, 0, 1, 1]
        scores = [0.1, 0.2, 0.3, 0.4]
        self.assertAlmostEqual(metrics.ks(labels, scores), 1.0)

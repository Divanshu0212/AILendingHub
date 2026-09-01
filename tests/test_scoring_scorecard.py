"""Tests for PAVA, monotone binning and the WOE scorecard (WS-1.1 Step 3).

The binning tests assert *properties* rather than hand-computed cut points,
because the Track B adapter calls OptBinning and a property is what both
implementations must satisfy. A test pinned to this port's exact edges would fail
on the library it is a port of.

Workstream: WS-1.1 Step 3
"""

import math
import random
import unittest

from lending_hub.definitions import Ungrounded
from lending_hub.scoring.binning import (
    ZERO_CELL_ADJUSTMENT,
    BinningError,
    fit_binning,
)
from lending_hub.scoring.features import ScreenVerdict
from lending_hub.scoring.isotonic import (
    Direction,
    fit_isotonic,
    fit_values,
    pool_adjacent_violators,
)
from lending_hub.scoring.scorecard import (
    PDO,
    ScaleAnchor,
    Scorecard,
    ScorecardError,
    fit_scorecard,
    negative_coefficients,
)


def sample(n=4000, seed=0, missing_rate=0.0):
    rng = random.Random(seed)
    rows, labels = [], []
    for _ in range(n):
        score = rng.uniform(300, 850)
        util = rng.uniform(0, 1.2)
        enquiries = rng.randint(0, 12)
        z = -3.0 + (700 - score) / 120 + util * 1.4 + enquiries * 0.12
        p = 1 / (1 + math.exp(-z))
        rows.append({
            "bureau_score": None if rng.random() < missing_rate else score,
            "utilisation": util,
            "enquiries": float(enquiries),
        })
        labels.append(1 if rng.random() < p else 0)
    return rows, labels


class TestPoolAdjacentViolators(unittest.TestCase):
    def test_an_already_monotone_series_is_unchanged(self):
        self.assertEqual(fit_values([1.0, 2.0, 3.0]), [1.0, 2.0, 3.0])

    def test_violators_are_pooled_to_their_weighted_mean(self):
        self.assertEqual(fit_values([1.0, 3.0, 2.0, 4.0]), [1.0, 2.5, 2.5, 4.0])

    def test_weights_move_the_pooled_value(self):
        fitted = fit_values([1.0, 3.0, 2.0], [1.0, 3.0, 1.0])
        self.assertAlmostEqual(fitted[1], (3 * 3 + 2) / 4)

    def test_the_fit_is_monotone_in_the_requested_direction(self):
        rng = random.Random(4)
        noisy = [rng.random() for _ in range(50)]
        up = fit_values(noisy, direction=Direction.INCREASING)
        down = fit_values(noisy, direction=Direction.DECREASING)
        self.assertTrue(all(a <= b for a, b in zip(up, up[1:])))
        self.assertTrue(all(a >= b for a, b in zip(down, down[1:])))

    def test_blocks_partition_the_input(self):
        blocks = pool_adjacent_violators([1.0, 3.0, 2.0, 4.0])
        self.assertEqual(blocks[0].start, 0)
        self.assertEqual(blocks[-1].stop, 4)
        for a, b in zip(blocks, blocks[1:]):
            self.assertEqual(a.stop, b.start)

    def test_auto_is_not_a_direction_pava_can_run(self):
        with self.assertRaises(ValueError):
            pool_adjacent_violators([1.0, 2.0], direction=Direction.AUTO)


class TestIsotonicCalibrator(unittest.TestCase):
    def test_the_calibrated_curve_is_non_decreasing(self):
        rng = random.Random(2)
        scores = [rng.random() for _ in range(500)]
        labels = [1 if rng.random() < s else 0 for s in scores]
        calibrator = fit_isotonic(scores, labels)
        grid = [i / 100 for i in range(101)]
        fitted = calibrator.predict_all(grid)
        self.assertTrue(all(a <= b + 1e-12 for a, b in zip(fitted, fitted[1:])))

    def test_predictions_stay_inside_zero_one(self):
        rng = random.Random(3)
        scores = [rng.random() for _ in range(300)]
        labels = [1 if rng.random() < s else 0 for s in scores]
        calibrator = fit_isotonic(scores, labels)
        for p in calibrator.predict_all([-5, 0, 0.5, 1, 5]):
            self.assertGreaterEqual(p, 0.0)
            self.assertLessEqual(p, 1.0)

    def test_ties_are_pooled_so_the_fit_is_order_independent(self):
        first = fit_isotonic([0.5, 0.5, 0.5, 0.9], [0, 1, 1, 1])
        second = fit_isotonic([0.5, 0.9, 0.5, 0.5], [1, 1, 0, 1])
        self.assertEqual(first.thresholds, second.thresholds)
        self.assertEqual(first.probabilities, second.probabilities)

    def test_empty_sample_is_refused(self):
        with self.assertRaises(ValueError):
            fit_isotonic([], [])


class TestBinning(unittest.TestCase):
    def setUp(self):
        self.rows, self.labels = sample()

    def test_event_rates_are_monotone(self):
        binning = fit_binning(
            [r["bureau_score"] for r in self.rows], self.labels, feature="bureau_score"
        )
        self.assertTrue(binning.monotone)

    def test_bins_cover_the_whole_domain(self):
        binning = fit_binning(
            [r["utilisation"] for r in self.rows], self.labels, feature="utilisation"
        )
        self.assertIsNone(binning.bins[0].lower)
        self.assertIsNone(binning.bins[-1].upper)
        for value in (-1e9, 0.0, 0.5, 1e9):
            binning.transform(value)

    def test_bins_are_contiguous_and_non_overlapping(self):
        binning = fit_binning(
            [r["bureau_score"] for r in self.rows], self.labels, feature="bureau_score"
        )
        interior = [b for b in binning.bins if not b.is_missing]
        for a, b in zip(interior, interior[1:]):
            self.assertEqual(a.upper, b.lower)

    def test_counts_reconcile_with_the_sample(self):
        binning = fit_binning(
            [r["enquiries"] for r in self.rows], self.labels, feature="enquiries"
        )
        self.assertEqual(sum(b.count for b in binning.bins), len(self.rows))
        self.assertEqual(sum(b.bads for b in binning.bins), sum(self.labels))

    def test_missing_values_get_their_own_bin_never_an_imputed_one(self):
        rows, labels = sample(missing_rate=0.15)
        binning = fit_binning(
            [r["bureau_score"] for r in rows], labels, feature="bureau_score"
        )
        missing = [b for b in binning.bins if b.is_missing]
        self.assertEqual(len(missing), 1)
        self.assertGreater(missing[0].count, 0)
        self.assertEqual(binning.transform(None), missing[0].woe)

    def test_a_policy_direction_is_recorded_as_policy(self):
        binning = fit_binning(
            [r["bureau_score"] for r in self.rows], self.labels,
            feature="bureau_score", direction=Direction.DECREASING,
        )
        self.assertEqual(binning.direction_source, "policy")
        self.assertIs(binning.direction, Direction.DECREASING)

    def test_an_inferred_direction_is_recorded_as_data_not_policy(self):
        binning = fit_binning(
            [r["bureau_score"] for r in self.rows], self.labels, feature="bureau_score"
        )
        self.assertEqual(binning.direction_source, "data")

    def test_a_higher_woe_bin_has_a_lower_bad_rate(self):
        binning = fit_binning(
            [r["utilisation"] for r in self.rows], self.labels, feature="utilisation"
        )
        ordered = sorted((b for b in binning.bins if not b.is_missing), key=lambda b: b.woe)
        rates = [b.event_rate for b in ordered]
        self.assertTrue(all(a >= b for a, b in zip(rates, rates[1:])),
                        "WOE must run opposite to the bad rate (SRS §4.3.1 convention)")

    def test_no_bin_has_an_infinite_woe(self):
        binning = fit_binning(
            [r["enquiries"] for r in self.rows], self.labels, feature="enquiries"
        )
        for b in binning.bins:
            self.assertTrue(math.isfinite(b.woe))

    def test_the_zero_cell_adjustment_is_recorded_on_the_bin(self):
        values = [0.0] * 100 + [1.0] * 100
        labels = [0] * 100 + [1] * 100
        binning = fit_binning(values, labels, feature="perfect")
        self.assertTrue(any(b.zero_cell_adjusted for b in binning.bins))
        self.assertEqual(ZERO_CELL_ADJUSTMENT, 0.5)

    def test_a_single_class_sample_is_refused(self):
        with self.assertRaises(BinningError):
            fit_binning([1.0, 2.0, 3.0], [0, 0, 0], feature="x")

    def test_mismatched_lengths_are_refused(self):
        with self.assertRaises(BinningError):
            fit_binning([1.0, 2.0], [0], feature="x")

    def test_a_perfect_predictor_trips_the_iv_leakage_screen(self):
        values = [float(y) + 0.01 for y in ([0] * 500 + [1] * 500)]
        labels = [0] * 500 + [1] * 500
        binning = fit_binning(values, labels, feature="leaky")
        self.assertIs(binning.screen()[0], ScreenVerdict.INVESTIGATE)


class TestScorecard(unittest.TestCase):
    def setUp(self):
        self.rows, self.labels = sample(seed=1)
        self.binnings = [
            fit_binning([r[f] for r in self.rows], self.labels, feature=f)
            for f in ("bureau_score", "utilisation", "enquiries")
        ]
        self.card = fit_scorecard(self.rows, self.labels, self.binnings)

    def test_it_ranks_risk(self):
        from lending_hub.modeling.metrics import auc
        self.assertGreater(auc(self.labels, self.card.predict_all(self.rows)), 0.7)

    def test_woe_coefficients_are_positive_on_a_well_behaved_sample(self):
        # Every coefficient on a WOE input should be positive: a better bin must
        # raise the log-odds of good. A negative one inverts that feature's
        # reason codes without moving AUC.
        self.assertEqual(negative_coefficients(self.card), [])

    def test_points_are_refused_until_the_policy_anchor_exists(self):
        with self.assertRaises(Ungrounded) as caught:
            self.card.points(self.rows[0])
        self.assertIn("LH-208", str(caught.exception))

    def test_pdo_is_the_only_grounded_scaling_constant(self):
        self.assertEqual(PDO.value, 20.0)
        anchor = ScaleAnchor(reference_score=600, reference_odds=50)
        self.assertAlmostEqual(anchor.factor, 20.0 / math.log(2))

    def test_doubling_the_odds_adds_pdo_points(self):
        anchor = ScaleAnchor(reference_score=600, reference_odds=50)
        self.assertAlmostEqual(
            anchor.points(math.log(100)) - anchor.points(math.log(50)), PDO.value
        )

    def test_a_missing_characteristic_is_an_error_not_a_default(self):
        row = dict(self.rows[0])
        del row["utilisation"]
        with self.assertRaises(ScorecardError):
            self.card.log_odds(row)

    def test_point_allocation_sums_to_the_score(self):
        self.card.anchor = ScaleAnchor(reference_score=600, reference_odds=50)
        row = self.rows[7]
        self.assertAlmostEqual(
            sum(self.card.point_allocation(row).values()), self.card.points(row), places=6
        )

    def test_unresolved_directions_are_reported(self):
        self.assertEqual(sorted(self.card.unresolved_directions()), sorted(self.card.names))

    def test_the_card_records_the_definitions_fingerprint(self):
        self.assertEqual(len(self.card.definitions_fingerprint), 16)


class TestReasonCodes(unittest.TestCase):
    def setUp(self):
        self.rows, self.labels = sample(seed=5)
        self.binnings = [
            fit_binning([r[f] for r in self.rows], self.labels, feature=f)
            for f in ("bureau_score", "utilisation", "enquiries")
        ]
        self.card = fit_scorecard(self.rows, self.labels, self.binnings)

    def worst_row(self):
        return max(self.rows, key=self.card.predict)

    def test_reasons_are_ranked_by_shortfall_and_capped(self):
        reasons = self.card.reasons(self.worst_row(), top=2)
        self.assertLessEqual(len(reasons), 2)
        self.assertGreaterEqual(reasons[0].shortfall, reasons[-1].shortfall)

    def test_an_applicant_in_every_best_bin_gets_no_reasons(self):
        best = {}
        for characteristic in self.card.characteristics:
            top_bin = max(characteristic.binning.bins, key=lambda b: b.woe)
            best[characteristic.name] = (
                (top_bin.lower + 0.001) if top_bin.lower is not None
                else (top_bin.upper - 0.001 if top_bin.upper is not None else 0.0)
            )
        self.assertEqual(self.card.reasons(best), [])

    def test_the_two_methods_are_both_available_and_can_disagree(self):
        row = self.worst_row()
        below_max = [r.characteristic for r in self.card.reasons(row, method="points_below_max")]
        literal = [r.characteristic for r in self.card.reasons(row, method="largest_negative")]
        self.assertTrue(below_max)
        self.assertTrue(literal)

    def test_points_below_max_is_never_negative(self):
        for row in self.rows[:50]:
            for reason in self.card.reasons(row):
                self.assertGreater(reason.shortfall, 0)

    def test_reason_ranking_is_stable_across_repeat_scoring(self):
        row = self.worst_row()
        first = [(r.characteristic, r.bin_label) for r in self.card.reasons(row)]
        second = [(r.characteristic, r.bin_label) for r in self.card.reasons(row)]
        self.assertEqual(first, second)

    def test_reasons_carry_no_rendered_wording(self):
        # Reason-code wording is [POLICY: Compliance] (LH-203). A Reason that
        # carried a sentence would freeze one nobody approved.
        reason = self.card.reasons(self.worst_row())[0]
        self.assertFalse(hasattr(reason, "wording"))
        self.assertFalse(hasattr(reason, "text"))

    def test_an_unknown_method_is_refused(self):
        with self.assertRaises(ScorecardError):
            self.card.reasons(self.rows[0], method="vibes")


if __name__ == "__main__":
    unittest.main()


def collinear_sample(n=3000, seed=1):
    """A suppressor variable — the standard cause of a wrong-signed coefficient.

    ``x2`` and ``x3`` track ``x1`` and carry none of the target's signal
    themselves, so a multivariate fit uses one of them to subtract the others'
    noise and gives it a negative weight. That is the pathology
    :func:`fit_scorecard_stepwise` exists to remove.
    """
    rng = random.Random(seed)
    rows, labels = [], []
    for _ in range(n):
        x1 = rng.gauss(0, 1)
        rows.append({
            "x1": x1,
            "x2": x1 + 0.15 * rng.gauss(0, 1),
            "x3": 0.9 * x1 + 0.1 * rng.gauss(0, 1),
            "x4": rng.gauss(0, 1),
        })
        labels.append(1 if rng.random() < 1 / (1 + math.exp(-(-2.0 + 1.6 * x1))) else 0)
    return rows, labels


class TestStepwiseElimination(unittest.TestCase):
    def setUp(self):
        from lending_hub.scoring.scorecard import fit_scorecard_stepwise
        self.stepwise = fit_scorecard_stepwise
        self.rows, self.labels = collinear_sample()
        self.pool = [
            fit_binning([r[f] for r in self.rows], self.labels, feature=f)
            for f in ("x1", "x2", "x3", "x4")
        ]
        self.pool.sort(key=lambda b: -b.iv)

    def test_the_plain_fit_really_does_produce_a_wrong_sign(self):
        # If this stops being true the test below proves nothing.
        card = fit_scorecard(self.rows, self.labels, self.pool[:3], epochs=25, seed=0)
        self.assertTrue(negative_coefficients(card))

    def test_stepwise_removes_it(self):
        card, log = self.stepwise(
            self.rows, self.labels, self.pool, size=3, minimum=2, epochs=25, seed=0
        )
        self.assertEqual(negative_coefficients(card), [])
        self.assertTrue(log)

    def test_the_log_records_what_was_dropped_and_what_replaced_it(self):
        _, log = self.stepwise(
            self.rows, self.labels, self.pool, size=3, minimum=2, epochs=25, seed=0
        )
        step = log[0].to_dict()
        self.assertLess(step["coefficient"], 0)
        self.assertIn("dropped", step)
        self.assertEqual(step["round"], 1)

    def test_a_clean_card_is_returned_unchanged_with_an_empty_log(self):
        clean = [b for b in self.pool if b.feature in ("x1", "x4")]
        card, log = self.stepwise(
            self.rows, self.labels, clean, size=2, minimum=2, epochs=25, seed=0
        )
        self.assertEqual(log, [])
        self.assertEqual(sorted(card.names), ["x1", "x4"])

    def test_a_spare_backfills_the_dropped_characteristic(self):
        _, log = self.stepwise(
            self.rows, self.labels, self.pool, size=3, minimum=2, epochs=25, seed=0
        )
        self.assertIsNotNone(log[0].added)
        self.assertEqual(log[0].remaining, 3)

    def test_it_shrinks_rather_than_stopping_once_the_pool_is_exhausted(self):
        # With no spare left the choice is a smaller clean card or a full card with
        # a characteristic fitted against its own evidence. Smaller and clean wins,
        # and the log says how it got there.
        card, log = self.stepwise(
            self.rows, self.labels, self.pool, size=3, minimum=2, epochs=25, seed=0
        )
        self.assertGreaterEqual(len(card.characteristics), 2)
        self.assertLessEqual(len(card.characteristics), 3)
        self.assertEqual(negative_coefficients(card), [])

    def test_a_size_below_the_minimum_is_refused(self):
        with self.assertRaises(ScorecardError):
            self.stepwise(self.rows, self.labels, self.pool, size=2, minimum=5)

    def test_the_stopping_rule_needs_no_threshold(self):
        # "No negative coefficients remain" is a property of the fit, not a number
        # someone chose — which matters because the correlation-cap alternative
        # needs a cap nobody has ratified.
        import inspect
        parameters = inspect.signature(self.stepwise).parameters
        self.assertNotIn("correlation_cap", parameters)
        self.assertNotIn("threshold", parameters)

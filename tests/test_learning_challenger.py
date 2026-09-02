"""The champion/challenger comparison contract — Phase 6 §2, §4.

Every Phase 6 promotion gate is comparative, and the ways a comparison goes
wrong are quiet: each of the four mismatches below produces a *positive* lift
that survives review, because a reviewer sees two numbers and a subtraction.

These tests pin that each is refused rather than adjusted. There is no
realignment step to test — a comparison whose windows differ cannot be repaired
by code, only re-run.
"""

from __future__ import annotations

import unittest
from datetime import datetime

from lending_hub.learning.challenger import ChallengerEntry, ComparisonError, assess, compare
from lending_hub.learning.promotion import EvaluationWindow

TRAIN_END = datetime(2026, 1, 1)
WINDOW = EvaluationWindow(
    train_end=TRAIN_END, eval_start=TRAIN_END, eval_end=datetime(2026, 6, 1)
)
LATER = EvaluationWindow(
    train_end=TRAIN_END,
    eval_start=datetime(2026, 3, 1),
    eval_end=datetime(2026, 9, 1),
)
IN_TIME = EvaluationWindow(
    train_end=TRAIN_END,
    eval_start=datetime(2025, 6, 1),
    eval_end=datetime(2026, 6, 1),
)


def _entry(**overrides) -> ChallengerEntry:
    defaults = dict(
        model_name="p3-gbm-champion",
        metric="c_index",
        value=0.71,
        window=WINDOW,
        population="retail unsecured, 2024 vintages",
        threshold=None,
        explainability_reviewed=True,
    )
    defaults.update(overrides)
    return ChallengerEntry(**defaults)


class HeldFixed(unittest.TestCase):
    def test_a_matching_pair_produces_a_lift(self):
        lift = compare(_entry(), _entry(model_name="deepsurv", value=0.74))
        self.assertAlmostEqual(lift.lift, 0.03, places=12)

    def test_a_different_metric_is_refused(self):
        with self.assertRaises(ComparisonError) as caught:
            compare(_entry(), _entry(model_name="x", metric="auc", value=0.9))
        self.assertIn("metric mismatch", str(caught.exception))

    def test_a_different_population_is_refused(self):
        """A broader or easier segment inflates the challenger."""
        with self.assertRaises(ComparisonError) as caught:
            compare(_entry(), _entry(model_name="x", population="all products"))
        self.assertIn("population mismatch", str(caught.exception))

    def test_a_later_window_is_refused(self):
        """It measures how the book changed, not how the model did."""
        with self.assertRaises(ComparisonError) as caught:
            compare(_entry(), _entry(model_name="x", window=LATER))
        self.assertIn("window mismatch", str(caught.exception))

    def test_a_different_operating_point_is_refused(self):
        with self.assertRaises(ComparisonError) as caught:
            compare(
                _entry(metric="recall", threshold=0.5),
                _entry(model_name="x", metric="recall", threshold=0.3),
            )
        self.assertIn("operating point", str(caught.exception))

    def test_an_unnamed_model_cannot_be_entered(self):
        with self.assertRaises(ComparisonError):
            _entry(model_name="  ")


class AssessAddsTheNonMetricConditions(unittest.TestCase):
    def test_a_good_challenger_may_proceed(self):
        verdict = assess(_entry(), _entry(model_name="deepsurv", value=0.74))
        self.assertTrue(verdict.may_proceed, verdict.blocking)

    def test_a_challenger_that_does_not_beat_the_champion_is_blocked(self):
        verdict = assess(_entry(), _entry(model_name="deepsurv", value=0.70))
        self.assertFalse(verdict.may_proceed)
        self.assertTrue(any("does not beat" in r for r in verdict.blocking))

    def test_a_tie_is_not_a_win(self):
        verdict = assess(_entry(), _entry(model_name="deepsurv", value=0.71))
        self.assertFalse(verdict.may_proceed)

    def test_an_in_time_window_is_blocked(self):
        verdict = assess(
            _entry(window=IN_TIME),
            _entry(model_name="deepsurv", value=0.74, window=IN_TIME),
        )
        self.assertFalse(verdict.may_proceed)
        self.assertTrue(any("out-of-time" in r for r in verdict.blocking))

    def test_an_unexplained_model_is_blocked_at_any_lift(self):
        """WS-6.3 extends P4's two-key rule to sequence models and WS-6.1
        requires every graph alert to ship with its subgraph. An unexplained
        alert is not actioned, so lift is irrelevant.
        """
        verdict = assess(
            _entry(),
            _entry(model_name="et-rnn", value=0.95, explainability_reviewed=False),
        )
        self.assertFalse(verdict.may_proceed)
        self.assertTrue(any("explainability" in r for r in verdict.blocking))

    def test_every_blocking_reason_is_returned_at_once(self):
        verdict = assess(
            _entry(window=IN_TIME),
            _entry(
                model_name="et-rnn",
                value=0.60,
                window=IN_TIME,
                explainability_reviewed=False,
            ),
        )
        self.assertEqual(len(verdict.blocking), 3)


class NoMinimumLiftIsDefaulted(unittest.TestCase):
    def test_a_hair_above_zero_passes_the_sign_test(self):
        """Deliberate. §4 says "measured lift", each workstream names its own
        gate, and none is quantified — LH-801. A minimum defaulted here would
        become the number every challenger in the programme was judged against.
        """
        verdict = assess(_entry(), _entry(model_name="x", value=0.7100001))
        self.assertTrue(verdict.may_proceed)


if __name__ == "__main__":
    unittest.main()

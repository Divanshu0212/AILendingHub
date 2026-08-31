"""Tests for reject inference (WS-1.1 Step 8).

The boundary these pin: parcelled rejects are a sensitivity analysis and can
never become training labels. Phase 1 §4 Step 8 forbids fabricated reject
outcomes in the same paragraph that schedules parcelling, and the reconciliation
this module implements has to be enforced rather than remembered.

Workstream: WS-1.1 Step 8
"""

import random
import unittest
from datetime import date

from lending_hub.definitions import Label
from lending_hub.scoring.rejects import (
    BUREAU_RETRO_AVAILABILITY,
    Method,
    Parcelled,
    RejectInferenceError,
    assert_not_in_target,
    memo_when_unavailable,
    parcel,
    selection_gap,
)
from lending_hub.scoring.target import TargetRow


def target_row(app_id="a"):
    return TargetRow(
        application_id=app_id,
        decided_at=date(2020, 1, 1),
        vintage="2020Q1",
        label=Label.GOOD,
        trainable=True,
    )


class TestSelectionGap(unittest.TestCase):
    def test_identical_populations_have_near_zero_psi(self):
        rng = random.Random(0)
        scores = [rng.gauss(0.1, 0.03) for _ in range(4000)]
        gap = selection_gap(scores[:2000], scores[2000:])
        self.assertLess(gap.score_psi, 0.1)

    def test_a_shifted_reject_population_shows_a_large_psi(self):
        rng = random.Random(1)
        accepted = [rng.gauss(0.05, 0.02) for _ in range(3000)]
        rejected = [rng.gauss(0.25, 0.06) for _ in range(1500)]
        gap = selection_gap(accepted, rejected)
        self.assertGreater(gap.score_psi, 0.25)
        self.assertAlmostEqual(gap.reject_rate, 1500 / 4500)

    def test_it_needs_no_reject_outcomes(self):
        # The point of this measurement: it quantifies the bias without assuming
        # anything about how rejects would have performed.
        import inspect
        parameters = inspect.signature(selection_gap).parameters
        self.assertEqual(sorted(parameters)[:2], ["accepted_scores", "bins"])
        self.assertNotIn("reject_labels", parameters)

    def test_an_empty_side_yields_no_psi_rather_than_zero(self):
        gap = selection_gap([0.1, 0.2], [])
        self.assertIsNone(gap.score_psi)
        self.assertEqual(gap.n_rejected, 0)


class TestParcellingCannotBecomeTruth(unittest.TestCase):
    def test_parcelling_splits_each_reject_between_outcomes(self):
        parcelled = parcel(["a", "b"], [0.3, 0.7])
        self.assertAlmostEqual(parcelled[0].weight_bad, 0.3)
        self.assertAlmostEqual(parcelled[0].weight_good, 0.7)
        self.assertAlmostEqual(
            parcelled[1].weight_bad + parcelled[1].weight_good, 1.0
        )

    def test_a_parcelled_row_is_not_a_target_row(self):
        self.assertNotIsInstance(parcel(["a"], [0.5])[0], TargetRow)

    def test_parcelled_rejects_in_a_training_population_are_refused(self):
        with self.assertRaises(RejectInferenceError) as caught:
            assert_not_in_target([target_row(), *parcel(["r1"], [0.4])])
        self.assertIn("fabricated", str(caught.exception))

    def test_a_clean_training_population_passes(self):
        assert_not_in_target([target_row("a"), target_row("b")])

    def test_anything_that_is_not_a_target_row_is_refused(self):
        with self.assertRaises(RejectInferenceError):
            assert_not_in_target([{"application_id": "a", "label": 1}])

    def test_an_out_of_range_prediction_is_refused(self):
        with self.assertRaises(RejectInferenceError):
            Parcelled(application_id="a", predicted_pd=1.4, weight_bad=1.0, weight_good=0.0)

    def test_mismatched_lengths_are_refused(self):
        with self.assertRaises(RejectInferenceError):
            parcel(["a", "b"], [0.5])


class TestMemo(unittest.TestCase):
    def test_the_unavailable_memo_states_the_selection_bias_limitation(self):
        memo = memo_when_unavailable(
            "application_pd",
            reason="no declined applications exist in Track P (ADR-0010)",
        )
        self.assertIs(memo.method, Method.NONE)
        self.assertFalse(memo.exercisable)
        self.assertEqual(len(memo.limitations), 3)
        self.assertTrue(
            any("through-the-door" in line for line in memo.limitations)
        )

    def test_the_memo_records_that_no_reject_outcome_was_assigned(self):
        memo = memo_when_unavailable("m", reason="r")
        self.assertTrue(
            any("No outcome has been assigned" in line for line in memo.limitations)
        )

    def test_the_memo_carries_the_bureau_retro_placeholder(self):
        payload = memo_when_unavailable("m", reason="r").to_dict()
        self.assertIn("LH-207", payload["bureau_retro_availability"])

    def test_the_swap_set_caveat_is_stated(self):
        # Both models were fitted on the same accepted population, so their
        # agreement is not independent evidence.
        memo = memo_when_unavailable("m", reason="r")
        self.assertTrue(any("Swap-set" in line for line in memo.limitations))

    def test_the_availability_placeholder_names_its_owner(self):
        self.assertEqual(BUREAU_RETRO_AVAILABILITY.ticket, "LH-207")


if __name__ == "__main__":
    unittest.main()

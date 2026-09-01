"""Tests for the Phase 1 gate evidence pack (Phase 1 §7, Master §3.1).

A gate report is read once a quarter by people who did not build the thing. The
tests that matter are the ones about what it refuses to claim.

Workstream: WS-1 (Master §3.1)
"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

import phase1_gate_report as gate  # noqa: E402


class TestWithNoRun(unittest.TestCase):
    def setUp(self):
        self.lines = gate.build(None)
        self.text = "\n".join(self.lines)

    def test_every_exit_criterion_appears(self):
        for label, _ in gate.CRITERIA:
            self.assertIn(label, self.text)

    def test_unmeasured_criteria_say_so_rather_than_being_omitted(self):
        # An omission reads as an oversight; a stated blocker reads as a blocker.
        self.assertEqual(self.text.count("**not measured**"), len(gate.CRITERIA))

    def test_it_never_claims_track_b_evidence(self):
        self.assertIn(f"Track B evidence: 0 of {len(gate.CRITERIA)}", self.text)
        self.assertIn("not exitable", self.text)

    def test_the_fraud_criteria_are_called_unevaluable_not_unmeasured(self):
        self.assertIn("not evaluable at all", self.text)
        self.assertIn("LH-101", self.text)


class TestWithATrackPRun(unittest.TestCase):
    def run_payload(self):
        return {
            "run": {"dataset": "home_credit_default_risk", "seed": 1, "seconds": 1.0},
            "validation": {
                "champion": {
                    "test": {"gini_points": 44.45}, "brier": 0.06996,
                    "ece": 0.009, "score_psi": 0.0005,
                    "exit_criteria": {
                        "champion_gini_uplift": {
                            "measured": None, "evaluated": False, "met": None,
                            "note": "no rebuilt legacy scorecard supplied",
                        },
                    },
                },
                "challenger": {
                    "test": {"gini_points": 47.73}, "brier": 0.06954,
                    "ece": 0.008, "score_psi": 0.0013,
                    "exit_criteria": {
                        "challenger_gini_uplift": {
                            "measured": 3.28, "evaluated": False, "met": None,
                            "note": "measured on a test set that is NOT out of time",
                        },
                        "brier_no_worse_than_legacy": {
                            "measured": 0.06954, "legacy": 0.06996, "met": True,
                        },
                        "swap_set_no_adverse_concentration": {
                            "measured": {"20-29": 1.32, "40-49": 1.07}, "met": None,
                        },
                    },
                },
            },
        }

    def setUp(self):
        self.text = "\n".join(gate.build(self.run_payload()))

    def test_track_p_numbers_are_labelled_track_p(self):
        self.assertIn("not gate evidence", self.text)
        self.assertIn("| 2 | Challenger", self.text)
        self.assertIn("| 1 | Champion", self.text)

    def test_an_in_time_uplift_is_reported_as_not_evaluable(self):
        # The number exists and still cannot satisfy the criterion as written.
        self.assertIn("+3.28 pts", self.text)
        self.assertIn("NOT out of time", self.text)

    def test_the_swap_set_criterion_reports_the_worst_segment_and_no_bar(self):
        self.assertIn("20-29 at 1.32x", self.text)
        self.assertIn("no bar (LH-205)", self.text)

    def test_a_passing_brier_is_reported_as_passing(self):
        self.assertIn("pass (Track P)", self.text)


class TestModelCards(unittest.TestCase):
    def test_the_shipped_cards_are_detected_and_reported_unsigned(self):
        cards = gate._model_cards()
        self.assertEqual(len(cards), 2)
        for name, signed in cards:
            self.assertFalse(signed, f"{name} should be unsigned on Track P")

    def test_the_report_says_an_unsigned_card_is_not_complete(self):
        text = "\n".join(gate.build(None))
        self.assertIn("An unsigned card is not a completed card", text)


class TestOpenTickets(unittest.TestCase):
    def test_open_phase_1_tickets_are_listed_with_their_owners(self):
        tickets = dict(gate._open_tickets())
        self.assertIn("LH-202", tickets)
        self.assertEqual(tickets["LH-205"], "Fair-Lending Committee")

    def test_phase_0_tickets_that_also_block_phase_1_are_named(self):
        text = "\n".join(gate.build(None))
        for ticket in ("LH-101", "LH-103", "LH-120"):
            self.assertIn(ticket, text)


if __name__ == "__main__":
    unittest.main()

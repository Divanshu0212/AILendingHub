"""The Phase 4 gate pack — tools/phase4_gate_report.py.

Phase 4 is the first phase whose pack uses all three columns: Track P evidence
for detection, not-measurable for action, and one criterion provable on Track A.
These tests pin that shape, and that nothing in the pack is simulated.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import phase4_gate_report as pack  # noqa: E402


def _run(capture=0.62, median_lead=120):
    return {
        "track": "P",
        "panel": {"loans_sampled": 5081, "account_months": 338210},
        "observed_defaults": 827,
        "capture_sweep": {
            "p90": {
                "threshold_percentile": 0.90,
                "alerts_raised": 12000,
                "accounts_alerted": 3000,
                "capture_rate": capture,
                "captured": 500,
                "captured_too_late": 100,
                "never_alerted": 227,
                "median_lead_days": median_lead,
                "lead_percentiles": {"p10": 65, "p50": median_lead, "p90": 400},
                "meets_target": capture >= 0.55,
                "why_not": "",
            },
            "p99": {
                "threshold_percentile": 0.99,
                "alerts_raised": 1200,
                "accounts_alerted": 400,
                "capture_rate": 0.18,
                "captured": 149,
                "captured_too_late": 40,
                "never_alerted": 638,
                "median_lead_days": 200,
                "lead_percentiles": {"p10": 90, "p50": 200, "p90": 500},
                "meets_target": False,
                "why_not": "capture 0.180 is below the 0.55 target",
            },
        },
    }


class TestCriteria(unittest.TestCase):
    def test_all_five_phase_four_exit_criteria_are_present(self):
        self.assertEqual(len(pack.CRITERIA), 5)

    def test_every_criterion_names_a_workstream(self):
        for name, workstream in pack.CRITERIA:
            self.assertTrue(workstream, f"{name} names no workstream")

    def test_three_criteria_are_structurally_not_measurable(self):
        self.assertEqual(len(pack.NOT_MEASURABLE), 3)

    def test_every_not_measurable_reason_cites_a_ticket_or_a_structural_fact(self):
        for name, reason in pack.NOT_MEASURABLE.items():
            self.assertTrue("LH-" in reason, f"{name}: {reason}")


class TestThreeColumns(unittest.TestCase):
    """The shape that makes this pack different from P1, P2 and P3's."""

    def test_the_ews_criterion_reports_track_p_evidence(self):
        track, measured, state = pack._criterion_state(
            "EWS backtest + silent-run meet targets", _run()
        )
        self.assertEqual(track, "P")
        self.assertIn("capture 0.620", measured)
        self.assertIn("median lead 120d", measured)

    def test_the_ews_criterion_still_reports_precision_as_unmeasurable(self):
        """Capture is measured; precision is not, and the row says both."""
        _, _, state = pack._criterion_state(
            "EWS backtest + silent-run meet targets", _run()
        )
        self.assertIn("not measurable", state)
        self.assertIn("LH-510", state)
        self.assertIn("not a substitute", state)

    def test_propensity_completeness_is_provable_on_track_a(self):
        track, measured, state = pack._criterion_state(
            "Propensity logging completeness = 100%", None
        )
        self.assertEqual(track, "A")
        self.assertIn("100%", measured)
        self.assertIn("provable on Track A", state)

    def test_propensity_is_still_not_gate_evidence(self):
        """Provable is not the same as passed."""
        _, _, state = pack._criterion_state(
            "Propensity logging completeness = 100%", None
        )
        self.assertIn("not gate evidence", state)

    def test_action_criteria_are_not_measurable(self):
        for name in pack.NOT_MEASURABLE:
            track, measured, state = pack._criterion_state(name, _run())
            self.assertEqual(track, "—")
            self.assertIn("not measurable", state)

    def test_the_ews_criterion_without_a_run_is_not_measured(self):
        """Not measured and not measurable are different columns."""
        _, _, state = pack._criterion_state(
            "EWS backtest + silent-run meet targets", None
        )
        self.assertIn("not measured", state)
        self.assertNotIn("not measurable", state)


class TestBestBand(unittest.TestCase):
    def test_the_highest_capture_band_is_selected(self):
        name, payload = pack._best_band(_run())
        self.assertEqual(name, "p90")
        self.assertAlmostEqual(payload["capture_rate"], 0.62, places=9)

    def test_a_run_with_no_rankable_snapshots_has_no_band(self):
        self.assertIsNone(pack._best_band({"capture_sweep": {"state": "not measurable"}}))

    def test_no_run_has_no_band(self):
        self.assertIsNone(pack._best_band(None))


class TestRenderedPack(unittest.TestCase):
    def test_states_that_nothing_is_simulated(self):
        text = "\n".join(pack.build(_run()))
        self.assertIn("Nothing here is simulated", text)
        self.assertIn("property of the", text)

    def test_explains_why_a_simulator_would_be_worse_than_absence(self):
        """The simulator would share the detector's theory of default."""
        text = "\n".join(pack.build(_run()))
        self.assertIn("same person as the detector", text)
        self.assertIn("P3-F14", text)

    def test_the_sweep_table_is_rendered(self):
        text = "\n".join(pack.build(_run()))
        self.assertIn("| p90 |", text)
        self.assertIn("| p99 |", text)
        self.assertIn("Collections Head needs", text)

    def test_without_a_run_it_says_so_rather_than_inventing_a_table(self):
        text = "\n".join(pack.build(None))
        self.assertIn("Not present", text)
        self.assertNotIn("| p90 |", text)

    def test_reports_zero_track_b_evidence(self):
        self.assertIn("Track B evidence: 0 of 5", "\n".join(pack.build(_run())))

    def test_names_the_findings_that_are_on_no_do_not_invent_list(self):
        text = "\n".join(pack.build(_run()))
        for ticket in ("LH-507", "LH-508", "LH-509", "LH-511", "LH-512", "LH-513"):
            self.assertIn(ticket, text)

    def test_singles_out_the_reward_finding(self):
        text = "\n".join(pack.build(_run()))
        self.assertIn("LH-509 is the one to read", text)
        self.assertIn("mis-selling engine", text)

    def test_the_gate_outcome_is_stated_honestly(self):
        text = "\n".join(pack.build(_run()))
        self.assertIn("**Fail.**", text)
        self.assertIn("refuse to make a decision it cannot log a propensity", text)


class TestTicketsAndCards(unittest.TestCase):
    def test_reads_the_phase_four_register(self):
        tickets = dict(pack._open_tickets())
        self.assertIn("LH-501", tickets)
        self.assertIn("LH-509", tickets)
        self.assertEqual(tickets["LH-501"], "Collections Head")

    def test_every_registered_phase_four_ticket_is_open(self):
        self.assertEqual(len(pack._open_tickets()), 13)

    def test_the_model_cards_exist(self):
        names = {name for name, _ in pack._model_cards()}
        self.assertIn("pd_velocity_ews.md", names)
        self.assertIn("linucb_offer_bandit.md", names)

    def test_no_card_is_signed(self):
        for name, signed in pack._model_cards():
            self.assertFalse(signed, f"{name} claims a signature")


class TestEntryPoint(unittest.TestCase):
    def test_writes_a_pack_and_exits_zero(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "phase4_gate.md"
            self.assertEqual(pack.main([f"--output={out}"]), 0)
            self.assertIn("Phase 4 — gate evidence pack", out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

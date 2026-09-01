"""The Phase 2 gate pack — tools/phase2_gate_report.py.

The pack's job is unusual: it has no numbers to report and must say so in a way
that does not read as an oversight. These tests pin that — every criterion is
present, every one is marked not measurable with a reason, and nothing in the
pack quotes a metric.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import phase2_gate_report as pack  # noqa: E402


class TestCriteria(unittest.TestCase):
    def test_all_six_phase_two_exit_criteria_are_present(self):
        self.assertEqual(len(pack.CRITERIA), 6)

    def test_every_criterion_carries_a_workstream_and_a_reason(self):
        for name, workstream, reason in pack.CRITERIA:
            self.assertTrue(name)
            self.assertTrue(workstream, f"{name} names no workstream")
            self.assertGreater(len(reason), 40, f"{name} has a thin reason")

    def test_every_reason_cites_a_ticket_or_a_structural_fact(self):
        """A blocker without a ticket is a blocker nobody chases."""
        for name, _, reason in pack.CRITERIA:
            has_ticket = "LH-" in reason
            structural = "rendering surface" in reason or "ADR-0013" in reason
            self.assertTrue(has_ticket or structural, f"{name}: {reason}")


class TestRenderedPack(unittest.TestCase):
    def setUp(self):
        self.text = "\n".join(pack.build())

    def test_states_all_six_are_not_measurable(self):
        self.assertIn("Not measurable: 6 of 6", self.text)
        self.assertIn("Track B evidence: 0 of 6", self.text)

    def test_every_criterion_row_says_not_measurable(self):
        self.assertEqual(self.text.count("**not measurable**"), 6)

    def test_says_plainly_that_there_is_no_track_p(self):
        """The single most important line for a reader of this pack."""
        self.assertIn("Phase 2 has no Track P", self.text)

    def test_explains_why_no_public_data_substitutes(self):
        self.assertIn("wrong agro-zone", self.text)

    def test_quotes_no_metrics(self):
        """A Measured column full of fixture numbers teaches the wrong lesson.

        Phase 1 and Phase 3 packs carry Track P figures because they have them.
        This one has none, and inventing a column would be worse than an empty
        one.
        """
        self.assertIn("quotes **no metrics**", self.text)

    def test_names_the_gate_outcome_honestly(self):
        self.assertIn("not presentable", self.text)
        self.assertIn("should not be taken to a Gate Review", self.text)

    def test_lists_the_deliverables_with_their_real_state(self):
        self.assertIn("Deliverables (Phase 2 §6)", self.text)
        self.assertEqual(len(pack.DELIVERABLES), 9)

    def test_distinguishes_blocked_from_track_b(self):
        """Different responses: chase a committee, or write an adapter."""
        self.assertIn("Track B", self.text)
        self.assertIn("blocked on data or policy", self.text)

    def test_reports_the_findings_that_are_on_no_do_not_invent_list(self):
        for ticket in ("LH-407", "LH-408", "LH-409", "LH-411", "LH-412"):
            self.assertIn(ticket, self.text)


class TestTicketsAndCards(unittest.TestCase):
    def test_reads_the_phase_two_register(self):
        tickets = dict(pack._open_tickets())
        self.assertIn("LH-401", tickets)
        self.assertIn("LH-412", tickets)
        self.assertEqual(tickets["LH-401"], "Agri Credit Head")

    def test_every_registered_phase_two_ticket_is_open(self):
        self.assertEqual(len(pack._open_tickets()), 13)

    def test_all_three_model_cards_exist(self):
        names = {name for name, _ in pack._model_cards()}
        self.assertEqual(
            names,
            {"boundary_delineation.md", "crop_classification.md", "yield_estimation.md"},
        )

    def test_no_card_is_signed(self):
        """Correctly so — there is no model to validate (Master §3.1)."""
        for name, signed in pack._model_cards():
            self.assertFalse(signed, f"{name} claims a signature")


class TestEntryPoint(unittest.TestCase):
    def test_writes_a_pack_and_exits_zero(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "phase2_gate.md"
            # main() resolves the output relative to the repo root, so pass an
            # absolute path through the same interface a caller would use.
            code = pack.main([f"--output={out}"])
            self.assertEqual(code, 0)
            self.assertTrue(out.exists())
            self.assertIn("Phase 2 — gate evidence pack", out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

"""The Phase 5 gate pack — tools/phase5_gate_report.py.

Phase 5 is the first phase whose central guarantee is structural rather than
measured, and the pack's main job is to communicate that without letting it read
as evidence. Phase 4 introduced one such column; Phase 5 has several, so the
risk of a structural guarantee being quoted as a measurement is larger.

These tests pin the shape: six criteria, none with Track B evidence, one
structurally guaranteed with its boundary stated, and no fabricated corpus,
triple, sentence or answer anywhere in the pack.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "src"))

import phase5_gate_report as pack  # noqa: E402


class PackShape(unittest.TestCase):
    def setUp(self):
        self.text = "\n".join(pack.build())

    def test_all_six_exit_criteria_appear(self):
        """Phase 5 §7 states six. A pack that dropped one would read as passing more."""
        self.assertEqual(len(pack.CRITERIA), 6)
        for name, _ in pack.CRITERIA:
            self.assertIn(name, self.text)

    def test_no_criterion_has_track_b_evidence(self):
        self.assertIn("**Track B evidence: 0 of 6.**", self.text)

    def test_five_criteria_are_not_measurable_and_each_names_its_ticket(self):
        """"Blocked" is not a reason. The five blockers are different kinds of
        thing, fixed by different people.

        A corpus needs SMEs, a model needs procurement, a containment target
        needs a product decision, and two need human sign-offs by functions that
        do not exist. Collapsing them loses the only actionable content.
        """
        self.assertEqual(len(pack.NOT_MEASURABLE), 5)
        for reason in pack.NOT_MEASURABLE.values():
            self.assertRegex(reason, r"LH-\d+", f"no ticket in: {reason[:60]!r}")

    def test_the_structural_criterion_states_its_boundary(self):
        """A guarantee quoted without its boundary is a guarantee misquoted.

        "Leak rate zero" is true of answers that went through validate(), and
        the pack has to say so in the same breath, or a reader takes it as a
        property of the deployed assistant.
        """
        self.assertIn("structurally guaranteed on Track A", self.text)
        self.assertIn("guards a code path, not a product", self.text)
        self.assertIn("citation, not truth", self.text)

    def test_the_structural_number_is_computed_not_typed(self):
        """The claim is produced by calling the code it describes.

        A stale measurement is obviously old; a stale guarantee reads as
        current, so it must fail here rather than persist in a document.
        """
        state = pack._structural_state()
        self.assertEqual(state["leak_audit"]["leak_rate"], 0.0)
        self.assertEqual(state["leak_audit"]["basis"], "structural")

    def test_the_pack_records_that_there_is_no_track_p_by_decision(self):
        """Not an unrun job. Public RAG benchmarks exist and test the wrong
        property, which is a different statement from "no data exists".

        ADR-0013 made the second claim for Phase 2 and had to be amended.
        """
        self.assertIn("no Track P", self.text)
        self.assertIn("decision rather", self.text)
        self.assertIn("ADR-0015", self.text)


class NothingIsFabricated(unittest.TestCase):
    def setUp(self):
        self.text = "\n".join(pack.build())
        # The pack is hard-wrapped prose. Asserting a phrase against the raw
        # text tests where the author put line breaks, not what the pack says,
        # so phrase assertions below run against the unwrapped form.
        self.flat = " ".join(self.text.split())

    def test_the_pack_reports_an_empty_corpus_rather_than_a_populated_one(self):
        state = pack._structural_state()
        self.assertEqual(state["corpus"]["registered"], 0)
        self.assertFalse(state["corpus"]["corpus_present"])

    def test_the_pack_reports_an_absent_golden_set(self):
        state = pack._structural_state()
        self.assertFalse(state["golden_set"]["present"])
        self.assertEqual(state["golden_set"]["blocking_ticket"], "LH-602")

    def test_no_template_is_ratified(self):
        state = pack._structural_state()
        self.assertFalse(state["templates"]["any_ratified"])

    def test_the_pack_argues_why_fabrication_would_be_worse_than_absence(self):
        """Phase 5 is the easiest phase in the programme to demo convincingly.

        The argument has to be in the pack rather than only in the ADR, because
        the pack is what a gate reviewer reads.
        """
        self.assertIn("measures the fabricator", self.flat)
        self.assertIn("stale-rate poisoning", self.flat.lower())

    def test_zero_counts_are_distinguished_from_measurements(self):
        """"0 undated documents" looks like a clean audit result.

        It is not a result at all — an undated document cannot be registered, so
        there is nothing to count.
        """
        state = pack._structural_state()
        self.assertIn("structurally zero", state["corpus"]["undated_note"])


class DeliverablesAndTickets(unittest.TestCase):
    def setUp(self):
        self.text = "\n".join(pack.build())

    def test_all_ten_deliverables_are_listed(self):
        for number in range(1, 11):
            self.assertIn(f"| {number} |", self.text)

    def test_the_four_launch_tools_are_named_from_the_registry(self):
        """Read from the code, so a fifth tool cannot appear only in the pack."""
        state = pack._structural_state()
        self.assertEqual(state["tools"]["count"], 4)
        for name in state["tools"]["registered"]:
            self.assertIn(name, self.text)

    def test_open_tickets_are_read_from_the_register(self):
        tickets = pack._open_tickets()
        self.assertGreaterEqual(len(tickets), 12)
        ids = {ticket for ticket, _ in tickets}
        self.assertIn("LH-601", ids)
        self.assertIn("LH-612", ids)

    def test_the_pack_separates_do_not_invent_tickets_from_found_by_building(self):
        """The distinction is what tells a reader whether the phase was attempted.

        Master §5's note on the P1 row: a short do-not-invent list is a sign the
        phase has not been built against, not a sign it is simple.
        """
        self.assertIn("found by building", self.text.lower())

    def test_model_cards_are_listed_and_none_is_signed(self):
        cards = pack._model_cards()
        self.assertGreaterEqual(len(cards), 2)
        self.assertTrue(all(not signed for _, signed in cards))

    def test_the_gate_outcome_is_fail(self):
        self.assertIn("**Fail.**", self.text)


class Regeneration(unittest.TestCase):
    def test_the_pack_writes_and_is_stable_apart_from_its_timestamp(self):
        """A pack that differed between runs would make every diff unreadable."""
        first = [line for line in pack.build() if not line.startswith("Generated ")]
        second = [line for line in pack.build() if not line.startswith("Generated ")]
        self.assertEqual(first, second)

    def test_main_writes_the_file_and_exits_zero(self):
        """Exit 0 whether or not the gate passes.

        A report that failed CI when the gate failed would create pressure to
        stop generating it, which is how a failing gate becomes an invisible one.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "phase5_gate.md"
            self.assertEqual(pack.main(["--output", str(out)]), 0)
            self.assertIn("Phase 5 — gate evidence pack", out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

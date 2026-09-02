"""The Phase 6 gate pack — tools/phase6_gate_report.py.

Phase 6 is the first phase with **no exit criteria to pass**, so its pack is a
different object from the five before it: it reports readiness to learn rather
than learning having happened.

These tests pin the shape that keeps that legible — that the pack never claims a
measured lift, that "not applicable" is distinguished from "fail", and that the
protocol / result distinction survives editing.
"""

from __future__ import annotations

import pathlib
import sys
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "src"))

import phase6_gate_report as pack  # noqa: E402


class PackShape(unittest.TestCase):
    def setUp(self):
        self.text = "\n".join(pack.build())
        # The pack is hard-wrapped prose; assert against the unwrapped form so a
        # test pins what it says rather than where the lines break.
        self.flat = " ".join(self.text.split())

    def test_all_five_standing_conditions_appear(self):
        """§4 states five. A pack that dropped one would read as passing more."""
        self.assertEqual(len(pack.STANDING), 5)
        for name, _, _ in pack.STANDING:
            self.assertIn(name, self.text)

    def test_all_seven_workstreams_appear(self):
        self.assertEqual(len(pack.WORKSTREAMS), 7)
        for code, _, _, _, _ in pack.WORKSTREAMS:
            self.assertIn(code, self.text)

    def test_every_workstream_names_its_feed(self):
        """The feed is the reason a workstream is or is not buildable, so it
        travels with the row rather than living only in the ADR."""
        for code, _, feed, _, _ in pack.WORKSTREAMS:
            self.assertTrue(feed.strip(), code)
            self.assertIn(feed, self.text)

    def test_the_gate_outcome_is_not_applicable_rather_than_fail(self):
        """Phase 6 has no exit criteria, so "fail" would be inaccurate — and the
        pack says explicitly that this is not a euphemism."""
        self.assertIn("Not applicable", self.text)
        self.assertIn("not a euphemism for fail", self.flat)

    def test_the_pack_states_that_no_lift_is_measured(self):
        """The sentence a reader skimming for numbers needs to find first."""
        self.assertIn("No lift of any kind is measured", self.flat)

    def test_the_protocol_result_distinction_is_stated(self):
        """This pack's specific misreading risk, and the inverse of Phase 5's."""
        self.assertIn("protocol being read as a result", self.flat)


class NothingIsClaimedThatWasNotRun(unittest.TestCase):
    def setUp(self):
        self.flat = " ".join(" ".join(pack.build()).split())

    def test_the_standing_conditions_are_marked_never_exercised(self):
        """Implemented and enforced is true; exercised on a promotion is not."""
        self.assertIn("never exercised", self.flat)

    def test_the_pack_records_that_there_is_no_track_p_by_decision(self):
        """Not an unrun job. Elliptic is real and would run; it tests the wrong
        property. ADR-0013 made the "no data exists" claim for Phase 2 and had
        to be amended."""
        self.assertIn("no Track P", self.flat)
        self.assertIn("decision", self.flat)
        self.assertIn("ADR-0016", self.flat)

    def test_no_model_card_is_claimed_when_no_model_is_fitted(self):
        """Master §2 rule 5 requires a card per model, and Phase 6 fits none, so
        an empty card directory is correct rather than incomplete."""
        cards = pack._model_cards()
        if not cards:
            self.assertIn("Master §2 rule 5", self.flat)
        else:
            self.assertTrue(all(not signed for _, signed in cards))


class ComputedNotTyped(unittest.TestCase):
    """Counts are read from the code and the register, so neither can drift."""

    def test_the_cadence_count_comes_from_the_module(self):
        from lending_hub.learning.cadence import CADENCE

        self.assertEqual(pack._cadence_state()["total"], len(CADENCE))

    def test_nothing_is_runnable_because_no_phase_has_shipped(self):
        """Not-yet-applicable, not overdue — the Phase 3 distinction in a
        monitoring dashboard."""
        self.assertEqual(pack._cadence_state()["runnable_now"], 0)

    def test_open_tickets_are_read_from_the_register(self):
        tickets = pack._open_tickets()
        ids = {t for t, _ in tickets}
        self.assertIn("LH-801", ids)
        self.assertIn("LH-811", ids)
        self.assertGreaterEqual(len(tickets), 11)

    def test_no_ticket_id_is_referenced_that_the_register_lacks(self):
        """A dangling ticket reference is how a register and a pack drift."""
        import re

        text = "\n".join(pack.build())
        registered = {t for t, _ in pack._open_tickets()}
        # Phase 6 owns the LH-8xx range; earlier ranges are other registers'.
        referenced = set(re.findall(r"LH-8\d\d", text))
        self.assertEqual(referenced - registered, set())


class TheUnidentifiableDistinction(unittest.TestCase):
    """The phase's central method note has to be in the pack, not only the ADR,
    because the pack is what a gate reviewer reads."""

    def setUp(self):
        self.flat = " ".join(" ".join(pack.build()).split())

    def test_the_third_gate_state_is_named_and_explained(self):
        self.assertIn("unidentifiable", self.flat.lower())
        self.assertIn("randomization", self.flat.lower())

    def test_the_counterintuitive_consequence_is_stated(self):
        """The part that inverts every other blocked ticket's advice: waiting
        for more data makes this estimate worse, not better."""
        self.assertIn("tighter, not truer", self.flat)


class Regeneration(unittest.TestCase):
    def test_the_pack_is_stable_apart_from_its_timestamp(self):
        first = [line for line in pack.build() if not line.startswith("Generated ")]
        second = [line for line in pack.build() if not line.startswith("Generated ")]
        self.assertEqual(first, second)

    def test_main_writes_the_file_and_exits_zero(self):
        """Exit 0 whether or not the gate passes: a report that failed CI when
        the gate failed would create pressure to stop generating it."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "phase6_gate.md"
            self.assertEqual(pack.main(["--output", str(out)]), 0)
            self.assertIn(
                "Phase 6 — gate evidence pack", out.read_text(encoding="utf-8")
            )


if __name__ == "__main__":
    unittest.main()

"""The Phase 5 assistant demonstration — lending_hub.assistant.demo.

A demo is where a fabricated number most easily enters a repository, because its
output looks like evidence and nobody diffs it. These tests pin that every
verdict shown is computed by the real validator on the text shown, and that the
scenarios which must refuse actually do.

One test exists because of a defect found while writing the demo:
`scan_for_injection` takes a *sequence* of untrusted items, and passing a bare
string iterates it character by character and finds nothing. A scanner reporting
zero findings on an obvious attack is exactly the false reassurance
`InjectionScan` is designed never to give, so it is pinned here.
"""

from __future__ import annotations

import contextlib
import io
import unittest

from lending_hub.assistant import demo


def _run(*argv: str) -> str:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = demo.main(list(argv))
    assert code == 0, f"demo exited {code}"
    return buffer.getvalue()


class ScenariosRun(unittest.TestCase):
    def test_each_scenario_runs_alone(self):
        for scenario in demo.SCENARIOS:
            with self.subTest(scenario=scenario):
                self.assertTrue(_run(scenario).strip())

    def test_all_scenarios_run_together(self):
        self.assertTrue(_run().strip())


class TheValidatorDemoIsComputed(unittest.TestCase):
    """Not a script of canned outcomes — the verdicts come from validate()."""

    def test_a_fully_uncited_answer_becomes_a_handoff(self):
        output = _run("validator")
        self.assertIn("(nothing — handed to a human)", output)

    def test_a_mixed_answer_keeps_the_sentence_without_a_number(self):
        output = _run("validator")
        self.assertIn("Rates depend on your profile.", output)
        self.assertIn("DROPPED", output)

    def test_a_resolvable_citation_keeps_the_claim(self):
        """The comparison the demo is built around: identical wording, and the
        only difference is whether the citation resolves."""
        output = _run("validator")
        self.assertIn("c1@rate-circular-2026-03", output)

    def test_a_tool_sourced_number_is_kept(self):
        """Phase 5 forbids LLM arithmetic outright — an EMI comes from the tool."""
        output = _run("validator")
        self.assertIn("compute_emi", output)
        self.assertIn("11,248.97", output)

    def test_custom_text_is_run_through_the_real_validator(self):
        """The mode that makes the demo a tool rather than a recording."""
        output = _run("--text", "You qualify for 5 lakh at 9.9% interest.")
        self.assertIn("5 lakh", output)
        self.assertIn("9.9%", output)
        self.assertIn("no citation", output)

    def test_a_different_input_gives_a_different_verdict(self):
        """If the output were canned, this would not change."""
        uncited = _run("--text", "Your rate is 12 percent.")
        safe = _run("--text", "Rates vary by product.")
        self.assertIn("DROPPED", uncited)
        self.assertNotIn("DROPPED", safe)


class TheInjectionScannerActuallyFires(unittest.TestCase):
    """Pinned because the demo's first version reported zero findings.

    `scan_for_injection` takes a sequence; a bare string is iterated per
    character and matches nothing. A clean scan on a real attack is the most
    dangerous output this package can produce, so a test guards it.
    """

    def test_an_obvious_override_is_detected(self):
        output = _run("injection")
        self.assertIn("findings: 1", output)
        self.assertIn("instruction_override", output)

    def test_the_scanner_never_claims_safety(self):
        output = _run("injection")
        self.assertIn("never returns a verdict of safety", output)


class TheDemoStatesItsLimits(unittest.TestCase):
    def test_it_says_no_model_is_bound(self):
        self.assertIn("No model is bound", _run("absent"))

    def test_it_names_every_blocking_ticket(self):
        output = _run("absent")
        for ticket in ("LH-601", "LH-602", "LH-603", "LH-604"):
            self.assertIn(ticket, output)

    def test_it_disclaims_being_gate_evidence(self):
        flat = " ".join(_run("absent").split())
        self.assertIn("Nothing here is a Phase 5 gate number", flat)


if __name__ == "__main__":
    unittest.main()

"""The Phase 6 demonstration runner — lending_hub.learning.demo.

A demo is the easiest place in a repository for a fabricated number to enter,
because its output looks like evidence and nobody diffs it. So these tests pin
the two properties that keep it honest:

* every number it prints is **computed**, which is checked by varying an input
  and asserting the output moves; and
* the refusals are **exercised**, not described — the scenarios that end in an
  exception must actually raise, or the demo would be claiming a guard that no
  longer fires.
"""

from __future__ import annotations

import contextlib
import io
import unittest

from lending_hub.learning import demo


def _run(*argv: str) -> str:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = demo.main(list(argv))
    assert code == 0, f"demo exited {code}"
    return buffer.getvalue()


class EveryScenarioRuns(unittest.TestCase):
    def test_each_scenario_runs_alone(self):
        for scenario in demo.SCENARIOS:
            with self.subTest(scenario=scenario):
                self.assertTrue(_run(scenario).strip())

    def test_all_scenarios_run_together(self):
        output = _run()
        for scenario in demo.SCENARIOS:
            self.assertIn(scenario, output.lower().replace(" ", ""), scenario)


class NumbersAreComputedNotPrinted(unittest.TestCase):
    """The property that separates a demo from a screenshot.

    If the output were canned, changing the input would not move it.
    """

    def test_graph_output_changes_with_group_size(self):
        small = _run("graph", "--group-size", "3")
        large = _run("graph", "--group-size", "5")
        self.assertIn("0.357143", small)  # hand-verified in test_learning_graph
        self.assertNotIn("0.357143", large)
        self.assertIn("6 applicants", small)
        self.assertIn("10 applicants", large)

    def test_the_modularity_matches_the_hand_computed_value(self):
        """Two triangles joined by one edge: Q = 0.357143, computed by hand in
        test_learning_graph and reproduced here through the demo path."""
        self.assertIn("0.357143", _run("graph", "--group-size", "3"))

    def test_the_dr_estimate_matches_the_hand_computed_value(self):
        """0.5 and ESS 40.0 were derived independently — see
        test_learning_offpolicy.TheEstimatorArithmetic."""
        output = _run("offpolicy")
        self.assertIn("0.500000", output)
        self.assertIn("40.0", output)


class RefusalsAreExercised(unittest.TestCase):
    """The demo's most useful output. A refusal that stopped firing would make
    the demo teach the opposite of the phase's central point."""

    def test_the_uplift_guard_refuses_an_observational_log(self):
        output = _run("uplift", "--observational")
        self.assertIn("REFUSED", output)
        self.assertIn("unidentifiable", output)

    def test_the_same_rows_are_estimable_when_randomized(self):
        """The comparison that makes the point: identical outcomes, different
        assignment mechanism, opposite results."""
        refused = _run("uplift", "--observational")
        allowed = _run("uplift")
        self.assertIn("REFUSED", refused)
        self.assertNotIn("REFUSED", allowed)
        self.assertIn("causal effect tau", allowed)

    def test_positivity_refuses_a_concentrated_log(self):
        output = _run("offpolicy", "--broken-log")
        self.assertIn("REFUSED", output)
        self.assertIn("effective sample size", output)

    def test_the_fraud_label_density_refusal_is_shown(self):
        output = _run("graph")
        self.assertIn("REFUSED", output)
        self.assertIn("disposition", output)

    def test_the_promotion_gate_refuses_then_passes_when_fixed(self):
        output = _run("promotion")
        self.assertIn("allowed: False", output)
        self.assertIn("after fixing all three: allowed = True", output)

    def test_a_mismatched_comparison_is_refused(self):
        output = _run("challenger")
        self.assertIn("REFUSED", output)
        self.assertIn("window mismatch", output)


class TheDemoStatesItsOwnLimits(unittest.TestCase):
    def test_it_says_no_model_is_fitted(self):
        self.assertIn("No model is fitted", _run("absent"))

    def test_it_names_every_absent_challenger_with_its_blocker(self):
        output = _run("absent")
        for name in ("CARE-GNN", "Noiseprint", "DeepSurv", "Causal forests"):
            self.assertIn(name, output)
        for ticket in ("LH-810", "LH-812", "LH-811", "LH-813"):
            self.assertIn(ticket, output)

    def test_it_disclaims_being_gate_evidence(self):
        """A demo's output is the easiest thing in a repo to mistake for a
        result, so the disclaimer prints on every run rather than once."""
        flat = " ".join(_run("cadence").split())
        self.assertIn("Nothing computed here is a Phase 6 gate number", flat)

    def test_a_degenerate_group_size_is_rejected(self):
        # argparse writes its usage message to stderr; captured so a passing
        # suite does not print an error that looks like a failure.
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            _run("graph", "--group-size", "1")


if __name__ == "__main__":
    unittest.main()

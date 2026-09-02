"""Uplift and the identifiability guard — Phase 6 WS-6.4.

The tests that matter here are the refusals. Phase 6 §2 WS-6.4 makes randomized
holdouts standing policy and states the reason — without them uplift is
*unidentifiable*, which is a stronger claim than unmeasurable — and §5 puts
"causal claims from observational data" on the do-not-invent list.

So these pin that an observational log produces no number at all, rather than a
number carrying a caveat: a caveat is an attribute, and the attribute is gone by
the second transformation.
"""

from __future__ import annotations

import unittest

from lending_hub.learning.uplift import (
    MIN_ARM_SIZE,
    SMD_FLAG,
    ActionLog,
    ActionRecord,
    Assignment,
    UpliftError,
    check_randomization,
    estimate_uplift,
    qini_coefficient,
    qini_curve,
)


def _records(n: int = 100, *, treated_rate: float = 0.4, control_rate: float = 0.2):
    """Half treated, with a real effect: treated cure more often."""
    out = []
    for i in range(n):
        treated = i % 2 == 0
        rate = treated_rate if treated else control_rate
        # Deterministic assignment of outcomes at the target rate.
        outcome = 1.0 if (i // 2) % round(1 / rate) == 0 else 0.0
        out.append(
            ActionRecord(
                account_id=f"a{i}",
                treated=treated,
                outcome=outcome,
                covariates={"balance": float(i % 7), "dpd": float(i % 3)},
            )
        )
    return out


class UnidentifiableIsNotUnmeasured(unittest.TestCase):
    """The distinction Phase 6 adds to Phase 3's not-measured / not-measurable.

    Both of those are about missing data: given the right dataset the number
    appears. This one is missing randomization, and no quantity of rows supplies
    it — more data narrows the interval around a confounded quantity.
    """

    def test_an_observational_log_yields_no_estimate(self):
        log = ActionLog(_records(), Assignment.OBSERVATIONAL)
        with self.assertRaises(UpliftError) as caught:
            estimate_uplift(log)
        self.assertIn("unidentifiable", str(caught.exception))

    def test_an_unknown_assignment_is_treated_as_observational(self):
        """The safe reading, and the one that creates pressure to record it."""
        log = ActionLog(_records(), Assignment.UNKNOWN)
        with self.assertRaises(UpliftError):
            estimate_uplift(log)

    def test_the_refusal_is_not_a_flagged_number(self):
        """No branch returns an estimate with causal=False. An estimate carrying
        a warning attribute is a number in a dataframe by the next step."""
        log = ActionLog(_records(), Assignment.OBSERVATIONAL)
        with self.assertRaises(UpliftError):
            estimate_uplift(log)

    def test_a_qini_curve_is_refused_on_the_same_grounds(self):
        """Ranking by a confounded quantity measures the assignment rule."""
        log = ActionLog(_records(), Assignment.OBSERVATIONAL)
        scores = {r.account_id: 0.5 for r in log.records}
        with self.assertRaises(UpliftError):
            qini_curve(log, scores)


class RandomizationIsAsserted(unittest.TestCase):
    """No code can verify randomization from a log, so the claim carries a name."""

    def test_randomized_requires_an_asserter(self):
        with self.assertRaises(UpliftError) as caught:
            ActionLog(_records(), Assignment.RANDOMIZED)
        self.assertIn("asserted_by", str(caught.exception))

    def test_a_randomized_log_estimates_and_records_who_claimed_it(self):
        log = ActionLog(_records(), Assignment.RANDOMIZED, asserted_by="collections-ops")
        estimate = estimate_uplift(log)
        self.assertEqual(estimate.asserted_by, "collections-ops")
        self.assertGreater(estimate.effect, 0.0)

    def test_the_effect_is_the_difference_of_arm_rates(self):
        log = ActionLog(_records(), Assignment.RANDOMIZED, asserted_by="ops")
        estimate = estimate_uplift(log)
        self.assertAlmostEqual(
            estimate.effect, estimate.treated_rate - estimate.control_rate, places=12
        )


class BalanceReportsAndNeverDecides(unittest.TestCase):
    """The same shape as InjectionScan: reports what it found, never safety."""

    def test_balance_never_proves_randomization(self):
        """A confounded log balances on the columns someone happened to record.

        The confounder is usually the officer's judgement, which is recorded
        nowhere — so a passing balance check is necessary and never sufficient.
        """
        log = ActionLog(_records(), Assignment.RANDOMIZED, asserted_by="ops")
        self.assertFalse(check_randomization(log).proves_randomization)

    def test_an_imbalanced_covariate_is_flagged_with_its_smd(self):
        records = [
            ActionRecord(f"t{i}", True, 1.0, {"balance": 100.0}) for i in range(MIN_ARM_SIZE)
        ] + [
            ActionRecord(f"c{i}", False, 0.0, {"balance": 1.0}) for i in range(MIN_ARM_SIZE)
        ]
        report = check_randomization(
            ActionLog(records, Assignment.RANDOMIZED, asserted_by="ops")
        )
        self.assertEqual(len(report.flagged), 1)
        self.assertGreater(abs(report.flagged[0].smd), SMD_FLAG)

    def test_a_log_with_no_covariates_says_it_compared_nothing(self):
        """The most dangerous balance report is the empty one that looks clean."""
        records = [ActionRecord(f"a{i}", i % 2 == 0, 1.0) for i in range(2 * MIN_ARM_SIZE)]
        report = check_randomization(
            ActionLog(records, Assignment.RANDOMIZED, asserted_by="ops")
        )
        self.assertIn("compared on nothing", report.summary())


class ArmSizeFloor(unittest.TestCase):
    def test_tiny_arms_are_refused(self):
        records = [ActionRecord(f"a{i}", i % 2 == 0, 1.0) for i in range(10)]
        log = ActionLog(records, Assignment.RANDOMIZED, asserted_by="ops")
        with self.assertRaises(UpliftError) as caught:
            estimate_uplift(log)
        self.assertIn("floor", str(caught.exception))


class QiniMechanics(unittest.TestCase):
    def test_the_curve_has_one_point_per_account(self):
        log = ActionLog(_records(), Assignment.RANDOMIZED, asserted_by="ops")
        scores = {r.account_id: 1.0 / (i + 1) for i, r in enumerate(log.records)}
        curve = qini_curve(log, scores)
        self.assertEqual(len(curve), len(log.records))
        self.assertEqual(curve[0].targeted, 1)

    def test_a_missing_score_is_refused_rather_than_dropped(self):
        """A partial ranking silently shortens the curve, which changes the
        coefficient without changing anything visible."""
        log = ActionLog(_records(), Assignment.RANDOMIZED, asserted_by="ops")
        scores = {r.account_id: 0.5 for r in log.records}
        del scores[log.records[3].account_id]
        with self.assertRaises(UpliftError) as caught:
            qini_curve(log, scores)
        self.assertIn("no score", str(caught.exception))

    def test_a_targeting_rule_that_finds_the_responders_beats_random(self):
        """The property a Qini coefficient exists to express.

        Built so treated responders sort first: a rule that ranks them above
        everyone else must score above the random-targeting diagonal.
        """
        records = []
        for i in range(200):
            treated = i % 2 == 0
            responder = treated and i < 100
            records.append(
                ActionRecord(f"a{i}", treated, 1.0 if responder else 0.0)
            )
        log = ActionLog(records, Assignment.RANDOMIZED, asserted_by="ops")
        good = {r.account_id: (1.0 if r.outcome > 0 else 0.0) for r in records}
        flat = {r.account_id: 0.5 for r in records}
        self.assertGreater(
            qini_coefficient(qini_curve(log, good)),
            qini_coefficient(qini_curve(log, flat)),
        )

    def test_a_coefficient_needs_at_least_two_points(self):
        with self.assertRaises(UpliftError):
            qini_coefficient([])


class NoPromotionThresholdIsDefaulted(unittest.TestCase):
    def test_no_qini_threshold_appears_in_the_module(self):
        """WS-6.4's gate is "Qini coefficient + online cure-rate lift", neither
        quantified. A default here would become the programme's number."""
        import lending_hub.learning.uplift as module

        self.assertFalse(
            [n for n in dir(module) if "THRESHOLD" in n or "MIN_QINI" in n]
        )


if __name__ == "__main__":
    unittest.main()

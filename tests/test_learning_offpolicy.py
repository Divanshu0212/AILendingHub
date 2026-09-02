"""Doubly-robust off-policy evaluation — Phase 6 WS-6.5.

Two things are pinned here. The estimator's arithmetic, against values computed
independently rather than read off this implementation — a golden file
transcribed from the code it tests proves only that the code is self-consistent,
which is the lesson from Phase 4's EMI fixtures.

And the positivity refusals. WS-6.5 evaluates candidate policies *before any
traffic*, so the estimate is the only thing standing between a policy and a
canary; an estimate computed on a log that cannot support it is worse than no
estimate, because it arrives with a number attached.
"""

from __future__ import annotations

import unittest

from lending_hub.learning.offpolicy import (
    MIN_EFFECTIVE_SAMPLE,
    MIN_PROPENSITY,
    LoggedDecision,
    OffPolicyError,
    check_positivity,
    evaluate_policy,
    from_bandit_decisions,
)


def _log(n: int = 80, propensity: float = 0.5):
    """Alternating A/B actions; every fourth row rewards. All rewards fall on A."""
    return [
        LoggedDecision(
            context_id=f"c{i}",
            action="A" if i % 2 == 0 else "B",
            propensity=propensity,
            reward=1.0 if i % 4 == 0 else 0.0,
        )
        for i in range(n)
    ]


def _always_a(context_id: str) -> str:
    return "A"


def _reward_model(context_id: str, action: str) -> float:
    return 0.5 if action == "A" else 0.2


class TheEstimatorArithmetic(unittest.TestCase):
    """Pinned against an independent hand computation, not against this code.

    For the fixture above: 40 rows logged A, of which 20 reward. The target
    policy always picks A, so on every A row the correction is
    (r − 0.5)/0.5 = ±1, summing to zero across 20 rewarding and 20 non-rewarding
    rows. On every B row the correction is zero. So V_DR is exactly the direct
    method's 0.5.
    """

    def test_the_dr_value_matches_the_hand_computation(self):
        estimate = evaluate_policy(_log(), _always_a, _reward_model)
        self.assertAlmostEqual(estimate.value, 0.5, places=12)

    def test_the_logged_value_is_the_empirical_mean_reward(self):
        """20 rewarding rows in 80 = 0.25."""
        estimate = evaluate_policy(_log(), _always_a, _reward_model)
        self.assertAlmostEqual(estimate.logged_value, 0.25, places=12)

    def test_the_lift_is_the_difference(self):
        estimate = evaluate_policy(_log(), _always_a, _reward_model)
        self.assertAlmostEqual(estimate.lift, 0.25, places=12)
        self.assertTrue(estimate.positive)

    def test_the_effective_sample_size_counts_matching_rows_only(self):
        """40 rows match at weight 2: (40·2)² / (40·4) = 40, not 80.

        Reporting n=80 beside this estimate is the misleading part.
        """
        estimate = evaluate_policy(_log(), _always_a, _reward_model)
        self.assertAlmostEqual(estimate.positivity.effective_sample_size, 40.0, places=9)
        self.assertEqual(estimate.n, 80)

    def test_a_perfect_reward_model_makes_dr_equal_the_direct_method(self):
        """The DR property: when r̂ is exact, every correction term is zero."""
        log = [
            LoggedDecision(f"c{i}", "A", 0.5, 0.7) for i in range(MIN_EFFECTIVE_SAMPLE * 2)
        ]
        estimate = evaluate_policy(log, _always_a, lambda c, a: 0.7)
        self.assertAlmostEqual(estimate.value, 0.7, places=12)
        self.assertAlmostEqual(estimate.standard_error, 0.0, places=12)


class PositivityIsARefusal(unittest.TestCase):
    """Not a diagnostic. If the logging policy never took an action, the log
    holds no evidence about it, and no estimator recovers what was never seen.
    """

    def test_a_near_zero_propensity_is_refused(self):
        log = _log()
        log[0] = LoggedDecision("c0", "A", MIN_PROPENSITY / 2, 1.0)
        with self.assertRaises(OffPolicyError) as caught:
            evaluate_policy(log, _always_a, _reward_model)
        self.assertIn("exploration cell", str(caught.exception))

    def test_a_zero_propensity_cannot_be_constructed_at_all(self):
        with self.assertRaises(OffPolicyError):
            LoggedDecision("c0", "A", 0.0, 1.0)

    def test_a_propensity_above_one_is_refused(self):
        with self.assertRaises(OffPolicyError):
            LoggedDecision("c0", "A", 1.5, 1.0)

    def test_an_action_the_log_never_took_is_refused(self):
        log = [LoggedDecision(f"c{i}", "A", 0.5, 1.0) for i in range(60)]
        with self.assertRaises(OffPolicyError) as caught:
            evaluate_policy(log, lambda c: "Z", _reward_model)
        self.assertIn("never took", str(caught.exception))

    def test_a_concentrated_log_is_refused_despite_many_rows(self):
        """The failure this guard exists for: many rows, few effective ones.

        One row matches the target policy, so the estimate describes that row.
        """
        log = [LoggedDecision(f"c{i}", "B", 0.5, 0.0) for i in range(200)]
        log[0] = LoggedDecision("c0", "A", 0.5, 1.0)
        with self.assertRaises(OffPolicyError) as caught:
            evaluate_policy(log, _always_a, _reward_model)
        self.assertIn("effective sample size", str(caught.exception))

    def test_an_empty_log_is_refused(self):
        with self.assertRaises(OffPolicyError):
            evaluate_policy([], _always_a, _reward_model)
        with self.assertRaises(OffPolicyError):
            check_positivity([], _always_a)


class TheBanditBridge(unittest.TestCase):
    """P4's BanditDecision guarantees a propensity, so a P4 log is admissible
    by construction. Duck-typed rather than imported so WS-6.4's collections
    actions run through the same estimator.
    """

    class _Decision:
        def __init__(self, context_id, action, propensity, reward):
            self.context_id = context_id
            self.action = action
            self.propensity = propensity
            self.reward = reward

    def test_a_well_formed_decision_converts(self):
        converted = from_bandit_decisions(
            [self._Decision("c1", "offer-a", 0.25, 1.0)]
        )
        self.assertEqual(converted[0].propensity, 0.25)

    def test_a_decision_without_a_propensity_is_refused_by_name(self):
        class NoPropensity:
            context_id = "c1"
            action = "offer-a"
            reward = 1.0

        with self.assertRaises(OffPolicyError) as caught:
            from_bandit_decisions([NoPropensity()])
        self.assertIn("propensity", str(caught.exception))


class NoCanaryThresholdIsDefaulted(unittest.TestCase):
    def test_positive_is_a_sign_test_and_nothing_more(self):
        """WS-6.5 says "only positive-DR-estimate policies proceed" and does not
        say how positive, or against what confidence. LH-804 — a point estimate
        marginally above zero is not evidence, and the phase file does not say so.
        """
        estimate = evaluate_policy(_log(), _always_a, _reward_model)
        self.assertTrue(estimate.positive)
        low, high = estimate.confidence_interval()
        self.assertLess(low, estimate.value)
        self.assertGreater(high, estimate.value)


if __name__ == "__main__":
    unittest.main()

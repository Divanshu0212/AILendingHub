"""LinUCB and propensity logging — WS-4.B Steps 3-4.

Two things carry this module. Propensity logging is a constructor invariant
rather than a logging call, which makes Phase 4 §8's "completeness = 100%" the
one exit criterion this repository can fully satisfy. And the reward refuses to
blend without a ratified weight (LH-509), which is what stops the bandit
becoming the mis-selling engine the finding describes.
"""

from __future__ import annotations

import unittest
from datetime import date

from lending_hub.definitions.provenance import Ungrounded
from lending_hub.reco.bandit import (
    EXPLORATION_CELL,
    REWARD_BLEND,
    BanditDecision,
    BanditError,
    LinUCB,
    OfferTemplate,
    Reward,
    propensity_completeness,
)
from lending_hub.reco.feasible import (
    Applicant,
    PolicyCaps,
    Segment,
    build_feasible_set,
)

TODAY = date(2026, 9, 1)
BASE_RATE = 0.12


def _caps() -> PolicyCaps:
    return PolicyCaps(
        product="personal_loan",
        segment=Segment.RETAIL,
        foir_cap=0.50,
        dscr_floor=None,
        ltv_cap=None,
        max_tenor_months=60,
        min_amount=50_000.0,
        max_amount=1_000_000.0,
        ratification_reference="CP-2026-11",
    )


def _applicant(income=80_000.0, obligations=5_000.0) -> Applicant:
    return Applicant(
        applicant_id="C1",
        segment=Segment.RETAIL,
        verified_monthly_income=income,
        existing_monthly_obligations=obligations,
    )


def _arms(amounts=(200_000.0, 500_000.0, 900_000.0)) -> dict[str, OfferTemplate]:
    return {
        f"t{i}": OfferTemplate(f"t{i}", "personal_loan", amount, 60)
        for i, amount in enumerate(amounts)
    }


def _feasible_set(applicant=None, arms=None):
    arms = arms or _arms()
    applicant = applicant or _applicant()
    offers = [t.to_offer(BASE_RATE) for t in arms.values()]
    return build_feasible_set(applicant, offers, {"personal_loan": _caps()})


def _bandit(arms=None, **kwargs) -> LinUCB:
    return LinUCB(arms=arms or _arms(), dimension=3, **kwargs)


def _select(bandit, feasible_set, decision_id="D1", context=(1.0, 0.5, 0.2)):
    return bandit.select(
        list(context), feasible_set, BASE_RATE,
        decision_id=decision_id, subject_token="TOK1", decided_on=TODAY,
    )


class TestPropensityIsStructural(unittest.TestCase):
    """Phase 4 §8's one fully-provable exit criterion."""

    def test_a_decision_cannot_be_built_without_a_propensity(self):
        with self.assertRaises(TypeError):
            BanditDecision(
                decision_id="D1", subject_token="TOK1", template_id="t0",
                decided_on=TODAY, considered_arms=("t0",), is_exploration=False,
            )

    def test_a_zero_propensity_is_refused(self):
        """It says the action could not have been taken, contradicting that it was.

        It also makes P6's importance weight infinite.
        """
        with self.assertRaises(BanditError) as ctx:
            BanditDecision(
                decision_id="D1", subject_token="TOK1", template_id="t0",
                propensity=0.0, decided_on=TODAY, considered_arms=("t0",),
                is_exploration=False,
            )
        self.assertIn("importance weight infinite", str(ctx.exception))

    def test_a_propensity_above_one_is_refused(self):
        with self.assertRaises(BanditError):
            BanditDecision(
                decision_id="D1", subject_token="TOK1", template_id="t0",
                propensity=1.4, decided_on=TODAY, considered_arms=("t0",),
                is_exploration=False,
            )

    def test_choosing_an_arm_outside_those_considered_is_refused(self):
        """The propensity is a probability over the arms that were available."""
        with self.assertRaises(BanditError) as ctx:
            BanditDecision(
                decision_id="D1", subject_token="TOK1", template_id="t9",
                propensity=0.5, decided_on=TODAY, considered_arms=("t0", "t1"),
                is_exploration=False,
            )
        self.assertIn("no interpretable propensity", str(ctx.exception))

    def test_a_decision_must_carry_a_tokenised_subject(self):
        with self.assertRaises(BanditError) as ctx:
            BanditDecision(
                decision_id="D1", subject_token="", template_id="t0",
                propensity=1.0, decided_on=TODAY, considered_arms=("t0",),
                is_exploration=False,
            )
        self.assertIn("raw PII", str(ctx.exception))

    def test_completeness_is_one_by_construction(self):
        bandit = _bandit()
        feasible_set = _feasible_set()
        decisions = [_select(bandit, feasible_set, f"D{i}") for i in range(20)]
        self.assertEqual(propensity_completeness(decisions), 1.0)

    def test_completeness_of_an_empty_log_is_one(self):
        """No decision is missing a propensity."""
        self.assertEqual(propensity_completeness([]), 1.0)


class TestSelectionInsideTheFeasibleSet(unittest.TestCase):
    def test_only_feasible_arms_are_considered(self):
        """§5 Step 4: exploration can never breach affordability or policy."""
        poor = _applicant(income=25_000.0, obligations=2_000.0)
        feasible_set = _feasible_set(applicant=poor)
        decision = _select(_bandit(), feasible_set)

        self.assertNotIn("t2", decision.considered_arms)
        self.assertIn("t0", decision.considered_arms)

    def test_an_empty_intersection_refuses_rather_than_relaxing(self):
        """Not an invitation to widen the set."""
        destitute = _applicant(income=8_000.0, obligations=6_000.0)
        feasible_set = _feasible_set(applicant=destitute)
        with self.assertRaises(BanditError) as ctx:
            _select(_bandit(), feasible_set)
        self.assertIn("not an invitation to relax", str(ctx.exception))

    def test_the_considered_arms_are_recorded_on_the_decision(self):
        decision = _select(_bandit(), _feasible_set())
        self.assertEqual(decision.considered_arms, ("t0", "t1", "t2"))

    def test_a_context_of_the_wrong_size_is_refused(self):
        with self.assertRaises(BanditError):
            _bandit().select(
                [1.0, 0.5], _feasible_set(), BASE_RATE,
                decision_id="D1", subject_token="TOK1", decided_on=TODAY,
            )

    def test_a_greedy_decision_reports_propensity_one(self):
        """LinUCB is deterministic given its state, and that is logged honestly.

        P6's importance weighting handles a deterministic logging policy; it
        cannot handle a determinism smoothed into a plausible distribution.
        """
        decision = _select(_bandit(), _feasible_set())
        self.assertEqual(decision.propensity, 1.0)
        self.assertFalse(decision.is_exploration)

    def test_ucb_scores_are_recorded_for_audit(self):
        decision = _select(_bandit(), _feasible_set())
        self.assertEqual(set(decision.ucb_scores), set(decision.considered_arms))


class TestExploration(unittest.TestCase):
    def test_exploration_is_uniform_over_feasible_arms(self):
        decision = _bandit().explore(
            [1.0, 0.5, 0.2], _feasible_set(), BASE_RATE,
            decision_id="D2", subject_token="TOK1", decided_on=TODAY, rng_value=0.5,
        )
        self.assertAlmostEqual(decision.propensity, 1 / 3, places=12)
        self.assertTrue(decision.is_exploration)

    def test_exploration_is_reproducible_from_its_log(self):
        """"The model picked randomly" is not an answer to a regulator."""
        bandit, feasible_set = _bandit(), _feasible_set()
        kwargs = dict(
            decision_id="D2", subject_token="TOK1", decided_on=TODAY, rng_value=0.7
        )
        first = bandit.explore([1.0, 0.5, 0.2], feasible_set, BASE_RATE, **kwargs)
        second = bandit.explore([1.0, 0.5, 0.2], feasible_set, BASE_RATE, **kwargs)
        self.assertEqual(first.template_id, second.template_id)

    def test_exploration_covers_every_feasible_arm(self):
        bandit, feasible_set = _bandit(), _feasible_set()
        chosen = {
            bandit.explore(
                [1.0, 0.5, 0.2], feasible_set, BASE_RATE,
                decision_id=f"D{i}", subject_token="TOK1", decided_on=TODAY,
                rng_value=i / 30,
            ).template_id
            for i in range(30)
        }
        self.assertEqual(chosen, {"t0", "t1", "t2"})

    def test_exploration_does_not_widen_the_feasible_set(self):
        destitute = _applicant(income=8_000.0, obligations=6_000.0)
        with self.assertRaises(BanditError) as ctx:
            _bandit().explore(
                [1.0, 0.5, 0.2], _feasible_set(applicant=destitute), BASE_RATE,
                decision_id="D2", subject_token="TOK1", decided_on=TODAY, rng_value=0.5,
            )
        self.assertIn("does not widen", str(ctx.exception))

    def test_an_out_of_range_rng_value_is_refused(self):
        for bad in (-0.1, 1.0, 1.5):
            with self.assertRaises(BanditError):
                _bandit().explore(
                    [1.0, 0.5, 0.2], _feasible_set(), BASE_RATE,
                    decision_id="D2", subject_token="TOK1", decided_on=TODAY,
                    rng_value=bad,
                )

    def test_the_exploration_cell_size_is_ungrounded(self):
        """How many customers get a deliberately sub-optimal offer."""
        self.assertEqual(EXPLORATION_CELL.ticket, "LH-503")
        with self.assertRaises(Ungrounded):
            EXPLORATION_CELL.value


class TestRewardRefusesToBlend(unittest.TestCase):
    """LH-509, the phase's sharpest gap."""

    def test_blending_without_a_ratified_weight_raises(self):
        reward = Reward("D1", took_up=True, seasoned_value=0.4, seasoning_months=12)
        with self.assertRaises(Ungrounded) as ctx:
            reward.blended()
        self.assertIn("LH-509", str(ctx.exception))

    def test_the_refusal_names_the_failure_mode(self):
        """A take-up-only bandit offers the largest permitted loan to whoever
        is likeliest to accept, and its reward curve looks like success."""
        reward = Reward("D1", took_up=True, seasoned_value=0.4, seasoning_months=12)
        with self.assertRaises(Ungrounded) as ctx:
            reward.blended()
        message = str(ctx.exception)
        self.assertIn("largest", message)
        self.assertIn("mis-selling engine", message)

    def test_a_ratified_weight_blends(self):
        reward = Reward("D1", took_up=True, seasoned_value=0.5, seasoning_months=12)
        self.assertAlmostEqual(reward.blended(take_up_weight=0.3), 0.3 + 0.7 * 0.5, places=12)

    def test_a_seasoned_value_needs_its_horizon(self):
        """A risk-adjusted value at 3 months and at 24 are different quantities."""
        with self.assertRaises(BanditError) as ctx:
            Reward("D1", took_up=True, seasoned_value=0.4, seasoning_months=None)
        self.assertIn("averaging them is meaningless", str(ctx.exception))

    def test_blending_without_a_seasoned_value_is_refused(self):
        """Waiting for seasoning is the delayed-reward correction, not a delay."""
        reward = Reward("D1", took_up=True, seasoned_value=None, seasoning_months=None)
        with self.assertRaises(BanditError) as ctx:
            reward.blended(take_up_weight=0.3)
        self.assertIn("not an inconvenience", str(ctx.exception))

    def test_a_weight_outside_the_unit_interval_is_refused(self):
        reward = Reward("D1", took_up=True, seasoned_value=0.4, seasoning_months=12)
        for bad in (-0.2, 1.5):
            with self.assertRaises(BanditError):
                reward.blended(take_up_weight=bad)

    def test_the_blend_placeholder_is_registered(self):
        self.assertEqual(REWARD_BLEND.ticket, "LH-509")


class TestLearning(unittest.TestCase):
    def test_update_refuses_without_a_ratified_blend(self):
        bandit, feasible_set = _bandit(), _feasible_set()
        decision = _select(bandit, feasible_set)
        reward = Reward("D1", took_up=True, seasoned_value=0.5, seasoning_months=12)
        with self.assertRaises(Ungrounded):
            bandit.update(decision, [1.0, 0.5, 0.2], reward)

    def test_update_with_a_ratified_blend_learns(self):
        bandit, feasible_set = _bandit(), _feasible_set()
        decision = _select(bandit, feasible_set)
        reward = Reward("D1", took_up=True, seasoned_value=0.5, seasoning_months=12)

        self.assertEqual(bandit.arm_observations(decision.template_id), 0)
        bandit.update(decision, [1.0, 0.5, 0.2], reward, take_up_weight=0.3)
        self.assertEqual(bandit.arm_observations(decision.template_id), 1)

    def test_a_reward_for_another_decision_is_refused(self):
        bandit, feasible_set = _bandit(), _feasible_set()
        decision = _select(bandit, feasible_set, "D1")
        reward = Reward("D9", took_up=True, seasoned_value=0.5, seasoning_months=12)
        with self.assertRaises(BanditError):
            bandit.update(decision, [1.0, 0.5, 0.2], reward, take_up_weight=0.3)

    def test_the_bandit_prefers_a_rewarded_arm(self):
        """The property a LinUCB swap must preserve, whatever its internals."""
        arms = _arms()
        bandit = LinUCB(arms=arms, dimension=3, alpha=0.1)
        feasible_set = _feasible_set(arms=arms)
        context = [1.0, 0.5, 0.2]

        for i in range(12):
            decision = BanditDecision(
                decision_id=f"D{i}", subject_token="TOK1", template_id="t1",
                propensity=1.0, decided_on=TODAY, considered_arms=("t0", "t1", "t2"),
                is_exploration=False,
            )
            bandit.update(
                decision, context,
                Reward(f"D{i}", took_up=True, seasoned_value=0.9, seasoning_months=12),
                take_up_weight=0.5,
            )

        self.assertEqual(_select(bandit, feasible_set).template_id, "t1")


class TestArmsAreTemplates(unittest.TestCase):
    def test_a_template_needs_an_id(self):
        with self.assertRaises(BanditError):
            OfferTemplate("", "personal_loan", 100_000.0, 24)

    def test_a_template_produces_an_offer_at_the_priced_rate(self):
        """A template adjusts price relative to the computed rate, never replaces it."""
        template = OfferTemplate("t0", "personal_loan", 300_000.0, 36, rate_offset=0.005)
        offer = template.to_offer(0.12)
        self.assertAlmostEqual(offer.annual_rate, 0.125, places=12)

    def test_a_bandit_needs_arms(self):
        with self.assertRaises(BanditError):
            LinUCB(arms={}, dimension=3)

    def test_a_negative_alpha_inverts_exploration(self):
        with self.assertRaises(BanditError) as ctx:
            _bandit(alpha=-1.0)
        self.assertIn("opposite of exploration", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

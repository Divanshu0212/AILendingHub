"""Agri lifecycle and the suitability duty — WS-4.B Step 5.

The drought rule is the one that has to be structural, because it runs against
the commercial grain: a drought-flagged farmer is in acute need and therefore
unusually likely to accept, so every take-up signal says market to them and the
duty says the opposite. A suppression implemented as a downstream filter is one
refactor from being lost, and its absence is invisible — the campaign simply
performs well.
"""

from __future__ import annotations

import unittest
from datetime import date

from lending_hub.definitions.provenance import Ungrounded
from lending_hub.reco.feasible import Applicant, Offer, Segment
from lending_hub.reco.suitability import (
    TRANCHING_RULE,
    ActionKind,
    LifecycleAction,
    LifecycleStage,
    Recommendation,
    SuitabilityError,
    SuitabilityVerdict,
    audit,
    lifecycle_action,
    restructuring_terms,
    tranche_release,
)

PERIOD_END = date(2026, 9, 30)


def _agri(borrower="F1", stressed=600_000.0) -> Applicant:
    return Applicant(
        applicant_id=borrower,
        segment=Segment.AGRI,
        annual_cash_flow=900_000.0,
        stressed_annual_cash_flow=stressed,
    )


def _recommendation(
    borrower="F1", *, stage=LifecycleStage.SOWING_CONFIRMED, amount=300_000.0
) -> Recommendation:
    return Recommendation(
        borrower_id=borrower,
        offer=Offer("kcc", amount, 36, 0.09),
        stage=stage,
        recommended_on=date(2026, 9, 1),
    )


class TestDroughtSuppression(unittest.TestCase):
    """The suitability duty, which runs against every commercial signal."""

    def test_a_drought_flag_suppresses_marketing(self):
        action = lifecycle_action("F1", LifecycleStage.DROUGHT_FLAGGED)
        self.assertIs(action.kind, ActionKind.SUPPRESS_MARKETING)

    def test_suppression_carries_a_support_obligation(self):
        """Suppression is not the absence of an offer; it is a positive duty."""
        action = lifecycle_action("F1", LifecycleStage.DROUGHT_FLAGGED)
        self.assertTrue(action.support_required)
        self.assertEqual(action.eligible_products, ())

    def test_suppression_without_support_cannot_be_constructed(self):
        """Otherwise it collapses into 'no offer', which is just silence."""
        with self.assertRaises(SuitabilityError) as ctx:
            LifecycleAction(
                borrower_id="F1",
                stage=LifecycleStage.DROUGHT_FLAGGED,
                kind=ActionKind.SUPPRESS_MARKETING,
                reason="drought",
                support_required=False,
            )
        self.assertIn("just silence", str(ctx.exception))

    def test_the_reason_names_why_the_duty_inverts_the_signal(self):
        action = lifecycle_action("F1", LifecycleStage.DROUGHT_FLAGGED)
        self.assertIn("likely to accept", action.reason)

    def test_the_drought_branch_needs_no_product_configuration(self):
        """It must fire even on a borrower for whom no campaign was configured."""
        action = lifecycle_action(
            "F1", LifecycleStage.DROUGHT_FLAGGED, input_products=(), equipment_products=()
        )
        self.assertIs(action.kind, ActionKind.SUPPRESS_MARKETING)


class TestLifecycleTriggers(unittest.TestCase):
    def test_sowing_opens_input_topup_eligibility(self):
        action = lifecycle_action(
            "F1", LifecycleStage.SOWING_CONFIRMED, input_products=("kcc_topup",)
        )
        self.assertIs(action.kind, ActionKind.OFFER)
        self.assertEqual(action.eligible_products, ("kcc_topup",))

    def test_a_good_harvest_opens_equipment_eligibility(self):
        action = lifecycle_action(
            "F1", LifecycleStage.GOOD_HARVEST, equipment_products=("tractor_loan",)
        )
        self.assertIs(action.kind, ActionKind.OFFER)
        self.assertEqual(action.eligible_products, ("tractor_loan",))

    def test_an_unknown_stage_opens_nothing(self):
        """An unmonitored plot is not a healthy one.

        Defaulting the first to the second markets to exactly the farmers the
        bank cannot see.
        """
        action = lifecycle_action("F1", LifecycleStage.UNKNOWN)
        self.assertIs(action.kind, ActionKind.NO_ACTION)
        self.assertIn("not a healthy one", action.reason)

    def test_a_trigger_with_nothing_to_offer_is_refused(self):
        """A rule that silently does nothing is worse than an absent one."""
        with self.assertRaises(SuitabilityError) as ctx:
            lifecycle_action("F1", LifecycleStage.SOWING_CONFIRMED)
        self.assertIn("silently does nothing", str(ctx.exception))

    def test_an_offer_action_must_name_its_products(self):
        with self.assertRaises(SuitabilityError) as ctx:
            LifecycleAction(
                borrower_id="F1",
                stage=LifecycleStage.SOWING_CONFIRMED,
                kind=ActionKind.OFFER,
                reason="sowing",
            )
        self.assertIn("not a lifecycle rule", str(ctx.exception))

    def test_every_action_carries_a_reason(self):
        with self.assertRaises(SuitabilityError):
            LifecycleAction(
                borrower_id="F1", stage=LifecycleStage.UNKNOWN,
                kind=ActionKind.NO_ACTION, reason="",
            )


class TestRestructuringTerms(unittest.TestCase):
    def test_terms_are_refused(self):
        """A restructuring on invented terms is a variation nobody approved."""
        action = lifecycle_action("F1", LifecycleStage.DROUGHT_FLAGGED)
        with self.assertRaises(Ungrounded) as ctx:
            restructuring_terms(action)
        self.assertIn("LH-506", str(ctx.exception))
        self.assertIn("nobody approved", str(ctx.exception))

    def test_restructuring_does_not_apply_to_a_healthy_borrower(self):
        action = lifecycle_action(
            "F1", LifecycleStage.GOOD_HARVEST, equipment_products=("tractor_loan",)
        )
        with self.assertRaises(SuitabilityError):
            restructuring_terms(action)


class TestAudit(unittest.TestCase):
    def test_an_offer_to_a_drought_flagged_borrower_is_a_finding(self):
        verdict = audit(
            [_recommendation(stage=LifecycleStage.DROUGHT_FLAGGED)],
            {"F1": _agri()},
            period_end=PERIOD_END,
        )
        self.assertFalse(verdict.clean)
        self.assertEqual(verdict.by_check, {"drought_marketing_suppression": 1})

    def test_an_offer_beyond_stressed_affordability_is_a_finding(self):
        """Not against expected affordability — the feasible set covers that.

        This is the stricter question, and an offer can be feasible and fail it.
        """
        verdict = audit(
            [_recommendation(amount=900_000.0)],
            {"F1": _agri(stressed=200_000.0)},
            period_end=PERIOD_END,
        )
        self.assertIn("stressed_affordability", verdict.by_check)

    def test_an_affordable_offer_to_a_healthy_borrower_is_clean(self):
        verdict = audit(
            [_recommendation(amount=200_000.0)],
            {"F1": _agri(stressed=800_000.0)},
            period_end=PERIOD_END,
        )
        self.assertTrue(verdict.clean)
        self.assertEqual(verdict.recommendations_reviewed, 1)

    def test_missing_stressed_income_is_itself_a_finding(self):
        """"Could not test" is not "passed"."""
        applicant = Applicant("F1", Segment.AGRI, stressed_annual_cash_flow=None)
        verdict = audit([_recommendation()], {"F1": applicant}, period_end=PERIOD_END)
        self.assertIn("stressed_affordability", verdict.by_check)
        self.assertIn("could not be tested", verdict.findings[0].detail)

    def test_both_checks_can_fire_on_one_recommendation(self):
        verdict = audit(
            [_recommendation(stage=LifecycleStage.DROUGHT_FLAGGED, amount=900_000.0)],
            {"F1": _agri(stressed=150_000.0)},
            period_end=PERIOD_END,
        )
        self.assertEqual(len(verdict.findings), 2)

    def test_a_recommendation_for_an_unknown_applicant_is_refused(self):
        """An audit that skipped them would report clean on an unreviewed population."""
        with self.assertRaises(SuitabilityError) as ctx:
            audit([_recommendation("GHOST")], {}, period_end=PERIOD_END)
        self.assertIn("did not review", str(ctx.exception))

    def test_an_empty_period_is_clean(self):
        verdict = audit([], {}, period_end=PERIOD_END)
        self.assertTrue(verdict.clean)
        self.assertEqual(verdict.recommendations_reviewed, 0)

    def test_the_audit_refuses_to_sign_itself_off(self):
        """An automated control clearing its own subject.

        §8's "suitability audit clean" would become a claim this module makes
        about itself.
        """
        verdict = audit([], {}, period_end=PERIOD_END)
        with self.assertRaises(SuitabilityError) as ctx:
            verdict.sign_off()
        self.assertIn("about itself", str(ctx.exception))

    def test_retail_borrowers_skip_the_stressed_cash_flow_check(self):
        """FOIR governs retail; there is no StressedIncome for a salaried borrower."""
        retail = Applicant("R1", Segment.RETAIL, verified_monthly_income=90_000.0)
        verdict = audit(
            [_recommendation("R1", amount=300_000.0)], {"R1": retail}, period_end=PERIOD_END
        )
        self.assertTrue(verdict.clean)


class TestTrancheRelease(unittest.TestCase):
    def test_release_is_refused(self):
        """Releasing a guessed fraction disburses money against an unwritten rule."""
        action = lifecycle_action(
            "F1", LifecycleStage.SOWING_CONFIRMED, input_products=("kcc_topup",)
        )
        with self.assertRaises(Ungrounded) as ctx:
            tranche_release(action, 500_000.0)
        self.assertIn("LH-403", str(ctx.exception))
        self.assertIn("nobody wrote", str(ctx.exception))

    def test_a_non_positive_sanction_is_refused_first(self):
        action = lifecycle_action("F1", LifecycleStage.UNKNOWN)
        with self.assertRaises(SuitabilityError):
            tranche_release(action, 0.0)

    def test_the_tranching_placeholder_is_registered(self):
        self.assertEqual(TRANCHING_RULE.ticket, "LH-403")


if __name__ == "__main__":
    unittest.main()

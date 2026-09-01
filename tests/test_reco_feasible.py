"""Feasible-set service — WS-4.B Step 1.

Phase 4 §5 Step 1 asks for "golden-file tests vs. hand-computed examples", and
:class:`TestGoldenEmi` is that: EMI values computed independently from the
annuity formula, checked to the paisa. The rest test the rules built on it and
the refusals that stop a cap being invented.
"""

from __future__ import annotations

import unittest

from lending_hub.definitions.provenance import Ungrounded
from lending_hub.reco.feasible import (
    POLICY_CAPS,
    Applicant,
    Assessment,
    FeasibilityError,
    FeasibleSet,
    Offer,
    PolicyCaps,
    Segment,
    assess,
    build_feasible_set,
    emi,
    total_interest,
)


def _retail_caps(**overrides) -> PolicyCaps:
    base = dict(
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
    base.update(overrides)
    return PolicyCaps(**base)


def _agri_caps(**overrides) -> PolicyCaps:
    base = dict(
        product="kcc",
        segment=Segment.AGRI,
        foir_cap=None,
        dscr_floor=1.25,
        ltv_cap=None,
        max_tenor_months=36,
        min_amount=25_000.0,
        max_amount=800_000.0,
        ratification_reference="CP-2026-12",
    )
    base.update(overrides)
    return PolicyCaps(**base)


def _retail(**overrides) -> Applicant:
    base = dict(
        applicant_id="C1",
        segment=Segment.RETAIL,
        verified_monthly_income=80_000.0,
        existing_monthly_obligations=10_000.0,
    )
    base.update(overrides)
    return Applicant(**base)


def _agri(**overrides) -> Applicant:
    base = dict(
        applicant_id="F1",
        segment=Segment.AGRI,
        annual_cash_flow=600_000.0,
        stressed_annual_cash_flow=420_000.0,
    )
    base.update(overrides)
    return Applicant(**base)


class TestGoldenEmi(unittest.TestCase):
    """Hand-computed EMI values — the golden file §5 Step 1 asks for.

    Each expected value is the annuity formula evaluated independently in
    28-digit ``decimal`` arithmetic — ``a·r(1+r)^n / ((1+r)^n − 1)`` with ``r``
    the monthly rate — and rounded to the paisa an instalment is quoted in.

    Computing them independently earned its keep: three of the six values in the
    first draft of this file were wrong by a few paise, and the implementation
    was right in every case. A golden file transcribed from the code it tests
    proves only that the code is self-consistent.
    """

    GOLDEN = [
        # (principal, annual rate, months, expected EMI)
        (500_000.00, 0.12, 60, 11_122.22),
        (100_000.00, 0.10, 12, 8_791.59),
        (1_000_000.00, 0.085, 240, 8_678.23),
        (250_000.00, 0.18, 36, 9_038.10),
        (50_000.00, 0.24, 6, 8_926.29),
        (2_000_000.00, 0.0725, 300, 14_456.14),
    ]

    def test_hand_computed_examples(self):
        for principal, rate, months, expected in self.GOLDEN:
            self.assertAlmostEqual(
                emi(principal, rate, months),
                expected,
                places=2,
                msg=f"{principal} at {rate:.2%} over {months}m",
            )

    def test_a_zero_rate_is_the_straight_line_limit(self):
        """The formula's singularity is arithmetic; an interest-free EMI is real."""
        self.assertAlmostEqual(emi(120_000.0, 0.0, 12), 10_000.0, places=9)

    def test_emi_times_tenor_exceeds_principal(self):
        for principal, rate, months, _ in self.GOLDEN:
            if rate > 0:
                self.assertGreater(emi(principal, rate, months) * months, principal)

    def test_a_longer_tenor_lowers_the_instalment_and_raises_the_cost(self):
        """The trade a recommendation engine will reach for first."""
        short = emi(500_000.0, 0.12, 24)
        long = emi(500_000.0, 0.12, 60)
        self.assertLess(long, short)
        self.assertGreater(
            total_interest(500_000.0, 0.12, 60), total_interest(500_000.0, 0.12, 24)
        )

    def test_emi_scales_linearly_in_principal(self):
        self.assertAlmostEqual(
            emi(1_000_000.0, 0.12, 60), 2 * emi(500_000.0, 0.12, 60), places=6
        )

    def test_a_negative_rate_is_a_data_error_not_a_price(self):
        """It produces an EMI below straight-line, which passes every test."""
        with self.assertRaises(FeasibilityError) as ctx:
            emi(100_000.0, -0.05, 12)
        self.assertIn("data error", str(ctx.exception))

    def test_degenerate_inputs_are_refused(self):
        for kwargs in (
            {"principal": 0.0, "annual_rate": 0.12, "months": 12},
            {"principal": 100_000.0, "annual_rate": 0.12, "months": 0},
        ):
            with self.assertRaises(FeasibilityError):
                emi(**kwargs)


class TestPolicyCaps(unittest.TestCase):
    def test_caps_need_a_ratification_reference(self):
        """Phase 4 §9 do-not-invent, and the 1.25 in §5 Step 1 is an illustration."""
        with self.assertRaises(FeasibilityError) as ctx:
            _retail_caps(ratification_reference="")
        self.assertIn("LH-504", str(ctx.exception))
        self.assertIn("worked formula", str(ctx.exception))

    def test_a_retail_product_needs_a_foir_cap(self):
        with self.assertRaises(FeasibilityError):
            _retail_caps(foir_cap=None)

    def test_an_agri_product_needs_a_dscr_floor(self):
        with self.assertRaises(FeasibilityError):
            _agri_caps(dscr_floor=None)

    def test_a_foir_cap_above_one_is_refused(self):
        """It commits more than the borrower earns."""
        with self.assertRaises(FeasibilityError) as ctx:
            _retail_caps(foir_cap=1.4)
        self.assertIn("more than the borrower earns", str(ctx.exception))

    def test_a_dscr_floor_below_one_is_refused(self):
        """It permits lending where cash flow misses debt service unstressed."""
        with self.assertRaises(FeasibilityError) as ctx:
            _agri_caps(dscr_floor=0.9)
        self.assertIn("before any stress", str(ctx.exception))

    def test_an_empty_amount_range_is_refused(self):
        with self.assertRaises(FeasibilityError):
            _retail_caps(min_amount=500_000.0, max_amount=100_000.0)

    def test_the_caps_placeholder_is_registered(self):
        self.assertEqual(POLICY_CAPS.ticket, "LH-504")
        with self.assertRaises(Ungrounded):
            POLICY_CAPS.value


class TestRetailFoir(unittest.TestCase):
    def test_an_affordable_offer_passes(self):
        """Hand-checked: EMI 11,122.22 + 10,000 = 21,122.22 vs cap 40,000."""
        assessment = assess(_retail(), Offer("personal_loan", 500_000.0, 60, 0.12), _retail_caps())
        self.assertTrue(assessment.feasible)
        foir = next(c for c in assessment.constraints if c.name == "foir")
        self.assertAlmostEqual(foir.value, 21_122.22, places=2)
        self.assertAlmostEqual(foir.limit, 40_000.0, places=2)

    def test_an_unaffordable_offer_fails_on_foir(self):
        applicant = _retail(verified_monthly_income=30_000.0)
        assessment = assess(applicant, Offer("personal_loan", 900_000.0, 60, 0.12), _retail_caps())
        self.assertFalse(assessment.feasible)
        self.assertEqual(assessment.binding_constraint.name, "foir")

    def test_existing_obligations_count_against_the_cap(self):
        light = _retail(existing_monthly_obligations=0.0)
        heavy = _retail(existing_monthly_obligations=28_000.0)
        offer = Offer("personal_loan", 700_000.0, 60, 0.12)
        self.assertTrue(assess(light, offer, _retail_caps()).feasible)
        self.assertFalse(assess(heavy, offer, _retail_caps()).feasible)

    def test_absent_income_is_not_zero_income(self):
        """It is an application that cannot be assessed."""
        with self.assertRaises(FeasibilityError) as ctx:
            assess(
                _retail(verified_monthly_income=None),
                Offer("personal_loan", 500_000.0, 60, 0.12),
                _retail_caps(),
            )
        self.assertIn("cannot be assessed", str(ctx.exception))


class TestAgriDscr(unittest.TestCase):
    def test_dscr_uses_stressed_cash_flow(self):
        """§5 Step 1: DSCR is on StressedIncome from P2.

        Expected income would size the loan on a good harvest — the failure mode
        agri lending is known for.
        """
        applicant = _agri(annual_cash_flow=900_000.0, stressed_annual_cash_flow=420_000.0)
        offer = Offer("kcc", 500_000.0, 36, 0.09)
        assessment = assess(applicant, offer, _agri_caps())
        dscr = next(c for c in assessment.constraints if c.name == "dscr")

        expected = 420_000.0 / (offer.emi * 12.0)
        self.assertAlmostEqual(dscr.value, expected, places=9)
        self.assertNotAlmostEqual(dscr.value, 900_000.0 / (offer.emi * 12.0), places=3)

    def test_a_thin_dscr_fails(self):
        applicant = _agri(stressed_annual_cash_flow=180_000.0)
        assessment = assess(applicant, Offer("kcc", 500_000.0, 36, 0.09), _agri_caps())
        self.assertFalse(assessment.feasible)
        self.assertEqual(assessment.binding_constraint.name, "dscr")

    def test_missing_stressed_income_is_refused(self):
        with self.assertRaises(FeasibilityError) as ctx:
            assess(
                _agri(stressed_annual_cash_flow=None),
                Offer("kcc", 300_000.0, 36, 0.09),
                _agri_caps(),
            )
        self.assertIn("good harvest", str(ctx.exception))

    def test_a_retail_cap_set_cannot_assess_an_agri_borrower(self):
        """It divides seasonal cash flow by a monthly income that does not exist."""
        with self.assertRaises(FeasibilityError) as ctx:
            assess(_agri(), Offer("personal_loan", 300_000.0, 36, 0.12), _retail_caps())
        self.assertIn("does not exist", str(ctx.exception))

    def test_the_segments_use_different_rules(self):
        self.assertFalse(Segment.RETAIL.uses_dscr)
        self.assertTrue(Segment.AGRI.uses_dscr)
        self.assertTrue(Segment.MSME.uses_dscr)


class TestLtvAndLimits(unittest.TestCase):
    def test_ltv_is_checked_when_the_product_carries_a_cap(self):
        caps = _retail_caps(product="home_loan", ltv_cap=0.80, max_amount=10_000_000.0)
        applicant = _retail(verified_monthly_income=300_000.0, collateral_value=5_000_000.0)
        within = assess(applicant, Offer("home_loan", 4_000_000.0, 60, 0.085), caps)
        beyond = assess(applicant, Offer("home_loan", 4_500_000.0, 60, 0.085), caps)
        self.assertTrue(within.feasible)
        self.assertFalse(beyond.feasible)
        self.assertEqual(beyond.binding_constraint.name, "ltv")

    def test_a_missing_valuation_on_a_secured_product_is_refused(self):
        """Not an unsecured loan — a secured one whose security is unvalued."""
        caps = _retail_caps(ltv_cap=0.80)
        with self.assertRaises(FeasibilityError) as ctx:
            assess(_retail(collateral_value=None), Offer("personal_loan", 400_000.0, 60, 0.12), caps)
        self.assertIn("has not been valued", str(ctx.exception))

    def test_tenor_beyond_the_cap_fails(self):
        assessment = assess(_retail(), Offer("personal_loan", 300_000.0, 84, 0.12), _retail_caps())
        self.assertFalse(assessment.feasible)
        self.assertEqual(assessment.binding_constraint.name, "tenor")

    def test_an_amount_below_the_minimum_fails(self):
        assessment = assess(_retail(), Offer("personal_loan", 20_000.0, 24, 0.12), _retail_caps())
        self.assertFalse(assessment.feasible)
        self.assertEqual(assessment.binding_constraint.name, "amount_min")

    def test_all_constraints_are_evaluated_even_after_one_fails(self):
        """Fixing the amount then discovering the tenor cap wastes a conversation."""
        assessment = assess(
            _retail(verified_monthly_income=20_000.0),
            Offer("personal_loan", 2_000_000.0, 120, 0.12),
            _retail_caps(),
        )
        failed = {c.name for c in assessment.constraints if not c.satisfied}
        self.assertIn("foir", failed)
        self.assertIn("tenor", failed)
        self.assertIn("amount_max", failed)


class TestFeasibleSet(unittest.TestCase):
    def _set(self, amounts=(200_000.0, 500_000.0, 950_000.0)) -> FeasibleSet:
        offers = [Offer("personal_loan", a, 60, 0.12) for a in amounts]
        return build_feasible_set(_retail(), offers, {"personal_loan": _retail_caps()})

    def test_feasible_and_rejected_are_both_available(self):
        """A set that discarded rejects cannot answer "why was this arm unavailable"."""
        feasible_set = self._set(amounts=(200_000.0, 5_000_000.0))
        self.assertEqual(len(feasible_set.feasible), 1)
        self.assertEqual(len(feasible_set.rejected), 1)

    def test_contains_is_the_bandits_safety_check(self):
        """§5 Step 4: exploration can never breach affordability or policy."""
        feasible_set = self._set()
        allowed = Offer("personal_loan", 200_000.0, 60, 0.12)
        blocked = Offer("personal_loan", 5_000_000.0, 60, 0.12)
        self.assertTrue(feasible_set.contains(allowed))
        self.assertFalse(feasible_set.contains(blocked))

    def test_an_unassessed_offer_is_not_a_rejected_one(self):
        with self.assertRaises(FeasibilityError) as ctx:
            self._set().reason_for(Offer("gold_loan", 100_000.0, 12, 0.10))
        self.assertIn("never assessed", str(ctx.exception))

    def test_largest_feasible_is_named_plainly(self):
        """LH-509: a take-up-only bandit converges here, so make it visible."""
        largest = self._set().largest_feasible
        self.assertEqual(largest.amount, 950_000.0)

    def test_largest_feasible_is_none_when_nothing_qualifies(self):
        feasible_set = build_feasible_set(
            _retail(verified_monthly_income=15_000.0),
            [Offer("personal_loan", 900_000.0, 60, 0.12)],
            {"personal_loan": _retail_caps()},
        )
        self.assertTrue(feasible_set.is_empty)
        self.assertIsNone(feasible_set.largest_feasible)

    def test_an_unconfigured_product_cannot_fall_back_to_other_caps(self):
        with self.assertRaises(Ungrounded) as ctx:
            build_feasible_set(
                _retail(), [Offer("gold_loan", 100_000.0, 12, 0.10)],
                {"personal_loan": _retail_caps()},
            )
        self.assertIn("LH-504", str(ctx.exception))

    def test_an_empty_candidate_list_is_refused(self):
        """Indistinguishable from a borrower who qualifies for nothing."""
        with self.assertRaises(FeasibilityError) as ctx:
            build_feasible_set(_retail(), [], {"personal_loan": _retail_caps()})
        self.assertIn("qualifies for nothing", str(ctx.exception))

    def test_every_assessment_names_its_binding_constraint(self):
        for assessment in self._set(amounts=(200_000.0, 5_000_000.0)).assessments:
            self.assertIsNotNone(assessment.binding_constraint)
            self.assertTrue(assessment.reason)


if __name__ == "__main__":
    unittest.main()

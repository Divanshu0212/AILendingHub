"""Risk-based pricing — WS-4.B Step 2.

Phase 4 §5 Step 2 puts "**never hard-coded**" in bold, and that emphasis is
about time rather than tidiness: ALM components move monthly, so a pricing
service reading a constant is wrong within a quarter even if the constant was
right when written. Most of these tests are about that failure and the ceiling
behaviour, which is a conduct control rather than a clamp.
"""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from lending_hub.definitions.provenance import Ungrounded
from lending_hub.reco.pricing import (
    ALM_COMPONENTS,
    MAX_ALM_TABLE_AGE_DAYS,
    RATE_BOUNDS,
    AlmTable,
    ExpectedLoss,
    PricedOffer,
    PricingError,
    load_alm_table,
    price,
)

TODAY = date(2026, 9, 1)


def _table(**overrides) -> AlmTable:
    base = dict(
        product="personal_loan",
        effective_from=date(2026, 8, 1),
        cost_of_funds=0.065,
        opex_allocation=0.018,
        capital_charge=0.011,
        hurdle_margin=0.020,
        rate_floor=0.09,
        rate_ceiling=0.24,
        source_reference="ALCO-2026-08",
    )
    base.update(overrides)
    return AlmTable(**base)


def _loss(**overrides) -> ExpectedLoss:
    base = dict(
        pd=0.04,
        lgd=0.55,
        ead_fraction=1.0,
        pd_source="P1 application champion v1.2",
        lgd_source="P3 LGD stage 2",
    )
    base.update(overrides)
    return ExpectedLoss(**base)


class TestAlmTable(unittest.TestCase):
    def test_a_table_must_name_its_source(self):
        """Without it nobody auditing a rate can tell which table priced it."""
        with self.assertRaises(PricingError) as ctx:
            _table(source_reference="")
        self.assertIn("LH-505", str(ctx.exception))

    def test_a_component_in_percent_rather_than_decimal_is_refused(self):
        """A table populated in percent prices every loan a hundred times over."""
        with self.assertRaises(PricingError) as ctx:
            _table(cost_of_funds=6.5)
        self.assertIn("hundred times over", str(ctx.exception))

    def test_a_negative_component_is_refused(self):
        with self.assertRaises(PricingError) as ctx:
            _table(opex_allocation=-0.01)
        self.assertIn("subsidises the rate", str(ctx.exception))

    def test_a_floor_above_the_ceiling_is_refused(self):
        with self.assertRaises(PricingError) as ctx:
            _table(rate_floor=0.30, rate_ceiling=0.24)
        self.assertIn("no rate is permissible", str(ctx.exception))

    def test_the_base_rate_excludes_expected_loss(self):
        self.assertAlmostEqual(_table().base_rate, 0.065 + 0.018 + 0.011 + 0.020, places=12)

    def test_the_placeholders_are_registered(self):
        self.assertEqual(ALM_COMPONENTS.ticket, "LH-505")
        self.assertEqual(RATE_BOUNDS.ticket, "LH-505")
        with self.assertRaises(Ungrounded):
            ALM_COMPONENTS.value


class TestStaleTables(unittest.TestCase):
    """The failure "never hard-coded" is really about."""

    def test_a_current_table_prices(self):
        offer = price(_table(), _loss(), as_of=TODAY)
        self.assertAlmostEqual(offer.computed_rate, 0.136, places=9)

    def test_a_stale_table_is_refused(self):
        """It produces plausible rates indefinitely from last year's funding."""
        stale = _table(effective_from=TODAY - timedelta(days=400))
        with self.assertRaises(PricingError) as ctx:
            price(stale, _loss(), as_of=TODAY)
        self.assertIn("different funding environment", str(ctx.exception))

    def test_a_table_at_the_age_limit_still_prices(self):
        table = _table(effective_from=TODAY - timedelta(days=MAX_ALM_TABLE_AGE_DAYS))
        self.assertIsInstance(price(table, _loss(), as_of=TODAY), PricedOffer)

    def test_a_future_table_is_refused(self):
        """Pricing against it quotes a rate that was not in force."""
        future = _table(effective_from=TODAY + timedelta(days=10))
        with self.assertRaises(PricingError) as ctx:
            price(future, _loss(), as_of=TODAY)
        self.assertIn("not in force", str(ctx.exception))

    def test_the_age_limit_is_the_documented_one(self):
        self.assertEqual(MAX_ALM_TABLE_AGE_DAYS, 92)


class TestExpectedLoss(unittest.TestCase):
    def test_the_product_is_pd_times_lgd_times_ead(self):
        self.assertAlmostEqual(_loss().rate, 0.04 * 0.55 * 1.0, places=12)

    def test_each_component_must_name_its_source(self):
        """P1 and P3 produce these against different populations.

        A rate built from a mismatched pair is not risk-based; it is two
        models' outputs multiplied together.
        """
        with self.assertRaises(PricingError) as ctx:
            _loss(lgd_source="")
        self.assertIn("multiplied together", str(ctx.exception))

    def test_probabilities_outside_the_unit_interval_are_refused(self):
        for kwargs in ({"pd": 1.4}, {"lgd": -0.1}):
            with self.assertRaises(PricingError):
                _loss(**kwargs)

    def test_a_zero_ead_prices_the_loss_out_of_existence(self):
        with self.assertRaises(PricingError) as ctx:
            _loss(ead_fraction=0.0)
        self.assertIn("out of existence", str(ctx.exception))

    def test_a_riskier_borrower_prices_higher(self):
        safe = price(_table(), _loss(pd=0.01), as_of=TODAY)
        risky = price(_table(), _loss(pd=0.12), as_of=TODAY)
        self.assertGreater(risky.computed_rate, safe.computed_rate)


class TestFloorsAndCeilings(unittest.TestCase):
    def test_a_rate_below_the_floor_is_lifted_to_it(self):
        """A floor is a minimum the bank charges, not a claim about the borrower."""
        cheap = _table(cost_of_funds=0.02, opex_allocation=0.005,
                       capital_charge=0.002, hurdle_margin=0.005, rate_floor=0.09)
        offer = price(cheap, _loss(pd=0.001, lgd=0.2), as_of=TODAY)
        self.assertTrue(offer.below_floor)
        self.assertAlmostEqual(offer.offerable_rate, 0.09, places=12)

    def test_a_rate_above_the_ceiling_is_a_decline_not_a_clamp(self):
        """Clamping produces a mis-priced loan AND a fair-lending pattern.

        A cluster of customers all priced identically at the cap is what a
        regulator looks for.
        """
        offer = price(_table(), _loss(pd=0.45, lgd=0.9), as_of=TODAY)
        self.assertTrue(offer.exceeds_ceiling)
        with self.assertRaises(PricingError) as ctx:
            offer.offerable_rate
        self.assertIn("must be declined", str(ctx.exception))
        self.assertIn("priced identically at the cap", str(ctx.exception))

    def test_a_rate_inside_the_bounds_is_quoted_as_computed(self):
        offer = price(_table(), _loss(), as_of=TODAY)
        self.assertFalse(offer.below_floor)
        self.assertFalse(offer.exceeds_ceiling)
        self.assertAlmostEqual(offer.offerable_rate, offer.computed_rate, places=12)

    def test_an_unbounded_product_quotes_the_computed_rate(self):
        table = _table(rate_floor=None, rate_ceiling=None)
        offer = price(table, _loss(pd=0.45, lgd=0.9), as_of=TODAY)
        self.assertFalse(offer.exceeds_ceiling)
        self.assertAlmostEqual(offer.offerable_rate, offer.computed_rate, places=12)


class TestDecomposition(unittest.TestCase):
    def test_the_breakdown_sums_to_the_rate(self):
        """A rate that cannot be decomposed cannot be explained or reconciled."""
        offer = price(_table(), _loss(), as_of=TODAY)
        breakdown = offer.breakdown
        components = sum(
            breakdown[k]
            for k in (
                "cost_of_funds", "opex_allocation", "capital_charge",
                "hurdle_margin", "expected_loss",
            )
        )
        self.assertAlmostEqual(components, breakdown["computed_rate"], places=12)

    def test_the_risk_share_says_whether_pricing_is_really_risk_based(self):
        """If it is a fraction of a percent, the model decorates a flat sheet."""
        offer = price(_table(), _loss(), as_of=TODAY)
        self.assertAlmostEqual(offer.risk_share, 0.022 / 0.136, places=9)

        decorative = price(_table(), _loss(pd=0.0001, lgd=0.1), as_of=TODAY)
        self.assertLess(decorative.risk_share, 0.001)

    def test_the_alm_reference_travels_with_the_price(self):
        offer = price(_table(), _loss(), as_of=TODAY)
        self.assertEqual(offer.alm_reference, "ALCO-2026-08")
        self.assertEqual(offer.priced_on, TODAY)

    def test_a_non_positive_rate_cannot_be_decomposed(self):
        offer = PricedOffer(
            product="p", priced_on=TODAY, alm_reference="r",
            cost_of_funds=0.0, opex_allocation=0.0, capital_charge=0.0,
            hurdle_margin=0.0, expected_loss=0.0, rate_floor=None, rate_ceiling=None,
        )
        with self.assertRaises(PricingError):
            offer.risk_share


class TestTableLookup(unittest.TestCase):
    def test_a_configured_product_resolves(self):
        table = _table()
        self.assertIs(load_alm_table("personal_loan", {"personal_loan": table}), table)

    def test_an_unconfigured_product_cannot_borrow_another_table(self):
        """Products are funded differently; the error direction is unpredictable."""
        with self.assertRaises(Ungrounded) as ctx:
            load_alm_table("gold_loan", {"personal_loan": _table()})
        self.assertIn("LH-505", str(ctx.exception))
        self.assertIn("funded differently", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

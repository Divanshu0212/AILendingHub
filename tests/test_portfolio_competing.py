"""WS-3.1 Step 4 — competing risks: prepayment against default."""

import math
import random
import unittest
from datetime import date

from lending_hub.portfolio import competing as CR
from lending_hub.portfolio.panel import (
    AccountMonth,
    Event,
    Panel,
    Spell,
    month_end,
)
from lending_hub.scoring.gbm import MonotoneConstraints


def me(y, m):
    return month_end(date(y, m, 1))


def simulate(n=1200, seed=9, follow=60, default_base=0.003, prepay_base=0.02):
    """Quality q raises default and lowers prepayment — the real pattern."""
    rng = random.Random(seed)
    spells = []
    for i in range(n):
        q = rng.random()
        h_d = default_base * math.exp(2.0 * q)
        h_p = prepay_base * math.exp(-1.5 * q)
        months, event, at = [], None, None
        for m in range(follow):
            months.append(AccountMonth(
                f"A{i}", me(2007 + m // 12, m % 12 + 1), m, 0, features={"q": q}))
            u = rng.random()
            if u < h_d:
                event, at = Event.DEFAULT, months[-1].snapshot
                break
            if u < h_d + h_p:
                event, at = Event.PREPAID, months[-1].snapshot
                break
        spells.append(Spell(f"A{i}", months, event, at))
    return Panel(spells, date(2012, 12, 31))


class ObservedIncidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = simulate()
        cls.incidence = CR.observed_incidence(cls.panel, horizon=60)

    def test_decomposition_is_exhaustive(self):
        """S(t) + CIF_default(t) + CIF_prepay(t) == 1 at every horizon."""
        self.assertTrue(self.incidence.closes(1e-9))

    def test_treating_prepayment_as_censoring_overstates_default(self):
        self.assertGreater(self.incidence.naive_at(60), self.incidence.default_at(60))
        self.assertGreater(self.incidence.overstatement_at(60), 0.0)

    def test_overstatement_grows_with_the_horizon(self):
        """The longer the horizon, the more chance the account left first."""
        short = self.incidence.overstatement_at(12)
        long = self.incidence.overstatement_at(60)
        self.assertGreater(long, short)

    def test_incidence_functions_are_non_decreasing(self):
        for series in (self.incidence.default, self.incidence.prepay):
            self.assertTrue(all(a <= b + 1e-12 for a, b in zip(series, series[1:])))

    def test_event_free_survival_is_non_increasing(self):
        s = self.incidence.event_free
        self.assertTrue(all(a >= b - 1e-12 for a, b in zip(s, s[1:])))

    def test_all_curves_are_probabilities(self):
        for series in (self.incidence.default, self.incidence.prepay,
                       self.incidence.event_free, self.incidence.naive_default):
            self.assertTrue(all(0.0 <= v <= 1.0 for v in series))

    def test_incidence_at_zero_is_zero(self):
        self.assertEqual(self.incidence.default_at(0), 0.0)

    def test_asking_past_the_horizon_raises(self):
        with self.assertRaises(CR.CompetingRisksError):
            self.incidence.default_at(61)

    def test_zero_horizon_rejected(self):
        with self.assertRaises(CR.CompetingRisksError):
            CR.observed_incidence(self.panel, horizon=0)

    def test_without_prepayment_the_naive_curve_matches_the_cif(self):
        panel = simulate(n=400, prepay_base=0.0, seed=2)
        incidence = CR.observed_incidence(panel, horizon=40)
        self.assertAlmostEqual(
            incidence.overstatement_at(40), 0.0, places=9)


class FittedCompetingRisksTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        panel = simulate(n=900, seed=13)
        rows = panel.hazard()
        constraints = MonotoneConstraints.for_experiment(["q"], reason="unit test")
        cls.model = CR.fit_competing_risks(
            rows, ["q"], constraints, n_trees=30, max_depth=3, learning_rate=0.15)

    def test_both_causes_are_fitted(self):
        self.assertEqual(self.model.default.cause, "default")
        self.assertEqual(self.model.prepay.cause, "prepay")

    def test_recovers_the_opposing_directions(self):
        """Quality raises default and lowers prepayment."""
        h_d_low, h_p_low, _ = self.model.hazards({"q": 0.1}, 12)
        h_d_high, h_p_high, _ = self.model.hazards({"q": 0.9}, 12)
        self.assertGreater(h_d_high, h_d_low)
        self.assertLess(h_p_high, h_p_low)

    def test_hazards_are_renormalised_if_they_exceed_one(self):
        class Saturated:
            cause = "x"
            promotable = (True, "")
            def hazard(self, covariates, month):
                return 0.8
        model = CR.CompetingRisks(default=Saturated(), prepay=Saturated())
        h_d, h_p, scaled = model.hazards({}, 1)
        self.assertTrue(scaled)
        self.assertAlmostEqual(h_d + h_p, 1.0, places=12)

    def test_fitted_incidence_closes(self):
        incidence = self.model.incidence({"q": 0.5}, from_month=0, horizon=36)
        self.assertTrue(incidence.closes(1e-9))

    def test_fitted_naive_curve_still_overstates(self):
        incidence = self.model.incidence({"q": 0.5}, from_month=0, horizon=36)
        self.assertGreaterEqual(incidence.overstatement_at(36), 0.0)

    def test_renormalisation_count_is_reported(self):
        incidence = self.model.incidence({"q": 0.5}, from_month=0, horizon=36)
        self.assertIn("months_with_hazards_renormalised", incidence.to_dict())

    def test_promotable_names_the_blocking_cause(self):
        ok, why = self.model.promotable
        self.assertFalse(ok)
        self.assertTrue(why.startswith("default hazard:"))

    def test_zero_horizon_rejected(self):
        with self.assertRaises(CR.CompetingRisksError):
            self.model.incidence({"q": 0.5}, from_month=0, horizon=0)


class SubdistributionTests(unittest.TestCase):
    def test_competing_event_accounts_stay_in_the_risk_set(self):
        months = [AccountMonth("A", me(2007, m), m - 1, 0) for m in range(1, 7)]
        panel = Panel([Spell("A", months, Event.PREPAID, me(2007, 6))], me(2007, 6))
        rows = CR.subdistribution_rows(panel, cause="default", horizon=24)
        self.assertEqual(len(rows), 24)
        self.assertTrue(all(r.cause != "default" for r in rows))

    def test_cause_of_interest_leaves_the_risk_set_at_its_event(self):
        months = [AccountMonth("A", me(2007, m), m - 1, 0) for m in range(1, 7)]
        panel = Panel([Spell("A", months, Event.DEFAULT, me(2007, 6))], me(2007, 6))
        rows = CR.subdistribution_rows(panel, cause="default", horizon=24)
        self.assertEqual(len(rows), 6)
        self.assertEqual(sum(r.defaulted for r in rows), 1)

    def test_non_administrative_censoring_is_refused_not_ignored(self):
        months = [AccountMonth("A", me(2007, m), m - 1, 0) for m in range(1, 7)]
        panel = Panel([Spell("A", months)], me(2009, 12))
        with self.assertRaises(CR.CompetingRisksError) as ctx:
            CR.subdistribution_rows(panel, cause="default", horizon=24)
        self.assertIn("weights", str(ctx.exception))

    def test_unknown_cause_rejected(self):
        panel = Panel([], me(2007, 6))
        with self.assertRaises(CR.CompetingRisksError):
            CR.subdistribution_rows(panel, cause="fraud", horizon=12)

    def test_zero_horizon_rejected(self):
        panel = Panel([], me(2007, 6))
        with self.assertRaises(CR.CompetingRisksError):
            CR.subdistribution_rows(panel, cause="default", horizon=0)


if __name__ == "__main__":
    unittest.main()

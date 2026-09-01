"""WS-3.1 Step 3 — the discrete-time hazard challenger.

Asserts the recasting and the survival reconstruction, not the boosting: that
is `lending_hub.scoring.gbm`, tested in test_scoring_gbm.py, and there is one
implementation of it in this repo.
"""

import math
import random
import unittest
from datetime import date

from lending_hub.portfolio import hazard as H
from lending_hub.portfolio.panel import (
    AccountMonth,
    Event,
    Panel,
    Spell,
    month_end,
)
from lending_hub.scoring.gbm import (
    DECREASING,
    INCREASING,
    UNCONSTRAINED,
    GBMError,
    MonotoneConstraints,
)


def me(y, m):
    return month_end(date(y, m, 1))


def simulate_panel(n=900, effect=2.0, base=0.004, seed=4, follow=48):
    rng = random.Random(seed)
    spells = []
    for i in range(n):
        util = rng.random()
        rate = base * math.exp(effect * util)
        months, event_at = [], None
        for m in range(follow):
            months.append(AccountMonth(
                f"A{i}", me(2007 + m // 12, m % 12 + 1), m, 0, features={"util": util}))
            if rng.random() < rate:
                event_at = months[-1].snapshot
                break
        spells.append(Spell(
            f"A{i}", months,
            Event.DEFAULT if event_at else None,
            event_at,
        ))
    return Panel(spells, date(2013, 12, 31))


def experiment_constraints(features):
    return MonotoneConstraints.for_experiment(features, reason="unit test")


class DesignTests(unittest.TestCase):
    def setUp(self):
        months = [AccountMonth("A", me(2007, m), m - 1, 0, features={"u": 0.4})
                  for m in range(1, 7)]
        self.rows = Panel([Spell("A", months, Event.DEFAULT, me(2007, 6))],
                          date(2009, 12, 31)).hazard()

    def test_time_axis_is_added_to_every_row(self):
        design, _ = H.hazard_design(self.rows, ["u"])
        self.assertEqual([r[H.TIME_FEATURE] for r in design], list(range(6)))

    def test_only_the_event_month_is_positive(self):
        _, labels = H.hazard_design(self.rows, ["u"])
        self.assertEqual(labels, [0, 0, 0, 0, 0, 1])

    def test_listing_the_time_feature_twice_is_rejected(self):
        with self.assertRaises(H.HazardError) as ctx:
            H.hazard_design(self.rows, ["u", H.TIME_FEATURE])
        self.assertIn("twice", str(ctx.exception))

    def test_competing_cause_rows_stay_in_the_sample_with_target_zero(self):
        months = [AccountMonth("B", me(2007, m), m - 1, 0) for m in range(1, 7)]
        rows = Panel([Spell("B", months, Event.PREPAID, me(2007, 6))],
                     date(2009, 12, 31)).hazard()
        design, labels = H.hazard_design(rows, [])
        self.assertEqual(len(design), 6)
        self.assertEqual(sum(labels), 0)

    def test_cause_selects_the_target(self):
        months = [AccountMonth("B", me(2007, m), m - 1, 0) for m in range(1, 7)]
        rows = Panel([Spell("B", months, Event.PREPAID, me(2007, 6))],
                     date(2009, 12, 31)).hazard()
        _, labels = H.hazard_design(rows, [], cause="prepay")
        self.assertEqual(sum(labels), 1)


class TimeAxisConstraintTests(unittest.TestCase):
    def test_time_axis_is_added_as_an_explicit_decision(self):
        base = experiment_constraints(["u"])
        extended = H.with_time_axis(base)
        self.assertEqual(extended.direction(H.TIME_FEATURE), UNCONSTRAINED)
        self.assertIn("unconstrained by construction", extended.provenance)

    def test_ratified_status_is_carried_through_not_granted(self):
        unratified = H.with_time_axis(experiment_constraints(["u"]))
        self.assertFalse(unratified.ratified)
        ratified = H.with_time_axis(MonotoneConstraints.from_policy(
            {"u": DECREASING}, decision_reference="CRC-2026-14"))
        self.assertTrue(ratified.ratified)

    def test_constraining_the_baseline_is_refused(self):
        constrained = MonotoneConstraints.from_policy(
            {"u": DECREASING, H.TIME_FEATURE: INCREASING},
            decision_reference="CRC-2026-14")
        with self.assertRaises(H.HazardError) as ctx:
            H.with_time_axis(constrained)
        self.assertIn("not monotone", str(ctx.exception))

    def test_already_unconstrained_time_axis_passes_through(self):
        c = MonotoneConstraints.from_policy(
            {"u": DECREASING, H.TIME_FEATURE: UNCONSTRAINED},
            decision_reference="CRC-2026-14")
        self.assertIs(H.with_time_axis(c), c)


class FitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = simulate_panel()
        cls.rows = cls.panel.hazard()
        cls.model = H.fit_hazard(
            cls.rows, ["util"], experiment_constraints(["util"]),
            n_trees=40, max_depth=3, learning_rate=0.15)

    def test_recovers_the_direction_of_the_generating_effect(self):
        low = self.model.hazard({"util": 0.1}, 12)
        high = self.model.hazard({"util": 0.9}, 12)
        self.assertGreater(high, low)

    def test_hazards_are_probabilities(self):
        for util in (0.0, 0.5, 1.0):
            for m in (1, 12, 36):
                h = self.model.hazard({"util": util}, m)
                self.assertTrue(0.0 <= h <= 1.0)

    def test_empty_risk_set_rejected(self):
        with self.assertRaises(H.HazardError):
            H.fit_hazard([], ["util"], experiment_constraints(["util"]))

    def test_no_events_rejected_rather_than_fitted(self):
        months = [AccountMonth("A", me(2007, m), m - 1, 0, features={"util": 0.5})
                  for m in range(1, 7)]
        rows = Panel([Spell("A", months)], date(2009, 12, 31)).hazard()
        with self.assertRaises(H.HazardError) as ctx:
            H.fit_hazard(rows, ["util"], experiment_constraints(["util"]))
        self.assertIn("no 'default' events", str(ctx.exception))

    def test_missing_direction_for_a_named_feature_is_reported(self):
        with self.assertRaises(H.HazardError):
            H.fit_hazard(self.rows, ["util"],
                         MonotoneConstraints.for_experiment([], reason="unit test"))

    def test_unratified_constraints_cite_the_behavioural_ticket(self):
        ok, why = self.model.promotable
        self.assertFalse(ok)
        self.assertIn("LH-310", why)
        self.assertIn("LH-202", why)

    def test_summary_reports_the_event_rate_per_account_month(self):
        summary = self.model.to_dict()
        self.assertEqual(summary["cause"], "default")
        self.assertIn(H.TIME_FEATURE, summary["features"])
        self.assertAlmostEqual(
            summary["event_rate_per_account_month"],
            self.model.events_fitted / self.model.rows_fitted,
        )


class SurvivalCurveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = H.fit_hazard(
            simulate_panel().hazard(), ["util"], experiment_constraints(["util"]),
            n_trees=40, max_depth=3, learning_rate=0.15)

    def test_survival_is_non_increasing_and_bounded(self):
        curve = self.model.curve({"util": 0.6}, from_month=0, horizon=36)
        self.assertTrue(all(a >= b for a, b in zip(curve.survival, curve.survival[1:])))
        self.assertTrue(all(0.0 <= v <= 1.0 for v in curve.survival))

    def test_survival_is_the_product_of_one_minus_hazard(self):
        curve = self.model.curve({"util": 0.6}, from_month=0, horizon=6)
        expected = 1.0
        for h, s in zip(curve.hazards, curve.survival):
            expected *= (1.0 - h)
            self.assertAlmostEqual(s, expected, places=12)

    def test_pd_is_one_minus_survival(self):
        curve = self.model.curve({"util": 0.6}, from_month=0, horizon=12)
        self.assertAlmostEqual(curve.pd(12), 1.0 - curve.at(12), places=12)

    def test_survival_at_zero_months_is_one(self):
        self.assertEqual(
            self.model.curve({"util": 0.6}, from_month=0, horizon=6).at(0), 1.0)

    def test_asking_past_the_horizon_raises(self):
        curve = self.model.curve({"util": 0.6}, from_month=0, horizon=6)
        with self.assertRaises(H.HazardError):
            curve.at(7)

    def test_riskier_account_has_lower_survival(self):
        safe = self.model.curve({"util": 0.05}, from_month=0, horizon=24).at(24)
        risky = self.model.curve({"util": 0.95}, from_month=0, horizon=24).at(24)
        self.assertLess(risky, safe)

    def test_curve_records_where_extrapolation_begins(self):
        curve = self.model.curve(
            {"util": 0.6}, from_month=6, horizon=24, observed_until=18)
        self.assertEqual(curve.extrapolated_from, 12)

    def test_curve_with_no_observed_until_extrapolates_immediately(self):
        curve = self.model.curve({"util": 0.6}, from_month=6, horizon=24)
        self.assertEqual(curve.extrapolated_from, 0)

    def test_lifetime_pd_uses_the_remaining_term(self):
        pd12 = self.model.lifetime_pd({"util": 0.6}, from_month=0, remaining_term=12)
        pd36 = self.model.lifetime_pd({"util": 0.6}, from_month=0, remaining_term=36)
        self.assertLess(pd12, pd36)

    def test_zero_horizon_rejected(self):
        with self.assertRaises(H.HazardError):
            self.model.curve({"util": 0.6}, from_month=0, horizon=0)


class BaselineTests(unittest.TestCase):
    def test_observed_hazard_divides_by_those_at_risk(self):
        months = [AccountMonth("A", me(2007, m), m - 1, 0) for m in range(1, 4)]
        a = Spell("A", months, Event.DEFAULT, me(2007, 3))
        b = Spell("B", [AccountMonth("B", me(2007, m), m - 1, 0) for m in range(1, 4)])
        rows = Panel([a, b], date(2009, 12, 31)).hazard()
        observed = dict(H.observed_hazard(rows))
        # Two at risk in month 0, no events; two at risk in month 2, one event.
        self.assertAlmostEqual(observed[0], 0.0)
        self.assertAlmostEqual(observed[2], 0.5)

    def test_baseline_hazard_is_read_at_a_named_reference(self):
        model = H.fit_hazard(
            simulate_panel(n=400).hazard(), ["util"], experiment_constraints(["util"]),
            n_trees=20, max_depth=2)
        curve = H.baseline_hazard(model, {"util": 0.5}, max_month=12)
        self.assertEqual([m for m, _ in curve], list(range(1, 13)))
        self.assertTrue(all(0.0 <= h <= 1.0 for _, h in curve))

    def test_baseline_needs_a_positive_horizon(self):
        model = H.fit_hazard(
            simulate_panel(n=400).hazard(), ["util"], experiment_constraints(["util"]),
            n_trees=20, max_depth=2)
        with self.assertRaises(H.HazardError):
            H.baseline_hazard(model, {"util": 0.5}, max_month=0)


if __name__ == "__main__":
    unittest.main()

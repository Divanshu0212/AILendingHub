"""WS-3.2 Steps 1/4/6 and WS-3.1 Step 8 — aggregates, vintages, macro."""

import math
import random
import unittest
from datetime import date, datetime, timedelta, timezone

from lending_hub.definitions.provenance import Ungrounded
from lending_hub.portfolio import aggregates as G
from lending_hub.portfolio import macro as M
from lending_hub.portfolio.panel import (
    AccountMonth,
    Event,
    Panel,
    Spell,
    month_end,
)

NOW = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
ASOF = NOW - timedelta(minutes=2)


def exposure(aid="A", ead=1_000_000, pd=0.05, lgd=0.4, dpd=0, basis="gross_of_enhancement"):
    return G.Exposure(
        account_id=aid, snapshot=date(2026, 8, 31), ead_minor_units=ead,
        pd=pd, lgd=lgd, lgd_basis=basis if lgd is not None else None, dpd=dpd)


class ExposureTests(unittest.TestCase):
    def test_expected_loss_is_the_product_of_three(self):
        self.assertEqual(exposure(ead=1_000_000, pd=0.05, lgd=0.4)
                         .expected_loss_minor_units, 20_000)

    def test_missing_factor_makes_expected_loss_none(self):
        self.assertIsNone(exposure(pd=None).expected_loss_minor_units)
        self.assertIsNone(exposure(lgd=None).expected_loss_minor_units)

    def test_lgd_without_a_basis_is_rejected(self):
        with self.assertRaises(G.AggregateError) as ctx:
            G.Exposure("A", date(2026, 8, 31), 1_000, lgd=0.4)
        self.assertIn("LH-311", str(ctx.exception))

    def test_negative_ead_rejected(self):
        with self.assertRaises(G.AggregateError):
            G.Exposure("A", date(2026, 8, 31), -1)

    def test_probability_outside_unit_interval_rejected(self):
        with self.assertRaises(G.AggregateError):
            G.Exposure("A", date(2026, 8, 31), 1_000, pd=1.5)

    def test_bucket_comes_from_the_shared_bucketing(self):
        self.assertEqual(exposure(dpd=0).bucket, "current")
        self.assertEqual(exposure(dpd=120).bucket, "npa")


class AggregateTests(unittest.TestCase):
    def test_sums_ead_and_expected_loss(self):
        cells = G.aggregate_by(
            [exposure("A", 1_000_000, 0.05, 0.4), exposure("B", 2_000_000, 0.10, 0.4)],
            lambda e: "book", as_of=ASOF, computed_at=NOW)
        cell = cells["book"]
        self.assertEqual(cell.ead_minor_units, 3_000_000)
        self.assertEqual(cell.expected_loss_minor_units, 100_000)

    def test_segments_split_by_the_supplied_function(self):
        cells = G.aggregate_by(
            [exposure("A"), exposure("B")],
            lambda e: e.account_id, as_of=ASOF, computed_at=NOW)
        self.assertEqual(sorted(cells), ["A", "B"])

    def test_freshness_is_computed_and_compared_to_the_slo(self):
        cell = G.aggregate_by([exposure()], lambda e: "book",
                              as_of=ASOF, computed_at=NOW)["book"]
        self.assertAlmostEqual(cell.freshness_seconds, 120.0)
        self.assertTrue(cell.meets_freshness_slo)

    def test_stale_data_fails_the_slo(self):
        stale = NOW - timedelta(hours=2)
        cell = G.aggregate_by([exposure()], lambda e: "book",
                              as_of=stale, computed_at=NOW)["book"]
        self.assertFalse(cell.meets_freshness_slo)

    def test_naive_timestamps_rejected(self):
        with self.assertRaises(G.AggregateError) as ctx:
            G.Aggregate("book", datetime(2026, 9, 1), NOW)
        self.assertIn("timezone-aware", str(ctx.exception))

    def test_data_newer_than_the_computation_rejected(self):
        with self.assertRaises(G.AggregateError):
            G.Aggregate("book", NOW + timedelta(minutes=1), NOW)

    def test_drill_through_keeps_the_member_list(self):
        cell = G.aggregate_by(
            [exposure("A"), exposure("B")], lambda e: "book",
            as_of=ASOF, computed_at=NOW)["book"]
        self.assertEqual(cell.members, ["A", "B"])
        self.assertIn("members", cell.to_dict(include_members=True))
        self.assertNotIn("members", cell.to_dict())

    def test_coverage_reports_incomplete_expected_loss(self):
        cell = G.aggregate_by(
            [exposure("A"), exposure("B", pd=None)], lambda e: "book",
            as_of=ASOF, computed_at=NOW)["book"]
        self.assertAlmostEqual(cell.coverage, 0.5)
        self.assertEqual(cell.exposures_missing_pd, 1)

    def test_mixed_lgd_bases_are_flagged(self):
        cell = G.aggregate_by(
            [exposure("A", basis="gross_of_enhancement"),
             exposure("B", basis="net_of_enhancement")],
            lambda e: "book", as_of=ASOF, computed_at=NOW)["book"]
        self.assertTrue(cell.mixed_lgd_bases)

    def test_single_basis_is_not_flagged(self):
        cell = G.aggregate_by(
            [exposure("A"), exposure("B")], lambda e: "book",
            as_of=ASOF, computed_at=NOW)["book"]
        self.assertFalse(cell.mixed_lgd_bases)

    def test_ead_is_split_by_dpd_bucket(self):
        cell = G.aggregate_by(
            [exposure("A", dpd=0, ead=100), exposure("B", dpd=120, ead=200)],
            lambda e: "book", as_of=ASOF, computed_at=NOW)["book"]
        self.assertEqual(cell.bucket_ead, {"current": 100, "npa": 200})

    def test_publishing_segmentation_is_gated_on_lh_306(self):
        with self.assertRaises(Ungrounded) as ctx:
            G.require_segmentation()
        self.assertIn("LH-306", str(ctx.exception))

    def test_supplied_segmentation_passes_the_gate(self):
        self.assertEqual(G.require_segmentation({"retail": []}), {"retail": []})


class VintageTests(unittest.TestCase):
    def build(self, default_at=None, follow=24, n=10):
        spells = []
        for i in range(n):
            months = [
                AccountMonth(f"A{i}", month_end(date(2007 + m // 12, m % 12 + 1, 1)),
                             m, 0)
                for m in range(follow)
            ]
            event = event_month = None
            if default_at is not None and i < n // 2:
                months = months[:default_at + 1]
                event, event_month = Event.DEFAULT, months[-1].snapshot
            spells.append(Spell(f"A{i}", months, event, event_month))
        return Panel(spells, date(2012, 12, 31))

    def test_curve_is_non_decreasing(self):
        curves = G.vintage_curves(
            self.build(default_at=6), lambda s: "2007", max_months=24)
        rates = [p.cumulative_bad_rate for p in curves["2007"].points]
        self.assertTrue(all(a <= b for a, b in zip(rates, rates[1:])))

    def test_denominator_is_the_original_cohort(self):
        """Not the still-at-risk count, which invents late deterioration."""
        curves = G.vintage_curves(
            self.build(default_at=6), lambda s: "2007", max_months=24)
        curve = curves["2007"]
        self.assertEqual(curve.cohort_size, 10)
        self.assertAlmostEqual(curve.rate_at(24), 0.5)
        self.assertTrue(all(p.cohort_size == 10 for p in curve.points))

    def test_bad_rate_is_zero_before_the_default(self):
        curves = G.vintage_curves(
            self.build(default_at=6), lambda s: "2007", max_months=24)
        self.assertAlmostEqual(curves["2007"].rate_at(5), 0.0)
        self.assertAlmostEqual(curves["2007"].rate_at(6), 0.5)

    def test_cohorts_are_separated(self):
        panel = self.build(default_at=6)
        curves = G.vintage_curves(
            panel, lambda s: "even" if int(s.account_id[1:]) % 2 == 0 else "odd",
            max_months=12)
        self.assertEqual(sorted(curves), ["even", "odd"])

    def test_zero_horizon_rejected(self):
        with self.assertRaises(G.AggregateError):
            G.vintage_curves(self.build(), lambda s: "x", max_months=0)


class MacroTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng = random.Random(5)
        cls.observations = []
        for t in range(60):
            u = 5.0 + 3.0 * math.sin(t / 9) + rng.gauss(0, 0.3)
            g = 2.0 - 0.5 * math.sin(t / 7) + rng.gauss(0, 0.2)
            z = -4.0 + 0.35 * u - 0.20 * g + rng.gauss(0, 0.1)
            cls.observations.append(
                M.Observation(str(t), M.expit(z), {"unemployment": u, "gdp": g}))
        cls.model = M.fit_macro(
            cls.observations, ["unemployment", "gdp"], segment="retail")

    def test_recovers_the_generating_coefficients(self):
        got = dict(zip(self.model.factors, self.model.coefficients))
        self.assertAlmostEqual(got["unemployment"], 0.35, delta=0.06)
        self.assertAlmostEqual(got["gdp"], -0.20, delta=0.10)
        self.assertGreater(self.model.r_squared, 0.9)

    def test_predicted_rate_is_a_probability(self):
        for u in (-50.0, 0.0, 100.0):
            rate = self.model.predicted_rate({"unemployment": u, "gdp": 2.0})
            self.assertTrue(0.0 <= rate <= 1.0)

    def test_stress_stays_a_probability_at_the_extremes(self):
        stressed = self.model.shift(
            0.99, {"unemployment": 50.0, "gdp": -20.0},
            {"unemployment": 5.0, "gdp": 2.0})
        self.assertTrue(0.0 < stressed < 1.0)

    def test_worse_macro_raises_the_rate(self):
        base = {"unemployment": 5.0, "gdp": 2.0}
        worse = {"unemployment": 8.0, "gdp": 0.0}
        self.assertGreater(self.model.shift(0.05, worse, base), 0.05)

    def test_identical_paths_leave_the_rate_unchanged(self):
        base = {"unemployment": 5.0, "gdp": 2.0}
        self.assertAlmostEqual(self.model.shift(0.05, base, base), 0.05, places=9)

    def test_missing_factor_raises_rather_than_substituting_zero(self):
        with self.assertRaises(M.MacroError) as ctx:
            self.model.predicted_rate({"unemployment": 5.0})
        self.assertIn("missing", str(ctx.exception))

    def test_scenario_application_is_gated_on_lh_304(self):
        with self.assertRaises(Ungrounded) as ctx:
            M.apply_scenario(self.model, 0.05, "adverse")
        self.assertIn("LH-304", str(ctx.exception))

    def test_ratified_scenarios_can_be_applied(self):
        scenarios = {
            "baseline": {"unemployment": 5.0, "gdp": 2.0},
            "adverse": {"unemployment": 9.0, "gdp": -1.0},
        }
        stressed = M.apply_scenario(
            self.model, 0.05, "adverse", scenarios=scenarios)
        self.assertGreater(stressed, 0.05)

    def test_unknown_scenario_name_rejected(self):
        scenarios = {"baseline": {"unemployment": 5.0, "gdp": 2.0}}
        with self.assertRaises(M.MacroError):
            M.apply_scenario(self.model, 0.05, "severe", scenarios=scenarios)

    def test_scenario_set_without_a_baseline_rejected(self):
        scenarios = {"adverse": {"unemployment": 9.0, "gdp": -1.0}}
        with self.assertRaises(M.MacroError) as ctx:
            M.apply_scenario(self.model, 0.05, "adverse", scenarios=scenarios)
        self.assertIn("baseline", str(ctx.exception))

    def test_autocorrelated_residuals_raise_a_caveat(self):
        model = M.MacroModel(
            segment="x", factors=["a"], intercept=0.0, coefficients=[1.0],
            standard_errors=[0.1], observations=50, r_squared=0.5,
            residual_autocorrelation=0.7)
        self.assertIn("too small", model.caveat)

    def test_too_few_observations_rejected(self):
        with self.assertRaises(M.MacroError) as ctx:
            M.fit_macro(self.observations[:2], ["unemployment", "gdp"])
        self.assertIn("degrees of freedom", str(ctx.exception))

    def test_collinear_factors_are_reported_not_regularised(self):
        observations = [
            M.Observation(str(t), 0.05, {"a": float(t), "b": float(t) * 2.0})
            for t in range(20)
        ]
        with self.assertRaises(M.MacroError) as ctx:
            M.fit_macro(observations, ["a", "b"])
        self.assertIn("collinear", str(ctx.exception))

    def test_rate_outside_unit_interval_rejected(self):
        with self.assertRaises(M.MacroError):
            M.Observation("t", 1.5, {})


if __name__ == "__main__":
    unittest.main()

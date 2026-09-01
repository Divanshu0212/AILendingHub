"""WS-2.4 backtest and geographic disparate impact.

Phase 2 §4 attaches one instruction to these three tests: *a failed test
triggers feature redesign — never threshold relaxation*. That is why the tests
below check that ``run_backtest`` accepts no thresholds, and why every bar is a
`[SPEC]` constant traced to the phase file.
"""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from lending_hub.agri.backtest import (
    GINI_UPLIFT_POINTS,
    MIN_BACKTEST_SEASONS,
    NON_SOWING_LEAD_DAYS,
    NON_SOWING_RECALL,
    SEASON_LINKAGE_RULE,
    BacktestError,
    FeatureUse,
    PointInTimeViolation,
    SeasonLinkedDefault,
    assert_point_in_time,
    gini_uplift,
    non_sowing_backtest,
    quartile_monotonicity,
    run_backtest,
)
from lending_hub.agri.disparate import (
    GEOGRAPHIC_UNITS,
    DisparateImpactError,
    UnitRates,
    assess_geographic,
)
from lending_hub.definitions.provenance import Ungrounded

DECISION = date(2024, 5, 15)


class TestSpecConstants(unittest.TestCase):
    """Every bar traces to a clause in the phase file."""

    def test_the_four_thresholds_are_the_phase_file_numbers(self):
        self.assertEqual(MIN_BACKTEST_SEASONS.value, 3)
        self.assertEqual(GINI_UPLIFT_POINTS.value, 4.0)
        self.assertEqual(NON_SOWING_RECALL.value, 0.60)
        self.assertEqual(NON_SOWING_LEAD_DAYS.value, 45)

    def test_each_carries_its_citation(self):
        for constant in (
            MIN_BACKTEST_SEASONS, GINI_UPLIFT_POINTS, NON_SOWING_RECALL, NON_SOWING_LEAD_DAYS
        ):
            self.assertIn("Phase 2 §4", constant.citation)

    def test_the_season_linkage_rule_is_ungrounded(self):
        """LH-412 — 'season-linked default' is not a defined population."""
        self.assertEqual(SEASON_LINKAGE_RULE.ticket, "LH-412")
        with self.assertRaises(Ungrounded):
            SEASON_LINKAGE_RULE.value


class TestPointInTime(unittest.TestCase):
    def _use(self, published_offset: int, observed_offset: int = -20) -> FeatureUse:
        return FeatureUse(
            decision_id="D1",
            feature="ndvi_peak",
            decision_date=DECISION,
            observation_date=DECISION + timedelta(days=observed_offset),
            published_date=DECISION + timedelta(days=published_offset),
        )

    def test_a_feature_published_before_the_decision_is_clean(self):
        assert_point_in_time([self._use(published_offset=-14)])

    def test_a_feature_published_after_the_decision_is_a_violation(self):
        """The structural leak: joining on acquisition instead of publication.

        Sentinel-2 publishes hours to days after acquisition and reanalysis
        weeks after, so a backtest joined on acquisition date uses scenes nobody
        could have seen — and the result looks better than the live system could
        ever be.
        """
        with self.assertRaises(PointInTimeViolation) as ctx:
            assert_point_in_time([self._use(published_offset=+9)])
        self.assertIn("9 days of hindsight", str(ctx.exception))
        self.assertIn("not acquisition date", str(ctx.exception))

    def test_the_worst_violation_is_named(self):
        uses = [self._use(-5), self._use(+3), self._use(+31)]
        with self.assertRaises(PointInTimeViolation) as ctx:
            assert_point_in_time(uses)
        self.assertIn("31 days", str(ctx.exception))
        self.assertIn("2 of 3", str(ctx.exception))

    def test_observation_after_publication_is_impossible(self):
        with self.assertRaises(BacktestError):
            FeatureUse(
                decision_id="D1", feature="f", decision_date=DECISION,
                observation_date=DECISION, published_date=DECISION - timedelta(days=3),
            )

    def test_an_observation_on_the_decision_date_is_allowed_if_published_by_then(self):
        """Same-day publication is legal; it is the ordering that matters."""
        assert_point_in_time([self._use(published_offset=0, observed_offset=0)])


class TestCriterionA(unittest.TestCase):
    def _ordered(self, rates=(0.12, 0.08, 0.05, 0.02), per_quartile=100):
        scores, defaults = [], []
        for q, rate in enumerate(rates):
            for i in range(per_quartile):
                scores.append(q + i / (per_quartile * 2))
                defaults.append(1 if i < round(rate * per_quartile) else 0)
        return scores, defaults

    def test_a_monotone_feature_passes(self):
        scores, defaults = self._ordered()
        result = quartile_monotonicity(scores, defaults, seasons=4)
        self.assertTrue(result.is_monotonic)
        self.assertTrue(result.passed)
        self.assertEqual(result.why_not, "")

    def test_a_non_monotone_feature_fails_with_its_rates(self):
        scores, defaults = self._ordered(rates=(0.12, 0.03, 0.09, 0.02))
        result = quartile_monotonicity(scores, defaults, seasons=4)
        self.assertFalse(result.passed)
        self.assertIn("not monotone", result.why_not)

    def test_fewer_than_three_seasons_fails_even_when_monotone(self):
        scores, defaults = self._ordered()
        result = quartile_monotonicity(scores, defaults, seasons=2)
        self.assertTrue(result.is_monotonic)
        self.assertFalse(result.passed)
        self.assertIn("below the 3", result.why_not)

    def test_equal_adjacent_quartiles_are_monotone(self):
        """Non-increasing, not strictly decreasing.

        Demanding strictness would fail a correct feature on a small sample.
        """
        scores, defaults = self._ordered(rates=(0.10, 0.06, 0.06, 0.02))
        self.assertTrue(quartile_monotonicity(scores, defaults, seasons=3).is_monotonic)

    def test_spread_shows_how_much_ordering_there_is(self):
        """Four quartiles at 4.1/4.0/4.0/3.9% are monotone and useless."""
        flat_scores, flat_defaults = self._ordered(rates=(0.041, 0.040, 0.040, 0.039), per_quartile=1000)
        strong_scores, strong_defaults = self._ordered(rates=(0.14, 0.09, 0.05, 0.01), per_quartile=1000)
        flat = quartile_monotonicity(flat_scores, flat_defaults, seasons=3)
        strong = quartile_monotonicity(strong_scores, strong_defaults, seasons=3)
        self.assertTrue(flat.is_monotonic)
        self.assertGreater(strong.spread, flat.spread * 10)

    def test_mismatched_lengths_are_refused(self):
        with self.assertRaises(BacktestError):
            quartile_monotonicity([1.0, 2.0, 3.0, 4.0], [0, 1], seasons=3)

    def test_too_few_accounts_for_quartiles(self):
        with self.assertRaises(BacktestError):
            quartile_monotonicity([1.0, 2.0], [0, 1], seasons=3)

    def test_non_binary_outcomes_are_refused(self):
        with self.assertRaises(BacktestError):
            quartile_monotonicity([1.0, 2.0, 3.0, 4.0], [0, 1, 2, 0], seasons=3)


class TestCriterionB(unittest.TestCase):
    def test_a_sufficient_out_of_time_uplift_passes(self):
        result = gini_uplift(0.42, 0.47, seasons=4, out_of_time=True)
        self.assertAlmostEqual(result.uplift_points, 5.0, places=6)
        self.assertTrue(result.passed)

    def test_an_insufficient_uplift_fails(self):
        result = gini_uplift(0.42, 0.445, seasons=4, out_of_time=True)
        self.assertFalse(result.passed)
        self.assertIn("below the 4", result.why_not)

    def test_an_in_sample_comparison_never_passes(self):
        """Phase 3 made this mistake and caught it (P3-F14).

        The agri feature set is strictly larger than the baseline, so an
        in-sample +4 Gini is close to guaranteed and means nothing.
        """
        result = gini_uplift(0.42, 0.55, seasons=5, out_of_time=False)
        self.assertFalse(result.passed)
        self.assertIn("capacity rather than skill", result.why_not)

    def test_out_of_time_has_no_default(self):
        with self.assertRaises(TypeError):
            gini_uplift(0.42, 0.47, seasons=4)

    def test_a_gini_outside_the_valid_range_is_refused(self):
        with self.assertRaises(BacktestError):
            gini_uplift(0.42, 1.4, seasons=4, out_of_time=True)

    def test_a_negative_uplift_is_reported_with_its_sign(self):
        result = gini_uplift(0.50, 0.44, seasons=4, out_of_time=True)
        self.assertAlmostEqual(result.uplift_points, -6.0, places=6)
        self.assertIn("-6.00", result.why_not)


class TestCriterionC(unittest.TestCase):
    def _default(self, account: str, lead: int | None) -> SeasonLinkedDefault:
        default_date = date(2024, 11, 30)
        return SeasonLinkedDefault(
            account_id=account,
            season="kharif-2024",
            default_date=default_date,
            flag_date=None if lead is None else default_date - timedelta(days=lead),
        )

    def test_sufficient_recall_at_lead_passes(self):
        defaults = [self._default(f"A{i}", 60) for i in range(7)] + [
            self._default(f"B{i}", None) for i in range(3)
        ]
        result = non_sowing_backtest(defaults, seasons=3)
        self.assertAlmostEqual(result.recall, 0.7, places=9)
        self.assertTrue(result.passed)

    def test_a_flag_that_fired_too_late_does_not_count(self):
        """44 days is a miss; the criterion is >= 45."""
        result = non_sowing_backtest([self._default("A", 44)], seasons=3)
        self.assertEqual(result.fired_in_time, 0)
        self.assertEqual(result.fired_too_late, 1)

    def test_exactly_the_lead_minimum_counts(self):
        result = non_sowing_backtest([self._default("A", 45)], seasons=3)
        self.assertEqual(result.fired_in_time, 1)

    def test_misses_are_separated_by_cause(self):
        """A late flag and a missing flag call for different fixes."""
        defaults = [self._default("A", 90), self._default("B", 10), self._default("C", None)]
        result = non_sowing_backtest(defaults, seasons=3)
        self.assertEqual((result.fired_in_time, result.fired_too_late, result.never_fired), (1, 1, 1))
        self.assertIn("1 fired too late, 1 never fired", result.why_not)

    def test_median_lead_is_reported_over_flags_that_fired(self):
        defaults = [self._default("A", 30), self._default("B", 60), self._default("C", None)]
        self.assertEqual(non_sowing_backtest(defaults, seasons=3).median_lead_days, 45)

    def test_median_lead_is_none_when_nothing_fired(self):
        result = non_sowing_backtest([self._default("A", None)], seasons=3)
        self.assertIsNone(result.median_lead_days)

    def test_recall_over_zero_events_is_unmeasured_not_perfect(self):
        result = non_sowing_backtest([], seasons=3)
        self.assertFalse(result.passed)
        with self.assertRaises(BacktestError) as ctx:
            result.recall
        self.assertIn("unmeasured", str(ctx.exception))

    def test_lead_days_of_an_unfired_flag_is_none(self):
        self.assertIsNone(self._default("A", None).lead_days)


class TestBacktestPack(unittest.TestCase):
    def _inputs(self, **overrides):
        scores, defaults = [], []
        for q, rate in enumerate((0.12, 0.08, 0.05, 0.02)):
            for i in range(100):
                scores.append(q + i / 200)
                defaults.append(1 if i < round(rate * 100) else 0)
        base = dict(
            lqi_scores=scores,
            lqi_defaults=defaults,
            baseline_gini=0.42,
            with_agri_gini=0.48,
            out_of_time=True,
            season_linked_defaults=[
                SeasonLinkedDefault(
                    f"A{i}", "kharif-2024", date(2024, 11, 30),
                    date(2024, 11, 30) - timedelta(days=70),
                )
                for i in range(7)
            ]
            + [
                SeasonLinkedDefault(f"B{i}", "kharif-2024", date(2024, 11, 30))
                for i in range(3)
            ],
            seasons=4,
        )
        base.update(overrides)
        return base

    def test_all_three_criteria_can_pass_together(self):
        report = run_backtest(**self._inputs())
        self.assertTrue(report.passed)
        self.assertEqual(report.failures, {})
        self.assertEqual(report.response, "all three criteria met")

    def test_a_failure_names_the_criterion(self):
        report = run_backtest(**self._inputs(with_agri_gini=0.43))
        self.assertFalse(report.passed)
        self.assertIn("b_gini_uplift", report.failures)
        self.assertNotIn("a_lqi_monotonic", report.failures)

    def test_the_response_to_a_failure_is_the_phase_file_instruction(self):
        report = run_backtest(**self._inputs(with_agri_gini=0.43))
        self.assertIn("never threshold relaxation", report.response)

    def test_run_backtest_accepts_no_thresholds(self):
        """The mechanism behind "never threshold relaxation".

        A parameter with a default is how relaxation happens without anyone
        deciding to relax anything.
        """
        for bad_kwarg in ("gini_uplift_points", "min_seasons", "recall_threshold"):
            with self.assertRaises(TypeError):
                run_backtest(**self._inputs(), **{bad_kwarg: 0.0})

    def test_a_point_in_time_violation_raises_rather_than_failing(self):
        """It invalidates every result after it, so it is not a criterion."""
        uses = [
            FeatureUse("D1", "ndvi_peak", DECISION, DECISION - timedelta(days=10),
                       DECISION + timedelta(days=4))
        ]
        with self.assertRaises(PointInTimeViolation):
            run_backtest(**self._inputs(), feature_uses=uses)

    def test_the_report_serialises(self):
        payload = run_backtest(**self._inputs()).to_dict()
        self.assertIn("a_lqi_monotonic", payload)
        self.assertIn("median_lead_days", payload["c_non_sowing_recall"])
        self.assertTrue(payload["b_gini_uplift"]["out_of_time"])


class TestGeographicDisparateImpact(unittest.TestCase):
    def _units(self):
        return [
            UnitRates("district-A", n=500, approvals=350, mean_land_quality=0.72),
            UnitRates("district-B", n=400, approvals=240, mean_land_quality=0.61),
            UnitRates("district-C", n=300, approvals=120, mean_land_quality=0.38),
        ]

    def test_measures_the_disparity_between_extremes(self):
        report = assess_geographic(
            self._units(), unit_kind="district", ratification_reference="FL-2026-03"
        )
        self.assertEqual(report.finding.highest.unit, "district-A")
        self.assertEqual(report.finding.lowest.unit, "district-C")
        self.assertAlmostEqual(report.finding.rate_difference, 0.70 - 0.40, places=9)
        self.assertAlmostEqual(report.finding.rate_ratio, 0.40 / 0.70, places=9)

    def test_it_refuses_to_reach_a_verdict(self):
        """LH-410 owns both halves: which units, and how much is too much."""
        report = assess_geographic(
            self._units(), unit_kind="district", ratification_reference="FL-2026-03"
        )
        with self.assertRaises(Ungrounded) as ctx:
            report.verdict()
        self.assertIn("LH-410", str(ctx.exception))

    def test_an_unratified_unit_choice_is_refused_outright(self):
        """The cut is the analysis: district and agro-zone give different answers."""
        with self.assertRaises(Ungrounded) as ctx:
            assess_geographic(self._units(), unit_kind="district", ratification_reference="")
        self.assertIn("not an analysis", str(ctx.exception))

    def test_the_land_quality_gap_is_reported_alongside_the_disparity(self):
        """The agri-specific problem: the signal and the disparity are one number.

        A rain-shadow district really does have lower yields, so a lower
        approval rate there is simultaneously correct risk assessment and
        geographic disparity.
        """
        report = assess_geographic(
            self._units(), unit_kind="district", ratification_reference="FL-1"
        )
        self.assertAlmostEqual(report.finding.land_quality_gap, 0.72 - 0.38, places=9)
        self.assertIn("may be agronomic", report.finding.explained_by_land_quality)

    def test_a_disparity_against_the_agronomic_gradient_is_called_out(self):
        """Lower approvals on *better* land is not explained by agronomy."""
        units = [
            UnitRates("district-A", n=500, approvals=350, mean_land_quality=0.40),
            UnitRates("district-C", n=300, approvals=120, mean_land_quality=0.75),
        ]
        report = assess_geographic(units, unit_kind="district", ratification_reference="FL-1")
        self.assertIn("NOT explained by agronomy", report.finding.explained_by_land_quality)

    def test_missing_land_quality_leaves_the_disparity_unattributed(self):
        units = [
            UnitRates("A", n=500, approvals=350),
            UnitRates("C", n=300, approvals=120),
        ]
        report = assess_geographic(units, unit_kind="district", ratification_reference="FL-1")
        self.assertIsNone(report.finding.land_quality_gap)
        self.assertIn("unattributed", report.finding.explained_by_land_quality)

    def test_tiny_units_are_excluded(self):
        """A block with 6 applications is the extreme of every comparison."""
        units = self._units() + [UnitRates("block-tiny", n=6, approvals=0)]
        report = assess_geographic(
            units, unit_kind="district", ratification_reference="FL-1"
        )
        self.assertNotIn("block-tiny", [u.unit for u in report.units])
        self.assertEqual(report.finding.lowest.unit, "district-C")

    def test_fewer_than_two_comparable_units_is_refused(self):
        units = [UnitRates("A", n=500, approvals=350), UnitRates("B", n=4, approvals=1)]
        with self.assertRaises(DisparateImpactError) as ctx:
            assess_geographic(units, unit_kind="district", ratification_reference="FL-1")
        self.assertIn("two comparable populations", str(ctx.exception))

    def test_overlapping_confidence_intervals_are_flagged(self):
        units = [
            UnitRates("A", n=40, approvals=22),
            UnitRates("B", n=40, approvals=19),
        ]
        report = assess_geographic(units, unit_kind="block", ratification_reference="FL-1")
        self.assertTrue(report.finding.intervals_overlap)

    def test_separated_intervals_are_flagged_as_such(self):
        units = [
            UnitRates("A", n=2000, approvals=1600),
            UnitRates("B", n=2000, approvals=600),
        ]
        report = assess_geographic(units, unit_kind="district", ratification_reference="FL-1")
        self.assertFalse(report.finding.intervals_overlap)

    def test_more_approvals_than_applications_is_refused(self):
        with self.assertRaises(DisparateImpactError):
            UnitRates("A", n=10, approvals=11)

    def test_an_empty_unit_has_no_rate(self):
        with self.assertRaises(DisparateImpactError) as ctx:
            UnitRates("A", n=0, approvals=0).approval_rate
        self.assertIn("unmeasured, not zero", str(ctx.exception))

    def test_the_units_placeholder_is_registered(self):
        self.assertEqual(GEOGRAPHIC_UNITS.ticket, "LH-410")

    def test_the_report_serialises_without_a_verdict(self):
        payload = assess_geographic(
            self._units(), unit_kind="district", ratification_reference="FL-1"
        ).to_dict()
        self.assertIn("not computable", payload["verdict"])
        self.assertEqual(len(payload["units"]), 3)


if __name__ == "__main__":
    unittest.main()

"""EWS backtest — WS-4.A Step 6.

The two halves of this backtest are not equally measurable, and the tests are
organised around that. Capture rate is computable from the panel alone and is
the criterion the Track P run measures. Precision needs a collections officer's
judgement and is refused rather than approximated — the available substitute
measures the opposite of what it is named for.
"""

from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta

from lending_hub.ews.backtest import (
    CAPTURE_TARGET,
    RED_PRECISION_TARGET,
    REPLAY_MONTHS,
    REQUIRED_LEAD_DAYS,
    BacktestError,
    BacktestReport,
    ObservedDefault,
    ReplayAlert,
    TierPrecision,
    assert_no_hindsight,
    capture_rate,
    tier_precision,
)
from lending_hub.ews.routing import Disposition, Tier

DEFAULT_ON = date(2026, 6, 30)


def _default(account="A1", on=DEFAULT_ON) -> ObservedDefault:
    return ObservedDefault(account_id=account, defaulted_on=on)


def _alert(account="A1", *, days_before=90, tier=Tier.RED, signals=("s1",)) -> ReplayAlert:
    return ReplayAlert(
        account_id=account,
        raised_on=DEFAULT_ON - timedelta(days=days_before),
        tier=tier,
        signal_ids=signals,
    )


def _disposition(account="A1", *, confirmed=True) -> Disposition:
    return Disposition(
        alert_id=f"AL-{account}",
        disposed_at=datetime(2026, 4, 1, 10, 0),
        officer_id="OFF1",
        confirmed_relevant=confirmed,
        outcome_code="CONTACTED_PTP",
    )


class TestSpecConstants(unittest.TestCase):
    def test_the_four_targets_are_the_phase_file_numbers(self):
        self.assertEqual(REQUIRED_LEAD_DAYS.value, 60)
        self.assertEqual(CAPTURE_TARGET.value, 0.55)
        self.assertEqual(RED_PRECISION_TARGET.value, 0.25)
        self.assertEqual(REPLAY_MONTHS.value, 24)

    def test_the_targets_carry_the_phase_files_own_caveat(self):
        """§4 Step 6 marks them "revisit at gate with measured numbers"."""
        self.assertIn("revisit at gate", CAPTURE_TARGET.citation)
        self.assertIn("revisit at gate", RED_PRECISION_TARGET.citation)


class TestCaptureRate(unittest.TestCase):
    def test_an_alert_at_sufficient_lead_captures(self):
        result = capture_rate([_alert(days_before=90)], [_default()])
        self.assertEqual(result.captured, 1)
        self.assertAlmostEqual(result.capture_rate, 1.0, places=12)
        self.assertEqual(result.lead_days, (90,))

    def test_an_alert_too_close_to_the_default_does_not_capture(self):
        """An alert the day before a miss is a notification, not a warning."""
        result = capture_rate([_alert(days_before=5)], [_default()])
        self.assertEqual(result.captured, 0)
        self.assertEqual(result.captured_too_late, 1)

    def test_an_alert_exactly_at_the_required_lead_captures(self):
        result = capture_rate([_alert(days_before=60)], [_default()])
        self.assertEqual(result.captured, 1)

    def test_an_unalerted_defaulter_is_counted_separately_from_a_late_one(self):
        """Different failures needing different fixes: coverage vs timeliness."""
        alerts = [_alert("A1", days_before=5)]
        defaults = [_default("A1"), _default("A2")]
        result = capture_rate(alerts, defaults)
        self.assertEqual(result.captured_too_late, 1)
        self.assertEqual(result.never_alerted, 1)

    def test_the_earliest_qualifying_alert_supplies_the_lead(self):
        """Using the latest would report the system as barely making its own
        deadline when it in fact warned months earlier."""
        alerts = [_alert("A1", days_before=150), _alert("A1", days_before=65)]
        result = capture_rate(alerts, [_default("A1")])
        self.assertEqual(result.lead_days, (150,))

    def test_a_late_alert_does_not_disqualify_an_early_one(self):
        alerts = [_alert("A1", days_before=120), _alert("A1", days_before=3)]
        self.assertEqual(capture_rate(alerts, [_default("A1")]).captured, 1)

    def test_alerts_on_non_defaulters_do_not_affect_capture(self):
        """Capture is a recall statistic; false positives belong to precision."""
        alerts = [_alert("A1", days_before=90)] + [
            _alert(f"B{i}", days_before=90) for i in range(50)
        ]
        self.assertAlmostEqual(capture_rate(alerts, [_default("A1")]).capture_rate, 1.0)

    def test_capture_over_zero_defaulters_is_unmeasured(self):
        result = capture_rate([], [])
        with self.assertRaises(BacktestError) as ctx:
            result.capture_rate
        self.assertIn("unmeasured", str(ctx.exception))

    def test_tier_filtering_answers_a_different_question(self):
        """How much Red alone catches, as opposed to the system."""
        alerts = [_alert("A1", days_before=90, tier=Tier.AMBER)]
        both = capture_rate(alerts, [_default("A1")])
        red_only = capture_rate(alerts, [_default("A1")], tiers=(Tier.RED,))
        self.assertEqual(both.captured, 1)
        self.assertEqual(red_only.captured, 0)

    def test_a_tier_none_alert_cannot_enter_a_replay(self):
        with self.assertRaises(BacktestError) as ctx:
            ReplayAlert("A1", DEFAULT_ON - timedelta(days=90), Tier.NONE)
        self.assertIn("inflates the denominator", str(ctx.exception))

    def test_the_target_comparison(self):
        strong = capture_rate(
            [_alert(f"A{i}", days_before=90) for i in range(60)],
            [_default(f"A{i}") for i in range(100)],
        )
        self.assertTrue(strong.meets_target)
        self.assertEqual(strong.why_not, "")

        weak = capture_rate(
            [_alert(f"A{i}", days_before=90) for i in range(30)],
            [_default(f"A{i}") for i in range(100)],
        )
        self.assertFalse(weak.meets_target)
        self.assertIn("below the 0.55 target", weak.why_not)


class TestLeadDistribution(unittest.TestCase):
    def test_the_distribution_is_reported_not_just_the_centre(self):
        """A 70-day mean of half-at-130 and half-at-10 is a different system.

        Only one of them delivers Phase 4 §1's "30-120 days ahead".
        """
        alerts = [_alert(f"A{i}", days_before=130) for i in range(50)]
        alerts += [_alert(f"B{i}", days_before=65) for i in range(50)]
        defaults = [_default(f"A{i}") for i in range(50)] + [
            _default(f"B{i}") for i in range(50)
        ]
        result = capture_rate(alerts, defaults)
        percentiles = result.lead_percentiles
        self.assertEqual(percentiles["p10"], 65)
        self.assertEqual(percentiles["p90"], 130)
        self.assertNotEqual(percentiles["p10"], percentiles["p90"])

    def test_a_tight_distribution_shows_as_one(self):
        alerts = [_alert(f"A{i}", days_before=90) for i in range(100)]
        defaults = [_default(f"A{i}") for i in range(100)]
        percentiles = capture_rate(alerts, defaults).lead_percentiles
        self.assertEqual(percentiles["p10"], percentiles["p90"])

    def test_median_lead_is_none_when_nothing_captured(self):
        result = capture_rate([_alert(days_before=5)], [_default()])
        self.assertIsNone(result.median_lead_days)
        self.assertEqual(result.lead_percentiles, {})


class TestHindsight(unittest.TestCase):
    def test_an_alert_on_the_default_date_is_refused(self):
        """It would capture every defaulter at zero lead."""
        with self.assertRaises(BacktestError) as ctx:
            assert_no_hindsight([_alert("A1", days_before=0)], [_default("A1")])
        self.assertIn("zero lead", str(ctx.exception))

    def test_an_alert_after_the_default_is_refused(self):
        with self.assertRaises(BacktestError):
            assert_no_hindsight([_alert("A1", days_before=-10)], [_default("A1")])

    def test_clean_alerts_pass(self):
        assert_no_hindsight([_alert("A1", days_before=90)], [_default("A1")])

    def test_alerts_on_non_defaulters_are_not_checked(self):
        assert_no_hindsight([_alert("B1", days_before=-30)], [_default("A1")])

    def test_the_worst_offender_is_named(self):
        alerts = [_alert("A1", days_before=-1), _alert("A2", days_before=-40)]
        defaults = [_default("A1"), _default("A2")]
        with self.assertRaises(BacktestError) as ctx:
            assert_no_hindsight(alerts, defaults)
        self.assertIn("A2", str(ctx.exception))
        self.assertIn("2 alert(s)", str(ctx.exception))


class TestPrecisionIsRefusedNotApproximated(unittest.TestCase):
    """The module's central refusal."""

    def test_precision_without_dispositions_raises(self):
        with self.assertRaises(BacktestError) as ctx:
            tier_precision([_alert()], {}, tier=Tier.RED)
        self.assertIn("LH-510", str(ctx.exception))

    def test_the_refusal_names_why_the_default_outcome_is_not_a_substitute(self):
        """An alert that found distress the bank cured is a true positive.

        Under the default-outcome proxy it becomes a false positive, so a better
        collections operation scores a worse EWS.
        """
        with self.assertRaises(BacktestError) as ctx:
            tier_precision([_alert()], {}, tier=Tier.RED)
        message = str(ctx.exception)
        self.assertIn("penalises the system for working", message)
        self.assertIn("cured", message)

    def test_precision_is_computed_when_dispositions_exist(self):
        alerts = [_alert(f"A{i}") for i in range(10)]
        dispositions = {
            f"A{i}": _disposition(f"A{i}", confirmed=i < 3) for i in range(10)
        }
        result = tier_precision(alerts, dispositions, tier=Tier.RED)
        self.assertAlmostEqual(result.precision, 0.3, places=12)
        self.assertEqual(result.alerts, 10)

    def test_only_the_requested_tier_is_scored(self):
        alerts = [_alert("A1", tier=Tier.RED), _alert("A2", tier=Tier.AMBER)]
        dispositions = {"A1": _disposition("A1"), "A2": _disposition("A2")}
        self.assertEqual(tier_precision(alerts, dispositions, tier=Tier.RED).alerts, 1)

    def test_undisposed_alerts_are_excluded_from_the_denominator(self):
        """An open case is not a wrong one; it is an unanswered question."""
        alerts = [_alert(f"A{i}") for i in range(10)]
        dispositions = {"A0": _disposition("A0"), "A1": _disposition("A1", confirmed=False)}
        result = tier_precision(alerts, dispositions, tier=Tier.RED)
        self.assertEqual(result.alerts, 2)
        self.assertAlmostEqual(result.precision, 0.5, places=12)

    def test_precision_over_zero_disposed_alerts_is_unmeasured(self):
        result = TierPrecision(tier=Tier.RED, alerts=0, confirmed_relevant=0)
        with self.assertRaises(BacktestError):
            result.precision

    def test_the_red_target_applies_only_to_red(self):
        weak_amber = TierPrecision(tier=Tier.AMBER, alerts=100, confirmed_relevant=5)
        weak_red = TierPrecision(tier=Tier.RED, alerts=100, confirmed_relevant=5)
        self.assertTrue(weak_amber.meets_target)
        self.assertFalse(weak_red.meets_target)


class TestReport(unittest.TestCase):
    def _report(self, *, red=None, months=24, captured=60):
        capture = capture_rate(
            [_alert(f"A{i}", days_before=90) for i in range(captured)],
            [_default(f"A{i}") for i in range(100)],
        )
        return BacktestReport(
            capture=capture,
            red_precision=red,
            amber_precision=None,
            months_replayed=months,
            accounts=100,
            track="P",
        )

    def test_a_report_without_dispositions_cannot_pass(self):
        passed, why = self._report().meets_targets
        self.assertFalse(passed)
        self.assertIn("LH-510", why)

    def test_a_short_replay_cannot_pass(self):
        passed, why = self._report(months=9).meets_targets
        self.assertFalse(passed)
        self.assertIn("below the 24", why)

    def test_every_failure_is_reported_together(self):
        """Fixing one and rediscovering the next is a wasted cycle."""
        _, why = self._report(months=9, captured=20).meets_targets
        self.assertIn("below the 24", why)
        self.assertIn("below the 0.55 target", why)
        self.assertIn("LH-510", why)

    def test_a_complete_report_passes(self):
        red = TierPrecision(tier=Tier.RED, alerts=200, confirmed_relevant=70)
        passed, why = self._report(red=red).meets_targets
        self.assertTrue(passed)
        self.assertEqual(why, "")

    def test_serialisation_labels_precision_as_not_measurable(self):
        payload = self._report().to_dict()
        self.assertEqual(payload["red_precision"]["state"], "not measurable")
        self.assertIn("LH-510", payload["red_precision"]["reason"])
        self.assertEqual(payload["track"], "P")

    def test_serialisation_carries_the_lead_distribution(self):
        payload = self._report().to_dict()
        self.assertEqual(payload["capture"]["median_lead_days"], 90)
        self.assertIn("p90", payload["capture"]["lead_percentiles"])


if __name__ == "__main__":
    unittest.main()

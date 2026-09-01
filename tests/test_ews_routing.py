"""Tiering, routing and fatigue guardrails — WS-4.A Step 5.

Two rules carry this module. Phase 4 §1: "every automated action has an owner,
an SLA, and a captured outcome" — enforced in the Alert constructor, because an
alert missing any of the three is a notification and the difference stops being
visible once it is in a queue with the others. And §4 Step 3's two-key rule,
which is the right design and is missing all three of its thresholds.
"""

from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta

from lending_hub.definitions import ALERT_PRECISION_WINDOW_DAYS
from lending_hub.definitions.provenance import Ungrounded
from lending_hub.ews.routing import (
    ACTION_LIBRARY,
    OFFICER_DAILY_ALERT_CAP,
    Alert,
    CaseManagementPort,
    Disposition,
    InMemoryCaseManager,
    RoutingError,
    Tier,
    TwoKeyEvidence,
    apply_officer_cap,
    apply_retirements,
    retire_degraded,
    rolling_precision,
    tier,
)
from lending_hub.ews.signals import catalog_v1

RAISED = datetime(2026, 9, 1, 9, 0)


def _alert(
    alert_id="AL1",
    *,
    tier_=Tier.RED,
    raised=RAISED,
    owner="OFF1",
    action="call_customer",
    sla=24,
    reasons=("cash-flow change-point",),
    signals=("cash_flow.inflow_collapse",),
    disposition=None,
    account="ACC1",
) -> Alert:
    return Alert(
        alert_id=alert_id,
        account_id=account,
        tier=tier_,
        raised_at=raised,
        trigger_reasons=reasons,
        pd_delta=0.012,
        recommended_action=action,
        sla_hours=sla,
        owner_id=owner,
        signal_ids=signals,
        disposition=disposition,
    )


def _disposition(alert_id="AL1", *, confirmed=True, disposed=None) -> Disposition:
    return Disposition(
        alert_id=alert_id,
        disposed_at=disposed or (RAISED + timedelta(hours=4)),
        officer_id="OFF1",
        confirmed_relevant=confirmed,
        outcome_code="CONTACTED_PTP",
    )


class TestTwoKeyRule(unittest.TestCase):
    def test_change_point_alone_is_amber(self):
        self.assertIs(tier(TwoKeyEvidence(True, False, False)), Tier.AMBER)

    def test_all_three_conditions_is_red(self):
        self.assertIs(tier(TwoKeyEvidence(True, True, True)), Tier.RED)

    def test_a_change_point_with_only_one_confirmation_stays_amber(self):
        """Both keys, not either. That is what protects Red's precision."""
        self.assertIs(tier(TwoKeyEvidence(True, True, False)), Tier.AMBER)
        self.assertIs(tier(TwoKeyEvidence(True, False, True)), Tier.AMBER)

    def test_velocity_alone_is_not_an_alert(self):
        """What the rule implies and the phase file does not say.

        A PD move with no cash-flow regime change is the ordinary drift of a
        hazard model over a month. Treating it as Amber floods the queue with
        model noise — part of LH-508.
        """
        self.assertIs(tier(TwoKeyEvidence(False, True, True)), Tier.NONE)

    def test_nothing_firing_is_a_value_not_an_absence(self):
        """"Evaluated and nothing fired" differs from "not evaluated"."""
        self.assertIs(tier(TwoKeyEvidence(False, False, False)), Tier.NONE)

    def test_tiers_are_ordered(self):
        self.assertLess(Tier.NONE, Tier.AMBER)
        self.assertLess(Tier.AMBER, Tier.RED)

    def test_keys_turned_is_reported(self):
        self.assertEqual(TwoKeyEvidence(True, True, False).keys_turned, 2)


class TestAlertIsNotANotification(unittest.TestCase):
    """Phase 4 §1's three requirements, each attacked separately."""

    def test_an_alert_without_an_owner_is_refused(self):
        with self.assertRaises(RoutingError) as ctx:
            _alert(owner="")
        self.assertIn("is a notification", str(ctx.exception))

    def test_an_alert_without_an_sla_is_refused(self):
        """Without one there is no definition of late, so §8 measures nothing."""
        with self.assertRaises(RoutingError) as ctx:
            _alert(sla=0)
        self.assertIn("definition of late", str(ctx.exception))

    def test_an_alert_without_a_recommended_action_is_refused(self):
        with self.assertRaises(RoutingError) as ctx:
            _alert(action="")
        self.assertIn("LH-502", str(ctx.exception))

    def test_an_alert_without_trigger_reasons_is_refused(self):
        """An officer who cannot see why it fired cannot dispose of it."""
        with self.assertRaises(RoutingError) as ctx:
            _alert(reasons=())
        self.assertIn("training signal", str(ctx.exception))

    def test_a_tier_none_alert_cannot_be_routed(self):
        with self.assertRaises(RoutingError) as ctx:
            _alert(tier_=Tier.NONE)
        self.assertIn("mis-tiered", str(ctx.exception))

    def test_the_action_library_is_ungrounded(self):
        self.assertEqual(ACTION_LIBRARY.ticket, "LH-502")
        with self.assertRaises(Ungrounded):
            ACTION_LIBRARY.value


class TestSlaBreach(unittest.TestCase):
    def test_an_open_alert_past_its_sla_has_breached(self):
        alert = _alert(sla=24)
        self.assertTrue(alert.breached_sla(now=RAISED + timedelta(hours=25)))

    def test_an_open_alert_inside_its_sla_has_not(self):
        self.assertFalse(_alert(sla=24).breached_sla(now=RAISED + timedelta(hours=3)))

    def test_a_disposed_alert_is_judged_on_when_it_was_disposed(self):
        """Not retrospectively: the question is whether it was handled in time."""
        in_time = _alert(disposition=_disposition(disposed=RAISED + timedelta(hours=4)))
        self.assertFalse(in_time.breached_sla(now=RAISED + timedelta(days=30)))

        late = _alert(disposition=_disposition(disposed=RAISED + timedelta(hours=40)))
        self.assertTrue(late.breached_sla(now=RAISED + timedelta(days=30)))


class TestDisposition(unittest.TestCase):
    def test_an_outcome_code_is_mandatory(self):
        """It is P6's training data; an alert closed without one trains nothing."""
        with self.assertRaises(RoutingError) as ctx:
            Disposition(
                alert_id="AL1", disposed_at=RAISED, officer_id="OFF1",
                confirmed_relevant=True, outcome_code="",
            )
        self.assertIn("trains nothing", str(ctx.exception))

    def test_confirmed_relevant_is_about_the_alert_not_the_default(self):
        """An alert that found distress the bank then cured is a true positive.

        Scoring it against the default outcome would penalise the system for
        working.
        """
        cured = _disposition(confirmed=True)
        self.assertTrue(cured.confirmed_relevant)


class TestCaseManagement(unittest.TestCase):
    def test_the_in_memory_manager_satisfies_the_port(self):
        self.assertIsInstance(InMemoryCaseManager(), CaseManagementPort)

    def test_opening_and_disposing_a_case(self):
        manager = InMemoryCaseManager()
        manager.open_case(_alert())
        self.assertEqual(manager.undisposed_count, 1)
        manager.record_disposition(_disposition())
        self.assertEqual(manager.undisposed_count, 0)

    def test_opening_the_same_alert_twice_is_refused(self):
        manager = InMemoryCaseManager()
        manager.open_case(_alert())
        with self.assertRaises(RoutingError):
            manager.open_case(_alert())

    def test_disposing_an_unopened_alert_is_refused(self):
        """The two systems disagreeing about what was raised invalidates precision."""
        manager = InMemoryCaseManager()
        with self.assertRaises(RoutingError) as ctx:
            manager.record_disposition(_disposition("GHOST"))
        self.assertIn("every precision estimate built from them is wrong", str(ctx.exception))

    def test_open_cases_excludes_disposed_ones(self):
        manager = InMemoryCaseManager()
        manager.open_case(_alert("AL1"))
        manager.open_case(_alert("AL2"))
        manager.record_disposition(_disposition("AL1"))
        self.assertEqual([a.alert_id for a in manager.open_cases], ["AL2"])


class TestOfficerCap(unittest.TestCase):
    def _queue(self, reds=3, ambers=5):
        alerts = [
            _alert(f"R{i}", tier_=Tier.RED, raised=RAISED + timedelta(minutes=i))
            for i in range(reds)
        ]
        alerts += [
            _alert(f"A{i}", tier_=Tier.AMBER, raised=RAISED + timedelta(minutes=i))
            for i in range(ambers)
        ]
        return alerts

    def test_the_cap_is_respected(self):
        assignment = apply_officer_cap(self._queue(), "OFF1", cap=5)
        self.assertEqual(len(assignment.assigned), 5)
        self.assertEqual(len(assignment.deferred), 3)

    def test_red_is_assigned_before_amber(self):
        assignment = apply_officer_cap(self._queue(reds=3, ambers=5), "OFF1", cap=3)
        self.assertTrue(all(a.tier is Tier.RED for a in assignment.assigned))

    def test_within_a_tier_the_oldest_goes_first(self):
        """An alert that has been waiting is closer to its SLA."""
        assignment = apply_officer_cap(self._queue(reds=0, ambers=5), "OFF1", cap=2)
        self.assertEqual([a.alert_id for a in assignment.assigned], ["A0", "A1"])

    def test_deferred_reds_are_counted_separately(self):
        """The number that says the cap is set wrong.

        Deferring Amber is the guardrail working. Deferring Red means the book
        generates more urgent work than the desk can absorb, and the answer is
        capacity or a stricter trigger — not a bigger cap.
        """
        assignment = apply_officer_cap(self._queue(reds=6, ambers=2), "OFF1", cap=4)
        self.assertEqual(assignment.deferred_red_count, 2)

    def test_at_capacity_is_reported(self):
        self.assertTrue(apply_officer_cap(self._queue(), "OFF1", cap=3).at_capacity)
        self.assertFalse(apply_officer_cap(self._queue(reds=1, ambers=0), "OFF1", cap=3).at_capacity)

    def test_the_cap_refuses_without_ratification(self):
        """Not derivable from the portfolio budget — a rate is not a workload."""
        with self.assertRaises(Ungrounded) as ctx:
            apply_officer_cap(self._queue(), "OFF1")
        self.assertIn("LH-507", str(ctx.exception))
        self.assertIn("district in drought", str(ctx.exception))

    def test_a_zero_cap_is_refused(self):
        with self.assertRaises(RoutingError):
            apply_officer_cap(self._queue(), "OFF1", cap=0)

    def test_the_cap_placeholder_is_registered(self):
        self.assertEqual(OFFICER_DAILY_ALERT_CAP.ticket, "LH-507")


class TestRollingPrecision(unittest.TestCase):
    def _setup(self, confirmed_count=3, total=10, *, signal="cash_flow.inflow_collapse"):
        alerts = {}
        dispositions = []
        for i in range(total):
            alert_id = f"AL{i}"
            alerts[alert_id] = _alert(alert_id, signals=(signal,))
            dispositions.append(_disposition(alert_id, confirmed=i < confirmed_count))
        return dispositions, alerts

    def test_precision_over_the_appendix_a_window(self):
        dispositions, alerts = self._setup(3, 10)
        precision, count = rolling_precision(
            dispositions, alerts, "cash_flow.inflow_collapse", as_of=date(2026, 9, 2)
        )
        self.assertAlmostEqual(precision, 0.3, places=9)
        self.assertEqual(count, 10)

    def test_alerts_outside_the_window_are_excluded(self):
        dispositions, alerts = self._setup(3, 10)
        precision, count = rolling_precision(
            dispositions, alerts, "cash_flow.inflow_collapse",
            as_of=date(2026, 9, 1) + timedelta(days=ALERT_PRECISION_WINDOW_DAYS.value + 5),
        )
        self.assertIsNone(precision)
        self.assertEqual(count, 0)

    def test_other_signals_alerts_are_excluded(self):
        dispositions, alerts = self._setup(3, 10, signal="bureau.new_enquiry_burst")
        precision, count = rolling_precision(
            dispositions, alerts, "cash_flow.inflow_collapse", as_of=date(2026, 9, 2)
        )
        self.assertIsNone(precision)

    def test_a_quiet_signal_has_no_precision_rather_than_zero(self):
        """A monitor that renders it as zero retires a working signal."""
        precision, count = rolling_precision(
            [], {}, "cash_flow.inflow_collapse", as_of=date(2026, 9, 2)
        )
        self.assertIsNone(precision)
        self.assertEqual(count, 0)


class TestAutoRetirement(unittest.TestCase):
    def _signal(self):
        return catalog_v1().get("cash_flow.inflow_collapse")

    def _history(self, confirmed_count, total=20):
        alerts = {}
        dispositions = []
        for i in range(total):
            alert_id = f"AL{i}"
            alerts[alert_id] = _alert(alert_id, signals=("cash_flow.inflow_collapse",))
            dispositions.append(_disposition(alert_id, confirmed=i < confirmed_count))
        return dispositions, alerts

    def test_a_degraded_signal_is_retired(self):
        dispositions, alerts = self._history(2, 20)
        decision = retire_degraded(
            self._signal(), dispositions, alerts, as_of=date(2026, 9, 2), floor=0.25
        )
        self.assertTrue(decision.retire)
        self.assertAlmostEqual(decision.measured_precision, 0.10, places=9)

    def test_a_healthy_signal_is_kept(self):
        dispositions, alerts = self._history(12, 20)
        decision = retire_degraded(
            self._signal(), dispositions, alerts, as_of=date(2026, 9, 2), floor=0.25
        )
        self.assertFalse(decision.retire)
        self.assertIn("holds the", decision.reason)

    def test_a_quiet_signal_is_not_retired_for_being_quiet(self):
        """Retiring it would remove a rare-event detector for being rare."""
        decision = retire_degraded(
            self._signal(), [], {}, as_of=date(2026, 9, 2), floor=0.25
        )
        self.assertFalse(decision.retire)
        self.assertIn("not a wrong one", decision.reason)

    def test_retirement_refuses_without_a_ratified_floor(self):
        dispositions, alerts = self._history(2, 20)
        with self.assertRaises(Ungrounded) as ctx:
            retire_degraded(self._signal(), dispositions, alerts, as_of=date(2026, 9, 2))
        self.assertIn("LH-501", str(ctx.exception))

    def test_applying_a_retirement_disables_rather_than_deletes(self):
        """A deleted definition makes every past alert citing it unexplainable."""
        catalog = catalog_v1()
        dispositions, alerts = self._history(2, 20)
        decision = retire_degraded(
            catalog.get("cash_flow.inflow_collapse"), dispositions, alerts,
            as_of=date(2026, 9, 2), floor=0.25,
        )
        retired = apply_retirements(catalog, [decision])

        self.assertEqual(retired, ("cash_flow.inflow_collapse",))
        signal = catalog.get("cash_flow.inflow_collapse")
        self.assertFalse(signal.enabled)
        self.assertEqual(signal.version, "1.0.0")
        self.assertIn("cash_flow.inflow_collapse", catalog.signals)

    def test_applying_no_retirements_changes_nothing(self):
        catalog = catalog_v1()
        decision = retire_degraded(
            catalog.get("cash_flow.inflow_collapse"), [], {},
            as_of=date(2026, 9, 2), floor=0.25,
        )
        self.assertEqual(apply_retirements(catalog, [decision]), ())
        self.assertTrue(catalog.get("cash_flow.inflow_collapse").enabled)


if __name__ == "__main__":
    unittest.main()

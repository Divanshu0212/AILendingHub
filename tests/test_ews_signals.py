"""Signal catalog and the anti-alert-fatigue contract — WS-4.A Step 1.

Phase 4 §4 Step 1: "a signal ships only with a backtested precision estimate
attached. Signals without measurable precision do not ship." Most of what
follows tests that this is a gate rather than a guideline — including the case
that matters here, where *no* signal can ship because dispositions do not exist.
"""

from __future__ import annotations

import unittest
from datetime import date

from lending_hub.definitions import ALERT_PRECISION_WINDOW_DAYS
from lending_hub.ews.signals import (
    MIN_ALERTS_FOR_PRECISION,
    PRECISION_FLOOR,
    Direction,
    PrecisionEvidence,
    SignalCatalog,
    SignalDefinition,
    SignalError,
    SignalFamily,
    catalog_v1,
)
from lending_hub.definitions.provenance import Ungrounded

WINDOW = ALERT_PRECISION_WINDOW_DAYS.value


def _evidence(confirmed=40, total=100, *, window=WINDOW, source="backtest") -> PrecisionEvidence:
    return PrecisionEvidence(
        confirmed_relevant=confirmed,
        total_alerts=total,
        window_days=window,
        measured_through=date(2026, 6, 30),
        source=source,
    )


def _signal(
    signal_id="repayment.test",
    *,
    precision=None,
    enabled=True,
    version="1.0.0",
    evaluate=None,
) -> SignalDefinition:
    return SignalDefinition(
        signal_id=signal_id,
        family=SignalFamily.REPAYMENT,
        version=version,
        description="test signal",
        direction=Direction.HIGHER_IS_WORSE,
        evaluate=evaluate or (lambda f: f["x"] > 1),
        srs_ref="SRS §10.3 repayment",
        precision=precision,
        enabled=enabled,
    )


class TestPrecisionEvidence(unittest.TestCase):
    def test_precision_uses_the_appendix_a_definition(self):
        self.assertAlmostEqual(_evidence(30, 120).precision, 0.25, places=12)

    def test_a_window_other_than_appendix_a_is_refused(self):
        """The window is shared with P1 fraud alerting and must move together."""
        with self.assertRaises(SignalError) as ctx:
            _evidence(window=30)
        self.assertIn("not comparable", str(ctx.exception))

    def test_more_confirmations_than_alerts_is_refused(self):
        with self.assertRaises(SignalError) as ctx:
            _evidence(confirmed=10, total=5)
        self.assertIn("never raised", str(ctx.exception))

    def test_negative_counts_are_refused(self):
        with self.assertRaises(SignalError):
            _evidence(confirmed=-1, total=10)

    def test_evidence_must_name_its_source(self):
        """A backtest precision and a live precision differ systematically.

        A backtest has no officer choosing what to investigate, so its
        disposition mix is not the operational one.
        """
        with self.assertRaises(SignalError) as ctx:
            _evidence(source="")
        self.assertIn("choosing what to investigate", str(ctx.exception))

    def test_an_empty_window_has_no_precision(self):
        """Appendix A returns None: no alerts fired is not every alert wrong."""
        self.assertIsNone(_evidence(0, 0).precision)

    def test_sufficiency_is_reported_separately_from_the_ratio(self):
        self.assertFalse(_evidence(3, 9).is_sufficient)
        self.assertTrue(_evidence(40, MIN_ALERTS_FOR_PRECISION).is_sufficient)


class TestShipGate(unittest.TestCase):
    def test_a_signal_with_no_precision_does_not_ship(self):
        shippable, why = _signal().shippable
        self.assertFalse(shippable)
        self.assertIn("do not ship", why)
        self.assertIn("LH-510", why)

    def test_a_thin_precision_estimate_does_not_gate(self):
        """Precision on 9 alerts moves across a floor on one disposition."""
        shippable, why = _signal(precision=_evidence(3, 9)).shippable
        self.assertFalse(shippable)
        self.assertIn("below the 100", why)

    def test_a_sufficient_estimate_still_needs_a_ratified_floor(self):
        """LH-501 — a floor chosen by whoever ships the signal is not a gate."""
        shippable, why = _signal(precision=_evidence(40, 200)).shippable
        self.assertFalse(shippable)
        self.assertIn("LH-501", why)
        self.assertIn("not a gate", why)

    def test_the_floor_itself_is_ungrounded(self):
        self.assertEqual(PRECISION_FLOOR.ticket, "LH-501")
        with self.assertRaises(Ungrounded):
            PRECISION_FLOOR.value

    def test_the_gate_reports_in_the_promotable_shape(self):
        """Same (bool, reason) shape as GBM.promotable and BandConfig.effective."""
        result = _signal().shippable
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], bool)
        self.assertIsInstance(result[1], str)


class TestSignalDefinition(unittest.TestCase):
    def test_a_signal_needs_a_version(self):
        """An unversioned definition invalidates every precision measured on it."""
        with self.assertRaises(SignalError) as ctx:
            _signal(version="")
        self.assertIn("changed silently", str(ctx.exception))

    def test_a_signal_needs_an_srs_citation(self):
        with self.assertRaises(SignalError):
            SignalDefinition(
                signal_id="x", family=SignalFamily.REPAYMENT, version="1.0.0",
                description="d", direction=Direction.HIGHER_IS_WORSE,
                evaluate=lambda f: True, srs_ref="",
            )

    def test_a_signal_needs_an_id(self):
        with self.assertRaises(SignalError):
            _signal(signal_id="")

    def test_firing_evaluates_the_predicate(self):
        signal = _signal()
        self.assertTrue(signal.fires({"x": 5}))
        self.assertFalse(signal.fires({"x": 0}))

    def test_a_missing_feature_raises_rather_than_reading_as_not_fired(self):
        """The silent-disable failure.

        A signal that treats a missing feature as "did not fire" is switched off
        for exactly the accounts with incomplete data, which are not a random
        subset of the book.
        """
        with self.assertRaises(SignalError) as ctx:
            _signal().fires({"other": 1})
        self.assertIn("not a random subset", str(ctx.exception))

    def test_direction_is_recorded_for_the_two_key_rule(self):
        """"Negative direction" is meaningless without knowing which way is bad."""
        balance = SignalDefinition(
            signal_id="cash_flow.b", family=SignalFamily.CASH_FLOW, version="1.0.0",
            description="d", direction=Direction.LOWER_IS_WORSE,
            evaluate=lambda f: True, srs_ref="SRS §10.3",
        )
        self.assertIs(balance.direction, Direction.LOWER_IS_WORSE)
        self.assertIs(_signal().direction, Direction.HIGHER_IS_WORSE)


class TestCatalog(unittest.TestCase):
    def test_registering_the_same_version_twice_is_refused(self):
        """How a definition changes while its precision refers to the old one."""
        catalog = SignalCatalog(version="v1")
        catalog.register(_signal())
        with self.assertRaises(SignalError) as ctx:
            catalog.register(_signal())
        self.assertIn("already registered", str(ctx.exception))

    def test_a_new_version_replaces_the_old(self):
        catalog = SignalCatalog(version="v1")
        catalog.register(_signal(version="1.0.0"))
        catalog.register(_signal(version="1.1.0"))
        self.assertEqual(catalog.get("repayment.test").version, "1.1.0")

    def test_an_unknown_signal_raises(self):
        with self.assertRaises(SignalError):
            SignalCatalog(version="v1").get("nope")

    def test_enabled_and_shippable_are_different_switches(self):
        """A duty manager may disable; nobody may re-enable past the ship gate."""
        catalog = SignalCatalog(version="v1")
        catalog.register(_signal(enabled=True, precision=None))
        self.assertEqual(len(catalog.active()), 0)
        self.assertIn("repayment.test", catalog.blocked)

    def test_evaluate_only_runs_active_signals(self):
        """A shadow alert that reaches a queue is a live alert."""
        catalog = SignalCatalog(version="v1")
        catalog.register(_signal(evaluate=lambda f: True))
        self.assertEqual(catalog.evaluate({"x": 9}), ())

    def test_by_family_groups_correlated_signals(self):
        catalog = catalog_v1()
        repayment = catalog.by_family(SignalFamily.REPAYMENT)
        self.assertEqual(len(repayment), 2)
        self.assertTrue(all(s.family is SignalFamily.REPAYMENT for s in repayment))


class TestCatalogV1(unittest.TestCase):
    def test_covers_the_srs_families_that_are_implementable_here(self):
        catalog = catalog_v1()
        families = {s.family for s in catalog.signals.values()}
        self.assertIn(SignalFamily.REPAYMENT, families)
        self.assertIn(SignalFamily.CASH_FLOW, families)
        self.assertIn(SignalFamily.BUREAU, families)
        self.assertIn(SignalFamily.BEHAVIORAL, families)
        self.assertIn(SignalFamily.MACRO_LOCAL, families)

    def test_not_one_signal_is_shippable(self):
        """The honest state of the catalogue, and the point of the module.

        Precision needs dispositions (LH-510) and a floor needs ratification
        (LH-501). Every signal says so with a reason instead of carrying a
        plausible number.
        """
        catalog = catalog_v1()
        self.assertEqual(len(catalog.shippable), 0)
        self.assertEqual(len(catalog.blocked), len(catalog.signals))

    def test_every_blocked_signal_gives_a_reason_naming_a_ticket(self):
        for signal_id, why in catalog_v1().blocked.items():
            self.assertTrue(
                "LH-510" in why or "LH-501" in why, f"{signal_id}: {why}"
            )

    def test_every_signal_carries_an_srs_reference(self):
        for signal in catalog_v1().signals.values():
            self.assertIn("SRS §10.3", signal.srs_ref)

    def test_signals_evaluate_on_a_full_feature_row(self):
        features = {
            "missed_emis_last_month": 1, "clean_months_before": 12,
            "consecutive_partial_payments": 0,
            "net_inflow": 100.0, "net_inflow_median_6m": 400.0,
            "balance_trend_weeks_negative": 2,
            "bureau_enquiries_30d": 4, "external_dpd_max": 0,
            "utilisation": 0.9, "utilisation_median_6m": 0.4,
            "district_delinquency_rising_months": 1,
        }
        catalog = catalog_v1()
        fired = {
            s.signal_id for s in catalog.signals.values() if s.fires(features)
        }
        self.assertIn("repayment.first_missed_emi", fired)
        self.assertIn("cash_flow.inflow_collapse", fired)
        self.assertIn("bureau.new_enquiry_burst", fired)
        self.assertNotIn("bureau.external_delinquency", fired)

    def test_serialisation_reports_the_blocked_state(self):
        payload = catalog_v1().to_dict()
        self.assertEqual(payload["shippable_count"], 0)
        self.assertEqual(payload["blocked_count"], 8)
        self.assertIsNone(payload["signals"]["repayment.first_missed_emi"]["precision"])


if __name__ == "__main__":
    unittest.main()

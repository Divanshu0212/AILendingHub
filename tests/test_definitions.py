"""Appendix A definitions — the tests that keep the frozen definitions frozen.

Workstream: WS-0.3.4
"""

import unittest
from datetime import date

from lending_hub.definitions import (
    AGRI_SEASON_CALENDAR,
    DEFINITIONS_VERSION,
    CONFIRMED_FRAUD_DISPOSITION_CODES,
    DEFAULT_DPD_THRESHOLD_DAYS,
    REGISTER,
    Label,
    OutcomeObservation,
    Pending,
    Scoring,
    Source,
    Ungrounded,
    alert_precision,
    fingerprint,
    is_trainable,
    label,
    month_end,
    observation_point,
    outcome_window,
    pending_definitions,
)


class TestDefaultDefinition(unittest.TestCase):
    """Appendix A: max DPD >= 90 OR write-off OR fraud OR distress restructure."""

    def test_dpd_at_threshold_is_bad(self):
        self.assertIs(label(OutcomeObservation(max_dpd=90)), Label.BAD)

    def test_dpd_below_threshold_alone_is_not_bad(self):
        self.assertIsNot(label(OutcomeObservation(max_dpd=89)), Label.BAD)

    def test_each_non_dpd_trigger_stands_alone(self):
        for field in ("written_off", "fraud_confirmed", "restructured_due_to_distress"):
            with self.subTest(trigger=field):
                obs = OutcomeObservation(max_dpd=0, **{field: True})
                self.assertIs(label(obs), Label.BAD)

    def test_unobserved_flag_is_not_a_negative(self):
        # None means "not observed", which must not be read as False-and-therefore-good
        # by accident. It is simply not a default trigger on its own.
        self.assertIs(label(OutcomeObservation(max_dpd=0, written_off=None)), Label.GOOD)

    def test_negative_dpd_rejected(self):
        with self.assertRaises(ValueError):
            OutcomeObservation(max_dpd=-1)


class TestIndeterminate(unittest.TestCase):
    """30-89 max DPD: out of training targets, into scoring and reporting."""

    def test_band_edges(self):
        self.assertIs(label(OutcomeObservation(max_dpd=29)), Label.GOOD)
        self.assertIs(label(OutcomeObservation(max_dpd=30)), Label.INDETERMINATE)
        self.assertIs(label(OutcomeObservation(max_dpd=89)), Label.INDETERMINATE)
        self.assertIs(label(OutcomeObservation(max_dpd=90)), Label.BAD)

    def test_indeterminate_excluded_from_training_only(self):
        obs = OutcomeObservation(max_dpd=45)
        self.assertFalse(is_trainable(obs))
        # ...but it still carries a label, so scoring and reporting can include it.
        self.assertIs(label(obs), Label.INDETERMINATE)

    def test_bad_beats_indeterminate_band(self):
        # 45 DPD but written off -> BAD, not INDETERMINATE. Order matters: an
        # indeterminate-first rule would quietly drop real defaults from training.
        self.assertIs(label(OutcomeObservation(max_dpd=45, written_off=True)), Label.BAD)

    def test_good_and_bad_are_trainable(self):
        self.assertTrue(is_trainable(OutcomeObservation(max_dpd=0)))
        self.assertTrue(is_trainable(OutcomeObservation(max_dpd=120)))


class TestOutcomeWindow(unittest.TestCase):
    def test_default_window_is_twelve_months(self):
        start, end = outcome_window(date(2026, 3, 15))
        self.assertEqual(start, date(2026, 3, 15))
        self.assertEqual(end, date(2027, 3, 15))

    def test_window_clamps_to_short_month(self):
        _, end = outcome_window(date(2026, 1, 31), months=1)
        self.assertEqual(end, date(2026, 2, 28))

    def test_window_crosses_leap_february(self):
        _, end = outcome_window(date(2027, 1, 31), months=1)
        self.assertEqual(end, date(2027, 2, 28))
        _, leap = outcome_window(date(2028, 1, 31), months=1)
        self.assertEqual(leap, date(2028, 2, 29))

    def test_december_rollover(self):
        _, end = outcome_window(date(2026, 12, 1))
        self.assertEqual(end, date(2027, 12, 1))


class TestObservationPoint(unittest.TestCase):
    def test_application_uses_final_decision_timestamp(self):
        point = observation_point(Scoring.APPLICATION, final_decision_at=date(2026, 5, 4))
        self.assertEqual(point, date(2026, 5, 4))

    def test_application_requires_the_timestamp(self):
        with self.assertRaises(ValueError):
            observation_point(Scoring.APPLICATION)

    def test_behavioral_requires_a_real_month_end(self):
        self.assertEqual(
            observation_point(Scoring.BEHAVIORAL, snapshot_month_end=date(2026, 4, 30)),
            date(2026, 4, 30),
        )
        with self.assertRaises(ValueError):
            observation_point(Scoring.BEHAVIORAL, snapshot_month_end=date(2026, 4, 15))

    def test_month_end(self):
        self.assertEqual(month_end(date(2026, 2, 1)), date(2026, 2, 28))
        self.assertEqual(month_end(date(2028, 2, 1)), date(2028, 2, 29))
        self.assertEqual(month_end(date(2026, 12, 9)), date(2026, 12, 31))


class TestAlertPrecision(unittest.TestCase):
    def test_ratio(self):
        self.assertAlmostEqual(alert_precision(3, 12), 0.25)

    def test_empty_window_is_none_not_zero(self):
        self.assertIsNone(alert_precision(0, 0))

    def test_impossible_counts_rejected(self):
        with self.assertRaises(ValueError):
            alert_precision(5, 2)
        with self.assertRaises(ValueError):
            alert_precision(-1, 2)


class TestProvenance(unittest.TestCase):
    def test_spec_constants_carry_a_citation(self):
        self.assertIs(DEFAULT_DPD_THRESHOLD_DAYS.source, Source.SPEC)
        self.assertIn("Appendix A", DEFAULT_DPD_THRESHOLD_DAYS.citation)

    def test_policy_placeholders_refuse_to_be_read(self):
        for placeholder in (CONFIRMED_FRAUD_DISPOSITION_CODES, AGRI_SEASON_CALENDAR):
            with self.subTest(placeholder=str(placeholder)):
                self.assertIsInstance(placeholder, Pending)
                with self.assertRaises(Ungrounded):
                    _ = placeholder.value

    def test_placeholder_renders_in_tbd_form(self):
        self.assertEqual(str(AGRI_SEASON_CALENDAR), "TBD[Agri Credit Head, LH-102]")
        parsed = Pending.parse(str(AGRI_SEASON_CALENDAR))
        self.assertEqual(parsed, Pending(owner="Agri Credit Head", ticket="LH-102"))

    def test_malformed_placeholder_does_not_parse(self):
        self.assertIsNone(Pending.parse("TBD"))
        self.assertIsNone(Pending.parse("TBD[no ticket]"))


class TestRegister(unittest.TestCase):
    def test_every_appendix_a_term_is_present(self):
        expected = {
            "DPD",
            "Default / Bad",
            "Outcome window",
            "Observation point",
            "Indeterminate",
            "Confirmed fraud",
            "Agri season",
            "Alert precision",
        }
        self.assertEqual({entry.term for entry in REGISTER}, expected)

    def test_pending_terms_include_partly_computable_ones(self):
        # Default / Bad has a grounded binding (the DPD threshold is [SPEC]) but
        # three of its four arms need bank code sets. Treating it as resolved
        # because the threshold is known is how an uncomputable target definition
        # reaches P1 unnoticed.
        self.assertEqual(
            {entry.term for entry in pending_definitions()},
            {"Confirmed fraud", "Agri season", "Default / Bad"},
        )

    def test_default_bad_binding_is_grounded_but_the_term_is_not_resolved(self):
        entry = next(e for e in REGISTER if e.term == "Default / Bad")
        self.assertIs(entry.binding.source, Source.SPEC)
        self.assertTrue(entry.unresolved)
        self.assertEqual(len(entry.depends_on), 3)

    def test_appendix_a_version_is_recorded(self):
        self.assertEqual(DEFINITIONS_VERSION, "v1.1")

    def test_fingerprint_is_stable_and_versioned(self):
        # Pinned so that any edit to Appendix A fails here first and forces the
        # Model Risk Committee impact analysis (Master §4) to be acknowledged.
        self.assertEqual(fingerprint(), FROZEN_FINGERPRINT)
        self.assertEqual(fingerprint(), fingerprint())


FROZEN_FINGERPRINT = "4ead11219554b5f2"
"""Appendix A v1 content hash. Changing Appendix A changes this, which fails
TestRegister and forces the Master §4 impact analysis to be acknowledged
explicitly rather than slipping through as a green build."""


if __name__ == "__main__":
    unittest.main()

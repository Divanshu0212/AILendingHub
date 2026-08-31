"""Fannie Mae adapter tests (Track P — ADR-0004).

The adapter maps an external schema onto Appendix A. Every test here is about a
way that mapping can be wrong while still producing plausible numbers — which is
the dangerous failure mode for a dataset nobody eyeballs row by row.

Workstream: WS-0.1.1, WS-0.3.4
"""

import unittest
from datetime import date

from lending_hub.definitions import Label
from lending_hub.sources import fanniemae as fm

FIXTURE = "tests/fixtures/fanniemae/sample_performance.txt"
EXTRACT_END = date(2026, 3, 1)


class TestCodeMapping(unittest.TestCase):
    def test_delinquency_months_convert_to_appendix_a_days(self):
        # Fannie reports months; Appendix A is in days. Status 03 must land
        # exactly on the 90-day default threshold, or the label boundary moves.
        self.assertEqual(fm.dlq_to_dpd_days("00"), 0)
        self.assertEqual(fm.dlq_to_dpd_days("01"), 30)
        self.assertEqual(fm.dlq_to_dpd_days("02"), 60)
        self.assertEqual(fm.dlq_to_dpd_days("03"), 90)

    def test_status_03_is_bad_and_02_is_indeterminate(self):
        from lending_hub.definitions import OutcomeObservation, label

        self.assertIs(label(OutcomeObservation(max_dpd=fm.dlq_to_dpd_days("03"))), Label.BAD)
        self.assertIs(
            label(OutcomeObservation(max_dpd=fm.dlq_to_dpd_days("02"))), Label.INDETERMINATE
        )

    def test_unknown_status_is_none_not_zero(self):
        # Reading XX as 0 would relabel a servicer reporting gap as a performing
        # month — the easiest way to understate a default rate on this dataset.
        self.assertIsNone(fm.dlq_to_dpd_days("XX"))
        self.assertIsNone(fm.dlq_to_dpd_days(""))

    def test_prepayment_is_not_a_credit_loss(self):
        # Counting ZB 01 as a write-off would invert the label on most of the
        # 2019 vintage, which prepaid en masse.
        self.assertNotIn(fm.Disposition.PREPAID_OR_MATURED, fm.CREDIT_LOSS_DISPOSITIONS)

    def test_credit_loss_dispositions(self):
        for code in ("02", "03", "09"):
            with self.subTest(code=code):
                self.assertIn(fm.Disposition(code), fm.CREDIT_LOSS_DISPOSITIONS)
        for code in ("01", "06", "15", "16"):
            with self.subTest(code=code):
                self.assertNotIn(fm.Disposition(code), fm.CREDIT_LOSS_DISPOSITIONS)

    def test_mmyyyy_parsing(self):
        self.assertEqual(fm.parse_mmyyyy("012019"), date(2019, 1, 1))
        self.assertIsNone(fm.parse_mmyyyy("132019"))
        self.assertIsNone(fm.parse_mmyyyy(""))
        self.assertIsNone(fm.parse_mmyyyy("2019-01"))

    def test_money_is_integer_minor_units(self):
        self.assertEqual(fm._to_minor_units("324000.00"), 32_400_000)
        self.assertEqual(fm._to_minor_units("1234.5"), 123_450)
        self.assertEqual(fm._to_minor_units(""), 0)
        self.assertIsInstance(fm._to_minor_units("100.99"), int)


class TestLayoutVerification(unittest.TestCase):
    def test_fixture_matches_the_column_map(self):
        fm.verify_layout(FIXTURE, sample=100)

    def test_shifted_column_map_is_detected(self):
        # A field index one position out reads a plausible wrong column and every
        # downstream number is confidently wrong. The signature check is what
        # stops that being silent.
        original = fm.FIELDS["channel"]
        fm.FIELDS["channel"] = original + 1
        try:
            with self.assertRaises(fm.LayoutError):
                fm.verify_layout(FIXTURE, sample=100)
        finally:
            fm.FIELDS["channel"] = original

    def test_wrong_field_count_is_rejected(self):
        import tempfile, pathlib

        with tempfile.TemporaryDirectory() as tmp:
            bad = pathlib.Path(tmp) / "bad.txt"
            bad.write_text("a|b|c\n")
            with self.assertRaises(fm.LayoutError):
                list(fm.iter_rows(str(bad)))


class TestOutcomes(unittest.TestCase):
    def setUp(self):
        self.outcomes, self.summary = fm.build_outcomes(FIXTURE)

    def label(self, loan_id):
        return self.outcomes[loan_id].label(EXTRACT_END)

    def test_clean_loan_is_good(self):
        self.assertIs(self.label("LN00000000001"), Label.GOOD)

    def test_ninety_dpd_is_bad(self):
        self.assertIs(self.label("LN00000000002"), Label.BAD)

    def test_sixty_dpd_peak_is_indeterminate(self):
        self.assertIs(self.label("LN00000000003"), Label.INDETERMINATE)

    def test_prepaid_loan_is_determined_not_censored(self):
        # The 2019 vintage prepaid en masse in the 2020-21 refi wave. Excluding
        # prepayments would leave a sample of borrowers who *could not*
        # refinance — systematically worse credits.
        outcome = self.outcomes["LN00000000004"]
        self.assertTrue(outcome.outcome_determined(EXTRACT_END))
        self.assertIs(outcome.label(EXTRACT_END), Label.GOOD)

    def test_credit_loss_disposition_is_bad(self):
        self.assertIs(self.label("LN00000000005"), Label.BAD)

    def test_loan_with_no_observed_month_is_censored_not_good(self):
        # max_dpd == 0 here means "nothing seen", not "nothing happened".
        outcome = self.outcomes["LN00000000006"]
        self.assertEqual(outcome.months_known, 0)
        self.assertFalse(outcome.outcome_determined(EXTRACT_END))
        self.assertIsNone(outcome.label(EXTRACT_END))

    def test_summary_counts_reconcile(self):
        determined = sum(self.summary.labels.values())
        self.assertEqual(determined + self.summary.censored, self.summary.loans)

    def test_censored_loans_are_excluded_from_the_bad_rate(self):
        self.assertEqual(self.summary.labels.get(Label.BAD.value), 2)
        self.assertEqual(self.summary.censored, 1)

    def test_months_outside_the_window_do_not_contribute(self):
        # A delinquency in month 40 says nothing about a 12-month outcome.
        outcomes, _ = fm.build_outcomes(FIXTURE, outcome_months=1)
        self.assertLess(outcomes["LN00000000002"].max_dpd, 90)

    def test_window_length_is_a_parameter_not_a_constant(self):
        short, _ = fm.build_outcomes(FIXTURE, outcome_months=3)
        long, _ = fm.build_outcomes(FIXTURE, outcome_months=12)
        self.assertLess(short["LN00000000002"].max_dpd, long["LN00000000002"].max_dpd)


class TestTrackStamping(unittest.TestCase):
    def test_report_is_stamped_track_p_and_names_the_dataset(self):
        # ADR-0004: a number from real-but-not-our data must never read as gate
        # evidence.
        report = fm.build_outcomes(FIXTURE)[1].to_dict()
        self.assertEqual(report["track"], "P")
        self.assertEqual(report["dataset"], fm.DATASET)
        self.assertIn("not Phase 0 gate evidence", report["track_note"])

    def test_empty_extract_reports_no_rate(self):
        summary = fm.ExtractSummary()
        self.assertIsNone(summary.bad_rate)
        self.assertIsNone(summary.indeterminate_rate)


if __name__ == "__main__":
    unittest.main()

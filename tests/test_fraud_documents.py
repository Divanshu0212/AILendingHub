"""Tests for document checks v1 and the AA-first rule (WS-1.2 Step 5).

Workstream: WS-1.2 Step 5
"""

import unittest

from lending_hub.fraud.documents import (
    BRANCH_DIRECTORY,
    CheckStatus,
    ConsentPosture,
    DocumentCheckReport,
    DocumentError,
    SalarySlip,
    StatementMonth,
    aa_first_features,
    check_balance_continuity,
    check_ifsc,
    check_salary_slip,
    reconcile,
)


def slip(**kw):
    defaults = dict(
        employee_name="R K",
        period="2026-03",
        earnings={"basic": 5_000_000, "hra": 2_000_000},
        deductions={"pf": 600_000},
        stated_gross=7_000_000,
        stated_net=6_400_000,
    )
    defaults.update(kw)
    return SalarySlip(**defaults)


class TestSalarySlip(unittest.TestCase):
    def test_a_consistent_slip_passes_both_checks(self):
        results = check_salary_slip(slip())
        self.assertTrue(all(r.status is CheckStatus.PASS for r in results))

    def test_an_edited_earnings_line_breaks_the_gross_check(self):
        results = {r.check: r for r in check_salary_slip(slip(stated_gross=9_000_000))}
        self.assertIs(results["salary_slip_gross"].status, CheckStatus.FAIL)

    def test_an_edited_net_breaks_only_the_net_check(self):
        # A forger who edits one line usually breaks exactly one identity, which
        # is why these are two checks and not one.
        results = {r.check: r for r in check_salary_slip(slip(stated_net=6_300_000))}
        self.assertIs(results["salary_slip_gross"].status, CheckStatus.PASS)
        self.assertIs(results["salary_slip_net"].status, CheckStatus.FAIL)

    def test_a_missing_field_is_not_checkable_rather_than_failed(self):
        # A bad scan and a forgery must not arrive as the same finding.
        results = {r.check: r for r in check_salary_slip(slip(stated_net=None))}
        self.assertIs(results["salary_slip_net"].status, CheckStatus.NOT_CHECKABLE)

    def test_the_computed_values_are_carried_as_evidence(self):
        results = {r.check: r for r in check_salary_slip(slip(stated_net=1))}
        self.assertEqual(results["salary_slip_net"].evidence["computed"], 6_400_000)


class TestBalanceContinuity(unittest.TestCase):
    def months(self, **overrides):
        base = [
            StatementMonth("2026-01", 100_000, 150_000, 80_000, 30_000),
            StatementMonth("2026-02", 150_000, 140_000, 20_000, 30_000),
        ]
        for index, patch in overrides.items():
            base[int(index)] = patch
        return base

    def test_a_consistent_statement_passes_every_check(self):
        results = check_balance_continuity(self.months())
        self.assertTrue(all(r.status is CheckStatus.PASS for r in results))

    def test_an_edited_transaction_breaks_the_within_month_identity(self):
        broken = self.months()
        broken[0] = StatementMonth("2026-01", 100_000, 150_000, 60_000, 30_000)
        failures = [r for r in check_balance_continuity(broken) if r.failed]
        self.assertEqual(len(failures), 1)
        self.assertIn("month_arithmetic", failures[0].check)

    def test_an_edited_closing_balance_breaks_the_between_month_identity(self):
        # Inflating a closing balance to lift an average leaves the within-month
        # sums intact; only the carry-forward catches it.
        broken = [
            StatementMonth("2026-01", 100_000, 150_000, 80_000, 30_000),
            StatementMonth("2026-02", 900_000, 890_000, 20_000, 30_000),
        ]
        failures = [r for r in check_balance_continuity(broken) if r.failed]
        self.assertEqual(len(failures), 1)
        self.assertIn("continuity", failures[0].check)

    def test_a_single_month_has_no_continuity_check(self):
        results = check_balance_continuity(self.months()[:1])
        self.assertEqual(len(results), 1)

    def test_no_months_is_refused(self):
        with self.assertRaises(DocumentError):
            check_balance_continuity([])


class TestIFSC(unittest.TestCase):
    def test_a_well_formed_code_passes_the_format_check(self):
        self.assertIs(check_ifsc("HDFC0001234").status, CheckStatus.PASS)

    def test_a_missing_reserved_zero_fails(self):
        self.assertIs(check_ifsc("HDFCX001234").status, CheckStatus.FAIL)

    def test_a_short_code_fails(self):
        self.assertIs(check_ifsc("HDFC001").status, CheckStatus.FAIL)

    def test_lowercase_is_normalised_before_checking(self):
        self.assertIs(check_ifsc("hdfc0001234").status, CheckStatus.PASS)

    def test_an_absent_code_is_not_checkable(self):
        self.assertIs(check_ifsc("").status, CheckStatus.NOT_CHECKABLE)

    def test_a_pass_states_that_existence_was_not_checked(self):
        # A forger who knows the format passes the regex every time.
        result = check_ifsc("HDFC0001234")
        self.assertFalse(result.evidence["existence_checked"])
        self.assertIn("LH-210", result.detail)

    def test_the_directory_placeholder_names_its_owner(self):
        self.assertEqual(BRANCH_DIRECTORY.ticket, "LH-210")


class TestAAFirstRule(unittest.TestCase):
    def test_aa_wins_outright_when_both_exist(self):
        result = reconcile("income", aa_value=6_300_000, document_value=9_000_000)
        self.assertEqual(result.used_value, 6_300_000)
        self.assertEqual(result.source, "account_aggregator")
        self.assertTrue(result.disagreed)

    def test_agreement_is_not_recorded_as_disagreement(self):
        result = reconcile("income", aa_value=6_300_000, document_value=6_300_000)
        self.assertFalse(result.disagreed)

    def test_the_document_is_used_only_when_aa_is_absent(self):
        result = reconcile("income", aa_value=None, document_value=9_000_000)
        self.assertEqual(result.used_value, 9_000_000)
        self.assertEqual(result.source, "uploaded_document")

    def test_neither_source_yields_no_value(self):
        result = reconcile("income", aa_value=None, document_value=None)
        self.assertIsNone(result.used_value)
        self.assertEqual(result.source, "none")

    def test_aa_is_never_averaged_with_the_document(self):
        result = reconcile("income", aa_value=100, document_value=200)
        self.assertEqual(result.used_value, 100)
        self.assertNotEqual(result.used_value, 150)


class TestConsentPostureFeatures(unittest.TestCase):
    def test_refusing_aa_while_uploading_documents_is_a_signal(self):
        features = aa_first_features(ConsentPosture.REFUSED, documents_uploaded=2)
        self.assertEqual(features["aa_refused_with_documents"], 1.0)

    def test_granting_aa_is_not_that_signal(self):
        features = aa_first_features(ConsentPosture.GRANTED, documents_uploaded=2)
        self.assertEqual(features["aa_refused_with_documents"], 0.0)

    def test_never_being_offered_aa_is_not_a_refusal(self):
        features = aa_first_features(ConsentPosture.NOT_OFFERED, documents_uploaded=2)
        self.assertEqual(features["aa_refused_with_documents"], 0.0)

    def test_an_unrecorded_posture_emits_no_feature_at_all(self):
        # Defaulting to "not refused" would make every application from a flow
        # that forgot to log consent read as the innocent case.
        self.assertEqual(
            aa_first_features(ConsentPosture.UNKNOWN, documents_uploaded=2), {}
        )

    def test_contradictions_are_counted_as_a_feature(self):
        contradicted = reconcile("income", aa_value=1, document_value=2)
        agreed = reconcile("obligations", aa_value=3, document_value=3)
        features = aa_first_features(
            ConsentPosture.GRANTED, documents_uploaded=1,
            reconciliations=[contradicted, agreed],
        )
        self.assertEqual(features["aa_document_disagreements"], 1.0)


class TestReport(unittest.TestCase):
    def test_the_report_separates_failures_from_unreadable_fields(self):
        report = DocumentCheckReport(
            application_id="A1",
            results=check_salary_slip(slip(stated_net=1, stated_gross=None)),
            posture=ConsentPosture.GRANTED,
            documents_uploaded=1,
        )
        self.assertEqual(len(report.failures), 1)
        self.assertEqual(len(report.not_checkable), 1)

    def test_features_include_both_counts(self):
        report = DocumentCheckReport(
            application_id="A1",
            results=check_salary_slip(slip(stated_net=1)),
            posture=ConsentPosture.GRANTED,
        )
        features = report.features()
        self.assertEqual(features["doc_check_failures"], 1.0)
        self.assertEqual(features["doc_check_not_checkable"], 0.0)

    def test_the_report_states_tamper_detection_is_out_of_scope(self):
        payload = DocumentCheckReport("A1").to_dict()
        self.assertIn("Phase 6", payload["tamper_detection"])


if __name__ == "__main__":
    unittest.main()

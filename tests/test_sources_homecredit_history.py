"""Tests for the bureau and repayment-history aggregations (WS-1.1 Step 2).

Two behaviours carry the weight: absent is not zero, and a month that is not
strictly before the application does not count.

Workstream: WS-1.1 Step 2 · ADR-0004, ADR-0010
"""

import pathlib
import unittest

from lending_hub.sources.homecredit_history import (
    BUREAU_FEATURES,
    LATEST_SAFE_MONTHS_BALANCE,
    POS_FEATURES,
    RECENT_WINDOW_DAYS,
    HistoryError,
    load_bureau,
    load_pos_cash,
)

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures/homecredit"
BUREAU = str(FIXTURES / "bureau_sample.csv")
POS = str(FIXTURES / "pos_cash_sample.csv")


class TestBureau(unittest.TestCase):
    def setUp(self):
        self.agg, self.summary = load_bureau(BUREAU)

    def test_it_aggregates_one_row_per_applicant(self):
        self.assertEqual(sorted(self.agg), ["900001", "900002", "900003"])
        self.assertEqual(self.summary.rows_read, 5)

    def test_counts_split_active_from_closed(self):
        record = self.agg["900001"]
        self.assertEqual(record["bureau_record_count"], 3.0)
        self.assertEqual(record["bureau_active_count"], 2.0)
        self.assertEqual(record["bureau_closed_count"], 1.0)

    def test_file_age_is_the_oldest_record_as_a_positive_number(self):
        # DAYS_CREDIT is negative days before the application; file age is not.
        self.assertEqual(self.agg["900001"]["bureau_file_age_days"], 1800.0)
        self.assertEqual(self.agg["900001"]["bureau_days_since_last"], 100.0)

    def test_the_recent_counter_uses_the_declared_window(self):
        # Records at -200 and -100 days are inside a 365-day window; -1800 is not.
        self.assertEqual(RECENT_WINDOW_DAYS, 365)
        self.assertEqual(self.agg["900001"]["bureau_recent_count"], 2.0)

    def test_worst_delinquency_is_a_max_not_a_sum(self):
        self.assertEqual(self.agg["900001"]["bureau_max_days_overdue"], 12.0)
        self.assertEqual(self.agg["900001"]["bureau_max_amount_overdue"], 4500.0)

    def test_utilisation_with_no_denominator_is_none_not_zero(self):
        # Applicant 900003's only record has a blank AMT_CREDIT_SUM. An undefined
        # utilisation is not a utilisation of zero.
        self.assertIsNone(self.agg["900003"]["bureau_debt_ratio"])
        self.assertAlmostEqual(self.agg["900001"]["bureau_debt_ratio"], 75000.0 / 400000.0)

    def test_prolongations_and_live_arrears_are_counted(self):
        self.assertEqual(self.agg["900001"]["bureau_prolong_count"], 1.0)
        self.assertEqual(self.agg["900001"]["bureau_active_overdue_count"], 1.0)
        self.assertEqual(self.agg["900002"]["bureau_active_overdue_count"], 0.0)

    def test_every_declared_feature_is_produced(self):
        self.assertEqual(sorted(self.agg["900001"]), sorted(BUREAU_FEATURES))

    def test_every_feature_carries_a_rationale(self):
        # WS-1.1 Step 2: a feature nobody can justify cannot be defended to a
        # regulator, whatever its information value.
        for name, rationale in BUREAU_FEATURES.items():
            self.assertTrue(rationale.strip(), name)

    def test_restricting_to_known_keys_skips_the_rest(self):
        agg, _ = load_bureau(BUREAU, keys={"900002"})
        self.assertEqual(sorted(agg), ["900002"])

    def test_a_wrong_table_is_refused(self):
        with self.assertRaises(HistoryError):
            load_bureau(POS)


class TestPosCash(unittest.TestCase):
    def setUp(self):
        self.agg, self.summary = load_pos_cash(POS)

    def test_only_months_strictly_before_the_application_are_aggregated(self):
        # Applicant 900003's only row is MONTHS_BALANCE = 0, which the publisher
        # documents as "at application" — not certainly pre-decision.
        self.assertEqual(LATEST_SAFE_MONTHS_BALANCE, -1)
        self.assertNotIn("900003", self.agg)
        self.assertEqual(self.summary.rows_skipped_future, 1)

    def test_an_excluded_applicant_is_absent_not_zeroed(self):
        # 900003's excluded row carries SK_DPD 900. Zeroing it would turn the
        # worst applicant in the fixture into an unremarkable one.
        self.assertIsNone(self.agg.get("900003"))

    def test_dpd_max_and_mean_come_from_observed_months(self):
        record = self.agg["900001"]
        self.assertEqual(record["pos_months_observed"], 4.0)
        self.assertEqual(record["pos_max_dpd"], 60.0)
        self.assertAlmostEqual(record["pos_mean_dpd"], (0 + 45 + 60 + 0) / 4)

    def test_months_in_arrears_counts_months_not_days(self):
        self.assertEqual(self.agg["900001"]["pos_months_in_arrears"], 2.0)

    def test_the_tolerated_dpd_is_tracked_separately(self):
        # A payment late by the calendar but not by the contract is not arrears.
        self.assertEqual(self.agg["900001"]["pos_max_dpd_tolerated"], 30.0)

    def test_completed_prior_loans_are_counted(self):
        self.assertEqual(self.agg["900001"]["pos_completed_count"], 1.0)
        self.assertEqual(self.agg["900002"]["pos_completed_count"], 1.0)

    def test_every_declared_feature_is_produced(self):
        self.assertEqual(sorted(self.agg["900001"]), sorted(POS_FEATURES))

    def test_the_summary_records_the_point_in_time_limitation(self):
        payload = self.summary.to_dict()
        self.assertTrue(payload["point_in_time_unsafe"])
        self.assertIn("no absolute timeline", payload["note"])

    def test_a_wrong_table_is_refused(self):
        with self.assertRaises(HistoryError):
            load_pos_cash(BUREAU)


if __name__ == "__main__":
    unittest.main()

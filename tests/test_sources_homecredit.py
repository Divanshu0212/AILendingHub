"""Tests for the Home Credit adapter (WS-1.1 Steps 1-2, ADR-0010).

Runs on six hand-written fixture rows, one per adapter behaviour, so the suite
stays green on a clean clone with no 700 MB download.

Workstream: WS-1.1 Steps 1-2 · ADR-0004, ADR-0010
"""

import pathlib
import unittest
from datetime import date

from lending_hub.definitions import Label
from lending_hub.scoring.splits import SplitError, split_by_vintage
from lending_hub.scoring.target import LabelProvenance, build_target_table
from lending_hub.sources.homecredit import (
    DAYS_EMPLOYED_SENTINEL,
    NUMERIC_FEATURES,
    SOURCE_ID,
    TARGET_DEFINITION,
    HomeCreditError,
    age_band,
    load,
    to_applications,
)

FIXTURE = str(
    pathlib.Path(__file__).resolve().parent / "fixtures/homecredit/application_sample.csv"
)


class TestLoading(unittest.TestCase):
    def setUp(self):
        self.rows, self.labels, self.protected, self.summary = load(FIXTURE)

    def test_unlabelled_rows_are_skipped_and_counted(self):
        # Never labelled good. A row with no TARGET is not a performing loan.
        self.assertEqual(self.summary.kept, 5)
        self.assertEqual(self.summary.skipped_no_label, 1)
        self.assertNotIn("900006", self.protected)

    def test_the_base_rate_is_computed_over_labelled_rows_only(self):
        self.assertAlmostEqual(self.summary.base_rate, 2 / 5)

    def test_a_missing_numeric_becomes_none_plus_a_flag_not_a_zero(self):
        by_id = {row["application_id"]: row for row in self.rows}
        self.assertIsNone(by_id["900002"]["EXT_SOURCE_3"])
        self.assertEqual(by_id["900002"]["EXT_SOURCE_3_missing"], 1.0)
        self.assertEqual(by_id["900001"]["EXT_SOURCE_3_missing"], 0.0)

    def test_missingness_is_detected_per_column_not_per_row(self):
        by_id = {row["application_id"]: row for row in self.rows}
        self.assertEqual(by_id["900003"]["EXT_SOURCE_1_missing"], 1.0)
        self.assertEqual(by_id["900003"]["EXT_SOURCE_3_missing"], 0.0)

    def test_the_days_employed_sentinel_is_read_as_missing(self):
        # 365243 is exactly 1000 years and means "no employment record". Left
        # unhandled it dominates any scaled model as a tenure.
        by_id = {row["application_id"]: row for row in self.rows}
        self.assertIsNone(by_id["900004"]["DAYS_EMPLOYED"])
        self.assertEqual(by_id["900004"]["DAYS_EMPLOYED_missing"], 1.0)
        self.assertEqual(DAYS_EMPLOYED_SENTINEL, 365243)

    def test_out_of_range_values_are_clipped_to_the_declared_bounds(self):
        by_id = {row["application_id"]: row for row in self.rows}
        low, high = NUMERIC_FEATURES["AMT_INCOME_TOTAL"]
        self.assertLessEqual(by_id["900005"]["AMT_INCOME_TOTAL"], high)

    def test_derived_ratios_are_computed(self):
        by_id = {row["application_id"]: row for row in self.rows}
        self.assertAlmostEqual(
            by_id["900001"]["credit_to_income"], 406597.5 / 202500.0
        )

    def test_categoricals_are_one_hot_with_a_fixed_level_set(self):
        names = [n for n in self.summary.feature_names if n.startswith("NAME_CONTRACT_TYPE=")]
        self.assertEqual(sorted(names),
                         ["NAME_CONTRACT_TYPE=Cash loans", "NAME_CONTRACT_TYPE=Revolving loans"])

    def test_an_unlabelled_extract_is_refused(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "test.csv"
            path.write_text("SK_ID_CURR,AMT_CREDIT\n1,100\n", encoding="utf-8")
            with self.assertRaises(HomeCreditError) as caught:
                load(str(path))
            self.assertIn("application_test", str(caught.exception))


class TestProtectedAttributesAreSeparated(unittest.TestCase):
    def setUp(self):
        self.rows, self.labels, self.protected, self.summary = load(FIXTURE)

    def test_protected_attributes_never_enter_the_feature_rows(self):
        for row in self.rows:
            for banned in ("CODE_GENDER", "DAYS_BIRTH", "REGION_RATING_CLIENT",
                           "gender", "age_band", "pincode"):
                self.assertNotIn(banned, row)

    def test_they_come_back_as_a_separate_value(self):
        # Using gender as a feature has to require code that visibly merges two
        # dictionaries, not code that forgets to exclude a column.
        self.assertEqual(self.protected["900001"]["gender"], "M")

    def test_xna_gender_is_absent_not_a_third_group(self):
        # A fairness finding about a group that does not exist is worse than none.
        self.assertIsNone(self.protected["900004"]["gender"])
        self.assertEqual(self.summary.unknown_gender, 1)

    def test_age_bands_are_ten_year_buckets(self):
        self.assertEqual(age_band(-9461), "20-29")
        self.assertEqual(age_band(-16765), "40-49")

    def test_an_implausible_age_yields_no_band(self):
        self.assertIsNone(age_band(-1000))
        self.assertIsNone(age_band(None))

    def test_the_region_rating_stands_in_for_the_pincode_probe(self):
        self.assertEqual(self.protected["900001"]["pincode"], "2")


class TestTargetTableIntegration(unittest.TestCase):
    def setUp(self):
        self.rows, self.labels, _, _ = load(FIXTURE)
        self.applications = to_applications(
            self.rows, self.labels, decided_at=date(2018, 1, 1), vintage="no-time-axis"
        )

    def test_the_table_is_never_marked_appendix_a_aligned(self):
        table = build_target_table(
            self.applications, dataset=SOURCE_ID,
            provenance=LabelProvenance.VENDOR, label_note=TARGET_DEFINITION,
            require_enforceable=False,
        )
        self.assertFalse(table.manifest()["appendix_a_aligned"])
        self.assertIn("NOT Master Appendix A", table.label_note)

    def test_the_vendor_label_maps_to_bad_and_good(self):
        table = build_target_table(
            self.applications, dataset=SOURCE_ID,
            provenance=LabelProvenance.VENDOR, label_note=TARGET_DEFINITION,
            require_enforceable=False,
        )
        labels = {row.application_id: row.label for row in table.rows}
        self.assertIs(labels["900001"], Label.BAD)
        self.assertIs(labels["900002"], Label.GOOD)

    def test_every_phase_1_exclusion_is_unenforceable_on_this_source(self):
        # A public extract carries no fraud tag, staff flag or restructure code.
        table = build_target_table(
            self.applications, dataset=SOURCE_ID,
            provenance=LabelProvenance.VENDOR, label_note=TARGET_DEFINITION,
            require_enforceable=False,
        )
        self.assertEqual(
            sorted(table.ledger.unenforceable),
            ["FRAUD_TAGGED", "RESTRUCTURE", "STAFF_LOAN"],
        )

    def test_a_single_cohort_cannot_produce_an_out_of_time_split(self):
        # The whole reason to_applications assigns one constant vintage.
        table = build_target_table(
            self.applications, dataset=SOURCE_ID,
            provenance=LabelProvenance.VENDOR, label_note=TARGET_DEFINITION,
            require_enforceable=False,
        )
        with self.assertRaises(SplitError):
            split_by_vintage(table)


if __name__ == "__main__":
    unittest.main()

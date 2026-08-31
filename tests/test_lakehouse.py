"""Lakehouse layering and GL reconciliation tests.

Workstream: WS-0.1.2, WS-0.1.5
"""

import unittest

from lending_hub.lakehouse import Lakehouse, Layer, LayerViolation, TableSpec
from lending_hub.lakehouse.reconcile import (
    GL_TOLERANCE,
    AccountDelta,
    reconcile,
)


def table(name, layer, reads_from=(), **kw):
    return TableSpec(name=name, layer=layer, source_id="cbs", reads_from=reads_from, **kw)


class TestLayering(unittest.TestCase):
    def setUp(self):
        self.lake = Lakehouse()
        self.lake.register(table("bronze_cbs_loans", Layer.BRONZE))
        self.lake.register(table("silver_loans", Layer.SILVER, ("bronze_cbs_loans",)))

    def test_gold_may_read_silver(self):
        self.lake.register(table("gold_loan_features", Layer.GOLD, ("silver_loans",)))
        self.assertIn("gold_loan_features", self.lake.tables)

    def test_gold_may_not_read_bronze(self):
        # The recurring shortcut: it works, and it moves cleaning logic somewhere
        # nobody audits.
        with self.assertRaises(LayerViolation):
            self.lake.register(table("gold_shortcut", Layer.GOLD, ("bronze_cbs_loans",)))

    def test_bronze_may_not_read_anything(self):
        with self.assertRaises(LayerViolation):
            self.lake.register(table("bronze_derived", Layer.BRONZE, ("silver_loans",)))

    def test_time_travel_cannot_be_disabled(self):
        # Without versioning, SRS CS-7's 8-year reconstruction is physically
        # impossible, so this is a construction error rather than a config choice.
        with self.assertRaises(LayerViolation):
            table("silver_x", Layer.SILVER, time_travel=False)

    def test_unregistered_upstream_is_rejected(self):
        with self.assertRaises(LayerViolation):
            self.lake.register(table("silver_y", Layer.SILVER, ("bronze_missing",)))

    def test_duplicate_registration_is_rejected(self):
        with self.assertRaises(LayerViolation):
            self.lake.register(table("silver_loans", Layer.SILVER, ("bronze_cbs_loans",)))

    def test_lineage_is_transitive(self):
        self.lake.register(table("gold_features", Layer.GOLD, ("silver_loans",)))
        self.assertEqual(
            self.lake.lineage("gold_features"), ["silver_loans", "bronze_cbs_loans"]
        )

    def test_unclassified_pii_is_distinct_from_classified_false(self):
        # None means the DPO has not decided (LH-110); False means they have.
        self.lake.register(table("gold_a", Layer.GOLD, ("silver_loans",), contains_pii=False))
        self.assertNotIn("gold_a", self.lake.unclassified())
        self.assertIn("silver_loans", self.lake.unclassified())


class TestGlReconciliation(unittest.TestCase):
    MAPPING = {"HL": "GL-1000", "PL": "GL-2000"}

    def test_exact_match_passes(self):
        report = reconcile(
            [{"product_code": "HL", "balance_minor_units": 500_000_00}],
            {"GL-1000": 500_000_00},
            self.MAPPING, track="A", as_of="2026-06-30",
        )
        self.assertTrue(report.passed)
        self.assertEqual(report.deltas[0].relative_delta, 0.0)

    def test_delta_inside_tolerance_passes(self):
        report = reconcile(
            [{"product_code": "HL", "balance_minor_units": 1_000_000}],
            {"GL-1000": 1_000_500},
            self.MAPPING, track="A", as_of="2026-06-30",
        )
        self.assertLessEqual(report.deltas[0].relative_delta, GL_TOLERANCE)
        self.assertTrue(report.passed)

    def test_delta_outside_tolerance_fails(self):
        report = reconcile(
            [{"product_code": "HL", "balance_minor_units": 1_000_000}],
            {"GL-1000": 1_100_000},
            self.MAPPING, track="A", as_of="2026-06-30",
        )
        self.assertFalse(report.passed)

    def test_unmapped_product_fails_the_run(self):
        # An unmapped product drops balances out of the platform total and makes
        # the reconciliation look *better*, so it cannot be a mere note.
        report = reconcile(
            [
                {"product_code": "HL", "balance_minor_units": 1_000_000},
                {"product_code": "GOLD_LOAN", "balance_minor_units": 500_000},
            ],
            {"GL-1000": 1_000_000},
            self.MAPPING, track="A", as_of="2026-06-30",
        )
        self.assertEqual(report.unmapped_products, ["GOLD_LOAN"])
        self.assertFalse(report.passed)

    def test_float_amounts_are_rejected(self):
        with self.assertRaises(TypeError):
            reconcile(
                [{"product_code": "HL", "balance_minor_units": 1000.50}],
                {"GL-1000": 1000},
                self.MAPPING, track="A", as_of="2026-06-30",
            )

    def test_account_present_only_in_gl_is_surfaced(self):
        report = reconcile(
            [{"product_code": "HL", "balance_minor_units": 1_000_000}],
            {"GL-1000": 1_000_000, "GL-9999": 250_000},
            self.MAPPING, track="A", as_of="2026-06-30",
        )
        self.assertEqual(len(report.deltas), 2)
        self.assertFalse(report.passed)

    def test_zero_gl_balance_is_not_a_ratio(self):
        delta = AccountDelta("GL-1", platform_minor_units=0, gl_minor_units=0)
        self.assertIsNone(delta.relative_delta)
        self.assertTrue(delta.within_tolerance)
        self.assertFalse(AccountDelta("GL-1", 500, 0).within_tolerance)

    def test_empty_reconciliation_is_not_a_pass(self):
        report = reconcile([], {}, self.MAPPING, track="A", as_of="2026-06-30")
        self.assertFalse(report.passed)


if __name__ == "__main__":
    unittest.main()

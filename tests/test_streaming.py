"""Stream schema compatibility and freshness tests.

Workstream: WS-0.1.4
"""

import pathlib
import unittest
from datetime import UTC, datetime, timedelta

from lending_hub.streaming import (
    FRESHNESS_GATE,
    FreshnessReport,
    Schema,
    Severity,
    check_backward,
    is_backward_compatible,
)

SCHEMA_DIR = pathlib.Path("src/lending_hub/streaming/schemas")


def schema(*fields, name="Ev", version=1):
    return Schema.from_dict({"name": name, "version": version, "fields": list(fields)})


def field(name, type_, **extra):
    return {"name": name, "type": type_, **extra}


def breaking(issues):
    return [i for i in issues if i.severity is Severity.BREAKING]


class TestBackwardCompatibility(unittest.TestCase):
    def test_identical_schemas_are_compatible(self):
        old = new = schema(field("a", "string"))
        self.assertEqual(check_backward(old, new), [])

    def test_adding_a_field_with_a_default_is_allowed(self):
        old = schema(field("a", "string"))
        new = schema(field("a", "string"), field("b", ["null", "string"], default=None))
        self.assertTrue(is_backward_compatible(old, new))

    def test_adding_a_required_field_breaks(self):
        # Every message written before the field existed becomes unreadable.
        old = schema(field("a", "string"))
        new = schema(field("a", "string"), field("b", "string"))
        self.assertEqual(len(breaking(check_backward(old, new))), 1)

    def test_null_is_a_valid_default(self):
        # Membership, not truthiness — `default: null` is the commonest case and a
        # truthiness test would reject it.
        old = schema(field("a", "string"))
        new = schema(field("a", "string"), field("b", ["null", "string"], default=None))
        self.assertEqual(breaking(check_backward(old, new)), [])

    def test_removing_a_field_warns_but_does_not_break(self):
        # Readers cope; features derived from it stop updating without failing,
        # which is why this is surfaced rather than passed silently.
        old = schema(field("a", "string"), field("b", "string"))
        new = schema(field("a", "string"))
        issues = check_backward(old, new)
        self.assertEqual(breaking(issues), [])
        self.assertEqual([i.severity for i in issues], [Severity.WARNING])

    def test_safe_type_promotion_is_allowed(self):
        old = schema(field("amount", "int"))
        new = schema(field("amount", "long"))
        self.assertTrue(is_backward_compatible(old, new))

    def test_narrowing_a_type_breaks(self):
        old = schema(field("amount", "long"))
        new = schema(field("amount", "int"))
        self.assertEqual(len(breaking(check_backward(old, new))), 1)

    def test_unrelated_type_change_breaks(self):
        old = schema(field("amount", "long"))
        new = schema(field("amount", "boolean"))
        self.assertEqual(len(breaking(check_backward(old, new))), 1)

    def test_removing_a_default_breaks(self):
        old = schema(field("a", ["null", "string"], default=None))
        new = schema(field("a", ["null", "string"]))
        self.assertEqual(len(breaking(check_backward(old, new))), 1)

    def test_renaming_the_record_breaks(self):
        # A rename is a new topic, not an evolution.
        self.assertEqual(
            len(breaking(check_backward(schema(field("a", "string"), name="A"),
                                        schema(field("a", "string"), name="B")))),
            1,
        )

    def test_field_without_a_type_is_rejected(self):
        with self.assertRaises(ValueError):
            Schema.from_dict({"name": "Ev", "fields": [{"name": "a"}]})


class TestCommittedSchemas(unittest.TestCase):
    """The two Phase 0 streams, as committed."""

    def load(self, stem):
        return Schema.load(SCHEMA_DIR / f"{stem}_v1.json")

    def test_both_phase_0_streams_exist(self):
        self.assertEqual(self.load("repayment_posting").name, "RepaymentPosting")
        self.assertEqual(self.load("application_submission").name, "ApplicationSubmission")

    def test_every_stream_carries_both_timestamps(self):
        # Without created_timestamp no point-in-time join over this stream can be
        # correct (WS-0.2.1), so it is a schema-level requirement, not a
        # convention.
        for stem in ("repayment_posting", "application_submission"):
            with self.subTest(stem=stem):
                fields = self.load(stem).fields
                self.assertIn("event_timestamp", fields)
                self.assertIn("created_timestamp", fields)

    def test_money_is_integer_minor_units(self):
        # Binary floating point cannot represent monetary decimals exactly, and
        # the GL reconciliation is gated at 0.1%.
        amount = self.load("repayment_posting").fields["amount_minor_units"]
        self.assertEqual(amount["type"], "long")

    def test_every_stream_carries_an_idempotency_key(self):
        for stem in ("repayment_posting", "application_submission"):
            with self.subTest(stem=stem):
                self.assertIn("event_id", self.load(stem).fields)


class TestFreshness(unittest.TestCase):
    def report(self, *lags):
        report = FreshnessReport(topic="repayment.posting.v1", track="A")
        base = datetime(2026, 5, 1, tzinfo=UTC)
        for lag in lags:
            report.observe(base, base + timedelta(seconds=lag))
        return report

    def test_gate_matches_the_phase_doc(self):
        self.assertEqual(FRESHNESS_GATE, timedelta(seconds=60))

    def test_fast_stream_passes(self):
        self.assertTrue(self.report(*([2.0] * 100)).passed)

    def test_slow_tail_fails_even_with_a_fast_median(self):
        report = self.report(*([1.0] * 98 + [120.0, 130.0]))
        self.assertLess(report.percentile(50), 60)
        self.assertFalse(report.passed)

    def test_empty_window_is_not_a_pass(self):
        # An idle topic or a dead consumer must not read as "0 s lag, passing".
        report = self.report()
        self.assertIsNone(report.p99)
        self.assertFalse(report.passed)

    def test_negative_lag_is_rejected_as_a_clock_problem(self):
        report = FreshnessReport(topic="t", track="A")
        base = datetime(2026, 5, 1, tzinfo=UTC)
        with self.assertRaises(ValueError):
            report.observe(base, base - timedelta(seconds=5))

    def test_percentile_bounds(self):
        report = self.report(1.0, 2.0, 3.0)
        self.assertEqual(report.percentile(100), 3.0)
        with self.assertRaises(ValueError):
            report.percentile(0)


if __name__ == "__main__":
    unittest.main()

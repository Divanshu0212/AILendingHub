"""Source-registry schema tests.

The interesting cases are the negative ones: the schema exists to stop a plausible
but ungrounded registry entry from passing CI.

Workstream: WS-0.1.1
"""

import copy
import unittest

from lending_hub.registry import (
    ExtractMechanism,
    SourceKind,
    Status,
    load_registry,
    unresolved_policy_fields,
    validate_document,
)

VALID = {
    "schema_version": "1.0",
    "id": "cbs",
    "name": "Core Banking System",
    "kind": "internal",
    "srs_ref": "SRS §2.1 (S1)",
    "owner": {"business": "Head of Retail Ops", "technical": "CBS Lead"},
    "extract": {"mechanism": "cdc", "cadence": "continuous"},
    "classification": {"pii": "TBD[DPO, LH-110]", "residency": "india_only"},
    "point_in_time": {"event_timestamp": "posted_at", "created_timestamp": "cdc_at"},
    "retention": {"period": "TBD[DPO + Compliance, LH-111]"},
    "entities": ["customer_id", "loan_id"],
    "status": "pending_approval",
}


def doc(**overrides):
    d = copy.deepcopy(VALID)
    for dotted, value in overrides.items():
        parts = dotted.split("__")
        node = d
        for part in parts[:-1]:
            node = node[part]
        if value is _MISSING:
            node.pop(parts[-1], None)
        else:
            node[parts[-1]] = value
    return d


_MISSING = object()

#: Real external reference data (ADR-0004), registered but not bank sources.
TRACK_P_SOURCES = {"fannie_mae_sf_performance", "home_credit_default_risk"}


class TestValidDocument(unittest.TestCase):
    def test_accepts_a_complete_entry(self):
        record, errors = validate_document(doc(), "cbs.yaml")
        self.assertEqual(errors, [])
        self.assertEqual(record.id, "cbs")
        self.assertIs(record.kind, SourceKind.INTERNAL)
        self.assertIs(record.mechanism, ExtractMechanism.CDC)
        self.assertIs(record.status, Status.PENDING_APPROVAL)

    def test_tbd_fields_are_reported_as_unresolved_not_as_errors(self):
        record, errors = validate_document(doc(), "cbs.yaml")
        self.assertEqual(errors, [])
        self.assertEqual(
            set(record.unresolved), {"classification.pii", "retention.period"}
        )


class TestRejections(unittest.TestCase):
    def assert_fails_at(self, document, path):
        record, errors = validate_document(document, "x.yaml")
        self.assertIsNone(record)
        self.assertIn(path, [e.path for e in errors], msg=[str(e) for e in errors])

    def test_rejects_missing_required_field(self):
        self.assert_fails_at(doc(entities=_MISSING), "entities")

    def test_rejects_unknown_extract_mechanism(self):
        self.assert_fails_at(doc(extract__mechanism="magic"), "extract.mechanism")

    def test_rejects_missing_cadence(self):
        self.assert_fails_at(doc(extract__cadence=_MISSING), "extract.cadence")

    def test_rejects_missing_owner(self):
        self.assert_fails_at(doc(owner__technical=""), "owner.technical")

    def test_rejects_blank_policy_field(self):
        # The whole point: a [POLICY] value may not be quietly empty.
        self.assert_fails_at(doc(classification__pii=""), "classification.pii")

    def test_rejects_malformed_placeholder(self):
        # "TBD" with no owner and no ticket is exactly the shape that rots — it
        # looks handled but nobody owns it.
        self.assert_fails_at(doc(classification__pii="TBD"), "classification.pii")
        self.assert_fails_at(
            doc(retention__period="TBD[someone]"), "retention.period"
        )

    def test_rejects_missing_residency(self):
        # Residency is [SPEC] from SRS §12, so unlike PII it may not be a TBD.
        self.assert_fails_at(doc(classification__residency=_MISSING), "classification.residency")

    def test_rejects_missing_srs_citation(self):
        self.assert_fails_at(doc(srs_ref=""), "srs_ref")

    def test_rejects_wrong_schema_version(self):
        self.assert_fails_at(doc(schema_version="0.9"), "schema_version")

    def test_rejects_non_mapping(self):
        record, errors = validate_document(["not", "a", "mapping"], "x.yaml")
        self.assertIsNone(record)
        self.assertEqual(errors[0].path, "<root>")


class TestRealRegistry(unittest.TestCase):
    """The registry as committed must validate — this is the CI gate itself."""

    def setUp(self):
        try:
            import yaml  # noqa: F401
        except ModuleNotFoundError:
            self.skipTest("PyYAML not installed; pip install -r requirements-dev.txt")

    def test_committed_registry_is_valid(self):
        records, errors = load_registry("config/sources")
        self.assertEqual([str(e) for e in errors], [])
        self.assertGreaterEqual(len(records), 12)

    def test_identity_spine_sources_are_registered(self):
        records, _ = load_registry("config/sources")
        ids = {r.id for r in records}
        self.assertTrue({"cbs", "los", "collections"} <= ids)

    def test_every_srs_2_1_source_is_covered(self):
        records, _ = load_registry("config/sources")
        ids = {r.id for r in records}
        expected = {
            "cbs",                    # S1
            "bureau",                 # S2
            "account_aggregator",     # S3
            "satellite",              # S4
            "weather",                # S5
            "soil_geo",               # S6
            "kyc_documents_devices",  # S7
            "repayment_events",       # S8
            "los",                    # SRS §2.1 S9 (added in SRS v1.1)
            "collections",            # SRS §2.1 S10 (added in SRS v1.1)
        }
        self.assertEqual(expected - ids, set())

    def test_bank_source_policy_fields_are_all_still_pending(self):
        # Documents the true state of Phase 0: no [POLICY] value has been supplied
        # for any bank source. When one arrives this test changes, which is the
        # point — it makes policy progress visible in the diff.
        records, _ = load_registry("config/sources")
        bank = [r for r in records if r.id not in TRACK_P_SOURCES]
        pending = unresolved_policy_fields(bank)
        self.assertEqual(len(pending), 2 * len(bank))

    def test_track_p_sources_classify_pii_rather_than_deferring_it(self):
        # These are de-identified as published, with no linked borrower to
        # classify, so answering is correct here — deferring to the DPO would be
        # process theatre. Retention still defers, because redistribution terms
        # are a real question.
        records, _ = load_registry("config/sources")
        for record in records:
            if record.id in TRACK_P_SOURCES:
                with self.subTest(source=record.id):
                    self.assertEqual(record.unresolved, ("retention.period",))

    def test_track_p_sources_are_declared_point_in_time_unsafe(self):
        # Neither ships an ingestion timestamp, so honest declaration beats a
        # reconstructed one presented as native (SRS §11.1).
        records, _ = load_registry("config/sources")
        for record in records:
            if record.id in TRACK_P_SOURCES:
                with self.subTest(source=record.id):
                    self.assertIs(
                        record.raw["point_in_time"].get("point_in_time_unsafe"), True
                    )


if __name__ == "__main__":
    unittest.main()


class TestPointInTimeBlock(unittest.TestCase):
    """WS-0.1.1 / SRS §11.1: a source must be point-in-time declarable.

    This is the field extract teams drop because it looks redundant, and without
    it every historical join over the source leaks.
    """

    def pit_doc(self, **pit):
        d = copy.deepcopy(VALID)
        d["point_in_time"] = pit
        return d

    def test_missing_block_is_rejected(self):
        d = copy.deepcopy(VALID)
        d.pop("point_in_time", None)
        record, errors = validate_document(d, "x.yaml")
        self.assertIsNone(record)
        self.assertIn("point_in_time", [e.path for e in errors])

    def test_both_timestamps_accepted(self):
        _, errors = validate_document(
            self.pit_doc(event_timestamp="posted_at", created_timestamp="cdc_at"), "x.yaml"
        )
        self.assertEqual(errors, [])

    def test_missing_created_timestamp_is_rejected(self):
        # Silence is not allowed: a source is either point-in-time safe or
        # explicitly declared unsafe.
        _, errors = validate_document(self.pit_doc(event_timestamp="posted_at"), "x.yaml")
        self.assertIn("point_in_time.created_timestamp", [e.path for e in errors])

    def test_unsafe_must_be_declared_with_a_reason(self):
        _, errors = validate_document(
            self.pit_doc(event_timestamp="d", point_in_time_unsafe=True), "x.yaml"
        )
        self.assertIn("point_in_time.unsafe_reason", [e.path for e in errors])

    def test_unsafe_with_a_reason_is_accepted(self):
        _, errors = validate_document(
            self.pit_doc(
                event_timestamp="d", point_in_time_unsafe=True,
                unsafe_reason="state portals republish without versioning",
            ),
            "x.yaml",
        )
        self.assertEqual(errors, [])


class TestCommittedRegistryPointInTime(unittest.TestCase):
    def setUp(self):
        try:
            import yaml  # noqa: F401
        except ModuleNotFoundError:
            self.skipTest("PyYAML not installed")

    def test_every_source_declares_its_point_in_time_position(self):
        records, _ = load_registry("config/sources")
        for record in records:
            with self.subTest(source=record.id):
                pit = record.raw["point_in_time"]
                self.assertTrue(pit.get("event_timestamp"))
                self.assertTrue(
                    pit.get("created_timestamp") or pit.get("point_in_time_unsafe") is True
                )

    def test_point_in_time_unsafe_sources_are_exactly_the_declared_ones(self):
        # soil_geo: state portals republish without versioning. The two Track P
        # datasets: neither ships an ingestion timestamp, so knowability would
        # have to be reconstructed, and a reconstruction presented as native is
        # the leakage this whole rule exists to prevent (SRS §11.1).
        records, _ = load_registry("config/sources")
        unsafe = {
            r.id for r in records if r.raw["point_in_time"].get("point_in_time_unsafe") is True
        }
        self.assertEqual(
            unsafe,
            {"soil_geo", "fannie_mae_sf_performance", "home_credit_default_risk"},
        )

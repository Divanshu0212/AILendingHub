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
        self.assertGreaterEqual(len(records), 10)

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
            "los",                    # Phase 0 §2 inputs (not in SRS §2.1 — see LH-121)
            "collections",            # Phase 0 §2 inputs (not in SRS §2.1 — see LH-121)
        }
        self.assertEqual(expected - ids, set())

    def test_policy_fields_are_all_still_pending(self):
        # Documents the true state of Phase 0: no [POLICY] value has been supplied
        # yet. When one arrives this test changes, which is the point — it makes
        # policy progress visible in the diff.
        records, _ = load_registry("config/sources")
        pending = unresolved_policy_fields(records)
        self.assertEqual(len(pending), 2 * len(records))


if __name__ == "__main__":
    unittest.main()

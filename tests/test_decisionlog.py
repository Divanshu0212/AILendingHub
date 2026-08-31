"""Decision log and replay tests.

Workstream: Master §3.3
"""

import pathlib
import tempfile
import unittest
from datetime import UTC, datetime

from lending_hub.decisionlog import (
    Actor,
    DecisionLog,
    DecisionRecord,
    ModelRef,
    Outcome,
    ReasonCode,
    spot_audit,
)


def model(version="1.4.0"):
    return ModelRef(
        name="retail_pd",
        version=version,
        registry_stage="Production",
        code_commit="abc123",
        data_snapshot="train-2026-05",
        config_hash="cfg-9f",
        definitions_fingerprint="3e3ee82e78f7043a",
    )


def record(decision_id="D-1", **overrides):
    base = dict(
        decision_id=decision_id,
        decided_at=datetime(2026, 5, 1, tzinfo=UTC),
        subject_token="tok-abc",
        application_id="AP-1",
        outcome=Outcome.APPROVE,
        decided_by=Actor.MODEL,
        inputs={"requested_amount": 100000},
        feature_values={"bureau_score": 720},
        models=[model()],
        scores={"pd": 0.041},
        reason_codes=[ReasonCode("R01", contribution=-0.12)],
        policy_version="policy-2026.05",
    )
    base.update(overrides)
    return DecisionRecord(**base)


class TestRecordCompleteness(unittest.TestCase):
    def test_model_decision_must_name_its_models(self):
        with self.assertRaises(ValueError):
            record(models=[])

    def test_human_decision_must_record_the_override(self):
        with self.assertRaises(ValueError):
            record(decided_by=Actor.HUMAN, override=None)

    def test_human_decision_with_an_override_is_valid(self):
        rec = record(
            decided_by=Actor.HUMAN,
            override={"by": "u-42", "at": "2026-05-01T10:00:00Z",
                      "reason": "documented income", "replaced_outcome": "decline"},
        )
        self.assertEqual(rec.decided_by, Actor.HUMAN)

    def test_policy_version_is_required(self):
        # Without it nobody can tell years later which rule set was in force.
        with self.assertRaises(ValueError):
            record(policy_version="")

    def test_reason_codes_store_codes_not_wording(self):
        # Reason-code wording is [POLICY] from P1 onward; a record that stored
        # rendered text would freeze a sentence nobody approved.
        rec = record()
        self.assertFalse(hasattr(rec.reason_codes[0], "wording"))

    def test_record_carries_its_own_provenance(self):
        # Replayable by someone with none of today's context.
        m = record().models[0]
        for attribute in ("code_commit", "data_snapshot", "config_hash",
                          "definitions_fingerprint", "version"):
            self.assertTrue(getattr(m, attribute))


class TestHashChain(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.dir.name) / "decisions.jsonl"

    def tearDown(self):
        self.dir.cleanup()

    def test_chain_verifies_after_appends(self):
        log = DecisionLog(self.path)
        for i in range(5):
            log.append(record(f"D-{i}"))
        status = log.verify()
        self.assertTrue(status.valid)
        self.assertEqual(status.records, 5)

    def test_edited_record_is_detected(self):
        log = DecisionLog(self.path)
        for i in range(3):
            log.append(record(f"D-{i}"))
        lines = self.path.read_text().splitlines()
        lines[1] = lines[1].replace('"pd": 0.041', '"pd": 0.001')
        self.path.write_text("\n".join(lines) + "\n")
        status = log.verify()
        self.assertFalse(status.valid)
        self.assertEqual(status.broken_at, 1)
        self.assertIn("edited", status.detail)

    def test_removed_record_is_detected(self):
        log = DecisionLog(self.path)
        for i in range(4):
            log.append(record(f"D-{i}"))
        lines = self.path.read_text().splitlines()
        del lines[2]
        self.path.write_text("\n".join(lines) + "\n")
        self.assertFalse(log.verify().valid)

    def test_empty_log_verifies(self):
        self.assertTrue(DecisionLog(self.path).verify().valid)

    def test_reopened_log_continues_the_chain(self):
        DecisionLog(self.path).append(record("D-0"))
        DecisionLog(self.path).append(record("D-1"))
        self.assertTrue(DecisionLog(self.path).verify().valid)


class TestSpotAudit(unittest.TestCase):
    def entries(self, n=10):
        return [record(f"D-{i}").to_dict() for i in range(n)]

    def test_identical_replay_passes(self):
        report = spot_audit(self.entries(), lambda m, f: {"pd": 0.041}, seed=1)
        self.assertTrue(report.passed)
        self.assertEqual(report.match_rate, 1.0)

    def test_any_drift_fails_because_tolerance_is_zero(self):
        # A replay is a re-execution of the same model on the same inputs. A
        # tolerance would hide exactly the drift the audit exists to find.
        report = spot_audit(self.entries(), lambda m, f: {"pd": 0.0410001}, seed=1)
        self.assertFalse(report.passed)

    def test_unresolvable_model_version_is_its_own_finding(self):
        def scorer(model_ref, features):
            raise LookupError(f"version {model_ref['version']} not in registry")

        report = spot_audit(self.entries(3), scorer, seed=1)
        self.assertEqual(len(report.unreplayable), 3)
        self.assertFalse(report.passed)
        self.assertEqual(report.mismatches, [])

    def test_extra_replayed_score_is_a_mismatch(self):
        report = spot_audit(self.entries(1), lambda m, f: {"pd": 0.041, "lgd": 0.4}, seed=1)
        self.assertFalse(report.passed)

    def test_empty_sample_has_demonstrated_nothing(self):
        report = spot_audit([], lambda m, f: {}, seed=1)
        self.assertFalse(report.passed)
        self.assertIsNone(report.match_rate)

    def test_sampling_is_reproducible(self):
        entries = self.entries(50)
        a = spot_audit(entries, lambda m, f: {"pd": 0.041}, sample_size=5, seed=7)
        b = spot_audit(entries, lambda m, f: {"pd": 0.041}, sample_size=5, seed=7)
        self.assertEqual(a.to_dict(), b.to_dict())

    def test_replay_uses_stored_features_not_recomputed_ones(self):
        seen = []

        def scorer(model_ref, features):
            seen.append(features)
            return {"pd": 0.041}

        spot_audit(self.entries(1), scorer, seed=1)
        self.assertEqual(seen, [{"bureau_score": 720}])


if __name__ == "__main__":
    unittest.main()

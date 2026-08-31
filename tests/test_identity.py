"""Identity-spine tests.

Workstream: WS-0.1.3
"""

import unittest

from lending_hub.identity import (
    SYSTEM_OF_RECORD,
    Conflict,
    Entity,
    FailureCause,
    KeyProblem,
    RejectedKey,
    SpineKey,
    build_spine,
    normalise,
    resolve,
)
from lending_hub.identity.audit import JOIN_RATE_GATE, evaluate, run_track_a
from lending_hub.identity.ports import FixtureReader, InMemoryReader


class TestKeyNormalisation(unittest.TestCase):
    def test_trims_and_uppercases(self):
        key = normalise(Entity.LOAN, "  ln-1001 ")
        self.assertEqual(key, SpineKey(Entity.LOAN, "LN-1001"))

    def test_rejects_null_and_blank(self):
        for raw in (None, "", "   "):
            with self.subTest(raw=raw):
                self.assertEqual(normalise(Entity.LOAN, raw).problem, KeyProblem.NULL)

    def test_rejects_unknown_sentinels(self):
        # These join to each other and manufacture phantom matches, which is worse
        # than not joining at all.
        for raw in ("NA", "n/a", "UNKNOWN", "0", "-"):
            with self.subTest(raw=raw):
                self.assertEqual(normalise(Entity.LOAN, raw).problem, KeyProblem.PLACEHOLDER)

    def test_rejects_free_text_used_as_a_key(self):
        self.assertEqual(
            normalise(Entity.LOAN, "loan for Mr A").problem, KeyProblem.CHARSET
        )

    def test_rejects_truncated_key(self):
        self.assertEqual(normalise(Entity.LOAN, "X").problem, KeyProblem.TOO_SHORT)

    def test_normalisation_never_removes_characters(self):
        # Deleting punctuation would make LN-001 and LN001 join. That is a
        # similarity judgement, and WS-0.1.3 puts those in P1.
        a = normalise(Entity.LOAN, "LN-001")
        b = normalise(Entity.LOAN, "LN001")
        self.assertNotEqual(a, b)


class TestSpineJoin(unittest.TestCase):
    def spine(self, cbs, los, collections):
        return build_spine(
            InMemoryReader("cbs", cbs),
            InMemoryReader("los", los),
            InMemoryReader("collections", collections),
        )

    def test_clean_three_way_join(self):
        _, audit = self.spine(
            [{"loan_id": "LN-1", "customer_id": "CU-1", "is_active": "true"}],
            [{"loan_id": "LN-1", "customer_id": "CU-1", "application_id": "AP-1"}],
            [{"loan_id": "LN-1", "customer_id": "CU-1", "case_id": "CS-1"}],
        )
        self.assertEqual(audit.loan_to_application_rate, 1.0)
        self.assertEqual(audit.collections_to_loan_rate, 1.0)
        self.assertEqual(audit.customer_consistency_rate, 1.0)
        self.assertEqual(audit.failures, [])

    def test_healthy_loan_without_collections_is_not_a_failure(self):
        # The correction at the heart of this module (LH-122): requiring every
        # active loan to appear in collections would make the join rate track the
        # delinquency rate, so a healthy book would fail the gate.
        _, audit = self.spine(
            [{"loan_id": f"LN-{i}", "customer_id": "CU-1", "is_active": "true"} for i in range(50)],
            [
                {"loan_id": f"LN-{i}", "customer_id": "CU-1", "application_id": f"AP-{i}"}
                for i in range(50)
            ],
            [],
        )
        self.assertEqual(audit.loan_to_application_rate, 1.0)
        self.assertEqual(audit.failures, [])
        # No collections cases at all: nothing measured, so no rate — not 100%.
        self.assertIsNone(audit.collections_to_loan_rate)

    def test_missing_application_is_caught_and_named(self):
        _, audit = self.spine(
            [{"loan_id": "LN-9", "customer_id": "CU-9", "is_active": "true"}], [], []
        )
        self.assertEqual(audit.loan_to_application_rate, 0.0)
        self.assertEqual(audit.causes(), {FailureCause.MISSING_APPLICATION.value: 1})

    def test_orphan_collections_case_is_caught(self):
        _, audit = self.spine(
            [{"loan_id": "LN-1", "customer_id": "CU-1", "is_active": "true"}],
            [{"loan_id": "LN-1", "customer_id": "CU-1", "application_id": "AP-1"}],
            [{"loan_id": "LN-404", "customer_id": "CU-1", "case_id": "CS-1"}],
        )
        self.assertEqual(audit.collections_to_loan_rate, 0.0)
        self.assertIn(FailureCause.ORPHAN_COLLECTIONS_CASE.value, audit.causes())

    def test_customer_disagreement_is_caught(self):
        _, audit = self.spine(
            [{"loan_id": "LN-1", "customer_id": "CU-1", "is_active": "true"}],
            [{"loan_id": "LN-1", "customer_id": "CU-2", "application_id": "AP-1"}],
            [],
        )
        self.assertEqual(audit.customer_consistency_rate, 0.0)
        self.assertIn(FailureCause.CUSTOMER_DISAGREEMENT.value, audit.causes())

    def test_declined_application_is_not_an_orphan(self):
        # LOS carries applications that never became loans. The mandatory
        # direction is CBS -> LOS only.
        _, audit = self.spine(
            [{"loan_id": "LN-1", "customer_id": "CU-1", "is_active": "true"}],
            [
                {"loan_id": "LN-1", "customer_id": "CU-1", "application_id": "AP-1"},
                {"loan_id": "LN-DECLINED", "customer_id": "CU-2", "application_id": "AP-2"},
            ],
            [],
        )
        self.assertEqual(audit.failures, [])

    def test_inactive_loans_are_outside_the_denominator(self):
        _, audit = self.spine(
            [
                {"loan_id": "LN-1", "customer_id": "CU-1", "is_active": "true"},
                {"loan_id": "LN-2", "customer_id": "CU-2", "is_active": "false"},
            ],
            [{"loan_id": "LN-1", "customer_id": "CU-1", "application_id": "AP-1"}],
            [],
        )
        self.assertEqual(audit.loans_in_cbs, 1)
        self.assertEqual(audit.loan_to_application_rate, 1.0)

    def test_unusable_key_is_classified_not_silently_dropped(self):
        _, audit = self.spine(
            [{"loan_id": "NA", "customer_id": "CU-1", "is_active": "true"}], [], []
        )
        self.assertEqual(audit.loans_in_cbs, 0)
        self.assertIn(FailureCause.UNUSABLE_KEY.value, audit.causes())
        self.assertEqual(audit.rejected_keys["cbs.placeholder_key"], 1)

    def test_empty_portfolio_reports_no_rate_rather_than_perfection(self):
        _, audit = self.spine([], [], [])
        self.assertIsNone(audit.loan_to_application_rate)
        # ...and an unmeasurable rate is not a pass.
        self.assertTrue(all(not passed for _, _, passed in evaluate(audit)))


class TestSurvivorship(unittest.TestCase):
    def test_system_of_record_wins(self):
        conflict = Conflict(
            entity=Entity.CUSTOMER, key="CU-1", attribute="address",
            values={"cbs": "A", "collections": "B"},
        )
        resolution = resolve(conflict)
        self.assertEqual(resolution.winner, SYSTEM_OF_RECORD[Entity.CUSTOMER])
        self.assertEqual(resolution.value, "A")

    def test_missing_sor_value_does_not_silently_fall_back(self):
        # A quiet fallback to whichever source has a value *is* an undocumented
        # survivorship exception, which Phase 0 §8 forbids inventing.
        conflict = Conflict(
            entity=Entity.CUSTOMER, key="CU-1", attribute="address",
            values={"collections": "B", "los": "C"},
        )
        resolution = resolve(conflict)
        self.assertFalse(resolution.resolved)
        self.assertIn("LH-130", resolution.rule)


class TestFixtureAudit(unittest.TestCase):
    def test_fixtures_exercise_every_root_cause(self):
        # If a change stops detecting a cause, this fails rather than quietly
        # reporting a better join rate.
        _, audit = run_track_a(__import__("pathlib").Path("tests/fixtures/identity"))
        self.assertEqual(
            set(audit.causes()),
            {c.value for c in FailureCause},
        )

    def test_gate_threshold_matches_the_phase_doc(self):
        self.assertEqual(JOIN_RATE_GATE, 0.995)


class TestFixtureReaderGuard(unittest.TestCase):
    def test_refuses_to_read_outside_tests_fixtures(self):
        # Master §2 rule 3, enforced where the data would actually cross over.
        with self.assertRaises(ValueError):
            FixtureReader("cbs", "data/silver/cbs_loans.csv")

    def test_accepts_a_fixture_path(self):
        reader = FixtureReader("cbs", "tests/fixtures/identity/cbs_loans.csv")
        self.assertEqual(reader.track, "A")


if __name__ == "__main__":
    unittest.main()

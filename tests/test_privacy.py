"""Privacy tests — tokenization, consent, retention.

Workstream: WS-0.3.3
"""

import unittest
from datetime import UTC, datetime, timedelta

from lending_hub.definitions import Pending
from lending_hub.privacy import (
    MINIMUM_DECISION_RETENTION_YEARS,
    Basis,
    ConsentArtifact,
    ConsentError,
    DataCategory,
    Domain,
    Purpose,
    RetentionRule,
    Tokenizer,
    TokenizationError,
    load,
    tokenize_record,
    unresolved,
    validate,
)


def at(day):
    return datetime(2026, 6, day, tzinfo=UTC)


class TestTokenization(unittest.TestCase):
    def setUp(self):
        self.tok = Tokenizer.for_tests()

    def test_is_deterministic_so_joins_survive(self):
        self.assertEqual(
            self.tok.tokenize(Domain.CUSTOMER, "CU-1"),
            self.tok.tokenize(Domain.CUSTOMER, "CU-1"),
        )

    def test_domains_are_separated(self):
        # Same raw value in two contexts must not be linkable across them.
        self.assertNotEqual(
            self.tok.tokenize(Domain.CUSTOMER, "X-1").value,
            self.tok.tokenize(Domain.DEVICE, "X-1").value,
        )

    def test_different_keys_give_different_tokens(self):
        other = Tokenizer(b"a-completely-different-32-byte-key")
        self.assertNotEqual(
            self.tok.tokenize(Domain.CUSTOMER, "CU-1").value,
            other.tokenize(Domain.CUSTOMER, "CU-1").value,
        )

    def test_weak_key_is_rejected(self):
        with self.assertRaises(TokenizationError):
            Tokenizer(b"short")

    def test_missing_env_key_raises_rather_than_generating_one(self):
        # A generated key would produce tokens that silently do not match
        # yesterday's, breaking every join while appearing to work.
        import os

        saved = os.environ.pop("LENDING_HUB_TOKENIZATION_KEY", None)
        try:
            with self.assertRaises(TokenizationError):
                Tokenizer.from_env()
        finally:
            if saved is not None:
                os.environ["LENDING_HUB_TOKENIZATION_KEY"] = saved

    def test_empty_identifier_is_refused(self):
        for raw in (None, "", "   "):
            with self.subTest(raw=raw):
                with self.assertRaises(TokenizationError):
                    self.tok.tokenize(Domain.CUSTOMER, raw)

    def test_no_detokenize_on_the_forward_path(self):
        # Reversal belongs to a separately-permissioned vault. If it lived here,
        # re-identification would be one attribute access from any pipeline.
        self.assertFalse(hasattr(self.tok, "detokenize"))

    def test_key_is_not_in_repr(self):
        self.assertNotIn("test-only-key", repr(self.tok))

    def test_record_tokenization_leaves_unmapped_columns_alone(self):
        record = {"customer_id": "CU-1", "amount": 5000}
        out = tokenize_record(self.tok, record, {"customer_id": Domain.CUSTOMER})
        self.assertEqual(out["amount"], 5000)
        self.assertNotEqual(out["customer_id"], "CU-1")
        self.assertEqual(record["customer_id"], "CU-1")  # input not mutated


class TestConsent(unittest.TestCase):
    def artifact(self, **overrides):
        base = dict(
            consent_id="CN-1",
            customer_token="tok",
            purposes=frozenset({Purpose.CREDIT_ASSESSMENT}),
            categories=frozenset({DataCategory.BANK_STATEMENTS}),
            granted_at=at(1),
            expires_at=at(30),
            notice_version="aa-notice-v3",
        )
        base.update(overrides)
        return ConsentArtifact(**base)

    def test_permits_the_granted_purpose_in_window(self):
        self.assertTrue(
            self.artifact().permits(Purpose.CREDIT_ASSESSMENT, DataCategory.BANK_STATEMENTS, at(5))
        )

    def test_purpose_limitation_is_enforced(self):
        # Consent to assess an application does not authorise model training.
        self.assertFalse(
            self.artifact().permits(Purpose.MODEL_TRAINING, DataCategory.BANK_STATEMENTS, at(5))
        )

    def test_category_limitation_is_enforced(self):
        self.assertFalse(
            self.artifact().permits(Purpose.CREDIT_ASSESSMENT, DataCategory.TELCO, at(5))
        )

    def test_expiry_and_revocation(self):
        self.assertFalse(
            self.artifact().permits(Purpose.CREDIT_ASSESSMENT, DataCategory.BANK_STATEMENTS, at(30))
        )
        revoked = self.artifact(revoked_at=at(10))
        self.assertTrue(
            revoked.permits(Purpose.CREDIT_ASSESSMENT, DataCategory.BANK_STATEMENTS, at(9))
        )
        self.assertFalse(
            revoked.permits(Purpose.CREDIT_ASSESSMENT, DataCategory.BANK_STATEMENTS, at(11))
        )

    def test_evaluated_as_of_a_time_not_now(self):
        # A decision replayed years later must be judged against the consent in
        # force when it was made (Master §3.3).
        revoked = self.artifact(revoked_at=at(10))
        self.assertTrue(
            revoked.permits(Purpose.CREDIT_ASSESSMENT, DataCategory.BANK_STATEMENTS, at(2))
        )

    def test_before_grant_is_not_permitted(self):
        self.assertFalse(
            self.artifact().permits(
                Purpose.CREDIT_ASSESSMENT, DataCategory.BANK_STATEMENTS, at(1) - timedelta(days=1)
            )
        )

    def test_notice_version_is_required(self):
        # Without it the record proves a box was ticked, not what it said.
        with self.assertRaises(ConsentError):
            self.artifact(notice_version="")

    def test_empty_purposes_or_categories_rejected(self):
        with self.assertRaises(ConsentError):
            self.artifact(purposes=frozenset())
        with self.assertRaises(ConsentError):
            self.artifact(categories=frozenset())

    def test_require_raises_with_a_useful_message(self):
        with self.assertRaises(ConsentError) as ctx:
            self.artifact().require(Purpose.MODEL_TRAINING, DataCategory.BANK_STATEMENTS, at(5))
        self.assertIn("model_training", str(ctx.exception))


class TestRetention(unittest.TestCase):
    def test_decision_table_below_the_srs_floor_is_an_error(self):
        errors = validate([
            RetentionRule("decision_log", 3, Basis.AUDIT, carries_decisions=True)
        ])
        self.assertEqual(len(errors), 1)
        self.assertIn("CS-7", errors[0])

    def test_decision_table_at_the_floor_is_fine(self):
        self.assertEqual(
            validate([
                RetentionRule(
                    "decision_log", MINIMUM_DECISION_RETENTION_YEARS, Basis.AUDIT,
                    carries_decisions=True,
                )
            ]),
            [],
        )

    def test_regulatory_and_erasable_contradict(self):
        errors = validate([
            RetentionRule("t", 10, Basis.REGULATORY, erasable_on_request=True)
        ])
        self.assertEqual(len(errors), 1)

    def test_placeholder_period_is_not_an_error_but_is_unresolved(self):
        rules = [RetentionRule("t", Pending("DPO", "LH-111"), Basis.AUDIT)]
        self.assertEqual(validate(rules), [])
        self.assertEqual(len(unresolved(rules)), 1)

    def test_duplicate_table_is_an_error(self):
        errors = validate([
            RetentionRule("t", 10, Basis.AUDIT),
            RetentionRule("t", 12, Basis.AUDIT),
        ])
        self.assertEqual(len(errors), 1)


class TestCommittedRetentionConfig(unittest.TestCase):
    def setUp(self):
        try:
            import yaml  # noqa: F401
        except ModuleNotFoundError:
            self.skipTest("PyYAML not installed")

    def test_config_is_internally_consistent(self):
        self.assertEqual(validate(load("config/retention.yaml")), [])

    def test_every_period_is_still_pending_on_the_dpo(self):
        rules = load("config/retention.yaml")
        self.assertEqual(len(unresolved(rules)), len(rules))

    def test_decision_log_is_flagged_as_carrying_decisions(self):
        rules = {r.table: r for r in load("config/retention.yaml")}
        self.assertTrue(rules["decision_log"].carries_decisions)


if __name__ == "__main__":
    unittest.main()

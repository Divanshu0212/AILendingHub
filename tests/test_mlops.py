"""MLOps tests — triplet, promotion gate, reproducibility.

Workstream: WS-0.2.2, WS-0.2.3
"""

import unittest
from datetime import UTC, datetime, timedelta

from lending_hub.definitions import fingerprint
from lending_hub.mlops import (
    MINIMUM_SHADOW,
    InMemoryRegistry,
    ModelArtifact,
    Stage,
    Triplet,
    can_promote,
    config_hash,
)
from lending_hub.mlops.reproducibility_test import run

NOW = datetime(2026, 7, 1, tzinfo=UTC)


def artifact(**overrides):
    base = dict(
        name="retail_pd",
        version="1.0.0",
        triplet=Triplet("abc123", "train-2026-05", "cfg99"),
        definitions_fingerprint=fingerprint(),
        stage=Stage.STAGING,
        model_card_path="docs/models/retail_pd.md",
        validation_report_path="docs/validation/retail_pd.md",
        shadow_started_at=NOW - MINIMUM_SHADOW,
    )
    base.update(overrides)
    return ModelArtifact(**base)


def promote(target=Stage.PRODUCTION, via_ci=True, **overrides):
    return can_promote(artifact(**overrides), target, now=NOW, via_ci=via_ci)


class TestTriplet(unittest.TestCase):
    def test_every_element_is_mandatory(self):
        for missing in ("code_commit", "data_snapshot", "config_hash"):
            with self.subTest(missing=missing):
                parts = {"code_commit": "a", "data_snapshot": "b", "config_hash": "c"}
                parts[missing] = ""
                with self.assertRaises(ValueError):
                    Triplet(**parts)

    def test_config_hash_ignores_key_order_and_formatting(self):
        self.assertEqual(config_hash({"a": 1, "b": 2}), config_hash({"b": 2, "a": 1}))

    def test_config_hash_changes_with_content(self):
        self.assertNotEqual(config_hash({"epochs": 40}), config_hash({"epochs": 41}))


class TestPromotionGate(unittest.TestCase):
    def test_complete_artifact_promotes(self):
        self.assertTrue(promote())

    def test_none_to_production_is_refused(self):
        # The transition every incident report describes.
        decision = promote(stage=Stage.NONE)
        self.assertFalse(decision)
        self.assertTrue(any("not a legal transition" in r for r in decision.reasons))

    def test_manual_promotion_is_refused(self):
        decision = promote(via_ci=False)
        self.assertFalse(decision)
        self.assertTrue(any("CI pipeline" in r for r in decision.reasons))

    def test_missing_model_card_blocks_production(self):
        self.assertFalse(promote(model_card_path=None))

    def test_missing_validation_report_blocks_production(self):
        self.assertFalse(promote(validation_report_path=None))

    def test_short_shadow_blocks_production(self):
        decision = promote(shadow_started_at=NOW - timedelta(weeks=3))
        self.assertFalse(decision)
        self.assertTrue(any("short of the" in r for r in decision.reasons))

    def test_no_shadow_at_all_blocks_production(self):
        self.assertFalse(promote(shadow_started_at=None))

    def test_cold_fallback_path_blocks_production(self):
        decision = can_promote(
            artifact(), Stage.PRODUCTION, now=NOW, via_ci=True, fallback_path_warm=False
        )
        self.assertFalse(decision)

    def test_stale_definitions_fingerprint_blocks_production(self):
        # Appendix A moved under a trained model: Master §4 impact analysis is due
        # before it reaches customers.
        decision = promote(definitions_fingerprint="0000000000000000")
        self.assertFalse(decision)
        self.assertTrue(any("impact analysis" in r for r in decision.reasons))

    def test_all_blocking_reasons_are_returned_at_once(self):
        # One condition per attempt would make unblocking a guessing game.
        decision = can_promote(
            artifact(stage=Stage.NONE, model_card_path=None, shadow_started_at=None),
            Stage.PRODUCTION, now=NOW, via_ci=False,
        )
        self.assertGreaterEqual(len(decision.reasons), 4)

    def test_rollback_to_archived_is_always_legal(self):
        self.assertTrue(can_promote(artifact(stage=Stage.PRODUCTION), Stage.ARCHIVED,
                                    now=NOW, via_ci=True))

    def test_staging_needs_no_shadow_history(self):
        self.assertTrue(can_promote(
            artifact(stage=Stage.NONE, shadow_started_at=None, model_card_path=None),
            Stage.STAGING, now=NOW, via_ci=True,
        ))


class TestRegistry(unittest.TestCase):
    def test_registry_applies_the_gate_and_does_not_move_on_refusal(self):
        registry = InMemoryRegistry()
        registry.register(artifact(stage=Stage.NONE))
        decision = registry.transition("retail_pd", "1.0.0", Stage.PRODUCTION,
                                       via_ci=True, now=NOW)
        self.assertFalse(decision)
        self.assertIs(registry.get("retail_pd", "1.0.0").stage, Stage.NONE)

    def test_allowed_transition_moves_the_stage(self):
        registry = InMemoryRegistry()
        registry.register(artifact())
        self.assertTrue(registry.transition("retail_pd", "1.0.0", Stage.PRODUCTION,
                                            via_ci=True, now=NOW))
        self.assertIs(registry.get("retail_pd", "1.0.0").stage, Stage.PRODUCTION)

    def test_unknown_version_raises_lookup_error(self):
        with self.assertRaises(LookupError):
            InMemoryRegistry().get("nope", "1")


class TestReproducibility(unittest.TestCase):
    def test_reproducibility_contract_holds(self):
        # Both halves: same triplet -> identical metrics, and every triplet
        # element changes the model. Without the second half a constant function
        # would pass.
        passed, findings = run()
        self.assertTrue(passed, findings)


if __name__ == "__main__":
    unittest.main()

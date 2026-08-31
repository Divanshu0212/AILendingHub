"""Orchestrator, load-test and parity tests.

Workstream: WS-0.2.4, WS-0.4
"""

import unittest
from datetime import UTC, datetime, timedelta

from lending_hub.decisionlog import Actor, ModelRef, Outcome
from lending_hub.definitions import fingerprint
from lending_hub.featurestore import FeatureSource, FeatureSpec, FeatureValue, LocalFeatureStore
from lending_hub.serving import ModelUnavailable, Orchestrator, PolicyRule
from lending_hub.serving.loadtest import percentile, run
from lending_hub.serving.parity import PARITY_GATE, Discrepancy, compare

NOW = datetime(2026, 7, 1, tzinfo=UTC)


def store(value=5):
    spec = FeatureSpec("repayments_30d", ttl=timedelta(days=90), owner="DS", source_id="cbs")
    source = FeatureSource(spec)
    source.add("tok-1", FeatureValue(NOW - timedelta(days=1), NOW - timedelta(days=1), value))
    return LocalFeatureStore([source])


def model_ref():
    return ModelRef("stub", "0.0.0", "None", "c", "s", "h", fingerprint())


def orchestrator(scorer=lambda f: {"pd": 0.1}, rules=()):
    return Orchestrator(
        feature_store=store(), scorer=scorer, policy_rules=rules,
        model_ref=model_ref(), features=["repayments_30d"],
    )


APPLICATION = {"customer_token": "tok-1", "application_id": "AP-1"}


class TestPolicyPrecedence(unittest.TestCase):
    def test_a_firing_policy_rule_decides(self):
        # SRS §2.2: policy rules always take precedence over the model.
        rule = PolicyRule("R-KYC-01", "1.0", Outcome.DECLINE, lambda c: True, "POL_KYC_FAIL")
        response = orchestrator(rules=[rule]).decide(APPLICATION)
        self.assertIs(response.outcome, Outcome.DECLINE)
        self.assertIs(response.decided_by, Actor.POLICY_RULE)

    def test_the_model_is_still_scored_and_logged_when_policy_decides(self):
        # Overridability has to be evidenced, not asserted: the record shows what
        # the model said and that policy overrode it.
        rule = PolicyRule("R-KYC-01", "1.0", Outcome.DECLINE, lambda c: True, "POL_KYC_FAIL")
        response = orchestrator(rules=[rule]).decide(APPLICATION)
        self.assertEqual(response.record.scores, {"pd": 0.1})
        self.assertEqual(response.record.rules_fired, ["R-KYC-01@1.0"])

    def test_rules_see_features_not_just_the_application(self):
        rule = PolicyRule(
            "R-1", "1.0", Outcome.DECLINE, lambda c: c.get("repayments_30d") == 5, "POL"
        )
        self.assertIs(orchestrator(rules=[rule]).decide(APPLICATION).outcome, Outcome.DECLINE)


class TestDegradation(unittest.TestCase):
    def test_model_outage_degrades_to_refer_rather_than_raising(self):
        # SRS §12: if an AI engine is down the orchestrator falls back and queues
        # for re-score. A 500 here would be an availability breach.
        def unavailable(features):
            raise ModelUnavailable("model server timeout")

        response = orchestrator(scorer=unavailable).decide(APPLICATION)
        self.assertTrue(response.degraded)
        self.assertIs(response.decided_by, Actor.FALLBACK)
        self.assertIs(response.outcome, Outcome.REFER)

    def test_degraded_decision_records_no_model(self):
        def unavailable(features):
            raise ModelUnavailable("down")

        record = orchestrator(scorer=unavailable).decide(APPLICATION).record
        self.assertEqual(record.models, [])
        self.assertEqual([r.code for r in record.reason_codes], ["SYS_MODEL_UNAVAILABLE"])

    def test_policy_still_decides_while_the_model_is_down(self):
        def unavailable(features):
            raise ModelUnavailable("down")

        rule = PolicyRule("R-1", "1.0", Outcome.DECLINE, lambda c: True, "POL")
        response = Orchestrator(
            feature_store=store(), scorer=unavailable, policy_rules=[rule],
            model_ref=model_ref(), features=["repayments_30d"],
        ).decide(APPLICATION)
        self.assertIs(response.decided_by, Actor.POLICY_RULE)


class TestPhase0HasNoCutoffs(unittest.TestCase):
    def test_every_model_decision_refers(self):
        # Cutoffs are [POLICY] from P1. Referring everything is the only honest
        # behaviour for a platform with no approved decision boundary.
        response = orchestrator().decide(APPLICATION)
        self.assertIs(response.outcome, Outcome.REFER)
        self.assertEqual([r.code for r in response.reason_codes], ["P0_NO_CUTOFF_CONFIGURED"])

    def test_the_decision_record_is_complete_and_chainable(self):
        record = orchestrator().decide(APPLICATION).record
        self.assertTrue(record.policy_version)
        self.assertTrue(record.content_hash())
        self.assertNotIn("customer_token", record.inputs)  # token not duplicated into inputs


class TestLoadTest(unittest.TestCase):
    def test_percentiles(self):
        self.assertEqual(percentile([1.0, 2.0, 3.0, 4.0], 50), 2.0)
        self.assertEqual(percentile([1.0, 2.0, 3.0, 4.0], 100), 4.0)
        self.assertIsNone(percentile([], 99))

    def test_result_records_timings(self):
        result = run(orchestrator(), [APPLICATION] * 20)
        self.assertEqual(result.requests, 20)
        self.assertEqual(len(result.feature_fetch_ms), 20)

    def test_empty_run_is_not_a_pass(self):
        self.assertFalse(run(orchestrator(), []).passed)

    def test_errors_fail_the_run(self):
        class Boom:
            feature_store = None

            def decide(self, application):
                raise RuntimeError("boom")

        boom = Boom()
        boom.feature_store = store()
        result = run(boom, [APPLICATION] * 3)
        self.assertEqual(result.errors, 3)
        self.assertFalse(result.passed)


class TestParity(unittest.TestCase):
    SAMPLE = [{"application_id": f"AP-{i}"} for i in range(1000)]

    def parity(self, reference, candidate, sample=None):
        return compare(
            sample if sample is not None else self.SAMPLE,
            reference, candidate,
            track="A", reference_name="ref", candidate_name="cand",
        )

    def test_identical_paths_reach_full_parity(self):
        both = lambda row: {"outcome": "refer", "score": 0.5}  # noqa: E731
        report = self.parity(both, both)
        self.assertEqual(report.parity, 1.0)
        self.assertTrue(report.passed)

    def test_gate_matches_the_phase_doc(self):
        self.assertEqual(PARITY_GATE, 0.999)

    def test_one_outcome_difference_in_a_thousand_still_passes(self):
        def candidate(row):
            outcome = "decline" if row["application_id"] == "AP-0" else "refer"
            return {"outcome": outcome, "score": 0.5}

        report = self.parity(lambda r: {"outcome": "refer", "score": 0.5}, candidate)
        self.assertEqual(report.parity, 0.999)
        self.assertTrue(report.passed)

    def test_two_differences_in_a_thousand_fails(self):
        def candidate(row):
            outcome = "decline" if row["application_id"] in ("AP-0", "AP-1") else "refer"
            return {"outcome": outcome, "score": 0.5}

        report = self.parity(lambda r: {"outcome": "refer", "score": 0.5}, candidate)
        self.assertFalse(report.passed)

    def test_discrepancies_are_root_caused(self):
        def candidate(row):
            if row["application_id"] == "AP-0":
                return None
            if row["application_id"] == "AP-1":
                return {"outcome": "decline", "score": 0.5}
            if row["application_id"] == "AP-2":
                return {"outcome": "refer", "score": 0.7}
            return {"outcome": "refer", "score": 0.5}

        report = self.parity(lambda r: {"outcome": "refer", "score": 0.5}, candidate)
        self.assertEqual(
            report.root_causes(),
            {
                Discrepancy.MISSING_IN_CANDIDATE.value: 1,
                Discrepancy.OUTCOME_DIFFERS.value: 1,
                Discrepancy.SCORE_DIFFERS.value: 1,
            },
        )

    def test_a_raising_path_is_a_finding_not_a_crash(self):
        def candidate(row):
            raise RuntimeError("feature missing")

        report = self.parity(lambda r: {"outcome": "refer"}, candidate, sample=[{"application_id": "AP-0"}])
        self.assertEqual(report.root_causes(), {Discrepancy.ERROR.value: 1})

    def test_score_tolerance_is_zero_by_default(self):
        # WS-0.4 rebuilds the same logic, so any difference is a finding. A
        # tolerance would absorb exactly the feature-level divergence being
        # hunted.
        report = self.parity(
            lambda r: {"outcome": "refer", "score": 0.5},
            lambda r: {"outcome": "refer", "score": 0.5000001},
            sample=[{"application_id": "AP-0"}],
        )
        self.assertFalse(report.passed)

    def test_empty_sample_proves_nothing(self):
        report = self.parity(lambda r: None, lambda r: None, sample=[])
        self.assertIsNone(report.parity)
        self.assertFalse(report.passed)

    def test_missing_in_reference_is_classified_separately(self):
        # Often a sample-definition mismatch rather than a platform defect, and
        # conflating it with a dropped join sends people hunting the wrong bug.
        report = self.parity(
            lambda r: None, lambda r: {"outcome": "refer"},
            sample=[{"application_id": "AP-0"}],
        )
        self.assertEqual(report.root_causes(), {Discrepancy.MISSING_IN_REFERENCE.value: 1})


if __name__ == "__main__":
    unittest.main()

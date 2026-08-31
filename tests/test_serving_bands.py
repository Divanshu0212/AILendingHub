"""Tests for policy bands and the shipping ladder (Phase 1 §5).

Workstream: Phase 1 §5 · Master §3.2
"""

import unittest
from datetime import UTC, date, datetime

from lending_hub.decisionlog import Outcome
from lending_hub.definitions import Pending, Ungrounded
from lending_hub.serving.bands import (
    REQUIRED_APPROVERS,
    Approval,
    BandConfig,
    BandConfigError,
    canary_assignment,
    load_bands,
)
from lending_hub.serving.shadow import (
    MINIMUM_CANARY,
    MINIMUM_SHADOW,
    ShadowError,
    ShadowReport,
    canary_status,
    compare_day,
    shadow_status,
)

WHEN = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
BLOCKED = Pending(owner="Credit Risk Committee", ticket="LH-204")


def config(**kw):
    defaults = dict(
        model="application_pd",
        owner="Credit Risk Committee",
        status="test",
        approve_below=0.05,
        decline_above=0.20,
        canary_percentage=5.0,
        canary_band_low=0.05,
        canary_band_high=0.20,
        approvals=[
            Approval("alice", "Credit Risk Committee", WHEN),
            Approval("bob", "Model Risk", WHEN),
        ],
    )
    defaults.update(kw)
    return BandConfig(**defaults)


class TestShippedConfigIsUngrounded(unittest.TestCase):
    def setUp(self):
        try:
            self.config = load_bands()
        except BandConfigError as exc:  # pragma: no cover - PyYAML absent
            self.skipTest(str(exc))

    def test_every_band_edge_is_a_registered_placeholder(self):
        self.assertEqual(
            self.config.unresolved(),
            ["approve_below", "canary_band_high", "canary_band_low",
             "canary_percentage", "decline_above"],
        )

    def test_the_shipped_config_has_no_approvals(self):
        # An empty approvals list is the correct state for an unratified config,
        # not a formality waiting to be filled in.
        self.assertEqual(self.config.approvals, [])
        self.assertFalse(self.config.dual_control_satisfied)

    def test_it_cannot_decide_anything(self):
        self.assertFalse(self.config.effective)
        with self.assertRaises(Ungrounded) as caught:
            self.config.outcome_for(0.01)
        self.assertIn("LH-204", str(caught.exception))


class TestDualControl(unittest.TestCase):
    def test_two_distinct_approvers_satisfy_dual_control(self):
        self.assertTrue(config().dual_control_satisfied)
        self.assertEqual(REQUIRED_APPROVERS, 2)

    def test_the_same_person_signing_twice_does_not(self):
        # The control that catches a mistyped cutoff is the second person, not
        # the second signature.
        twice = config(approvals=[
            Approval("alice", "Credit Risk Committee", WHEN),
            Approval("alice", "Model Risk", WHEN),
        ])
        self.assertEqual(twice.distinct_approvers, 1)
        self.assertFalse(twice.dual_control_satisfied)

    def test_a_grounded_but_unapproved_config_refuses_to_decide(self):
        with self.assertRaises(BandConfigError):
            config(approvals=[]).outcome_for(0.01)

    def test_the_version_hash_covers_the_approvals(self):
        # A config re-approved by different people is a different governance
        # object even when the numbers are identical.
        first = config()
        second = config(approvals=[
            Approval("carol", "Credit Risk Committee", WHEN),
            Approval("dave", "Model Risk", WHEN),
        ])
        self.assertNotEqual(first.version(), second.version())

    def test_the_version_is_stable_for_identical_content(self):
        self.assertEqual(config().version(), config().version())


class TestOutcomes(unittest.TestCase):
    def test_the_three_bands_map_as_configured(self):
        bands = config()
        self.assertIs(bands.outcome_for(0.01), Outcome.APPROVE)
        self.assertIs(bands.outcome_for(0.10), Outcome.REFER)
        self.assertIs(bands.outcome_for(0.30), Outcome.DECLINE)

    def test_the_edges_belong_to_approve_and_decline(self):
        bands = config()
        self.assertIs(bands.outcome_for(0.05), Outcome.APPROVE)
        self.assertIs(bands.outcome_for(0.20), Outcome.DECLINE)

    def test_overlapping_cutoffs_are_refused_at_construction(self):
        with self.assertRaises(BandConfigError):
            config(approve_below=0.30, decline_above=0.20)

    def test_a_pd_outside_zero_one_is_refused(self):
        with self.assertRaises(BandConfigError):
            config().outcome_for(1.5)

    def test_the_canary_band_is_the_middle_of_the_range(self):
        bands = config()
        self.assertTrue(bands.in_canary_band(0.10))
        self.assertFalse(bands.in_canary_band(0.01))

    def test_an_unconfigured_canary_band_includes_nobody(self):
        bands = config(canary_band_low=BLOCKED, canary_band_high=BLOCKED)
        self.assertFalse(bands.in_canary_band(0.10))


class TestCanaryAssignment(unittest.TestCase):
    def test_assignment_is_stable_for_the_same_applicant(self):
        # A coin flip would move an applicant between arms on a retry and could
        # hand the same person two different decisions on the same day.
        bands = config()
        self.assertEqual(
            canary_assignment("APP-123", bands), canary_assignment("APP-123", bands)
        )

    def test_roughly_the_configured_share_lands_in_the_canary(self):
        bands = config(canary_percentage=10.0)
        share = sum(canary_assignment(f"APP-{i}", bands) for i in range(4000)) / 4000
        self.assertGreater(share, 0.07)
        self.assertLess(share, 0.13)

    def test_nobody_is_in_the_canary_while_the_percentage_is_policy_blocked(self):
        bands = config(canary_percentage=BLOCKED)
        self.assertFalse(any(canary_assignment(f"APP-{i}", bands) for i in range(200)))

    def test_an_out_of_range_percentage_is_refused(self):
        with self.assertRaises(BandConfigError):
            canary_assignment("APP-1", config(canary_percentage=140.0))


class TestOrchestratorWiring(unittest.TestCase):
    def orchestrator(self, bands):
        from lending_hub.decisionlog import ModelRef
        from lending_hub.definitions import fingerprint
        from lending_hub.featurestore import LocalFeatureStore
        from lending_hub.serving.orchestrator import Orchestrator

        return Orchestrator(
            feature_store=LocalFeatureStore([]),
            scorer=lambda features: {"pd": 0.01},
            bands=bands,
            model_ref=ModelRef(
                name="application_pd",
                version="1",
                registry_stage="staging",
                code_commit="test",
                data_snapshot="test",
                config_hash="test",
                definitions_fingerprint=fingerprint(),
            ),
        )

    def application(self):
        return {"customer_token": "tok-1", "application_id": "APP-1"}

    def test_an_effective_config_decides(self):
        response = self.orchestrator(config()).decide(self.application())
        self.assertIs(response.outcome, Outcome.APPROVE)
        self.assertEqual([r.code for r in response.reason_codes], ["BAND_APPROVE"])

    def test_ungrounded_cutoffs_refer_and_say_why(self):
        bands = config(approve_below=BLOCKED, decline_above=BLOCKED)
        response = self.orchestrator(bands).decide(self.application())
        self.assertIs(response.outcome, Outcome.REFER)
        self.assertEqual(
            [r.code for r in response.reason_codes], ["P1_CUTOFFS_NOT_RATIFIED"]
        )

    def test_missing_dual_control_is_a_distinct_reason_from_missing_cutoffs(self):
        # A control failure is not a scoring outcome and must not look like one.
        response = self.orchestrator(config(approvals=[])).decide(self.application())
        self.assertIs(response.outcome, Outcome.REFER)
        self.assertEqual(
            [r.code for r in response.reason_codes], ["P1_BANDS_NOT_DUAL_APPROVED"]
        )

    def test_no_config_at_all_keeps_the_phase_0_behaviour(self):
        response = self.orchestrator(None).decide(self.application())
        self.assertIs(response.outcome, Outcome.REFER)
        self.assertEqual(
            [r.code for r in response.reason_codes], ["P0_NO_CUTOFF_CONFIGURED"]
        )

    def test_the_decision_record_names_the_band_version_that_decided(self):
        bands = config()
        response = self.orchestrator(bands).decide(self.application())
        self.assertIn(bands.version(), response.record.policy_version)


class TestShippingLadder(unittest.TestCase):
    def test_shadow_needs_four_elapsed_weeks(self):
        self.assertEqual(MINIMUM_SHADOW.days, 28)
        short = shadow_status(date(2026, 3, 1), date(2026, 3, 20))
        self.assertFalse(short.duration_met)
        self.assertTrue(shadow_status(date(2026, 3, 1), date(2026, 3, 29)).duration_met)

    def test_an_unstarted_shadow_is_blocked(self):
        status = shadow_status(None, date(2026, 3, 1))
        self.assertIn("shadow has not started", status.blocking)
        self.assertFalse(status.may_advance)

    def test_canary_counts_clean_days_separately_from_elapsed(self):
        # A canary interrupted by an incident and restarted has not accumulated
        # four clean weeks however long it has been running.
        status = canary_status(
            date(2026, 3, 1), date(2026, 5, 1), traffic_fraction=0.05, clean_days=10
        )
        self.assertGreater(status.days_elapsed, MINIMUM_CANARY.days)
        self.assertFalse(status.may_advance)
        self.assertTrue(any("clean canary days" in reason for reason in status.blocking))

    def test_an_unconfigured_canary_percentage_blocks_advancement(self):
        status = canary_status(
            date(2026, 3, 1), date(2026, 5, 1), traffic_fraction=None, clean_days=40
        )
        self.assertTrue(any("LH-204" in reason for reason in status.blocking))

    def test_a_clean_canary_may_advance(self):
        status = canary_status(
            date(2026, 3, 1), date(2026, 4, 5), traffic_fraction=0.05, clean_days=35
        )
        self.assertTrue(status.may_advance)


class TestDailyComparison(unittest.TestCase):
    def day(self, **kw):
        import random
        rng = random.Random(1)
        training = [rng.random() for _ in range(2000)]
        live = [rng.random() for _ in range(400)]
        defaults = dict(
            training_scores=training,
            live_scores=live,
            champion_approves=[1 if s < 0.7 else 0 for s in live],
            challenger_approves=[1 if s < 0.65 else 0 for s in live],
            labels=[0] * len(live),
            fraud_alerts=4,
        )
        defaults.update(kw)
        return compare_day(date(2026, 3, 1), **defaults)

    def test_disagreement_is_reported(self):
        comparison = self.day()
        self.assertGreater(comparison.disagreement_rate, 0.0)
        self.assertLess(comparison.disagreement_rate, 0.2)

    def test_full_agreement_reports_zero_disagreement(self):
        # A shadow model agreeing everywhere has shown only that it was fitted on
        # the same data.
        import random
        rng = random.Random(2)
        live = [rng.random() for _ in range(300)]
        approvals = [1 if s < 0.7 else 0 for s in live]
        comparison = self.day(
            live_scores=live, champion_approves=approvals,
            challenger_approves=approvals, labels=[0] * len(live),
        )
        self.assertEqual(comparison.disagreement_rate, 0.0)

    def test_a_day_with_no_scored_applications_is_refused(self):
        with self.assertRaises(ShadowError):
            self.day(live_scores=[], champion_approves=[], challenger_approves=[],
                     labels=[])

    def test_the_report_refuses_to_compute_a_verdict(self):
        report = ShadowReport(
            "challenger", [self.day()], shadow_status(date(2026, 3, 1), date(2026, 3, 29))
        )
        payload = report.to_dict()
        self.assertIn("LH-204", payload["verdict"])
        self.assertIn("LH-206", payload["verdict"])

    def test_the_alert_rate_is_reported_against_the_volume_that_produced_it(self):
        comparison = self.day(fraud_alerts=4)
        self.assertAlmostEqual(comparison.fraud_alert_rate, 4 / comparison.scored)


if __name__ == "__main__":
    unittest.main()

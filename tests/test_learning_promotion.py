"""The standing promotion criterion — Phase 6 §4.

These tests pin the behaviour that makes §4 a rule rather than a checklist: that
out-of-time is *checked* rather than trusted, that a feasible-but-skipped A/B
blocks a promotion whose artifact is otherwise perfect, and that every failing
reason comes back in one call.

They deliberately do not pin a minimum lift. §4 says "measured", each workstream
names its own comparative gate, and none is quantified (LH-801) — a test
asserting a threshold would be inventing one.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from lending_hub.definitions import fingerprint
from lending_hub.learning.promotion import (
    AbTestFeasibility,
    EvaluationWindow,
    LiftMeasurement,
    PromotionError,
    PromotionRequest,
    RollbackPlan,
    evaluate_promotion,
)
from lending_hub.mlops.artifact import ModelArtifact, Stage, Triplet

NOW = datetime(2026, 9, 2)


def _artifact(**overrides) -> ModelArtifact:
    """An artifact that passes every Phase 0 condition, so §4 is what is tested."""
    defaults = dict(
        name="ews-challenger",
        version="3",
        triplet=Triplet(
            code_commit="a" * 40, data_snapshot="snap-2026-08", config_hash="c" * 12
        ),
        definitions_fingerprint=fingerprint(),
        stage=Stage.STAGING,
        model_card_path="docs/phase6/model_cards/x.md",
        validation_report_path="docs/governance/validation/x.md",
        shadow_started_at=NOW - timedelta(weeks=6),
    )
    defaults.update(overrides)
    return ModelArtifact(**defaults)


def _window(out_of_time: bool = True) -> EvaluationWindow:
    train_end = datetime(2026, 1, 1)
    start = train_end if out_of_time else train_end - timedelta(days=45)
    return EvaluationWindow(
        train_end=train_end, eval_start=start, eval_end=datetime(2026, 6, 1)
    )


def _request(**overrides) -> PromotionRequest:
    defaults = dict(
        artifact=_artifact(),
        target=Stage.PRODUCTION,
        lift=LiftMeasurement(
            metric="recall@budget",
            champion=0.41,
            challenger=0.47,
            window=_window(),
            population="retail unsecured, all vintages",
        ),
        rollback=RollbackPlan(
            trigger="alert precision below the ratified floor for 3 days",
            owner="EWS on-call",
            rehearsed_on=NOW - timedelta(days=20),
        ),
        ab_test=AbTestFeasibility.RAN,
        submitted_by="ews-squad-lead",
    )
    defaults.update(overrides)
    return PromotionRequest(**defaults)


class TheHappyPath(unittest.TestCase):
    def test_a_complete_request_is_allowed(self):
        decision = evaluate_promotion(_request(), now=NOW, via_ci=True)
        self.assertTrue(decision, decision.reasons)
        self.assertEqual(decision.evidence_reasons, [])


class OutOfTimeIsCheckedNotTrusted(unittest.TestCase):
    """The condition a submitter most often violates while believing otherwise.

    A random split of a three-year panel is out-of-sample and in-time, and it
    produces the optimistic number P4-F11 and Phase 3's in-sample comparison
    both describe. Checking the dates is what separates the two.
    """

    def test_an_overlapping_window_blocks_promotion(self):
        request = _request(
            lift=LiftMeasurement(
                metric="recall@budget",
                champion=0.41,
                challenger=0.47,
                window=_window(out_of_time=False),
                population="retail unsecured",
            )
        )
        decision = evaluate_promotion(request, now=NOW, via_ci=True)
        self.assertFalse(decision)
        self.assertTrue(any("out-of-time" in r for r in decision.reasons))

    def test_the_overlap_is_reported_in_days(self):
        window = _window(out_of_time=False)
        self.assertEqual(window.overlap_days, 45)
        self.assertFalse(window.is_out_of_time)

    def test_a_window_starting_exactly_at_train_end_is_out_of_time(self):
        """A model fitted through train_end has seen nothing after it."""
        self.assertTrue(_window().is_out_of_time)
        self.assertEqual(_window().overlap_days, 0)

    def test_a_backwards_window_is_incoherent_rather_than_failing(self):
        with self.assertRaises(PromotionError):
            EvaluationWindow(
                train_end=datetime(2026, 1, 1),
                eval_start=datetime(2026, 6, 1),
                eval_end=datetime(2026, 3, 1),
            )


class TheABSentence(unittest.TestCase):
    """§4's final sentence, which is a rule about admissible evidence.

    It does not require an A/B. It makes offline lift inadmissible *as the sole
    evidence* where an A/B was feasible and skipped — so the gate's question is
    "was one available?", not "did you run one?".
    """

    def test_a_feasible_but_skipped_ab_blocks_an_otherwise_perfect_request(self):
        request = _request(ab_test=AbTestFeasibility.FEASIBLE_NOT_RUN)
        decision = evaluate_promotion(request, now=NOW, via_ci=True)
        self.assertFalse(decision)
        self.assertEqual(len(decision.evidence_reasons), 1)
        self.assertIn("inadmissible", decision.evidence_reasons[0])

    def test_infeasible_is_allowed_when_a_reason_is_stated(self):
        request = _request(
            ab_test=AbTestFeasibility.INFEASIBLE,
            ab_infeasible_reason="single-tenant product, no concurrent cohort exists",
        )
        self.assertTrue(evaluate_promotion(request, now=NOW, via_ci=True))

    def test_infeasible_without_a_reason_cannot_be_constructed(self):
        """An unexplained infeasibility claim is how a standing rule becomes a
        formality — so it fails at construction, not at review."""
        with self.assertRaises(PromotionError) as caught:
            _request(ab_test=AbTestFeasibility.INFEASIBLE)
        self.assertIn("ab_infeasible_reason", str(caught.exception))

    def test_a_request_needs_a_submitter(self):
        with self.assertRaises(PromotionError):
            _request(submitted_by="   ")


class TheRollbackPlan(unittest.TestCase):
    def test_a_missing_plan_blocks(self):
        decision = evaluate_promotion(_request(rollback=None), now=NOW, via_ci=True)
        self.assertFalse(decision)
        self.assertTrue(any("rollback" in r for r in decision.reasons))

    def test_an_unrehearsed_plan_blocks(self):
        """An unrehearsed procedure is a hypothesis, and it is tested at the
        worst possible moment."""
        request = _request(
            rollback=RollbackPlan(trigger="precision drop", owner="on-call")
        )
        decision = evaluate_promotion(request, now=NOW, via_ci=True)
        self.assertFalse(decision)
        self.assertTrue(any("rehearsed" in r for r in decision.reasons))


class EveryReasonComesBackAtOnce(unittest.TestCase):
    def test_artifact_and_evidence_failures_are_reported_together(self):
        """A team that learns one blocker per run learns the gate one week at a time."""
        request = _request(
            artifact=_artifact(model_card_path=None, shadow_started_at=None),
            lift=None,
            rollback=None,
            ab_test=AbTestFeasibility.FEASIBLE_NOT_RUN,
        )
        decision = evaluate_promotion(request, now=NOW, via_ci=False)
        self.assertFalse(decision)
        self.assertGreaterEqual(len(decision.reasons), 6)

    def test_artifact_and_evidence_reasons_stay_distinguishable(self):
        """They go to different people: one to the model owner, one to whoever
        ran the evaluation."""
        request = _request(artifact=_artifact(model_card_path=None), rollback=None)
        decision = evaluate_promotion(request, now=NOW, via_ci=True)
        self.assertTrue(any("model card" in r for r in decision.artifact_decision.reasons))
        self.assertTrue(any("rollback" in r for r in decision.evidence_reasons))
        self.assertNotIn(
            decision.evidence_reasons[0], decision.artifact_decision.reasons
        )


class StagingIsNotSubjectToTheStandingCriterion(unittest.TestCase):
    def test_promotion_to_staging_needs_no_lift(self):
        """Staging is how a model reaches somewhere it can be evaluated.

        Requiring measured lift for it would forbid the step that produces the
        evidence the rule demands.
        """
        request = _request(
            artifact=_artifact(stage=Stage.NONE),
            target=Stage.STAGING,
            lift=None,
            rollback=None,
        )
        decision = evaluate_promotion(request, now=NOW, via_ci=True)
        self.assertTrue(decision, decision.reasons)
        self.assertEqual(decision.evidence_reasons, [])


class LiftArithmetic(unittest.TestCase):
    def test_lift_is_a_difference_not_a_ratio(self):
        """A percentage lift on a metric that can approach zero reports a large
        number from a tiny absolute move."""
        lift = LiftMeasurement(
            metric="recall@budget",
            champion=0.41,
            challenger=0.47,
            window=_window(),
            population="retail",
        )
        self.assertAlmostEqual(lift.lift, 0.06, places=10)


if __name__ == "__main__":
    unittest.main()

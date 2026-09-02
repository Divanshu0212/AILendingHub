"""The standing promotion criterion — Phase 6 §4.

Phase 6 §4 is one sentence and it is the most reusable artifact in the phase:

    Measured lift on out-of-time data · model card · independent validation ·
    rollback plan · online A/B where feasible. **Offline lift alone never
    promotes a model that could have been A/B tested.**

It is called *standing* because it does not expire at a gate review. Every
promotion, forever, is subject to it — which makes it the one Phase 6 artifact
Track B needs unchanged, and the reason this module exists before any challenger
does. A promotion rule written under pressure by whoever is shipping the first
challenger is a promotion rule shaped by that challenger.

Why this is not simply more conditions in ``mlops.promotion``
--------------------------------------------------------------
Phase 0's :func:`~lending_hub.mlops.promotion.can_promote` answers *"is this
registry transition legal?"* — card present, validation report present, shadow
long enough, fallback warm, definitions fingerprint current. Those are
properties of an **artifact**.

Phase 6 asks a different question: *"is the evidence offered for this promotion
admissible?"* That is a property of an **evaluation**, and it can fail on a
model whose artifact is impeccable. A challenger with a card, a validation
report and six weeks of shadow, whose lift was measured on the window it was
tuned on, passes every Phase 0 condition and must still be refused.

So this module composes rather than replaces: :func:`evaluate_promotion` runs
the Phase 0 gate and adds the §4 conditions, returning one list of reasons. A
team learns everything blocking them in one run.

The condition that is a rule about evidence, not a threshold
--------------------------------------------------------------
Four of the five conditions are presence checks. The fifth — *"offline lift
alone never promotes a model that could have been A/B tested"* — is different in
kind, and it is the one worth stating carefully because it is easy to implement
backwards.

It does **not** say an A/B is required. It says that where an A/B was *feasible*
and was not run, offline lift is inadmissible as the sole evidence. So the
question the gate asks is not "did you run an A/B?" but "was one available to
you?" — and a submitter answering "no" is making a claim that gets recorded with
their name on it. `AbTestFeasibility.INFEASIBLE` therefore requires a stated
reason, because "we could not A/B test this" with no reason attached is the
sentence that turns a standing rule into a formality.

What this module does not decide
----------------------------------
**How much lift is enough.** No minimum appears here and none is defaulted. The
§4 sentence says *measured*, not *sufficient*, and each workstream names its own
comparative gate (WS-6.1 "+recall at the fixed alert budget", WS-6.4 "Qini
coefficient + online cure-rate lift") — none of them quantified, all of them
`[POLICY]`. A default here would become the number every promotion was judged
against, chosen by whoever typed it. LH-801.

**Whether the lift is real.** A confidence interval that excludes zero is a
statistical question this module does not answer; it checks that the evaluation
was out-of-time, which is the property a submitter can most easily get wrong
while believing they got it right.

Workstream: WS-6.7 · Phase 6 §4
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from lending_hub.mlops.artifact import ModelArtifact, Stage
from lending_hub.mlops.promotion import PromotionDecision, can_promote


class PromotionError(Exception):
    """Raised when a promotion request cannot be *constructed* coherently.

    Distinct from a refused promotion, which is a returned decision. A request
    claiming an out-of-time evaluation whose window precedes its training window
    is not a failing request — it is an incoherent one, and returning "refused"
    would suggest a threshold might fix it.
    """


class AbTestFeasibility(str, Enum):
    """Whether an online A/B was available for this promotion.

    Three states rather than two. "Not run" and "not possible" are the same
    checkbox to a submitter in a hurry and completely different facts to a
    reviewer, which is precisely the distinction Phase 6 §4's final sentence
    turns on.
    """

    RAN = "ran"
    """An online A/B was run. Its result is the primary evidence."""

    FEASIBLE_NOT_RUN = "feasible_not_run"
    """An A/B was available and was not run. §4 makes offline lift inadmissible
    as the sole evidence in this state — this is the case the sentence exists
    for."""

    INFEASIBLE = "infeasible"
    """No A/B was available. Requires a stated reason, recorded against the
    submitter."""


@dataclass(frozen=True)
class EvaluationWindow:
    """The period an evaluation was measured over.

    Out-of-time is checked here rather than asserted by the submitter, because
    it is the condition most often violated by someone who believes they
    satisfied it — a random split of a panel spanning three years is
    out-of-sample and in-time, and it produces the optimistic number Phase 3's
    findings and P4-F11 both describe.
    """

    train_end: datetime
    """Last observation the model was fitted on."""

    eval_start: datetime
    eval_end: datetime

    def __post_init__(self) -> None:
        if self.eval_end <= self.eval_start:
            raise PromotionError(
                f"evaluation window ends {self.eval_end} at or before it starts "
                f"{self.eval_start}"
            )

    @property
    def is_out_of_time(self) -> bool:
        """True when no evaluation observation predates the end of training.

        Strict: an evaluation starting exactly at ``train_end`` is out-of-time,
        one starting a day earlier is not. The boundary is inclusive of the
        training end because a model fitted on data *through* ``train_end``
        has seen nothing after it.
        """
        return self.eval_start >= self.train_end

    @property
    def overlap_days(self) -> int:
        """Days of the evaluation window that fall inside the training period."""
        if self.is_out_of_time:
            return 0
        overlap_end = min(self.train_end, self.eval_end)
        return (overlap_end - self.eval_start).days


@dataclass(frozen=True)
class LiftMeasurement:
    """A challenger's measured performance against the champion it must beat.

    Both models, one metric, one window, one population. A "lift" whose two
    numbers came from different windows or different populations is not a
    smaller lift — it is not a lift, and the champion/challenger contract in
    :mod:`lending_hub.learning.challenger` is what enforces that.
    """

    metric: str
    """The metric's name. Comparative gates in §2 name different ones per
    workstream (recall at a fixed budget, C-index, Qini), so this is free text
    rather than an enum — constraining it would mean inventing the list."""

    champion: float
    challenger: float
    window: EvaluationWindow
    population: str
    """What the two numbers were computed over. Compared for equality by the
    challenger contract, so it must name the population, not describe it."""

    @property
    def lift(self) -> float:
        """Challenger minus champion, in the metric's own units.

        Deliberately not a ratio or a percentage. A percentage lift on a metric
        that can be near zero is unstable and invites reporting a large number
        from a tiny absolute move.
        """
        return self.challenger - self.champion


@dataclass(frozen=True)
class RollbackPlan:
    """What happens when the promoted model misbehaves.

    A plan is a *rehearsed* procedure with an owner and a trigger, not an
    intention. All three fields are required because a rollback plan missing any
    one of them fails at exactly the moment it is needed: no trigger means
    nobody calls it, no owner means everyone assumes someone else has, and an
    unrehearsed procedure is a hypothesis.
    """

    trigger: str
    """The observable condition that starts a rollback."""

    owner: str
    """The role accountable for executing it."""

    rehearsed_on: datetime | None = None
    """When the procedure was last exercised. ``None`` means never."""

    @property
    def is_rehearsed(self) -> bool:
        return self.rehearsed_on is not None


@dataclass(frozen=True)
class PromotionRequest:
    """One request to promote a model, with the evidence offered for it."""

    artifact: ModelArtifact
    target: Stage
    lift: LiftMeasurement | None
    rollback: RollbackPlan | None
    ab_test: AbTestFeasibility
    ab_infeasible_reason: str = ""
    """Required when ``ab_test`` is INFEASIBLE. Recorded, not evaluated — this
    module cannot judge whether a stated reason is a good one, and pretending
    otherwise would put a judgement in code that belongs to Model Risk."""

    submitted_by: str = ""

    def __post_init__(self) -> None:
        if self.ab_test is AbTestFeasibility.INFEASIBLE and not self.ab_infeasible_reason.strip():
            raise PromotionError(
                "ab_test=INFEASIBLE requires ab_infeasible_reason: an unexplained "
                "claim that no A/B was possible is how Phase 6 §4's final sentence "
                "becomes a formality"
            )
        if not self.submitted_by.strip():
            raise PromotionError(
                "submitted_by is required: the infeasibility claim and the lift "
                "measurement are attributable statements"
            )


@dataclass
class StandingDecision:
    """The outcome of the standing criterion, with every failing reason.

    Carries the Phase 0 decision alongside its own so a reader can tell an
    artifact problem from an evidence problem — they go to different people.
    """

    allowed: bool
    reasons: list[str]
    artifact_decision: PromotionDecision
    evidence_reasons: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.allowed


def evaluate_promotion(
    request: PromotionRequest,
    *,
    now: datetime,
    via_ci: bool,
    fallback_path_warm: bool = True,
) -> StandingDecision:
    """Run Phase 0's artifact gate and Phase 6 §4's evidence gate together.

    Returns every failing reason from both, because a team that fixes one
    blocker per run learns the gate's shape one week at a time.

    Only promotions *to Production* are subject to §4. A move to Staging is how
    a model gets somewhere it can be evaluated, so requiring measured lift for
    it would make the evidence unobtainable — the condition would forbid the
    step that produces what it demands.
    """
    artifact_decision = can_promote(
        request.artifact,
        request.target,
        now=now,
        via_ci=via_ci,
        fallback_path_warm=fallback_path_warm,
    )
    evidence: list[str] = []

    if request.target is Stage.PRODUCTION:
        evidence.extend(_evidence_reasons(request))

    reasons = list(artifact_decision.reasons) + evidence
    return StandingDecision(
        allowed=not reasons,
        reasons=reasons,
        artifact_decision=artifact_decision,
        evidence_reasons=evidence,
    )


def _evidence_reasons(request: PromotionRequest) -> list[str]:
    """The five §4 conditions. Card and validation are Phase 0's, checked there."""
    reasons: list[str] = []

    if request.lift is None:
        reasons.append(
            "no measured lift: Phase 6 §4 requires lift against the champion on "
            "out-of-time data"
        )
    elif not request.lift.window.is_out_of_time:
        reasons.append(
            f"lift measured on a window overlapping training by "
            f"{request.lift.window.overlap_days}d; Phase 6 §4 requires out-of-time "
            "evidence"
        )

    if request.rollback is None:
        reasons.append("no rollback plan (Phase 6 §4)")
    elif not request.rollback.is_rehearsed:
        reasons.append(
            f"rollback plan owned by {request.rollback.owner} has never been "
            "rehearsed; an unrehearsed procedure is a hypothesis"
        )

    if request.ab_test is AbTestFeasibility.FEASIBLE_NOT_RUN:
        reasons.append(
            "an online A/B was feasible and was not run: Phase 6 §4 makes offline "
            "lift alone inadmissible in this case"
        )

    return reasons

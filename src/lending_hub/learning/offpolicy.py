"""Doubly-robust off-policy evaluation — Phase 6 WS-6.5.

WS-6.5: candidate offer policies are evaluated with **doubly-robust off-policy
estimation** (Dudík, Langford & Li, arXiv:1103.4601) on logged propensities
*before any traffic*; only positive-DR-estimate policies proceed to canary. An
exploration cell is maintained at its `[POLICY]` percentage forever — "the
learning loop dies without it".

This is the one Phase 6 workstream whose *schema* already exists. Phase 4's
:class:`~lending_hub.reco.bandit.BanditDecision` cannot be constructed without a
propensity, so a P4 log is admissible by construction. What it lacks is rows —
no offer has been made (ADR-0014) — which makes this module the clean case of
built-and-untested-on-reality: the estimator is exact and pinned against
hand-computed values, and the log it would run on is empty.

Why doubly robust rather than IPS or the direct method
--------------------------------------------------------
Three estimators, and the phase file names the third for a reason worth stating
because it decides how this module handles failure.

* **Direct method**: fit a reward model, evaluate the new policy under it.
  Low variance, and biased by exactly the amount the reward model is wrong —
  which is unbounded and invisible.
* **IPS**: reweight logged rewards by 1/propensity. Unbiased given positivity,
  and its variance explodes as propensities approach zero — a single row logged
  at p=0.001 carries a weight of 1000.
* **DR**: the direct method plus an IPS correction on its residuals. Consistent
  if *either* the reward model or the propensities are right, which is why it is
  the estimator a bank should use: it does not require being certain which of
  the two is trustworthy.

The property that makes DR safe is also what makes an unchecked DR estimate
dangerous. "Consistent if either component is right" is not "correct if both are
wrong", and a log that violates positivity breaks the IPS half in a way the
reward-model half cannot rescue. So :func:`evaluate_policy` refuses such a log
rather than returning a number with a wide interval.

Positivity is a refusal, not a diagnostic
-------------------------------------------
If the logging policy never took action *a* in context *x*, the log contains no
evidence about what would have happened, and no estimator recovers it. A zero
propensity makes the IPS weight undefined; a near-zero one makes it enormous,
which is the same problem wearing a finite number.

This is the off-policy analogue of :mod:`lending_hub.learning.uplift`'s
identifiability guard, and it is why the exploration cell is standing policy: an
exploration floor is what *guarantees* positivity going forward, rather than
hoping the logging policy happened to be diverse.

What this module does not decide
----------------------------------
**The exploration percentage.** `[POLICY]` in the phase file with no number, and
it decides how much revenue is deliberately spent on learning. LH-803.

**The canary threshold.** "Only positive-DR-estimate policies proceed" is a sign
test, which this module implements. How *much* positive, and against what
confidence, is LH-804 — a point estimate marginally above zero is not evidence,
and the phase file's wording does not say so.

Workstream: WS-6.5 · SRS §6
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass


class OffPolicyError(Exception):
    """Raised when a log cannot support the estimate being asked of it."""


#: Propensities at or below this are treated as a positivity violation.
#: [SPEC] — an arithmetic bound rather than a tuned one: 1/p above 1000 means a
#: single logged row can dominate the estimate, at which point the "estimate" is
#: a report about that row. The *acceptable* effective sample size is LH-804.
MIN_PROPENSITY = 1e-3

#: Effective sample size below which an estimate is refused as uninformative.
#: [SPEC] Kish's ESS floor — with fewer than this many effective observations
#: the variance term dominates whatever the point estimate says.
MIN_EFFECTIVE_SAMPLE = 30


@dataclass(frozen=True)
class LoggedDecision:
    """One decision the logging policy made, with the propensity it made it at.

    Mirrors :class:`~lending_hub.reco.bandit.BanditDecision`'s guarantee rather
    than importing it: this module evaluates *any* logged policy, and coupling
    it to P4's offer type would make the estimator unusable for the collections
    actions WS-6.4 logs. :func:`from_bandit_decisions` bridges the two.
    """

    context_id: str
    action: str
    propensity: float
    reward: float

    def __post_init__(self) -> None:
        if not 0.0 < self.propensity <= 1.0:
            raise OffPolicyError(
                f"propensity {self.propensity} outside (0, 1] for action "
                f"{self.action!r}: a logged decision with no valid propensity is "
                "not a weaker observation, it is unusable — every off-policy "
                "estimator divides by it"
            )


@dataclass(frozen=True)
class PositivityReport:
    """Whether the log supports evaluating the target policy at all."""

    violations: tuple[tuple[str, str, float], ...]
    """(context_id, action, propensity) triples below :data:`MIN_PROPENSITY`."""

    unsupported_actions: tuple[str, ...]
    """Actions the target policy takes that the log never took."""

    effective_sample_size: float
    """Kish's ESS over the importance weights: (Σw)² / Σw².

    The honest denominator. A log of 10,000 rows whose weights are dominated by
    three of them has an ESS in single digits, and reporting n=10,000 next to
    that estimate is the misleading part.
    """

    @property
    def supported(self) -> bool:
        return (
            not self.violations
            and not self.unsupported_actions
            and self.effective_sample_size >= MIN_EFFECTIVE_SAMPLE
        )


@dataclass(frozen=True)
class DoublyRobustEstimate:
    """A DR value estimate with the quantities needed to read it honestly."""

    value: float
    """Estimated expected reward per decision under the target policy."""

    standard_error: float
    logged_value: float
    """The logging policy's own empirical mean reward, on the same rows. The
    comparison every reader will make, computed here so it is made correctly."""

    n: int
    positivity: PositivityReport

    @property
    def lift(self) -> float:
        return self.value - self.logged_value

    @property
    def positive(self) -> bool:
        """The sign test WS-6.5 states. Point estimate only — see LH-804."""
        return self.lift > 0.0

    def confidence_interval(self, z: float = 1.96) -> tuple[float, float]:
        """Normal-approximation interval. `z` is the caller's choice, not a default policy."""
        half = z * self.standard_error
        return (self.value - half, self.value + half)


def check_positivity(
    log: Sequence[LoggedDecision],
    target_policy: Callable[[str], str],
) -> PositivityReport:
    """Whether every action the target policy would take is represented.

    Computed before any estimate, because a positivity violation is not a
    quality problem to be noted — it is the absence of the evidence the estimate
    claims to summarise.
    """
    if not log:
        raise OffPolicyError("cannot check positivity of an empty log")

    violations = tuple(
        (d.context_id, d.action, d.propensity)
        for d in log
        if d.propensity <= MIN_PROPENSITY
    )
    logged_actions = {d.action for d in log}
    wanted = {target_policy(d.context_id) for d in log}
    unsupported = tuple(sorted(wanted - logged_actions))

    weights = [
        (1.0 / d.propensity) if target_policy(d.context_id) == d.action else 0.0
        for d in log
    ]
    total = sum(weights)
    sq = sum(w * w for w in weights)
    ess = (total * total / sq) if sq > 0 else 0.0

    return PositivityReport(violations, unsupported, ess)


def evaluate_policy(
    log: Sequence[LoggedDecision],
    target_policy: Callable[[str], str],
    reward_model: Callable[[str, str], float],
) -> DoublyRobustEstimate:
    """The Dudík–Langford–Li doubly-robust estimate of a target policy's value.

    For each logged decision, with `a*` the target policy's action and `a` the
    logged one::

        V_DR = (1/n) Σ [ r̂(x, a*) + 1{a = a*} · (r − r̂(x, a)) / p ]

    The first term is the direct method's prediction under the target policy;
    the second corrects it with the logged residual, on rows where the two
    policies agree. Consistent if either component is right, which is the whole
    reason WS-6.5 names this estimator rather than IPS.

    Refuses rather than returning a wide interval when positivity fails: an
    unsupported estimate is not an imprecise one.
    """
    if not log:
        raise OffPolicyError("cannot evaluate a policy on an empty log")

    positivity = check_positivity(log, target_policy)
    if positivity.violations:
        context, action, p = positivity.violations[0]
        raise OffPolicyError(
            f"{len(positivity.violations)} decision(s) logged below propensity "
            f"{MIN_PROPENSITY} (first: action {action!r} at p={p} in context "
            f"{context!r}). The importance weight exceeds {1 / MIN_PROPENSITY:.0f}, "
            "so the estimate reports those rows rather than the policy. WS-6.5's "
            "exploration cell is what prevents this"
        )
    if positivity.unsupported_actions:
        raise OffPolicyError(
            f"target policy takes action(s) the log never took: "
            f"{', '.join(positivity.unsupported_actions)}. No estimator recovers "
            "an outcome that was never observed"
        )
    if positivity.effective_sample_size < MIN_EFFECTIVE_SAMPLE:
        raise OffPolicyError(
            f"effective sample size {positivity.effective_sample_size:.1f} is below "
            f"{MIN_EFFECTIVE_SAMPLE}: the log has {len(log)} rows but the importance "
            "weights concentrate on too few of them for the estimate to describe "
            "the policy"
        )

    terms: list[float] = []
    for d in log:
        chosen = target_policy(d.context_id)
        direct = reward_model(d.context_id, chosen)
        correction = 0.0
        if chosen == d.action:
            correction = (d.reward - reward_model(d.context_id, d.action)) / d.propensity
        terms.append(direct + correction)

    n = len(terms)
    value = sum(terms) / n
    variance = sum((t - value) ** 2 for t in terms) / (n - 1) if n > 1 else 0.0
    return DoublyRobustEstimate(
        value=value,
        standard_error=math.sqrt(variance / n) if n else 0.0,
        logged_value=sum(d.reward for d in log) / n,
        n=n,
        positivity=positivity,
    )


def from_bandit_decisions(decisions: Sequence[object]) -> list[LoggedDecision]:
    """Bridge P4's bandit log into this module's input type.

    Duck-typed on purpose: importing :mod:`lending_hub.reco.bandit` would make
    the estimator depend on the offer layer, and WS-6.4's collections actions
    must run through the same estimator. Anything carrying the four attributes
    is admissible — which is safe here because P4's type already guarantees the
    propensity is present.
    """
    out: list[LoggedDecision] = []
    for d in decisions:
        missing = [
            name
            for name in ("context_id", "action", "propensity", "reward")
            if not hasattr(d, name)
        ]
        if missing:
            raise OffPolicyError(
                f"decision is missing {', '.join(missing)}; an off-policy log "
                "needs all four, and the propensity is the one no downstream step "
                "can reconstruct"
            )
        out.append(
            LoggedDecision(
                context_id=str(d.context_id),
                action=str(d.action),
                propensity=float(d.propensity),
                reward=float(d.reward),
            )
        )
    return out

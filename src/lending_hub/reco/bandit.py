"""LinUCB over offer templates, with propensity logging that cannot be skipped.

Phase 4 §5 Step 4:

    **LinUCB** — Li, Chu, Langford & Schapire, WWW 2010, arXiv:1003.0146. Arms =
    offer *templates* (auditable, small arm space), chosen **only within the
    feasible set** — exploration can never breach affordability or policy.
    Choose arm maximizing ``x^T θ̂_a + α √(x^T A_a^{-1} x)``. Reward = take-up
    blended with a seasoning risk-adjusted value proxy (delayed-reward
    correction). Exploration cell 1-2% of eligible traffic `[POLICY: Credit Risk
    Committee]`. **Log propensities for every decision** — this enables P6
    off-policy evaluation.

Propensity logging is a constructor invariant, not a logging call
------------------------------------------------------------------
Phase 4 §8 makes "propensity logging completeness = 100%" an exit criterion, and
P6's off-policy evaluation is impossible without it — a logged decision with no
propensity cannot be reweighted, so it is not merely missing from the analysis,
it silently biases whatever remains toward the decisions that happened to be
logged.

A requirement enforced by remembering to call a logger holds until the first
refactor. So :class:`BanditDecision` **cannot be constructed without a
propensity**, and :meth:`LinUCB.select` returns one rather than an arm. There is
no code path that produces an action without the probability it was taken with.

This is also the one Phase 4 criterion that is fully provable here: completeness
is a structural property of the decision type, not a measurement, so it holds
without a single real decision.

Exploration inside the feasible set, not beside it
----------------------------------------------------
:meth:`LinUCB.select` takes a :class:`~lending_hub.reco.feasible.FeasibleSet`
and considers only arms whose template maps to a feasible offer. The ordering
matters: filter first, then explore. A learner that explored first and checked
afterwards would need a fallback when its choice was infeasible, and every
fallback is a hole in the propensity — the logged probability would be for the
wrong action.

The reward is not defined, so this does not learn
---------------------------------------------------
:meth:`LinUCB.update` requires a :class:`Reward` carrying both components the
phase file names. It raises without them (LH-509). That is the phase's sharpest
gap: a bandit rewarded on take-up alone learns, quickly and correctly, to offer
**the largest amount the feasible set permits to the customers most likely to
accept**. Take-up rises, the reward curve looks like success, and the losses
arrive two years later in a different report. The feasible set bounds it, but a
feasible set is a floor rather than a suitability judgement.

What this does not port
-----------------------
No disjoint-vs-hybrid LinUCB variants, no delayed-reward machinery beyond the
interface, no Thompson Sampling alternative. The linear algebra reuses
``portfolio.linalg`` — arm feature dimensions here are tens, so an exact
Gauss-Jordan inverse is right and a Sherman-Morrison rank-one update would be
an optimisation with no data to justify it.

Workstream: WS-4.B Steps 3-4 (SRS §6)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Mapping, Sequence

from lending_hub.definitions.provenance import Pending, Ungrounded
from lending_hub.portfolio.linalg import SingularMatrix, dot, invert
from lending_hub.reco.feasible import FeasibleSet, Offer

#: The exploration cell size. `[POLICY: Credit Risk Committee]` — Phase 4 §5
#: Step 4 illustrates 1-2%, which is an illustration and not a ratification.
#: It decides how many customers receive a deliberately sub-optimal offer, so
#: it is a customer-impact decision rather than a tuning knob.
EXPLORATION_CELL = Pending(
    owner="Credit Risk Committee",
    ticket="LH-503",
    note="share of eligible traffic receiving a randomised arm",
)

#: The reward blend: how take-up and the seasoning risk-adjusted value proxy
#: combine, and over what horizon. Phase 4 §5 Step 4 names both components and
#: defines neither. The most consequential unspecified value in the phase.
REWARD_BLEND = Pending(
    owner="Model Risk + Credit Risk Committee",
    ticket="LH-509",
    note="weight on take-up vs seasoned risk-adjusted value, and the horizon",
)


class BanditError(Exception):
    """A bandit decision cannot be made, logged or learned from."""


@dataclass(frozen=True)
class OfferTemplate:
    """One arm. A *template*, not a free parameter set.

    Phase 4 §5 Step 4 specifies templates for a reason worth keeping: a small,
    named, auditable arm space is what makes a bandit explainable to a
    regulator. "The model chose template `top_up_12m_standard`" is reviewable;
    "the model chose amount 347,912 at 14.7% over 41 months" is not, and no
    amount of logging makes it so.
    """

    template_id: str
    product: str
    amount: float
    tenor_months: int
    rate_offset: float = 0.0
    """Added to the risk-based rate from `reco.pricing`. A template adjusts
    price relative to the computed rate; it never replaces it."""

    def __post_init__(self) -> None:
        if not self.template_id:
            raise BanditError("an arm needs a template id")
        if self.amount <= 0 or self.tenor_months <= 0:
            raise BanditError(f"{self.template_id}: degenerate template")

    def to_offer(self, base_rate: float) -> Offer:
        return Offer(
            product=self.product,
            amount=self.amount,
            tenor_months=self.tenor_months,
            annual_rate=base_rate + self.rate_offset,
        )


@dataclass(frozen=True)
class BanditDecision:
    """One arm choice, with the probability it was chosen with.

    Cannot exist without a propensity. Phase 4 §8 requires 100% completeness
    because P6 reweights logged decisions by their propensity to estimate what a
    different policy would have done — and a decision with none cannot be
    reweighted, so it does not merely drop out of the analysis, it biases
    whatever remains toward the decisions that happened to be logged.
    """

    decision_id: str
    subject_token: str
    template_id: str
    propensity: float
    decided_on: date
    considered_arms: tuple[str, ...]
    is_exploration: bool
    ucb_scores: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 < self.propensity <= 1.0:
            raise BanditError(
                f"{self.decision_id}: propensity {self.propensity} must be in "
                "(0, 1]. A zero propensity says this action could not have been "
                "taken, which contradicts the fact that it was — and it makes "
                "the P6 importance weight infinite."
            )
        if self.template_id not in self.considered_arms:
            raise BanditError(
                f"{self.decision_id}: chose {self.template_id!r}, which is not "
                "among the arms considered. The propensity is a probability over "
                "the arms that were available, so a choice outside that set has "
                "no interpretable propensity at all."
            )
        if not self.subject_token:
            raise BanditError(
                f"{self.decision_id}: a decision must carry a tokenised subject "
                "(SRS §11.4 — the log never holds raw PII)"
            )


@dataclass(frozen=True)
class Reward:
    """The two components Phase 4 §5 Step 4 names.

    Both are required. ``took_up`` is observable within days; ``seasoned_value``
    needs the horizon nobody has specified, which is half of LH-509.
    """

    decision_id: str
    took_up: bool
    seasoned_value: float | None
    seasoning_months: int | None

    def __post_init__(self) -> None:
        if self.seasoned_value is not None and self.seasoning_months is None:
            raise BanditError(
                f"{self.decision_id}: a seasoned value must say over how many "
                "months it seasoned. A risk-adjusted value at 3 months and at 24 "
                "are different quantities, and averaging them is meaningless."
            )

    def blended(self, *, take_up_weight: float | None = None) -> float:
        """Combine the two components. Raises without a ratified blend.

        The refusal that stops this bandit becoming a mis-selling engine. A
        bandit rewarded on take-up alone learns to offer the largest permitted
        loan to whoever is likeliest to accept it, and its own reward curve
        looks like success throughout.
        """
        if take_up_weight is None:
            raise Ungrounded(
                f"the reward blend is not ratified ({REWARD_BLEND}). Phase 4 §5 "
                "Step 4 names take-up and a seasoning risk-adjusted value proxy "
                "and gives neither the weight nor the horizon. Defaulting to "
                "take-up alone produces a bandit that offers the largest "
                "permitted loan to whoever is likeliest to accept — a "
                "mis-selling engine whose reward curve looks like success."
            )
        if not 0.0 <= take_up_weight <= 1.0:
            raise BanditError(f"take-up weight {take_up_weight} outside [0, 1]")
        if self.seasoned_value is None:
            raise BanditError(
                f"{self.decision_id}: no seasoned value, so the blend has only "
                "one component. Waiting for seasoning is the delayed-reward "
                "correction the phase file asks for, not an inconvenience to "
                "work around."
            )
        return take_up_weight * (1.0 if self.took_up else 0.0) + (
            1.0 - take_up_weight
        ) * self.seasoned_value


@dataclass
class _ArmState:
    """LinUCB's per-arm ridge regression state: ``A = I + Σxx^T``, ``b = Σrx``."""

    dimension: int
    a: list[list[float]]
    b: list[float]
    observations: int = 0

    @classmethod
    def fresh(cls, dimension: int) -> "_ArmState":
        return cls(
            dimension=dimension,
            a=[[1.0 if i == j else 0.0 for j in range(dimension)] for i in range(dimension)],
            b=[0.0] * dimension,
        )

    def theta(self) -> list[float]:
        inverse = invert(self.a)
        return [dot(row, self.b) for row in inverse]

    def ucb(self, x: Sequence[float], alpha: float) -> float:
        """``x^T θ̂_a + α √(x^T A_a^{-1} x)`` — the phase file's formula."""
        inverse = invert(self.a)
        mean = dot(self.theta(), x)
        variance = sum(
            x[i] * sum(inverse[i][j] * x[j] for j in range(self.dimension))
            for i in range(self.dimension)
        )
        return mean + alpha * math.sqrt(max(0.0, variance))

    def update(self, x: Sequence[float], reward: float) -> None:
        for i in range(self.dimension):
            for j in range(self.dimension):
                self.a[i][j] += x[i] * x[j]
            self.b[i] += reward * x[i]
        self.observations += 1


@dataclass
class LinUCB:
    """Contextual bandit over offer templates (Li et al., WWW 2010).

    ``alpha`` controls the exploration bonus. It has a default because it is a
    *statistical* parameter with a principled value from the paper's regret
    bound, unlike the exploration cell size (LH-503), which is a decision about
    how many customers receive a deliberately sub-optimal offer.
    """

    arms: dict[str, OfferTemplate]
    dimension: int
    alpha: float = 1.0
    _state: dict[str, _ArmState] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if not self.arms:
            raise BanditError("a bandit needs at least one arm")
        if self.dimension <= 0:
            raise BanditError(f"context dimension must be positive, got {self.dimension}")
        if self.alpha < 0:
            raise BanditError(
                f"alpha {self.alpha} is negative, which subtracts the confidence "
                "bound and makes the bandit avoid arms it is uncertain about — "
                "the opposite of exploration"
            )
        for template_id in self.arms:
            self._state.setdefault(template_id, _ArmState.fresh(self.dimension))

    def select(
        self,
        context: Sequence[float],
        feasible_set: FeasibleSet,
        base_rate: float,
        *,
        decision_id: str,
        subject_token: str,
        decided_on: date,
    ) -> BanditDecision:
        """Choose an arm within the feasible set, returning its propensity.

        Filters to feasible arms **first**, then scores. A learner that chose
        first and checked afterwards would need a fallback, and every fallback
        is a hole in the propensity: the logged probability would be for an
        action other than the one taken.

        The returned propensity is 1.0 for the greedy arm, because LinUCB is
        deterministic given its state. That is correct and worth stating: P6's
        importance weighting handles a deterministic logging policy, but only if
        the determinism is recorded honestly rather than smoothed into a
        plausible-looking distribution.
        """
        if len(context) != self.dimension:
            raise BanditError(
                f"context has {len(context)} features, expected {self.dimension}"
            )

        available = []
        for template_id, template in self.arms.items():
            if feasible_set.contains(template.to_offer(base_rate)):
                available.append(template_id)

        if not available:
            raise BanditError(
                f"{decision_id}: no arm maps to a feasible offer. Phase 4 §5 "
                "Step 4 puts exploration inside the feasible set, so an empty "
                "intersection means no offer may be made — it is not an "
                "invitation to relax the set."
            )

        scores = {
            template_id: self._state[template_id].ucb(context, self.alpha)
            for template_id in available
        }
        chosen = max(available, key=lambda t: scores[t])

        return BanditDecision(
            decision_id=decision_id,
            subject_token=subject_token,
            template_id=chosen,
            propensity=1.0,
            decided_on=decided_on,
            considered_arms=tuple(sorted(available)),
            is_exploration=False,
            ucb_scores=scores,
        )

    def explore(
        self,
        context: Sequence[float],
        feasible_set: FeasibleSet,
        base_rate: float,
        *,
        decision_id: str,
        subject_token: str,
        decided_on: date,
        rng_value: float,
    ) -> BanditDecision:
        """Choose uniformly at random among feasible arms — the exploration cell.

        ``rng_value`` is supplied rather than drawn, so a decision is
        reproducible from its log. A bandit whose exploration cannot be replayed
        cannot be audited, and "the model picked randomly" is not an answer to a
        regulator asking why one customer got a worse offer than another.

        Whether a given customer *enters* the cell is LH-503 and is not decided
        here — this method is what happens once they have.
        """
        if not 0.0 <= rng_value < 1.0:
            raise BanditError(f"rng_value {rng_value} must be in [0, 1)")

        available = sorted(
            template_id
            for template_id, template in self.arms.items()
            if feasible_set.contains(template.to_offer(base_rate))
        )
        if not available:
            raise BanditError(
                f"{decision_id}: no feasible arm to explore among. Exploration "
                "does not widen the feasible set."
            )

        index = min(int(rng_value * len(available)), len(available) - 1)
        return BanditDecision(
            decision_id=decision_id,
            subject_token=subject_token,
            template_id=available[index],
            propensity=1.0 / len(available),
            decided_on=decided_on,
            considered_arms=tuple(available),
            is_exploration=True,
        )

    def update(
        self,
        decision: BanditDecision,
        context: Sequence[float],
        reward: Reward,
        *,
        take_up_weight: float | None = None,
    ) -> None:
        """Learn from an observed reward. Raises without a ratified blend.

        This is where the bandit refuses to become the thing LH-509 describes.
        """
        if reward.decision_id != decision.decision_id:
            raise BanditError(
                f"reward for {reward.decision_id} applied to decision "
                f"{decision.decision_id}"
            )
        if len(context) != self.dimension:
            raise BanditError(f"context has {len(context)} features")

        value = reward.blended(take_up_weight=take_up_weight)
        self._state[decision.template_id].update(context, value)

    def arm_observations(self, template_id: str) -> int:
        return self._state[template_id].observations


def propensity_completeness(decisions: Sequence[BanditDecision]) -> float:
    """Phase 4 §8's exit criterion: the share of decisions carrying a propensity.

    Structurally 1.0 whenever there are any decisions, because
    :class:`BanditDecision` cannot be built without one. That is the point —
    the criterion is satisfied by construction rather than by a monitoring job
    that could itself fail. Returns 1.0 for an empty sequence with the same
    reasoning: no decision is missing a propensity.
    """
    if not decisions:
        return 1.0
    with_propensity = sum(1 for d in decisions if 0.0 < d.propensity <= 1.0)
    return with_propensity / len(decisions)

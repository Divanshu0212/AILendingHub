"""Alert routing and the case queue — where Phase 6's training set is created.

Phase 1 §4 WS-1.2 Step 6: "Orchestrator outcomes: pass / step-up verification /
refer-to-fraud-desk. Case-management queue with **mandatory disposition codes** —
these labels are P6's training set; completeness is enforced from day one (no case
closes without a code)."

This module is a labelling pipeline wearing an operations interface
--------------------------------------------------------------------
Every workstream downstream of here — the Layer-1 GBM's retrains, P6's GraphSAGE
and CARE-GNN, the Appendix A *Confirmed fraud* arm itself — consumes fraud-desk
dispositions. A case closed without a code is not an administrative gap. It is a
row deleted from a training set that has not been collected yet, and it is
unrecoverable: nobody will reconstruct in 2028 what an analyst concluded in 2026.

So :meth:`CaseQueue.close` raises without a code, and there is no "unknown"
member in the taxonomy for someone to reach for. The enum is also deliberately
**not** hard-coded as the bank's taxonomy — that is `[POLICY: Fraud Head]`
(LH-101), the same placeholder Appendix A's *Confirmed fraud* definition waits on.
What ships is the *shape*: a disposition names an outcome, says whether it
confirms fraud, and cannot be omitted.

The thresholds are not here either
----------------------------------
Where the pass / step-up / refer boundaries sit is the operating alert budget
(LH-206) plus the bank's friction tolerance. :func:`route` therefore takes the
bands as an argument with no default, and :class:`RoutingPolicy` records whether
they were ratified. A default band set would become the production one by
inertia — nobody passes the argument, and the number ends up in a gate pack.

Workstream: WS-1.2 Step 6 · SRS §5.2 (FR-1, FR-5), Master Appendix A
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Sequence

from lending_hub.definitions import CONFIRMED_FRAUD_DISPOSITION_CODES, Pending, alert_precision


class RoutingError(Exception):
    """The alert cannot be routed or the case cannot be closed as asked."""


class Action(str, Enum):
    """SRS §5.2 FR-1: the three outcomes, and only these three."""

    PASS = "pass"
    STEP_UP = "step_up"
    REFER = "refer"


class DispositionOutcome(str, Enum):
    """What a disposition *means*, independent of the bank's code for it.

    Deliberately no UNKNOWN member. An outcome bucket for "we never decided"
    turns the mandatory-code rule into a formality: the code becomes mandatory and
    meaningless in the same move, and the training set fills with rows that teach
    nothing.
    """

    CONFIRMED_FRAUD = "confirmed_fraud"
    NOT_FRAUD = "not_fraud"
    INCONCLUSIVE = "inconclusive"
    """Investigated and undecided. A real analytical outcome — the case was
    worked — and distinct from never having been dispositioned. It is excluded
    from training labels rather than counted as not-fraud, because "we looked and
    could not tell" is not evidence of innocence."""


@dataclass(frozen=True)
class Disposition:
    """One code from the bank's approved taxonomy."""

    code: str
    outcome: DispositionOutcome
    description: str = ""

    @property
    def is_training_label(self) -> bool:
        return self.outcome is not DispositionOutcome.INCONCLUSIVE


@dataclass
class DispositionTaxonomy:
    """The approved code set. `[POLICY: Fraud Head]` until LH-101 lands."""

    codes: dict[str, Disposition] = field(default_factory=dict)
    ratified: bool = False
    provenance: str = str(CONFIRMED_FRAUD_DISPOSITION_CODES)

    @classmethod
    def from_policy(cls, dispositions: Sequence[Disposition], *, decision_reference: str):
        if not decision_reference:
            raise RoutingError(
                "a ratified taxonomy must cite the Fraud Head decision that approved "
                "it — Master Appendix A: suspicion is not a label"
            )
        return cls(
            codes={d.code: d for d in dispositions},
            ratified=True,
            provenance=decision_reference,
        )

    @classmethod
    def for_experiment(cls, dispositions: Sequence[Disposition], *, reason: str):
        if not reason:
            raise RoutingError("a stand-in taxonomy needs a written reason")
        return cls(
            codes={d.code: d for d in dispositions},
            ratified=False,
            provenance=f"stand-in, not the approved taxonomy: {reason}",
        )

    def resolve(self, code: str) -> Disposition:
        if code not in self.codes:
            raise RoutingError(
                f"{code!r} is not in the disposition taxonomy. A free-text "
                "disposition cannot become a training label, and this is the point "
                "at which that is still fixable."
            )
        return self.codes[code]


@dataclass(frozen=True)
class Band:
    """One routing band: scores at or above ``lower`` take ``action``."""

    lower: float
    action: Action


@dataclass
class RoutingPolicy:
    """The score bands, and whether anyone ratified them."""

    bands: list[Band]
    ratified: bool
    provenance: str

    def __post_init__(self) -> None:
        if not self.bands:
            raise RoutingError("a routing policy needs at least one band")
        ordered = sorted(self.bands, key=lambda band: band.lower)
        if [band.lower for band in ordered] != [band.lower for band in self.bands]:
            raise RoutingError("bands must be given in ascending order of score")
        if len({band.lower for band in self.bands}) != len(self.bands):
            raise RoutingError("two bands share a lower edge; the boundary is ambiguous")

    @classmethod
    def from_policy(cls, bands: Sequence[Band], *, decision_reference: str):
        if not decision_reference:
            raise RoutingError("ratified bands must cite the decision that set them")
        return cls(list(bands), True, decision_reference)

    @classmethod
    def for_experiment(cls, bands: Sequence[Band], *, reason: str):
        if not reason:
            raise RoutingError(
                "unratified bands need a written reason. Where the pass/step-up/refer "
                "boundaries sit is the operating alert budget (LH-206) plus the "
                "bank's friction tolerance."
            )
        return cls(list(bands), False, f"unratified: {reason}")

    def action_for(self, score: float) -> Action:
        action = Action.PASS
        for band in self.bands:
            if score >= band.lower:
                action = band.action
        return action


def route(score: float, policy: RoutingPolicy) -> Action:
    """Map a fraud score to one of the three SRS §5.2 outcomes."""
    if not 0.0 <= score <= 1.0:
        raise RoutingError("a fraud score must be a probability in [0, 1]")
    return policy.action_for(score)


@dataclass
class Case:
    """One fraud-desk case. Cannot be closed without a disposition."""

    case_id: str
    application_id: str
    action: Action
    score: float
    opened_at: datetime
    signal: str = ""
    """Which signal raised it — Appendix A measures alert precision *per signal*."""

    closed_at: datetime | None = None
    disposition: Disposition | None = None
    analyst: str = ""

    @property
    def open(self) -> bool:
        return self.closed_at is None

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "application_id": self.application_id,
            "action": self.action.value,
            "score": self.score,
            "signal": self.signal,
            "opened_at": self.opened_at.isoformat(),
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
            "disposition": self.disposition.code if self.disposition else None,
            "outcome": self.disposition.outcome.value if self.disposition else None,
            "analyst": self.analyst,
        }


@dataclass
class CaseQueue:
    """The case-management queue, with completeness enforced from day one."""

    taxonomy: DispositionTaxonomy
    cases: dict[str, Case] = field(default_factory=dict)

    def open_case(
        self,
        *,
        case_id: str,
        application_id: str,
        action: Action,
        score: float,
        opened_at: datetime,
        signal: str = "",
    ) -> Case:
        if action is Action.PASS:
            raise RoutingError(
                "a passed application does not open a case. Opening one anyway "
                "would put every clean application into the disposition set and "
                "drown the base rate the fraud model is fitted to."
            )
        if case_id in self.cases:
            raise RoutingError(f"case {case_id!r} already exists")
        case = Case(
            case_id=case_id,
            application_id=application_id,
            action=action,
            score=score,
            opened_at=opened_at,
            signal=signal,
        )
        self.cases[case_id] = case
        return case

    def close(
        self, case_id: str, *, code: str, closed_at: datetime, analyst: str
    ) -> Case:
        """Close a case. The disposition code is mandatory and validated.

        Both halves matter. Mandatory stops the row vanishing; validated against
        the taxonomy stops it arriving as free text that no training job can read.
        """
        case = self.cases.get(case_id)
        if case is None:
            raise RoutingError(f"no such case: {case_id!r}")
        if not case.open:
            raise RoutingError(f"case {case_id!r} is already closed")
        if not analyst:
            raise RoutingError(
                "a disposition must record who made it: an unattributed label "
                "cannot be questioned later, and it will be"
            )
        case.disposition = self.taxonomy.resolve(code)
        case.closed_at = closed_at
        case.analyst = analyst
        return case

    @property
    def open_cases(self) -> list[Case]:
        return [case for case in self.cases.values() if case.open]

    @property
    def completeness(self) -> float | None:
        """Fraction of cases carrying a disposition. The P6 readiness number."""
        if not self.cases:
            return None
        return sum(1 for case in self.cases.values() if not case.open) / len(self.cases)

    def training_labels(self) -> list[tuple[str, int]]:
        """``(application_id, label)`` for cases that produced a usable label.

        Inconclusive cases are excluded rather than labelled 0. "We looked and
        could not tell" is not evidence of innocence, and folding it into the
        negative class teaches the model that the hardest cases are clean — which
        is precisely backwards.
        """
        if not self.taxonomy.ratified:
            raise RoutingError(
                f"{CONFIRMED_FRAUD_DISPOSITION_CODES} — the taxonomy is not "
                "ratified, so these dispositions are not Appendix A confirmed "
                "fraud. Training on them would fit a definition nobody approved."
            )
        return [
            (
                case.application_id,
                1 if case.disposition.outcome is DispositionOutcome.CONFIRMED_FRAUD else 0,
            )
            for case in self.cases.values()
            if case.disposition is not None and case.disposition.is_training_label
        ]

    def precision(self, signal: str | None = None) -> float | None:
        """Appendix A *Alert precision*, per signal.

        Delegates the arithmetic to :func:`lending_hub.definitions.alert_precision`
        rather than restating it — including its refusal to render an empty window
        as zero.
        """
        closed = [
            case
            for case in self.cases.values()
            if not case.open and (signal is None or case.signal == signal)
        ]
        confirmed = sum(
            1
            for case in closed
            if case.disposition.outcome is DispositionOutcome.CONFIRMED_FRAUD
        )
        return alert_precision(confirmed, len(closed))

    def to_dict(self) -> dict:
        return {
            "taxonomy_ratified": self.taxonomy.ratified,
            "taxonomy_provenance": self.taxonomy.provenance,
            "cases": len(self.cases),
            "open_cases": len(self.open_cases),
            "completeness": self.completeness,
            "alert_precision": self.precision(),
            "note": (
                "disposition completeness is P6's training-set completeness. A case "
                "closed without a code is a row deleted from a training set that "
                "has not been collected yet."
            ),
        }


#: The routing bands the orchestrator needs, and does not have.
ROUTING_BANDS = Pending(
    owner="Fraud Head",
    ticket="LH-206",
    note=(
        "the score boundaries between pass, step-up verification and refer-to-desk. "
        "They follow from the operating alert budget and the step-up friction the "
        "bank will accept, neither of which is settled"
    ),
)

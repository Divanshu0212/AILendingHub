"""Reject inference, and the line it must not cross.

Phase 1 §4 WS-1.1 Step 8: "First release: bureau-retro based (how our rejects
performed on loans elsewhere) if retro data is purchasable `[DATA]`; otherwise
document the selection-bias limitation in the model card and schedule
parceling/fuzzy augmentation for the first retrain. **Never fabricate outcomes for
rejects.**"

The instruction contains a tension worth naming rather than resolving quietly.
Parcelling *does* assign outcomes to rejected applicants — that is what it is —
weighting each reject as part-good and part-bad according to the current model's
prediction. It is not observation; it is the model's own belief fed back as data.
Read one way, the paragraph's last sentence forbids the method its previous
sentence schedules.

SRS §4.3.2.4 and Phase 1 §4 Step 8 (v1.1) settle it, and this module implements
the settlement:

* **Bureau retro is inference from evidence.** Someone else lent to the applicant
  and observed the outcome. It belongs in the target table, labelled as
  externally observed.
* **Parcelling is inference from belief.** It belongs in a *sensitivity analysis*
  — "how much would the coefficients move if the rejects behaved as the model
  expects" — and never in a label column. :class:`Parcelled` is deliberately not
  a :class:`~lending_hub.scoring.target.TargetRow`, and
  :func:`assert_not_in_target` exists so the boundary is enforced rather than
  remembered.

What is measurable without any reject outcomes at all is the *size* of the
problem: how far the rejected population sits from the booked one.
:func:`selection_gap` reports that, and it needs no assumption whatsoever.

Workstream: WS-1.1 Step 8 · SRS §4.3.2.4, CS-5
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence

from lending_hub.definitions import Pending

from .features import psi
from .target import TargetRow

#: Whether the bank can buy bureau retro data on its own declines. A procurement
#: and contractual question, not an engineering one, and the answer decides
#: whether the first release corrects selection bias or merely documents it.
BUREAU_RETRO_AVAILABILITY = Pending(
    owner="Credit Risk Head",
    ticket="LH-207",
    note=(
        "whether bureau retro data on declined applicants is purchasable, at what "
        "match rate, and under what consent basis. Phase 1 §4 Step 8 makes the "
        "first release's reject-inference method conditional on this"
    ),
)


class RejectInferenceError(Exception):
    """A reject-inference operation would cross the fabrication line."""


class Method(str, Enum):
    NONE = "none"
    """No correction. The honest default, paired with a model-card limitation."""

    BUREAU_RETRO = "bureau_retro"
    """Outcomes observed elsewhere by a bureau. Evidence about the reject."""

    PARCELLING = "parcelling"
    """Weighted good/bad assignment from the current model. Belief, not evidence —
    sensitivity analysis only."""


@dataclass(frozen=True)
class Parcelled:
    """A rejected application with a *modelled* outcome weight.

    Deliberately not a :class:`~lending_hub.scoring.target.TargetRow`. The types
    are separate so that appending parcelled rows to a training target is a type
    error at the point it is attempted, rather than a decision buried in a
    pipeline that nobody revisits.
    """

    application_id: str
    predicted_pd: float
    weight_bad: float
    weight_good: float
    method: str = Method.PARCELLING.value

    def __post_init__(self) -> None:
        if not 0.0 <= self.predicted_pd <= 1.0:
            raise RejectInferenceError("predicted_pd must be a probability")


@dataclass
class SelectionGap:
    """How far the rejected population sits from the booked one.

    Measurable with no reject outcomes at all, which is what makes it the honest
    first thing to report: it quantifies the bias a model carries without
    pretending to correct it.
    """

    n_accepted: int
    n_rejected: int
    score_psi: float | None
    accepted_mean_score: float | None
    rejected_mean_score: float | None

    @property
    def reject_rate(self) -> float | None:
        total = self.n_accepted + self.n_rejected
        return self.n_rejected / total if total else None

    def to_dict(self) -> dict:
        return {
            "n_accepted": self.n_accepted,
            "n_rejected": self.n_rejected,
            "reject_rate": self.reject_rate,
            "score_psi": self.score_psi,
            "accepted_mean_score": self.accepted_mean_score,
            "rejected_mean_score": self.rejected_mean_score,
            "note": (
                "measured without any reject outcomes. A large PSI means the model "
                "was fitted on a population materially unlike the one it scores, "
                "which is the size of the selection bias — not a correction for it"
            ),
        }


def selection_gap(
    accepted_scores: Sequence[float],
    rejected_scores: Sequence[float],
    *,
    bins: int = 10,
) -> SelectionGap:
    """Compare booked and declined score distributions."""
    if not accepted_scores or not rejected_scores:
        return SelectionGap(
            n_accepted=len(accepted_scores),
            n_rejected=len(rejected_scores),
            score_psi=None,
            accepted_mean_score=(
                sum(accepted_scores) / len(accepted_scores) if accepted_scores else None
            ),
            rejected_mean_score=(
                sum(rejected_scores) / len(rejected_scores) if rejected_scores else None
            ),
        )

    edges = _quantile_edges(accepted_scores, bins)
    return SelectionGap(
        n_accepted=len(accepted_scores),
        n_rejected=len(rejected_scores),
        score_psi=psi(
            _proportions(accepted_scores, edges), _proportions(rejected_scores, edges)
        ),
        accepted_mean_score=sum(accepted_scores) / len(accepted_scores),
        rejected_mean_score=sum(rejected_scores) / len(rejected_scores),
    )


def _quantile_edges(values: Sequence[float], bins: int) -> list[float]:
    ordered = sorted(values)
    edges = []
    for k in range(1, bins):
        candidate = ordered[min(len(ordered) - 1, int(k * len(ordered) / bins))]
        if not edges or candidate > edges[-1]:
            edges.append(candidate)
    return edges


def _proportions(values: Sequence[float], edges: Sequence[float]) -> list[float]:
    from bisect import bisect_right

    counts = [0] * (len(edges) + 1)
    for value in values:
        counts[bisect_right(edges, value)] += 1
    return [count / len(values) for count in counts]


def parcel(
    application_ids: Sequence[str], predicted_pd: Sequence[float]
) -> list[Parcelled]:
    """Fuzzy augmentation: each reject counted as part-good and part-bad.

    Returns :class:`Parcelled`, never a target row. The uplift this produces is
    reported as a *sensitivity* — "the coefficients move this much if the rejects
    behave as the model already believes they will" — which is the only claim the
    method supports. Presented as a correction it is circular: the model's belief
    becomes the model's evidence, and the resulting confidence is manufactured.
    """
    if len(application_ids) != len(predicted_pd):
        raise RejectInferenceError("ids and predictions must be the same length")
    return [
        Parcelled(
            application_id=application_id,
            predicted_pd=pd,
            weight_bad=pd,
            weight_good=1.0 - pd,
        )
        for application_id, pd in zip(application_ids, predicted_pd)
    ]


def assert_not_in_target(rows: Sequence[object]) -> None:
    """Refuse a training population that contains parcelled rejects."""
    offenders = [r for r in rows if isinstance(r, Parcelled)]
    if offenders:
        raise RejectInferenceError(
            f"{len(offenders)} parcelled reject(s) in a training population. "
            "Parcelling assigns outcomes the bank never observed; Phase 1 §4 Step 8 "
            "forbids fabricated reject outcomes. Use them for sensitivity analysis "
            "and report the uplift as a sensitivity, not as a correction."
        )
    non_target = [r for r in rows if not isinstance(r, TargetRow)]
    if non_target:
        raise RejectInferenceError(
            f"{len(non_target)} row(s) in the training population are not TargetRows; "
            "the target table is the only sanctioned training input (WS-1.1 Step 1)"
        )


@dataclass
class RejectInferenceMemo:
    """Phase 1 §6 deliverable: the reject-inference memo, as a checkable object."""

    model: str
    method: Method
    exercisable: bool
    reason: str
    gap: SelectionGap | None = None
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "method": self.method.value,
            "exercisable": self.exercisable,
            "reason": self.reason,
            "bureau_retro_availability": str(BUREAU_RETRO_AVAILABILITY),
            "selection_gap": self.gap.to_dict() if self.gap else None,
            "limitations": self.limitations,
        }


def memo_when_unavailable(model: str, *, reason: str, gap: SelectionGap | None = None):
    """The memo for the case Phase 1 anticipates: no reject outcomes at all.

    Phase 1 requires the limitation to be documented on the model card when reject
    inference cannot run. This produces that text as data, so the model card
    cannot be signed off with the section left blank.
    """
    return RejectInferenceMemo(
        model=model,
        method=Method.NONE,
        exercisable=False,
        reason=reason,
        gap=gap,
        limitations=[
            "The model is fitted only on applications the current policy approved, "
            "so it estimates default risk conditional on having been approved — not "
            "through-the-door risk. Its PD is understated for segments the current "
            "policy declines and it has no evidence at all about applicants far "
            "outside the booked population.",
            "Swap-set analysis against the legacy scorecard is affected in the same "
            "direction: both models were fitted on the same accepted population, so "
            "agreement between them is not independent evidence.",
            "No outcome has been assigned to any rejected applicant. Parcelling is "
            "available as a sensitivity analysis only (Phase 1 §4 Step 8).",
        ],
    )

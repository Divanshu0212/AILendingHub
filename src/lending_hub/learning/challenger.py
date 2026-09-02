"""The champion/challenger comparison contract — Phase 6 §2, §4.

Every Phase 6 workstream promotes by *comparison*: WS-6.1 is "+recall at the
fixed alert budget vs. the P1 stack", WS-6.3 is "C-index / capture-rate lift on
out-of-time data", WS-6.4 is "Qini coefficient + online cure-rate lift". None of
those is a number a challenger produces alone — each is a difference between two
models, and a difference is only meaningful when everything except the model is
held fixed.

This module is what "held fixed" means, and it exists because the ways a
comparison goes wrong are quiet ones. A challenger evaluated on a *later* window
than its champion looks better if the book improved. One evaluated on a
*broader* population looks better if the extra segment is easier. One scored at
a different operating threshold is not being compared at all. Each produces a
positive lift that survives review, because the reviewer sees two numbers and a
subtraction.

So :func:`compare` refuses rather than adjusts. There is no reweighting or
alignment step here: a comparison whose windows differ cannot be repaired by
code, only re-run.

What a challenger must also carry that a champion need not
------------------------------------------------------------
WS-6.3's promotion gate ends with a clause the others do not have — *"a sequence
model never fires an EWS alert without a human-readable co-signal (P4 two-key
rule extends to it)."* That is not a metric condition, and
:attr:`ChallengerEntry.explainability_reviewed` is where it lands: a model whose
outputs cannot be explained to the desk that acts on them fails the gate at any
lift.

Workstream: WS-6.7 · Phase 6 §4
"""

from __future__ import annotations

from dataclasses import dataclass

from .promotion import EvaluationWindow, LiftMeasurement, PromotionError


class ComparisonError(Exception):
    """Raised when two evaluations are not comparable."""


@dataclass(frozen=True)
class ChallengerEntry:
    """One model's evaluation, as offered for comparison."""

    model_name: str
    metric: str
    value: float
    window: EvaluationWindow
    population: str
    threshold: float | None = None
    """The operating point the metric was computed at, where the metric has one.
    ``None`` means threshold-free (AUC, C-index); two entries must agree on
    whether they have one."""

    explainability_reviewed: bool = False
    """WS-6.3's co-signal condition. False blocks promotion at any lift."""

    def __post_init__(self) -> None:
        if not self.model_name.strip():
            raise ComparisonError("a comparison entry needs a model name")


def compare(
    champion: ChallengerEntry,
    challenger: ChallengerEntry,
) -> LiftMeasurement:
    """Build a :class:`LiftMeasurement`, or refuse the comparison.

    Four conditions, each of which produces a plausible positive lift when
    violated:

    * **same metric** — otherwise the subtraction is meaningless;
    * **same population** — a broader or easier segment inflates the challenger;
    * **same evaluation window** — a later window measures the book, not the model;
    * **same operating threshold** — a metric read at a different cut point is a
      different metric.
    """
    if champion.metric != challenger.metric:
        raise ComparisonError(
            f"metric mismatch: champion measured {champion.metric!r}, challenger "
            f"{challenger.metric!r}. The difference of two different metrics is "
            "not a lift"
        )
    if champion.population != challenger.population:
        raise ComparisonError(
            f"population mismatch: {champion.population!r} vs "
            f"{challenger.population!r}. A challenger scored on a different "
            "population is measuring that population"
        )
    if (champion.window.eval_start, champion.window.eval_end) != (
        challenger.window.eval_start,
        challenger.window.eval_end,
    ):
        raise ComparisonError(
            f"window mismatch: champion {champion.window.eval_start.date()}–"
            f"{champion.window.eval_end.date()}, challenger "
            f"{challenger.window.eval_start.date()}–{challenger.window.eval_end.date()}. "
            "A later window measures how the book changed"
        )
    if champion.threshold != challenger.threshold:
        raise ComparisonError(
            f"operating point mismatch: {champion.threshold} vs "
            f"{challenger.threshold}. Two models read at different thresholds are "
            "not being compared"
        )

    return LiftMeasurement(
        metric=challenger.metric,
        champion=champion.value,
        challenger=challenger.value,
        window=challenger.window,
        population=challenger.population,
    )


@dataclass(frozen=True)
class ChallengerVerdict:
    """Whether a challenger may proceed, with every blocking reason."""

    lift: LiftMeasurement
    blocking: tuple[str, ...]

    @property
    def may_proceed(self) -> bool:
        return not self.blocking


def assess(
    champion: ChallengerEntry,
    challenger: ChallengerEntry,
) -> ChallengerVerdict:
    """Compare, then apply the conditions that are not about the metric.

    Deliberately does not check whether the lift is *large enough*. §4 says
    "measured lift", each workstream names its own gate, and none of them is
    quantified — LH-801. A minimum defaulted here would become the number every
    challenger in the programme was judged against.
    """
    lift = compare(champion, challenger)
    blocking: list[str] = []

    if not challenger.window.is_out_of_time:
        blocking.append(
            f"evaluation overlaps training by {challenger.window.overlap_days}d; "
            "Phase 6 §4 requires out-of-time evidence"
        )
    if lift.lift <= 0:
        blocking.append(
            f"lift is {lift.lift:+.4f} on {lift.metric}: a challenger that does not "
            "beat the champion does not replace it"
        )
    if not challenger.explainability_reviewed:
        blocking.append(
            "no explainability review: WS-6.3 extends P4's two-key rule to "
            "sequence models, and WS-6.1 requires every graph alert to ship with "
            "its subgraph — an unexplained alert is not actioned by the desk"
        )

    return ChallengerVerdict(lift=lift, blocking=tuple(blocking))


__all__ = [
    "ChallengerEntry",
    "ChallengerVerdict",
    "ComparisonError",
    "PromotionError",
    "assess",
    "compare",
]

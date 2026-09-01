"""Survival estimators and the metrics Phase 3 §7 grades the hazard model on.

Ports the parts of `scikit-survival <https://github.com/sebp/scikit-survival>`_
that Phase 3 WS-3.1 Step 3 names as the metric set: Harrell's C-index,
cumulative/dynamic time-dependent AUC, and the integrated Brier score. The
Kaplan-Meier estimator is here too because two of those three need it —
not for the survival curve, but for the *censoring* distribution.

Why censoring weighting is not optional
---------------------------------------
The naive Brier score at 12 months drops censored accounts, and the naive
time-dependent AUC drops them from the control set. On a mortgage panel that
is a catastrophic sample selection: accounts disappear from the risk set
because they *prepaid*, and prepayment is strongly related to credit quality.
Dropping them means grading the model on the borrowers who could not
refinance. Graf et al. (1999) fix this by weighting each retained observation
by the inverse probability that it was still uncensored — implemented here as
:func:`censoring_survival`, the Kaplan-Meier estimate with the event indicator
reversed.

What this does not port
-----------------------
* **Uno's C** — Harrell's C is known to drift upward as censoring gets heavy,
  and Uno's inverse-probability-weighted variant is the fix. Phase 3 names
  Harrell's, so Harrell's is what :func:`harrell_c` computes; the
  :attr:`Concordance.censoring_rate` it reports alongside is there so the
  number is never read without the caveat that applies to it.
* No competing-risks-aware concordance. Under competing risks the quantity
  that matters is the cumulative incidence, which
  :mod:`lending_hub.portfolio.competing` handles.

On cost
-------
:func:`harrell_c` and :func:`time_dependent_auc` are **O(n²)**: both compare
every pair. That is fine for the tens of thousands of subjects a Track P run or
a validation sample carries, and it is not fine for a whole book — a million
accounts is 10¹² comparisons. The O(n log n) formulation (sort by risk, count
inversions with a Fenwick tree) is the standard fix and is what a Track B
implementation should use. It is not here because the sampling a validation
sample already involves makes the quadratic version adequate, and because an
inversion-counting concordance is materially harder to read than the definition
it implements.

Reference: Graf, Schmoor, Sauerbrei & Schumacher, "Assessment and comparison of
prognostic classification schemes for survival data", *Statistics in Medicine*
18(17-18), 1999. Uno et al., *Statistics in Medicine* 30(10), 2011.

Workstream: WS-3.1 Step 3 (SRS §7.3.2)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


class SurvivalError(Exception):
    """The inputs cannot support the metric being asked for."""


@dataclass(frozen=True)
class Subject:
    """One account's observed survival outcome.

    ``time`` is the observed time — the event time if ``event`` is true, the
    censoring time otherwise. Both are on the same axis (months on book), and
    conflating them is the classic survival-analysis error: a censored account
    at month 6 has *not* survived to month 6 and stopped, it has survived *at
    least* to month 6.
    """

    time: int
    event: bool

    def __post_init__(self) -> None:
        if self.time < 0:
            raise SurvivalError(f"observed time {self.time} is negative")


# --------------------------------------------------------------------------
# Kaplan-Meier
# --------------------------------------------------------------------------


@dataclass
class StepFunction:
    """A right-continuous step function, as Kaplan-Meier produces."""

    times: list[int] = field(default_factory=list)
    values: list[float] = field(default_factory=list)

    def at(self, t: float) -> float:
        """Value at ``t``. Before the first step the value is 1.0."""
        out = 1.0
        for time, value in zip(self.times, self.values):
            if time > t:
                break
            out = value
        return out

    def to_dict(self) -> dict:
        return {"times": list(self.times), "values": [round(v, 6) for v in self.values]}


def kaplan_meier(subjects: Sequence[Subject]) -> StepFunction:
    """Product-limit estimate of S(t) = P(T > t)."""
    return _product_limit(subjects, event_of=lambda s: s.event)


def censoring_survival(subjects: Sequence[Subject]) -> StepFunction:
    """Kaplan-Meier estimate of the *censoring* distribution, Ĝ(t).

    The event indicator is reversed: an account that was censored is an
    "event" for this purpose. Ĝ(t) is the probability of remaining uncensored
    past t, and 1/Ĝ is the weight Graf et al. use to undo the selection that
    censoring imposes.
    """
    return _product_limit(subjects, event_of=lambda s: not s.event)


def _product_limit(subjects: Sequence[Subject], *, event_of) -> StepFunction:
    if not subjects:
        raise SurvivalError("cannot estimate a survival curve from no subjects")

    at_time: dict[int, list[int]] = {}
    for s in subjects:
        bucket = at_time.setdefault(s.time, [0, 0])   # [events, total]
        bucket[1] += 1
        if event_of(s):
            bucket[0] += 1

    n_at_risk = len(subjects)
    survival = 1.0
    out = StepFunction()
    for t in sorted(at_time):
        events, total = at_time[t]
        if n_at_risk > 0 and events > 0:
            survival *= (1.0 - events / n_at_risk)
            out.times.append(t)
            out.values.append(survival)
        n_at_risk -= total
    return out


# --------------------------------------------------------------------------
# Harrell's C-index
# --------------------------------------------------------------------------


@dataclass
class Concordance:
    """Harrell's C with the counts behind it, and the caveat that applies."""

    concordant: float
    comparable: int
    tied_risk: int
    censoring_rate: float

    @property
    def c_index(self) -> float | None:
        if self.comparable == 0:
            return None
        return self.concordant / self.comparable

    @property
    def caveat(self) -> str:
        """Whether the censoring rate makes Harrell's C optimistic."""
        if self.censoring_rate >= 0.5:
            return (
                f"{self.censoring_rate:.0%} of subjects are censored; Harrell's C "
                "is biased upward at this level (Uno et al. 2011). Read it as an "
                "upper bound and compare only against other Harrell's C values on "
                "the same censoring pattern."
            )
        return ""

    def to_dict(self) -> dict:
        return {
            "c_index": self.c_index,
            "comparable_pairs": self.comparable,
            "tied_risk_pairs": self.tied_risk,
            "censoring_rate": round(self.censoring_rate, 4),
            "caveat": self.caveat,
        }


def harrell_c(subjects: Sequence[Subject], risk: Sequence[float]) -> Concordance:
    """Harrell's concordance index.

    A pair is *comparable* when the ordering of their event times is known
    despite censoring: either the earlier time carries an event, or the times
    tie and exactly one carries an event. Higher ``risk`` should mean earlier
    failure, so a concordant pair is one where the subject that failed first
    carried the higher risk score. Ties in risk count a half — the model
    expressed no preference, and scoring them as wins would reward a constant
    model with 1.0.
    """
    if len(subjects) != len(risk):
        raise SurvivalError(
            f"{len(subjects)} subjects but {len(risk)} risk scores"
        )
    if not subjects:
        raise SurvivalError("cannot compute concordance from no subjects")

    concordant = 0.0
    comparable = 0
    tied = 0

    for i, (si, ri) in enumerate(zip(subjects, risk)):
        if not si.event:
            continue
        for j, (sj, rj) in enumerate(zip(subjects, risk)):
            if i == j:
                continue
            if sj.time > si.time:
                pass
            elif sj.time == si.time and not sj.event:
                pass
            else:
                continue
            comparable += 1
            if ri > rj:
                concordant += 1.0
            elif ri == rj:
                concordant += 0.5
                tied += 1

    censored = sum(1 for s in subjects if not s.event)
    return Concordance(concordant, comparable, tied, censored / len(subjects))


# --------------------------------------------------------------------------
# Time-dependent AUC (cumulative cases / dynamic controls, IPCW)
# --------------------------------------------------------------------------


def time_dependent_auc(
    subjects: Sequence[Subject],
    risk: Sequence[float],
    times: Sequence[int],
) -> list[tuple[int, float | None]]:
    """Cumulative/dynamic AUC at each horizon in ``times`` (Uno et al. 2007).

    At horizon ``t`` the cases are subjects who had the event by ``t`` and the
    controls are those still event-free after ``t``. Cases are weighted by
    ``1/Ĝ(T_i)`` so that a case which only became observable because it was
    *not* censored does not over-represent itself.

    Returns ``None`` for a horizon with no cases or no controls, rather than a
    number: an AUC computed on an empty case set is not 0.5, it is undefined,
    and printing 0.5 puts a plausible value on a chart with nothing behind it.
    """
    if len(subjects) != len(risk):
        raise SurvivalError(f"{len(subjects)} subjects but {len(risk)} risk scores")

    g = censoring_survival(subjects)
    out: list[tuple[int, float | None]] = []

    for t in times:
        cases: list[tuple[float, float]] = []   # (risk, weight)
        controls: list[float] = []
        for s, r in zip(subjects, risk):
            if s.event and s.time <= t:
                # Weight by the censoring survival just before the event.
                gt = g.at(s.time - 1)
                if gt > 0:
                    cases.append((r, 1.0 / gt))
            elif s.time > t:
                controls.append(r)

        if not cases or not controls:
            out.append((t, None))
            continue

        numerator = 0.0
        for r_case, w in cases:
            for r_control in controls:
                if r_case > r_control:
                    numerator += w
                elif r_case == r_control:
                    numerator += 0.5 * w
        denominator = sum(w for _, w in cases) * len(controls)
        out.append((t, numerator / denominator))
    return out


# --------------------------------------------------------------------------
# Brier score and its integral (Graf et al. 1999)
# --------------------------------------------------------------------------


def brier_at(
    subjects: Sequence[Subject],
    survival_at_t: Sequence[float],
    t: int,
    *,
    censoring: StepFunction | None = None,
) -> float:
    """IPCW Brier score at horizon ``t``.

    Three groups, and they are treated differently on purpose:

    * event before ``t`` — contributes ``(0 - Ŝ)²`` weighted by ``1/Ĝ(T_i)``;
    * still alive after ``t`` — contributes ``(1 - Ŝ)²`` weighted by ``1/Ĝ(t)``;
    * censored before ``t`` — contributes **nothing**, and its share of the
      weight is what the other two are scaled up by.
    """
    if len(subjects) != len(survival_at_t):
        raise SurvivalError(
            f"{len(subjects)} subjects but {len(survival_at_t)} survival predictions"
        )
    if not subjects:
        raise SurvivalError("cannot compute a Brier score from no subjects")

    g = censoring if censoring is not None else censoring_survival(subjects)
    g_t = g.at(t)
    total = 0.0

    for s, prediction in zip(subjects, survival_at_t):
        if not 0.0 <= prediction <= 1.0:
            raise SurvivalError(
                f"survival prediction {prediction} is outside [0, 1]"
            )
        if s.event and s.time <= t:
            gi = g.at(s.time - 1)
            if gi > 0:
                total += (prediction ** 2) / gi
        elif s.time > t:
            if g_t > 0:
                total += ((1.0 - prediction) ** 2) / g_t
    return total / len(subjects)


@dataclass
class IntegratedBrier:
    scores: list[tuple[int, float]]
    integrated: float

    def to_dict(self) -> dict:
        return {
            "integrated_brier": round(self.integrated, 6),
            "by_horizon": [(t, round(v, 6)) for t, v in self.scores],
        }


def integrated_brier(
    subjects: Sequence[Subject],
    survival_curves: Sequence[Sequence[float]],
    times: Sequence[int],
) -> IntegratedBrier:
    """Trapezoidal integral of the Brier score over ``times``.

    ``survival_curves[i][k]`` is subject ``i``'s predicted S(times[k]). The
    integral is normalised by the width of the horizon so that runs over
    different grids stay comparable.
    """
    if len(times) < 2:
        raise SurvivalError(
            "the integrated Brier score needs at least two horizons; for a "
            "single horizon call brier_at and say which horizon it is"
        )
    ordered = sorted(times)
    if list(times) != ordered:
        raise SurvivalError("times must be sorted ascending")

    censoring = censoring_survival(subjects)
    scores = []
    for k, t in enumerate(times):
        column = [curve[k] for curve in survival_curves]
        scores.append((t, brier_at(subjects, column, t, censoring=censoring)))

    area = 0.0
    for (t0, b0), (t1, b1) in zip(scores, scores[1:]):
        area += (t1 - t0) * (b0 + b1) / 2.0
    span = times[-1] - times[0]
    return IntegratedBrier(scores, area / span if span else 0.0)


# --------------------------------------------------------------------------
# S(t) calibration by decile (Phase 3 WS-3.1 Step 3)
# --------------------------------------------------------------------------


@dataclass
class CalibrationBucket:
    rank: int
    count: int
    predicted_survival: float
    observed_survival: float | None

    @property
    def gap(self) -> float | None:
        if self.observed_survival is None:
            return None
        return self.observed_survival - self.predicted_survival

    def to_dict(self) -> dict:
        return {
            "decile": self.rank,
            "accounts": self.count,
            "predicted_survival": round(self.predicted_survival, 6),
            "observed_survival": (
                round(self.observed_survival, 6)
                if self.observed_survival is not None else None
            ),
            "gap": round(self.gap, 6) if self.gap is not None else None,
        }


def survival_calibration(
    subjects: Sequence[Subject],
    survival_at_t: Sequence[float],
    t: int,
    *,
    buckets: int = 10,
) -> list[CalibrationBucket]:
    """Predicted vs Kaplan-Meier-observed S(t), by predicted-survival decile.

    The observed side is a Kaplan-Meier estimate *within the bucket*, not a raw
    proportion. A raw proportion would count a loan censored at month 3 as a
    survivor to month 12, which is the same error the IPCW weighting exists to
    prevent — and it biases every bucket in the same direction, so the plot
    looks well calibrated while the model is not.

    Rows are sorted on the prediction alone; tie groups are kept whole, so a
    model that outputs one constant value produces one bucket rather than ten
    identical ones sorted by an accidental secondary key.
    """
    if len(subjects) != len(survival_at_t):
        raise SurvivalError(
            f"{len(subjects)} subjects but {len(survival_at_t)} predictions"
        )
    if buckets < 1:
        raise SurvivalError("buckets must be positive")

    order = sorted(range(len(subjects)), key=lambda i: survival_at_t[i])
    target = max(1, len(order) // buckets)

    out: list[CalibrationBucket] = []
    start = 0
    while start < len(order):
        stop = min(start + target, len(order))
        # Keep a tie group whole: never split rows sharing a prediction.
        while stop < len(order) and survival_at_t[order[stop]] == survival_at_t[order[stop - 1]]:
            stop += 1
        chunk = order[start:stop]
        members = [subjects[i] for i in chunk]
        predicted = sum(survival_at_t[i] for i in chunk) / len(chunk)
        try:
            observed = kaplan_meier(members).at(t)
        except SurvivalError:
            observed = None
        out.append(CalibrationBucket(len(out) + 1, len(chunk), predicted, observed))
        start = stop
    return out

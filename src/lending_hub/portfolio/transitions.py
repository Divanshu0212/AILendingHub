"""DPD transition matrices, roll rates and CUSUM alarms (WS-3.2 Step 2).

SRS §9.3.2 specifies a monthly Markov transition matrix across DPD buckets, per
segment, with the 30→60 and 60→90 cells watched for deterioration — those two
cells are the earliest portfolio-level warning available, because they move
before anything reaches the NPA bucket and before any model score does.

Three things are computed here and they are graded differently:

* **The matrix itself** is `[DATA]` — counts over adjacent month pairs.
* **Forward multiplication** for short-horizon NPA forecasts is arithmetic, but
  it rests on time-homogeneity, which is false across a credit cycle.
  :meth:`TransitionMatrix.forward` carries the assumption in its return type
  rather than in a comment.
* **The CUSUM alarm** needs a reference shift ``k`` and a decision interval
  ``h``. Neither is in the SRS or the phase file, both set the false-alarm rate
  on a surface risk officers are expected to act on, and :func:`cusum`
  therefore takes them as required arguments. LH-307.

What this does not port
-----------------------
No Druid/ClickHouse rollup and no Flink job — those are the Track B backends.
This computes the same matrices in memory from
:meth:`lending_hub.portfolio.panel.Panel.pairs`, which is what a laptop can do
and what a test can assert on.

Workstream: WS-3.2 Step 2 (SRS §9.3.2)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from lending_hub.definitions import DEFAULT_DPD_THRESHOLD_DAYS
from lending_hub.portfolio.panel import AccountMonth

#: Bucket lower edges in days past due, `[SPEC]` from SRS §9.3.2's
#: ``{current, 1-30, 31-60, 61-90, 90+, closed}``. The top edge is imported
#: from Appendix A rather than restated: the NPA bucket and the default
#: definition are the same concept, and if the definition moves the bucket must
#: move with it or the dashboard and the provision disagree.
BUCKET_EDGES: tuple[int, ...] = (0, 1, 31, 61, DEFAULT_DPD_THRESHOLD_DAYS.value)

CURRENT = "current"
NPA = "npa"
CLOSED = "closed"
UNKNOWN = "unknown"
"""A month the servicer did not report. Not a bucket the account was *in* — it
is the absence of an observation, and folding it into ``current`` is the
cheapest way to make a roll rate look good."""


class TransitionError(Exception):
    """The transition matrix cannot be formed or read as asked."""


def bucket_names() -> list[str]:
    """Bucket labels in order, deteriorating left to right."""
    names = [CURRENT]
    for lower, upper in zip(BUCKET_EDGES[1:], BUCKET_EDGES[2:]):
        names.append(f"{lower}-{upper - 1}")
    names.append(NPA)
    names.append(CLOSED)
    names.append(UNKNOWN)
    return names


def bucket_of(dpd: int | None, *, closed: bool = False) -> str:
    """Which bucket a DPD reading falls in."""
    if closed:
        return CLOSED
    if dpd is None:
        return UNKNOWN
    if dpd < 0:
        raise TransitionError(f"DPD cannot be negative, got {dpd}")
    if dpd >= BUCKET_EDGES[-1]:
        return NPA
    if dpd == 0:
        return CURRENT
    for lower, upper in zip(BUCKET_EDGES[1:], BUCKET_EDGES[2:]):
        if lower <= dpd < upper:
            return f"{lower}-{upper - 1}"
    raise TransitionError(f"no bucket for DPD {dpd}")


@dataclass
class Forecast:
    """An n-step-ahead bucket distribution, and the assumption behind it."""

    steps: int
    distribution: dict[str, float]
    assumption: str = (
        "time-homogeneous Markov: this month's transition probabilities are "
        "assumed to hold for every future month. That is false across a credit "
        "cycle, and the error compounds with the horizon — a 3-month forecast "
        "is a projection, a 24-month one is an illustration."
    )

    def to_dict(self) -> dict:
        return {
            "steps": self.steps,
            "distribution": {k: round(v, 6) for k, v in self.distribution.items()},
            "assumption": self.assumption,
        }


@dataclass
class TransitionMatrix:
    """Monthly DPD-bucket transition counts and probabilities.

    ``counts[from][to]`` is the number of adjacent month pairs observed. The
    probability matrix is estimated only where the row has observations; a row
    with none is reported as ``None`` rather than as a uniform distribution,
    because "we never saw an account here" and "accounts here go everywhere"
    are opposite statements.
    """

    counts: dict[str, dict[str, int]] = field(default_factory=dict)
    segment: str = ""

    def row_total(self, bucket: str) -> int:
        return sum(self.counts.get(bucket, {}).values())

    def probability(self, source: str, target: str) -> float | None:
        total = self.row_total(source)
        if total == 0:
            return None
        return self.counts.get(source, {}).get(target, 0) / total

    def row(self, bucket: str) -> dict[str, float] | None:
        total = self.row_total(bucket)
        if total == 0:
            return None
        observed = self.counts.get(bucket, {})
        return {name: observed.get(name, 0) / total for name in bucket_names()}

    @property
    def observations(self) -> int:
        return sum(self.row_total(name) for name in bucket_names())

    def roll_rate(self, source: str, target: str) -> float | None:
        """The named cell — ``roll_rate('1-30', '31-60')`` is the 30→60 rate."""
        return self.probability(source, target)

    def forward(self, start: dict[str, float], steps: int) -> Forecast:
        """Propagate a bucket distribution ``steps`` months forward.

        Rows with no observations act as absorbing: an account in a bucket the
        matrix never saw is held there rather than being redistributed by an
        invented row. That makes an under-populated matrix produce an obviously
        stuck forecast instead of a plausible one.
        """
        if steps < 0:
            raise TransitionError("steps cannot be negative")
        total = sum(start.values())
        if total <= 0:
            raise TransitionError("the starting distribution sums to zero")

        current = {name: start.get(name, 0.0) / total for name in bucket_names()}
        for _ in range(steps):
            nxt = {name: 0.0 for name in bucket_names()}
            for source, mass in current.items():
                if mass == 0.0:
                    continue
                row = self.row(source)
                if row is None:
                    nxt[source] += mass
                    continue
                for target, probability in row.items():
                    nxt[target] += mass * probability
            current = nxt
        return Forecast(steps=steps, distribution=current)

    def to_dict(self) -> dict:
        return {
            "segment": self.segment,
            "observations": self.observations,
            "buckets": bucket_names(),
            "counts": {
                source: dict(sorted(targets.items()))
                for source, targets in sorted(self.counts.items())
            },
            "probabilities": {
                name: (
                    {k: round(v, 6) for k, v in row.items()}
                    if (row := self.row(name)) is not None else None
                )
                for name in bucket_names()
            },
        }


def build_matrix(
    pairs: Iterable[tuple[AccountMonth, AccountMonth]],
    *,
    segment: str = "",
) -> TransitionMatrix:
    """Count adjacent-month bucket transitions.

    Takes the pairs from :meth:`lending_hub.portfolio.panel.Panel.pairs`, which
    already refuses non-adjacent months — a jump from March to July is not one
    month's movement, and counting it as one puts four months of deterioration
    into a single cell.
    """
    matrix = TransitionMatrix(segment=segment)
    for before, after in pairs:
        source = bucket_of(before.dpd)
        target = bucket_of(after.dpd)
        matrix.counts.setdefault(source, {})
        matrix.counts[source][target] = matrix.counts[source].get(target, 0) + 1
    return matrix


# --------------------------------------------------------------------------
# CUSUM on a monitored cell
# --------------------------------------------------------------------------


@dataclass
class CusumPoint:
    period: str
    value: float
    standardised: float
    statistic: float
    alarm: bool

    def to_dict(self) -> dict:
        return {
            "period": self.period,
            "value": round(self.value, 6),
            "z": round(self.standardised, 4),
            "cusum": round(self.statistic, 4),
            "alarm": self.alarm,
        }


@dataclass
class CusumResult:
    baseline: float
    points: list[CusumPoint]
    reference_shift: float
    decision_interval: float

    @property
    def first_alarm(self) -> str | None:
        for point in self.points:
            if point.alarm:
                return point.period
        return None

    def to_dict(self) -> dict:
        return {
            "baseline_rate": round(self.baseline, 6),
            "reference_shift_k": self.reference_shift,
            "decision_interval_h": self.decision_interval,
            "first_alarm": self.first_alarm,
            "points": [p.to_dict() for p in self.points],
        }


def cusum(
    series: Sequence[tuple[str, int, int]],
    *,
    baseline: float,
    reference_shift: float,
    decision_interval: float,
) -> CusumResult:
    """One-sided upper CUSUM on a monitored roll rate.

    ``series`` is ``(period, numerator, denominator)`` — the cell count and its
    row total, per period. The rate is standardised against the baseline's
    binomial standard error before accumulating, so ``reference_shift`` and
    ``decision_interval`` are in sigma units and do not have to be re-tuned when
    portfolio volume changes.

    Both parameters are **required and have no defaults**. They set the
    false-alarm rate on a surface risk officers act on, and neither the SRS nor
    the phase file supplies them (LH-307). A CUSUM with invented parameters
    alarms at a rate nobody chose, which is worse than no alarm because it
    trains people to ignore it.
    """
    if not 0.0 <= baseline <= 1.0:
        raise TransitionError(f"baseline rate {baseline} is outside [0, 1]")
    if reference_shift < 0 or decision_interval <= 0:
        raise TransitionError(
            "reference_shift must be non-negative and decision_interval positive"
        )

    points: list[CusumPoint] = []
    statistic = 0.0
    for period, numerator, denominator in series:
        if denominator <= 0:
            raise TransitionError(
                f"{period}: denominator is {denominator}; a period with no "
                "accounts at risk has no rate, and treating it as zero is a "
                "spurious improvement"
            )
        rate = numerator / denominator
        variance = baseline * (1.0 - baseline) / denominator
        standard_error = math.sqrt(variance) if variance > 0 else 0.0
        z = (rate - baseline) / standard_error if standard_error > 0 else 0.0
        statistic = max(0.0, statistic + z - reference_shift)
        points.append(CusumPoint(
            period=period,
            value=rate,
            standardised=z,
            statistic=statistic,
            alarm=statistic > decision_interval,
        ))
    return CusumResult(
        baseline=baseline,
        points=points,
        reference_shift=reference_shift,
        decision_interval=decision_interval,
    )


def chi_square_against(
    observed: TransitionMatrix,
    baseline: TransitionMatrix,
    bucket: str,
) -> tuple[float, int] | None:
    """Chi-square statistic for one row against a trailing baseline row.

    Returns ``(statistic, degrees_of_freedom)`` and deliberately **no p-value**:
    converting it needs a chi-square CDF, and a significance figure on a
    dashboard is read as a decision rule. The statistic and its degrees of
    freedom are what a risk analyst needs to look one up deliberately.
    """
    expected_row = baseline.row(bucket)
    if expected_row is None:
        return None
    total = observed.row_total(bucket)
    if total == 0:
        return None

    statistic = 0.0
    cells = 0
    for target, probability in expected_row.items():
        expected = probability * total
        if expected <= 0:
            continue
        actual = observed.counts.get(bucket, {}).get(target, 0)
        statistic += (actual - expected) ** 2 / expected
        cells += 1
    return statistic, max(0, cells - 1)

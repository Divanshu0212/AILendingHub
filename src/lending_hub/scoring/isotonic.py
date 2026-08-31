"""Pool-adjacent-violators, and the isotonic regression built on it.

One primitive, two callers, which is why it is its own module rather than a
private helper inside either. Master §2 rule 2 allows one reference
implementation per algorithm, and both of these are the same algorithm:

* **Monotonic binning** (§4 Step 3) needs the event rate to be monotone across
  bins, and PAVA gives the L2-optimal monotone fit by pooling adjacent violators.
  The pooled blocks *are* the merged bins.
* **Calibration** (§4 Step 5) needs a monotone map from score to probability —
  isotonic regression ([Niculescu-Mizil & Caruana, ICML 2005]) — which is PAVA on
  the scores followed by a step-function lookup.

Reference implementations on Track B: ``sklearn.isotonic.IsotonicRegression`` and
OptBinning's monotone solver. This is the Track A port, and the tests reproduce
the properties those libraries guarantee rather than asserting hand-computed
numbers.

Workstream: WS-1.1 Steps 3 and 5 · SRS §4.3.1, §4.3.2
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from enum import Enum
from typing import Sequence


class Direction(str, Enum):
    """Which way the fitted relationship is allowed to run."""

    INCREASING = "increasing"
    DECREASING = "decreasing"
    AUTO = "auto"
    """Chosen from the data. Legitimate for exploratory binning and **not** a
    substitute for the ratified direction list, which is `[POLICY]` (LH-202). A
    result fitted this way records ``direction_source="data"`` so nobody later
    reads it as a constraint that was imposed."""


@dataclass(frozen=True)
class Block:
    """One pooled block: a run of adjacent inputs sharing a fitted value."""

    start: int
    stop: int
    weight: float
    value: float

    @property
    def size(self) -> int:
        return self.stop - self.start


def pool_adjacent_violators(
    values: Sequence[float],
    weights: Sequence[float] | None = None,
    *,
    direction: Direction = Direction.INCREASING,
) -> list[Block]:
    """Weighted PAVA. Returns the pooled blocks, in input order.

    The blocks are the useful output, not just the fitted values: binning needs to
    know *which* inputs were pooled together, because those are the bins that must
    merge. A function returning only the fitted series would force the caller to
    rediscover the blocks by comparing floats for equality.
    """
    if direction is Direction.AUTO:
        raise ValueError(
            "AUTO is a choice the caller makes between two fits, not a direction "
            "PAVA can be run with"
        )
    n = len(values)
    if weights is None:
        weights = [1.0] * n
    if len(weights) != n:
        raise ValueError("values and weights must be the same length")
    if any(w < 0 for w in weights):
        raise ValueError("weights cannot be negative")

    sign = 1.0 if direction is Direction.INCREASING else -1.0
    blocks: list[Block] = []

    for i in range(n):
        weight = weights[i]
        value = sign * values[i]
        start, stop = i, i + 1
        # A zero-weight point carries no information; pooling it with a mean of
        # 0/0 would produce a NaN that propagates silently through every
        # downstream bin.
        total = weight * value if weight else 0.0

        while blocks and (
            blocks[-1].value > value or (weight == 0 and blocks[-1].stop == start)
        ):
            previous = blocks.pop()
            start = previous.start
            total += previous.value * previous.weight
            weight += previous.weight
            value = total / weight if weight else previous.value

        blocks.append(Block(start=start, stop=stop, weight=weight, value=value))

    return [Block(b.start, b.stop, b.weight, sign * b.value) for b in blocks]


def fit_values(
    values: Sequence[float],
    weights: Sequence[float] | None = None,
    *,
    direction: Direction = Direction.INCREASING,
) -> list[float]:
    """The monotone fit, one value per input."""
    out = [0.0] * len(values)
    for block in pool_adjacent_violators(values, weights, direction=direction):
        for i in range(block.start, block.stop):
            out[i] = block.value
    return out


@dataclass
class IsotonicCalibrator:
    """A fitted monotone score -> probability map.

    Predicts by looking the score up in the fitted step function and
    interpolating linearly between knots. Interpolation rather than a bare step
    because a step function assigns identical probabilities to every score inside
    a block, and two applicants with visibly different scores getting the same PD
    is a question the model owner cannot answer in a validation meeting.
    """

    thresholds: list[float]
    probabilities: list[float]
    n_fitted: int = 0
    n_positives: int = 0

    def predict(self, score: float) -> float:
        if not self.thresholds:
            raise ValueError("calibrator is not fitted")
        if score <= self.thresholds[0]:
            return self.probabilities[0]
        if score >= self.thresholds[-1]:
            return self.probabilities[-1]

        index = bisect_right(self.thresholds, score)
        low_x, high_x = self.thresholds[index - 1], self.thresholds[index]
        low_y, high_y = self.probabilities[index - 1], self.probabilities[index]
        if high_x == low_x:
            return high_y
        fraction = (score - low_x) / (high_x - low_x)
        return low_y + fraction * (high_y - low_y)

    def predict_all(self, scores: Sequence[float]) -> list[float]:
        return [self.predict(score) for score in scores]

    def to_dict(self) -> dict:
        return {
            "kind": "isotonic",
            "knots": len(self.thresholds),
            "thresholds": self.thresholds,
            "probabilities": self.probabilities,
            "n_fitted": self.n_fitted,
            "n_positives": self.n_positives,
        }


def fit_isotonic(scores: Sequence[float], labels: Sequence[int]) -> IsotonicCalibrator:
    """Fit isotonic regression of ``labels`` on ``scores``.

    Ties are pooled before fitting. Without that, two identical scores with
    different labels become an ordering the fit has to invent, and the result
    depends on the order the rows arrived in — which makes the calibrator
    irreproducible from the same triplet (WS-0.2.3).
    """
    if len(scores) != len(labels):
        raise ValueError("scores and labels must be the same length")
    if not scores:
        raise ValueError("cannot calibrate on an empty sample")

    grouped: dict[float, list[int]] = {}
    for score, label in zip(scores, labels):
        grouped.setdefault(float(score), []).append(label)

    ordered = sorted(grouped)
    rates = [sum(grouped[s]) / len(grouped[s]) for s in ordered]
    weights = [float(len(grouped[s])) for s in ordered]

    blocks = pool_adjacent_violators(rates, weights, direction=Direction.INCREASING)

    thresholds: list[float] = []
    probabilities: list[float] = []
    for block in blocks:
        # One knot per block, anchored at the block's first and last score so the
        # interpolation between blocks is well defined.
        thresholds.append(ordered[block.start])
        probabilities.append(block.value)
        if block.stop - 1 != block.start:
            thresholds.append(ordered[block.stop - 1])
            probabilities.append(block.value)

    return IsotonicCalibrator(
        thresholds=thresholds,
        probabilities=probabilities,
        n_fitted=len(scores),
        n_positives=sum(labels),
    )

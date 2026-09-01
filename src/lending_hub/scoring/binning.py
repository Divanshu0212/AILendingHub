"""Monotone optimal binning, weight of evidence, and information value.

Phase 1 §4 WS-1.1 Step 3: "Library: OptBinning (monotonic optimal binning) → WOE
transform → scikit-learn logistic regression → PDO-20 score scaling (SRS §4.3.1).
IV window [0.02, 0.5]; IV > 0.5 → leakage-investigation ticket before use."

Master §2 rule 2 permits one reference implementation per algorithm, used or
ported with tests. This is the **port**, and the difference from the library is
stated rather than glossed:

    OptBinning solves binning as a mixed-integer program that maximises IV
    subject to a monotonicity constraint. This module instead takes the
    L2-optimal monotone fit of the event rate (PAVA) and adopts its pooled
    blocks as the bins.

Those are not the same optimisation and will not always give the same cut points.
They agree on what matters — bins are contiguous, event rates are monotone, and
IV is computed identically — and they differ at the margin on which of several
near-equal monotone binnings is chosen. The Track B adapter calls OptBinning; the
tests here assert the *properties* both must satisfy, so a Track B swap is
checkable rather than hopeful.

The direction question
----------------------
OptBinning's default picks the monotone direction from the data. That is the
right default for exploration and the wrong one for a shipped scorecard, because
a direction read off the training sample is not a constraint — it is a
restatement of the fit. Phase 1 §4 Step 3 (v1.1) settles it: the **same ratified
list that constrains the challenger governs the champion's binning direction**,
so that the two models cannot encode opposite risk relationships for one
characteristic and leave the Step 9 swap-set analysis comparing models that
disagree about the direction of risk.

The list is `[POLICY]` and does not exist yet (LH-202), so :class:`Binning`
records ``direction_source``: ``"policy"`` when a direction was imposed,
``"data"`` when it was inferred. A scorecard built entirely on inferred directions
is buildable, reportable, and not promotable.

Workstream: WS-1.1 Step 3 · SRS §4.3.1
"""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass
from typing import Sequence

from .features import ScreenVerdict, screen_iv
from .isotonic import Direction, pool_adjacent_violators

#: OptBinning's documented default minimum prebin size, adopted so the port and
#: the library start from the same fine binning. A *library default*, not a bank
#: policy — a bank that wants a different floor states it, and the value is a
#: parameter for exactly that reason.
DEFAULT_MIN_BIN_FRACTION = 0.05

#: Maximum number of quantile prebins before merging. OptBinning's default.
DEFAULT_MAX_PREBINS = 20

#: Added to both cells of a bin that has no goods or no bads, so its WOE is
#: finite. Stated as a constant rather than buried in an expression because the
#: adjustment changes the number, and a WOE quoted without it is not reproducible.
ZERO_CELL_ADJUSTMENT = 0.5


class BinningError(Exception):
    """The feature cannot be binned as requested."""


@dataclass(frozen=True)
class Bin:
    """One bin, with the counts that produced its WOE."""

    index: int
    lower: float | None
    """Inclusive lower edge; ``None`` means unbounded below."""

    upper: float | None
    """Exclusive upper edge; ``None`` means unbounded above."""

    count: int
    goods: int
    bads: int
    woe: float
    iv_contribution: float
    is_missing: bool = False
    zero_cell_adjusted: bool = False

    @property
    def event_rate(self) -> float | None:
        if self.count == 0:
            return None
        return self.bads / self.count

    def contains(self, value: float | None) -> bool:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return self.is_missing
        if self.is_missing:
            return False
        if self.lower is not None and value < self.lower:
            return False
        if self.upper is not None and value >= self.upper:
            return False
        return True

    def label(self) -> str:
        if self.is_missing:
            return "missing"
        low = "-inf" if self.lower is None else f"{self.lower:g}"
        high = "+inf" if self.upper is None else f"{self.upper:g}"
        return f"[{low}, {high})"

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "label": self.label(),
            "count": self.count,
            "goods": self.goods,
            "bads": self.bads,
            "event_rate": self.event_rate,
            "woe": self.woe,
            "iv_contribution": self.iv_contribution,
            "is_missing": self.is_missing,
            "zero_cell_adjusted": self.zero_cell_adjusted,
        }


@dataclass
class Binning:
    """A fitted binning for one feature."""

    feature: str
    bins: list[Bin]
    iv: float
    direction: Direction
    direction_source: str
    """``"policy"`` if the direction was imposed from the ratified list,
    ``"data"`` if it was inferred from this sample."""

    total_goods: int = 0
    total_bads: int = 0
    missing_count: int = 0

    def transform(self, value: float | None) -> float:
        """Map a raw value to its bin's WOE."""
        for candidate in self.bins:
            if candidate.contains(value):
                return candidate.woe
        raise BinningError(
            f"{self.feature}: {value!r} falls in no bin. The binning does not cover "
            "the domain, which means an unseen value would be scored by accident."
        )

    def bin_for(self, value: float | None) -> Bin:
        for candidate in self.bins:
            if candidate.contains(value):
                return candidate
        raise BinningError(f"{self.feature}: {value!r} falls in no bin")

    @property
    def monotone(self) -> bool:
        rates = [b.event_rate for b in self.bins if not b.is_missing and b.event_rate is not None]
        if len(rates) < 2:
            return True
        increasing = all(a <= b for a, b in zip(rates, rates[1:]))
        decreasing = all(a >= b for a, b in zip(rates, rates[1:]))
        return increasing or decreasing

    def screen(self) -> tuple[ScreenVerdict, str]:
        return screen_iv(self.iv)

    def to_dict(self) -> dict:
        verdict, note = self.screen()
        return {
            "feature": self.feature,
            "iv": self.iv,
            "iv_screen": verdict.value,
            "iv_note": note,
            "direction": self.direction.value,
            "direction_source": self.direction_source,
            "monotone": self.monotone,
            "n_bins": len(self.bins),
            "missing_count": self.missing_count,
            "bins": [b.to_dict() for b in self.bins],
        }


def _is_missing(value) -> bool:
    if value is None:
        return True
    return isinstance(value, float) and math.isnan(value)


def _woe_and_iv(goods: int, bads: int, total_goods: int, total_bads: int) -> tuple[float, float, bool]:
    """WOE and IV contribution for one bin.

    SRS §4.3.1: ``WOE = ln(%Goods / %Bads)`` and ``IV = Σ (%Goods − %Bads)·WOE``.
    A positive WOE therefore means *better than average*, which is the convention
    the scorecard's points scaling depends on — flipping it silently inverts every
    reason code.
    """
    adjusted = goods == 0 or bads == 0
    g = goods + ZERO_CELL_ADJUSTMENT if adjusted else goods
    b = bads + ZERO_CELL_ADJUSTMENT if adjusted else bads
    tg = total_goods + (ZERO_CELL_ADJUSTMENT if adjusted else 0)
    tb = total_bads + (ZERO_CELL_ADJUSTMENT if adjusted else 0)

    if tg <= 0 or tb <= 0:
        raise BinningError(
            "WOE needs both goods and bads in the population; a single-class sample "
            "has no evidence to weigh"
        )

    good_share = g / tg
    bad_share = b / tb
    woe = math.log(good_share / bad_share)
    return woe, (good_share - bad_share) * woe, adjusted


def _quantile_prebins(values: list[float], max_prebins: int) -> list[float]:
    """Interior cut points at quantiles of the observed values."""
    ordered = sorted(values)
    n = len(ordered)
    cuts: list[float] = []
    for k in range(1, max_prebins):
        index = int(round(k * n / max_prebins))
        if 0 < index < n:
            candidate = ordered[index]
            if not cuts or candidate > cuts[-1]:
                cuts.append(candidate)
    return cuts


def _group(pairs: list[tuple[float, int]], cuts: list[float]) -> list[tuple[int, int]]:
    """Counts of (goods, bads) per prebin, in ascending value order."""
    counts = [[0, 0] for _ in range(len(cuts) + 1)]
    for value, label in pairs:
        counts[bisect_right(cuts, value)][label] += 1
    return [(goods, bads) for goods, bads in counts]


def _merge_small(
    groups: list[tuple[int, int]], cuts: list[float], minimum: int
) -> tuple[list[tuple[int, int]], list[float]]:
    """Merge prebins below the minimum size into their neighbour."""
    groups = list(groups)
    cuts = list(cuts)
    while len(groups) > 1:
        sizes = [g + b for g, b in groups]
        smallest = min(range(len(groups)), key=lambda i: sizes[i])
        if sizes[smallest] >= minimum:
            break
        # Merge into the smaller neighbour, which keeps the merged bin as tight as
        # possible instead of snowballing into one giant bin.
        left = smallest - 1
        right = smallest + 1
        if left < 0:
            target = right
        elif right >= len(groups):
            target = left
        else:
            target = left if sizes[left] <= sizes[right] else right

        low, high = sorted((smallest, target))
        merged = (groups[low][0] + groups[high][0], groups[low][1] + groups[high][1])
        groups[low:high + 1] = [merged]
        del cuts[low]
    return groups, cuts


def fit_binning(
    values: Sequence[float | None],
    labels: Sequence[int],
    *,
    feature: str,
    direction: Direction = Direction.AUTO,
    min_bin_fraction: float = DEFAULT_MIN_BIN_FRACTION,
    max_prebins: int = DEFAULT_MAX_PREBINS,
) -> Binning:
    """Fit a monotone binning of ``values`` against binary ``labels`` (1 = bad).

    Missing values get their own bin, never an imputed one. For credit data
    missingness is usually informative — a thin file is a real segment, not a
    data-quality defect — and a separate bin lets the WOE say so.
    """
    if len(values) != len(labels):
        raise BinningError(f"{feature}: values and labels must be the same length")
    if not values:
        raise BinningError(f"{feature}: cannot bin an empty sample")
    if any(label not in (0, 1) for label in labels):
        raise BinningError(f"{feature}: labels must be 0 or 1")

    total_goods = sum(1 for label in labels if label == 0)
    total_bads = sum(1 for label in labels if label == 1)
    if total_goods == 0 or total_bads == 0:
        raise BinningError(
            f"{feature}: the sample has only one class, so no bin can carry evidence"
        )

    present: list[tuple[float, int]] = []
    missing_goods = missing_bads = 0
    for value, label in zip(values, labels):
        if _is_missing(value):
            if label == 1:
                missing_bads += 1
            else:
                missing_goods += 1
        else:
            present.append((float(value), label))

    if not present:
        raise BinningError(f"{feature}: every value is missing")

    minimum = max(1, int(min_bin_fraction * len(present)))
    cuts = _quantile_prebins([v for v, _ in present], max_prebins)
    groups = _group(present, cuts)
    groups, cuts = _merge_small(groups, cuts, minimum)

    if direction is Direction.AUTO:
        chosen = _choose_direction(groups, cuts, total_goods, total_bads, minimum)
        source = "data"
    else:
        chosen, source = direction, "policy"

    groups, cuts = _enforce_monotone(groups, cuts, chosen)
    groups, cuts = _merge_zero_cells(groups, cuts, minimum)

    bins: list[Bin] = []
    for index, (goods, bads) in enumerate(groups):
        woe, iv_part, adjusted = _woe_and_iv(goods, bads, total_goods, total_bads)
        bins.append(
            Bin(
                index=index,
                lower=None if index == 0 else cuts[index - 1],
                upper=None if index == len(groups) - 1 else cuts[index],
                count=goods + bads,
                goods=goods,
                bads=bads,
                woe=woe,
                iv_contribution=iv_part,
                zero_cell_adjusted=adjusted,
            )
        )

    missing_count = missing_goods + missing_bads
    if missing_count:
        woe, iv_part, adjusted = _woe_and_iv(
            missing_goods, missing_bads, total_goods, total_bads
        )
        bins.append(
            Bin(
                index=len(bins),
                lower=None,
                upper=None,
                count=missing_count,
                goods=missing_goods,
                bads=missing_bads,
                woe=woe,
                iv_contribution=iv_part,
                is_missing=True,
                zero_cell_adjusted=adjusted,
            )
        )

    return Binning(
        feature=feature,
        bins=bins,
        iv=sum(b.iv_contribution for b in bins),
        direction=chosen,
        direction_source=source,
        total_goods=total_goods,
        total_bads=total_bads,
        missing_count=missing_count,
    )


def _choose_direction(groups, cuts, total_goods, total_bads, minimum: int) -> Direction:
    """Pick the monotone direction that retains more information value."""
    best = None
    for candidate in (Direction.INCREASING, Direction.DECREASING):
        merged, merged_cuts = _enforce_monotone(groups, cuts, candidate)
        merged, _ = _merge_zero_cells(merged, merged_cuts, minimum)
        try:
            iv = sum(
                _woe_and_iv(g, b, total_goods, total_bads)[1] for g, b in merged
            )
        except BinningError:  # pragma: no cover - single-class guard upstream
            continue
        if best is None or iv > best[0]:
            best = (iv, candidate)
    return Direction.INCREASING if best is None else best[1]


def _enforce_monotone(groups, cuts, direction: Direction):
    """Merge adjacent bins until the event rate is monotone in ``direction``."""
    if len(groups) < 2:
        return list(groups), list(cuts)

    rates = [b / (g + b) if (g + b) else 0.0 for g, b in groups]
    weights = [float(g + b) for g, b in groups]
    blocks = pool_adjacent_violators(rates, weights, direction=direction)

    merged: list[tuple[int, int]] = []
    new_cuts: list[float] = []
    for position, block in enumerate(blocks):
        goods = sum(groups[i][0] for i in range(block.start, block.stop))
        bads = sum(groups[i][1] for i in range(block.start, block.stop))
        merged.append((goods, bads))
        if position < len(blocks) - 1:
            new_cuts.append(cuts[block.stop - 1])
    return merged, new_cuts


def _merge_zero_cells(groups, cuts, minimum: int):
    """Fold away *small* bins with no goods or no bads.

    Size is the whole of the rule, and getting it wrong defeats the leakage
    screen. A bin holding three loans and no bads is noise, and its adjusted WOE
    is an extreme number resting on nothing. A bin holding a fifth of the
    portfolio and no bads is the most informative thing in the dataset — and
    usually the sign that the feature post-dates the decision. Merging both away
    makes a perfectly-separating feature score IV ≈ 0 and read as *useless*
    rather than *suspicious*, so the one binning that should trip the IV ceiling
    is the one that never reaches it.

    So: below the minimum bin size, merge. At or above it, keep the bin and let
    :data:`ZERO_CELL_ADJUSTMENT` give it a finite WOE.

    Done after monotonicity rather than before: merging a zero cell pulls an event
    rate toward its neighbour's, so it cannot break a monotone ordering, whereas
    merging first would change the sequence PAVA sees.
    """
    groups = list(groups)
    cuts = list(cuts)
    while len(groups) > 1:
        offender = next(
            (
                i
                for i, (goods, bads) in enumerate(groups)
                if (goods == 0 or bads == 0) and goods + bads < minimum
            ),
            None,
        )
        if offender is None:
            break
        target = offender - 1 if offender > 0 else offender + 1
        low, high = sorted((offender, target))
        groups[low:high + 1] = [
            (groups[low][0] + groups[high][0], groups[low][1] + groups[high][1])
        ]
        del cuts[low]
    return groups, cuts


def information_value(binning: Binning) -> float:
    return binning.iv

"""The champion — a WOE-binned logistic regression scorecard.

Phase 1 §4 WS-1.1 Step 3 · SRS §4.3.1. Binning → WOE transform → logistic
regression → points scaling. Reason codes fall out of the points.

Two things here differ from the naive reading of the phase file, and both are
deliberate.

**The scale is not computable yet, and the code says so.**
Points are ``offset − factor·ln(odds)``. Phase 1 fixes PDO = 20 `[SPEC]`, which
fixes ``factor = PDO / ln(2)``. It fixes neither the anchor score nor the odds at
that anchor, and SRS CS-2's "e.g., 300–900 scale" is an illustration, not a
policy. Two of the three scaling constants are therefore ungrounded, and a
scorecard that emits a number on an invented scale is worse than one that emits
none: the number reaches a letter, a cutoff and a customer conversation, and
nothing about it looks wrong. So :meth:`Scorecard.points` raises until the anchor
is supplied, while :meth:`Scorecard.log_odds` and :meth:`Scorecard.predict` — the
calibrated PD, which is what pricing and IFRS-9 actually consume — work today.
Registered as LH-208.

**Reason codes are points-below-max.**
Phase 1 §4 Step 3 (v1.1) and SRS §4.3.1 require ranking by the distance from the
points this applicant got to the best points attainable on that characteristic.
Both documents originally said "largest negative point contributions", which
ranks characteristics by their *weight range* rather than by this applicant's
shortfall: a heavily-weighted characteristic on which the applicant scores
averagely outranks a lightly-weighted one on which they score worst, and the
customer is told the principal reason for their decline is something they are
unremarkable at. "The principal reasons why" is a question about the applicant.
The superseded rule is still implemented as ``method="largest_negative"``, because
a model validated under it needs to be reproducible under it.

Workstream: WS-1.1 Steps 3 and 6 · SRS §4.3.1, §11.2
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

from lending_hub.definitions import Grounded, Pending, Source, Ungrounded, fingerprint

from .binning import Binning
from .isotonic import Direction

#: Phase 1 §4 WS-1.1 Step 3 [SPEC]: "PDO-20 score scaling". Points to double the
#: odds. This one *is* grounded.
PDO = Grounded(
    value=20.0,
    source=Source.SPEC,
    citation="Phase_1_Credit_Scoring_Fraud.md §4 WS-1.1 Step 3 — 'PDO-20 score scaling'",
)

#: The other two scaling constants. SRS §4.3.1 gives the *form* — "points = offset
#: − factor·log-odds, e.g. 20 points to double the odds" — and SRS CS-2 offers
#: "e.g., 300–900" as an illustration of a scale, not as this bank's scale.
SCORE_ANCHOR = Pending(
    owner="Credit Risk Head",
    ticket="LH-208",
    note=(
        "the score anchor: the reference score and the odds at it. PDO fixes the "
        "slope of the points scale; nothing in the SRS or the phase file fixes its "
        "intercept, so no points value is computable"
    ),
)


class ScorecardError(Exception):
    """The scorecard cannot be built or read as requested."""


@dataclass(frozen=True)
class ScaleAnchor:
    """The `[POLICY]` half of the points scale, once someone supplies it."""

    reference_score: float
    reference_odds: float
    """Good:bad odds at ``reference_score``."""

    pdo: float = PDO.value

    def __post_init__(self) -> None:
        if self.reference_odds <= 0:
            raise ScorecardError("reference odds must be positive")
        if self.pdo <= 0:
            raise ScorecardError("PDO must be positive")

    @property
    def factor(self) -> float:
        return self.pdo / math.log(2.0)

    @property
    def offset(self) -> float:
        return self.reference_score - self.factor * math.log(self.reference_odds)

    def points(self, log_odds_good: float) -> float:
        """``offset + factor · ln(good:bad odds)``.

        The SRS writes ``offset − factor·log-odds`` with log-odds of *bad*; this
        is the same expression with the sign carried by the odds definition. It is
        written in terms of good:bad odds because that matches the WOE convention
        used throughout — ``ln(%goods/%bads)`` — and mixing the two conventions is
        how a scorecard ends up ranking backwards.
        """
        return self.offset + self.factor * log_odds_good


@dataclass
class Characteristic:
    """One binned feature and its fitted coefficient."""

    binning: Binning
    coefficient: float

    @property
    def name(self) -> str:
        return self.binning.feature

    def contribution(self, value) -> float:
        """This characteristic's addition to the log-odds of *good*."""
        return self.coefficient * self.binning.transform(value)

    def best_contribution(self) -> float:
        """The largest contribution attainable on this characteristic.

        The reference point for adverse-action reasons: what the applicant would
        have contributed had they been in the best bin.
        """
        return max(self.coefficient * b.woe for b in self.binning.bins)

    def worst_contribution(self) -> float:
        return min(self.coefficient * b.woe for b in self.binning.bins)


@dataclass(frozen=True)
class Reason:
    """One ranked adverse-action reason.

    ``code`` is a stable identifier, never rendered wording. Reason-code wording
    is `[POLICY: Compliance]` (LH-203) and is looked up from a versioned mapping
    table at render time — see :mod:`lending_hub.scoring.reasons`.
    """

    characteristic: str
    bin_label: str
    shortfall: float
    """Points (or log-odds) below the best attainable on this characteristic."""

    contribution: float
    method: str


@dataclass
class Scorecard:
    """A fitted scorecard: bins, coefficients, and an intercept."""

    characteristics: list[Characteristic]
    intercept: float
    anchor: ScaleAnchor | None = None
    definitions_fingerprint: str = field(default_factory=fingerprint)
    training_rows: int = 0
    training_bads: int = 0

    @property
    def names(self) -> list[str]:
        return [c.name for c in self.characteristics]

    def log_odds(self, row: dict) -> float:
        """Log-odds of *good* for one applicant."""
        total = self.intercept
        for characteristic in self.characteristics:
            if characteristic.name not in row:
                raise ScorecardError(
                    f"{characteristic.name!r} is missing from the row. A scorecard "
                    "cannot skip a characteristic — the missing bin is a bin, and "
                    "an absent key is a pipeline defect"
                )
            total += characteristic.contribution(row[characteristic.name])
        return total

    def predict(self, row: dict) -> float:
        """Probability of *bad* — the uncalibrated PD."""
        return 1.0 / (1.0 + math.exp(max(-60.0, min(60.0, self.log_odds(row)))))

    def predict_all(self, rows: Sequence[dict]) -> list[float]:
        return [self.predict(row) for row in rows]

    def points(self, row: dict) -> float:
        """The scaled score. Raises until the `[POLICY]` anchor is supplied."""
        if self.anchor is None:
            raise Ungrounded(
                f"{SCORE_ANCHOR} — the points scale has no anchor. PDO fixes the "
                "slope; the reference score and the odds at it are [POLICY] and "
                "nobody has stated them. Use predict() for the PD, which is "
                "grounded, and do not put an invented score in front of a customer."
            )
        return self.anchor.points(self.log_odds(row))

    def point_allocation(self, row: dict) -> dict[str, float]:
        """Points contributed by each characteristic, including the base."""
        if self.anchor is None:
            raise Ungrounded(f"{SCORE_ANCHOR} — no points scale, so no allocation")
        factor = self.anchor.factor
        allocation = {"(base)": self.anchor.offset + factor * self.intercept}
        for characteristic in self.characteristics:
            allocation[characteristic.name] = factor * characteristic.contribution(
                row[characteristic.name]
            )
        return allocation

    def reasons(self, row: dict, *, top: int = 5, method: str = "points_below_max") -> list[Reason]:
        """Ranked adverse-action reasons.

        ``points_below_max`` (default) ranks by how far this applicant's bin falls
        short of the best bin on the same characteristic — what Phase 1 §4 Step 3
        (v1.1) requires, and the one that answers "why *you*".
        ``largest_negative`` is the superseded rule, kept so a model validated
        under it stays reproducible; on a real scorecard it is dominated by
        whichever characteristics carry the widest weight range.

        Units are log-odds when no anchor is set and points when one is, so the
        ranking is identical either way — the anchor is a positive linear rescale.
        """
        if method not in ("points_below_max", "largest_negative"):
            raise ScorecardError(f"unknown reason method {method!r}")

        scale = self.anchor.factor if self.anchor else 1.0
        reasons: list[Reason] = []
        for characteristic in self.characteristics:
            value = row[characteristic.name]
            contribution = characteristic.contribution(value)
            if method == "points_below_max":
                shortfall = (characteristic.best_contribution() - contribution) * scale
            else:
                shortfall = -contribution * scale
            reasons.append(
                Reason(
                    characteristic=characteristic.name,
                    bin_label=characteristic.binning.bin_for(value).label(),
                    shortfall=shortfall,
                    contribution=contribution * scale,
                    method=method,
                )
            )

        # Ties broken by characteristic name so the same applicant scored twice
        # gets the same reasons in the same order (Master §3.3 replayability).
        reasons.sort(key=lambda r: (-r.shortfall, r.characteristic))
        return [r for r in reasons[:top] if r.shortfall > 0]

    def unresolved_directions(self) -> list[str]:
        """Characteristics whose monotone direction was inferred, not ratified."""
        return sorted(
            c.name for c in self.characteristics if c.binning.direction_source != "policy"
        )

    def to_dict(self) -> dict:
        return {
            "kind": "woe_logistic_scorecard",
            "intercept": self.intercept,
            "pdo": PDO.value,
            "anchor": (
                {
                    "reference_score": self.anchor.reference_score,
                    "reference_odds": self.anchor.reference_odds,
                    "factor": self.anchor.factor,
                    "offset": self.anchor.offset,
                }
                if self.anchor
                else str(SCORE_ANCHOR)
            ),
            "definitions_fingerprint": self.definitions_fingerprint,
            "training_rows": self.training_rows,
            "training_bads": self.training_bads,
            "unresolved_directions": self.unresolved_directions(),
            "characteristics": [
                {
                    "name": c.name,
                    "coefficient": c.coefficient,
                    "iv": c.binning.iv,
                    "direction": c.binning.direction.value,
                    "direction_source": c.binning.direction_source,
                    "bins": [b.to_dict() for b in c.binning.bins],
                }
                for c in self.characteristics
            ],
        }


def fit_scorecard(
    rows: Sequence[dict],
    labels: Sequence[int],
    binnings: Sequence[Binning],
    *,
    anchor: ScaleAnchor | None = None,
    epochs: int = 60,
    learning_rate: float = 0.1,
    l2: float = 1e-3,
    seed: int = 0,
) -> Scorecard:
    """Fit logistic regression on WOE-transformed characteristics.

    The target modelled is *good* (label 0), matching the WOE convention, so a
    positive coefficient on a positive WOE means "this bin is better than
    average" throughout. Fitting *bad* against a good-oriented WOE is the sign
    error that silently inverts every reason code, and it does not show up in AUC.
    """
    if len(rows) != len(labels):
        raise ScorecardError("rows and labels must be the same length")
    if not rows:
        raise ScorecardError("cannot fit on an empty sample")

    design: list[list[float]] = []
    for row in rows:
        design.append([b.transform(row[b.feature]) for b in binnings])

    good = [1 if label == 0 else 0 for label in labels]
    positives = sum(good)
    negatives = len(good) - positives
    if positives == 0 or negatives == 0:
        raise ScorecardError("a scorecard needs both goods and bads")

    weight_bad = positives / negatives

    width = len(binnings)
    weights = [0.0] * width
    intercept = 0.0

    import random as _random

    rng = _random.Random(seed)
    order = list(range(len(design)))
    for _ in range(epochs):
        rng.shuffle(order)
        for i in order:
            x, y = design[i], good[i]
            weight = 1.0 if y == 1 else weight_bad
            z = intercept + sum(w * xi for w, xi in zip(weights, x))
            error = (1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, z)))) - y) * weight
            for j, xi in enumerate(x):
                weights[j] -= learning_rate * (error * xi + l2 * weights[j])
            intercept -= learning_rate * error

    return Scorecard(
        characteristics=[
            Characteristic(binning=binning, coefficient=weight)
            for binning, weight in zip(binnings, weights)
        ],
        intercept=intercept,
        anchor=anchor,
        training_rows=len(rows),
        training_bads=negatives,
    )


def negative_coefficients(scorecard: Scorecard) -> list[str]:
    """Characteristics whose fitted coefficient has the wrong sign.

    On WOE-transformed inputs every coefficient should be positive: a higher WOE
    is a better bin, so it must raise the log-odds of good. A negative one means
    the characteristic is fighting the others through a correlation, and the
    resulting reason codes point the wrong way for that feature. Standard
    scorecard practice is to drop it and refit, which is a decision for the
    modeller — this function only makes it visible.
    """
    return sorted(c.name for c in scorecard.characteristics if c.coefficient < 0)

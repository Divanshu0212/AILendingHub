"""Geographic disparate-impact analysis of the agri features (SRS §11.3).

Phase 2 §6 deliverable 9 and §7 both require this, and it is a different
analysis from Phase 1's. LH-205 asks the Fair-Lending Committee for a disparity
bar on the application model's protected attributes; a *geographic* analysis
needs something LH-205 does not supply — the **unit of comparison**. District?
Agro-climatic zone? Tribal-area designation? Block? The answer changes the
result, and nothing ratifies one, which is LH-410.

Why geography is harder than the P1 case
------------------------------------------
A protected attribute is given. Geography is constructed, and it is constructed
by the analyst: the same book cut by district and by agro-zone produces
different disparities, and a cut chosen after seeing the numbers is not an
analysis. That is the substance of this module — the units come from outside it
with a ratification reference, and :func:`assess_geographic` refuses without
one.

There is a second problem specific to agri, and it is worse. The agri features
are **derived from land**, so a genuine agronomic signal and a geographic
disparity are the same measurement. A district on thin soil in a rain-shadow
really does have lower expected yields, so ``LandQualityIndex`` really is lower
there, so approval rates really will be lower — and that is simultaneously a
correct risk assessment and a geographic disparity of exactly the kind SRS §11.3
exists to surface. :class:`GeographicFinding` therefore reports the disparity
and the *land-quality gap alongside it*, so a reviewer can see how much of the
first is explained by the second. It does not adjudicate: deciding whether
agronomically-justified geographic disparity is acceptable is a policy question
about redlining, and it is precisely the question the memo is for.

What this does not port
-----------------------
No Fairlearn, no statistical significance testing beyond Wilson intervals, no
mitigation. It measures and refuses to conclude, following
``scoring.fairness.FairnessReport``.

Workstream: WS-2.4 (SRS §11.3), Phase 2 §6 deliverable 9
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

from lending_hub.definitions.provenance import Pending, Ungrounded

#: The geographic units the analysis compares, and the disparity level at which
#: a finding requires action. Phase 2 §6 deliverable 9 requires the memo;
#: nothing ratifies the units or the bar (LH-410).
GEOGRAPHIC_UNITS = Pending(
    owner="Fair Lending + Agri Credit Head",
    ticket="LH-410",
    note="the ratified geographic comparison units and the disparity bar",
)


class DisparateImpactError(Exception):
    """The analysis cannot be run on what was supplied."""


def _wilson(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval — the same estimator scoring.fairness uses.

    Wilson rather than normal-approximation because agri geographic units are
    small: a block with 40 applications and 2 approvals has a normal interval
    that runs below zero, and an interval that includes impossible values gets
    quietly discarded by whoever reads it.
    """
    if total == 0:
        return (0.0, 0.0)
    phat = successes / total
    denominator = 1 + z * z / total
    centre = (phat + z * z / (2 * total)) / denominator
    margin = (
        z * math.sqrt(phat * (1 - phat) / total + z * z / (4 * total * total))
    ) / denominator
    return (max(0.0, centre - margin), min(1.0, centre + margin))


@dataclass(frozen=True)
class UnitRates:
    """Approval and land-quality summary for one geographic unit."""

    unit: str
    n: int
    approvals: int
    mean_land_quality: float | None = None

    def __post_init__(self) -> None:
        if self.n < 0 or self.approvals < 0:
            raise DisparateImpactError(f"{self.unit}: negative counts")
        if self.approvals > self.n:
            raise DisparateImpactError(
                f"{self.unit}: {self.approvals} approvals of {self.n} applications"
            )

    @property
    def approval_rate(self) -> float:
        if self.n == 0:
            raise DisparateImpactError(
                f"{self.unit} has no applications; an approval rate over zero "
                "applications is unmeasured, not zero"
            )
        return self.approvals / self.n

    @property
    def confidence_interval(self) -> tuple[float, float]:
        return _wilson(self.approvals, self.n)


@dataclass(frozen=True)
class GeographicFinding:
    """A disparity between the best- and worst-served units, in context."""

    highest: UnitRates
    lowest: UnitRates
    rate_difference: float
    rate_ratio: float | None
    land_quality_gap: float | None
    intervals_overlap: bool

    @property
    def explained_by_land_quality(self) -> str:
        """A reading aid, deliberately not a verdict.

        The disparity and the agronomic signal are the same measurement in this
        phase: a rain-shadow district really does have lower yields, so a lower
        approval rate there is simultaneously correct risk assessment and
        geographic disparity. Whether that is acceptable is a redlining
        question, and it is the question the memo exists to answer.
        """
        if self.land_quality_gap is None:
            return "no land-quality data supplied; the disparity is unattributed"
        if self.land_quality_gap <= 0:
            return (
                "the lower-approval unit has equal or better land quality — the "
                "disparity is NOT explained by agronomy and warrants direct "
                "scrutiny"
            )
        return (
            f"the lower-approval unit also has land quality lower by "
            f"{self.land_quality_gap:.3f}; some of the disparity may be "
            "agronomic. Whether agronomically-justified geographic disparity is "
            "acceptable is a policy question (redlining), not a modelling one"
        )


@dataclass(frozen=True)
class GeographicReport:
    """Measured disparity with no verdict, mirroring FairnessReport.

    :meth:`verdict` raises. LH-410 owns both halves of what a verdict needs —
    which units to compare, and how much disparity is too much — and a bar
    invented here would be quoted as the bank's fair-lending standard for years.
    """

    unit_kind: str
    units: tuple[UnitRates, ...]
    finding: GeographicFinding
    ratification_reference: str

    def verdict(self) -> str:
        raise Ungrounded(
            f"no ratified geographic disparity bar ({GEOGRAPHIC_UNITS}). This "
            "report measures disparity between "
            f"{self.finding.highest.unit} and {self.finding.lowest.unit}; it "
            "does not decide whether that disparity requires action. Phase 1's "
            "LH-205 sets a bar for protected attributes and does not cover "
            "geographic units, which have to be chosen before they can be "
            "compared."
        )

    def to_dict(self) -> dict:
        return {
            "unit_kind": self.unit_kind,
            "ratification_reference": self.ratification_reference,
            "units": [
                {
                    "unit": u.unit,
                    "n": u.n,
                    "approval_rate": u.approval_rate,
                    "confidence_interval": list(u.confidence_interval),
                    "mean_land_quality": u.mean_land_quality,
                }
                for u in self.units
            ],
            "highest": self.finding.highest.unit,
            "lowest": self.finding.lowest.unit,
            "rate_difference": self.finding.rate_difference,
            "rate_ratio": self.finding.rate_ratio,
            "land_quality_gap": self.finding.land_quality_gap,
            "intervals_overlap": self.finding.intervals_overlap,
            "attribution_note": self.finding.explained_by_land_quality,
            "verdict": "not computable: geographic units and bar are [POLICY] (LH-410)",
        }


def assess_geographic(
    units: Sequence[UnitRates],
    *,
    unit_kind: str,
    ratification_reference: str,
    min_unit_size: int = 30,
) -> GeographicReport:
    """Measure approval-rate disparity across geographic units.

    ``unit_kind`` and ``ratification_reference`` are both required. The unit
    choice *is* the analysis here — the same book cut by district and by
    agro-zone gives different answers — so an analysis that cannot say who
    chose the cut is an analysis of the cut.

    Units below ``min_unit_size`` are excluded and the exclusion is visible in
    the report's unit list: a block with 6 applications produces an approval
    rate of 0.0 or 1.0 that will otherwise be the extreme of every comparison.
    """
    if not ratification_reference:
        raise Ungrounded(
            f"geographic comparison units are not ratified ({GEOGRAPHIC_UNITS}). "
            "District, agro-zone, block and tribal-area designation give "
            "different disparities on the same book, and a cut chosen after "
            "seeing the numbers is not an analysis."
        )
    if not unit_kind:
        raise DisparateImpactError("unit_kind must name what the units are")

    eligible = [u for u in units if u.n >= min_unit_size]
    if len(eligible) < 2:
        raise DisparateImpactError(
            f"only {len(eligible)} of {len(units)} units have at least "
            f"{min_unit_size} applications; a disparity needs two comparable "
            "populations, and a unit of 6 applications supplies an approval "
            "rate of 0 or 1 that would be the extreme of every comparison"
        )

    highest = max(eligible, key=lambda u: u.approval_rate)
    lowest = min(eligible, key=lambda u: u.approval_rate)

    ratio = (
        lowest.approval_rate / highest.approval_rate
        if highest.approval_rate > 0
        else None
    )

    gap = None
    if highest.mean_land_quality is not None and lowest.mean_land_quality is not None:
        gap = highest.mean_land_quality - lowest.mean_land_quality

    high_low, high_high = highest.confidence_interval
    low_low, low_high = lowest.confidence_interval
    overlap = not (low_high < high_low or high_high < low_low)

    return GeographicReport(
        unit_kind=unit_kind,
        units=tuple(eligible),
        finding=GeographicFinding(
            highest=highest,
            lowest=lowest,
            rate_difference=highest.approval_rate - lowest.approval_rate,
            rate_ratio=ratio,
            land_quality_gap=gap,
            intervals_overlap=overlap,
        ),
        ratification_reference=ratification_reference,
    )

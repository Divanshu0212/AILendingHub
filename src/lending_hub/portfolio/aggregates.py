"""Portfolio aggregates, vintage curves and drill-through (WS-3.2 Steps 1, 4, 6).

SRS §9.2 asks for exposure, expected loss, DPD buckets, vintage curves and
concentration views. Phase 3 WS-3.2 adds two requirements that are easy to read
past and are the reason this is a module rather than a GROUP BY:

1. **Every panel shows a data-as-of timestamp.** The phase file's own words:
   "a dashboard that hides staleness manufactures false confidence". So
   :class:`Aggregate` cannot be constructed without one, and
   :attr:`Aggregate.freshness_seconds` is on every serialisation.
2. **Every aggregate resolves to the account list behind it, with lineage.**
   Drill-through is what makes a dashboard a tool rather than a poster, and it
   has to be built in — an aggregate that discarded its members cannot get them
   back.

Two things this refuses to do
-----------------------------
* **Choose the segments.** :func:`aggregate_by` takes a segmentation function
  and ships none. Reporting segment definitions are `[POLICY]` (Phase 3 §8,
  LH-306), and a dashboard whose segments were chosen by an engineer gets
  reconciled against Finance's numbers exactly once.
* **Compute LGD.** :class:`Exposure` carries an LGD that a caller supplies
  along with the basis it was measured on (LH-311), because expected loss
  computed from a net-of-enhancement LGD and one computed gross of it are
  different numbers with the same name.

Workstream: WS-3.2 Steps 1, 4, 6 (SRS §9.2, §9.3.1)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Callable, Iterable, Sequence

from lending_hub.definitions.provenance import Grounded, Pending, Source, Ungrounded
from lending_hub.portfolio.transitions import bucket_of

#: Dashboard freshness service level, `[SPEC]` from Phase 3 WS-3.2 Step 1.
FRESHNESS_SLO_SECONDS = Grounded(
    value=300,
    source=Source.SPEC,
    citation="Phase 3 WS-3.2 Step 1 — 'Freshness SLO <= 5 min'",
)

#: How the book is cut for management and regulatory reporting (Phase 3 §8).
REPORTING_SEGMENTS = Pending(
    owner="Risk Reporting + Finance",
    ticket="LH-306",
    note="the reporting segment definitions — product, geography, portfolio",
)


class AggregateError(Exception):
    """The aggregate cannot be formed or read as asked."""


@dataclass(frozen=True)
class Exposure:
    """One account's contribution to the book, at one snapshot.

    ``lgd_basis`` travels with ``lgd`` and is required whenever ``lgd`` is set.
    An expected loss is a product of three numbers, and one of them means two
    different things depending on a policy decision nobody has taken (LH-311);
    carrying the basis is what stops the two being summed together.
    """

    account_id: str
    snapshot: date
    ead_minor_units: int
    pd: float | None = None
    lgd: float | None = None
    lgd_basis: str | None = None
    dpd: int | None = None
    closed: bool = False
    origination: date | None = None
    attributes: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.ead_minor_units < 0:
            raise AggregateError(f"{self.account_id}: EAD cannot be negative")
        for name in ("pd", "lgd"):
            value = getattr(self, name)
            if value is not None and not 0.0 <= value <= 1.0:
                raise AggregateError(
                    f"{self.account_id}: {name} is {value}, outside [0, 1]"
                )
        if self.lgd is not None and not self.lgd_basis:
            raise AggregateError(
                f"{self.account_id}: an LGD was supplied with no basis. Net and "
                "gross of credit enhancement are different quantities (LH-311) "
                "and summing them produces a number with no interpretation."
            )

    @property
    def bucket(self) -> str:
        return bucket_of(self.dpd, closed=self.closed)

    @property
    def expected_loss_minor_units(self) -> int | None:
        """``PD x LGD x EAD``. None when any factor is missing."""
        if self.pd is None or self.lgd is None:
            return None
        return int(round(self.pd * self.lgd * self.ead_minor_units))


@dataclass
class Aggregate:
    """One aggregated cell, with its staleness and its members.

    ``members`` is the drill-through: the account ids behind the number, in the
    order they were aggregated. Held rather than counted, because an aggregate
    that discarded them cannot answer "which accounts" afterwards, and that is
    the first question anyone asks of a red number.
    """

    key: str
    as_of: datetime
    computed_at: datetime
    accounts: int = 0
    ead_minor_units: int = 0
    expected_loss_minor_units: int = 0
    exposures_missing_pd: int = 0
    exposures_missing_lgd: int = 0
    bucket_ead: dict[str, int] = field(default_factory=dict)
    lgd_bases: set = field(default_factory=set)
    members: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None or self.computed_at.tzinfo is None:
            raise AggregateError(
                "as_of and computed_at must be timezone-aware. A naive timestamp "
                "on a freshness indicator is a freshness indicator that is wrong "
                "by the reader's offset and says nothing about it."
            )
        if self.as_of > self.computed_at:
            raise AggregateError(
                f"as_of {self.as_of.isoformat()} is after computed_at "
                f"{self.computed_at.isoformat()}; data cannot be newer than the "
                "pass that read it"
            )

    @property
    def freshness_seconds(self) -> float:
        return (self.computed_at - self.as_of).total_seconds()

    @property
    def meets_freshness_slo(self) -> bool:
        return self.freshness_seconds <= FRESHNESS_SLO_SECONDS.value

    @property
    def coverage(self) -> float:
        """Share of accounts with a computable expected loss."""
        if not self.accounts:
            return 0.0
        missing = max(self.exposures_missing_pd, self.exposures_missing_lgd)
        return (self.accounts - missing) / self.accounts

    @property
    def mixed_lgd_bases(self) -> bool:
        """Whether this cell summed LGDs measured on different bases."""
        return len(self.lgd_bases) > 1

    def to_dict(self, *, include_members: bool = False) -> dict:
        out = {
            "key": self.key,
            "as_of": self.as_of.isoformat(),
            "computed_at": self.computed_at.isoformat(),
            "freshness_seconds": round(self.freshness_seconds, 3),
            "freshness_slo_seconds": FRESHNESS_SLO_SECONDS.value,
            "meets_freshness_slo": self.meets_freshness_slo,
            "accounts": self.accounts,
            "ead_minor_units": self.ead_minor_units,
            "expected_loss_minor_units": self.expected_loss_minor_units,
            "expected_loss_coverage": round(self.coverage, 4),
            "accounts_missing_pd": self.exposures_missing_pd,
            "accounts_missing_lgd": self.exposures_missing_lgd,
            "lgd_bases": sorted(self.lgd_bases),
            "mixed_lgd_bases": self.mixed_lgd_bases,
            "ead_by_bucket": dict(sorted(self.bucket_ead.items())),
        }
        if include_members:
            out["members"] = list(self.members)
        return out


def aggregate_by(
    exposures: Iterable[Exposure],
    segment_of: Callable[[Exposure], str],
    *,
    as_of: datetime,
    computed_at: datetime | None = None,
) -> dict[str, Aggregate]:
    """Aggregate exposures into cells named by ``segment_of``.

    ``segment_of`` is a required argument and no default segmentation is
    offered: reporting segments are LH-306. Passing ``lambda e: "book"`` for a
    whole-book total is a deliberate one-line decision by the caller, which is
    the point.
    """
    if computed_at is None:
        computed_at = datetime.now(timezone.utc)

    cells: dict[str, Aggregate] = {}
    for exposure in exposures:
        key = segment_of(exposure)
        cell = cells.get(key)
        if cell is None:
            cell = Aggregate(key=key, as_of=as_of, computed_at=computed_at)
            cells[key] = cell

        cell.accounts += 1
        cell.ead_minor_units += exposure.ead_minor_units
        cell.members.append(exposure.account_id)
        cell.bucket_ead[exposure.bucket] = (
            cell.bucket_ead.get(exposure.bucket, 0) + exposure.ead_minor_units
        )
        if exposure.pd is None:
            cell.exposures_missing_pd += 1
        if exposure.lgd is None:
            cell.exposures_missing_lgd += 1
        else:
            cell.lgd_bases.add(exposure.lgd_basis)
        el = exposure.expected_loss_minor_units
        if el is not None:
            cell.expected_loss_minor_units += el
    return cells


def require_segmentation(segments=REPORTING_SEGMENTS):
    """Raise unless the reporting segmentation has been ratified (LH-306)."""
    if isinstance(segments, Pending):
        raise Ungrounded(
            f"the reporting segmentation is not ratified: {segments}. Phase 3 §8 "
            "puts segment definitions on the do-not-invent list. aggregate_by() "
            "will aggregate by whatever function it is given — this gate is for "
            "the paths that publish a management or regulatory figure."
        )
    return segments


# --------------------------------------------------------------------------
# Vintage curves (SRS §9.2 RD-2)
# --------------------------------------------------------------------------


@dataclass
class VintagePoint:
    months_on_book: int
    cohort_size: int
    at_risk: int
    cumulative_bad: int

    @property
    def cumulative_bad_rate(self) -> float | None:
        """Cumulative bads over the *original* cohort, not those still at risk.

        The denominator is the cohort as originated. Using the still-at-risk
        count instead makes the curve bend upward at long durations purely
        because accounts have left, which is the standard way a vintage chart
        invents a deterioration that did not happen.
        """
        if self.cohort_size == 0:
            return None
        return self.cumulative_bad / self.cohort_size

    def to_dict(self) -> dict:
        return {
            "months_on_book": self.months_on_book,
            "cohort_size": self.cohort_size,
            "still_at_risk": self.at_risk,
            "cumulative_bad": self.cumulative_bad,
            "cumulative_bad_rate": (
                round(self.cumulative_bad_rate, 6)
                if self.cumulative_bad_rate is not None else None
            ),
        }


@dataclass
class VintageCurve:
    cohort: str
    points: list[VintagePoint] = field(default_factory=list)

    @property
    def cohort_size(self) -> int:
        return self.points[0].cohort_size if self.points else 0

    def rate_at(self, months_on_book: int) -> float | None:
        for point in self.points:
            if point.months_on_book == months_on_book:
                return point.cumulative_bad_rate
        return None

    def to_dict(self) -> dict:
        return {
            "cohort": self.cohort,
            "cohort_size": self.cohort_size,
            "points": [p.to_dict() for p in self.points],
        }


def vintage_curves(
    panel,
    cohort_of: Callable[[object], str],
    *,
    max_months: int,
) -> dict[str, VintageCurve]:
    """Cumulative bad rate by months on book, per origination cohort.

    A vintage chart is the one portfolio view that separates "the book is
    deteriorating" from "the book is younger than it was" — an overall bad rate
    conflates the two, and cohorts are the only way to tell which is happening.
    """
    if max_months < 1:
        raise AggregateError("max_months must be at least 1")

    from lending_hub.portfolio.panel import Event

    cohorts: dict[str, dict] = {}
    for spell in panel.spells:
        cohort = cohort_of(spell)
        state = cohorts.setdefault(cohort, {"size": 0, "bad_at": [], "last": []})
        state["size"] += 1
        bad_month = (
            _event_months_on_book(spell)
            if spell.event is Event.DEFAULT else None
        )
        state["bad_at"].append(bad_month)
        state["last"].append(
            spell.months[-1].months_on_book if spell.months else 0)

    out: dict[str, VintageCurve] = {}
    for cohort, state in sorted(cohorts.items()):
        curve = VintageCurve(cohort=cohort)
        for m in range(max_months + 1):
            cumulative = sum(
                1 for b in state["bad_at"] if b is not None and b <= m)
            at_risk = sum(
                1 for last, b in zip(state["last"], state["bad_at"])
                if last >= m and (b is None or b > m)
            )
            curve.points.append(VintagePoint(
                months_on_book=m,
                cohort_size=state["size"],
                at_risk=at_risk,
                cumulative_bad=cumulative,
            ))
        out[cohort] = curve
    return out


def _event_months_on_book(spell) -> int | None:
    if spell.event_month is None or not spell.months:
        return None
    from lending_hub.portfolio.panel import months_between
    last = spell.months[-1]
    return last.months_on_book + months_between(last.snapshot, spell.event_month)

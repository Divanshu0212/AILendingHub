"""The steady-state governance rhythm — Phase 6 WS-6.7.

WS-6.7 is a table: nightly, weekly, monthly, quarterly and annual activities,
each feeding a different phase's monitoring. It is the part of Phase 6 that makes
the phase "ongoing" rather than a project, and it is the part most likely to be
read as documentation.

It is modelled here because a cadence that lives only in a table has no state:
nothing knows when an activity last ran, so nothing can say it is overdue. The
first sign that a quarterly golden-set refresh stopped happening should not be a
model review eighteen months later.

What this module is not
-------------------------
**Not a scheduler.** It runs nothing and triggers nothing — Airflow is Track B's
(ADR-0003), behind the same ports seam as every other backend. What this
provides is the *schedule as data* plus overdue detection, which is what a gate
report and a monitoring dashboard both need and neither should re-derive.

**Not a source of new cadences.** Every entry below is transcribed from the
WS-6.7 table, and the intervals are `[SPEC]`. Where the phase file says
"monthly … as data warrants", the qualifier is preserved as
:attr:`Activity.conditional` rather than resolved into a hard interval, because
resolving it would invent a rule the phase file deliberately left to judgement.

The one thing the table leaves open
-------------------------------------
An activity's interval says how often it runs, not how late it may be before
someone is told. Those are different numbers: a weekly PSI check one day late is
noise, and a quarterly reject-inference cycle one day late may already have
missed its retrain. The phase file gives intervals and no tolerances, so
:func:`overdue` takes the grace period as an argument with no default, and
LH-807 registers the tolerance set.

Workstream: WS-6.7 · SRS §11
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum


class CadenceError(Exception):
    """Raised when a cadence question cannot be answered from what is recorded."""


class Frequency(str, Enum):
    """The five cadences in the WS-6.7 table. [SPEC]"""

    NIGHTLY = "nightly"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"

    @property
    def interval(self) -> timedelta:
        return {
            Frequency.NIGHTLY: timedelta(days=1),
            Frequency.WEEKLY: timedelta(days=7),
            Frequency.MONTHLY: timedelta(days=30),
            Frequency.QUARTERLY: timedelta(days=91),
            Frequency.ANNUAL: timedelta(days=365),
        }[self]


@dataclass(frozen=True)
class Activity:
    """One row of the WS-6.7 table."""

    name: str
    frequency: Frequency
    owning_phase: str
    """Which phase produces the thing being monitored. A cadence item whose
    owning phase has not shipped cannot run, and saying so is more useful than
    reporting it perpetually overdue."""

    conditional: str = ""
    """The phase file's own qualifier, preserved verbatim where it has one."""

    @property
    def is_conditional(self) -> bool:
        return bool(self.conditional)


#: The WS-6.7 table, transcribed. [SPEC] Phase 6 §2 WS-6.7.
CADENCE: tuple[Activity, ...] = (
    Activity("graph community scores", Frequency.NIGHTLY, "P6"),
    Activity("agri revisit processing", Frequency.NIGHTLY, "P2"),
    Activity("feature freshness checks", Frequency.NIGHTLY, "P0"),
    Activity("PSI/CSI + calibration monitors", Frequency.WEEKLY, "P1"),
    Activity("hallucination audit", Frequency.WEEKLY, "P5"),
    Activity("alert-precision tracking", Frequency.WEEKLY, "P4"),
    Activity(
        "fraud/EWS retrains",
        Frequency.MONTHLY,
        "P1",
        conditional="as data warrants",
    ),
    Activity("suitability audit", Frequency.MONTHLY, "P4"),
    Activity("fairness dashboards", Frequency.MONTHLY, "P1"),
    Activity("scoring retrain calendar", Frequency.QUARTERLY, "P1"),
    Activity("golden-set refresh", Frequency.QUARTERLY, "P5"),
    Activity("reject-inference cycle", Frequency.QUARTERLY, "P1"),
    Activity("exploration-cell review", Frequency.QUARTERLY, "P6"),
    Activity("full model revalidation", Frequency.ANNUAL, "P0"),
    Activity("definitions-package review", Frequency.ANNUAL, "P0"),
    Activity("DR test of decisioning fallback", Frequency.ANNUAL, "P0"),
)


@dataclass(frozen=True)
class OverdueItem:
    """An activity past its interval plus grace, or never run."""

    activity: Activity
    last_run: date | None
    days_late: int | None
    """``None`` when the activity has never run — which is not "infinitely late"
    but a different state, and the two are reported differently because they
    have different causes."""

    @property
    def never_run(self) -> bool:
        return self.last_run is None


def overdue(
    activities: Sequence[Activity],
    last_run: dict[str, date],
    *,
    as_of: date,
    grace: timedelta,
) -> tuple[OverdueItem, ...]:
    """Activities past their interval plus ``grace``.

    ``grace`` is required and has no default: the phase file states intervals
    and no tolerances, and a default here would silently become the tolerance
    for every activity in the programme regardless of consequence (LH-807).
    """
    if grace < timedelta(0):
        raise CadenceError("grace period cannot be negative")

    items: list[OverdueItem] = []
    for activity in activities:
        seen = last_run.get(activity.name)
        if seen is None:
            items.append(OverdueItem(activity, None, None))
            continue
        if seen > as_of:
            raise CadenceError(
                f"{activity.name!r} last ran {seen}, after the as-of date {as_of}"
            )
        due = seen + activity.frequency.interval + grace
        if as_of > due:
            items.append(OverdueItem(activity, seen, (as_of - due).days))
    return tuple(items)


def runnable(activities: Sequence[Activity], shipped_phases: Sequence[str]) -> tuple[Activity, ...]:
    """The activities whose owning phase has shipped.

    Separating these from the rest is what stops a cadence report from being a
    wall of red: an activity whose phase has not shipped is not overdue, it is
    not yet applicable, and reporting the two the same way is the not-measured /
    not-measurable error (Phase 3) in a monitoring dashboard.
    """
    shipped = set(shipped_phases)
    return tuple(a for a in activities if a.owning_phase in shipped)

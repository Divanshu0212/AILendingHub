"""Master Appendix A — Frozen Definitions v1, as importable code constants.

This module is the **single** place these definitions exist in executable form.
Master §2 rule 6: "Code imports them as constants from a single ``definitions``
package — never re-typed inline." A retyped ``dpd >= 90`` anywhere else in the
tree is a build failure, not a style nit — see ``tools/check_grounding.py``.

Changing anything here requires Model Risk Committee approval and an impact
analysis on every model importing it (Master §4). :func:`fingerprint` exists to
make that analysis mechanical rather than manual: a registered model records the
fingerprint it trained against, and CI flags every model whose recorded value has
gone stale.

Workstream: WS-0.3.4 · Unblocks: P1 target engineering onward
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum

from .provenance import Grounded, Pending, Source

DEFINITIONS_VERSION = "v1"
"""Appendix A version. Bumped only by Model Risk Committee decision."""

_MASTER = "00_MASTER_Implementation_Guide.md §4 Appendix A"


# ---------------------------------------------------------------------------
# Grounded scalar constants
# ---------------------------------------------------------------------------

DEFAULT_DPD_THRESHOLD_DAYS = Grounded(
    value=90,
    source=Source.SPEC,
    citation=f"{_MASTER} — 'max DPD >= 90 within the outcome window'",
)

INDETERMINATE_DPD_LOWER_DAYS = Grounded(
    value=30,
    source=Source.SPEC,
    citation=f"{_MASTER} — 'Indeterminate: 30-89 max DPD in window'",
)

INDETERMINATE_DPD_UPPER_DAYS = Grounded(
    value=89,
    source=Source.SPEC,
    citation=f"{_MASTER} — 'Indeterminate: 30-89 max DPD in window'",
)

OUTCOME_WINDOW_MONTHS = Grounded(
    value=12,
    source=Source.SPEC,
    citation=f"{_MASTER} — '12 months from disbursal ... next-12-months rolling'",
)

ALERT_PRECISION_WINDOW_DAYS = Grounded(
    value=90,
    source=Source.SPEC,
    citation=f"{_MASTER} — 'rolling 90 days, per signal'",
)


# ---------------------------------------------------------------------------
# Placeholders — the two Appendix A terms whose content is [POLICY]
# ---------------------------------------------------------------------------

CONFIRMED_FRAUD_DISPOSITION_CODES = Pending(
    owner="Fraud Head",
    ticket="LH-101",
    note="approved fraud-desk disposition taxonomy; suspicion is not a label",
)

AGRI_SEASON_CALENDAR = Pending(
    owner="Agri Credit Head",
    ticket="LH-102",
    note="ratified zone crop calendar giving Kharif/Rabi/Zaid boundaries per zone",
)

DISTRESS_RESTRUCTURE_CODES = Pending(
    owner="Credit Policy",
    ticket="LH-103",
    note=(
        "CBS restructure reason codes that count as distress. Appendix A names "
        "'restructure-due-to-distress' as a default trigger [SPEC], but the code set "
        "that identifies it in the source system is a bank mapping [POLICY]."
    ),
)

WRITE_OFF_CODES = Pending(
    owner="Finance Controller",
    ticket="LH-103",
    note="CBS/GL codes that constitute a write-off for target labelling",
)


# ---------------------------------------------------------------------------
# Target labelling
# ---------------------------------------------------------------------------


class Label(str, Enum):
    """Outcome label for a loan observed over its outcome window.

    ``INDETERMINATE`` is a first-class label, not a missing value: Appendix A
    excludes it from *training targets* while requiring it in *scoring and
    reporting*. Collapsing it into GOOD is the classic silent bias in a scorecard
    rebuild, so the type system refuses to let it disappear.
    """

    GOOD = "good"
    BAD = "bad"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True)
class OutcomeObservation:
    """What is known about one loan over one outcome window.

    Every field maps to an Appendix A default trigger. ``None`` means *not
    observed* and is distinct from ``False`` — an unobserved write-off flag must
    not be read as "did not write off".
    """

    max_dpd: int
    written_off: bool | None = None
    fraud_confirmed: bool | None = None
    restructured_due_to_distress: bool | None = None

    def __post_init__(self) -> None:
        if self.max_dpd < 0:
            raise ValueError("max_dpd cannot be negative")


def is_default(observation: OutcomeObservation) -> bool:
    """Appendix A *Default / Bad*.

    max DPD >= 90 within the outcome window, OR write-off, OR fraud-confirmed, OR
    restructure-due-to-distress — aligned with the IFRS-9 / Ind AS 109
    credit-impaired definition. One definition shared by scoring, provisioning,
    and EWS.
    """
    if observation.max_dpd >= DEFAULT_DPD_THRESHOLD_DAYS.value:
        return True
    return any(
        flag is True
        for flag in (
            observation.written_off,
            observation.fraud_confirmed,
            observation.restructured_due_to_distress,
        )
    )


def is_indeterminate(observation: OutcomeObservation) -> bool:
    """Appendix A *Indeterminate*: 30-89 max DPD in window, and not otherwise bad."""
    if is_default(observation):
        return False
    return (
        INDETERMINATE_DPD_LOWER_DAYS.value
        <= observation.max_dpd
        <= INDETERMINATE_DPD_UPPER_DAYS.value
    )


def label(observation: OutcomeObservation) -> Label:
    """Assign the Appendix A outcome label."""
    if is_default(observation):
        return Label.BAD
    if is_indeterminate(observation):
        return Label.INDETERMINATE
    return Label.GOOD


def is_trainable(observation: OutcomeObservation) -> bool:
    """Whether the observation may enter a training target.

    Indeterminates are excluded from training targets and included everywhere else.
    """
    return label(observation) is not Label.INDETERMINATE


# ---------------------------------------------------------------------------
# Windows and observation points
# ---------------------------------------------------------------------------


class Scoring(str, Enum):
    """Which scoring context a window/observation point belongs to."""

    APPLICATION = "application"
    BEHAVIORAL = "behavioral"


def outcome_window(start: date, months: int | None = None) -> tuple[date, date]:
    """Appendix A *Outcome window*, as a half-open ``[start, end)`` interval.

    Application scoring: 12 months from disbursal. Behavioral: next 12 months
    rolling from the snapshot month-end.
    """
    span = OUTCOME_WINDOW_MONTHS.value if months is None else months
    year = start.year + (start.month - 1 + span) // 12
    month = (start.month - 1 + span) % 12 + 1
    day = min(start.day, _days_in_month(year, month))
    return start, date(year, month, day)


def observation_point(
    scoring: Scoring,
    *,
    final_decision_at: date | None = None,
    snapshot_month_end: date | None = None,
) -> date:
    """Appendix A *Observation point*.

    Application: final-decision timestamp. Behavioral: snapshot month-end. All
    features must be computed strictly as-of this point — see
    ``lending_hub.featurestore.pit`` which takes this value as its cutoff.
    """
    if scoring is Scoring.APPLICATION:
        if final_decision_at is None:
            raise ValueError("application observation point is the final-decision timestamp")
        return final_decision_at
    if snapshot_month_end is None:
        raise ValueError("behavioral observation point is the snapshot month-end")
    if snapshot_month_end != month_end(snapshot_month_end):
        raise ValueError(
            f"{snapshot_month_end} is not a month-end; behavioral features are "
            "snapshotted month-end per Appendix A (daily once P3 streaming is live)"
        )
    return snapshot_month_end


def month_end(day: date) -> date:
    """Last calendar day of ``day``'s month — the DPD snapshot cadence."""
    return date(day.year, day.month, _days_in_month(day.year, day.month))


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - timedelta(days=1)).day


# ---------------------------------------------------------------------------
# Alert precision
# ---------------------------------------------------------------------------


def alert_precision(confirmed_relevant: int, total_alerts: int) -> float | None:
    """Appendix A *Alert precision*: confirmed-relevant dispositions / total alerts.

    Computed per signal over a rolling :data:`ALERT_PRECISION_WINDOW_DAYS` window.
    Returns ``None`` for an empty window rather than 0.0 — "no alerts fired" is
    not "every alert was wrong", and a dashboard that renders it as zero will
    trigger a false remediation.
    """
    if total_alerts < 0 or confirmed_relevant < 0:
        raise ValueError("counts cannot be negative")
    if confirmed_relevant > total_alerts:
        raise ValueError("confirmed-relevant dispositions cannot exceed total alerts")
    if total_alerts == 0:
        return None
    return confirmed_relevant / total_alerts


# ---------------------------------------------------------------------------
# The frozen register + fingerprint
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DefinitionEntry:
    """One Appendix A row, in the form a model card can cite."""

    term: str
    text: str
    binding: Grounded | Pending
    tags: tuple[str, ...] = field(default_factory=tuple)


REGISTER: tuple[DefinitionEntry, ...] = (
    DefinitionEntry(
        "DPD",
        "Days past due per the CBS ageing engine, snapshotted month-end "
        "(and daily once P3 streaming is live)",
        Grounded(value="cbs_ageing_engine", source=Source.SPEC, citation=_MASTER),
        ("scoring", "provisioning", "ews"),
    ),
    DefinitionEntry(
        "Default / Bad",
        "max DPD >= threshold within the outcome window, OR write-off, OR "
        "fraud-confirmed, OR restructure-due-to-distress; IFRS-9 / Ind AS 109 "
        "credit-impaired aligned",
        DEFAULT_DPD_THRESHOLD_DAYS,
        ("scoring", "provisioning", "ews"),
    ),
    DefinitionEntry(
        "Outcome window",
        "12 months from disbursal (application scoring); next-12-months rolling "
        "(behavioral)",
        OUTCOME_WINDOW_MONTHS,
        ("scoring",),
    ),
    DefinitionEntry(
        "Observation point",
        "Application: final-decision timestamp. Behavioral: snapshot month-end. "
        "All features computed strictly as-of this point (point-in-time joins)",
        Grounded(value="as_of_observation_point", source=Source.SPEC, citation=_MASTER),
        ("scoring", "featurestore"),
    ),
    DefinitionEntry(
        "Indeterminate",
        "30-89 max DPD in window: excluded from training targets, always included "
        "in scoring and reporting",
        INDETERMINATE_DPD_LOWER_DAYS,
        ("scoring",),
    ),
    DefinitionEntry(
        "Confirmed fraud",
        "Fraud-desk disposition code in the approved taxonomy; suspicion is not a label",
        CONFIRMED_FRAUD_DISPOSITION_CODES,
        ("fraud",),
    ),
    DefinitionEntry(
        "Agri season",
        "Kharif/Rabi/Zaid boundaries per ratified zone crop calendar",
        AGRI_SEASON_CALENDAR,
        ("agri",),
    ),
    DefinitionEntry(
        "Alert precision",
        "Confirmed-relevant dispositions / total alerts, rolling 90 days, per signal",
        ALERT_PRECISION_WINDOW_DAYS,
        ("ews", "fraud"),
    ),
)


def pending_definitions() -> tuple[DefinitionEntry, ...]:
    """Appendix A rows still waiting on a `[POLICY]` owner."""
    return tuple(e for e in REGISTER if isinstance(e.binding, Pending))


def fingerprint() -> str:
    """Stable content hash of the definitions register.

    A model records this at training time. When Appendix A changes, every model
    whose recorded fingerprint no longer matches is, by construction, in scope for
    the impact analysis Master §4 requires — no one has to remember which models
    used which definition.
    """
    payload = [
        {
            "term": e.term,
            "text": e.text,
            "binding": str(e.binding),
            "tags": list(e.tags),
        }
        for e in REGISTER
    ]
    blob = json.dumps(
        {"version": DEFINITIONS_VERSION, "entries": payload},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

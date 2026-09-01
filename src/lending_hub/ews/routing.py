"""Tiering, routing and fatigue guardrails (WS-4.A Step 5).

Phase 4 §4 Step 5:

    Amber (watch) / Red (act) → case management with: trigger reasons, PD delta,
    recommended action from the action library `[POLICY]`, SLA, owner.
    Disposition + outcome codes mandatory (P6 training data). Fatigue
    guardrails: per-officer daily alert cap; auto-retirement of any signal whose
    rolling precision falls below the floor `[POLICY]`.

(The phase file writes the window as a literal there; it is Appendix A's
``ALERT_PRECISION_WINDOW_DAYS`` and is imported rather than restated, so that a
change to the frozen definition moves collections alerting and P1 fraud
alerting together.)

and the two-key rule from §4 Step 3:

    change-point alone → Amber; change-point + negative direction + PD-velocity
    confirmation → Red. This keeps Red precision high.

An alert is not a notification
--------------------------------
Phase 4 §1: "every automated action has an owner, an SLA, and a captured
outcome." :class:`Alert` cannot be constructed without all three, and that is
the module's central design choice rather than a validation nicety. A queue of
alerts with no owner is a dashboard; a queue with no SLA has no definition of
late; and a queue with no outcome capture generates no training data, which
silently breaks Phase 6 two phases downstream. Each of the three is unavailable
here for a different reason, and each says which.

The two-key rule is right and under-specified
-----------------------------------------------
Requiring two independent mechanisms to agree before a high-severity tier fires
is the correct way to protect Red precision. But as a decision procedure the
rule names three conditions and quantifies none of them: what posterior counts
as a change-point (LH-512), how negative a direction must be, and what
percentile confirms (LH-501). :func:`tier` therefore takes the evaluated
conditions as booleans rather than raw values — the thresholds live with the
detectors that own them, and this module refuses to invent the combination.

Auto-retirement is the catalogue's immune system
--------------------------------------------------
A signal whose precision decays below the floor is retired automatically. The
important property is that retirement is *not* a human decision: a signal
degrading slowly is exactly the case where nobody notices, because each week's
precision looks like last week's. :func:`retire_degraded` is what makes §4 Step
1's ship gate hold over time rather than only at launch.

What this does not port
-----------------------
No case-management system, no queue, no work assignment, no SLA clock. Track B
integrates a real case manager behind :class:`CaseManagementPort`; this defines
what must cross that boundary and refuses to hand over an incomplete case.

Workstream: WS-4.A Step 5 (SRS §10)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import IntEnum
from typing import Mapping, Protocol, Sequence, runtime_checkable

from lending_hub.definitions import ALERT_PRECISION_WINDOW_DAYS
from lending_hub.definitions.provenance import Pending, Ungrounded
from lending_hub.ews.signals import PRECISION_FLOOR, SignalCatalog, SignalDefinition

#: The action library: the set of interventions an officer may be told to take,
#: with the SLA attached to each. Phase 4 §9 do-not-invent.
ACTION_LIBRARY = Pending(
    owner="Collections Head",
    ticket="LH-502",
    note="the ratified intervention set and the SLA attached to each",
)

#: The per-officer daily alert cap. Phase 4 §4 Step 5 requires the guardrail
#: without stating the number, and it is **not** derivable from the portfolio
#: alert budget — see LH-507 and :func:`apply_officer_cap`.
OFFICER_DAILY_ALERT_CAP = Pending(
    owner="Collections Head + Operations",
    ticket="LH-507",
    note="maximum alerts one officer may be assigned in a day",
)


class RoutingError(Exception):
    """An alert cannot be tiered, routed or capped."""


class Tier(IntEnum):
    """Alert severity. Ordered so a comparison means what it looks like.

    ``NONE`` exists as a value rather than an absence because "evaluated and
    nothing fired" and "not evaluated" are different states, and only the second
    is a gap in coverage.
    """

    NONE = 0
    AMBER = 1
    """Watch. Something changed; no confirmation that it is adverse."""

    RED = 2
    """Act. Two independent mechanisms agree, per the §4 Step 3 two-key rule."""


@dataclass(frozen=True)
class TwoKeyEvidence:
    """The three conditions the §4 Step 3 rule combines.

    Booleans rather than raw values on purpose: each condition's threshold
    belongs to the detector that owns it (BOCPD's posterior threshold, the
    velocity percentile), and evaluating them here would put three ungrounded
    numbers in a module that has no claim on any of them.
    """

    change_point: bool
    adverse_direction: bool
    velocity_confirmed: bool

    @property
    def keys_turned(self) -> int:
        return sum((self.change_point, self.adverse_direction, self.velocity_confirmed))


def tier(evidence: TwoKeyEvidence) -> Tier:
    """Apply the two-key rule.

    Phase 4 §4 Step 3 exactly: a change-point alone is Amber; a change-point
    *plus* an adverse direction *plus* velocity confirmation is Red.

    Note what this implies and the phase file does not say: **velocity
    confirmation without a change-point is not an alert at all.** A PD move with
    no corresponding regime change in cash flow is the ordinary drift of a
    hazard model over a month, and treating it as Amber would flood the queue
    with model noise. Raised as part of LH-508.
    """
    if not evidence.change_point:
        return Tier.NONE
    if evidence.adverse_direction and evidence.velocity_confirmed:
        return Tier.RED
    return Tier.AMBER


@dataclass(frozen=True)
class Disposition:
    """A collections officer's judgement on an alert.

    The numerator of every precision estimate in the catalogue, and the thing
    that does not exist here (LH-510). ``confirmed_relevant`` is the Appendix A
    quantity — whether the alert identified real deterioration, *not* whether
    the account subsequently defaulted. An alert that correctly identified
    distress the bank then successfully cured is a true positive, and scoring it
    against the default outcome would penalise the system for working.
    """

    alert_id: str
    disposed_at: datetime
    officer_id: str
    confirmed_relevant: bool
    outcome_code: str

    def __post_init__(self) -> None:
        if not self.outcome_code:
            raise RoutingError(
                f"{self.alert_id}: an outcome code is mandatory (Phase 4 §4 "
                "Step 5). It is P6's training data, so an alert closed without "
                "one is a case that trains nothing."
            )


@dataclass(frozen=True)
class Alert:
    """One routed alert. Cannot exist without an owner, an SLA and an outcome path.

    Phase 4 §1: "every automated action has an owner, an SLA, and a captured
    outcome." Enforced in the constructor because an alert missing any of the
    three is a different object — a notification — and the distinction stops
    being visible the moment it is in a queue with the others.
    """

    alert_id: str
    account_id: str
    tier: Tier
    raised_at: datetime
    trigger_reasons: tuple[str, ...]
    pd_delta: float | None
    recommended_action: str
    sla_hours: int
    owner_id: str
    signal_ids: tuple[str, ...] = ()
    disposition: Disposition | None = None

    def __post_init__(self) -> None:
        if self.tier is Tier.NONE:
            raise RoutingError(
                f"{self.alert_id}: an alert cannot be tier NONE. Nothing fired, "
                "so there is nothing to route — and a NONE alert in a queue is "
                "indistinguishable from a real one that was mis-tiered."
            )
        if not self.trigger_reasons:
            raise RoutingError(
                f"{self.alert_id}: Phase 4 §4 Step 5 requires trigger reasons on "
                "every case. An officer who cannot see why an alert fired cannot "
                "dispose of it correctly, and the disposition is the training "
                "signal for everything downstream."
            )
        if not self.owner_id:
            raise RoutingError(
                f"{self.alert_id}: every automated action has an owner (Phase 4 "
                "§1). An unowned alert is a notification."
            )
        if not self.recommended_action:
            raise RoutingError(
                f"{self.alert_id}: an alert must carry a recommended action from "
                f"the ratified library ({ACTION_LIBRARY}). An alert with no "
                "action tells an officer that something is wrong and not what to "
                "do, which is the least useful possible output."
            )
        if self.sla_hours <= 0:
            raise RoutingError(
                f"{self.alert_id}: an SLA of {self.sla_hours}h is not an SLA. "
                "Without one there is no definition of late, so §8's 'alert SLA "
                "compliance >= 90%' has nothing to measure."
            )

    @property
    def is_disposed(self) -> bool:
        return self.disposition is not None

    def breached_sla(self, *, now: datetime) -> bool:
        """Whether this alert is past its SLA and still open.

        A disposed alert never breaches retrospectively: the question is whether
        it *was* disposed in time, which is a property of the disposition.
        """
        if self.disposition is not None:
            elapsed = (self.disposition.disposed_at - self.raised_at).total_seconds()
            return elapsed > self.sla_hours * 3600
        return (now - self.raised_at).total_seconds() > self.sla_hours * 3600


@runtime_checkable
class CaseManagementPort(Protocol):
    """The Track B seam to a real case-management system.

    Track A implementations hold alerts in memory. Track B pushes them to the
    bank's case manager, which is Phase 4 §3's entry criterion ("case-management
    integration API available and tested") and does not exist here.
    """

    def open_case(self, alert: Alert) -> str: ...

    def record_disposition(self, disposition: Disposition) -> None: ...


class InMemoryCaseManager:
    """Track A case manager. Enforces the disposition requirement."""

    def __init__(self) -> None:
        self._cases: dict[str, Alert] = {}
        self._dispositions: dict[str, Disposition] = {}

    def open_case(self, alert: Alert) -> str:
        if alert.alert_id in self._cases:
            raise RoutingError(f"{alert.alert_id} is already open")
        self._cases[alert.alert_id] = alert
        return alert.alert_id

    def record_disposition(self, disposition: Disposition) -> None:
        if disposition.alert_id not in self._cases:
            raise RoutingError(
                f"{disposition.alert_id}: cannot dispose an alert that was never "
                "opened. A disposition arriving for an unknown alert means the "
                "case manager and the EWS disagree about what was raised, and "
                "every precision estimate built from them is wrong."
            )
        self._dispositions[disposition.alert_id] = disposition

    @property
    def open_cases(self) -> tuple[Alert, ...]:
        return tuple(
            a for a in self._cases.values() if a.alert_id not in self._dispositions
        )

    @property
    def undisposed_count(self) -> int:
        return len(self.open_cases)

    def disposition_for(self, alert_id: str) -> Disposition | None:
        return self._dispositions.get(alert_id)


@dataclass(frozen=True)
class OfficerAssignment:
    """Alerts assigned to one officer for one day, and what was held back."""

    officer_id: str
    assigned: tuple[Alert, ...]
    deferred: tuple[Alert, ...]
    cap: int

    @property
    def at_capacity(self) -> bool:
        return len(self.assigned) >= self.cap

    @property
    def deferred_red_count(self) -> int:
        """Red alerts held back by the cap.

        Reported separately because it is the number that says the cap is set
        wrong. Deferring Amber is the guardrail working; deferring Red means the
        book is generating more urgent work than the desk can absorb, and the
        answer is capacity or a stricter trigger — not a bigger cap.
        """
        return sum(1 for a in self.deferred if a.tier is Tier.RED)


def apply_officer_cap(
    alerts: Sequence[Alert], officer_id: str, *, cap: int | None = None
) -> OfficerAssignment:
    """Assign at most ``cap`` alerts to one officer, worst first.

    Phase 4 §4 Step 5's fatigue guardrail. ``cap`` has no default and raises
    without LH-507.

    **The cap is not derivable from the portfolio alert budget**, which is why
    it is a separate ticket. The budget is a portfolio-level *rate*; the cap is
    a per-person *workload*. Alerts are spatially and temporally correlated
    exactly when they matter — a district in drought, a local employer closing —
    so a book comfortably inside its budget can still bury the one officer
    covering that district on that day.

    Red before Amber, and within a tier, oldest first: an alert that has been
    waiting is closer to its SLA.
    """
    if cap is None:
        try:
            cap = OFFICER_DAILY_ALERT_CAP.value
        except Ungrounded as exc:
            raise Ungrounded(
                f"the per-officer daily alert cap is not ratified "
                f"({OFFICER_DAILY_ALERT_CAP}). Phase 4 §4 Step 5 requires the "
                "guardrail without stating the number, and it cannot be derived "
                "from the alert budget: the budget is a portfolio rate and the "
                "cap is a person's workload. A book inside its budget can still "
                "bury the officer covering a district in drought."
            ) from exc
    if cap <= 0:
        raise RoutingError(f"an alert cap of {cap} assigns nothing to anybody")

    ordered = sorted(alerts, key=lambda a: (-int(a.tier), a.raised_at))
    return OfficerAssignment(
        officer_id=officer_id,
        assigned=tuple(ordered[:cap]),
        deferred=tuple(ordered[cap:]),
        cap=cap,
    )


@dataclass(frozen=True)
class RetirementDecision:
    """Whether a signal should be auto-retired, and why."""

    signal_id: str
    retire: bool
    reason: str
    measured_precision: float | None
    alerts_in_window: int


def rolling_precision(
    dispositions: Sequence[Disposition],
    alerts: Mapping[str, Alert],
    signal_id: str,
    *,
    as_of: date,
    window_days: int | None = None,
) -> tuple[float | None, int]:
    """Precision for one signal over the rolling Appendix A window.

    Returns ``(precision, alert_count)``; precision is ``None`` when no alerts
    fired in the window, per the definitions package — "no alerts fired" is not
    "every alert was wrong", and a monitor that renders it as zero retires a
    working signal for being quiet.
    """
    window = window_days if window_days is not None else ALERT_PRECISION_WINDOW_DAYS.value
    if window <= 0:
        raise RoutingError(f"precision window must be positive, got {window}")

    in_window = []
    for disposition in dispositions:
        alert = alerts.get(disposition.alert_id)
        if alert is None or signal_id not in alert.signal_ids:
            continue
        age = (as_of - alert.raised_at.date()).days
        if 0 <= age < window:
            in_window.append(disposition)

    if not in_window:
        return None, 0
    confirmed = sum(1 for d in in_window if d.confirmed_relevant)
    return confirmed / len(in_window), len(in_window)


def retire_degraded(
    signal: SignalDefinition,
    dispositions: Sequence[Disposition],
    alerts: Mapping[str, Alert],
    *,
    as_of: date,
    floor: float | None = None,
) -> RetirementDecision:
    """Decide whether a signal has decayed below its precision floor.

    Phase 4 §4 Step 5: auto-retire any signal whose rolling precision — over
    Appendix A's window, imported not restated — falls below the floor. The
    important property is that this is **automatic** —
    a signal degrading slowly is exactly the case nobody notices, because each
    week's precision looks like last week's.

    Raises without a ratified floor (LH-501). A floor chosen here would retire
    or preserve signals on an engineer's judgement of what precision is
    acceptable, which is the alert budget's decision.
    """
    if floor is None:
        try:
            floor = PRECISION_FLOOR.value
        except Ungrounded as exc:
            raise Ungrounded(
                f"no ratified precision floor ({PRECISION_FLOOR}), so no signal "
                "can be auto-retired. Choosing one here would retire or preserve "
                "signals on an engineer's view of acceptable precision, which is "
                "the Collections Head's decision (LH-501)."
            ) from exc

    precision, count = rolling_precision(
        dispositions, alerts, signal.signal_id, as_of=as_of
    )

    if precision is None:
        return RetirementDecision(
            signal_id=signal.signal_id,
            retire=False,
            reason=(
                "no alerts in the rolling window; a quiet signal is not a wrong "
                "one, and retiring it would remove a rare-event detector for "
                "being rare"
            ),
            measured_precision=None,
            alerts_in_window=0,
        )

    if precision < floor:
        return RetirementDecision(
            signal_id=signal.signal_id,
            retire=True,
            reason=(
                f"rolling precision {precision:.3f} over {count} alerts is below "
                f"the {floor:.3f} floor"
            ),
            measured_precision=precision,
            alerts_in_window=count,
        )
    return RetirementDecision(
        signal_id=signal.signal_id,
        retire=False,
        reason=f"rolling precision {precision:.3f} holds the {floor:.3f} floor",
        measured_precision=precision,
        alerts_in_window=count,
    )


def apply_retirements(
    catalog: SignalCatalog, decisions: Sequence[RetirementDecision]
) -> tuple[str, ...]:
    """Disable every signal a retirement decision condemns.

    Sets ``enabled = False`` rather than removing the definition: a retired
    signal's history must remain interpretable, and a deleted definition makes
    every past alert that cited it unexplainable.
    """
    retired = []
    for decision in decisions:
        if not decision.retire:
            continue
        signal = catalog.get(decision.signal_id)
        catalog.signals[decision.signal_id] = SignalDefinition(
            signal_id=signal.signal_id,
            family=signal.family,
            version=signal.version,
            description=signal.description,
            direction=signal.direction,
            evaluate=signal.evaluate,
            srs_ref=signal.srs_ref,
            precision=signal.precision,
            enabled=False,
        )
        retired.append(decision.signal_id)
    return tuple(retired)

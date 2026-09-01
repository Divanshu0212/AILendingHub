"""Signal catalog — and the rule that a signal without precision does not ship.

Phase 4 §4 Step 1 states the contract:

    Implement the SRS §10.3 signal families as versioned, individually-toggleable
    definitions. **Rule: a signal ships only with a backtested precision estimate
    attached.** Signals without measurable precision do not ship — this is the
    anti-alert-fatigue contract.

That is the most important sentence in Workstream A, and it is the one this
module exists to enforce mechanically rather than remember.

Why alert fatigue is a modelling problem, not an ops problem
--------------------------------------------------------------
An early-warning system fails in a specific and predictable way. Signals are
cheap to add and each one seems individually reasonable, so the catalogue grows;
precision falls; officers learn that most alerts are noise and start triaging by
gut; and the *good* signals stop being acted on, because they arrive in the same
queue as the bad ones. The system then has excellent recall and no effect.

The defence is a ship gate on precision, and it only works if it is a gate. So
:meth:`SignalDefinition.shippable` returns ``(bool, reason)`` in the same shape
as ``GBM.promotable`` and ``BandConfig.effective``, and a catalogue can report
exactly which of its signals are admissible.

Precision here is not measurable at all, and that is the honest state
----------------------------------------------------------------------
Master Appendix A defines *Alert precision*, and this module imports both the
ratio and its window from :mod:`lending_hub.definitions` rather than restating
them. What matters here is the numerator: it counts **confirmed-relevant
dispositions**, which are human judgements recorded by a collections desk.
There is no desk (LH-510), so **no signal in this catalogue is shippable**, and
each one says so with a reason rather than carrying a plausible number.

The definition is imported from ``lending_hub.definitions``, never retyped
(Master §2 rule 6) — the same rolling window governs P1 fraud alerts and P4
collections alerts, and if it ever changes it must change for both at once.

What this does not port
-----------------------
No Flink, no SQL generation, no feature-store binding. A signal here is a
*definition* — an identity, a family, a version, an evaluator and its precision
evidence — not an execution plan. Track B compiles these into streaming
predicates behind ``featurestore.ports``.

Workstream: WS-4.A Step 1 (SRS §10.3)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Callable, Mapping, Sequence

from lending_hub.definitions import ALERT_PRECISION_WINDOW_DAYS, alert_precision
from lending_hub.definitions.provenance import Pending, Ungrounded

#: The per-signal precision floor below which a signal must not ship, and below
#: which a shipped signal auto-retires (Phase 4 §4 Steps 1 and 5). `[POLICY]`,
#: Phase 4 §9 do-not-invent.
PRECISION_FLOOR = Pending(
    owner="Collections Head",
    ticket="LH-501",
    note="the rolling-90-day precision floor a signal must hold to keep shipping",
)

#: Minimum alerts a precision estimate must be computed from before it is
#: allowed to gate anything. Not from the phase file, and not a policy value —
#: an engineering floor. Precision measured on 9 alerts has a 95% interval
#: roughly 0.3 wide, so a signal can pass or fail a floor on one disposition.
#: Reported as a Phase 4 finding.
MIN_ALERTS_FOR_PRECISION = 100


class SignalError(Exception):
    """A signal cannot be defined, evaluated, or admitted to the catalogue."""


class SignalFamily(str, Enum):
    """The SRS §10.3 signal families, verbatim.

    The family is not decoration. Fatigue guardrails and precision floors are
    applied per signal, but *correlation* is a property of the family: six
    repayment signals on one account fire together and produce six alerts about
    one fact, which is how a catalogue with individually acceptable precision
    still buries an officer.
    """

    REPAYMENT = "repayment"
    CASH_FLOW = "cash_flow"
    BUREAU = "bureau"
    AGRI = "agri"
    BEHAVIORAL = "behavioral"
    MACRO_LOCAL = "macro_local"


class Direction(str, Enum):
    """Which way a signal's underlying quantity moves when risk rises.

    Recorded because the two-key rule in Phase 4 §4 Step 3 requires a
    "negative direction" confirmation, and "negative" is meaningless without
    knowing whether the series is a balance (down is bad) or an arrears count
    (up is bad).
    """

    HIGHER_IS_WORSE = "higher_is_worse"
    LOWER_IS_WORSE = "lower_is_worse"


@dataclass(frozen=True)
class PrecisionEvidence:
    """A backtested precision estimate, with what it was computed from.

    The counts travel with the ratio because a precision of 0.31 from 13 alerts
    and one from 1,300 are not the same claim, and only one of them should gate
    a shipping decision.
    """

    confirmed_relevant: int
    total_alerts: int
    window_days: int
    measured_through: date
    source: str
    """Where the dispositions came from — a backtest run, a silent run, or live
    operation. A precision from a backtest and one from live alerts differ
    systematically: a backtest has no officer deciding what to look at."""

    def __post_init__(self) -> None:
        if self.total_alerts < 0 or self.confirmed_relevant < 0:
            raise SignalError("alert counts cannot be negative")
        if self.confirmed_relevant > self.total_alerts:
            raise SignalError(
                f"{self.confirmed_relevant} confirmed of {self.total_alerts} "
                "alerts — a disposition cannot confirm an alert that was never raised"
            )
        if self.window_days != ALERT_PRECISION_WINDOW_DAYS.value:
            raise SignalError(
                f"precision window {self.window_days}d does not match Appendix A's "
                f"{ALERT_PRECISION_WINDOW_DAYS.value}d. The window is a frozen "
                "definition shared with P1 fraud alerting; a signal measured over "
                "a different window is not comparable with the floor it is "
                "checked against."
            )
        if not self.source:
            raise SignalError(
                "precision evidence must name its source: a backtest precision "
                "and a live precision differ systematically, because a backtest "
                "has no officer choosing what to investigate"
            )

    @property
    def precision(self) -> float:
        """Appendix A's alert precision, computed by the definitions package."""
        return alert_precision(self.confirmed_relevant, self.total_alerts)

    @property
    def is_sufficient(self) -> bool:
        return self.total_alerts >= MIN_ALERTS_FOR_PRECISION


@dataclass(frozen=True)
class SignalDefinition:
    """One versioned, individually-toggleable signal.

    ``evaluate`` takes a feature mapping and returns whether the signal fires.
    It is a plain callable rather than an expression language because Track B
    compiles these to Flink/SQL and the Python form is the reference the
    compilation is checked against, not the production path.
    """

    signal_id: str
    family: SignalFamily
    version: str
    description: str
    direction: Direction
    evaluate: Callable[[Mapping], bool]
    srs_ref: str
    precision: PrecisionEvidence | None = None
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.signal_id:
            raise SignalError("a signal needs an id")
        if not self.version:
            raise SignalError(
                f"{self.signal_id}: a signal needs a version. Phase 4 §4 Step 1 "
                "requires versioned definitions because a signal whose logic "
                "changed silently invalidates every precision estimate measured "
                "against the old one."
            )
        if not self.srs_ref:
            raise SignalError(f"{self.signal_id}: a signal must cite its SRS clause")

    @property
    def shippable(self) -> tuple[bool, str]:
        """Whether this signal may be routed to a human, and why not.

        The anti-alert-fatigue contract as a value a gate script reads, in the
        same shape as ``GBM.promotable`` and ``BandConfig.effective``.

        Two independent conditions, and the second is the one that bites here:
        the signal needs a precision estimate at all, and there must be a
        ratified floor to compare it against (LH-501).
        """
        if self.precision is None:
            return False, (
                f"{self.signal_id} has no backtested precision estimate. "
                "Phase 4 §4 Step 1: signals without measurable precision do not "
                "ship. Dispositions are LH-510."
            )
        if not self.precision.is_sufficient:
            return False, (
                f"{self.signal_id} precision is measured on "
                f"{self.precision.total_alerts} alerts, below the "
                f"{MIN_ALERTS_FOR_PRECISION} needed for the estimate to gate "
                "anything — at that count one disposition moves it across a floor"
            )
        try:
            floor = PRECISION_FLOOR.value
        except Ungrounded:
            return False, (
                f"{self.signal_id} has precision {self.precision.precision:.3f} "
                f"and there is no ratified floor to compare it against "
                f"({PRECISION_FLOOR}). A floor chosen by whoever is shipping the "
                "signal is not a gate."
            )
        if self.precision.precision < floor:  # pragma: no cover - needs LH-501
            return False, (
                f"{self.signal_id} precision {self.precision.precision:.3f} is "
                f"below the {floor:.3f} floor"
            )
        return True, ""

    def fires(self, features: Mapping) -> bool:
        """Evaluate the signal, refusing on a missing input rather than defaulting.

        A signal that treats a missing feature as "did not fire" is silently
        disabled for exactly the accounts whose data is incomplete — which
        correlates with the accounts worth watching.
        """
        try:
            return bool(self.evaluate(features))
        except KeyError as exc:
            raise SignalError(
                f"{self.signal_id}: feature {exc} is missing. A signal that reads "
                "a missing feature as 'did not fire' is silently disabled for the "
                "accounts with incomplete data, which are not a random subset."
            ) from exc


@dataclass
class SignalCatalog:
    """The versioned catalogue, with per-signal toggles.

    Phase 4 §4 Step 1 asks for individually-toggleable definitions. The toggle is
    separate from shippability on purpose: ``enabled`` is an operational switch a
    duty manager flips during an incident, and ``shippable`` is a governance
    property nobody can flip. Conflating them would let a signal be re-enabled
    past its own ship gate.
    """

    version: str
    signals: dict[str, SignalDefinition] = field(default_factory=dict)

    def register(self, signal: SignalDefinition) -> None:
        existing = self.signals.get(signal.signal_id)
        if existing is not None and existing.version == signal.version:
            raise SignalError(
                f"{signal.signal_id} v{signal.version} is already registered. "
                "Re-registering under the same version is how a definition "
                "changes while its precision estimate keeps referring to the "
                "old one."
            )
        self.signals[signal.signal_id] = signal

    def get(self, signal_id: str) -> SignalDefinition:
        try:
            return self.signals[signal_id]
        except KeyError as exc:
            raise SignalError(f"no signal registered as {signal_id!r}") from exc

    @property
    def shippable(self) -> tuple[SignalDefinition, ...]:
        return tuple(s for s in self.signals.values() if s.shippable[0])

    @property
    def blocked(self) -> dict[str, str]:
        """Signal id -> why it cannot ship. The catalogue's honest state."""
        return {
            s.signal_id: s.shippable[1]
            for s in self.signals.values()
            if not s.shippable[0]
        }

    def active(self) -> tuple[SignalDefinition, ...]:
        """Signals that may actually raise an alert: enabled *and* shippable."""
        return tuple(s for s in self.signals.values() if s.enabled and s.shippable[0])

    def evaluate(self, features: Mapping) -> tuple[str, ...]:
        """Which active signals fire on this account.

        Only active signals are evaluated. A signal that has not passed its ship
        gate must not contribute to an alert even in shadow, because a shadow
        alert that reaches a queue is a live alert.
        """
        return tuple(s.signal_id for s in self.active() if s.fires(features))

    def by_family(self, family: SignalFamily) -> tuple[SignalDefinition, ...]:
        return tuple(s for s in self.signals.values() if s.family is family)

    def to_dict(self) -> dict:
        return {
            "catalog_version": self.version,
            "signals": {
                s.signal_id: {
                    "family": s.family.value,
                    "version": s.version,
                    "direction": s.direction.value,
                    "srs_ref": s.srs_ref,
                    "enabled": s.enabled,
                    "shippable": s.shippable[0],
                    "why_not": s.shippable[1],
                    "precision": (
                        {
                            "value": s.precision.precision,
                            "alerts": s.precision.total_alerts,
                            "source": s.precision.source,
                        }
                        if s.precision
                        else None
                    ),
                }
                for s in self.signals.values()
            },
            "shippable_count": len(self.shippable),
            "blocked_count": len(self.blocked),
        }


def catalog_v1() -> SignalCatalog:
    """Signal catalog v1 — the SRS §10.3 families as definitions.

    Every signal here is **unshippable**, and that is the correct state rather
    than an incomplete one: precision needs dispositions (LH-510) and a floor
    needs ratification (LH-501). The definitions are still worth committing,
    because they are what a Track B team compiles and what a backtest measures
    precision *for* once dispositions exist.

    The thresholds inside the evaluators are deliberately *structural* rather
    than tuned — "any missed payment", "utilisation above its own trailing
    median" — because a tuned threshold with no data to tune on is an invented
    number wearing a decimal point.
    """
    catalog = SignalCatalog(version="v1")

    catalog.register(
        SignalDefinition(
            signal_id="repayment.first_missed_emi",
            family=SignalFamily.REPAYMENT,
            version="1.0.0",
            description="First missed instalment after a clean run of >= 6 months",
            direction=Direction.HIGHER_IS_WORSE,
            evaluate=lambda f: f["missed_emis_last_month"] >= 1
            and f["clean_months_before"] >= 6,
            srs_ref="SRS §10.3 repayment",
        )
    )
    catalog.register(
        SignalDefinition(
            signal_id="repayment.partial_payment_pattern",
            family=SignalFamily.REPAYMENT,
            version="1.0.0",
            description="Two consecutive part-payments below the contractual EMI",
            direction=Direction.HIGHER_IS_WORSE,
            evaluate=lambda f: f["consecutive_partial_payments"] >= 2,
            srs_ref="SRS §10.3 repayment",
        )
    )
    catalog.register(
        SignalDefinition(
            signal_id="cash_flow.inflow_collapse",
            family=SignalFamily.CASH_FLOW,
            version="1.0.0",
            description="Monthly net inflow below half its trailing 6-month median",
            direction=Direction.LOWER_IS_WORSE,
            evaluate=lambda f: f["net_inflow"] < 0.5 * f["net_inflow_median_6m"],
            srs_ref="SRS §10.3 cash-flow",
        )
    )
    catalog.register(
        SignalDefinition(
            signal_id="cash_flow.balance_trend_negative",
            family=SignalFamily.CASH_FLOW,
            version="1.0.0",
            description="Closing-balance trend negative over 8 consecutive weeks",
            direction=Direction.LOWER_IS_WORSE,
            evaluate=lambda f: f["balance_trend_weeks_negative"] >= 8,
            srs_ref="SRS §10.3 cash-flow",
        )
    )
    catalog.register(
        SignalDefinition(
            signal_id="bureau.new_enquiry_burst",
            family=SignalFamily.BUREAU,
            version="1.0.0",
            description="Three or more credit enquiries in 30 days",
            direction=Direction.HIGHER_IS_WORSE,
            evaluate=lambda f: f["bureau_enquiries_30d"] >= 3,
            srs_ref="SRS §10.3 bureau",
        )
    )
    catalog.register(
        SignalDefinition(
            signal_id="bureau.external_delinquency",
            family=SignalFamily.BUREAU,
            version="1.0.0",
            description="Delinquency reported by another lender",
            direction=Direction.HIGHER_IS_WORSE,
            evaluate=lambda f: f["external_dpd_max"] > 0,
            srs_ref="SRS §10.3 bureau",
        )
    )
    catalog.register(
        SignalDefinition(
            signal_id="behavioral.utilisation_spike",
            family=SignalFamily.BEHAVIORAL,
            version="1.0.0",
            description="Revolving utilisation above its own trailing median",
            direction=Direction.HIGHER_IS_WORSE,
            evaluate=lambda f: f["utilisation"] > f["utilisation_median_6m"],
            srs_ref="SRS §10.3 behavioral",
        )
    )
    catalog.register(
        SignalDefinition(
            signal_id="macro_local.district_stress",
            family=SignalFamily.MACRO_LOCAL,
            version="1.0.0",
            description="District-level delinquency rate rising for 3 months",
            direction=Direction.HIGHER_IS_WORSE,
            evaluate=lambda f: f["district_delinquency_rising_months"] >= 3,
            srs_ref="SRS §10.3 macro/local",
        )
    )
    return catalog

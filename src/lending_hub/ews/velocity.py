"""PD-velocity trigger — deterioration, not level (WS-4.A Step 2).

Phase 4 §4 Step 2 states the mechanism and, unusually, its justification:

    From the P3 hazard model: Δ(30-day) hazard, expressed as a percentile of the
    portfolio distribution. Alert when Δ crosses the budget-derived percentile
    `[POLICY: Collections Head]`. **Velocity, not level, is the trigger** — a
    thin-file borrower can be permanently "medium risk"; deterioration is the
    signal.

That justification is worth taking seriously, because it inverts the instinct.
An early-warning system built on *level* re-alerts the same structurally-risky
accounts every month, which is both useless and the fastest known route to alert
fatigue: the officer learns that the queue is the same names, and stops reading
it. An account that has been at 4% hazard for two years is not news. An account
that moved from 1.1% to 2.4% in thirty days is, even though it is still the safer
of the two.

Why the trigger is a percentile and not a threshold
-----------------------------------------------------
The phase file says "expressed as a percentile of the portfolio distribution",
and the reason is capacity. A fixed Δ-hazard threshold produces an alert volume
that swings with the macro cycle — in a downturn every account deteriorates at
once and the queue explodes on the week the collections desk is least able to
absorb it. A percentile pins the *volume* and lets the severity float, which is
the correct way round when the constraint is human hours. It also means the
trigger is derived from the alert budget (LH-501) rather than from a view about
what Δ is dangerous.

The cost, which belongs on the model card: in a genuinely benign quarter the top
percentile is still alerted, so some alerts are on accounts nobody would worry
about. That is the price of a bounded queue and it is the right trade, but it
makes per-signal precision *look* worse in good times through no fault of the
signal.

What is measurable here and what is not
-----------------------------------------
Whether hazard deterioration precedes default, and by how many days, is a
question the Track P panel answers — real accounts, real defaults, real
preceding trajectories. That is measured in :mod:`lending_hub.ews.backtest`.

Whether an alert was *right* is a disposition (LH-510) and is not measured
anywhere in this repository.

What this does not port
-----------------------
No streaming. Velocity is computed from two survival curves the caller supplies;
Track B recomputes hazards on a schedule behind ``featurestore.ports``. There is
no smoothing of the velocity series either — a single-month Δ is noisy, and a
smoothed one is a different statistic that would need its own backtest rather
than inheriting this one's.

Workstream: WS-4.A Step 2 (SRS §10, §7.3.2)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping, Sequence

from lending_hub.definitions.provenance import Grounded, Pending, Source, Ungrounded

#: The portfolio percentile at which a PD-velocity move raises an alert.
#: `[POLICY: Collections Head]` — Phase 4 §4 Step 2 says the percentile is
#: *derived from the alert budget*, so it is the same ticket as the budget
#: itself (LH-501) rather than an independent number.
VELOCITY_ALERT_PERCENTILE = Pending(
    owner="Collections Head",
    ticket="LH-501",
    note="the budget-derived portfolio percentile at which PD velocity alerts",
)

#: The velocity window. `[SPEC]` — Phase 4 §4 Step 2 says "Δ(30-day) hazard".
VELOCITY_WINDOW_DAYS = Grounded(
    value=30, source=Source.SPEC, citation="Phase 4 §4 Step 2"
)

#: The horizon over which the PD being differenced is measured. `[SPEC]` — the
#: same 12-month behavioural window Appendix A fixes and P3's behavioural model
#: uses, imported from `portfolio.panel` rather than restated so that a change
#: to the outcome window moves the trigger with it.
from lending_hub.portfolio.panel import BEHAVIOURAL_HORIZON_MONTHS  # noqa: E402

#: Smallest portfolio a percentile may be computed from. Not from the phase
#: file. A percentile over 40 accounts is a rank, and the "95th percentile"
#: of 40 accounts is the second-worst one — which is a fixed *count* dressed as
#: a rate, and it stops behaving like a budget the moment the book grows.
#: Reported as a Phase 4 finding.
MIN_PORTFOLIO_FOR_PERCENTILE = 200


class VelocityError(Exception):
    """A velocity cannot be computed or ranked."""


@dataclass(frozen=True)
class PdReading:
    """One account's cumulative PD at one observation point.

    ``horizon_months`` travels with the value because a 12-month PD and a
    lifetime PD differ by more than any month-on-month move, and differencing
    two readings taken at different horizons produces a velocity that is
    entirely an artefact of the horizon change.
    """

    account_id: str
    as_of: date
    pd: float
    horizon_months: int = BEHAVIOURAL_HORIZON_MONTHS

    def __post_init__(self) -> None:
        if not 0.0 <= self.pd <= 1.0:
            raise VelocityError(
                f"{self.account_id}: PD {self.pd} is outside [0, 1]"
            )
        if self.horizon_months <= 0:
            raise VelocityError(f"{self.account_id}: horizon must be positive")


@dataclass(frozen=True)
class Velocity:
    """A change in PD between two readings of the same account.

    Both the absolute and the relative move are carried, because they answer
    different questions and the phase file does not say which one the percentile
    ranks. See :func:`portfolio_percentiles` for why the choice matters and is
    ticketed rather than made here.
    """

    account_id: str
    previous: PdReading
    current: PdReading
    days_between: int

    @property
    def absolute(self) -> float:
        """``PD_now - PD_then``. Positive means deterioration."""
        return self.current.pd - self.previous.pd

    @property
    def relative(self) -> float:
        """``(PD_now - PD_then) / PD_then``.

        Raises rather than returning infinity when the earlier PD was zero. A
        zero prior PD is not a well-behaved denominator, and an account moving
        from 0.000 to 0.004 would otherwise rank above every genuinely
        deteriorating account in the book.
        """
        if self.previous.pd <= 0:
            raise VelocityError(
                f"{self.account_id}: previous PD is {self.previous.pd}, so a "
                "relative velocity is undefined. An account moving off exactly "
                "zero would otherwise outrank every real deterioration in the "
                "portfolio."
            )
        return self.absolute / self.previous.pd

    @property
    def is_deterioration(self) -> bool:
        return self.absolute > 0


def velocity(
    previous: PdReading,
    current: PdReading,
    *,
    window_days: int | None = None,
    tolerance_days: int = 5,
) -> Velocity:
    """Δ-PD between two readings of one account.

    Refuses to difference readings taken at different horizons, or readings
    whose spacing is not the specified window. Both refusals prevent the same
    class of error: a velocity that is an artefact of *how it was measured*
    rather than of anything the account did.
    """
    window = window_days if window_days is not None else VELOCITY_WINDOW_DAYS.value

    if previous.account_id != current.account_id:
        raise VelocityError(
            f"cannot difference {previous.account_id} against {current.account_id}"
        )
    if previous.horizon_months != current.horizon_months:
        raise VelocityError(
            f"{current.account_id}: readings are at {previous.horizon_months}m and "
            f"{current.horizon_months}m horizons. Differencing them produces a "
            "velocity that is entirely an artefact of the horizon change."
        )
    if current.as_of <= previous.as_of:
        raise VelocityError(
            f"{current.account_id}: current reading {current.as_of} does not "
            f"follow previous {previous.as_of}"
        )

    days = (current.as_of - previous.as_of).days
    if abs(days - window) > tolerance_days:
        raise VelocityError(
            f"{current.account_id}: readings are {days} days apart, outside the "
            f"{window}-day window (±{tolerance_days}). A Δ over a longer gap is "
            "a larger number for the same rate of deterioration, so mixing "
            "spacings makes the portfolio percentile rank the calendar."
        )

    return Velocity(
        account_id=current.account_id,
        previous=previous,
        current=current,
        days_between=days,
    )


@dataclass(frozen=True)
class PortfolioRanking:
    """Velocities ranked into portfolio percentiles.

    The percentile is the trigger quantity (Phase 4 §4 Step 2), so this is the
    object the alert decision reads.
    """

    percentiles: Mapping[str, float]
    """account_id -> percentile in [0, 1]; 1.0 is the fastest deterioration."""

    basis: str
    n: int

    def percentile_for(self, account_id: str) -> float:
        try:
            return self.percentiles[account_id]
        except KeyError as exc:
            raise VelocityError(
                f"{account_id} is not in this ranking. An account ranked against "
                "a portfolio it was not measured in has no percentile."
            ) from exc

    def alerts(self, *, threshold_percentile: float) -> tuple[str, ...]:
        """Accounts at or above the trigger percentile.

        ``threshold_percentile`` has no default. Phase 4 §4 Step 2 derives it
        from the alert budget (LH-501), and a default here would be an invented
        alert volume — the exact quantity the budget exists to control.
        """
        if not 0.0 < threshold_percentile < 1.0:
            raise VelocityError(
                f"threshold percentile {threshold_percentile} must be in (0, 1)"
            )
        return tuple(
            sorted(
                (a for a, p in self.percentiles.items() if p >= threshold_percentile),
                key=lambda a: -self.percentiles[a],
            )
        )

    def expected_alert_count(self, *, threshold_percentile: float) -> int:
        """How many alerts this threshold produces on this portfolio.

        The number a Collections Head actually needs to set LH-501: a percentile
        is not interpretable as a workload until it is multiplied by a book.
        """
        return len(self.alerts(threshold_percentile=threshold_percentile))


def portfolio_percentiles(
    velocities: Sequence[Velocity],
    *,
    basis: str = "absolute",
    min_portfolio: int = MIN_PORTFOLIO_FOR_PERCENTILE,
) -> PortfolioRanking:
    """Rank velocities into portfolio percentiles.

    ``basis`` selects absolute or relative Δ. **Phase 4 §4 Step 2 does not say
    which**, and the two rank differently in a way that decides who gets
    alerted: absolute Δ concentrates alerts on already-risky accounts, because a
    move from 8% to 10% is two points and a move from 0.4% to 1.2% is under one;
    relative Δ does the opposite and surfaces the early deterioration the
    workstream is named for, while being unstable at small PDs. The default here
    is absolute because it is the reading of "Δ(30-day) hazard" that needs no
    additional assumption, and the choice is raised as a Phase 4 finding rather
    than settled.

    Ties share the lower percentile, which matters more than it sounds: a book
    with many identical zero velocities would otherwise have its unchanged
    accounts spread across the whole lower range.
    """
    if basis not in ("absolute", "relative"):
        raise VelocityError(f"basis must be 'absolute' or 'relative', got {basis!r}")
    if len(velocities) < min_portfolio:
        raise VelocityError(
            f"{len(velocities)} accounts is below the {min_portfolio} needed for "
            "a portfolio percentile. Below that a percentile is a rank: the "
            "'95th percentile' of 40 accounts is the second-worst one, which is "
            "a fixed count dressed as a rate and stops behaving like a budget "
            "as soon as the book grows."
        )

    values = {
        v.account_id: (v.absolute if basis == "absolute" else v.relative)
        for v in velocities
    }
    ordered = sorted(values.values())
    n = len(ordered)

    percentiles = {}
    for account_id, value in values.items():
        # Share of the portfolio strictly below this value: ties take the lower
        # percentile together rather than being split by dictionary order.
        below = sum(1 for v in ordered if v < value)
        percentiles[account_id] = below / n

    return PortfolioRanking(percentiles=percentiles, basis=basis, n=n)


def trigger(ranking: PortfolioRanking) -> tuple[str, ...]:
    """Apply the ratified velocity trigger.

    Raises :class:`Ungrounded` until LH-501 supplies the percentile. The
    alternative — defaulting to, say, the 95th — sets the bank's alert volume
    from a round number, and Phase 4 §4 Step 5's fatigue guardrails exist
    precisely because that volume is the thing that breaks the system.
    """
    try:
        threshold = VELOCITY_ALERT_PERCENTILE.value
    except Ungrounded as exc:
        raise Ungrounded(
            f"the PD-velocity trigger percentile is not ratified "
            f"({VELOCITY_ALERT_PERCENTILE}). Phase 4 §4 Step 2 derives it from "
            "the alert budget, so choosing it here would set the collections "
            "desk's workload from a round number — and alert volume is exactly "
            "what the §4 Step 5 fatigue guardrails exist to protect."
        ) from exc
    return ranking.alerts(threshold_percentile=threshold)  # pragma: no cover

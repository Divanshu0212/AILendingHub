"""EWS backtest — capture rate at lead, and per-tier precision (WS-4.A Step 6).

Phase 4 §4 Step 6:

    Replay 24 months of history: capture rate of eventual 90+ defaulters at
    >= 60-day lead; precision per tier; lead-time distribution. Targets
    `[SPEC — revisit at gate with measured numbers]`: capture >= 55% at
    >= 60-day lead; tier-Red precision >= 25%.

The two halves of this backtest are not equally measurable
------------------------------------------------------------
**Capture rate is measurable here.** It asks: of the accounts that eventually
defaulted, on how many did we raise an alert at least 60 days beforehand? Both
sides come from the panel — the default date is Appendix A applied to observed
DPD, and the alert date is when the detector would have fired on
point-in-time features. No human judgement enters. This is what
:func:`capture_rate` computes and what the Track P run measures on the Fannie
panel.

**Precision is not measurable at all.** It asks: of the alerts raised, how many
were *right*? "Right" is a confirmed-relevant disposition — a collections
officer's judgement — and there is no desk (LH-510). :func:`tier_precision`
therefore takes dispositions as a required argument and refuses an empty set
rather than substituting the default outcome for them.

The substitution is tempting and wrong, so it is worth naming: using "did this
account later default?" as a proxy for "was this alert correct?" **penalises the
system for working.** An alert that correctly identified distress, which the
bank then successfully cured, becomes a false positive under that proxy — so the
better the collections operation, the worse its EWS scores. That is the same
class of error as Phase 3's in-sample comparison (P3-F14): a metric that
measures the opposite of what it is named for.

Lead time is the whole product
--------------------------------
Phase 4 §1 promises flags "30-120 days ahead". An alert that fires the day
before a missed payment is not an early warning, it is a notification of
something already happening, and it has no operational value — there is nothing
an officer can do in a day that they could not do at the moment of the miss. So
this module reports the *lead-time distribution*, not just a mean: a system with
a 70-day mean lead composed of half at 130 days and half at 10 is a different
system from one where every alert lands at 70.

What this does not port
-----------------------
No replay harness for the detectors themselves. This module scores an
already-produced sequence of alerts against observed defaults; the alerts come
from ``ews.experiment`` running the detectors over point-in-time panel rows.
Keeping the two apart is what stops the scorer from quietly acquiring knowledge
of the outcome it is scoring.

Workstream: WS-4.A Step 6 (SRS §10)
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Mapping, Sequence

from lending_hub.definitions.provenance import Grounded, Source
from lending_hub.ews.routing import Disposition, Tier

#: Minimum lead, in days, for an alert to count as an early warning.
#: `[SPEC]` — Phase 4 §4 Step 6.
REQUIRED_LEAD_DAYS = Grounded(
    value=60, source=Source.SPEC, citation="Phase 4 §4 Step 6"
)

#: Share of eventual defaulters that must be captured at the required lead.
#: `[SPEC]` — Phase 4 §4 Step 6, marked "revisit at gate with measured numbers",
#: which makes it a target rather than a ratified floor. Recorded as SPEC
#: because the phase file states it; the caveat travels with it.
CAPTURE_TARGET = Grounded(
    value=0.55,
    source=Source.SPEC,
    citation="Phase 4 §4 Step 6 (marked: revisit at gate with measured numbers)",
)

#: Tier-Red precision target. `[SPEC]`, same caveat.
RED_PRECISION_TARGET = Grounded(
    value=0.25,
    source=Source.SPEC,
    citation="Phase 4 §4 Step 6 (marked: revisit at gate with measured numbers)",
)

#: Months of history the replay must cover. `[SPEC]` — Phase 4 §4 Step 6.
REPLAY_MONTHS = Grounded(
    value=24, source=Source.SPEC, citation="Phase 4 §4 Step 6"
)


class BacktestError(Exception):
    """The backtest cannot be run or its result cannot be interpreted."""


@dataclass(frozen=True)
class ReplayAlert:
    """One alert as it would have been raised during replay.

    ``raised_on`` must be a point-in-time decision: computed from features
    available on that date and nothing later. This module cannot verify that —
    it receives alerts already produced — so the obligation sits with the
    replay harness, and :func:`assert_no_hindsight` checks the one violation
    that is detectable from the outside.
    """

    account_id: str
    raised_on: date
    tier: Tier
    signal_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.tier is Tier.NONE:
            raise BacktestError(
                f"{self.account_id}: a tier-NONE alert was never raised, so it "
                "cannot appear in a replay. Including them inflates the "
                "denominator of every precision figure."
            )


@dataclass(frozen=True)
class ObservedDefault:
    """An account that reached Appendix A default, and when.

    ``defaulted_on`` is the month-end at which the definition was first
    satisfied — not the month the account was written off, and not the month it
    was closed. Using a later date inflates every lead time by the difference.
    """

    account_id: str
    defaulted_on: date


@dataclass(frozen=True)
class CaptureResult:
    """Criterion 1: were eventual defaulters flagged early enough?"""

    defaulters: int
    captured: int
    captured_too_late: int
    never_alerted: int
    lead_days: tuple[int, ...]
    required_lead_days: int

    @property
    def capture_rate(self) -> float:
        if self.defaulters == 0:
            raise BacktestError(
                "no defaulters in the replay window; a capture rate over zero "
                "events is unmeasured, not 1.0 and not 0.0"
            )
        return self.captured / self.defaulters

    @property
    def median_lead_days(self) -> float | None:
        return statistics.median(self.lead_days) if self.lead_days else None

    @property
    def lead_percentiles(self) -> dict[str, int]:
        """The distribution, not just the centre.

        A 70-day mean lead made of half at 130 and half at 10 days is a
        different system from one where every alert lands at 70, and only the
        second is what Phase 4 §1's "30-120 days ahead" promises.
        """
        if not self.lead_days:
            return {}
        ordered = sorted(self.lead_days)
        return {
            "p10": _nearest_rank(ordered, 0.10),
            "p25": _nearest_rank(ordered, 0.25),
            "p50": _nearest_rank(ordered, 0.50),
            "p75": _nearest_rank(ordered, 0.75),
            "p90": _nearest_rank(ordered, 0.90),
        }

    @property
    def meets_target(self) -> bool:
        return self.defaulters > 0 and self.capture_rate >= CAPTURE_TARGET.value

    @property
    def why_not(self) -> str:
        if self.defaulters == 0:
            return "no defaulters in the replay window"
        if self.meets_target:
            return ""
        return (
            f"capture {self.capture_rate:.3f} at >= {self.required_lead_days} days "
            f"is below the {CAPTURE_TARGET.value:.2f} target "
            f"({self.captured_too_late} alerted too late, "
            f"{self.never_alerted} never alerted)"
        )


def _nearest_rank(ordered: Sequence[int], q: float) -> int:
    index = max(0, min(len(ordered) - 1, int(-(-q * len(ordered) // 1)) - 1))
    return ordered[index]


def capture_rate(
    alerts: Sequence[ReplayAlert],
    defaults: Sequence[ObservedDefault],
    *,
    required_lead_days: int | None = None,
    tiers: tuple[Tier, ...] = (Tier.AMBER, Tier.RED),
) -> CaptureResult:
    """Criterion 1: of eventual defaulters, how many were flagged in time?

    An account counts as captured if **any** qualifying alert preceded its
    default by at least the required lead. The earliest such alert supplies the
    lead time — using the latest would report the system as barely making its
    own deadline when it in fact warned months earlier.

    ``tiers`` restricts which alerts count. Defaults to both, because Phase 4
    §4 Step 6 asks for the capture rate of the *system*; passing ``(Tier.RED,)``
    answers the different and also useful question of how much Red alone
    catches.
    """
    lead = required_lead_days if required_lead_days is not None else REQUIRED_LEAD_DAYS.value
    if lead < 0:
        raise BacktestError(f"required lead must be non-negative, got {lead}")

    qualifying = [a for a in alerts if a.tier in tiers]
    by_account: dict[str, list[ReplayAlert]] = {}
    for alert in qualifying:
        by_account.setdefault(alert.account_id, []).append(alert)

    captured = 0
    too_late = 0
    never = 0
    leads: list[int] = []

    for default in defaults:
        account_alerts = by_account.get(default.account_id, [])
        if not account_alerts:
            never += 1
            continue

        in_time = [
            a
            for a in account_alerts
            if (default.defaulted_on - a.raised_on).days >= lead
        ]
        if in_time:
            captured += 1
            earliest = min(in_time, key=lambda a: a.raised_on)
            leads.append((default.defaulted_on - earliest.raised_on).days)
        else:
            too_late += 1

    return CaptureResult(
        defaulters=len(defaults),
        captured=captured,
        captured_too_late=too_late,
        never_alerted=never,
        lead_days=tuple(leads),
        required_lead_days=lead,
    )


@dataclass(frozen=True)
class TierPrecision:
    """Criterion 2: of the alerts raised at a tier, how many were right?

    Not computable without dispositions. This class exists to hold the result
    when they arrive and to make the absence explicit until then.
    """

    tier: Tier
    alerts: int
    confirmed_relevant: int

    @property
    def precision(self) -> float:
        if self.alerts == 0:
            raise BacktestError(
                f"no {self.tier.name} alerts disposed; precision over zero "
                "alerts is unmeasured"
            )
        return self.confirmed_relevant / self.alerts

    @property
    def meets_target(self) -> bool:
        if self.tier is not Tier.RED:
            return True
        return self.alerts > 0 and self.precision >= RED_PRECISION_TARGET.value


def tier_precision(
    alerts: Sequence[ReplayAlert],
    dispositions: Mapping[str, Disposition],
    *,
    tier: Tier,
) -> TierPrecision:
    """Per-tier precision from **dispositions**, never from default outcomes.

    ``dispositions`` maps account id to the officer's judgement. It is required
    and an empty mapping raises, because the available substitute — scoring
    against whether the account later defaulted — measures the opposite of what
    it is named for: an alert that found real distress the bank then cured
    becomes a false positive, so a better collections operation scores a worse
    EWS.
    """
    if not dispositions:
        raise BacktestError(
            "no dispositions supplied, so no precision can be computed "
            "(LH-510). Do not substitute the default outcome: an alert that "
            "correctly identified distress the bank then cured would count as a "
            "false positive, which penalises the system for working and makes a "
            "better collections operation look like a worse EWS."
        )

    at_tier = [a for a in alerts if a.tier is tier]
    disposed = [
        dispositions[a.account_id] for a in at_tier if a.account_id in dispositions
    ]
    return TierPrecision(
        tier=tier,
        alerts=len(disposed),
        confirmed_relevant=sum(1 for d in disposed if d.confirmed_relevant),
    )


def assert_no_hindsight(
    alerts: Sequence[ReplayAlert], defaults: Sequence[ObservedDefault]
) -> None:
    """Refuse alerts raised on or after the default they claim to predict.

    The one point-in-time violation detectable from outside the replay harness,
    and the one that most flatters a backtest: an alert raised on the default
    month captures 100% of defaulters at zero lead. It would pass a capture
    criterion that did not check the lead, which is why the lead requirement is
    load-bearing rather than a refinement.
    """
    default_dates = {d.account_id: d.defaulted_on for d in defaults}
    offenders = [
        a
        for a in alerts
        if a.account_id in default_dates and a.raised_on >= default_dates[a.account_id]
    ]
    if offenders:
        worst = min(offenders, key=lambda a: (default_dates[a.account_id] - a.raised_on).days)
        raise BacktestError(
            f"{len(offenders)} alert(s) were raised on or after the default they "
            f"claim to predict — worst: {worst.account_id} alerted "
            f"{worst.raised_on} against a default on "
            f"{default_dates[worst.account_id]}. An alert raised on the default "
            "month captures every defaulter at zero lead."
        )


@dataclass(frozen=True)
class BacktestReport:
    """The Phase 4 §4 Step 6 pack, with the two halves labelled honestly."""

    capture: CaptureResult
    red_precision: TierPrecision | None
    amber_precision: TierPrecision | None
    months_replayed: int
    accounts: int
    track: str

    @property
    def spans_required_history(self) -> bool:
        return self.months_replayed >= REPLAY_MONTHS.value

    @property
    def meets_targets(self) -> tuple[bool, str]:
        reasons = []
        if not self.spans_required_history:
            reasons.append(
                f"replay covers {self.months_replayed} months, below the "
                f"{REPLAY_MONTHS.value} the phase file requires"
            )
        if not self.capture.meets_target:
            reasons.append(self.capture.why_not)
        if self.red_precision is None:
            reasons.append(
                "tier-Red precision is not measured: it needs collections "
                "dispositions, which do not exist on any track here (LH-510)"
            )
        elif not self.red_precision.meets_target:
            reasons.append(
                f"Red precision {self.red_precision.precision:.3f} is below the "
                f"{RED_PRECISION_TARGET.value:.2f} target"
            )
        return (not reasons), "; ".join(reasons)

    def to_dict(self) -> dict:
        passed, why_not = self.meets_targets
        return {
            "track": self.track,
            "accounts": self.accounts,
            "months_replayed": self.months_replayed,
            "spans_required_history": self.spans_required_history,
            "capture": {
                "defaulters": self.capture.defaulters,
                "captured": self.capture.captured,
                "capture_rate": (
                    self.capture.capture_rate if self.capture.defaulters else None
                ),
                "required_lead_days": self.capture.required_lead_days,
                "median_lead_days": self.capture.median_lead_days,
                "lead_percentiles": self.capture.lead_percentiles,
                "captured_too_late": self.capture.captured_too_late,
                "never_alerted": self.capture.never_alerted,
                "target": CAPTURE_TARGET.value,
                "meets_target": self.capture.meets_target,
            },
            "red_precision": (
                {
                    "alerts": self.red_precision.alerts,
                    "precision": self.red_precision.precision,
                    "target": RED_PRECISION_TARGET.value,
                }
                if self.red_precision is not None
                else {
                    "state": "not measurable",
                    "reason": "collections dispositions do not exist (LH-510)",
                }
            ),
            "passed": passed,
            "why_not": why_not,
        }

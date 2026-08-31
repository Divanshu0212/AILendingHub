"""Shadow and canary comparison — the Phase 1 §5 shipping-ladder evidence.

Phase 1 §5.1: "Shadow (≥ 4 weeks). Both scoring models + fraud stack score 100% of
live applications; legacy policy still decides. Daily automated comparison: score
PSI vs training, champion-vs-challenger swap sets, fraud alert volumes."

What makes a shadow run evidence rather than reassurance
--------------------------------------------------------
A shadow model that agrees with the incumbent everywhere has demonstrated
nothing except that it was fitted on the same data. The comparison that matters
is where they *disagree*, on which applicants, and whether the disagreements are
concentrated. So this module reports the disagreement structure first and the
aggregate agreement rate last — the opposite of how a shadow dashboard usually
reads, and the opposite of how it usually gets summarised into a gate pack.

Three things it refuses to do
-----------------------------
* It will not call a shadow period complete before Master §3.2's four weeks,
  counted in elapsed days rather than in "we have enough data now".
* It will not report a canary result without saying what fraction of traffic
  produced it. A 0.5% canary that looks clean is a statement about ~0.5% of
  applicants, and the sample size is the first thing that gets dropped when the
  number is repeated.
* It will not compute a pass/fail. The thresholds are `[POLICY]` — the alert
  budget (LH-206), the fairness bar (LH-205), the cutoffs (LH-204).

Workstream: Phase 1 §5 · Master §3.2 · SRS §4.3.4
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Sequence

from lending_hub.scoring.features import ScreenVerdict, screen_psi
from lending_hub.scoring.validation import SwapSetAnalysis, score_psi, swap_sets

#: Master §3.2 [SPEC]: "shadow >= 4 weeks". Elapsed calendar time, because the
#: purpose is to see the model across a month of real operating conditions —
#: month-end, salary cycles, a bank holiday — not to accumulate a row count.
MINIMUM_SHADOW = timedelta(weeks=4)

#: Phase 1 §5.3 [SPEC]: "Full traffic after >= 4 clean canary weeks."
MINIMUM_CANARY = timedelta(weeks=4)


class ShadowError(Exception):
    """The comparison cannot be made as requested."""


@dataclass
class DailyComparison:
    """One day of the Phase 1 §5.1 automated comparison."""

    day: date
    scored: int
    score_psi_vs_training: float
    swap_set: SwapSetAnalysis
    fraud_alerts: int
    fraud_alert_rate: float
    degraded_decisions: int = 0

    @property
    def psi_verdict(self) -> ScreenVerdict:
        return screen_psi(self.score_psi_vs_training)[0]

    @property
    def disagreement_rate(self) -> float | None:
        total = (
            self.swap_set.both_approve
            + self.swap_set.both_decline
            + self.swap_set.swap_in
            + self.swap_set.swap_out
        )
        if total == 0:
            return None
        return (self.swap_set.swap_in + self.swap_set.swap_out) / total

    def to_dict(self) -> dict:
        return {
            "day": self.day.isoformat(),
            "scored": self.scored,
            # Disagreement first: a shadow model that agrees everywhere has shown
            # only that it was fitted on the same data.
            "disagreement_rate": self.disagreement_rate,
            "swap_set": self.swap_set.to_dict(),
            "score_psi_vs_training": self.score_psi_vs_training,
            "psi_verdict": self.psi_verdict.value,
            "fraud_alerts": self.fraud_alerts,
            "fraud_alert_rate": self.fraud_alert_rate,
            "degraded_decisions": self.degraded_decisions,
        }


def compare_day(
    day: date,
    *,
    training_scores: Sequence[float],
    live_scores: Sequence[float],
    champion_approves: Sequence[int],
    challenger_approves: Sequence[int],
    labels: Sequence[int],
    segments: Sequence[str] | None = None,
    fraud_alerts: int = 0,
    degraded_decisions: int = 0,
) -> DailyComparison:
    """Assemble one day's comparison.

    ``labels`` are the outcomes known *so far*. During shadow most are unknown,
    which is why the swap-set bad rates are reported alongside their counts and
    never on their own: a swap-out bad rate computed on three matured loans is a
    number, not evidence.
    """
    if not live_scores:
        raise ShadowError("a comparison day with no scored applications is not a day")

    return DailyComparison(
        day=day,
        scored=len(live_scores),
        score_psi_vs_training=score_psi(training_scores, live_scores),
        swap_set=swap_sets(champion_approves, challenger_approves, labels, segments),
        fraud_alerts=fraud_alerts,
        fraud_alert_rate=fraud_alerts / len(live_scores),
        degraded_decisions=degraded_decisions,
    )


@dataclass
class LadderStatus:
    """Where a model stands on the Master §3.2 ladder, and why."""

    stage: str
    started_at: date | None
    as_of: date
    days_elapsed: int
    minimum_days: int
    traffic_fraction: float | None = None
    blocking: list[str] = field(default_factory=list)

    @property
    def duration_met(self) -> bool:
        return self.days_elapsed >= self.minimum_days

    @property
    def may_advance(self) -> bool:
        return self.duration_met and not self.blocking

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "as_of": self.as_of.isoformat(),
            "days_elapsed": self.days_elapsed,
            "minimum_days": self.minimum_days,
            "duration_met": self.duration_met,
            "traffic_fraction": self.traffic_fraction,
            "may_advance": self.may_advance,
            "blocking": self.blocking,
        }


def shadow_status(
    started_at: date | None, as_of: date, *, blocking: Sequence[str] = ()
) -> LadderStatus:
    """Master §3.2: shadow runs at least four weeks of elapsed time."""
    elapsed = (as_of - started_at).days if started_at else 0
    reasons = list(blocking)
    if started_at is None:
        reasons.append("shadow has not started")
    return LadderStatus(
        stage="shadow",
        started_at=started_at,
        as_of=as_of,
        days_elapsed=elapsed,
        minimum_days=MINIMUM_SHADOW.days,
        traffic_fraction=1.0,
        blocking=reasons,
    )


def canary_status(
    started_at: date | None,
    as_of: date,
    *,
    traffic_fraction: float | None,
    clean_days: int,
    blocking: Sequence[str] = (),
) -> LadderStatus:
    """Phase 1 §5.3: full traffic after four *clean* canary weeks.

    "Clean" is counted separately from elapsed, because a canary interrupted by
    an incident and restarted has not accumulated four clean weeks however long
    it has been running — and the elapsed figure is the one that gets quoted.
    """
    elapsed = (as_of - started_at).days if started_at else 0
    reasons = list(blocking)
    if started_at is None:
        reasons.append("canary has not started")
    if traffic_fraction is None:
        reasons.append(
            "canary traffic percentage is [POLICY: Credit Risk Committee] (LH-204) "
            "and is not configured"
        )
    if clean_days < MINIMUM_CANARY.days:
        reasons.append(
            f"{clean_days} clean canary days of {MINIMUM_CANARY.days} required "
            "(Phase 1 §5.3)"
        )
    return LadderStatus(
        stage="canary",
        started_at=started_at,
        as_of=as_of,
        days_elapsed=elapsed,
        minimum_days=MINIMUM_CANARY.days,
        traffic_fraction=traffic_fraction,
        blocking=reasons,
    )


@dataclass
class ShadowReport:
    """The Phase 1 §6 deliverable: the shadow/canary comparison pack."""

    model: str
    days: list[DailyComparison]
    status: LadderStatus

    @property
    def mean_disagreement(self) -> float | None:
        rates = [d.disagreement_rate for d in self.days if d.disagreement_rate is not None]
        return sum(rates) / len(rates) if rates else None

    @property
    def psi_breaches(self) -> list[date]:
        return [d.day for d in self.days if d.psi_verdict is not ScreenVerdict.PASS]

    @property
    def total_scored(self) -> int:
        return sum(d.scored for d in self.days)

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "days_observed": len(self.days),
            "total_scored": self.total_scored,
            "mean_disagreement_rate": self.mean_disagreement,
            "psi_breach_days": [day.isoformat() for day in self.psi_breaches],
            "ladder": self.status.to_dict(),
            "daily": [d.to_dict() for d in self.days],
            "verdict": (
                "not computed here: the pass/fail thresholds are [POLICY] — alert "
                "budget (LH-206), fairness bar (LH-205), cutoffs (LH-204)"
            ),
        }

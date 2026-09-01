"""WS-2.4 — backtest before any live use.

Phase 2 §4 states three tests over >= 3 historical seasons, everything computed
as of historical decision dates with point-in-time imagery only:

    (a) LandQualityIndex quartiles order historical agri NPA rates monotonically
    (b) adding agri features to the P1 architecture yields >= +4 Gini `[SPEC]`
    (c) the non-sowing flag would have fired on >= 60% of season-linked defaults
        with >= 45 days lead

and one instruction that is the most important sentence in the workstream:

    A failed test triggers feature redesign — never threshold relaxation.

That sentence is why every threshold here is a module constant read from the
phase file rather than a parameter with a default. :func:`run_backtest` takes
no thresholds at all.

Point-in-time is the whole test
--------------------------------
"Computing everything as-of historical decision dates (point-in-time imagery
only)" is not a caveat on the backtest, it is the backtest. The leak is
structural and it is easy: imagery for a season is published days to weeks after
acquisition, and a backtest that joins on acquisition date uses scenes that had
not been published when the decision was made. :func:`assert_point_in_time`
checks the property directly against publication timestamps rather than
asserting it in a docstring — the same approach ``portfolio.behavioural`` takes,
for the same reason.

Why (c) is the hardest of the three
------------------------------------
(a) and (b) are ordinary retrospective evaluations. (c) is a claim about *lead
time*, which needs the default date, the season it was linked to, and the date
the flag would have fired — and "season-linked default" is not defined anywhere.
Appendix A defines default; nothing defines which season a default belongs to
when a farmer holds a Kharif and a Rabi loan and defaults in March. That is
raised as a finding (LH-412) and :func:`non_sowing_backtest` requires the
linkage as an input rather than inferring it.

What this does not port
-----------------------
No P1 model refit — criterion (b) compares two Gini figures the caller supplies
from a real refit, because refitting the P1 architecture is `scoring`'s job and
duplicating it here would produce a second reference implementation (Master §2
rule 2).

Workstream: WS-2.4 (SRS §3.6, §11.3)
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date
from typing import Mapping, Sequence

from lending_hub.definitions.provenance import Grounded, Pending, Source

#: Minimum historical seasons the backtest must span. `[SPEC]` — Phase 2 §4
#: WS-2.4: "On >= 3 historical seasons".
MIN_BACKTEST_SEASONS = Grounded(
    value=3, source=Source.SPEC, citation="Phase 2 §4 WS-2.4"
)

#: Gini uplift the agri features must add to the P1 architecture. `[SPEC]` —
#: Phase 2 §4 WS-2.4(b), marked `[SPEC]` in the phase file itself.
GINI_UPLIFT_POINTS = Grounded(
    value=4.0, source=Source.SPEC, citation="Phase 2 §4 WS-2.4(b)"
)

#: Share of season-linked defaults the non-sowing flag must have fired on.
#: `[SPEC]` — Phase 2 §4 WS-2.4(c).
NON_SOWING_RECALL = Grounded(
    value=0.60, source=Source.SPEC, citation="Phase 2 §4 WS-2.4(c)"
)

#: Minimum lead time for a non-sowing flag to count. `[SPEC]` — Phase 2 §4
#: WS-2.4(c): ">= 45 days".
NON_SOWING_LEAD_DAYS = Grounded(
    value=45, source=Source.SPEC, citation="Phase 2 §4 WS-2.4(c)"
)

#: How a default is attributed to a crop season. Found by building (LH-412):
#: Appendix A defines default, and nothing defines which season a default
#: belongs to for a farmer holding both a Kharif and a Rabi loan.
SEASON_LINKAGE_RULE = Pending(
    owner="Agri Credit Head + Credit Policy",
    ticket="LH-412",
    note="the rule attributing a default to a crop season",
)


class BacktestError(Exception):
    """A backtest cannot be run or its result cannot be interpreted."""


class PointInTimeViolation(BacktestError):
    """A feature used data published after the decision it informed.

    Its own type because it invalidates a result rather than degrading it, and
    because the correct response is never to widen a tolerance.
    """


# ---------------------------------------------------------------------------
# Point-in-time
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FeatureUse:
    """One feature value, the decision it informed, and its provenance dates."""

    decision_id: str
    feature: str
    decision_date: date
    observation_date: date
    published_date: date

    def __post_init__(self) -> None:
        if self.published_date < self.observation_date:
            raise BacktestError(
                f"{self.decision_id}/{self.feature}: published "
                f"{self.published_date} before observed {self.observation_date}"
            )


def assert_point_in_time(uses: Sequence[FeatureUse]) -> None:
    """Prove no feature used data unavailable at its decision date.

    Checks the **publication** date, not the observation date. That is the
    distinction the whole check exists for: Sentinel-2 L2A publishes hours to
    days after acquisition and reanalysis weather publishes weeks after, so a
    backtest joining on acquisition date uses scenes nobody could have seen.
    The result looks *better* than the live system could ever be, which is what
    an unnoticed leak looks like.
    """
    violations = [u for u in uses if u.published_date > u.decision_date]
    if violations:
        worst = max(violations, key=lambda u: (u.published_date - u.decision_date).days)
        raise PointInTimeViolation(
            f"{len(violations)} of {len(uses)} feature uses read data published "
            f"after the decision they informed. Worst: {worst.feature} for "
            f"{worst.decision_id}, published {worst.published_date} against a "
            f"decision on {worst.decision_date} — "
            f"{(worst.published_date - worst.decision_date).days} days of "
            "hindsight. Join on publication date, not acquisition date."
        )


# ---------------------------------------------------------------------------
# (a) LandQualityIndex quartiles order NPA monotonically
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QuartileRate:
    quartile: int
    n: int
    defaults: int

    @property
    def npa_rate(self) -> float:
        if self.n == 0:
            raise BacktestError(f"quartile {self.quartile} is empty")
        return self.defaults / self.n


@dataclass(frozen=True)
class MonotonicityResult:
    """Criterion (a): do LQI quartiles order NPA rates monotonically?"""

    quartiles: tuple[QuartileRate, ...]
    seasons: int

    @property
    def rates(self) -> tuple[float, ...]:
        return tuple(q.npa_rate for q in self.quartiles)

    @property
    def is_monotonic(self) -> bool:
        """Non-increasing NPA as land quality rises.

        Non-increasing rather than strictly decreasing: two adjacent quartiles
        with identical rates is not a failure of ordering, and demanding
        strictness would fail a correct feature on a small sample.
        """
        rates = self.rates
        return all(a >= b for a, b in zip(rates, rates[1:]))

    @property
    def spread(self) -> float:
        """Q1 NPA minus Q4 NPA — how much ordering there is to be monotone.

        Reported because monotonicity alone is a weak claim: four quartiles at
        4.1%, 4.0%, 4.0% and 3.9% are perfectly monotone and useless.
        """
        rates = self.rates
        return rates[0] - rates[-1]

    @property
    def passed(self) -> bool:
        return self.is_monotonic and self.seasons >= MIN_BACKTEST_SEASONS.value

    @property
    def why_not(self) -> str:
        reasons = []
        if self.seasons < MIN_BACKTEST_SEASONS.value:
            reasons.append(
                f"spans {self.seasons} seasons, below the "
                f"{MIN_BACKTEST_SEASONS.value} the phase file requires"
            )
        if not self.is_monotonic:
            rates = ", ".join(f"{r:.4f}" for r in self.rates)
            reasons.append(f"NPA rates are not monotone across quartiles ({rates})")
        return "; ".join(reasons)


def quartile_monotonicity(
    scores: Sequence[float], defaults: Sequence[int], seasons: int
) -> MonotonicityResult:
    """Criterion (a). ``scores`` is LandQualityIndex; higher should mean safer."""
    if len(scores) != len(defaults):
        raise BacktestError(f"{len(scores)} scores against {len(defaults)} outcomes")
    if len(scores) < 4:
        raise BacktestError("cannot form quartiles from fewer than 4 accounts")
    if any(d not in (0, 1) for d in defaults):
        raise BacktestError("outcomes must be 0/1")

    order = sorted(range(len(scores)), key=lambda i: scores[i])
    size = len(order) // 4
    quartiles = []
    for q in range(4):
        start = q * size
        end = (q + 1) * size if q < 3 else len(order)
        members = order[start:end]
        quartiles.append(
            QuartileRate(
                quartile=q + 1,
                n=len(members),
                defaults=sum(defaults[i] for i in members),
            )
        )
    return MonotonicityResult(quartiles=tuple(quartiles), seasons=seasons)


# ---------------------------------------------------------------------------
# (b) +4 Gini from the agri features
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UpliftResult:
    """Criterion (b): does adding agri features buy >= 4 Gini points?"""

    baseline_gini: float
    with_agri_gini: float
    seasons: int
    out_of_time: bool

    @property
    def uplift_points(self) -> float:
        return (self.with_agri_gini - self.baseline_gini) * 100.0

    @property
    def passed(self) -> bool:
        return (
            self.uplift_points >= GINI_UPLIFT_POINTS.value
            and self.seasons >= MIN_BACKTEST_SEASONS.value
            and self.out_of_time
        )

    @property
    def why_not(self) -> str:
        reasons = []
        if not self.out_of_time:
            reasons.append(
                "the comparison is in-sample; a richer feature set always wins "
                "in-sample, which measures capacity rather than skill"
            )
        if self.seasons < MIN_BACKTEST_SEASONS.value:
            reasons.append(f"spans {self.seasons} seasons, below {MIN_BACKTEST_SEASONS.value}")
        if self.uplift_points < GINI_UPLIFT_POINTS.value:
            reasons.append(
                f"uplift {self.uplift_points:+.2f} Gini points is below the "
                f"{GINI_UPLIFT_POINTS.value:.0f} the phase file requires"
            )
        return "; ".join(reasons)


def gini_uplift(
    baseline_gini: float,
    with_agri_gini: float,
    *,
    seasons: int,
    out_of_time: bool,
) -> UpliftResult:
    """Criterion (b), from two Gini figures the caller measured.

    ``out_of_time`` is required with no default. Phase 3 made exactly this
    mistake and caught it (finding P3-F14): an in-sample comparison between a
    richer and a poorer feature set measures capacity, and the richer set always
    wins. The agri feature set is strictly larger than the baseline, so an
    in-sample "+4 Gini" here would be close to guaranteed and would mean
    nothing.
    """
    for name, value in (("baseline", baseline_gini), ("with agri", with_agri_gini)):
        if not -1.0 <= value <= 1.0:
            raise BacktestError(f"{name} Gini {value} is outside [-1, 1]")
    return UpliftResult(
        baseline_gini=baseline_gini,
        with_agri_gini=with_agri_gini,
        seasons=seasons,
        out_of_time=out_of_time,
    )


# ---------------------------------------------------------------------------
# (c) non-sowing flag recall at lead
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SeasonLinkedDefault:
    """A default attributed to a crop season, with when the flag would have fired.

    ``flag_date`` is ``None`` when the flag never fired for this account. That is
    a miss, and it is kept distinct from a flag that fired too late — the two
    fail the criterion for different reasons and call for different fixes.
    """

    account_id: str
    season: str
    default_date: date
    flag_date: date | None = None

    @property
    def lead_days(self) -> int | None:
        if self.flag_date is None:
            return None
        return (self.default_date - self.flag_date).days

    def fired_with_lead(self, minimum_days: int) -> bool:
        lead = self.lead_days
        return lead is not None and lead >= minimum_days


@dataclass(frozen=True)
class NonSowingResult:
    """Criterion (c): recall at lead, with the misses separated by cause."""

    total_defaults: int
    fired_in_time: int
    fired_too_late: int
    never_fired: int
    seasons: int
    median_lead_days: float | None

    @property
    def recall(self) -> float:
        if self.total_defaults == 0:
            raise BacktestError(
                "no season-linked defaults; a recall over zero events is not "
                "1.0 and not 0.0 — it is unmeasured"
            )
        return self.fired_in_time / self.total_defaults

    @property
    def passed(self) -> bool:
        return (
            self.total_defaults > 0
            and self.recall >= NON_SOWING_RECALL.value
            and self.seasons >= MIN_BACKTEST_SEASONS.value
        )

    @property
    def why_not(self) -> str:
        if self.total_defaults == 0:
            return "no season-linked defaults to measure recall over"
        reasons = []
        if self.seasons < MIN_BACKTEST_SEASONS.value:
            reasons.append(f"spans {self.seasons} seasons, below {MIN_BACKTEST_SEASONS.value}")
        if self.recall < NON_SOWING_RECALL.value:
            reasons.append(
                f"recall {self.recall:.3f} at >= {NON_SOWING_LEAD_DAYS.value} days "
                f"lead is below the {NON_SOWING_RECALL.value:.2f} required "
                f"({self.fired_too_late} fired too late, {self.never_fired} "
                "never fired)"
            )
        return "; ".join(reasons)


def non_sowing_backtest(
    defaults: Sequence[SeasonLinkedDefault], *, seasons: int
) -> NonSowingResult:
    """Criterion (c).

    ``defaults`` must already be season-linked. The attribution rule is
    :data:`SEASON_LINKAGE_RULE` (LH-412) and is not inferred here — a farmer
    holding a Kharif and a Rabi loan who defaults in March belongs to one of
    them, and which one changes both the numerator and the lead time.
    """
    lead_minimum = NON_SOWING_LEAD_DAYS.value
    fired_in_time = [d for d in defaults if d.fired_with_lead(lead_minimum)]
    fired_late = [
        d for d in defaults if d.flag_date is not None and not d.fired_with_lead(lead_minimum)
    ]
    never = [d for d in defaults if d.flag_date is None]

    leads = [d.lead_days for d in defaults if d.lead_days is not None]
    return NonSowingResult(
        total_defaults=len(defaults),
        fired_in_time=len(fired_in_time),
        fired_too_late=len(fired_late),
        never_fired=len(never),
        seasons=seasons,
        median_lead_days=statistics.median(leads) if leads else None,
    )


# ---------------------------------------------------------------------------
# The pack
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BacktestReport:
    """All three criteria, with the phase file's response rule attached."""

    monotonicity: MonotonicityResult
    uplift: UpliftResult
    non_sowing: NonSowingResult

    @property
    def passed(self) -> bool:
        return (
            self.monotonicity.passed and self.uplift.passed and self.non_sowing.passed
        )

    @property
    def failures(self) -> dict[str, str]:
        out = {}
        for name, result in (
            ("a_lqi_monotonic", self.monotonicity),
            ("b_gini_uplift", self.uplift),
            ("c_non_sowing_recall", self.non_sowing),
        ):
            if not result.passed:
                out[name] = result.why_not
        return out

    @property
    def response(self) -> str:
        """What the phase file says to do about a failure.

        Carried on the report because the instruction — "a failed test triggers
        feature redesign, never threshold relaxation" — is aimed at the moment
        someone is looking at a near miss, which is exactly when they are
        reading this object.
        """
        if self.passed:
            return "all three criteria met"
        return (
            "Phase 2 §4 WS-2.4: a failed test triggers feature redesign — never "
            "threshold relaxation. The thresholds here are [SPEC] constants and "
            "run_backtest() accepts no overrides."
        )

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "a_lqi_monotonic": {
                "passed": self.monotonicity.passed,
                "npa_rates_by_quartile": list(self.monotonicity.rates),
                "spread": self.monotonicity.spread,
                "why_not": self.monotonicity.why_not,
            },
            "b_gini_uplift": {
                "passed": self.uplift.passed,
                "uplift_points": self.uplift.uplift_points,
                "out_of_time": self.uplift.out_of_time,
                "why_not": self.uplift.why_not,
            },
            "c_non_sowing_recall": {
                "passed": self.non_sowing.passed,
                "total_defaults": self.non_sowing.total_defaults,
                "fired_in_time": self.non_sowing.fired_in_time,
                "fired_too_late": self.non_sowing.fired_too_late,
                "never_fired": self.non_sowing.never_fired,
                "median_lead_days": self.non_sowing.median_lead_days,
                "why_not": self.non_sowing.why_not,
            },
            "response": self.response,
        }


def run_backtest(
    *,
    lqi_scores: Sequence[float],
    lqi_defaults: Sequence[int],
    baseline_gini: float,
    with_agri_gini: float,
    out_of_time: bool,
    season_linked_defaults: Sequence[SeasonLinkedDefault],
    seasons: int,
    feature_uses: Sequence[FeatureUse] = (),
) -> BacktestReport:
    """Run all three WS-2.4 criteria.

    Takes **no thresholds**. Every bar is a `[SPEC]` constant from the phase
    file, because the instruction attached to these tests is that a failure
    triggers feature redesign rather than threshold relaxation, and a parameter
    with a default is how relaxation happens without anyone deciding to relax
    anything.

    ``feature_uses`` is checked first: a point-in-time violation invalidates
    everything after it, so it raises rather than being reported as a failure.
    """
    if feature_uses:
        assert_point_in_time(feature_uses)

    return BacktestReport(
        monotonicity=quartile_monotonicity(lqi_scores, lqi_defaults, seasons),
        uplift=gini_uplift(
            baseline_gini, with_agri_gini, seasons=seasons, out_of_time=out_of_time
        ),
        non_sowing=non_sowing_backtest(season_linked_defaults, seasons=seasons),
    )

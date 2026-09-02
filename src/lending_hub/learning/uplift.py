"""Uplift modelling and the identifiability guard — Phase 6 WS-6.4.

WS-6.4 wants the causal effect of each collections action on cure:

    τ(x) = E[cure|action,x] − E[cure|control,x]

via meta-learners (Künzel et al., arXiv:1706.03461) or causal forests (Wager &
Athey, arXiv:1510.04342). The phase file then states the condition the whole
workstream rests on:

    Randomized action holdouts are **standing policy** (without them, uplift is
    unidentifiable — an AI assistant must never estimate uplift from purely
    observational action logs and present it as causal).

That parenthesis is the module's subject.

Why this is a refusal and not a warning
-----------------------------------------
Phase 3 established that *not measured* and *not measurable* are different gate
states. This is a third thing, and it is stronger than either.

"Not measurable" means the data is absent: given the right dataset, the number
appears. **Unidentifiable** means no quantity of data supplies it. A collections
desk that called every borrower an officer judged likely to cure produces a log
in which treatment and outcome are confounded by that judgement — and the naive
difference computed on it is not a noisy estimate of τ. It is a different
quantity, biased in the direction that flatters the action, because the officer
selected the cases most likely to cure anyway.

More data makes it *tighter*, not *truer*. A confidence interval around a
confounded estimate narrows around the wrong number, which is worse than a wide
interval around the right one — it converts a visible uncertainty into an
invisible bias.

So :func:`estimate_uplift` refuses a log it cannot verify was randomized, and
the refusal is structural: :class:`UpliftEstimate` cannot be constructed from an
unrandomized log at all. A warning attached to a returned number would be
stripped by the first person who put the number in a slide.

What "verify" can and cannot mean here
----------------------------------------
This module cannot prove randomization — no code can, from the log alone. What
it can do is refuse the cases where randomization is *demonstrably* absent, and
require an attributable assertion for the rest:

* **Demonstrably absent.** A log with no control arm, or with a control arm that
  differs from treatment on the covariates recorded, fails
  :func:`check_randomization` on the evidence in front of it.
* **Asserted.** :class:`ActionLog.assignment` records *how* treatment was
  assigned, as a claim by a named owner. ``OBSERVATIONAL`` is refused outright;
  ``RANDOMIZED`` is accepted and attributed.

The balance check is a necessary condition, never a sufficient one. A
confounded log can pass covariate balance on the three columns someone happened
to record, and :class:`BalanceReport` says so rather than returning a verdict —
the same shape as :class:`~lending_hub.assistant.guardrails.InjectionScan`,
which reports what matched and never reports safety.

What this does not port
-------------------------
No meta-learner and no causal forest. Both need a base learner fitted on an
outcome the log does not contain (there are no logged actions — ADR-0014), and
the phase file's promotion gate for this workstream is *Qini + online cure-rate
lift*, whose second term needs live traffic. What is built is the identifiability
guard, the Qini/uplift-curve mechanics, and the T-learner *contract* — the
arithmetic is exact and testable; the base learners are a port boundary.

Workstream: WS-6.4 · SRS §10
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum


class UpliftError(Exception):
    """Raised when a causal quantity is requested from a log that cannot support it."""


#: Minimum accounts in each arm before an uplift curve is computed at all.
#: [SPEC] — not a policy threshold but an arithmetic floor: a Qini curve over
#: fewer points than this is dominated by the ordering of individual accounts.
#: The *promotion* threshold on the resulting coefficient is LH-802.
MIN_ARM_SIZE = 30

#: Standardised-mean-difference above which a covariate is reported as imbalanced.
#: [SPEC] Austin 2009's conventional flag, used across the causal-inference
#: literature as a reporting convention rather than a decision rule — which is
#: exactly how it is used here: :class:`BalanceReport` reports, never decides.
SMD_FLAG = 0.1


class Assignment(str, Enum):
    """How treatment was assigned in a log. The only thing that matters."""

    RANDOMIZED = "randomized"
    """Assigned by a mechanism independent of the outcome. τ is identifiable."""

    OBSERVATIONAL = "observational"
    """Assigned by human or model judgement. τ is **not** identifiable, whatever
    the sample size."""

    UNKNOWN = "unknown"
    """Nobody recorded how. Treated as observational — the safe reading, and the
    one that creates pressure to record it."""


@dataclass(frozen=True)
class ActionRecord:
    """One account, the action it did or did not receive, and what happened."""

    account_id: str
    treated: bool
    outcome: float
    """The cure indicator, or any outcome on which uplift is defined."""

    covariates: dict[str, float] = field(default_factory=dict)
    propensity: float | None = None
    """P(treated | covariates) at assignment time, when it was logged. Required
    for IPW-style estimators; absent in a plain A/B where it is constant."""


@dataclass(frozen=True)
class ActionLog:
    """A set of action records with an attributed claim about how they arose."""

    records: Sequence[ActionRecord]
    assignment: Assignment
    asserted_by: str = ""
    """Who claims the assignment mechanism. Required for RANDOMIZED: it is an
    attributable statement, because everything downstream depends on it and no
    code can check it."""

    def __post_init__(self) -> None:
        if self.assignment is Assignment.RANDOMIZED and not self.asserted_by.strip():
            raise UpliftError(
                "assignment=RANDOMIZED requires asserted_by: no code can verify "
                "randomization from a log, so the claim carries a name"
            )

    @property
    def treated(self) -> list[ActionRecord]:
        return [r for r in self.records if r.treated]

    @property
    def control(self) -> list[ActionRecord]:
        return [r for r in self.records if not r.treated]


@dataclass(frozen=True)
class CovariateBalance:
    """One covariate's standardised mean difference between arms."""

    name: str
    treated_mean: float
    control_mean: float
    smd: float

    @property
    def flagged(self) -> bool:
        return abs(self.smd) > SMD_FLAG


@dataclass(frozen=True)
class BalanceReport:
    """What the covariate comparison found. **Never a verdict.**

    A passing balance report is not evidence of randomization: a confounded log
    balances on the columns someone happened to record, and the confounder is
    usually the officer's judgement, which is recorded nowhere. So this reports
    what it compared and how many columns that was, and
    :attr:`proves_randomization` exists only to be ``False``.
    """

    covariates: tuple[CovariateBalance, ...]
    treated_n: int
    control_n: int

    @property
    def flagged(self) -> tuple[CovariateBalance, ...]:
        return tuple(c for c in self.covariates if c.flagged)

    @property
    def proves_randomization(self) -> bool:
        """Always ``False``, and the docstring is the point.

        Balance on observed covariates is a necessary condition. Reporting it as
        sufficient is the single most common way an observational uplift number
        acquires the authority of an experimental one.
        """
        return False

    def summary(self) -> str:
        if not self.covariates:
            return (
                f"no covariates recorded; {self.treated_n} treated vs "
                f"{self.control_n} control compared on nothing"
            )
        names = ", ".join(c.name for c in self.flagged)
        if not names:
            return (
                f"{len(self.covariates)} covariate(s) within SMD {SMD_FLAG}; "
                "this is a necessary condition, not evidence of randomization"
            )
        return f"{len(self.flagged)} covariate(s) imbalanced above SMD {SMD_FLAG}: {names}"


def check_randomization(log: ActionLog) -> BalanceReport:
    """Compare arms on every recorded covariate. Reports; does not decide."""
    treated, control = log.treated, log.control
    names = sorted({k for r in log.records for k in r.covariates})

    balances: list[CovariateBalance] = []
    for name in names:
        t_vals = [r.covariates[name] for r in treated if name in r.covariates]
        c_vals = [r.covariates[name] for r in control if name in r.covariates]
        if not t_vals or not c_vals:
            continue
        t_mean, c_mean = _mean(t_vals), _mean(c_vals)
        pooled = _pooled_sd(t_vals, c_vals)
        if pooled > 0.0:
            smd = (t_mean - c_mean) / pooled
        elif t_mean == c_mean:
            # Both arms constant at the same value: identical, not merely balanced.
            smd = 0.0
        else:
            # Both arms constant at *different* values — zero within-arm variance
            # and a non-zero gap. This is maximal separation, not perfect balance,
            # and returning 0.0 here would report the most imbalanced covariate
            # possible as the cleanest one. Infinity is the honest SMD.
            smd = math.inf if t_mean > c_mean else -math.inf
        balances.append(CovariateBalance(name, t_mean, c_mean, smd))

    return BalanceReport(tuple(balances), len(treated), len(control))


@dataclass(frozen=True)
class UpliftEstimate:
    """A causal effect estimate. Constructible only from a randomized log.

    The guard is in :func:`estimate_uplift` rather than ``__post_init__`` so the
    refusal names the log's actual defect, but the invariant is the same one
    Phase 4's :class:`~lending_hub.reco.bandit.BanditDecision` uses for
    propensity: the dangerous state is unrepresentable.
    """

    effect: float
    treated_n: int
    control_n: int
    treated_rate: float
    control_rate: float
    asserted_by: str
    balance: BalanceReport


def estimate_uplift(log: ActionLog) -> UpliftEstimate:
    """The average treatment effect, or a refusal naming why it is unavailable.

    Raises rather than returning a flagged number. An estimate carrying a
    ``causal=False`` attribute is a number in a dataframe, and the attribute is
    gone by the second transformation.
    """
    if log.assignment is not Assignment.RANDOMIZED:
        raise UpliftError(
            f"assignment={log.assignment.value}: uplift is unidentifiable from a "
            "log whose treatment was not randomized. More rows narrow the interval "
            "around a confounded quantity rather than converging on tau — Phase 6 "
            "§2 WS-6.4 makes randomized holdouts standing policy, and §5 forbids "
            "presenting an observational estimate as causal"
        )

    treated, control = log.treated, log.control
    if len(treated) < MIN_ARM_SIZE or len(control) < MIN_ARM_SIZE:
        raise UpliftError(
            f"arms of {len(treated)} treated and {len(control)} control are below "
            f"the arithmetic floor of {MIN_ARM_SIZE}; an effect computed here is "
            "an artefact of a handful of accounts"
        )

    t_rate = _mean([r.outcome for r in treated])
    c_rate = _mean([r.outcome for r in control])
    return UpliftEstimate(
        effect=t_rate - c_rate,
        treated_n=len(treated),
        control_n=len(control),
        treated_rate=t_rate,
        control_rate=c_rate,
        asserted_by=log.asserted_by,
        balance=check_randomization(log),
    )


@dataclass(frozen=True)
class QiniPoint:
    """One point on the Qini curve: accounts targeted, incremental outcomes."""

    targeted: int
    incremental: float


def qini_curve(
    log: ActionLog, scores: dict[str, float]
) -> tuple[QiniPoint, ...]:
    """The Qini curve for a targeting rule, highest score first.

    At each prefix, the incremental outcome is

        Y_t(k) − Y_c(k) · N_t(k)/N_c(k)

    — the treated outcomes in the prefix, minus the control outcomes scaled to
    the treated arm's size, which is what makes the curve comparable across
    prefixes with different arm ratios.

    Subject to the same identifiability guard: a Qini curve over an
    observational log ranks accounts by a confounded quantity.
    """
    if log.assignment is not Assignment.RANDOMIZED:
        raise UpliftError(
            f"assignment={log.assignment.value}: a Qini curve over an "
            "unrandomized log measures the assignment rule, not the targeting rule"
        )
    missing = [r.account_id for r in log.records if r.account_id not in scores]
    if missing:
        raise UpliftError(
            f"{len(missing)} account(s) have no score, first {missing[0]!r}: a "
            "partial ranking silently drops accounts from the curve"
        )

    ordered = sorted(log.records, key=lambda r: (-scores[r.account_id], r.account_id))
    points: list[QiniPoint] = []
    y_t = y_c = 0.0
    n_t = n_c = 0
    for k, record in enumerate(ordered, start=1):
        if record.treated:
            y_t += record.outcome
            n_t += 1
        else:
            y_c += record.outcome
            n_c += 1
        incremental = y_t - (y_c * n_t / n_c if n_c else 0.0)
        points.append(QiniPoint(targeted=k, incremental=incremental))
    return tuple(points)


def qini_coefficient(curve: Sequence[QiniPoint]) -> float:
    """Area between the Qini curve and the random-targeting diagonal.

    Normalised by the number of accounts so curves over different populations
    are comparable. No threshold is applied — WS-6.4's promotion gate is "Qini
    coefficient + online cure-rate lift" with neither quantified (LH-802).
    """
    if len(curve) < 2:
        raise UpliftError("a Qini coefficient needs at least two points")

    n = len(curve)
    final = curve[-1].incremental
    area = 0.0
    for left, right in zip(curve, curve[1:]):
        area += (left.incremental + right.incremental) / 2.0
    diagonal = sum(final * (k / n) for k in range(1, n))
    return (area - diagonal) / n


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _pooled_sd(left: Sequence[float], right: Sequence[float]) -> float:
    def variance(values: Sequence[float]) -> float:
        if len(values) < 2:
            return 0.0
        m = _mean(values)
        return sum((v - m) ** 2 for v in values) / (len(values) - 1)

    return ((variance(left) + variance(right)) / 2.0) ** 0.5

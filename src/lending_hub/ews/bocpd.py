"""Bayesian Online Changepoint Detection (WS-4.A Step 3).

Phase 4 §4 Step 3 names the method, the reference and the test:

    **BOCPD** — Adams & MacKay, 2007, arXiv:0710.3742 — run on three canonical
    weekly series per account with AA/CASA visibility: net inflows,
    closing-balance trend, discretionary-spend share. Implementation: reference
    BOCPD code or `bayesian_changepoint_detection`; **unit-test against the
    paper's well-log example** (reference-implementation rule). Mechanics:
    posterior over run length r_t; spike in P(r_t = 0) = regime change (salary
    loss, business interruption) — visible months before a missed EMI.

What the algorithm actually does, and why it suits this problem
----------------------------------------------------------------
BOCPD maintains a posterior over the **run length** — how long since the last
regime change — updated one observation at a time. At each step the run length
either grows by one (the regime continues) or resets to zero (a change). The
posterior over ``r_t = 0`` is therefore a direct, calibrated "did something just
change?" probability.

That online, one-observation-at-a-time property is why the phase file chose it
over a retrospective segmentation method. An EWS sees a customer's cash-flow
series *as it arrives*; a method that needs the whole series to place its
changepoints cannot answer "has something changed as of this week", which is the
only question the desk can act on.

The other reason is that a regime change in inflows is not an outlier. A salary
stopping is a *level shift* — every subsequent week is low, and none of them is
individually anomalous once you have seen two of them. Outlier detectors
(``portfolio.opsanomaly``'s S-H-ESD, for instance) find spikes and are close to
blind to exactly this. BOCPD is built for it.

Where the change-point signal actually lives
---------------------------------------------
Phase 4 §4 Step 3 says "spike in P(r_t = 0) = regime change". Taken literally
that is wrong, and it is wrong in a way that produces a detector which never
detects anything — so it is worth stating precisely.

Under a **constant** hazard ``h``, the normalised ``P(r_t = 0)`` is *identically*
``h`` at every step. The algebra is two lines: the change-point row is
``logsumexp_r(posterior[r] + predictive[r]) + log(h)`` and the growth rows sum to
``logsumexp_r(posterior[r] + predictive[r]) + log(1-h)``, so the evidence is
``logsumexp_r(posterior[r] + predictive[r])`` and the ratio is exactly ``h``. The
change row sums the *same* predictive mass the growth rows do, so it carries no
evidence about whether a change occurred.

The evidence appears one step later, at **``P(r_t = 1)``** — "the current regime
began with the previous observation" — because that is the first point at which
the new regime has an observation to discriminate on. On a clean level shift
this rises to ~0.71 at the shifted index while ``P(r_t = 0)`` sits at 0.004.

:attr:`RunLengthPosterior.changepoint_probability` therefore reports
``P(r_t = 1)``, and ``P(r_t = 0)`` is kept as
:attr:`RunLengthPosterior.prior_reset_mass` for diagnostics. Raised as a Phase 4
finding against the phase file's wording.

The conjugate model
--------------------
Gaussian observations with unknown mean and variance, under a Normal-Inverse-Gamma
prior, so the posterior predictive is a Student-t and the whole update is closed
form. This is the model the paper uses for the well-log data, and it keeps the
implementation exact rather than approximate — no sampling, no particle filter.

The hazard is constant (``1/lambda``), which is the paper's memoryless
assumption: a regime is equally likely to end at any point. That is wrong for
some series and right for this one — a salary is not more likely to stop because
it has been paid for a long time.

What this does not port
-----------------------
Not `bayesian_changepoint_detection` and not the authors' MATLAB. There is no
run-length pruning (the paper suggests truncating the tail below a threshold for
long series; here the series are weekly over a couple of years, so the full
triangle is affordable and exact), no non-Gaussian likelihoods, and no
hyperparameter learning. The tests assert the *properties* a library swap must
preserve and the paper's published configuration — never this port's exact
posteriors on an arbitrary series.

Workstream: WS-4.A Step 3 (SRS §10.3 cash-flow)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

from lending_hub.definitions.provenance import Grounded, Pending, Source

#: The hazard rate Adams & MacKay use for the well-log example: a constant
#: 1/250, i.e. an expected regime length of 250 observations. `[SPEC]` from the
#: paper, and used here only by the reference test — a *customer cash-flow*
#: series has its own expected regime length and it is not 250 weeks.
WELL_LOG_HAZARD = Grounded(
    value=1.0 / 250.0,
    source=Source.SPEC,
    citation="Adams & MacKay 2007 (arXiv:0710.3742), well-log example",
)

#: The expected regime length for a customer cash-flow series, in weeks. This
#: sets how readily the model declares a change, so it sets the alert volume
#: from this signal family — which makes it the Collections Head's number, not
#: a modelling constant.
CASHFLOW_EXPECTED_REGIME_WEEKS = Pending(
    owner="Collections Head",
    ticket="LH-501",
    note="expected weeks between genuine cash-flow regime changes, per product",
)

#: P(r_t = 0) above which a change is declared. Also alert-budget-derived: the
#: posterior is calibrated, so this threshold converts directly into how many
#: customers get looked at.
CHANGEPOINT_PROBABILITY_THRESHOLD = Pending(
    owner="Collections Head",
    ticket="LH-501",
    note="posterior P(r_t = 0) at which a cash-flow change-point is declared",
)

#: The three canonical weekly series Phase 4 §4 Step 3 names. `[SPEC]`.
CANONICAL_SERIES = ("net_inflows", "closing_balance_trend", "discretionary_spend_share")


class BocpdError(Exception):
    """The detector cannot run on what it was given."""


@dataclass(frozen=True)
class NormalInverseGamma:
    """Conjugate prior for a Gaussian with unknown mean and variance.

    Parameterised as in the paper: ``mu`` prior mean, ``kappa`` prior
    observations on the mean, ``alpha``/``beta`` shape and scale on the
    precision. The well-log configuration uses weak values so the data
    dominates quickly, which is what makes the detector usable from a short
    history.
    """

    mu: float = 0.0
    kappa: float = 1.0
    alpha: float = 1.0
    beta: float = 1.0

    def __post_init__(self) -> None:
        if self.kappa <= 0:
            raise BocpdError(f"kappa must be positive, got {self.kappa}")
        if self.alpha <= 0:
            raise BocpdError(f"alpha must be positive, got {self.alpha}")
        if self.beta <= 0:
            raise BocpdError(f"beta must be positive, got {self.beta}")


def student_t_logpdf(x: float, mu: float, sigma_squared: float, nu: float) -> float:
    """Log density of a Student-t — the posterior predictive of the NIG model.

    Written in log space throughout. The run-length posterior is a product of
    many predictive densities and underflows to zero in linear space on a series
    of a few hundred points, which shows up as a detector that silently stops
    detecting.
    """
    if sigma_squared <= 0:
        raise BocpdError(f"scale must be positive, got {sigma_squared}")
    if nu <= 0:
        raise BocpdError(f"degrees of freedom must be positive, got {nu}")

    z = (x - mu) ** 2 / sigma_squared
    return (
        math.lgamma((nu + 1.0) / 2.0)
        - math.lgamma(nu / 2.0)
        - 0.5 * math.log(math.pi * nu * sigma_squared)
        - ((nu + 1.0) / 2.0) * math.log1p(z / nu)
    )


@dataclass
class _SufficientStatistics:
    """Per-run-length NIG parameters, updated in place as the run grows."""

    mu: list[float] = field(default_factory=list)
    kappa: list[float] = field(default_factory=list)
    alpha: list[float] = field(default_factory=list)
    beta: list[float] = field(default_factory=list)

    def predictive_logpdf(self, x: float) -> list[float]:
        """Posterior predictive log-density of ``x`` under every run length."""
        out = []
        for mu, kappa, alpha, beta in zip(self.mu, self.kappa, self.alpha, self.beta):
            scale = beta * (kappa + 1.0) / (alpha * kappa)
            out.append(student_t_logpdf(x, mu, scale, 2.0 * alpha))
        return out

    def update(self, x: float, prior: NormalInverseGamma) -> None:
        """Standard NIG update, prepending the fresh-prior row for ``r_t = 0``."""
        new_mu = [prior.mu] + [
            (k * m + x) / (k + 1.0) for m, k in zip(self.mu, self.kappa)
        ]
        new_kappa = [prior.kappa] + [k + 1.0 for k in self.kappa]
        new_alpha = [prior.alpha] + [a + 0.5 for a in self.alpha]
        new_beta = [prior.beta] + [
            b + (k * (x - m) ** 2) / (2.0 * (k + 1.0))
            for m, k, b in zip(self.mu, self.kappa, self.beta)
        ]
        self.mu, self.kappa, self.alpha, self.beta = new_mu, new_kappa, new_alpha, new_beta


@dataclass(frozen=True)
class RunLengthPosterior:
    """The output of one BOCPD step.

    ``changepoint_probability`` is the quantity the alerting layer reads, and
    getting it right required correcting the phase file's shorthand — see
    :func:`detect` and the module note below.
    """

    index: int
    changepoint_probability: float
    most_likely_run_length: int
    posterior: tuple[float, ...]

    @property
    def prior_reset_mass(self) -> float:
        """``P(r_t = 0)`` as it appears in the normalised posterior.

        Kept because the phase file names it, and because it is a useful
        diagnostic: under a **constant** hazard it is identically the hazard at
        every step, so seeing anything else here means the hazard is not
        constant or the normalisation is wrong.
        """
        return self.posterior[0] if self.posterior else 0.0

    @property
    def expected_run_length(self) -> float:
        return sum(r * p for r, p in enumerate(self.posterior))


@dataclass(frozen=True)
class ChangepointResult:
    """A full BOCPD pass over a series."""

    series_name: str
    steps: tuple[RunLengthPosterior, ...]
    hazard: float

    @property
    def changepoint_probabilities(self) -> tuple[float, ...]:
        return tuple(s.changepoint_probability for s in self.steps)

    def changepoints(self, *, threshold: float) -> tuple[int, ...]:
        """Indices whose change-point probability exceeds ``threshold``.

        ``threshold`` has no default: the posterior is calibrated, so the
        threshold converts directly into how many customers are looked at, which
        makes it the alert budget's business (LH-501) rather than a modelling
        constant.

        Index 0 is excluded. The first observation of any series necessarily
        begins a regime, so it scores ~1.0 on every series ever passed in — it
        is a boundary artefact, not a detection, and leaving it in would put a
        change-point on every customer the day their account is opened.
        """
        if not 0.0 < threshold < 1.0:
            raise BocpdError(f"threshold must be in (0, 1), got {threshold}")
        return tuple(
            s.index
            for s in self.steps
            if s.index > 0 and s.changepoint_probability > threshold
        )

    @property
    def peak(self) -> RunLengthPosterior:
        """The step with the highest change-point probability, index 0 excluded.

        Excluded for the same reason as in :meth:`changepoints`: index 0 always
        wins, and a peak that is always the first observation is not a peak.
        """
        candidates = [s for s in self.steps if s.index > 0]
        if not candidates:
            raise BocpdError(
                "no steps after index 0; a series of one observation has no "
                "change-point to find"
            )
        return max(candidates, key=lambda s: s.changepoint_probability)


def detect(
    series: Sequence[float],
    *,
    hazard: float,
    prior: NormalInverseGamma | None = None,
    series_name: str = "",
) -> ChangepointResult:
    """Run BOCPD over ``series``.

    ``hazard`` is the constant per-step probability that the current regime
    ends — the paper's memoryless hazard function. It has no default: for the
    well-log example it is 1/250 `[SPEC]`, and for a customer cash-flow series
    it is an expected regime length nobody has supplied (LH-501).

    Returns one :class:`RunLengthPosterior` per observation. The algorithm is
    the paper's Algorithm 1 exactly: evaluate the predictive probability under
    each run length, compute growth and change-point probabilities, normalise,
    then update the sufficient statistics.
    """
    if not 0.0 < hazard < 1.0:
        raise BocpdError(
            f"hazard must be in (0, 1), got {hazard}. It is a per-step "
            "probability of regime change, not an expected run length — passing "
            "250 where 1/250 belongs makes every step a change-point."
        )
    if len(series) < 2:
        raise BocpdError(
            f"BOCPD needs at least 2 observations, got {len(series)}. A run "
            "length posterior over a single point is the prior."
        )
    if any(not math.isfinite(x) for x in series):
        raise BocpdError(
            "series contains a non-finite value. A missing cash-flow week is "
            "not a zero-inflow week, and imputing one as the other manufactures "
            "exactly the level shift this detector is looking for."
        )

    prior = prior or NormalInverseGamma()
    stats = _SufficientStatistics(
        mu=[prior.mu], kappa=[prior.kappa], alpha=[prior.alpha], beta=[prior.beta]
    )

    # log P(r_t = 0) = 0 at t = 0: before any data the run length is certainly 0.
    log_posterior = [0.0]
    log_hazard = math.log(hazard)
    log_survival = math.log1p(-hazard)

    steps: list[RunLengthPosterior] = []

    for index, x in enumerate(series):
        predictive = stats.predictive_logpdf(x)

        # Growth: the run continues, so r_t = r_{t-1} + 1.
        growth = [
            lp + pred + log_survival for lp, pred in zip(log_posterior, predictive)
        ]
        # Change: the run resets, summing the mass over every prior run length.
        change = _logsumexp(
            [lp + pred + log_hazard for lp, pred in zip(log_posterior, predictive)]
        )

        unnormalised = [change] + growth
        evidence = _logsumexp(unnormalised)
        log_posterior = [v - evidence for v in unnormalised]

        posterior = tuple(math.exp(v) for v in log_posterior)
        steps.append(
            RunLengthPosterior(
                index=index,
                # P(r_t = 1): the regime began at this observation. See the
                # module docstring's "Where the change-point signal actually
                # lives" — P(r_t = 0) is identically the hazard under a constant
                # hazard function and carries no evidence at all.
                changepoint_probability=posterior[1] if len(posterior) > 1 else 0.0,
                most_likely_run_length=max(
                    range(len(posterior)), key=lambda r: posterior[r]
                ),
                posterior=posterior,
            )
        )

        stats.update(x, prior)

    return ChangepointResult(
        series_name=series_name, steps=tuple(steps), hazard=hazard
    )


def _logsumexp(values: Sequence[float]) -> float:
    """Numerically stable log-sum-exp."""
    if not values:
        raise BocpdError("logsumexp of an empty sequence")
    peak = max(values)
    if peak == -math.inf:
        return -math.inf
    return peak + math.log(sum(math.exp(v - peak) for v in values))


@dataclass(frozen=True)
class CashflowChange:
    """A detected change in one of the three canonical series, with direction.

    ``direction`` is what the two-key rule in Phase 4 §4 Step 3 needs: a
    change-point alone is Amber, and Red requires the change to be in the
    *adverse* direction. A regime change upward in net inflows is a promotion,
    not a distress signal, and an EWS that alerts on it burns the officer's
    attention on good news.
    """

    account_id: str
    series_name: str
    index: int
    probability: float
    mean_before: float
    mean_after: float

    @property
    def is_adverse(self) -> bool:
        """Whether the shift is in the direction that indicates distress.

        All three canonical series are defined so that *down is bad* for the
        first two and *up is bad* for the third — a rising discretionary-spend
        share on a falling income is the classic pre-distress pattern.
        """
        if self.series_name == "discretionary_spend_share":
            return self.mean_after > self.mean_before
        return self.mean_after < self.mean_before

    @property
    def shift(self) -> float:
        return self.mean_after - self.mean_before


def describe_change(
    account_id: str,
    series: Sequence[float],
    result: ChangepointResult,
    index: int,
) -> CashflowChange:
    """Characterise a detected change: how big, and in which direction.

    The means either side are computed from the observations, not from the
    model's posterior. A caller acting on a change needs to know it went from
    ₹40,000 a week to ₹8,000 — the posterior mean of a Student-t is not the
    thing to put in front of a collections officer.
    """
    if not 0 < index < len(series):
        raise BocpdError(
            f"change index {index} is outside the series (length {len(series)}); "
            "a change at index 0 is the start of the record, not a change"
        )
    before = series[:index]
    after = series[index:]
    if not before or not after:
        raise BocpdError("a change needs observations on both sides")

    return CashflowChange(
        account_id=account_id,
        series_name=result.series_name,
        index=index,
        probability=result.steps[index].changepoint_probability,
        mean_before=sum(before) / len(before),
        mean_after=sum(after) / len(after),
    )

"""Loss given default — two-stage, on real workout cashflows (WS-3.1 Step 5).

SRS §7.3.3 specifies two stages: (i) the probability a defaulted account
*cures* and returns to performing, and (ii) the recovery rate on those that do
not, modelled by beta regression. Expected LGD combines them:

    E[LGD] = P(not cured) · E[LGD | not cured]

Both stages sit behind a `[POLICY]` value that does not exist, and both say so
by raising rather than defaulting — the cure definition (LH-309) decides which
defaults enter stage two at all, and the discounting convention (LH-305) moves
the answer by more than most modelling choices do.

What is grounded and what is not
--------------------------------
* :func:`realised_lgd` is **`[DATA]`**: exposure plus workout costs minus
  workout proceeds, over exposure. It is computable from cashflows with no
  policy input, and it is *undiscounted* — a different quantity from the LGD
  that enters ECL, named differently here so the two cannot be confused in a
  report.
* :func:`discounted_lgd` needs the LH-305 convention and raises without it.
* :func:`downturn_lgd` needs the LH-302 add-on and raises without it.
* The cure model needs LH-309 and raises without it.

The boundary problem, which is not a detail
-------------------------------------------
Realised LGD is not beta-distributed. It has large point masses at 0 (the
collateral covered everything) and at or above 1 (it did not, and costs
exceeded the exposure), with a thin spread between. Beta regression is defined
on the open interval, so those masses have to be handled explicitly, and
"handled" here means the Smithson-Verkuilen squeeze — a transformation that
*changes the data* and is therefore reported by :class:`LGDDistribution` rather
than applied quietly. On the Fannie Mae 2007 vintage the boundary mass is large
enough that a model fitted to the interior alone is describing a minority of
the defaults.

What this does not port
-----------------------
No zero-and-one-inflated beta model, no mixture, no survival-based workout
timing model. Phase 3 names beta regression, so beta regression is what is
here; the inflation is measured and reported rather than modelled, and that
limitation is in the model card.

Reference: Ferrari & Cribari-Neto, "Beta regression for modelling rates and
proportions", *Journal of Applied Statistics* 31(7), 2004. Benchmark context:
Loterman, Brown, Martens, Mues & Baesens, *IJF* 28(1), 2012.

Workstream: WS-3.1 Step 5 (SRS §7.3.3)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence

from lending_hub.definitions.provenance import Pending, Ungrounded
from lending_hub.portfolio.linalg import SingularMatrix, invert, solve

#: The discounting convention for workout cashflows. SRS §7.3.3 names the
#: contract rate but not the convention — compounding basis, and whether the
#: horizon starts at default or at last paid instalment. Both move LGD.
DISCOUNT_CONVENTION = Pending(
    owner="Finance Controller",
    ticket="LH-305",
    note=(
        "workout discounting: which rate, what compounding, and the date the "
        "horizon runs from"
    ),
)

#: What counts as a defaulted account returning to performing, and over what
#: window. Appendix A defines default; nothing defines cure.
CURE_DEFINITION = Pending(
    owner="Credit Policy",
    ticket="LH-309",
    note="the cure definition and its observation window",
)

#: Whether credit enhancement (mortgage insurance, guarantees, make-whole
#: proceeds) is netted off the loss before LGD is computed. Not on the Phase 3
#: §8 list; found by building — see :class:`LossBasis`.
CREDIT_ENHANCEMENT_TREATMENT = Pending(
    owner="Risk Committee + Finance Controller",
    ticket="LH-311",
    note=(
        "whether LGD is measured net or gross of credit enhancement, and which "
        "enhancements count as integral to the contract"
    ),
)

#: The evidence-backed downturn uplift (Phase 3 §8).
DOWNTURN_ADD_ON = Pending(
    owner="Risk Committee",
    ticket="LH-302",
    note="downturn LGD add-on and the downturn period it was measured over",
)

MAX_ITERATIONS = 100
CONVERGENCE_TOLERANCE = 1e-8


class LGDError(Exception):
    """The LGD calculation cannot be performed as asked."""


# --------------------------------------------------------------------------
# Realised LGD from workout cashflows — [DATA]
# --------------------------------------------------------------------------


class LossBasis(str, Enum):
    """Whether credit enhancement is netted off before LGD is computed.

    This is not a presentation choice. Measured on the Fannie Mae 2007 vintage
    (`tools/trackp_p3_report.py`), where private mortgage insurance is required
    above 80% original LTV and paid on ~90% of the losses that had it:

    ==========  ======  =========  =================  ===================
    orig LTV         n    MI paid    LGD net of MI      LGD gross of MI
    ==========  ======  =========  =================  ===================
    <= 80       15,712       0.0%             0.4285               0.4285
    81-90        3,147      89.9%             0.3102               0.4925
    > 90         1,600      94.6%             0.2120               0.4767
    ==========  ======  =========  =================  ===================

    Net of enhancement, LGD *falls* as LTV rises; gross of it, LGD *rises*. The
    basis therefore decides the **sign** of the LTV coefficient in the recovery
    model — a model fitted on the net basis says less equity means smaller
    losses, which is true of this insurance structure and false of the
    collateral. Neither basis is wrong; using one while reading the other's
    interpretation is. LH-311.
    """

    NET_OF_ENHANCEMENT = "net_of_enhancement"
    """Loss after mortgage insurance, guarantees and make-whole proceeds. What
    the lender actually lost."""

    GROSS_OF_ENHANCEMENT = "gross_of_enhancement"
    """Loss before them. What the collateral failed to cover, and the basis on
    which an LTV coefficient can be read as a statement about collateral."""


@dataclass(frozen=True)
class WorkoutCashflows:
    """One defaulted account's workout, in integer minor units.

    Minor units throughout, as everywhere else money appears in this platform:
    a recovery rate computed from floats that have been through a currency
    conversion is reproducible only by accident.

    ``proceeds`` and ``credit_enhancement_proceeds`` are separate fields
    because summing them at ingestion destroys the only information that makes
    :class:`LossBasis` a choice rather than a fait accompli.

Any of ``costs``, ``proceeds`` and
    ``credit_enhancement_proceeds`` may be **negative**, and none of them is
    validated as a magnitude. Servicing systems post net of credits — Fannie
    Mae's own field is "miscellaneous holding expenses *and credits*" — and a
    proceed that was later clawed back posts as a reversal. On the 2007
    vintage that is 2 rows in 20,459: immaterial to any average, and exactly
    the kind of row a strict magnitude check would drop while reporting
    nothing. :class:`LGDDistribution` counts them instead, so they are visible
    rather than either silently dropped or silently included.
    """

    account_id: str
    exposure_at_default: int
    costs: int = 0
    proceeds: int = 0
    credit_enhancement_proceeds: int = 0
    months_to_resolution: int | None = None
    attributes: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.exposure_at_default <= 0:
            raise LGDError(
                f"{self.account_id}: exposure at default is "
                f"{self.exposure_at_default}. LGD is a ratio to exposure and is "
                "undefined at zero — such an account is not a loss observation."
            )


    def net_loss(self, basis: LossBasis) -> int:
        """Loss on the named basis. There is no default basis — see LH-311."""
        loss = self.exposure_at_default + self.costs - self.proceeds
        if basis is LossBasis.NET_OF_ENHANCEMENT:
            loss -= self.credit_enhancement_proceeds
        return loss


def realised_lgd(
    workout: WorkoutCashflows,
    *,
    basis: LossBasis,
    clip: bool = True,
) -> float:
    """Undiscounted realised LGD on the named basis — **`[DATA]`**.

    ``basis`` is required and has no default. It flips the sign of the LTV
    relationship on real data (see :class:`LossBasis`), so a default here would
    silently decide the economics of every recovery model fitted downstream.

    ``clip`` bounds the result to ``[0, 1]``, which is what a downstream model
    needs and what every published severity figure reports. Set it False to see
    the raw ratio: values below 0 (proceeds exceeded exposure plus costs) and
    above 1 (costs alone exceeded the shortfall) are both real and both
    informative about the workout process rather than the borrower.
    """
    if not isinstance(basis, LossBasis):
        raise LGDError(
            f"basis must be a LossBasis, not {basis!r}. Whether credit "
            "enhancement is netted off is LH-311 and changes the sign of the "
            "LTV effect; it cannot be left to a default."
        )
    raw = workout.net_loss(basis) / workout.exposure_at_default
    if not clip:
        return raw
    return min(1.0, max(0.0, raw))


def discounted_lgd(workout: WorkoutCashflows, *, convention=DISCOUNT_CONVENTION) -> float:
    """Discounted LGD. Raises until LH-305 supplies the convention.

    There is deliberately no default rate and no default compounding basis. A
    discount convention chosen by an engineer becomes the bank's ECL convention
    the moment the first number is quoted from it.
    """
    if isinstance(convention, Pending):
        raise Ungrounded(
            f"discounted LGD needs the workout discounting convention: "
            f"{convention}. realised_lgd() computes the undiscounted figure, "
            "which is a different quantity — do not substitute one for the other "
            "in an ECL calculation."
        )
    raise LGDError(
        "a grounded discount convention was supplied but no implementation is "
        "registered against it. LH-305 must state the convention — which rate, "
        "what compounding, and the date the horizon runs from — before this path "
        "can be written; guessing any one of the three changes the answer."
    )


def downturn_lgd(base_lgd: float, *, add_on=DOWNTURN_ADD_ON) -> float:
    """Downturn-adjusted LGD. Raises until LH-302 supplies the add-on.

    Phase 3 §8 requires the add-on be evidence-backed, which means a named
    downturn period and a measured uplift. Track P can show the arithmetic —
    the Fannie Mae 2007 vintage is a downturn cohort by construction — but a
    US mortgage crisis severity is not this bank's add-on.
    """
    if isinstance(add_on, Pending):
        raise Ungrounded(
            f"downturn LGD needs the ratified add-on: {add_on}. Phase 3 §8 puts "
            "it on the do-not-invent list and requires it be evidence-backed."
        )
    return min(1.0, base_lgd + add_on)


@dataclass
class LGDDistribution:
    """The shape of realised LGD, with the boundary masses named.

    Reported before any model is fitted, because the boundary mass decides
    whether beta regression is describing the population or a slice of it.
    """

    basis: str
    count: int
    mean: float
    median: float
    at_zero: int
    at_one: int
    interior: int
    raw_below_zero: int = 0
    raw_above_one: int = 0
    reversals: int = 0
    """Workouts carrying a negative cost or proceed — a credit or a clawback.
    Real postings, kept in the sample and counted here so that a reader can see
    whether they are a rounding detail or a systemic feed problem."""

    @property
    def boundary_fraction(self) -> float:
        return (self.at_zero + self.at_one) / self.count if self.count else 0.0

    @property
    def beta_regression_caveat(self) -> str:
        if self.boundary_fraction >= 0.2:
            return (
                f"{self.boundary_fraction:.0%} of observations sit exactly on 0 or 1. "
                "Beta regression is defined on the open interval, so this share is "
                "moved inward by the Smithson-Verkuilen squeeze before fitting. The "
                "fitted model describes the interior; the point masses are a "
                "separate phenomenon it does not represent."
            )
        return ""

    def to_dict(self) -> dict:
        return {
            "basis": self.basis,
            "observations": self.count,
            "mean_lgd": round(self.mean, 6),
            "median_lgd": round(self.median, 6),
            "at_zero": self.at_zero,
            "at_one": self.at_one,
            "interior": self.interior,
            "boundary_fraction": round(self.boundary_fraction, 4),
            "raw_below_zero": self.raw_below_zero,
            "raw_above_one": self.raw_above_one,
            "workouts_with_reversals": self.reversals,
            "caveat": self.beta_regression_caveat,
        }


def describe(
    workouts: Sequence[WorkoutCashflows], *, basis: LossBasis
) -> LGDDistribution:
    """Summarise realised LGD on one basis, counting boundary masses separately."""
    if not workouts:
        raise LGDError("cannot describe an empty set of workouts")
    clipped = [realised_lgd(w, basis=basis) for w in workouts]
    raw = [realised_lgd(w, basis=basis, clip=False) for w in workouts]
    ordered = sorted(clipped)
    n = len(ordered)
    median = (
        ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2
    )
    return LGDDistribution(
        basis=basis.value,
        count=n,
        mean=sum(clipped) / n,
        median=median,
        at_zero=sum(1 for v in clipped if v == 0.0),
        at_one=sum(1 for v in clipped if v == 1.0),
        interior=sum(1 for v in clipped if 0.0 < v < 1.0),
        raw_below_zero=sum(1 for v in raw if v < 0.0),
        raw_above_one=sum(1 for v in raw if v > 1.0),
        reversals=sum(
            1 for w in workouts
            if min(w.costs, w.proceeds, w.credit_enhancement_proceeds) < 0
        ),
    )


# --------------------------------------------------------------------------
# Special functions the beta likelihood needs
# --------------------------------------------------------------------------


def digamma(x: float) -> float:
    """ψ(x) = d/dx log Γ(x). Recurrence up to 6, then the asymptotic series."""
    if x <= 0 and x == int(x):
        raise LGDError(f"digamma is undefined at the non-positive integer {x}")
    result = 0.0
    while x < 6.0:
        result -= 1.0 / x
        x += 1.0
    inv = 1.0 / x
    inv2 = inv * inv
    return result + math.log(x) - 0.5 * inv - inv2 * (
        1.0 / 12.0 - inv2 * (1.0 / 120.0 - inv2 * (1.0 / 252.0 - inv2 / 240.0))
    )


def trigamma(x: float) -> float:
    """ψ'(x). Same structure — recurrence to 6, then the asymptotic series."""
    if x <= 0 and x == int(x):
        raise LGDError(f"trigamma is undefined at the non-positive integer {x}")
    result = 0.0
    while x < 6.0:
        result += 1.0 / (x * x)
        x += 1.0
    inv = 1.0 / x
    inv2 = inv * inv
    return result + inv * (
        1.0 + 0.5 * inv + inv2 * (
            1.0 / 6.0 - inv2 * (1.0 / 30.0 - inv2 * (1.0 / 42.0 - inv2 / 30.0))
        )
    )


def squeeze(values: Sequence[float]) -> list[float]:
    """Smithson-Verkuilen: move 0 and 1 inside the open interval.

    ``y' = (y·(n-1) + 0.5) / n``. This changes every observation, not only the
    boundary ones, and the amount it changes them shrinks with sample size. It
    is applied here rather than in the caller so that a beta regression cannot
    be fitted to boundary data by forgetting it.
    """
    n = len(values)
    if n == 0:
        raise LGDError("cannot squeeze an empty sample")
    if n == 1:
        raise LGDError(
            "the Smithson-Verkuilen transform is undefined for a single "
            "observation; it needs a sample size to scale by"
        )
    return [(v * (n - 1) + 0.5) / n for v in values]


# --------------------------------------------------------------------------
# Beta regression (Ferrari & Cribari-Neto 2004)
# --------------------------------------------------------------------------


def _logistic(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


@dataclass
class BetaRegression:
    """A fitted beta regression: logit link on the mean, constant precision."""

    features: list[str]
    coefficients: list[float]
    intercept: float
    precision: float
    converged: bool
    iterations: int
    log_likelihood: float
    observations: int
    standard_errors: list[float | None] = field(default_factory=list)

    def predict(self, row: dict) -> float:
        """Expected rate for one observation."""
        z = self.intercept
        for name, beta in zip(self.features, self.coefficients):
            value = row.get(name)
            if value is None or (isinstance(value, float) and math.isnan(value)):
                value = 0.0
            z += beta * float(value)
        return _logistic(z)

    @property
    def promotable(self) -> tuple[bool, str]:
        if not self.converged:
            return False, (
                f"the beta regression did not converge in {self.iterations} "
                "iterations; the coefficients are wherever the last step landed"
            )
        return True, ""

    def to_dict(self) -> dict:
        ok, why = self.promotable
        return {
            "model": "beta_regression",
            "link": "logit",
            "intercept": round(self.intercept, 6),
            "precision_phi": round(self.precision, 6),
            "converged": self.converged,
            "iterations": self.iterations,
            "log_likelihood": round(self.log_likelihood, 6),
            "observations": self.observations,
            "promotable": ok,
            "promotable_blocker": "" if ok else why,
            "coefficients": [
                {
                    "feature": name,
                    "coefficient": round(beta, 6),
                    "standard_error": (
                        round(se, 6) if se is not None else None
                    ),
                }
                for name, beta, se in zip(
                    self.features, self.coefficients,
                    self.standard_errors or [None] * len(self.features),
                )
            ],
        }


def _beta_log_likelihood(y: Sequence[float], mu: Sequence[float], phi: float) -> float:
    total = 0.0
    for yi, mi in zip(y, mu):
        a, b = mi * phi, (1.0 - mi) * phi
        total += (
            math.lgamma(phi) - math.lgamma(a) - math.lgamma(b)
            + (a - 1.0) * math.log(yi) + (b - 1.0) * math.log1p(-yi)
        )
    return total


def fit_beta_regression(
    rows: Sequence[dict],
    targets: Sequence[float],
    features: Sequence[str],
    *,
    max_iterations: int = MAX_ITERATIONS,
    tolerance: float = CONVERGENCE_TOLERANCE,
    apply_squeeze: bool = True,
) -> BetaRegression:
    """Maximum likelihood by Fisher scoring on ``(β, φ)`` jointly.

    ``apply_squeeze`` moves boundary observations inside ``(0, 1)`` — set it
    False only when the caller has already done so and can say what transform
    it used. Fitting on raw boundary values is not an option: the log
    likelihood is ``-inf`` there, and a silent drop of those rows would remove
    every total loss and every full recovery, which are the observations the
    model most needs.
    """
    if len(rows) != len(targets):
        raise LGDError(f"{len(rows)} rows but {len(targets)} targets")
    if len(rows) < 2:
        raise LGDError("beta regression needs at least two observations")

    y = squeeze(list(targets)) if apply_squeeze else list(targets)
    for value in y:
        if not 0.0 < value < 1.0:
            raise LGDError(
                f"target {value} is outside the open interval (0, 1). The beta "
                "likelihood is -inf on the boundary; pass apply_squeeze=True or "
                "transform the targets and say which transform was used."
            )

    p = len(features)
    x = [
        [1.0] + [
            float(row.get(name) or 0.0)
            if not isinstance(row.get(name), bool) else float(row.get(name))
            for name in features
        ]
        for row in rows
    ]
    k = p + 1

    mean_y = sum(y) / len(y)
    var_y = sum((v - mean_y) ** 2 for v in y) / len(y)
    beta = [math.log(mean_y / (1.0 - mean_y))] + [0.0] * p
    phi = max(1.1, mean_y * (1.0 - mean_y) / var_y - 1.0) if var_y > 0 else 2.0

    y_star = [math.log(v / (1.0 - v)) for v in y]
    converged = False
    iterations = 0
    loglik = float("-inf")

    for iterations in range(1, max_iterations + 1):
        eta = [sum(b * v for b, v in zip(beta, xi)) for xi in x]
        mu = [_logistic(z) for z in eta]
        if any(not 1e-12 < m < 1 - 1e-12 for m in mu):
            break

        mu_star = [digamma(m * phi) - digamma((1.0 - m) * phi) for m in mu]
        t = [m * (1.0 - m) for m in mu]
        w = [
            phi * (trigamma(m * phi) + trigamma((1.0 - m) * phi)) * ti * ti
            for m, ti in zip(mu, t)
        ]

        score_beta = [
            phi * sum(
                xi[j] * ti * (ys - ms)
                for xi, ti, ys, ms in zip(x, t, y_star, mu_star)
            )
            for j in range(k)
        ]
        score_phi = sum(
            m * (ys - ms) + math.log1p(-v) - digamma((1.0 - m) * phi) + digamma(phi)
            for m, ys, ms, v in zip(mu, y_star, mu_star, y)
        )

        information = [[0.0] * (k + 1) for _ in range(k + 1)]
        for j in range(k):
            for l in range(k):
                information[j][l] = phi * sum(
                    wi * xi[j] * xi[l] for wi, xi in zip(w, x)
                )
        c = [
            phi * (trigamma(m * phi) * m - trigamma((1.0 - m) * phi) * (1.0 - m)) * ti
            for m, ti in zip(mu, t)
        ]
        for j in range(k):
            value = sum(ci * xi[j] for ci, xi in zip(c, x))
            information[j][k] = value
            information[k][j] = value
        information[k][k] = sum(
            m * m * trigamma(m * phi)
            + (1.0 - m) * (1.0 - m) * trigamma((1.0 - m) * phi)
            - trigamma(phi)
            for m in mu
        )

        try:
            step = solve(information, score_beta + [score_phi])
        except SingularMatrix as exc:
            raise LGDError(
                f"the beta-regression information matrix is singular at iteration "
                f"{iterations}: {exc}"
            ) from exc

        candidate_beta = [b + s for b, s in zip(beta, step[:k])]
        candidate_phi = phi + step[k]
        halvings = 0
        while candidate_phi <= 0.01 and halvings < 40:
            step = [s / 2.0 for s in step]
            candidate_beta = [b + s for b, s in zip(beta, step[:k])]
            candidate_phi = phi + step[k]
            halvings += 1

        delta = max(abs(s) for s in step)
        beta, phi = candidate_beta, max(candidate_phi, 0.01)
        if delta < tolerance:
            converged = True
            break

    eta = [sum(b * v for b, v in zip(beta, xi)) for xi in x]
    mu = [_logistic(z) for z in eta]
    loglik = _beta_log_likelihood(y, mu, phi)

    errors: list[float | None] = [None] * p
    try:
        covariance = invert(information)
        errors = [
            math.sqrt(covariance[j][j]) if covariance[j][j] > 0 else None
            for j in range(1, k)
        ]
    except (SingularMatrix, NameError, UnboundLocalError):
        pass

    return BetaRegression(
        features=list(features),
        coefficients=beta[1:],
        intercept=beta[0],
        precision=phi,
        converged=converged,
        iterations=iterations,
        log_likelihood=loglik,
        observations=len(y),
        standard_errors=errors,
    )


# --------------------------------------------------------------------------
# The two-stage model
# --------------------------------------------------------------------------


@dataclass
class TwoStageLGD:
    """Cure probability × recovery rate, per SRS §7.3.3.

    Stage one is deliberately absent, not stubbed. LH-309 owns the cure
    definition, and without it there is no way to say which defaults belong in
    stage two — so :meth:`expected_lgd` raises rather than quietly assuming
    every default is a loss.
    """

    recovery: BetaRegression
    cure_definition: object = CURE_DEFINITION
    cure_model: object = None

    @property
    def promotable(self) -> tuple[bool, str]:
        if isinstance(self.cure_definition, Pending):
            return False, (
                f"stage 1 (cure) is not buildable: {self.cure_definition}. "
                "SRS §7.3.3 makes cure probability the first stage, and Appendix A "
                "defines default but not cure."
            )
        ok, why = self.recovery.promotable
        return (False, f"stage 2 (recovery): {why}") if not ok else (True, "")

    def loss_given_no_cure(self, row: dict) -> float:
        """Stage two alone — E[LGD | not cured]. **`[DATA]`**, computable now."""
        return self.recovery.predict(row)

    def expected_lgd(self, row: dict) -> float:
        """Full two-stage LGD. Raises until LH-309 lands."""
        if isinstance(self.cure_definition, Pending) or self.cure_model is None:
            raise Ungrounded(
                f"expected LGD needs stage 1: {self.cure_definition}. "
                "loss_given_no_cure() gives the stage-2 figure, which is a "
                "different quantity — using it as LGD assumes no account ever "
                "cures, and that overstates the loss on every secured product."
            )
        cure_probability = self.cure_model.predict(row)
        return (1.0 - cure_probability) * self.loss_given_no_cure(row)

    def to_dict(self) -> dict:
        ok, why = self.promotable
        return {
            "model": "two_stage_lgd",
            "stage_1_cure": (
                str(self.cure_definition)
                if isinstance(self.cure_definition, Pending) else "supplied"
            ),
            "stage_2_recovery": self.recovery.to_dict(),
            "promotable": ok,
            "promotable_blocker": "" if ok else why,
        }

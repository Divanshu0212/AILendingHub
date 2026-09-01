"""Macro conditioning — Wilson-style segment default-rate regressions (Step 8).

SRS §7.3.4 and Phase 3 WS-3.1 Step 8 ask for segment default rates regressed on
macro factors so that PD can be shifted under a scenario. The formulation is
Wilson's: regress a *transform* of the segment default rate on macro factors,
because a default rate is bounded in [0, 1] and a linear model on the raw rate
will happily predict a negative one under a benign scenario and above 1 under a
severe one — which is exactly the range a stress test lives in.

    ``logit(default_rate_t) = a + b'x_t + e_t``

The regression is `[DATA]`. **The scenarios it is evaluated at are not.**
:meth:`MacroModel.shift` will apply any factor path a caller hands it;
:func:`apply_scenario` is the path that publishes a stressed PD, and it raises
until LH-304 supplies the ratified scenario set. A scenario invented to make a
widget render becomes the bank's stress test.

What this does not port
-----------------------
No dynamic factor model, no VAR on the macro factors themselves, and no
autocorrelation correction. Segment default rates are serially correlated, so
the ordinary standard errors here are too small — :attr:`MacroModel.caveat`
says so rather than leaving it to the reader, and a Track B implementation
should use Newey-West.

Reference: Wilson, "Portfolio Credit Risk", *FRBNY Economic Policy Review*,
October 1998.

Workstream: WS-3.1 Step 8 (SRS §7.3.4)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

from lending_hub.definitions.provenance import Pending, Ungrounded
from lending_hub.portfolio.linalg import SingularMatrix, invert, solve

#: The ratified macro scenario set (Phase 3 §8).
MACRO_SCENARIOS = Pending(
    owner="ICAAP / ALCO",
    ticket="LH-304",
    note="baseline / adverse / severely adverse factor paths and their horizons",
)

#: Rates are clamped away from the boundary before the logit. Stated because it
#: changes the fitted coefficients on a segment that ever hits 0% or 100%.
RATE_FLOOR = 1e-6


class MacroError(Exception):
    """The macro model cannot be fitted or applied as asked."""


def logit(p: float) -> float:
    p = min(1.0 - RATE_FLOOR, max(RATE_FLOOR, p))
    return math.log(p / (1.0 - p))


def expit(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


@dataclass(frozen=True)
class Observation:
    """One segment-period: the realised default rate and the macro factors."""

    period: str
    default_rate: float
    factors: dict

    def __post_init__(self) -> None:
        if not 0.0 <= self.default_rate <= 1.0:
            raise MacroError(
                f"{self.period}: default rate {self.default_rate} is outside [0, 1]"
            )


@dataclass
class MacroModel:
    """A fitted Wilson-style regression for one segment."""

    segment: str
    factors: list[str]
    intercept: float
    coefficients: list[float]
    standard_errors: list[float | None]
    observations: int
    r_squared: float
    residual_autocorrelation: float

    @property
    def caveat(self) -> str:
        if abs(self.residual_autocorrelation) > 0.3:
            return (
                f"residual autocorrelation is {self.residual_autocorrelation:+.2f}. "
                "The standard errors above assume independent errors and are "
                "therefore too small; treat the coefficients as point estimates "
                "and the intervals as unusable until refitted with a "
                "heteroskedasticity- and autocorrelation-consistent covariance."
            )
        return ""

    def predicted_rate(self, factors: dict) -> float:
        z = self.intercept
        for name, beta in zip(self.factors, self.coefficients):
            value = factors.get(name)
            if value is None:
                raise MacroError(
                    f"factor {name!r} is missing from the supplied path; a macro "
                    "model cannot substitute a zero for an unobserved factor"
                )
            z += beta * float(value)
        return expit(z)

    def shift(self, base_rate: float, factors: dict, baseline_factors: dict) -> float:
        """Move ``base_rate`` by the model's predicted change between two paths.

        Applied as a shift in log-odds rather than a multiplier on the rate, so
        the result stays a probability at both ends of a severe scenario.
        """
        delta = (
            logit(self.predicted_rate(factors))
            - logit(self.predicted_rate(baseline_factors))
        )
        return expit(logit(base_rate) + delta)

    def to_dict(self) -> dict:
        return {
            "model": "wilson_segment_default_rate",
            "segment": self.segment,
            "link": "logit",
            "intercept": round(self.intercept, 6),
            "observations": self.observations,
            "r_squared": round(self.r_squared, 6),
            "residual_autocorrelation": round(self.residual_autocorrelation, 4),
            "caveat": self.caveat,
            "factors": [
                {
                    "factor": name,
                    "coefficient": round(beta, 6),
                    "standard_error": round(se, 6) if se is not None else None,
                }
                for name, beta, se in zip(
                    self.factors, self.coefficients, self.standard_errors)
            ],
        }


def fit_macro(
    observations: Sequence[Observation],
    factors: Sequence[str],
    *,
    segment: str = "",
) -> MacroModel:
    """Ordinary least squares of ``logit(default rate)`` on the macro factors."""
    n = len(observations)
    p = len(factors)
    if p == 0:
        raise MacroError("a macro model needs at least one factor")
    if n <= p + 1:
        raise MacroError(
            f"{n} observations for {p} factors plus an intercept. A regression "
            "with no residual degrees of freedom fits perfectly and means nothing."
        )

    x = [[1.0] + [float(o.factors[f]) for f in factors] for o in observations]
    y = [logit(o.default_rate) for o in observations]
    k = p + 1

    xtx = [[sum(row[i] * row[j] for row in x) for j in range(k)] for i in range(k)]
    xty = [sum(row[i] * yi for row, yi in zip(x, y)) for i in range(k)]
    try:
        beta = solve(xtx, xty)
    except SingularMatrix as exc:
        raise MacroError(
            f"the macro factors are collinear: {exc}. Macro series usually are — "
            "drop one rather than regularising, because a coefficient split "
            "across two near-identical factors cannot be read as an elasticity."
        ) from exc

    fitted = [sum(b * v for b, v in zip(beta, row)) for row in x]
    residuals = [yi - fi for yi, fi in zip(y, fitted)]
    mean_y = sum(y) / n
    ss_total = sum((yi - mean_y) ** 2 for yi in y)
    ss_residual = sum(r * r for r in residuals)
    r_squared = 1.0 - ss_residual / ss_total if ss_total > 0 else 0.0

    errors: list[float | None] = [None] * p
    dof = n - k
    if dof > 0 and ss_residual > 0:
        sigma2 = ss_residual / dof
        try:
            covariance = invert(xtx)
            errors = [
                math.sqrt(sigma2 * covariance[j][j])
                if covariance[j][j] > 0 else None
                for j in range(1, k)
            ]
        except SingularMatrix:
            pass

    return MacroModel(
        segment=segment,
        factors=list(factors),
        intercept=beta[0],
        coefficients=beta[1:],
        standard_errors=errors,
        observations=n,
        r_squared=r_squared,
        residual_autocorrelation=_lag_one_autocorrelation(residuals),
    )


def _lag_one_autocorrelation(residuals: Sequence[float]) -> float:
    n = len(residuals)
    if n < 3:
        return 0.0
    mean = sum(residuals) / n
    numerator = sum(
        (residuals[i] - mean) * (residuals[i - 1] - mean) for i in range(1, n))
    denominator = sum((r - mean) ** 2 for r in residuals)
    return numerator / denominator if denominator > 0 else 0.0


def apply_scenario(
    model: MacroModel,
    base_rate: float,
    scenario_name: str,
    *,
    scenarios=MACRO_SCENARIOS,
) -> float:
    """Stress ``base_rate`` under a named ratified scenario. Raises until LH-304.

    :meth:`MacroModel.shift` will apply any factor path a caller constructs —
    that is what makes sensitivity analysis possible. This is the path that
    publishes a stressed number, and it is gated, because the difference between
    "we explored a shock" and "this is the bank's adverse scenario" is entirely
    whether a committee ratified the path.
    """
    if isinstance(scenarios, Pending):
        raise Ungrounded(
            f"scenario {scenario_name!r} cannot be applied: {scenarios}. "
            "Phase 3 §8 puts macro scenarios on the do-not-invent list. Use "
            "MacroModel.shift() with an explicit factor path for sensitivity "
            "work, and label the result a sensitivity rather than a scenario."
        )
    path = scenarios.get(scenario_name)
    if path is None:
        raise MacroError(
            f"scenario {scenario_name!r} is not in the ratified set "
            f"{sorted(scenarios)}"
        )
    baseline = scenarios.get("baseline")
    if baseline is None:
        raise MacroError(
            "the ratified scenario set has no 'baseline' path to shift against; "
            "a stressed rate is a difference, not a level"
        )
    return model.shift(base_rate, path, baseline)

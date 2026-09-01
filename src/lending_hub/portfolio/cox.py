"""Cox proportional hazards with time-varying covariates (WS-3.1 Step 2).

Phase 3 builds this *before* the challenger and names it "the interpretable
reference every survival challenger must beat, and the model auditors will read
first". Ports `scikit-survival
<https://github.com/sebp/scikit-survival>`_'s ``CoxPHSurvivalAnalysis``:
partial likelihood maximised by Newton-Raphson, with the counting-process
``(start, stop]`` formulation that lets each account-month carry its own
covariate values.

Tie handling is not a detail here
---------------------------------
Cox's partial likelihood was derived for continuous time, where exact ties have
probability zero. This panel is *monthly*, so every event time carries hundreds
of ties, and the approximation chosen for them changes the coefficients rather
than the sixth decimal. Breslow — scikit-survival's default — biases
coefficients toward zero as ties get heavier; Efron is markedly more accurate
at the same cost class. Both are implemented and :attr:`CoxModel.ties` records
which produced the fit, because a hazard ratio quoted without it is not
reproducible.

This is also the concrete argument for the phase's own ordering: with tie
fractions this high, Cox is the *reference* and the discrete-time hazard model
(``portfolio.hazard``) is the production form, because discrete time models the
month directly instead of approximating around it.

What this does not port
-----------------------
* No penalised (ridge/lasso) Cox — collinearity surfaces as
  :class:`~lending_hub.portfolio.linalg.SingularMatrix` and is a modelling
  decision, not something to regularise away silently.
* No stratified baseline hazard, no frailty terms, no robust sandwich variance.
* No formal proportional-hazards test. :func:`schoenfeld_trend` reports the
  scaled-residual trend that such a test is built on, and says plainly that it
  is a diagnostic rather than a p-value.

Reference: Cox, "Regression models and life-tables", *JRSS-B* 34(2), 1972;
Efron, *JASA* 72(359), 1977.

Workstream: WS-3.1 Step 2 (SRS §7.3.2a)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from lending_hub.portfolio.linalg import SingularMatrix, invert, solve
from lending_hub.portfolio.panel import HazardRow
from lending_hub.portfolio.survival import StepFunction

MAX_ITERATIONS = 50
CONVERGENCE_TOLERANCE = 1e-7
MAX_STEP_HALVINGS = 20


class CoxError(Exception):
    """The model cannot be fitted or read as asked."""


@dataclass(frozen=True)
class Interval:
    """A counting-process row: at risk over ``(start, stop]``.

    One account contributes many intervals, one per month, each carrying that
    month's covariates. This is what makes time-varying covariates work without
    any special handling in the likelihood: the risk set at an event time picks
    up whichever interval was live then.
    """

    start: int
    stop: int
    event: bool
    covariates: Sequence[float]

    def __post_init__(self) -> None:
        if self.stop <= self.start:
            raise CoxError(
                f"interval ({self.start}, {self.stop}] is empty or reversed; an "
                "account cannot be at risk over zero time"
            )


def intervals_from_hazard_rows(
    rows: Iterable[HazardRow],
    features: Sequence[str],
) -> list[Interval]:
    """Adapt ``portfolio.panel`` risk-set rows to counting-process intervals.

    Each account-month becomes ``(m, m+1]`` on the months-on-book axis. Only
    :attr:`~lending_hub.portfolio.panel.Event.DEFAULT` counts as the event —
    a prepayment ends the interval without one, which is precisely the
    censoring Cox assumes. That assumption is wrong on this data and the
    competing-risks model exists to say so; Cox is still the reference the
    phase file asks for, and this function does not quietly patch it.
    """
    out: list[Interval] = []
    for row in rows:
        values = []
        for name in features:
            v = row.features.get(name)
            if v is None or (isinstance(v, float) and math.isnan(v)):
                v = 0.0
            values.append(float(v))
        out.append(Interval(
            start=row.months_on_book,
            stop=row.months_on_book + 1,
            event=row.defaulted == 1,
            covariates=values,
        ))
    return out


@dataclass
class Coefficient:
    name: str
    beta: float
    standard_error: float | None

    @property
    def hazard_ratio(self) -> float:
        return math.exp(self.beta)

    @property
    def z(self) -> float | None:
        if not self.standard_error:
            return None
        return self.beta / self.standard_error

    def confidence_interval(self, z: float = 1.96) -> tuple[float, float] | None:
        """Hazard-ratio interval. ``z`` is the caller's confidence choice."""
        if self.standard_error is None:
            return None
        lo = math.exp(self.beta - z * self.standard_error)
        hi = math.exp(self.beta + z * self.standard_error)
        return lo, hi

    def to_dict(self) -> dict:
        ci = self.confidence_interval()
        return {
            "feature": self.name,
            "coefficient": round(self.beta, 6),
            "hazard_ratio": round(self.hazard_ratio, 6),
            "standard_error": (
                round(self.standard_error, 6) if self.standard_error is not None else None
            ),
            "z": round(self.z, 4) if self.z is not None else None,
            "hazard_ratio_ci95": [round(ci[0], 6), round(ci[1], 6)] if ci else None,
        }


@dataclass
class CoxModel:
    """A fitted Cox model, with everything an auditor reads in one object."""

    features: list[str]
    coefficients: list[Coefficient]
    ties: str
    converged: bool
    iterations: int
    log_likelihood: float
    events: int
    intervals: int
    tie_fraction: float
    baseline_cumulative_hazard: StepFunction = field(default_factory=StepFunction)
    _centre: list[float] = field(default_factory=list)
    _scale: list[float] = field(default_factory=list)

    @property
    def promotable(self) -> tuple[bool, str]:
        """Whether this fit may be promoted, and why not when it may not.

        A non-converged Cox fit still returns coefficients — Newton-Raphson
        stops at whatever it reached — and they look exactly like converged
        ones on a slide.
        """
        if not self.converged:
            return False, (
                f"Newton-Raphson did not converge in {self.iterations} iterations. "
                "The coefficients are wherever the last step landed."
            )
        if self.events == 0:
            return False, "no events in the fitting sample"
        if self.ties == "breslow" and self.tie_fraction > 0.5:
            return False, (
                f"{self.tie_fraction:.0%} of events share an event time and the "
                "Breslow approximation was used; refit with ties='efron' before "
                "quoting these hazard ratios"
            )
        return True, ""

    def linear_predictor(self, covariates: Sequence[float]) -> float:
        total = 0.0
        for value, beta, centre, scale in zip(
            covariates, (c.beta for c in self.coefficients), self._centre, self._scale
        ):
            total += beta * (value - centre) / scale if scale else 0.0
        return total

    def risk(self, covariates: Sequence[float]) -> float:
        """``exp(β'x)`` — the relative hazard multiplier."""
        return math.exp(self.linear_predictor(covariates))

    def survival(self, covariates: Sequence[float], t: float) -> float:
        """S(t | x) = exp(-H₀(t) · exp(β'x)), with H₀ from Breslow."""
        h0 = self.baseline_cumulative_hazard.at(t)
        return math.exp(-h0 * self.risk(covariates))

    def summary(self) -> dict:
        ok, why = self.promotable
        return {
            "model": "cox_proportional_hazards",
            "ties": self.ties,
            "converged": self.converged,
            "iterations": self.iterations,
            "log_likelihood": round(self.log_likelihood, 6),
            "intervals": self.intervals,
            "events": self.events,
            "tie_fraction": round(self.tie_fraction, 4),
            "promotable": ok,
            "promotable_blocker": why,
            "coefficients": [c.to_dict() for c in self.coefficients],
        }


def _standardise(intervals: Sequence[Interval], p: int) -> tuple[list[float], list[float]]:
    """Centre and scale each covariate.

    Newton-Raphson on raw credit scores (~700) beside LTV (~80) and a 0/1 flag
    is badly conditioned, and the failure mode is a singular Hessian rather than
    a wrong answer — which at least is loud. Coefficients are returned on the
    original scale, so nothing downstream sees the standardisation.
    """
    n = len(intervals)
    centre = [0.0] * p
    scale = [1.0] * p
    for j in range(p):
        column = [iv.covariates[j] for iv in intervals]
        mean = sum(column) / n
        variance = sum((v - mean) ** 2 for v in column) / n
        sd = math.sqrt(variance)
        centre[j] = mean
        scale[j] = sd if sd > 1e-12 else 1.0
    return centre, scale


def _risk_sets(intervals: Sequence[Interval]) -> list[tuple[int, list[int], list[int]]]:
    """``(time, risk-set indices, event indices)`` for each distinct event time."""
    event_times = sorted({iv.stop for iv in intervals if iv.event})
    out = []
    for t in event_times:
        risk = [i for i, iv in enumerate(intervals) if iv.start < t <= iv.stop]
        events = [i for i, iv in enumerate(intervals) if iv.event and iv.stop == t]
        out.append((t, risk, events))
    return out


def _log_likelihood_and_derivatives(
    beta: list[float],
    x: list[list[float]],
    risk_sets,
    ties: str,
):
    p = len(beta)
    loglik = 0.0
    gradient = [0.0] * p
    information = [[0.0] * p for _ in range(p)]

    for _t, risk, events in risk_sets:
        d = len(events)
        if d == 0 or not risk:
            continue

        weights = {i: math.exp(sum(b * v for b, v in zip(beta, x[i]))) for i in risk}

        s0 = sum(weights[i] for i in risk)
        s1 = [sum(weights[i] * x[i][j] for i in risk) for j in range(p)]
        s2 = [
            [sum(weights[i] * x[i][j] * x[i][k] for i in risk) for k in range(p)]
            for j in range(p)
        ]

        for i in events:
            loglik += sum(b * v for b, v in zip(beta, x[i]))
            for j in range(p):
                gradient[j] += x[i][j]

        if ties == "efron" and d > 1:
            d0 = sum(weights[i] for i in events)
            d1 = [sum(weights[i] * x[i][j] for i in events) for j in range(p)]
            d2 = [
                [sum(weights[i] * x[i][j] * x[i][k] for i in events) for k in range(p)]
                for j in range(p)
            ]
            for l in range(d):
                frac = l / d
                a0 = s0 - frac * d0
                if a0 <= 0:
                    raise CoxError(
                        "the Efron denominator went non-positive; the risk set is "
                        "degenerate at an event time"
                    )
                a1 = [s1[j] - frac * d1[j] for j in range(p)]
                loglik -= math.log(a0)
                for j in range(p):
                    gradient[j] -= a1[j] / a0
                    for k in range(p):
                        a2jk = s2[j][k] - frac * d2[j][k]
                        information[j][k] += a2jk / a0 - (a1[j] * a1[k]) / (a0 * a0)
        else:
            loglik -= d * math.log(s0)
            mean = [s1[j] / s0 for j in range(p)]
            for j in range(p):
                gradient[j] -= d * mean[j]
                for k in range(p):
                    information[j][k] += d * (s2[j][k] / s0 - mean[j] * mean[k])

    return loglik, gradient, information


def fit_cox(
    intervals: Sequence[Interval],
    features: Sequence[str],
    *,
    ties: str = "efron",
    max_iterations: int = MAX_ITERATIONS,
    tolerance: float = CONVERGENCE_TOLERANCE,
) -> CoxModel:
    """Maximise the partial likelihood by Newton-Raphson with step halving.

    ``ties`` defaults to ``"efron"`` rather than scikit-survival's ``"breslow"``
    because this panel is monthly: the tie fraction is near 1, which is exactly
    where Breslow's downward bias bites. :attr:`CoxModel.promotable` refuses a
    heavily-tied Breslow fit for the same reason.
    """
    if ties not in ("efron", "breslow"):
        raise CoxError(f"unknown tie handling {ties!r}; use 'efron' or 'breslow'")
    if not intervals:
        raise CoxError("cannot fit a Cox model with no intervals")
    p = len(features)
    if p == 0:
        raise CoxError("cannot fit a Cox model with no covariates")
    if any(len(iv.covariates) != p for iv in intervals):
        raise CoxError(
            f"every interval must carry {p} covariates, one per named feature"
        )

    centre, scale = _standardise(intervals, p)
    x = [
        [(iv.covariates[j] - centre[j]) / scale[j] for j in range(p)]
        for iv in intervals
    ]
    risk_sets = _risk_sets(intervals)
    n_events = sum(1 for iv in intervals if iv.event)
    if n_events == 0:
        raise CoxError(
            "no events in the sample; a partial likelihood with no events is "
            "constant and every coefficient is arbitrary"
        )
    distinct = len(risk_sets)
    tie_fraction = 1.0 - distinct / n_events if n_events else 0.0

    beta = [0.0] * p
    loglik, gradient, information = _log_likelihood_and_derivatives(
        beta, x, risk_sets, ties)
    converged = False
    iterations = 0

    for iterations in range(1, max_iterations + 1):
        try:
            step = solve(information, gradient)
        except SingularMatrix as exc:
            raise CoxError(
                f"the information matrix is singular at iteration {iterations}: "
                f"{exc}"
            ) from exc

        halvings = 0
        while True:
            candidate = [b + s for b, s in zip(beta, step)]
            try:
                new_ll, new_g, new_i = _log_likelihood_and_derivatives(
                    candidate, x, risk_sets, ties)
            except (OverflowError, ValueError, CoxError):
                new_ll = float("-inf")
                new_g, new_i = gradient, information
            if new_ll >= loglik or halvings >= MAX_STEP_HALVINGS:
                break
            step = [s / 2.0 for s in step]
            halvings += 1

        delta = max(abs(s) for s in step)
        beta, loglik, gradient, information = candidate, new_ll, new_g, new_i
        if delta < tolerance:
            converged = True
            break

    try:
        covariance = invert(information)
        errors = [
            math.sqrt(covariance[j][j]) if covariance[j][j] > 0 else None
            for j in range(p)
        ]
    except SingularMatrix:
        errors = [None] * p

    coefficients = [
        Coefficient(
            name=features[j],
            beta=beta[j] / scale[j],
            standard_error=errors[j] / scale[j] if errors[j] is not None else None,
        )
        for j in range(p)
    ]

    model = CoxModel(
        features=list(features),
        coefficients=coefficients,
        ties=ties,
        converged=converged,
        iterations=iterations,
        log_likelihood=loglik,
        events=n_events,
        intervals=len(intervals),
        tie_fraction=tie_fraction,
        _centre=centre,
        _scale=scale,
    )
    model.baseline_cumulative_hazard = _breslow_baseline(model, intervals, x, beta, risk_sets)
    return model


def _breslow_baseline(model, intervals, x, beta, risk_sets) -> StepFunction:
    """Breslow's estimator of the cumulative baseline hazard H₀(t)."""
    out = StepFunction()
    cumulative = 0.0
    for t, risk, events in risk_sets:
        denominator = sum(
            math.exp(sum(b * v for b, v in zip(beta, x[i]))) for i in risk
        )
        if denominator > 0:
            cumulative += len(events) / denominator
        out.times.append(t)
        out.values.append(cumulative)
    return out


def schoenfeld_trend(
    model: CoxModel,
    intervals: Sequence[Interval],
) -> list[tuple[str, float]]:
    """Correlation of each covariate's Schoenfeld residual with event time.

    A diagnostic, **not** a test. Proportional hazards says the effect of a
    covariate does not drift with time; a residual that trends with time is the
    signature of a violation. A correlation near zero is weak evidence of
    nothing in particular, and this deliberately returns no p-value: a
    significance figure here would be read as a pass mark, and the honest
    reading is "look at this covariate's effect over time before quoting one
    hazard ratio for it".
    """
    p = len(model.features)
    x = [
        [(iv.covariates[j] - model._centre[j]) / model._scale[j] for j in range(p)]
        for iv in intervals
    ]
    beta = [c.beta * model._scale[j] for j, c in enumerate(model.coefficients)]
    risk_sets = _risk_sets(intervals)

    times: list[float] = []
    residuals: list[list[float]] = []
    for t, risk, events in risk_sets:
        if not risk:
            continue
        weights = {i: math.exp(sum(b * v for b, v in zip(beta, x[i]))) for i in risk}
        s0 = sum(weights.values())
        if s0 <= 0:
            continue
        expected = [sum(weights[i] * x[i][j] for i in risk) / s0 for j in range(p)]
        for i in events:
            times.append(float(t))
            residuals.append([x[i][j] - expected[j] for j in range(p)])

    if len(times) < 3:
        return [(name, 0.0) for name in model.features]

    mean_t = sum(times) / len(times)
    var_t = sum((t - mean_t) ** 2 for t in times)

    out = []
    for j, name in enumerate(model.features):
        column = [r[j] for r in residuals]
        mean_r = sum(column) / len(column)
        var_r = sum((v - mean_r) ** 2 for v in column)
        if var_t <= 0 or var_r <= 0:
            out.append((name, 0.0))
            continue
        covariance = sum(
            (t - mean_t) * (v - mean_r) for t, v in zip(times, column)
        )
        out.append((name, covariance / math.sqrt(var_t * var_r)))
    return out

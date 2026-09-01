"""Seasonal-Hybrid ESD on operational metrics (WS-3.2 Step 5).

SRS §9.3.4 asks for anomaly detection on application volumes per channel,
approval rates and alert rates, "so that pipeline breaks or agent-level
manipulation (a DSA suddenly at 100% approval) surface without anyone writing a
bespoke alert". That last clause is the requirement: the value is in *not*
having to enumerate the failure modes in advance.

Three parts, per Hochenbaum, Vallis & Kejariwal (2017):

* **Seasonal** — operational series have a weekly shape. Monday is not an
  anomaly. The seasonal component is removed before testing.
* **Hybrid** — the residual is standardised by **median and MAD**, not mean and
  standard deviation. This is the part that makes it work: a large anomaly
  inflates the standard deviation enough to hide itself, and the failure is
  worst exactly when the anomaly is biggest.
* **ESD** — Rosner's generalized extreme studentized deviate test, which finds
  up to ``k`` anomalies while controlling the false-positive rate, rather than
  flagging everything past a fixed z.

What this does not port
-----------------------
* **STL** is replaced by a seasonal-median decomposition: the seasonal
  component of each position in the period is the median of that position's
  observations. Two consequences, both measured rather than asserted:

  - *No trend term.* A trend leaks into the residual and inflates the anomaly
    count. :attr:`AnomalyReport.trend_warning` fires when the series median
    moves by more than two robust sigma between its halves.
  - *The seasonal component is estimated from the data it is subtracted from,
    with only ``n / period`` observations per position.* Each position's median
    carries its own error, so the residuals are a mixture of slightly shifted
    normals — which has fatter tails than the single normal that MAD estimates
    the spread of, and the test is therefore liberal. On a clean sinusoidal
    weekly series of 84 points (12 periods) at ``alpha=0.05`` this produces
    three false positives where under one is expected. STL's smoothing and
    robustness iterations are what fix it. :attr:`AnomalyReport.periods_observed`
    reports how many periods the estimate rests on, because the effect shrinks
    with that number and a reader cannot judge the result without it.

* **piecewise median** for long series is not implemented — the paper uses it
  beyond about two periods of data to stop a slow trend swamping the test.

Reference: Hochenbaum, Vallis & Kejariwal, "Automatic Anomaly Detection in the
Cloud Via Statistical Learning", arXiv:1704.07706, 2017; Rosner,
*Technometrics* 25(2), 1983.

Workstream: WS-3.2 Step 5 (SRS §9.3.4)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

#: The MAD-to-sigma factor for a normal distribution: ``1 / Phi^-1(0.75)``.
#: A constant of the method, not a tuning parameter.
MAD_TO_SIGMA = 1.4826


class AnomalyError(Exception):
    """The series cannot be tested as asked."""


# --------------------------------------------------------------------------
# Student-t quantile, for the ESD critical values
# --------------------------------------------------------------------------


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (Lentz's method)."""
    tiny = 1e-30
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, 201):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3e-16:
            break
    return h


def incomplete_beta(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta ``I_x(a, b)``."""
    if not 0.0 <= x <= 1.0:
        raise AnomalyError(f"incomplete beta needs x in [0, 1], got {x}")
    if x in (0.0, 1.0):
        return x
    front = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + a * math.log(x) + b * math.log1p(-x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def student_t_cdf(t: float, df: float) -> float:
    """CDF of Student's t with ``df`` degrees of freedom."""
    if df <= 0:
        raise AnomalyError("degrees of freedom must be positive")
    x = df / (df + t * t)
    tail = 0.5 * incomplete_beta(df / 2.0, 0.5, x)
    return 1.0 - tail if t > 0 else tail


def student_t_quantile(p: float, df: float) -> float:
    """Inverse CDF of Student's t, by bisection on :func:`student_t_cdf`.

    Bisection rather than a closed-form approximation: the ESD critical values
    are computed a handful of times per series, so exactness is free, and an
    approximation that is good to two decimals in the tail is not good enough
    for a test whose whole job is the tail.
    """
    if not 0.0 < p < 1.0:
        raise AnomalyError(f"quantile needs p in (0, 1), got {p}")
    lo, hi = -1e4, 1e4
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if student_t_cdf(mid, df) < p:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-12:
            break
    return (lo + hi) / 2.0


# --------------------------------------------------------------------------
# Seasonal decomposition and the ESD test
# --------------------------------------------------------------------------


def median(values: Sequence[float]) -> float:
    if not values:
        raise AnomalyError("median of an empty sample")
    ordered = sorted(values)
    n = len(ordered)
    return ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2.0


def mad(values: Sequence[float], centre: float | None = None) -> float:
    """Median absolute deviation."""
    if not values:
        raise AnomalyError("MAD of an empty sample")
    c = median(values) if centre is None else centre
    return median([abs(v - c) for v in values])


def local_scale(values: Sequence[float]) -> float:
    """Robust noise scale from successive differences.

    ``MAD(diff(x)) * MAD_TO_SIGMA / sqrt(2)``. Differencing removes any smooth
    trend, so this estimates the *local* noise a series carries rather than its
    total spread. That distinction is the whole point: on a trending series the
    ordinary MAD is dominated by the trend, so a trend test scaled by it is
    silent exactly when it is needed — the trend inflates its own yardstick.
    """
    if len(values) < 2:
        raise AnomalyError("the local scale needs at least two observations")
    differences = [b - a for a, b in zip(values, values[1:])]
    return mad(differences) * MAD_TO_SIGMA / math.sqrt(2.0)


def seasonal_component(values: Sequence[float], period: int) -> list[float]:
    """Median of each position within the period, repeated over the series."""
    if period < 1:
        raise AnomalyError("period must be at least 1")
    if len(values) < 2 * period:
        raise AnomalyError(
            f"need at least two full periods ({2 * period} points) to estimate a "
            f"seasonal component; got {len(values)}"
        )
    positions: list[list[float]] = [[] for _ in range(period)]
    for i, value in enumerate(values):
        positions[i % period].append(value)
    medians = [median(bucket) for bucket in positions]
    overall = median(medians)
    centred = [m - overall for m in medians]
    return [centred[i % period] for i in range(len(values))]


@dataclass
class Anomaly:
    index: int
    value: float
    residual: float
    score: float
    critical_value: float
    direction: str

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "value": round(self.value, 6),
            "residual": round(self.residual, 6),
            "test_statistic": round(self.score, 6),
            "critical_value": round(self.critical_value, 6),
            "direction": self.direction,
        }


@dataclass
class AnomalyReport:
    anomalies: list[Anomaly] = field(default_factory=list)
    tested: int = 0
    period: int = 1
    max_anomalies: int = 0
    trend_warning: str = ""
    periods_observed: int = 0
    """Complete periods behind the seasonal estimate. The test is liberal when
    this is small — see the module docstring — and a reader cannot calibrate
    the anomaly count without it."""

    @property
    def indices(self) -> list[int]:
        return [a.index for a in self.anomalies]

    def to_dict(self) -> dict:
        return {
            "observations": self.tested,
            "seasonal_period": self.period,
            "max_anomalies_tested": self.max_anomalies,
            "periods_observed": self.periods_observed,
            "anomalies_found": len(self.anomalies),
            "anomalies": [a.to_dict() for a in self.anomalies],
            "trend_warning": self.trend_warning,
        }


def detect(
    values: Sequence[float],
    *,
    period: int,
    alpha: float,
    max_fraction: float,
) -> AnomalyReport:
    """Seasonal-Hybrid ESD.

    ``alpha`` is the test level and ``max_fraction`` caps how much of the series
    may be declared anomalous — both are required, because they are the whole
    tuning surface and a dashboard alarm rate is an operational decision
    (LH-307). The paper caps the fraction because ESD needs an upper bound on
    the anomaly count, and an uncapped run on a broken feed declares half the
    series anomalous, which is true and useless.
    """
    n = len(values)
    if n < 2 * period:
        raise AnomalyError(
            f"need at least two full periods ({2 * period} points), got {n}"
        )
    if not 0.0 < alpha < 1.0:
        raise AnomalyError(f"alpha must be in (0, 1), got {alpha}")
    if not 0.0 < max_fraction < 0.5:
        raise AnomalyError(
            f"max_fraction must be in (0, 0.5), got {max_fraction}. Above a half "
            "the 'anomalies' are the series."
        )

    seasonal = seasonal_component(values, period)
    baseline = median(values)
    residuals = [v - s - baseline for v, s in zip(values, seasonal)]

    k = max(1, int(n * max_fraction))
    remaining = list(range(n))
    working = list(residuals)
    candidates: list[tuple[int, float, float, float]] = []

    for i in range(1, k + 1):
        current = [working[j] for j in remaining]
        if len(current) < 3:
            break
        centre = median(current)
        spread = mad(current, centre) * MAD_TO_SIGMA
        if spread <= 0:
            break
        worst = max(remaining, key=lambda j: abs(working[j] - centre))
        statistic = abs(working[worst] - centre) / spread

        size = len(current)
        df = size - 2
        if df <= 0:
            break
        p = 1.0 - alpha / (2.0 * size)
        t = student_t_quantile(p, df)
        critical = (size - 1) * t / math.sqrt((df + t * t) * size)

        candidates.append((worst, statistic, critical, working[worst]))
        remaining.remove(worst)

    found = 0
    for index, (_, statistic, critical, _) in enumerate(candidates, start=1):
        if statistic > critical:
            found = index

    anomalies = [
        Anomaly(
            index=idx,
            value=values[idx],
            residual=residual,
            score=statistic,
            critical_value=critical,
            direction="high" if residual > 0 else "low",
        )
        for idx, statistic, critical, residual in candidates[:found]
    ]
    anomalies.sort(key=lambda a: a.index)

    # Measured on the residuals against the *local* scale. Both choices matter:
    # a trend inflates the raw MAD enough to hide itself, and so does the
    # residual MAD, because the seasonal decomposition removes no trend. Only a
    # difference-based scale is insensitive to the thing being detected.
    first_half = median(residuals[: n // 2])
    second_half = median(residuals[n // 2:])
    spread = local_scale(residuals)
    warning = ""
    # No `spread > 0` guard: a scale of exactly zero means a noiseless
    # series, and a moving median there is the strongest trend evidence
    # available rather than a reason to stay silent.
    if abs(second_half - first_half) > 2.0 * spread:
        warning = (
            f"the residual median moves from {first_half:.4g} to "
            f"{second_half:.4g} between the halves of the series, against a "
            f"local noise scale of {spread:.4g}. The seasonal-median decomposition "
            "has no trend term, so that movement is trend leaking into the "
            "residual and it inflates the anomaly count. Detrend first, or read "
            "this result as an upper bound."
        )

    return AnomalyReport(
        anomalies=anomalies,
        tested=n,
        period=period,
        max_anomalies=k,
        trend_warning=warning,
        periods_observed=n // period,
    )

"""Standardised drought indices — SPI and SPEI (WS-2.1 Step 3).

SPI (McKee et al., 1993) answers one question: **how unusual is this
accumulation, for this place, at this time of year?** The answer is a z-score,
which is what makes it comparable between a district that gets 3,000 mm a year
and one that gets 400 — and comparability is the whole reason a credit feature
uses SPI rather than millimetres. "Rainfall was 200 mm below normal" means
nothing across a portfolio; "SPEI was -1.8" means the same thing everywhere.

The computation, exactly as the paper specifies it
--------------------------------------------------
1. Accumulate the series over the timescale (SPI-3 sums three months).
2. Fit a two-parameter gamma to the non-zero accumulations, by Thom's (1958)
   approximate maximum likelihood — the estimator McKee names.
3. Evaluate the gamma CDF, mixing in the zero-precipitation mass:
   ``H(x) = q + (1-q)·G(x)`` where ``q`` is the empirical fraction of zeros.
   Skipping the mixture is the classic SPI bug: in an arid month where a third
   of years record zero rain, an unmixed CDF pushes every dry year to the same
   extreme value and the index stops discriminating exactly where drought
   lending decisions are made.
4. Transform to a standard normal deviate.

SPEI (Vicente-Serrano et al., 2010) is the same machine driven by a **climatic
water balance** ``D = P - PET`` instead of precipitation. That difference is
not cosmetic for this phase: SPI cannot see a heat event, and a rain-adequate
season with 4°C of positive temperature anomaly is a crop failure SPI scores as
normal. Because ``D`` is signed, SPEI cannot use a gamma; the paper specifies a
three-parameter log-logistic fitted by probability-weighted moments, which is
what :func:`spei` implements.

Fitted per calendar month, always
---------------------------------
Both indices fit a *separate* distribution for each calendar month of the year.
A single pooled fit would score every monsoon month as wet and every dry-season
month as drought, on the same land, forever. The cost is that each fit sees one
observation per year, which is why :data:`MIN_YEARS_FOR_FIT` refuses short
series rather than returning a confidently meaningless index.

What this does not port
-----------------------
Not the `spei` R package, and not SciPy. The gamma and log-logistic fits are
the estimators the two papers name (Thom's AML; probability-weighted moments)
rather than the general-purpose MLE those libraries would use, and the normal
quantile is Wichura's AS 241 rather than an `erfinv` call. There is no
Hargreaves or Penman-Monteith PET model here — PET arrives as an input from the
ERA5 port, because computing PET from raw reanalysis fields is a
meteorological pipeline, not a credit feature.

Workstream: WS-2.1 Step 3 (SRS §3.2)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

#: A distribution is fitted per calendar month, so a 30-year series gives each
#: fit 30 points and a 10-year series gives it 10. Below this, a two-parameter
#: gamma is fitted on single digits and the resulting index has error bars wider
#: than the categories it is being read into. The WMO's own SPI guidance asks
#: for 30 years and calls 20 a minimum; this is the harder floor below which the
#: number should not be produced at all, not the recommended record length.
MIN_YEARS_FOR_FIT = 20

#: SPI/SPEI are unbounded in principle but the normal quantile saturates in
#: floating point, and an index of -8.7 is an artefact of a 30-point fit rather
#: than a measurement. Clipping is standard practice and is done explicitly so
#: that a saturated value is visibly at the rail.
INDEX_LIMIT = 3.09


class DroughtError(Exception):
    """The series cannot support the index being asked of it."""


@dataclass(frozen=True)
class DroughtIndex:
    """One standardised index value, with what it took to produce it.

    ``fitted_on`` is the number of observations behind the calendar-month fit.
    It travels with the value because a -1.5 from a 40-year fit and a -1.5 from
    a 20-year fit are not the same claim, and the second is the one that gets
    quoted in a stressed-income calculation.
    """

    value: float
    timescale_months: int
    calendar_month: int
    fitted_on: int
    zero_fraction: float = 0.0

    @property
    def category(self) -> str:
        """McKee's severity classes, verbatim from the 1993 paper's Table 1."""
        v = self.value
        if v >= 2.0:
            return "extremely wet"
        if v >= 1.5:
            return "very wet"
        if v >= 1.0:
            return "moderately wet"
        if v > -1.0:
            return "near normal"
        if v > -1.5:
            return "moderately dry"
        if v > -2.0:
            return "severely dry"
        return "extremely dry"

    @property
    def is_drought(self) -> bool:
        """SPEI <= -1, the threshold WS-2.3 uses for drought frequency.

        `[SPEC]` — Phase 2 §4 WS-2.3 defines drought frequency as "share of last
        20 seasons with SPEI <= -1". The boundary is inclusive because the phase
        file writes it that way, and McKee's own moderate-drought class opens at
        -1.0 inclusive.
        """
        return self.value <= -1.0


# ---------------------------------------------------------------------------
# Distribution fits
# ---------------------------------------------------------------------------


def _gamma_fit_thom(values: Sequence[float]) -> tuple[float, float]:
    """Shape and scale of a two-parameter gamma, by Thom's approximate MLE.

    This is the estimator McKee et al. specify, not a general MLE. It solves the
    likelihood equations through the sample statistic ``A = ln(x̄) - mean(ln x)``
    with Thom's (1958) closed-form approximation, which is accurate to better
    than 1% over the range of shapes rainfall produces and needs no iteration.

    Zeros must be excluded by the caller: ``ln 0`` is undefined and the zero mass
    is handled separately by the mixed CDF, which is the statistically correct
    treatment rather than a numerical dodge.
    """
    positive = [v for v in values if v > 0]
    if len(positive) < 2:
        raise DroughtError(
            f"gamma fit needs at least 2 positive accumulations, got {len(positive)}"
        )

    mean = sum(positive) / len(positive)
    log_mean = sum(math.log(v) for v in positive) / len(positive)
    a = math.log(mean) - log_mean

    if a <= 0:
        # Every value identical: the series has no variance to standardise.
        raise DroughtError(
            "accumulations are constant; a standardised index of a constant "
            "series is undefined, not zero"
        )

    shape = (1.0 + math.sqrt(1.0 + 4.0 * a / 3.0)) / (4.0 * a)
    scale = mean / shape
    return shape, scale


def _gamma_cdf(x: float, shape: float, scale: float) -> float:
    """Regularised lower incomplete gamma P(shape, x/scale).

    Series expansion below the shape, continued fraction above — the standard
    split, because the series converges slowly in the tail and the continued
    fraction converges slowly at the origin.
    """
    if x <= 0:
        return 0.0
    t = x / scale
    if t < shape + 1.0:
        # Series representation.
        term = 1.0 / shape
        total = term
        n = shape
        for _ in range(1000):
            n += 1.0
            term *= t / n
            total += term
            if abs(term) < abs(total) * 1e-14:
                break
        return total * math.exp(-t + shape * math.log(t) - math.lgamma(shape))

    # Continued fraction for the upper incomplete gamma (Lentz's algorithm).
    tiny = 1e-300
    b = t + 1.0 - shape
    c = 1.0 / tiny
    d = 1.0 / b
    h = d
    for i in range(1, 1000):
        an = -i * (i - shape)
        b += 2.0
        d = an * d + b
        if abs(d) < tiny:
            d = tiny
        c = b + an / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-14:
            break
    upper = h * math.exp(-t + shape * math.log(t) - math.lgamma(shape))
    return 1.0 - upper


def _log_logistic_fit_pwm(values: Sequence[float]) -> tuple[float, float, float]:
    """Three-parameter log-logistic by probability-weighted moments.

    The fit Vicente-Serrano et al. (2010) specify for SPEI. Unbiased PWMs are
    used rather than plotting-position estimators: the difference is small at
    n=100 and material at the n=30 a per-calendar-month fit actually gets.

    Returns ``(shape beta, scale alpha, location gamma)``.
    """
    ordered = sorted(values)
    n = len(ordered)
    if n < 4:
        raise DroughtError(f"log-logistic fit needs at least 4 values, got {n}")

    # Unbiased probability-weighted moments w0, w1, w2.
    w = [0.0, 0.0, 0.0]
    for i, x in enumerate(ordered):
        # i is 0-based; the estimator is written 1-based.
        j = i + 1
        w[0] += x
        if n > 1:
            w[1] += x * (n - j) / (n - 1)
        if n > 2:
            w[2] += x * (n - j) * (n - j - 1) / ((n - 1) * (n - 2))
    w = [v / n for v in w]

    shape_denominator = 6.0 * w[1] - w[0] - 6.0 * w[2]
    if abs(shape_denominator) < 1e-12:
        raise DroughtError(
            "degenerate water-balance series; the PWM shape estimate divides "
            "by zero, which happens when the accumulations carry no spread"
        )

    beta = (2.0 * w[1] - w[0]) / shape_denominator
    if beta <= 1.0:
        # Gamma(1 - 1/beta) has a pole at beta = 1 and is negative below it.
        # The fit is then outside the log-logistic family rather than merely
        # imprecise, so it must not be evaluated.
        raise DroughtError(
            f"log-logistic shape estimate {beta:.3f} <= 1; the scale parameter "
            "is undefined there. The water-balance series is too short or too "
            "heavy-tailed for a three-parameter fit."
        )

    g1 = math.gamma(1.0 + 1.0 / beta)
    g2 = math.gamma(1.0 - 1.0 / beta)
    alpha = (w[0] - 2.0 * w[1]) * beta / (g1 * g2)
    gamma_loc = w[0] - alpha * g1 * g2
    return beta, alpha, gamma_loc


def _log_logistic_cdf(x: float, beta: float, alpha: float, loc: float) -> float:
    """CDF of the three-parameter log-logistic."""
    if alpha <= 0:
        raise DroughtError("log-logistic scale must be positive")
    z = x - loc
    if z <= 0:
        return 0.0
    return 1.0 / (1.0 + (alpha / z) ** beta)


def normal_quantile(p: float) -> float:
    """Inverse standard normal CDF — Wichura's AS 241 algorithm.

    Accurate to about 1e-16, which matters because the whole point of a
    standardised index is that the number is comparable across places; a
    quantile good to 1e-4 would put SPI's second decimal in play, and the
    reference test in this phase's §4 checks two decimals.
    """
    if not 0.0 < p < 1.0:
        raise DroughtError(f"quantile requires 0 < p < 1, got {p}")

    q = p - 0.5
    if abs(q) <= 0.425:
        r = 0.180625 - q * q
        num = (
            ((((((2509.0809287301226727 * r + 33430.575583588128105) * r
                 + 67265.770927008700853) * r + 45921.953931549871457) * r
               + 13731.693765509461125) * r + 1971.5909503065514427) * r
             + 133.14166789178437745) * r + 3.387132872796366608
        )
        den = (
            ((((((5226.495278852854561 * r + 28729.085735721942674) * r
                 + 39307.89580009271061) * r + 21213.794301586595867) * r
               + 5394.1960214247511077) * r + 687.1870074920579083) * r
             + 42.313330701600911252) * r + 1.0
        )
        return q * num / den

    r = p if q < 0 else 1.0 - p
    r = math.sqrt(-math.log(r))
    if r <= 5.0:
        r -= 1.6
        num = (
            ((((((7.7454501427834140764e-4 * r + 0.0227238449892691845833) * r
                 + 0.24178072517745061177) * r + 1.27045825245236838258) * r
               + 3.64784832476320460504) * r + 5.7694972214606914055) * r
             + 4.6303378461565452959) * r + 1.42343711074968357734
        )
        den = (
            ((((((1.05075007164441684324e-9 * r + 5.475938084995344946e-4) * r
                 + 0.0151986665636164571966) * r + 0.14810397642748007459) * r
               + 0.68976733498510000455) * r + 1.6763848301838038494) * r
             + 2.05319162663775882187) * r + 1.0
        )
    else:
        r -= 5.0
        num = (
            ((((((2.01033439929228813265e-7 * r + 2.71155556874348757815e-5) * r
                 + 0.0012426609473880784386) * r + 0.026532189526576123093) * r
               + 0.29656057182850489123) * r + 1.7848265399172913358) * r
             + 5.4637849111641143699) * r + 6.6579046435011037772
        )
        den = (
            ((((((2.04426310338993978564e-15 * r + 1.4215117583164458887e-7) * r
                 + 1.8463183175100546818e-5) * r + 7.868691311456132591e-4) * r
               + 0.0148753612908506148525) * r + 0.13692988092273580531) * r
             + 0.59983220655588793769) * r + 1.0
        )
    value = num / den
    return -value if q < 0 else value


# ---------------------------------------------------------------------------
# The indices
# ---------------------------------------------------------------------------


def accumulate(series: Sequence[float], timescale: int) -> list[float | None]:
    """Rolling sums over ``timescale`` months, aligned to the ending month.

    The first ``timescale - 1`` positions are ``None`` rather than partial sums.
    A partial sum is a *smaller* accumulation over a shorter window, and feeding
    it to a fit calibrated on full windows makes the start of every series look
    like a drought.
    """
    if timescale < 1:
        raise DroughtError(f"timescale must be >= 1 month, got {timescale}")
    out: list[float | None] = []
    for i in range(len(series)):
        if i + 1 < timescale:
            out.append(None)
        else:
            out.append(sum(series[i + 1 - timescale : i + 1]))
    return out


def _calendar_month_slices(
    accumulations: Sequence[float | None], first_month: int
) -> dict[int, list[float]]:
    """Group accumulations by calendar month (1-12)."""
    grouped: dict[int, list[float]] = {}
    for offset, value in enumerate(accumulations):
        if value is None:
            continue
        month = (first_month - 1 + offset) % 12 + 1
        grouped.setdefault(month, []).append(value)
    return grouped


def spi(
    monthly_precip: Sequence[float],
    timescale: int,
    first_month: int = 1,
    *,
    min_years: int = MIN_YEARS_FOR_FIT,
) -> list[DroughtIndex | None]:
    """Standardised Precipitation Index (McKee et al., 1993).

    ``monthly_precip`` is a contiguous monthly series in mm starting at
    ``first_month`` (1 = January). Returns one index per input month, ``None``
    where the accumulation window is incomplete.

    Raises :class:`DroughtError` if any calendar month has fewer than
    ``min_years`` observations. Refusing is the right behaviour: an SPI fitted on
    eight years is not a weaker SPI, it is a number whose sampling error is
    larger than the difference between "near normal" and "severely dry".
    """
    accumulations = accumulate(monthly_precip, timescale)
    grouped = _calendar_month_slices(accumulations, first_month)

    short = {m: len(v) for m, v in grouped.items() if len(v) < min_years}
    if short:
        raise DroughtError(
            f"calendar months {sorted(short)} have fewer than {min_years} "
            f"observations ({short}); a per-month gamma fit on that many points "
            "produces an index whose error exceeds its categories"
        )

    fits: dict[int, tuple[float, float, float, int]] = {}
    for month, values in grouped.items():
        zeros = sum(1 for v in values if v <= 0)
        zero_fraction = zeros / len(values)
        shape, scale = _gamma_fit_thom(values)
        fits[month] = (shape, scale, zero_fraction, len(values))

    out: list[DroughtIndex | None] = []
    for offset, value in enumerate(accumulations):
        if value is None:
            out.append(None)
            continue
        month = (first_month - 1 + offset) % 12 + 1
        shape, scale, zero_fraction, n = fits[month]
        # The mixed CDF: H(x) = q + (1-q)G(x). Without the zero mass an arid
        # month's dry years all collapse onto the same extreme index value.
        h = zero_fraction + (1.0 - zero_fraction) * _gamma_cdf(value, shape, scale)
        out.append(
            DroughtIndex(
                value=_standardise(h),
                timescale_months=timescale,
                calendar_month=month,
                fitted_on=n,
                zero_fraction=zero_fraction,
            )
        )
    return out


def spei(
    monthly_precip: Sequence[float],
    monthly_pet: Sequence[float],
    timescale: int,
    first_month: int = 1,
    *,
    min_years: int = MIN_YEARS_FOR_FIT,
) -> list[DroughtIndex | None]:
    """Standardised Precipitation-Evapotranspiration Index (Vicente-Serrano 2010).

    Same machine as :func:`spi` driven by the climatic water balance
    ``D = P - PET``, fitted with a three-parameter log-logistic because ``D`` is
    signed and a gamma cannot represent it.

    PET is an *input*, not something computed here — see the module docstring.
    """
    if len(monthly_precip) != len(monthly_pet):
        raise DroughtError(
            f"precipitation and PET series differ in length "
            f"({len(monthly_precip)} vs {len(monthly_pet)}); they must be the "
            "same months in the same order"
        )

    balance = [p - e for p, e in zip(monthly_precip, monthly_pet)]
    accumulations = accumulate(balance, timescale)
    grouped = _calendar_month_slices(accumulations, first_month)

    short = {m: len(v) for m, v in grouped.items() if len(v) < min_years}
    if short:
        raise DroughtError(
            f"calendar months {sorted(short)} have fewer than {min_years} "
            f"observations ({short}) for a log-logistic fit"
        )

    fits = {m: (*_log_logistic_fit_pwm(v), len(v)) for m, v in grouped.items()}

    out: list[DroughtIndex | None] = []
    for offset, value in enumerate(accumulations):
        if value is None:
            out.append(None)
            continue
        month = (first_month - 1 + offset) % 12 + 1
        beta, alpha, loc, n = fits[month]
        h = _log_logistic_cdf(value, beta, alpha, loc)
        out.append(
            DroughtIndex(
                value=_standardise(h),
                timescale_months=timescale,
                calendar_month=month,
                fitted_on=n,
            )
        )
    return out


def _standardise(cumulative_probability: float) -> float:
    """Probability -> clipped standard normal deviate."""
    p = min(max(cumulative_probability, 1e-10), 1.0 - 1e-10)
    return max(-INDEX_LIMIT, min(INDEX_LIMIT, normal_quantile(p)))


def drought_frequency(indices: Sequence[DroughtIndex], seasons: int) -> float:
    """Share of the last ``seasons`` observations with SPEI <= -1.

    `[SPEC]` — the WS-2.3 climate feature, defined by Phase 2 §4 as "share of
    last 20 seasons with SPEI <= -1". Raises if the history is shorter than the
    window rather than dividing by what happens to be there: a drought frequency
    computed over 6 seasons and reported as a 20-season figure is the kind of
    error that reads as a low-risk plot.
    """
    if seasons < 1:
        raise DroughtError(f"seasons must be >= 1, got {seasons}")
    if len(indices) < seasons:
        raise DroughtError(
            f"drought frequency over {seasons} seasons needs {seasons} "
            f"observations, got {len(indices)}. A shorter window is a different "
            "statistic and must not be reported as this one."
        )
    window = list(indices)[-seasons:]
    return sum(1 for i in window if i.is_drought) / seasons

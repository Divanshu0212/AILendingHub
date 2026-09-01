"""Model-health panel — drift, calibration and change detection (WS-3.2 Step 3).

SRS §9.3.3 names three instruments and they answer different questions:

* **PSI/CSI** — has the *input or output distribution* moved against a
  reference? Batch, weekly, and already implemented in
  :mod:`lending_hub.scoring.features`; this module reuses it rather than
  restating the formula or the 0.1/0.25 thresholds.
* **ADWIN** — has a *stream* changed, without anyone choosing a window? The
  point of adaptive windowing is that a fixed weekly comparison misses a change
  that happens mid-week and over-reports one that reverses. Ported from
  Bifet & Gavaldà (2007), as used in `River <https://github.com/online-ml/river>`_.
* **Rolling calibration** — is the model still *right*, as opposed to still
  stable? A model can hold PSI at zero and drift badly in calibration; a rate
  environment moves the outcome, not the inputs. Watched with a two-sided CUSUM
  on observed-minus-expected.

Distribution stability is not correctness, and reporting only PSI is the most
common way a monitoring panel stays green through a model failure.

The parameters this module refuses to invent
--------------------------------------------
ADWIN's confidence ``delta`` and the calibration CUSUM's ``k``/``h`` are
required arguments with no defaults (LH-307). The paper's worked examples use
a particular delta, and that is a fact about the paper rather than a decision
about this bank's alert volume — :data:`ADWIN_PAPER_DELTA` records it as a
citation a caller may pass deliberately, which is different from a default
nobody chose.

Workstream: WS-3.2 Step 3 (SRS §9.3.3)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

from lending_hub.definitions.provenance import Grounded, Source
from lending_hub.scoring.features import PSI_ACT, PSI_ALERT, psi, screen_psi

#: The confidence parameter used in the ADWIN paper's own experiments. A
#: citation, not a default: it is available to pass deliberately and nothing
#: here reads it unless a caller does.
ADWIN_PAPER_DELTA = Grounded(
    value=0.002,
    source=Source.SPEC,
    citation=(
        "Bifet & Gavaldà, 'Learning from Time-Changing Data with Adaptive "
        "Windowing', SDM 2007 — the delta used in the paper's experiments. "
        "The operating value for this bank's alert volume is LH-307."
    ),
)

#: Minimum sub-window size before ADWIN will consider a cut. Below a handful of
#: points the Hoeffding bound is so wide that no cut is ever significant, and
#: allowing size-1 sub-windows just burns comparisons.
MIN_SUBWINDOW = 5


class HealthError(Exception):
    """A health statistic cannot be computed as asked."""


# --------------------------------------------------------------------------
# PSI / CSI, over the reference bin edges
# --------------------------------------------------------------------------


@dataclass
class DriftReading:
    """One feature or score, its PSI, and what the standard thresholds say."""

    name: str
    psi: float
    verdict: str
    detail: str

    @property
    def acts(self) -> bool:
        return self.psi >= PSI_ACT

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "psi": round(self.psi, 6),
            "verdict": self.verdict,
            "detail": self.detail,
            "alert_threshold": PSI_ALERT,
            "act_threshold": PSI_ACT,
        }


def bin_proportions(values: Sequence[float], edges: Sequence[float]) -> list[float]:
    """Share of ``values`` in each bin defined by ``edges``.

    Edges come from the *reference* sample and are passed in, never recomputed
    from the current one. Re-binning both sides on their own quantiles makes
    PSI approximately zero by construction — the single most common way a drift
    monitor reports stability through a distribution shift.
    """
    if len(edges) < 1:
        raise HealthError("PSI needs at least one interior bin edge")
    if list(edges) != sorted(edges):
        raise HealthError("bin edges must be ascending")
    if not values:
        raise HealthError("cannot bin an empty sample")

    counts = [0] * (len(edges) + 1)
    for value in values:
        index = len(edges)
        for i, edge in enumerate(edges):
            if value <= edge:
                index = i
                break
        counts[index] += 1
    total = len(values)
    return [c / total for c in counts]


def drift(
    name: str,
    reference: Sequence[float],
    current: Sequence[float],
    edges: Sequence[float],
) -> DriftReading:
    """PSI of ``current`` against ``reference`` over shared bin edges."""
    value = psi(bin_proportions(reference, edges), bin_proportions(current, edges))
    verdict, detail = screen_psi(value)
    return DriftReading(name=name, psi=value, verdict=verdict.value, detail=detail)


# --------------------------------------------------------------------------
# ADWIN — adaptive windowing (Bifet & Gavaldà, SDM 2007)
# --------------------------------------------------------------------------


@dataclass
class ChangePoint:
    index: int
    left_mean: float
    right_mean: float
    left_size: int
    right_size: int

    @property
    def shift(self) -> float:
        return self.right_mean - self.left_mean

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "left_mean": round(self.left_mean, 6),
            "right_mean": round(self.right_mean, 6),
            "left_size": self.left_size,
            "right_size": self.right_size,
            "shift": round(self.shift, 6),
        }


@dataclass
class Adwin:
    """Adaptive windowing: drop the oldest data once it provably differs.

    Maintains a window and, on every observation, looks for a split into
    ``W₀ | W₁`` whose means differ by more than the Hoeffding-style bound
    ``epsilon_cut``. When one is found the older part is dropped — so the window
    itself is the estimate of "how far back the current regime goes", and
    nobody has to choose a window length.

    ``delta`` is required. It is the probability of a false change report, and
    it is the whole tuning surface of the method.
    """

    delta: float
    window: list[float] = field(default_factory=list)
    changes: list[ChangePoint] = field(default_factory=list)
    seen: int = 0

    def __post_init__(self) -> None:
        if not 0.0 < self.delta < 1.0:
            raise HealthError(
                f"delta must be in (0, 1), got {self.delta}. It is the false-change "
                "probability and has no default here (LH-307)."
            )

    @property
    def width(self) -> int:
        return len(self.window)

    @property
    def mean(self) -> float:
        if not self.window:
            raise HealthError("no observations in the window")
        return sum(self.window) / len(self.window)

    def update(self, value: float) -> ChangePoint | None:
        """Add one observation; return the change point if the window shrank."""
        self.window.append(value)
        self.seen += 1
        detected = None

        shrinking = True
        while shrinking and len(self.window) >= 2 * MIN_SUBWINDOW:
            shrinking = False
            for cut in range(MIN_SUBWINDOW, len(self.window) - MIN_SUBWINDOW + 1):
                left = self.window[:cut]
                right = self.window[cut:]
                if self._separated(left, right):
                    detected = ChangePoint(
                        index=self.seen - len(self.window) + cut,
                        left_mean=sum(left) / len(left),
                        right_mean=sum(right) / len(right),
                        left_size=len(left),
                        right_size=len(right),
                    )
                    self.changes.append(detected)
                    self.window = right
                    shrinking = True
                    break
        return detected

    def _separated(self, left: Sequence[float], right: Sequence[float]) -> bool:
        n0, n1 = len(left), len(right)
        mean0 = sum(left) / n0
        mean1 = sum(right) / n1
        # Harmonic window size and the delta' correction, per the paper.
        m = 1.0 / (1.0 / n0 + 1.0 / n1)
        n = n0 + n1
        delta_prime = self.delta / max(1, n)
        combined = left + list(right) if isinstance(left, list) else list(left) + list(right)
        variance = _variance(combined)
        epsilon = (
            math.sqrt(2.0 / m * variance * math.log(2.0 / delta_prime))
            + 2.0 / (3.0 * m) * math.log(2.0 / delta_prime)
        )
        return abs(mean0 - mean1) > epsilon


def _variance(values: Sequence[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    return sum((v - mean) ** 2 for v in values) / n


# --------------------------------------------------------------------------
# Rolling calibration with a two-sided CUSUM
# --------------------------------------------------------------------------


@dataclass
class CalibrationPoint:
    period: str
    expected: float
    observed: float
    exposures: int
    upper: float
    lower: float
    alarm: str | None

    @property
    def gap(self) -> float:
        return self.observed - self.expected

    def to_dict(self) -> dict:
        return {
            "period": self.period,
            "expected_rate": round(self.expected, 6),
            "observed_rate": round(self.observed, 6),
            "accounts": self.exposures,
            "gap": round(self.gap, 6),
            "cusum_upper": round(self.upper, 4),
            "cusum_lower": round(self.lower, 4),
            "alarm": self.alarm,
        }


@dataclass
class CalibrationDrift:
    points: list[CalibrationPoint]
    reference_shift: float
    decision_interval: float

    @property
    def first_alarm(self) -> tuple[str, str] | None:
        for point in self.points:
            if point.alarm:
                return point.period, point.alarm
        return None

    def to_dict(self) -> dict:
        alarm = self.first_alarm
        return {
            "reference_shift_k": self.reference_shift,
            "decision_interval_h": self.decision_interval,
            "first_alarm_period": alarm[0] if alarm else None,
            "first_alarm_direction": alarm[1] if alarm else None,
            "points": [p.to_dict() for p in self.points],
        }


def calibration_drift(
    series: Sequence[tuple[str, float, int, int]],
    *,
    reference_shift: float,
    decision_interval: float,
) -> CalibrationDrift:
    """Two-sided CUSUM on observed-minus-expected default rate.

    ``series`` is ``(period, expected_rate, bad_count, account_count)``.

    Two-sided on purpose. A model that *under*-predicts is a provisioning
    shortfall and a model that *over*-predicts is lost business; a one-sided
    chart optimised for the first is silent through the second, and the second
    is the one that survives for years because nothing complains.
    """
    if reference_shift < 0 or decision_interval <= 0:
        raise HealthError(
            "reference_shift must be non-negative and decision_interval positive; "
            "neither has a default (LH-307)"
        )

    points: list[CalibrationPoint] = []
    upper = lower = 0.0
    for period, expected, bads, accounts in series:
        if accounts <= 0:
            raise HealthError(f"{period}: no accounts, so there is no observed rate")
        if not 0.0 <= expected <= 1.0:
            raise HealthError(f"{period}: expected rate {expected} is outside [0, 1]")
        observed = bads / accounts
        variance = expected * (1.0 - expected) / accounts
        se = math.sqrt(variance) if variance > 0 else 0.0
        z = (observed - expected) / se if se > 0 else 0.0
        upper = max(0.0, upper + z - reference_shift)
        lower = max(0.0, lower - z - reference_shift)
        alarm = None
        if upper > decision_interval:
            alarm = "under_predicting"
        elif lower > decision_interval:
            alarm = "over_predicting"
        points.append(CalibrationPoint(
            period=period, expected=expected, observed=observed,
            exposures=accounts, upper=upper, lower=lower, alarm=alarm))
    return CalibrationDrift(
        points=points,
        reference_shift=reference_shift,
        decision_interval=decision_interval,
    )

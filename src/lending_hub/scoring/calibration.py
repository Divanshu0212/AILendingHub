"""Calibration: turning a ranking into a probability that means what it says.

Phase 1 §4 WS-1.1 Step 5: "Isotonic regression on the validation set
(Niculescu-Mizil & Caruana, ICML 2005). Both models output calibrated PD;
reliability diagram + Brier score go in the validation report."

Calibration is not cosmetic here. SRS §4.3.2 puts it plainly: PDs feed pricing
and IFRS-9 ECL, so a model that ranks perfectly and predicts 4% where the truth
is 9% prices every loan wrong while every discrimination metric stays green.

Two rules the phase file makes binding (v1.1)
--------------------------------------------
Both began as findings against the original wording, which fitted the calibrator
on the validation set and mandated isotonic unconditionally. Both were accepted.

**The calibration sample is not the model-selection sample.** Step 4 fits
hyperparameters and early stopping on the validation vintages, so a calibrator
fitted on those same rows is fitted where the model was selected to look good, and
the reliability diagram that results is optimistic — mildly for a scorecard, more
for an early-stopped challenger. Since PDs feed pricing and IFRS-9, that is a
systematic mispricing rather than a cosmetic overstatement.
:class:`CalibrationSource` names the sanctioned alternatives:
``CROSS_FITTED_TRAIN`` (preferred on a thin-bad portfolio, because it uses the
largest sample available) and ``DEDICATED`` (a fourth block carved from train by
:func:`lending_hub.scoring.splits.carve_calibration`). ``VALIDATION`` remains
available and :class:`CalibrationReport` carries ``optimism_risk`` when it is used
on rows that drove model selection — a run that has to take that path must report
what it costs, not hide it.

**Isotonic is not automatic.** The paper Phase 1 cites is also the source of the
caveat: isotonic regression needs more data than Platt scaling and overfits small
samples, where its step function chases noise. On a rare default the binding
constraint is the **event count**, not the row count. :func:`recommend_calibrator`
returns a recommendation *with its citation*, the caller decides, and the choice
is recorded either way — a calibrator swapped silently between retrains is a
change nobody can see in the metrics.

One consequence worth knowing before reading a Gini: isotonic is a monotone *step*
function, so it quantises the score. It cannot reorder, but it collapses distinct
values into ties, and ties cost discrimination. SRS §4.3.4 therefore measures
discrimination on the raw score and calibration on the PD.

Workstream: WS-1.1 Step 5 · SRS §4.3.2, §4.3.4
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Sequence

from .isotonic import IsotonicCalibrator, fit_isotonic

#: Niculescu-Mizil & Caruana (ICML 2005) — the reference Phase 1 §4 Step 5 names —
#: report isotonic regression overfitting below roughly one thousand examples,
#: with Platt scaling preferable there. This is the *paper's* guidance, not a bank
#: policy, and a bank that sets its own floor states it and overrides this.
ISOTONIC_MINIMUM_SAMPLE = 1_000

#: Below this many minority-class examples, an isotonic step function is being
#: fitted to a handful of events regardless of how large the sample is. The
#: binding constraint on a rare-default portfolio is the event count, not the row
#: count — the same paper's argument applied to the class that carries the signal.
ISOTONIC_MINIMUM_POSITIVES = 100


class CalibrationError(Exception):
    """Calibration cannot be fitted or evaluated as requested."""


class Method(str, Enum):
    ISOTONIC = "isotonic"
    PLATT = "platt"


class CalibrationSource(str, Enum):
    """Which rows the calibrator was fitted on, and what that costs."""

    VALIDATION = "validation"
    """The validation split. Permitted, but if those rows drove early stopping or
    hyperparameter choice the calibration is optimistic and must be reported as
    such — Phase 1 §4 Step 5 (v1.1) directs the other two sources instead."""

    CROSS_FITTED_TRAIN = "cross_fitted_train"
    """Out-of-fold predictions over the training set: each row is predicted by a
    model that did not see it. No overlap with model selection, and it uses the
    largest sample available — which is the half of the problem that matters most
    when defaults are rare."""

    DEDICATED = "dedicated"
    """A fourth split carved out for calibration alone. Cleanest, and it costs
    rows that a thin-bad portfolio may not have."""


@dataclass
class PlattCalibrator:
    """Sigmoid calibration: ``p = σ(a·s + b)`` fitted by maximum likelihood.

    Two parameters, so it cannot chase noise the way an isotonic step function
    can. The cost is the assumption that miscalibration is sigmoidal — true for a
    margin-like score, less true for a model whose distortion is local.
    """

    a: float
    b: float
    n_fitted: int = 0
    n_positives: int = 0

    def predict(self, score: float) -> float:
        return 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, self.a * score + self.b))))

    def predict_all(self, scores: Sequence[float]) -> list[float]:
        return [self.predict(score) for score in scores]

    def to_dict(self) -> dict:
        return {
            "kind": "platt",
            "a": self.a,
            "b": self.b,
            "n_fitted": self.n_fitted,
            "n_positives": self.n_positives,
        }


def fit_platt(
    scores: Sequence[float],
    labels: Sequence[int],
    *,
    iterations: int = 50,
    tolerance: float = 1e-10,
    ridge: float = 1e-9,
) -> PlattCalibrator:
    """Fit Platt scaling by Newton-Raphson on the log-likelihood.

    Newton rather than gradient descent, because the two-parameter Hessian is
    closed-form and the descent version needs a learning rate — which is one more
    hyperparameter to tune and, tuned wrongly, converges to something *worse* than
    the uncalibrated score while every diagnostic still says "calibrated". Newton
    converges here in a handful of steps with nothing to tune.

    Uses Platt's own target smoothing — the positive class is fitted toward
    ``(N₊+1)/(N₊+2)`` rather than 1.0 — which is what stops the coefficients
    running to infinity on a perfectly separated sample.
    """
    if len(scores) != len(labels):
        raise CalibrationError("scores and labels must be the same length")
    if not scores:
        raise CalibrationError("cannot calibrate on an empty sample")

    positives = sum(labels)
    negatives = len(labels) - positives
    if positives == 0 or negatives == 0:
        raise CalibrationError(
            "calibration needs both outcomes; a single-class sample has no "
            "probability to fit"
        )

    high = (positives + 1) / (positives + 2)
    low = 1 / (negatives + 2)
    targets = [high if label == 1 else low for label in labels]

    a, b = 0.0, 0.0
    n = len(scores)
    for _ in range(iterations):
        grad_a = grad_b = 0.0
        h_aa = h_ab = h_bb = 0.0
        for score, target in zip(scores, targets):
            p = 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, a * score + b))))
            error = p - target
            weight = p * (1.0 - p)
            grad_a += error * score
            grad_b += error
            h_aa += weight * score * score
            h_ab += weight * score
            h_bb += weight

        h_aa += ridge
        h_bb += ridge
        determinant = h_aa * h_bb - h_ab * h_ab
        if abs(determinant) < 1e-18:
            break

        step_a = (h_bb * grad_a - h_ab * grad_b) / determinant
        step_b = (h_aa * grad_b - h_ab * grad_a) / determinant
        a -= step_a
        b -= step_b
        if abs(step_a) < tolerance and abs(step_b) < tolerance:
            break

    return PlattCalibrator(a=a, b=b, n_fitted=n, n_positives=positives)


@dataclass(frozen=True)
class ReliabilityBin:
    """One row of the reliability diagram (SRS §4.3.4 Hosmer-Lemeshow by decile)."""

    lower: float
    upper: float
    count: int
    predicted: float
    observed: float

    @property
    def gap(self) -> float:
        return self.observed - self.predicted

    def to_dict(self) -> dict:
        return {
            "lower": self.lower,
            "upper": self.upper,
            "count": self.count,
            "predicted": self.predicted,
            "observed": self.observed,
            "gap": self.gap,
        }


def brier_score(labels: Sequence[int], probabilities: Sequence[float]) -> float:
    """Mean squared error of the probability. Lower is better."""
    if len(labels) != len(probabilities):
        raise CalibrationError("labels and probabilities must be the same length")
    if not labels:
        raise CalibrationError("Brier score is undefined on an empty sample")
    return sum((p - y) ** 2 for y, p in zip(labels, probabilities)) / len(labels)


def reliability(
    labels: Sequence[int], probabilities: Sequence[float], bins: int = 10
) -> list[ReliabilityBin]:
    """Predicted versus observed rate, by equal-count bin of predicted PD."""
    if not labels:
        return []
    # Sorted by probability *only*. `sorted(zip(probabilities, labels))` compares
    # the label whenever probabilities tie, which lets the outcome decide which
    # bin a row lands in: a model predicting one constant probability then shows a
    # reliability diagram running cleanly from 0 to 1 and reads as perfectly
    # discriminating when it has discriminated nothing.
    order = sorted(range(len(labels)), key=lambda i: probabilities[i])
    paired = [(probabilities[i], labels[i]) for i in order]
    size = max(1, len(paired) // bins)

    # A bin is a *range of predicted probability*, so rows sharing a prediction
    # cannot be split across two of them. Cutting strictly every `size` rows would
    # put identical predictions either side of a boundary and let their outcomes
    # differ by bin — which is how a model predicting one constant probability
    # ends up with a diagram running from 0.0 to 1.0.
    out: list[ReliabilityBin] = []
    start = 0
    while start < len(paired):
        stop = min(start + size, len(paired))
        while stop < len(paired) and paired[stop][0] == paired[stop - 1][0]:
            stop += 1
        chunk = paired[start:stop]
        start = stop
        if not chunk:
            continue
        out.append(
            ReliabilityBin(
                lower=chunk[0][0],
                upper=chunk[-1][0],
                count=len(chunk),
                predicted=sum(p for p, _ in chunk) / len(chunk),
                observed=sum(y for _, y in chunk) / len(chunk),
            )
        )
    return out


def expected_calibration_error(
    labels: Sequence[int], probabilities: Sequence[float], bins: int = 10
) -> float:
    """ECE (SRS §4.3.4): count-weighted mean absolute gap across bins."""
    diagram = reliability(labels, probabilities, bins)
    total = sum(b.count for b in diagram)
    if total == 0:
        raise CalibrationError("ECE is undefined on an empty sample")
    return sum(b.count * abs(b.gap) for b in diagram) / total


def recommend_calibrator(n: int, positives: int) -> tuple[Method, str]:
    """Which calibrator the cited paper's guidance points to for this sample."""
    if n < ISOTONIC_MINIMUM_SAMPLE:
        return Method.PLATT, (
            f"{n} rows is below the {ISOTONIC_MINIMUM_SAMPLE}-row guidance in "
            "Niculescu-Mizil & Caruana (ICML 2005): isotonic overfits at this size, "
            "and its step function will chase noise into the reliability diagram"
        )
    if positives < ISOTONIC_MINIMUM_POSITIVES:
        return Method.PLATT, (
            f"{positives} events is below {ISOTONIC_MINIMUM_POSITIVES}: on a "
            "rare-default portfolio the isotonic fit rests on a handful of bads "
            "however many rows surround them"
        )
    return Method.ISOTONIC, (
        f"{n} rows and {positives} events support the isotonic fit Phase 1 §4 "
        "Step 5 specifies"
    )


@dataclass
class CalibrationReport:
    """Everything the validation report needs about one calibration."""

    method: Method
    source: CalibrationSource
    n_fitted: int
    n_positives: int
    brier_before: float
    brier_after: float
    ece_before: float
    ece_after: float
    diagram_before: list[ReliabilityBin]
    diagram_after: list[ReliabilityBin]
    optimism_risk: bool = False
    optimism_note: str = ""
    recommendation: Method | None = None
    recommendation_note: str = ""
    followed_recommendation: bool = True
    calibrator: object | None = field(default=None, repr=False)

    @property
    def improved(self) -> bool:
        return self.brier_after <= self.brier_before

    def to_dict(self) -> dict:
        return {
            "method": self.method.value,
            "source": self.source.value,
            "n_fitted": self.n_fitted,
            "n_positives": self.n_positives,
            "brier_before": self.brier_before,
            "brier_after": self.brier_after,
            "brier_improved": self.improved,
            "ece_before": self.ece_before,
            "ece_after": self.ece_after,
            "reliability_before": [b.to_dict() for b in self.diagram_before],
            "reliability_after": [b.to_dict() for b in self.diagram_after],
            "optimism_risk": self.optimism_risk,
            "optimism_note": self.optimism_note,
            "recommendation": self.recommendation.value if self.recommendation else None,
            "recommendation_note": self.recommendation_note,
            "followed_recommendation": self.followed_recommendation,
        }


def fit_calibration(
    scores: Sequence[float],
    labels: Sequence[int],
    *,
    method: Method | None = None,
    source: CalibrationSource = CalibrationSource.VALIDATION,
    model_selected_on_these_rows: bool = False,
    bins: int = 10,
) -> CalibrationReport:
    """Fit a calibrator and report what it did and what it cost.

    ``model_selected_on_these_rows`` is not a warning flag to be ignored — it is
    the difference between a reliability diagram that describes the model and one
    that describes the selection. It is recorded, never silently corrected, and
    when it is set the report says so in a field a gate reviewer reads. Under
    Phase 1 §4 Step 5 (v1.1) a run that sets it is taking a path the phase file
    directs away from, and owes an explanation.
    """
    if len(scores) != len(labels):
        raise CalibrationError("scores and labels must be the same length")
    if not scores:
        raise CalibrationError("cannot calibrate on an empty sample")

    positives = sum(labels)
    recommended, why = recommend_calibrator(len(scores), positives)
    chosen = method or recommended

    if chosen is Method.ISOTONIC:
        calibrator: object = fit_isotonic(scores, labels)
    else:
        calibrator = fit_platt(scores, labels)

    after = calibrator.predict_all(scores)

    optimism = source is CalibrationSource.VALIDATION and model_selected_on_these_rows
    return CalibrationReport(
        method=chosen,
        source=source,
        n_fitted=len(scores),
        n_positives=positives,
        brier_before=brier_score(labels, scores),
        brier_after=brier_score(labels, after),
        ece_before=expected_calibration_error(labels, scores, bins),
        ece_after=expected_calibration_error(labels, after, bins),
        diagram_before=reliability(labels, scores, bins),
        diagram_after=reliability(labels, after, bins),
        optimism_risk=optimism,
        optimism_note=(
            "fitted on the rows that drove early stopping and hyperparameter "
            "choice, so this reliability diagram is optimistic. Phase 1 §4 Step 5 "
            "(v1.1) directs CROSS_FITTED_TRAIN or a DEDICATED block instead."
            if optimism
            else ""
        ),
        recommendation=recommended,
        recommendation_note=why,
        followed_recommendation=chosen is recommended,
        calibrator=calibrator,
    )


def cross_fitted_scores(
    rows: Sequence[dict],
    labels: Sequence[int],
    fit: Callable[[Sequence[dict], Sequence[int]], object],
    *,
    folds: int = 5,
    seed: int = 0,
) -> list[float]:
    """Out-of-fold predictions: every row scored by a model that never saw it.

    The input to :data:`CalibrationSource.CROSS_FITTED_TRAIN`. Folds are cut by a
    seeded shuffle rather than by vintage — this is not an out-of-time exercise,
    it is a leakage-free way to reuse the training rows, and cutting folds by
    vintage would instead measure how well the model travels across time, which
    is the out-of-time test's job.
    """
    import random as _random

    if len(rows) != len(labels):
        raise CalibrationError("rows and labels must be the same length")
    if folds < 2:
        raise CalibrationError("cross-fitting needs at least two folds")
    if len(rows) < folds:
        raise CalibrationError(f"{len(rows)} rows cannot be cut into {folds} folds")

    order = list(range(len(rows)))
    _random.Random(seed).shuffle(order)
    assignment = {index: position % folds for position, index in enumerate(order)}

    out = [0.0] * len(rows)
    for fold in range(folds):
        train_index = [i for i in range(len(rows)) if assignment[i] != fold]
        held_index = [i for i in range(len(rows)) if assignment[i] == fold]
        if not held_index:
            continue
        model = fit([rows[i] for i in train_index], [labels[i] for i in train_index])
        predictions = model.predict_all([rows[i] for i in held_index])
        for i, prediction in zip(held_index, predictions):
            out[i] = prediction
    return out

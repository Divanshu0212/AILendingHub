"""Regularised logistic regression, stdlib only.

Chosen over a gradient-boosting challenger on purpose: an application scorecard
has to produce reason codes a customer can be told, and a linear model's
contributions are the reason codes rather than an approximation of them
(SRS §2.2 explainability, §11.2 adverse action).

Training is deterministic given its seed, and the seed comes from the caller's
reproducibility triplet (WS-0.2.3).

Workstream: WS-0.2.3
"""

from __future__ import annotations

import json
import math
import pathlib
import random
from dataclasses import dataclass, field


@dataclass
class Standardiser:
    """Zero-mean, unit-variance scaling, fitted on training data only.

    Fitting on the full dataset before splitting is the second-most-common
    leakage in a modelling pipeline after the join itself, so the fit is
    deliberately a separate, explicit step.
    """

    means: list[float] = field(default_factory=list)
    scales: list[float] = field(default_factory=list)

    @classmethod
    def fit(cls, rows: list[list[float]]) -> Standardiser:
        if not rows:
            raise ValueError("cannot standardise an empty design")
        width = len(rows[0])
        means = [0.0] * width
        for row in rows:
            for i, value in enumerate(row):
                means[i] += value
        means = [m / len(rows) for m in means]

        variances = [0.0] * width
        for row in rows:
            for i, value in enumerate(row):
                variances[i] += (value - means[i]) ** 2
        scales = [math.sqrt(v / len(rows)) or 1.0 for v in variances]
        return cls(means=means, scales=scales)

    def apply(self, row: list[float]) -> list[float]:
        return [(v - m) / s for v, m, s in zip(row, self.means, self.scales)]


def sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, z))))


@dataclass
class LogisticModel:
    columns: list[str]
    weights: list[float]
    bias: float
    standardiser: Standardiser
    epochs: int
    learning_rate: float
    l2: float
    seed: int

    def score_raw(self, row: list[float]) -> float:
        z = self.bias
        for w, x in zip(self.weights, self.standardiser.apply(row)):
            z += w * x
        return z

    def predict(self, row: list[float]) -> float:
        return sigmoid(self.score_raw(row))

    def predict_all(self, rows: list[list[float]]) -> list[float]:
        return [self.predict(row) for row in rows]

    def contributions(self, row: list[float]) -> list[tuple[str, float]]:
        """Per-feature contribution to the log-odds, largest magnitude first.

        These are the reason codes. For a linear model they are exact, not an
        attribution method's estimate of them.
        """
        scaled = self.standardiser.apply(row)
        pairs = [(name, w * x) for name, w, x in zip(self.columns, self.weights, scaled)]
        return sorted(pairs, key=lambda pair: abs(pair[1]), reverse=True)

    def to_dict(self) -> dict:
        return {
            "columns": self.columns,
            "weights": self.weights,
            "bias": self.bias,
            "means": self.standardiser.means,
            "scales": self.standardiser.scales,
            "hyperparameters": {
                "epochs": self.epochs,
                "learning_rate": self.learning_rate,
                "l2": self.l2,
                "seed": self.seed,
            },
        }

    def save(self, path: str | pathlib.Path) -> None:
        path = pathlib.Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")


def train(
    columns: list[str],
    rows: list[list[float]],
    labels: list[int],
    *,
    epochs: int = 12,
    learning_rate: float = 0.15,
    l2: float = 1e-4,
    seed: int = 0,
    class_weight: bool = True,
) -> LogisticModel:
    """Fit by stochastic gradient descent.

    ``class_weight`` rescales the positive class by the inverse base rate.
    Without it, a 0.2% default rate makes "predict nobody defaults" a 99.8%
    accurate model and the gradient has almost nothing to pull against.
    """
    if not rows:
        raise ValueError("cannot train on an empty design")

    standardiser = Standardiser.fit(rows)
    scaled = [standardiser.apply(row) for row in rows]

    positives = sum(labels)
    negatives = len(labels) - positives
    if class_weight and positives and negatives:
        weight_positive = negatives / positives
    else:
        weight_positive = 1.0

    width = len(columns)
    weights = [0.0] * width
    bias = 0.0
    rng = random.Random(seed)
    order = list(range(len(scaled)))

    for _ in range(epochs):
        rng.shuffle(order)
        for i in order:
            row, y = scaled[i], labels[i]
            weight = weight_positive if y == 1 else 1.0
            error = (sigmoid(_dot(weights, row) + bias) - y) * weight
            for j, x in enumerate(row):
                weights[j] -= learning_rate * (error * x + l2 * weights[j])
            bias -= learning_rate * error

    return LogisticModel(
        columns=list(columns),
        weights=weights,
        bias=bias,
        standardiser=standardiser,
        epochs=epochs,
        learning_rate=learning_rate,
        l2=l2,
        seed=seed,
    )


def _dot(weights: list[float], row: list[float]) -> float:
    return sum(w * x for w, x in zip(weights, row))

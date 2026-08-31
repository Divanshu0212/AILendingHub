"""Discrimination and calibration metrics, stdlib only.

Workstream: WS-0.2.3
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def auc(labels: list[int], scores: list[float]) -> float | None:
    """Area under the ROC curve, by rank (Mann-Whitney U), with tie handling.

    Returns None when one class is absent — AUC is undefined there, and
    reporting 0.5 would look like a working-but-useless model rather than an
    unmeasurable one.
    """
    positives = sum(labels)
    negatives = len(labels) - positives
    if positives == 0 or negatives == 0:
        return None

    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        average = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = average
        i = j + 1

    rank_sum = sum(r for r, y in zip(ranks, labels) if y == 1)
    return (rank_sum - positives * (positives + 1) / 2) / (positives * negatives)


def ks(labels: list[int], scores: list[float]) -> float | None:
    """Kolmogorov-Smirnov separation between the good and bad score curves."""
    positives = sum(labels)
    negatives = len(labels) - positives
    if positives == 0 or negatives == 0:
        return None

    paired = sorted(zip(scores, labels))
    cum_pos = cum_neg = 0
    best = 0.0
    for _, y in paired:
        if y == 1:
            cum_pos += 1
        else:
            cum_neg += 1
        best = max(best, abs(cum_pos / positives - cum_neg / negatives))
    return best


def log_loss(labels: list[int], scores: list[float]) -> float | None:
    if not labels:
        return None
    total = 0.0
    for y, p in zip(labels, scores):
        p = min(max(p, 1e-12), 1 - 1e-12)
        total -= y * math.log(p) + (1 - y) * math.log(1 - p)
    return total / len(labels)


@dataclass
class CalibrationBin:
    lower: float
    upper: float
    count: int
    predicted: float
    observed: float


def calibration(labels: list[int], scores: list[float], bins: int = 10) -> list[CalibrationBin]:
    """Predicted versus observed default rate by score decile."""
    if not labels:
        return []
    paired = sorted(zip(scores, labels))
    size = max(1, len(paired) // bins)
    out: list[CalibrationBin] = []
    for start in range(0, len(paired), size):
        chunk = paired[start : start + size]
        if not chunk:
            continue
        out.append(
            CalibrationBin(
                lower=chunk[0][0],
                upper=chunk[-1][0],
                count=len(chunk),
                predicted=sum(p for p, _ in chunk) / len(chunk),
                observed=sum(y for _, y in chunk) / len(chunk),
            )
        )
    return out


def summary(labels: list[int], scores: list[float]) -> dict:
    return {
        "n": len(labels),
        "positives": sum(labels),
        "base_rate": (sum(labels) / len(labels)) if labels else None,
        "auc": auc(labels, scores),
        "ks": ks(labels, scores),
        "log_loss": log_loss(labels, scores),
    }

"""Isolation Forest — the unsupervised layer, and why it does not alert.

Phase 1 §4 WS-1.2 Step 4: "scikit-learn **IsolationForest** (Liu, Ting & Zhou,
ICDM 2008), default hyperparameters, trained on 12 months of applications. Its
score is a **feature into the GBM** (semi-supervised stacking) — it does not raise
alerts on its own (single tunable alert queue)."

That last clause is the design, not a caveat. Two independently-alerting layers
mean two alert budgets, two thresholds and two sets of false positives arriving in
the same queue with no common scale — and a fraud desk that cannot tell which
model it is disagreeing with. Feeding the anomaly score into the supervised layer
keeps one queue with one tunable threshold. :func:`anomaly_feature` is therefore
the exported surface, and there is deliberately no ``raise_alert`` here.

The algorithm, from the paper
-----------------------------
Anomalies are *few and different*, so random axis-parallel splits isolate them in
fewer partitions. Each tree is built on a subsample; the score is derived from
the expected path length ``E[h(x)]`` normalised by ``c(n)``, the average path
length of an unsuccessful search in a binary search tree:

    ``c(n) = 2·H(n−1) − 2(n−1)/n``      (``H`` the harmonic number)
    ``s(x) = 2^(−E[h(x)] / c(n))``

so ``s → 1`` is anomalous and ``s → 0.5`` is unremarkable. Subsampling is not an
optimisation: the paper's point is that small subsamples *improve* detection by
reducing swamping and masking, which is why ``max_samples`` defaults to 256 rather
than to the dataset.

Hyperparameters are scikit-learn's documented defaults, as Phase 1 requires — a
library default is traceable, and "we tuned it a bit" is not.

Workstream: WS-1.2 Step 4 · SRS §5.3.2
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Sequence

#: scikit-learn IsolationForest defaults, as Phase 1 §4 WS-1.2 Step 4 specifies.
DEFAULT_N_ESTIMATORS = 100
DEFAULT_MAX_SAMPLES = 256

#: The name the stacked score carries into the supervised layer's feature vector.
ANOMALY_FEATURE = "fraud_anomaly_score"

EULER_MASCHERONI = 0.5772156649


class AnomalyError(Exception):
    """The forest cannot be fitted or scored as requested."""


def average_path_length(n: int) -> float:
    """``c(n)`` — average unsuccessful-search path length in a BST of ``n`` nodes.

    The normaliser that makes scores comparable across subsample sizes. Without
    it, a deeper tree looks like a more normal point.
    """
    if n <= 1:
        return 0.0
    if n == 2:
        return 1.0
    harmonic = math.log(n - 1) + EULER_MASCHERONI
    return 2 * harmonic - 2 * (n - 1) / n


@dataclass
class IsolationNode:
    feature: str | None = None
    threshold: float | None = None
    left: "IsolationNode | None" = None
    right: "IsolationNode | None" = None
    size: int = 0

    @property
    def is_leaf(self) -> bool:
        return self.feature is None

    def path_length(self, row: dict, depth: int = 0) -> float:
        if self.is_leaf:
            # An external node holding several points stands for a subtree that
            # was never built; the expected depth of that subtree is added back.
            return depth + average_path_length(self.size)
        value = row.get(self.feature)
        if value is None:
            # A missing value cannot be split on. Charging the average of both
            # sides keeps missingness from reading as either extremely normal or
            # extremely anomalous.
            return (
                self.left.path_length(row, depth + 1)
                + self.right.path_length(row, depth + 1)
            ) / 2.0
        return (
            self.left.path_length(row, depth + 1)
            if value < self.threshold
            else self.right.path_length(row, depth + 1)
        )


def _build_tree(
    rows: list[dict], features: Sequence[str], depth: int, limit: int, rng: random.Random
) -> IsolationNode:
    if depth >= limit or len(rows) <= 1:
        return IsolationNode(size=len(rows))

    usable = []
    for feature in features:
        values = [row[feature] for row in rows if row.get(feature) is not None]
        if len(values) >= 2 and min(values) < max(values):
            usable.append((feature, min(values), max(values)))
    if not usable:
        return IsolationNode(size=len(rows))

    feature, low, high = usable[rng.randrange(len(usable))]
    threshold = rng.uniform(low, high)

    left = [r for r in rows if r.get(feature) is not None and r[feature] < threshold]
    right = [r for r in rows if not (r.get(feature) is not None and r[feature] < threshold)]
    if not left or not right:
        return IsolationNode(size=len(rows))

    return IsolationNode(
        feature=feature,
        threshold=threshold,
        left=_build_tree(left, features, depth + 1, limit, rng),
        right=_build_tree(right, features, depth + 1, limit, rng),
        size=len(rows),
    )


@dataclass
class IsolationForest:
    """A fitted forest. Scores in [0, 1]; higher is more anomalous."""

    features: list[str]
    trees: list[IsolationNode] = field(default_factory=list)
    subsample_size: int = DEFAULT_MAX_SAMPLES
    n_estimators: int = DEFAULT_N_ESTIMATORS
    seed: int = 0
    n_fitted: int = 0

    def path_length(self, row: dict) -> float:
        return sum(tree.path_length(row) for tree in self.trees) / len(self.trees)

    def score(self, row: dict) -> float:
        """``s(x) = 2^(−E[h(x)]/c(n))``."""
        if not self.trees:
            raise AnomalyError("forest is not fitted")
        normaliser = average_path_length(self.subsample_size)
        if normaliser == 0:
            return 0.5
        return 2.0 ** (-self.path_length(row) / normaliser)

    def score_all(self, rows: Sequence[dict]) -> list[float]:
        return [self.score(row) for row in rows]

    def to_dict(self) -> dict:
        return {
            "kind": "isolation_forest",
            "features": self.features,
            "n_estimators": self.n_estimators,
            "max_samples": self.subsample_size,
            "seed": self.seed,
            "n_fitted": self.n_fitted,
            "hyperparameters": "scikit-learn defaults (Phase 1 §4 WS-1.2 Step 4)",
            "alerts_independently": False,
            "role": (
                "stacked as the feature "
                f"{ANOMALY_FEATURE!r} into the supervised layer; one alert queue, "
                "one tunable threshold (SRS §5.3.2)"
            ),
        }


def fit_isolation_forest(
    rows: Sequence[dict],
    features: Sequence[str],
    *,
    n_estimators: int = DEFAULT_N_ESTIMATORS,
    max_samples: int = DEFAULT_MAX_SAMPLES,
    seed: int = 0,
) -> IsolationForest:
    """Fit the forest. Deterministic for a given seed and input order."""
    rows = list(rows)
    if not rows:
        raise AnomalyError("cannot fit an isolation forest on an empty sample")
    features = list(features)
    if not features:
        raise AnomalyError("an isolation forest needs at least one feature")

    subsample_size = min(max_samples, len(rows))
    limit = max(1, math.ceil(math.log2(subsample_size))) if subsample_size > 1 else 1
    rng = random.Random(seed)

    trees = []
    for _ in range(n_estimators):
        sample = rng.sample(rows, subsample_size)
        trees.append(_build_tree(sample, features, 0, limit, rng))

    return IsolationForest(
        features=features,
        trees=trees,
        subsample_size=subsample_size,
        n_estimators=n_estimators,
        seed=seed,
        n_fitted=len(rows),
    )


def anomaly_feature(forest: IsolationForest, row: dict) -> dict[str, float]:
    """The one sanctioned way to consume the anomaly score.

    Returns a feature to merge into the supervised layer's input, never a
    decision. There is no ``raise_alert`` in this module: two independently
    alerting layers mean two thresholds and two false-positive streams landing in
    one queue on no common scale, and a fraud desk that cannot tell which model it
    is disagreeing with.
    """
    return {ANOMALY_FEATURE: forest.score(row)}

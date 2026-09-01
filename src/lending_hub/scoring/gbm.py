"""The challenger — histogram gradient boosting with monotone constraints.

Phase 1 §4 WS-1.1 Step 4: "Library: LightGBM. ``monotone_constraints`` applied to
every feature on the ratified direction list `[POLICY: Credit Risk Head]`.
Hyperparameter search on validation vintages only; early stopping; seeds fixed."

Master §2 rule 2 again: this is a **port**, and what it ports is stated. The
split criterion is the regularised second-order gain the SRS §4.3.2 writes out —

    ``w*_j = −ΣG / (ΣH + λ)``
    ``Gain = ½[ G_L²/(H_L+λ) + G_R²/(H_R+λ) − (G_L+G_R)²/(H_L+H_R+λ) ] − γ``

— on histogram-binned features, which is LightGBM's split-finding structure with
XGBoost's gain. It does not implement GOSS or EFB: those are LightGBM's speed
optimisations on hundreds of millions of rows, and reproducing them in a
reference implementation would add sampling behaviour without adding fidelity.
The Track B adapter calls LightGBM. What the tests pin is the behaviour a swap
must preserve — monotone outputs, determinism from the seed, and early stopping
on a set the model does not learn from.

Monotone constraints are not optional here
------------------------------------------
:func:`fit_gbm` requires a :class:`MonotoneConstraints` for every feature.
Fitting without one is possible only through
:meth:`MonotoneConstraints.for_experiment`, which demands a written reason and
stamps ``ratified=False`` on the model. The reason is Phase 1 §8: the direction
list is `[POLICY]` (LH-202), and the whole value of a monotone constraint is that
it comes from outside the data. A model that inferred its own directions has
imposed nothing — it has re-described its fit — and the regulator objection the
constraint exists to answer is still open.

The constraint is enforced the way XGBoost enforces it: a split on a constrained
feature is rejected unless the child values run the right way, and the children
inherit value bounds around the split's midpoint so no deeper split can undo it.

Workstream: WS-1.1 Step 4 · SRS §4.3.2
"""

from __future__ import annotations

import math
import random
from bisect import bisect_left
from dataclasses import dataclass, field
from typing import Sequence

from .parallel import pmap

#: LightGBM's default maximum histogram bins per feature.
DEFAULT_MAX_BINS = 255

INCREASING = 1
DECREASING = -1
UNCONSTRAINED = 0


class GBMError(Exception):
    """The model cannot be fitted or read as requested."""


@dataclass(frozen=True)
class MonotoneConstraints:
    """Per-feature monotone directions, and where they came from."""

    directions: dict[str, int]
    ratified: bool
    provenance: str

    def __post_init__(self) -> None:
        for name, direction in self.directions.items():
            if direction not in (INCREASING, DECREASING, UNCONSTRAINED):
                raise GBMError(
                    f"{name}: direction must be +1, -1 or 0, not {direction!r}"
                )

    @classmethod
    def from_policy(cls, directions: dict[str, int], *, decision_reference: str):
        """The real thing: a ratified direction list with a decision reference."""
        if not decision_reference:
            raise GBMError(
                "a ratified direction list must cite the decision that ratified it; "
                "a dict with no provenance is indistinguishable from a guess"
            )
        return cls(directions=dict(directions), ratified=True, provenance=decision_reference)

    @classmethod
    def for_experiment(cls, features: Sequence[str], *, reason: str):
        """Unconstrained fitting, permitted for experiments and stamped as such."""
        if not reason:
            raise GBMError(
                "fitting without monotone constraints needs a written reason. "
                "Phase 1 §8 puts the direction list on the do-not-invent list "
                "(LH-202), so an unconstrained challenger is an experiment, not a "
                "candidate."
            )
        return cls(
            directions={name: UNCONSTRAINED for name in features},
            ratified=False,
            provenance=f"unratified, for experiment only: {reason}",
        )

    def direction(self, feature: str) -> int:
        if feature not in self.directions:
            raise GBMError(
                f"{feature!r} has no monotone direction. Phase 1 §4 Step 4 requires "
                "the constraint on *every* feature; a feature omitted from the list "
                "is unconstrained by accident rather than by decision."
            )
        return self.directions[feature]


@dataclass
class Node:
    """One node. Leaves carry a value; internal nodes carry a split."""

    value: float = 0.0
    feature: str | None = None
    threshold: float | None = None
    left: "Node | None" = None
    right: "Node | None" = None
    cover: float = 0.0
    """Sum of hessians reaching this node — TreeSHAP's weighting (Step 6)."""

    count: int = 0

    @property
    def is_leaf(self) -> bool:
        return self.feature is None

    def predict(self, row: dict) -> float:
        node = self
        while not node.is_leaf:
            value = row.get(node.feature)
            # A missing value goes left, consistently in training and scoring.
            # The direction matters less than that it is the same in both, which
            # is where training/serving skew usually enters a tree model.
            node = node.left if value is None or value <= node.threshold else node.right
        return node.value

    def leaves(self) -> int:
        return 1 if self.is_leaf else self.left.leaves() + self.right.leaves()

    def depth(self) -> int:
        return 1 if self.is_leaf else 1 + max(self.left.depth(), self.right.depth())

    def to_dict(self) -> dict:
        if self.is_leaf:
            return {"value": self.value, "cover": self.cover, "count": self.count}
        return {
            "feature": self.feature,
            "threshold": self.threshold,
            "cover": self.cover,
            "count": self.count,
            "left": self.left.to_dict(),
            "right": self.right.to_dict(),
        }


@dataclass
class GBM:
    """A fitted gradient-boosting model."""

    features: list[str]
    trees: list[Node]
    base_score: float
    learning_rate: float
    constraints: MonotoneConstraints
    params: dict = field(default_factory=dict)
    best_iteration: int = 0
    validation_curve: list[float] = field(default_factory=list)

    @property
    def promotable(self) -> tuple[bool, str]:
        """Whether this model may enter the shipping ladder at all.

        Separate from "does it fit well". An unratified direction list is a
        governance state, not a metric, and it is the kind of thing that gets
        waved through at a gate review when it lives only in a footnote.
        """
        if not self.constraints.ratified:
            return False, (
                "monotone directions are not ratified (LH-202): Phase 1 §4 Step 4 "
                "requires the constraint on every feature from the ratified list"
            )
        return True, "monotone directions ratified"

    def raw_score(self, row: dict) -> float:
        total = self.base_score
        for tree in self.trees[: self.best_iteration or len(self.trees)]:
            total += self.learning_rate * tree.predict(row)
        return total

    def predict(self, row: dict) -> float:
        """Probability of the positive class — raw and uncalibrated (SRS §4.3.2.2)."""
        return 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, self.raw_score(row)))))

    def predict_all(self, rows: Sequence[dict]) -> list[float]:
        return [self.predict(row) for row in rows]

    def to_dict(self) -> dict:
        promotable, note = self.promotable
        return {
            "kind": "histogram_gbm",
            "features": self.features,
            "n_trees": len(self.trees),
            "best_iteration": self.best_iteration,
            "base_score": self.base_score,
            "learning_rate": self.learning_rate,
            "params": self.params,
            "monotone_constraints": self.constraints.directions,
            "constraints_ratified": self.constraints.ratified,
            "constraints_provenance": self.constraints.provenance,
            "promotable": promotable,
            "promotion_note": note,
            "validation_curve": self.validation_curve,
        }


def _histogram_edges(values: Sequence[float], max_bins: int) -> list[float]:
    """Quantile bin edges, the candidate split thresholds for one feature."""
    present = sorted(v for v in values if v is not None and not _isnan(v))
    if not present:
        return []
    unique = sorted(set(present))
    if len(unique) <= max_bins:
        return unique[:-1] if len(unique) > 1 else []
    step = len(present) / max_bins
    edges: list[float] = []
    for k in range(1, max_bins):
        candidate = present[min(len(present) - 1, int(k * step))]
        if not edges or candidate > edges[-1]:
            edges.append(candidate)
    return edges


def _isnan(value) -> bool:
    return isinstance(value, float) and math.isnan(value)


def _leaf_value(grad: float, hess: float, l2: float, bounds: tuple[float, float]) -> float:
    raw = -grad / (hess + l2) if (hess + l2) != 0 else 0.0
    return min(max(raw, bounds[0]), bounds[1])


def _bin_index(edges: list[float], value) -> int:
    """Histogram bin for one value.

    ``bisect_left`` rather than ``bisect_right`` so that "bin index <= b" is
    exactly "value <= edges[b]", which is the comparison :meth:`Node.predict`
    makes at score time. Using the other one puts a value sitting exactly on a
    split edge in a different child during training than during scoring — a
    training/serving skew that touches only the rows on the boundary and is
    invisible in aggregate metrics.
    """
    if value is None or _isnan(value):
        # Missing goes to the lowest bin, which sends it left under every split,
        # matching Node.predict. The direction matters less than that it is the
        # same in both places.
        return 0
    return bisect_left(edges, value)


def _histograms(
    indices: list[int],
    columns: list[list[int]],
    grads: list[float],
    hess: list[float],
    widths: list[int],
    active: list[int],
) -> list[tuple[list[float], list[float], list[int]]]:
    """Gradient/hessian/count histograms for one node, one entry per feature.

    Column-major: ``columns[f]`` is a flat list of bin indices for feature ``f``,
    so the inner loop does one list lookup per row rather than two. On a wide
    feature set that single change is most of the difference between a run that
    iterates and one that does not.
    """
    out = []
    for position in active:
        width = widths[position]
        column = columns[position]
        hist_g = [0.0] * width
        hist_h = [0.0] * width
        hist_n = [0] * width
        for i in indices:
            b = column[i]
            hist_g[b] += grads[i]
            hist_h[b] += hess[i]
            hist_n[b] += 1
        out.append((hist_g, hist_h, hist_n))
    return out


def _subtract(parent, child):
    """Sibling histograms by subtraction — LightGBM's standard trick.

    A node's two children partition its rows, so one child's histogram is the
    parent's minus the other's. Building only the *smaller* child and subtracting
    for the larger turns the per-level cost from "every row" into "the smaller
    half of every row", and the saving compounds with depth.
    """
    out = []
    for (pg, ph, pn), (cg, ch, cn) in zip(parent, child):
        out.append((
            [a - b for a, b in zip(pg, cg)],
            [a - b for a, b in zip(ph, ch)],
            [a - b for a, b in zip(pn, cn)],
        ))
    return out


def _bin_index(edges: list[float], value) -> int:
    """Histogram bin for one value.

    ``bisect_left`` rather than ``bisect_right`` so that "bin index <= b" is
    exactly "value <= edges[b]", which is the comparison :meth:`Node.predict`
    makes at score time. Using the other one puts a value sitting exactly on a
    split edge in a different child during training than during scoring — a
    training/serving skew that touches only the rows on the boundary and is
    invisible in aggregate metrics.
    """
    if value is None or _isnan(value):
        # Missing goes to the lowest bin, which sends it left under every split,
        # matching Node.predict. The direction matters less than that it is the
        # same in both places.
        return 0
    return bisect_left(edges, value)


def _build(
    indices: list[int],
    hists,
    columns: list[list[int]],
    grads: list[float],
    hess: list[float],
    features: Sequence[str],
    edges: dict[str, list[float]],
    widths: list[int],
    active: list[int],
    constraints: MonotoneConstraints,
    *,
    depth: int,
    max_depth: int,
    min_child_weight: float,
    l2: float,
    gamma: float,
    bounds: tuple[float, float],
) -> Node:
    """Grow one node from its precomputed histograms.

    The split scan walks bins, not rows — that is LightGBM's structure, and it is
    the difference between O(rows x bins) and O(rows + bins) per feature per node.
    Histograms arrive precomputed so a parent can hand a child the result of
    :func:`_subtract` instead of a second pass over the data.
    """
    total_g = sum(hists[0][0]) if hists else 0.0
    total_h = sum(hists[0][1]) if hists else 0.0
    node = Node(
        value=_leaf_value(total_g, total_h, l2, bounds),
        cover=total_h,
        count=len(indices),
    )

    if depth >= max_depth or len(indices) < 2:
        return node

    parent_gain = total_g * total_g / (total_h + l2) if (total_h + l2) else 0.0
    best = None

    for slot, position in enumerate(active):
        feature = features[position]
        if widths[position] < 2:
            continue
        histogram_g, histogram_h, histogram_n = hists[slot]
        direction = constraints.direction(feature)
        left_g = left_h = 0.0
        left_n = 0
        for b in range(widths[position] - 1):
            left_g += histogram_g[b]
            left_h += histogram_h[b]
            left_n += histogram_n[b]
            right_g, right_h = total_g - left_g, total_h - left_h
            right_n = len(indices) - left_n
            if left_n == 0 or right_n == 0:
                continue
            if left_h < min_child_weight or right_h < min_child_weight:
                continue

            left_value = _leaf_value(left_g, left_h, l2, bounds)
            right_value = _leaf_value(right_g, right_h, l2, bounds)
            if direction == INCREASING and left_value > right_value:
                continue
            if direction == DECREASING and left_value < right_value:
                continue

            gain = 0.5 * (
                left_g * left_g / (left_h + l2)
                + right_g * right_g / (right_h + l2)
                - parent_gain
            ) - gamma
            if gain <= 0:
                continue
            if best is None or gain > best[0]:
                best = (gain, position, feature, b, left_value, right_value)

    if best is None:
        return node

    _, position, feature, split_bin, left_value, right_value = best
    column = columns[position]
    left_indices = [i for i in indices if column[i] <= split_bin]
    right_indices = [i for i in indices if column[i] > split_bin]

    direction = constraints.direction(feature)
    left_bounds, right_bounds = bounds, bounds
    if direction != UNCONSTRAINED:
        # XGBoost's rule: children are bounded either side of the split midpoint,
        # so a deeper split cannot walk back across it and break monotonicity in
        # the assembled tree.
        midpoint = (left_value + right_value) / 2.0
        if direction == INCREASING:
            left_bounds = (bounds[0], min(bounds[1], midpoint))
            right_bounds = (max(bounds[0], midpoint), bounds[1])
        else:
            left_bounds = (max(bounds[0], midpoint), bounds[1])
            right_bounds = (bounds[0], min(bounds[1], midpoint))

    # Build the smaller child's histograms and subtract for the larger.
    if len(left_indices) <= len(right_indices):
        left_hists = _histograms(left_indices, columns, grads, hess, widths, active)
        right_hists = _subtract(hists, left_hists)
    else:
        right_hists = _histograms(right_indices, columns, grads, hess, widths, active)
        left_hists = _subtract(hists, right_hists)

    node.feature = feature
    node.threshold = edges[feature][split_bin]
    node.left = _build(
        left_indices, left_hists, columns, grads, hess, features, edges, widths,
        active, constraints, depth=depth + 1, max_depth=max_depth,
        min_child_weight=min_child_weight, l2=l2, gamma=gamma, bounds=left_bounds,
    )
    node.right = _build(
        right_indices, right_hists, columns, grads, hess, features, edges, widths,
        active, constraints, depth=depth + 1, max_depth=max_depth,
        min_child_weight=min_child_weight, l2=l2, gamma=gamma, bounds=right_bounds,
    )
    return node


def fit_gbm(
    rows: Sequence[dict],
    labels: Sequence[int],
    features: Sequence[str],
    constraints: MonotoneConstraints,
    *,
    n_trees: int = 100,
    learning_rate: float = 0.1,
    max_depth: int = 3,
    min_child_weight: float = 1.0,
    l2: float = 1.0,
    gamma: float = 0.0,
    max_bins: int = DEFAULT_MAX_BINS,
    feature_fraction: float = 1.0,
    scale_pos_weight: float | None = None,
    validation: tuple[Sequence[dict], Sequence[int]] | None = None,
    early_stopping_rounds: int | None = None,
    seed: int = 0,
) -> GBM:
    """Fit the challenger.

    ``validation`` is used for early stopping and nothing else — the model never
    takes a gradient step on it. Phase 1 §4 Step 4 restricts hyperparameter search
    to validation vintages for the same reason: a test set touched by model
    selection has stopped being out-of-time.

    ``scale_pos_weight`` rescales the positive class, the standard handling for
    the extreme imbalance in fraud (§4 WS-1.2 Step 3) and the mild imbalance in
    credit. It changes the calibration of the raw output, which is one of several
    reasons the calibration step is separate and mandatory.

    ``feature_fraction`` is LightGBM's parameter of the same name: each tree
    considers a seeded random subset of the features. It cuts the per-node
    histogram cost proportionally — the dominant term in a wide-feature fit — and
    on correlated credit features it usually costs little accuracy, because a
    feature left out of one tree is available to the next. It is a *speed and
    decorrelation* control, not a feature-selection one: a feature excluded here
    is still in the model. Default 1.0, so nothing changes unless asked.
    """
    if len(rows) != len(labels):
        raise GBMError("rows and labels must be the same length")
    if not rows:
        raise GBMError("cannot fit on an empty sample")
    if any(label not in (0, 1) for label in labels):
        raise GBMError("labels must be 0 or 1")

    features = list(features)
    for feature in features:
        constraints.direction(feature)

    positives = sum(labels)
    if positives in (0, len(labels)):
        raise GBMError("a classifier needs both classes present")

    weight_positive = scale_pos_weight if scale_pos_weight is not None else 1.0
    base_rate = positives / len(labels)
    base_score = math.log(base_rate / (1 - base_rate))

    edges = {
        feature: _histogram_edges([row.get(feature) for row in rows], max_bins)
        for feature in features
    }
    # Bin once, up front, column-major. Re-deriving bin membership at every node
    # is where a histogram implementation quietly becomes the naive one; storing
    # it row-major costs a second list lookup on the hottest line in the fit.
    columns = [
        [_bin_index(edges[feature], row.get(feature)) for row in rows]
        for feature in features
    ]
    widths = [len(edges[feature]) + 1 for feature in features]

    if not 0.0 < feature_fraction <= 1.0:
        raise GBMError("feature_fraction must be in (0, 1]")

    # The seed drives feature sampling. It is part of the reproducibility triplet
    # (WS-0.2.3), and a model whose card records no seed cannot be re-derived by
    # an auditor who has only the card.
    rng = random.Random(seed)
    n_active = max(1, round(feature_fraction * len(features)))

    raw = [base_score] * len(rows)
    trees: list[Node] = []
    curve: list[float] = []
    best_iteration = 0
    best_loss = float("inf")
    since_improvement = 0

    for _ in range(n_trees):
        grads, hess = [], []
        for score, label in zip(raw, labels):
            p = 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, score))))
            weight = weight_positive if label == 1 else 1.0
            grads.append(weight * (p - label))
            hess.append(weight * max(p * (1 - p), 1e-9))

        active = (
            list(range(len(features)))
            if n_active >= len(features)
            else sorted(rng.sample(range(len(features)), n_active))
        )
        root = list(range(len(rows)))
        tree = _build(
            root, _histograms(root, columns, grads, hess, widths, active),
            columns, grads, hess, features, edges, widths, active, constraints,
            depth=0, max_depth=max_depth, min_child_weight=min_child_weight,
            l2=l2, gamma=gamma, bounds=(-float("inf"), float("inf")),
        )
        trees.append(tree)
        for i, row in enumerate(rows):
            raw[i] += learning_rate * tree.predict(row)

        if validation is not None:
            model = GBM(features, trees, base_score, learning_rate, constraints)
            model.best_iteration = len(trees)
            loss = _log_loss(validation[1], model.predict_all(validation[0]))
            curve.append(loss)
            if loss < best_loss - 1e-9:
                best_loss, best_iteration, since_improvement = loss, len(trees), 0
            else:
                since_improvement += 1
                if early_stopping_rounds and since_improvement >= early_stopping_rounds:
                    break

    return GBM(
        features=features,
        trees=trees,
        base_score=base_score,
        learning_rate=learning_rate,
        constraints=constraints,
        params={
            "n_trees": n_trees,
            "max_depth": max_depth,
            "min_child_weight": min_child_weight,
            "l2": l2,
            "gamma": gamma,
            "max_bins": max_bins,
            "feature_fraction": feature_fraction,
            "scale_pos_weight": weight_positive,
            "early_stopping_rounds": early_stopping_rounds,
            "seed": seed,
        },
        best_iteration=best_iteration or len(trees),
        validation_curve=curve,
    )


#: The search space for :func:`tune_gbm`. Named configurations rather than a
#: cross-product: a full grid over four axes is 24 fits, most of them
#: uninformative, and a reviewer cannot tell from a grid definition which
#: hypotheses were actually being tested.
#:
#: Every value brackets LightGBM's documented defaults — depth around its shallow
#: end because SRS §4.3.2 wants a depth-limited credit model, learning rate at and
#: below the default, ``min_child_weight`` and ``lambda_l2`` at the default and one
#: step up. Nothing here is invented: it is the library's own defaults plus a step
#: either side, which is what makes the search reportable.
DEFAULT_GRID: tuple[dict, ...] = (
    {"name": "library-default", "max_depth": 3, "learning_rate": 0.1,
     "min_child_weight": 1.0, "l2": 1.0},
    {"name": "shallow-slow", "max_depth": 3, "learning_rate": 0.05,
     "min_child_weight": 1.0, "l2": 1.0},
    {"name": "deeper", "max_depth": 4, "learning_rate": 0.1,
     "min_child_weight": 1.0, "l2": 1.0},
    {"name": "deeper-regularised", "max_depth": 4, "learning_rate": 0.05,
     "min_child_weight": 20.0, "l2": 10.0},
    {"name": "deepest-regularised", "max_depth": 5, "learning_rate": 0.05,
     "min_child_weight": 20.0, "l2": 10.0},
    {"name": "shallow-heavy-leaf", "max_depth": 3, "learning_rate": 0.05,
     "min_child_weight": 20.0, "l2": 10.0},
)


@dataclass
class TuningResult:
    """What the search tried, and what it chose."""

    best: dict
    trials: list[dict]
    rows_searched: int
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "best": self.best,
            "trials": self.trials,
            "rows_searched": self.rows_searched,
            "note": self.note,
        }


def _run_trial(payload):
    """One grid trial, at module level so a process pool can pickle it."""
    (config, rows, labels, features, constraints, validation,
     n_trees, early_stopping_rounds, max_bins, scale_pos_weight, seed) = payload
    params = {k: v for k, v in config.items() if k != "name"}
    model = fit_gbm(
        rows, labels, features, constraints,
        n_trees=n_trees, max_bins=max_bins, scale_pos_weight=scale_pos_weight,
        validation=validation, early_stopping_rounds=early_stopping_rounds,
        seed=seed, **params,
    )
    loss = min(model.validation_curve) if model.validation_curve else float("inf")
    return {
        "name": config.get("name", ""),
        **params,
        "validation_log_loss": loss,
        "best_iteration": model.best_iteration,
        "trees_grown": len(model.trees),
    }


def tune_gbm(
    rows: Sequence[dict],
    labels: Sequence[int],
    features: Sequence[str],
    constraints: MonotoneConstraints,
    *,
    validation: tuple[Sequence[dict], Sequence[int]],
    grid: Sequence[dict] = DEFAULT_GRID,
    n_trees: int = 200,
    early_stopping_rounds: int = 20,
    max_bins: int = DEFAULT_MAX_BINS,
    scale_pos_weight: float | None = None,
    search_rows: int | None = None,
    seed: int = 0,
    workers: int | None = None,
) -> TuningResult:
    """Search the grid on the validation set, as Phase 1 §4 Step 4 requires.

    Selection is by **validation log-loss**, not by validation AUC. A search that
    optimises AUC picks the configuration that ranks best and says nothing about
    whether its probabilities mean anything; log-loss is a proper scoring rule and
    penalises both. Calibration happens afterwards on rows neither the fit nor
    this search has seen, which is what keeps that ordering honest.

    ``search_rows`` fits the grid on a seeded subsample and refits the winner on
    everything. The alternative — searching at full size — costs the grid's length
    times the full fit, and on a portfolio that is hours for a decision that is
    stable well before then. The subsample size is recorded, because a
    hyperparameter chosen on a tenth of the data is a weaker claim than one chosen
    on all of it, and a reader cannot tell which they have without being told.

    The test set is never touched. That is the point of the step.
    """
    if not grid:
        raise GBMError("an empty grid searches nothing")

    pool = list(range(len(rows)))
    if search_rows is not None and search_rows < len(pool):
        rng = random.Random(seed)
        pool = sorted(rng.sample(pool, search_rows))
    search_x = [rows[i] for i in pool]
    search_y = [labels[i] for i in pool]

    # The configurations are independent, so they run in parallel. Results come
    # back in grid order regardless of which finished first, which keeps the
    # winner reproducible from the seed (WS-0.2.3).
    payloads = [
        (config, search_x, search_y, features, constraints, validation,
         n_trees, early_stopping_rounds, max_bins, scale_pos_weight, seed)
        for config in grid
    ]
    trials = pmap(_run_trial, payloads, workers=workers)

    best: dict | None = None
    for trial in trials:
        if best is None or trial["validation_log_loss"] < best["validation_log_loss"]:
            best = trial

    return TuningResult(
        best=best,
        trials=trials,
        rows_searched=len(search_x),
        note=(
            f"selected by validation log-loss over {len(grid)} configurations on "
            f"{len(search_x)} of {len(rows)} training rows; the test set was not "
            "read (Phase 1 §4 WS-1.1 Step 4)"
        ),
    )


def _log_loss(labels: Sequence[int], probabilities: Sequence[float]) -> float:
    total = 0.0
    for label, p in zip(labels, probabilities):
        p = min(max(p, 1e-12), 1 - 1e-12)
        total -= label * math.log(p) + (1 - label) * math.log(1 - p)
    return total / len(labels)

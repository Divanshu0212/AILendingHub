"""SHAP attributions for the challenger, and exact ones for the champion.

Phase 1 §4 WS-1.1 Step 6: "TreeSHAP at score time; top-5 negative SHAP features →
approved reason-code dictionary `[POLICY: Compliance]`. The mapping table is
*data* (editable by legal), not code."

SRS §4.3.2.3 states what makes SHAP the right tool: the Shapley values φᵢ are the
*unique* attribution satisfying local accuracy (``Σφᵢ = f(x) − E[f]``),
consistency and missingness. Any attribution that violates local accuracy is not
an explanation of the score — it is a plausible story next to it, and the
difference matters when the number is being defended to a customer or a regulator.

Why this computes Shapley values exactly instead of porting TreeSHAP
--------------------------------------------------------------------
TreeSHAP's contribution is *polynomial time* — it makes attribution tractable on
trees deep enough that enumerating feature subsets is hopeless. That is not the
situation here. A credit challenger is depth-limited by design (Phase 1 §4 Step 4;
depth 3 in the reference configuration), so a single tree touches at most a
handful of distinct features, and the exact computation over subsets of *those*
features is cheap. Ensemble Shapley values are additive across trees, so summing
per-tree exact values gives the exact ensemble attribution.

Exactness is worth more than speed here, because a subtly wrong TreeSHAP port
produces attributions that look entirely reasonable and are wrong in a way no
reviewer can see. :data:`MAX_EXACT_FEATURES_PER_TREE` guards the assumption: a
tree using more distinct features than that raises rather than silently taking
minutes, and the Track B path is the SHAP library's TreeSHAP.

The estimand
------------
This is the **path-dependent** (tree-structure) formulation: absent features are
marginalised using the training cover recorded on each node, which is what the
model itself saw. It matches ``shap.TreeExplainer(...)`` with its default
``feature_perturbation="tree_path_dependent"``. The interventional variant needs a
background dataset and answers a different question; mixing the two is a common
way to get attributions that do not reconcile between two reports.

Workstream: WS-1.1 Step 6 · SRS §4.3.2, §11.2
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import factorial
from typing import Sequence

from .gbm import GBM, Node

#: A tree touching more distinct features than this makes exact enumeration
#: expensive. Depth-3 trees touch at most 7, so the limit is generous for the
#: shipped configuration and still fires before anyone waits minutes for a score.
MAX_EXACT_FEATURES_PER_TREE = 12


class ExplainError(Exception):
    """The attribution cannot be computed as requested."""


@dataclass(frozen=True)
class Attribution:
    """One feature's contribution to one score, in log-odds."""

    feature: str
    value: object
    shap: float

    def to_dict(self) -> dict:
        return {"feature": self.feature, "value": self.value, "shap": self.shap}


@dataclass
class Explanation:
    """A complete, checkable attribution of one score."""

    base_value: float
    """``E[f]`` — the model's output with no feature known."""

    attributions: list[Attribution]
    raw_score: float

    @property
    def reconciles(self) -> bool:
        """Local accuracy: the attributions must sum to the score minus the base.

        Checked rather than assumed. An explanation that does not reconcile is
        not an explanation, and this is the one property that catches almost every
        implementation error in an attribution method.
        """
        total = self.base_value + sum(a.shap for a in self.attributions)
        return abs(total - self.raw_score) < 1e-6

    def adverse(self, top: int = 5) -> list[Attribution]:
        """The attributions pushing the score toward the adverse outcome.

        For a PD model the positive class is default, so a *positive* SHAP value
        raises the probability of default and is therefore adverse. Getting this
        sign backwards produces reason codes listing the applicant's strengths as
        the reasons they were declined — which reads as plausible and is exactly
        wrong.
        """
        adverse = [a for a in self.attributions if a.shap > 0]
        adverse.sort(key=lambda a: (-a.shap, a.feature))
        return adverse[:top]

    def to_dict(self) -> dict:
        return {
            "base_value": self.base_value,
            "raw_score": self.raw_score,
            "reconciles": self.reconciles,
            "attributions": [a.to_dict() for a in self.attributions],
        }


def _tree_features(node: Node, seen: set[str]) -> set[str]:
    if node.is_leaf:
        return seen
    seen.add(node.feature)
    _tree_features(node.left, seen)
    _tree_features(node.right, seen)
    return seen


def _expected_value(node: Node, row: dict, known: frozenset[str]) -> float:
    """``E[tree(x) | x_S]`` — the tree's output knowing only the features in ``S``.

    An unknown feature is marginalised by weighting both children by the training
    cover that flowed down them, which is the path-dependent estimand. Cover, not
    row count: it is the hessian mass the split was actually chosen on.
    """
    if node.is_leaf:
        return node.value

    if node.feature in known:
        value = row.get(node.feature)
        child = node.left if value is None or value <= node.threshold else node.right
        return _expected_value(child, row, known)

    total = node.left.cover + node.right.cover
    if total <= 0:
        return (
            _expected_value(node.left, row, known)
            + _expected_value(node.right, row, known)
        ) / 2.0
    return (
        node.left.cover * _expected_value(node.left, row, known)
        + node.right.cover * _expected_value(node.right, row, known)
    ) / total


def tree_shap(node: Node, row: dict) -> tuple[float, dict[str, float]]:
    """Exact Shapley values for one tree, plus its base value."""
    features = sorted(_tree_features(node, set()))
    base = _expected_value(node, row, frozenset())

    if not features:
        return base, {}
    if len(features) > MAX_EXACT_FEATURES_PER_TREE:
        raise ExplainError(
            f"tree uses {len(features)} distinct features, above the "
            f"{MAX_EXACT_FEATURES_PER_TREE} exact-enumeration limit. Depth-limited "
            "credit trees do not reach this; a tree that does needs the polynomial "
            "TreeSHAP algorithm — use the Track B SHAP adapter."
        )

    # Memoise E[f | S] once per subset: every feature's marginal reuses the same
    # coalition values, and recomputing them per feature is the difference
    # between a fast exact method and an unusable one.
    cache: dict[frozenset[str], float] = {}

    def value_of(subset: frozenset[str]) -> float:
        if subset not in cache:
            cache[subset] = _expected_value(node, row, subset)
        return cache[subset]

    n = len(features)
    weights = {
        size: factorial(size) * factorial(n - size - 1) / factorial(n)
        for size in range(n)
    }

    shap = {feature: 0.0 for feature in features}
    others = {feature: [f for f in features if f != feature] for feature in features}
    for feature in features:
        rest = others[feature]
        for size in range(n):
            weight = weights[size]
            for subset in combinations(rest, size):
                without = frozenset(subset)
                shap[feature] += weight * (value_of(without | {feature}) - value_of(without))
    return base, shap


def explain_gbm(model: GBM, row: dict) -> Explanation:
    """Exact SHAP attribution of one GBM score, in raw log-odds.

    Attributions are on the raw score, not the probability. The probability is a
    non-linear transform of it, so probability-space attributions do not sum to
    the probability and are not Shapley values of anything — a distinction that
    disappears silently if the transform is applied to the attributions instead
    of the total.
    """
    trees = model.trees[: model.best_iteration or len(model.trees)]
    total: dict[str, float] = {}
    base = model.base_score

    for tree in trees:
        tree_base, contributions = tree_shap(tree, row)
        base += model.learning_rate * tree_base
        for feature, value in contributions.items():
            total[feature] = total.get(feature, 0.0) + model.learning_rate * value

    attributions = [
        Attribution(feature=name, value=row.get(name), shap=total.get(name, 0.0))
        for name in model.features
    ]
    return Explanation(
        base_value=base, attributions=attributions, raw_score=model.raw_score(row)
    )


def explain_scorecard(scorecard, row: dict) -> Explanation:
    """Attribution of a scorecard score.

    For a linear model on binned inputs the Shapley values are the centred
    per-characteristic contributions — exactly, with no approximation and no
    background sample. This is the reason the champion is a scorecard: the
    explanation is the model rather than an estimate of it (SRS §4.3.1, "reason
    codes are free").

    Signs are aligned with :func:`explain_gbm`: positive means "pushes toward
    default", so both models' attributions feed the same reason-code mapping.
    """
    expected = {}
    for characteristic in scorecard.characteristics:
        binning = characteristic.binning
        total = sum(b.count for b in binning.bins)
        if total == 0:
            raise ExplainError(f"{binning.feature}: binning has no population to average over")
        expected[characteristic.name] = sum(
            b.count * b.woe for b in binning.bins
        ) / total

    attributions = []
    for characteristic in scorecard.characteristics:
        woe = characteristic.binning.transform(row[characteristic.name])
        centred = characteristic.coefficient * (woe - expected[characteristic.name])
        # log_odds() is the log-odds of *good*; the reason-code convention is
        # "positive pushes toward default", so the sign flips here once, in one
        # place, rather than at every call site.
        attributions.append(
            Attribution(
                feature=characteristic.name,
                value=row[characteristic.name],
                shap=-centred,
            )
        )

    base = -(
        scorecard.intercept
        + sum(
            c.coefficient * expected[c.name] for c in scorecard.characteristics
        )
    )
    return Explanation(
        base_value=base,
        attributions=attributions,
        raw_score=-scorecard.log_odds(row),
    )


def global_importance(
    model: GBM, rows: Sequence[dict], *, limit: int | None = None
) -> list[tuple[str, float]]:
    """Mean absolute SHAP per feature — the model-documentation summary.

    ``limit`` samples the rows. Global SHAP on a full portfolio is expensive and
    the ranking stabilises quickly, but a sampled figure must be labelled as one:
    the returned value is a mean over whatever was passed, and the caller records
    the sample size.
    """
    subset = rows[:limit] if limit else rows
    if not subset:
        raise ExplainError("cannot summarise importance over zero rows")

    totals: dict[str, float] = {name: 0.0 for name in model.features}
    for row in subset:
        for attribution in explain_gbm(model, row).attributions:
            totals[attribution.feature] += abs(attribution.shap)

    return sorted(
        ((name, total / len(subset)) for name, total in totals.items()),
        key=lambda pair: (-pair[1], pair[0]),
    )

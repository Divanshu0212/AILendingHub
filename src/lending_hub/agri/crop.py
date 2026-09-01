"""Model B — crop classification: the baseline and the earn-it rule (WS-2.2).

Phase 2 §4 specifies fine-tuning **Presto** per agro-zone, against a Random
Forest baseline on NDVI time-series statistics, with one unusually good
instruction attached:

    Presto ships only if >= +5 macro-F1 points over the baseline (complexity
    must be earned).

**Presto is not ported here** (ADR-0013): it is a pretrained remote-sensing
transformer, there is no imagery to fine-tune it on and no ground truth to
fine-tune it against. What ships is the half of that sentence that decides
whether it would ever be deployed — the baseline, the metric, and the
comparison — plus the two output rules the phase file attaches to the
classifier.

The baseline is the deliverable, not the fallback
--------------------------------------------------
Phase 2 §6 lists "RF baseline + fallback yield regression (kept, documented)" as
its own checklist item. That is the right instinct: the baseline is what the
comparison is *against*, so a baseline built carelessly makes the challenger
look good, and nobody audits a challenger that won. The features here are the
standard NDVI time-series statistics — peak, integral, amplitude, timing,
green-up and senescence rates — because those are what separate crops
phenologically, and a classifier that beats them has learned something a
phenological summary does not contain.

Two output rules, both from the phase file
-------------------------------------------
* **Fallow is a first-class label**, not the absence of a prediction. A model
  that can only say "not any of these crops" cannot distinguish an unsown plot
  from an unfamiliar one, and the non-sowing flag in WS-2.4(c) is built on
  exactly that distinction.
* **Below 0.6 confidence the answer is "unsure"**, never a forced class. The
  probability is calibrated first (temperature scaling), because an uncalibrated
  softmax confidence is not a probability and thresholding it at 0.6 thresholds
  an arbitrary monotone transform of one.

The class set is not ours to choose
-------------------------------------
:class:`ClassSet` requires a ratified zone crop list (LH-404). This is not a
downstream filter that can be applied later: the class set is the label space, so
a set chosen by an engineer decides what the model can *ever* predict, and adding
a class afterwards means retraining rather than reconfiguring.

What this does not port
-----------------------
No Presto, no transformer, no pretrained weights, no CropHarvest loader. The
Random Forest here is a real forest — bootstrap resampling, per-split feature
subsampling, Gini impurity — but it has no out-of-bag scoring, no proximity
matrix and no permutation importance beyond the split-count kind. Temperature
scaling is a one-parameter fit by golden-section search rather than LBFGS.

Workstream: WS-2.2 Model B (SRS §3.4.2)
"""

from __future__ import annotations

import math
import random
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Mapping, Sequence

from lending_hub.agri.indices import IndexSeries, VegetationIndexError
from lending_hub.definitions.provenance import Pending

#: The confidence below which a prediction is reported as "unsure" rather than
#: forced to a class. `[SPEC]` — Phase 2 §4 WS-2.2 Model B: "predictions < 0.6
#: confidence surface as 'unsure', never forced."
UNSURE_THRESHOLD = 0.6

#: Macro-F1 improvement Presto must show over the RF baseline to ship.
#: `[SPEC]` — Phase 2 §4: ">= +5 macro-F1 points over the baseline (complexity
#: must be earned)". Expressed in points, not a fraction, because the phase file
#: does.
COMPLEXITY_EARNED_MARGIN_POINTS = 5.0

#: The label every zone crop list must contain, whatever else is in it.
#: `[SPEC]` — Phase 2 §4: "Class set = ratified zone crop list **+ fallow**
#: (first-class label)".
FALLOW = "fallow"

#: The ratified per-zone crop list. Phase 2 §8 do-not-invent — it is the
#: classifier's label space, so it cannot be chosen here and cannot be widened
#: later without retraining.
ZONE_CROP_LIST = Pending(
    owner="Agri Credit Head",
    ticket="LH-404",
    note="the ratified qualifying-crop list per agro-climatic zone",
)


class CropError(Exception):
    """A classifier cannot be fitted, evaluated, or asked for a prediction."""


@dataclass(frozen=True)
class ClassSet:
    """The label space for one agro-zone: ratified crops plus fallow.

    Constructed only from a ratified list. :meth:`from_policy` is the sole
    entry point and it demands a decision reference, mirroring
    ``MonotoneConstraints.from_policy`` in the Phase 1 GBM — an unratified label
    space is exactly as unusable as an unratified constraint list, and for the
    same reason: it is a policy choice wearing an engineering shape.
    """

    zone: str
    crops: tuple[str, ...]
    decision_reference: str

    def __post_init__(self) -> None:
        if not self.crops:
            raise CropError(f"{self.zone}: an empty class set predicts nothing")
        if FALLOW not in self.crops:
            raise CropError(
                f"{self.zone}: {FALLOW!r} must be in the class set. Phase 2 §4 "
                "makes it a first-class label, because a model that can only "
                "say 'not any of these crops' cannot tell an unsown plot from "
                "an unfamiliar one — and the non-sowing flag is built on "
                "exactly that distinction."
            )
        if len(set(self.crops)) != len(self.crops):
            duplicates = [c for c, n in Counter(self.crops).items() if n > 1]
            raise CropError(f"{self.zone}: duplicate classes {duplicates}")
        if not self.decision_reference:
            raise CropError(
                f"{self.zone}: a class set needs the ratification reference that "
                "approved it (LH-404)"
            )

    @classmethod
    def from_policy(
        cls, zone: str, crops: Sequence[str], *, decision_reference: str
    ) -> ClassSet:
        """Build from a ratified zone crop list.

        ``fallow`` is appended if absent — it is `[SPEC]` rather than policy, so
        a committee list that omits it is not wrong, it is just not the whole
        label space.
        """
        ordered = list(crops)
        if FALLOW not in ordered:
            ordered.append(FALLOW)
        return cls(zone=zone, crops=tuple(ordered), decision_reference=decision_reference)

    def index(self, crop: str) -> int:
        try:
            return self.crops.index(crop)
        except ValueError as exc:
            raise CropError(
                f"{crop!r} is not in {self.zone}'s ratified class set "
                f"{list(self.crops)}. A crop outside the label space cannot be "
                "predicted or scored; widening the set means retraining."
            ) from exc

    def __len__(self) -> int:
        return len(self.crops)


# ---------------------------------------------------------------------------
# Phenological features — the baseline's inputs
# ---------------------------------------------------------------------------


def phenology_features(series: IndexSeries, season_start: date, season_end: date) -> dict:
    """NDVI time-series statistics that separate crops phenologically.

    These are the RF baseline's features, and the reason the baseline is a real
    contender rather than a formality: crops differ in *when* they green up, how
    fast, how long they hold peak, and how sharply they senesce, and a summary
    carrying all four is hard to beat with anything that has not learned
    something genuinely additional.

    Raises rather than imputing when the season was not observed. A crop
    classified from two cloudy revisits is a classification of the cloud.
    """
    window = [
        o
        for o in series.valid
        if season_start <= o.acquired <= season_end
    ]
    if len(window) < 4:
        raise CropError(
            f"{series.plot_id}: {len(window)} valid observations in "
            f"{season_start}..{season_end}; a phenological summary needs at "
            "least 4. Classifying from fewer classifies the cloud."
        )

    values = [o.value for o in window]
    days = [(o.acquired - season_start).days for o in window]
    peak_index = max(range(len(values)), key=lambda i: values[i])

    # Trapezoidal integral of the index over the season — the standard proxy for
    # accumulated biomass, and the single most discriminative summary statistic.
    integral = sum(
        (values[i] + values[i + 1]) / 2 * (days[i + 1] - days[i])
        for i in range(len(values) - 1)
    )

    green_up = _slope(days[: peak_index + 1], values[: peak_index + 1])
    senescence = _slope(days[peak_index:], values[peak_index:])

    return {
        "ndvi_peak": values[peak_index],
        "ndvi_mean": sum(values) / len(values),
        "ndvi_min": min(values),
        "ndvi_amplitude": max(values) - min(values),
        "ndvi_integral": integral,
        "days_to_peak": float(days[peak_index]),
        "green_up_rate": green_up,
        "senescence_rate": senescence,
        "observations": float(len(window)),
    }


def _slope(days: Sequence[float], values: Sequence[float]) -> float:
    """Least-squares slope of index against day; 0.0 for a degenerate segment."""
    if len(days) < 2:
        return 0.0
    n = len(days)
    mean_x = sum(days) / n
    mean_y = sum(values) / n
    denominator = sum((x - mean_x) ** 2 for x in days)
    if denominator == 0:
        return 0.0
    return sum((x - mean_x) * (y - mean_y) for x, y in zip(days, values)) / denominator


# ---------------------------------------------------------------------------
# The Random Forest baseline
# ---------------------------------------------------------------------------


@dataclass
class _TreeNode:
    feature: str | None = None
    threshold: float = 0.0
    left: "_TreeNode | None" = None
    right: "_TreeNode | None" = None
    distribution: tuple[float, ...] = ()

    @property
    def is_leaf(self) -> bool:
        return self.feature is None


def _gini(counts: Sequence[int]) -> float:
    total = sum(counts)
    if total == 0:
        return 0.0
    return 1.0 - sum((c / total) ** 2 for c in counts)


def _build_tree(
    rows: Sequence[dict],
    labels: Sequence[int],
    features: Sequence[str],
    n_classes: int,
    *,
    depth: int,
    max_depth: int,
    min_samples_leaf: int,
    features_per_split: int,
    rng: random.Random,
) -> _TreeNode:
    counts = [0] * n_classes
    for label in labels:
        counts[label] += 1

    if (
        depth >= max_depth
        or len(labels) < 2 * min_samples_leaf
        or sum(1 for c in counts if c) == 1
    ):
        total = sum(counts)
        return _TreeNode(distribution=tuple(c / total for c in counts))

    candidates = rng.sample(list(features), min(features_per_split, len(features)))
    best = None
    parent_impurity = _gini(counts)

    for feature in candidates:
        values = sorted({row[feature] for row in rows})
        if len(values) < 2:
            continue
        for a, b in zip(values, values[1:]):
            threshold = (a + b) / 2
            left_counts = [0] * n_classes
            right_counts = [0] * n_classes
            for row, label in zip(rows, labels):
                if row[feature] <= threshold:
                    left_counts[label] += 1
                else:
                    right_counts[label] += 1
            left_total, right_total = sum(left_counts), sum(right_counts)
            if left_total < min_samples_leaf or right_total < min_samples_leaf:
                continue
            total = left_total + right_total
            weighted = (
                left_total / total * _gini(left_counts)
                + right_total / total * _gini(right_counts)
            )
            gain = parent_impurity - weighted
            if best is None or gain > best[0]:
                best = (gain, feature, threshold)

    if best is None or best[0] <= 0:
        total = sum(counts)
        return _TreeNode(distribution=tuple(c / total for c in counts))

    _, feature, threshold = best
    left_rows, left_labels, right_rows, right_labels = [], [], [], []
    for row, label in zip(rows, labels):
        if row[feature] <= threshold:
            left_rows.append(row)
            left_labels.append(label)
        else:
            right_rows.append(row)
            right_labels.append(label)

    return _TreeNode(
        feature=feature,
        threshold=threshold,
        left=_build_tree(
            left_rows, left_labels, features, n_classes,
            depth=depth + 1, max_depth=max_depth,
            min_samples_leaf=min_samples_leaf,
            features_per_split=features_per_split, rng=rng,
        ),
        right=_build_tree(
            right_rows, right_labels, features, n_classes,
            depth=depth + 1, max_depth=max_depth,
            min_samples_leaf=min_samples_leaf,
            features_per_split=features_per_split, rng=rng,
        ),
    )


def _tree_predict(node: _TreeNode, row: Mapping) -> tuple[float, ...]:
    while not node.is_leaf:
        node = node.left if row[node.feature] <= node.threshold else node.right
    return node.distribution


@dataclass(frozen=True)
class RandomForest:
    """The Phase 2 §4 baseline: RF on NDVI time-series statistics.

    Deliberately a real forest rather than a token one. The phase file makes
    this the bar Presto must clear by 5 macro-F1 points, and a weak baseline
    hands the challenger a margin it did not earn — after which nobody audits a
    challenger that won.
    """

    class_set: ClassSet
    features: tuple[str, ...]
    trees: tuple[_TreeNode, ...]
    temperature: float = 1.0

    def probabilities(self, row: Mapping) -> tuple[float, ...]:
        """Calibrated class probabilities, averaged over the forest.

        Temperature scaling is applied in log space over the averaged vote, so
        ``temperature == 1.0`` is exactly the uncalibrated forest.
        """
        missing = [f for f in self.features if f not in row]
        if missing:
            raise CropError(f"row is missing features {missing}")

        totals = [0.0] * len(self.class_set)
        for tree in self.trees:
            for i, p in enumerate(_tree_predict(tree, row)):
                totals[i] += p
        averaged = [t / len(self.trees) for t in totals]

        if self.temperature == 1.0:
            return tuple(averaged)
        return _temperature_apply(averaged, self.temperature)

    def predict(self, row: Mapping) -> "Prediction":
        probabilities = self.probabilities(row)
        best = max(range(len(probabilities)), key=lambda i: probabilities[i])
        return Prediction(
            crop=self.class_set.crops[best],
            confidence=probabilities[best],
            distribution=probabilities,
            class_set=self.class_set,
        )


@dataclass(frozen=True)
class Prediction:
    """A crop prediction that is allowed to decline to answer."""

    crop: str
    confidence: float
    distribution: tuple[float, ...]
    class_set: ClassSet

    @property
    def is_unsure(self) -> bool:
        """`[SPEC]` Phase 2 §4: below 0.6 the prediction is 'unsure'."""
        return self.confidence < UNSURE_THRESHOLD

    @property
    def label(self) -> str:
        """What may be shown or stored: the crop, or ``"unsure"``.

        Note that ``fallow`` is a *crop* here and comes back as itself. "Unsure"
        and "fallow" are opposite claims — one says the plot was not sown, the
        other says we could not tell — and the non-sowing flag depends on
        keeping them apart.
        """
        return "unsure" if self.is_unsure else self.crop


def fit_random_forest(
    rows: Sequence[Mapping],
    labels: Sequence[str],
    class_set: ClassSet,
    features: Sequence[str],
    *,
    n_trees: int = 100,
    max_depth: int = 8,
    min_samples_leaf: int = 3,
    features_per_split: int | None = None,
    seed: int = 0,
) -> RandomForest:
    """Fit the baseline. Bootstrap resampling, sqrt(p) features per split."""
    if len(rows) != len(labels):
        raise CropError(f"{len(rows)} rows against {len(labels)} labels")
    if not rows:
        raise CropError("cannot fit a classifier on an empty sample")

    encoded = [class_set.index(label) for label in labels]
    present = set(encoded)
    if len(present) < 2:
        raise CropError(
            f"only {len(present)} class present in the training labels; a "
            "classifier fitted on one class predicts that class everywhere and "
            "reports perfect accuracy for it"
        )

    per_split = features_per_split or max(1, int(math.sqrt(len(features))))
    rng = random.Random(seed)
    trees = []
    for _ in range(n_trees):
        indices = [rng.randrange(len(rows)) for _ in range(len(rows))]
        trees.append(
            _build_tree(
                [dict(rows[i]) for i in indices],
                [encoded[i] for i in indices],
                features,
                len(class_set),
                depth=0,
                max_depth=max_depth,
                min_samples_leaf=min_samples_leaf,
                features_per_split=per_split,
                rng=rng,
            )
        )

    return RandomForest(
        class_set=class_set, features=tuple(features), trees=tuple(trees)
    )


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------


def _temperature_apply(
    probabilities: Sequence[float], temperature: float
) -> tuple[float, ...]:
    """Divide the logits by T and re-normalise."""
    floor = 1e-12
    logits = [math.log(max(p, floor)) / temperature for p in probabilities]
    peak = max(logits)
    exponentiated = [math.exp(z - peak) for z in logits]
    total = sum(exponentiated)
    return tuple(e / total for e in exponentiated)


def fit_temperature(
    forest: RandomForest,
    rows: Sequence[Mapping],
    labels: Sequence[str],
    *,
    bounds: tuple[float, float] = (0.05, 10.0),
    tolerance: float = 1e-4,
) -> RandomForest:
    """Fit a single temperature by minimising NLL on a held-out set.

    Phase 2 §4 requires calibrated per-class probabilities, and the reason is
    the 0.6 abstention rule immediately after it: thresholding an uncalibrated
    confidence thresholds an arbitrary monotone transform of a probability, so
    the "unsure" band would be some other band entirely.

    Golden-section search rather than LBFGS — the objective is one-dimensional
    and unimodal in ``log T``, so a line search is exact enough and needs no
    gradient.

    **This must be fitted on data the forest did not train on.** Nothing here
    can check that, which is why it is said: a temperature fitted in-sample
    calibrates against the forest's memorised training votes, which are already
    near-perfect, and returns a temperature near 1 that changes nothing.
    """
    if len(rows) != len(labels):
        raise CropError(f"{len(rows)} rows against {len(labels)} labels")
    if not rows:
        raise CropError("cannot calibrate on an empty set")

    encoded = [forest.class_set.index(label) for label in labels]
    raw = [forest.probabilities(row) for row in rows]

    def nll(temperature: float) -> float:
        total = 0.0
        for distribution, target in zip(raw, encoded):
            scaled = _temperature_apply(distribution, temperature)
            total -= math.log(max(scaled[target], 1e-12))
        return total / len(raw)

    golden = (math.sqrt(5.0) - 1.0) / 2.0
    low, high = bounds
    c = high - golden * (high - low)
    d = low + golden * (high - low)
    fc, fd = nll(c), nll(d)
    while abs(high - low) > tolerance:
        if fc < fd:
            high, d, fd = d, c, fc
            c = high - golden * (high - low)
            fc = nll(c)
        else:
            low, c, fc = c, d, fd
            d = low + golden * (high - low)
            fd = nll(d)

    return RandomForest(
        class_set=forest.class_set,
        features=forest.features,
        trees=forest.trees,
        temperature=(low + high) / 2.0,
    )


# ---------------------------------------------------------------------------
# Evaluation and the earn-it rule
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClassificationReport:
    """Per-class precision/recall/F1 and the macro average.

    Macro rather than micro, as the phase file specifies, and the difference
    matters here more than usual: an agri class set is severely imbalanced —
    one or two staples dominate a zone — so micro-F1 is nearly the majority
    crop's recall, and a model that never predicts a minor crop scores well on
    it. Macro-F1 weights every crop equally, including the ones a lending
    decision most needs distinguished.
    """

    per_class: Mapping[str, Mapping[str, float]]
    macro_f1: float
    accuracy: float
    support: Mapping[str, int]
    unsure_share: float
    n: int

    @property
    def macro_f1_points(self) -> float:
        """Macro-F1 in points, the unit the phase file states its margin in."""
        return self.macro_f1 * 100.0


def classification_report(
    predictions: Sequence[Prediction], truth: Sequence[str], class_set: ClassSet
) -> ClassificationReport:
    """Score predictions against ground truth.

    Unsure predictions are **counted as errors** for every class. That is the
    conservative choice and it is deliberate: abstention has an operational cost
    (LH-409 — somebody must go and look), and a metric that excluded abstentions
    would improve monotonically as the model declined to answer more often.
    """
    if len(predictions) != len(truth):
        raise CropError(f"{len(predictions)} predictions against {len(truth)} labels")
    if not predictions:
        raise CropError("cannot score an empty prediction set")

    labels = [p.label for p in predictions]
    support = Counter(truth)
    per_class: dict[str, dict[str, float]] = {}
    f1_scores = []

    for crop in class_set.crops:
        true_positive = sum(1 for p, t in zip(labels, truth) if p == crop and t == crop)
        predicted = sum(1 for p in labels if p == crop)
        actual = support.get(crop, 0)

        precision = true_positive / predicted if predicted else 0.0
        recall = true_positive / actual if actual else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision + recall
            else 0.0
        )
        per_class[crop] = {"precision": precision, "recall": recall, "f1": f1}
        # A class with no ground-truth support contributes nothing to the macro
        # average — including it would let a zone's macro-F1 be diluted by crops
        # that never occur there.
        if actual:
            f1_scores.append(f1)

    if not f1_scores:
        raise CropError("no class has ground-truth support; macro-F1 is undefined")

    return ClassificationReport(
        per_class=per_class,
        macro_f1=sum(f1_scores) / len(f1_scores),
        accuracy=sum(1 for p, t in zip(labels, truth) if p == t) / len(truth),
        support=dict(support),
        unsure_share=sum(1 for p in predictions if p.is_unsure) / len(predictions),
        n=len(predictions),
    )


@dataclass(frozen=True)
class ComplexityVerdict:
    """Whether a challenger earned its complexity (Phase 2 §4)."""

    baseline_macro_f1_points: float
    challenger_macro_f1_points: float
    margin_points: float
    required_points: float

    @property
    def earned(self) -> bool:
        return self.margin_points >= self.required_points

    @property
    def why_not(self) -> str:
        if self.earned:
            return ""
        return (
            f"challenger gained {self.margin_points:+.2f} macro-F1 points over "
            f"the baseline, short of the {self.required_points:.1f} the phase "
            "file requires. Phase 2 §4: complexity must be earned."
        )


def complexity_earned(
    baseline: ClassificationReport,
    challenger: ClassificationReport,
    *,
    required_points: float = COMPLEXITY_EARNED_MARGIN_POINTS,
) -> ComplexityVerdict:
    """Apply the phase file's ship/no-ship rule to two held-out reports.

    Both reports must come from the **same held-out set**. Nothing here can
    verify that, and it is the way this comparison goes wrong in practice: a
    challenger evaluated on a different or larger sample can clear five points
    on sampling noise alone.
    """
    if baseline.n != challenger.n:
        raise CropError(
            f"baseline scored {baseline.n} plots and the challenger "
            f"{challenger.n}. A margin between two different held-out sets is "
            "not a margin; it is a difference in samples."
        )
    margin = challenger.macro_f1_points - baseline.macro_f1_points
    return ComplexityVerdict(
        baseline_macro_f1_points=baseline.macro_f1_points,
        challenger_macro_f1_points=challenger.macro_f1_points,
        margin_points=margin,
        required_points=required_points,
    )

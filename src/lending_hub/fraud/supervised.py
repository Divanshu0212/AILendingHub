"""Layer 1 — the supervised fraud model, and the label problem underneath it.

Phase 1 §4 WS-1.2 Step 3: "LightGBM on confirmed-fraud labels (historical
fraud-desk dispositions). If `[DATA]` confirmed frauds < 200 → ship rules +
anomaly layer only; log limitation. Imbalance: ``scale_pos_weight``. Evaluation:
AUC-PR and **recall @ 0.5% alert rate** on out-of-time months — never accuracy."

The scope test cannot be evaluated yet, and that is the finding
---------------------------------------------------------------
The instruction reads as though "how many confirmed frauds do we have" is a
question someone can go and count. It is not. Master Appendix A defines confirmed
fraud as "a fraud-desk disposition code in the approved taxonomy", and that
taxonomy is `[POLICY: Fraud Head]` and does not exist (LH-101). Until it does,
every count is a count of *something*, and which something depends on which codes
someone decided to include — which is precisely the decision the taxonomy is.

So the scope test here is three-valued, not two. ``TAXONOMY_BLOCKED`` is a
different state from ``BELOW_MINIMUM``, and collapsing them lets "we have 150
frauds, so scorecard-only" be reported when the truth is "nobody has said what
counts as a fraud". The first is a data limitation; the second is an ungrounded
definition, and only the second means the number on the slide is meaningless.

Evaluation rate versus operating budget
---------------------------------------
Phase 1 names 0.5% as the rate to *evaluate* recall at, which is `[SPEC]` and
lives here as a constant. The alert rate the desk actually runs at is a capacity
and risk-appetite decision, `[POLICY: Fraud Head]` (LH-206). They are different
numbers with the same units, and using the evaluation rate as an operating budget
because it was the one written down is an easy and expensive mistake.

Never accuracy. On a base rate below 1%, "predict nobody is a fraudster" scores
above 99%.

Workstream: WS-1.2 Step 3 · SRS §5.3.1, §5.4
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence

from lending_hub.definitions import CONFIRMED_FRAUD_DISPOSITION_CODES, Pending
from lending_hub.scoring.gbm import GBM, MonotoneConstraints, fit_gbm

#: Phase 1 §4 WS-1.2 Step 3 [SPEC]: below this many confirmed frauds the
#: supervised layer is out of scope and the rules plus anomaly layers ship alone.
MINIMUM_CONFIRMED_FRAUDS = 200

#: Phase 1 §4 WS-1.2 Step 3 [SPEC]: the alert rate recall is *evaluated* at.
#: Not the operating budget — see the module docstring.
EVALUATION_ALERT_RATE = 0.005

#: Phase 1 §7 and SRS §5.4 [SPEC]: "step-up friction on eventual-good customers
#: < 3%". A ceiling on how many good customers the fraud stack may inconvenience.
MAX_STEP_UP_FRICTION = 0.03

#: The rate the desk actually runs at.
ALERT_BUDGET = Pending(
    owner="Fraud Head",
    ticket="LH-206",
    note=(
        "the operating alert budget: what fraction of applications the desk can "
        "review, given its capacity and the bank's risk appetite. Phase 1 §8 "
        "do-not-invent. Distinct from the 0.5% evaluation rate, which is [SPEC]"
    ),
)


class FraudModelError(Exception):
    """The supervised layer cannot be fitted or evaluated as requested."""


class Scope(str, Enum):
    """Whether the supervised layer is in scope for this release."""

    TAXONOMY_BLOCKED = "taxonomy_blocked"
    """No approved disposition taxonomy, so no count of confirmed frauds means
    anything yet (LH-101)."""

    BELOW_MINIMUM = "below_minimum"
    """Taxonomy exists; too few confirmed frauds. Rules plus anomaly only."""

    IN_SCOPE = "in_scope"


def supervised_layer_scope(
    *, taxonomy_ratified: bool, confirmed_frauds: int | None
) -> tuple[Scope, str]:
    """Evaluate Phase 1's scope test, three-valued."""
    if not taxonomy_ratified:
        return Scope.TAXONOMY_BLOCKED, (
            f"{CONFIRMED_FRAUD_DISPOSITION_CODES} — Appendix A defines confirmed "
            "fraud as a disposition code in the approved taxonomy, and the taxonomy "
            "does not exist. The count of confirmed frauds is therefore not a "
            "number anyone can produce, so Phase 1's < 200 test cannot be "
            "evaluated at all. This is not the same as having too few."
        )
    if confirmed_frauds is None:
        raise FraudModelError(
            "a ratified taxonomy without a count: run the count before deciding scope"
        )
    if confirmed_frauds < MINIMUM_CONFIRMED_FRAUDS:
        return Scope.BELOW_MINIMUM, (
            f"{confirmed_frauds} confirmed frauds is below the Phase 1 §4 WS-1.2 "
            f"Step 3 floor of {MINIMUM_CONFIRMED_FRAUDS}: ship rules and the "
            "anomaly layer, and log the limitation"
        )
    return Scope.IN_SCOPE, (
        f"{confirmed_frauds} confirmed frauds meets the Phase 1 floor of "
        f"{MINIMUM_CONFIRMED_FRAUDS}"
    )


@dataclass(frozen=True)
class FraudLabels:
    """Confirmed-fraud labels, carrying the taxonomy that defined them.

    The labels and their definition travel together, because a fraud label is
    meaningless without the code set that produced it — and a model trained under
    one taxonomy and evaluated under another compares two different targets.
    """

    labels: list[int]
    taxonomy_ratified: bool
    taxonomy_provenance: str

    @classmethod
    def from_taxonomy(cls, labels: Sequence[int], *, decision_reference: str):
        if not decision_reference:
            raise FraudModelError(
                "ratified fraud labels must cite the taxonomy decision that defined "
                "them (Master Appendix A, Confirmed fraud)"
            )
        return cls(list(labels), True, decision_reference)

    @classmethod
    def for_experiment(cls, labels: Sequence[int], *, reason: str):
        """Proxy labels, for exercising the code path. Never promotable."""
        if not reason:
            raise FraudModelError(
                "proxy fraud labels need a written reason. Confirmed fraud is "
                "[POLICY: Fraud Head] (LH-101); anything else is a stand-in and the "
                "model must be stamped as trained on one."
            )
        return cls(list(labels), False, f"proxy labels, not confirmed fraud: {reason}")

    @property
    def confirmed(self) -> int:
        return sum(self.labels)


@dataclass
class FraudModel:
    """The supervised layer, with its governance state attached."""

    gbm: GBM
    labels: FraudLabels
    scope: Scope
    scope_note: str
    anomaly_feature_used: bool = False

    @property
    def promotable(self) -> tuple[bool, str]:
        if not self.labels.taxonomy_ratified:
            return False, (
                "trained on proxy labels, not confirmed fraud (LH-101): Master "
                "Appendix A requires a disposition code in the approved taxonomy, "
                "and suspicion is not a label"
            )
        if self.scope is not Scope.IN_SCOPE:
            return False, self.scope_note
        return self.gbm.promotable

    def predict(self, row: dict) -> float:
        return self.gbm.predict(row)

    def predict_all(self, rows: Sequence[dict]) -> list[float]:
        return self.gbm.predict_all(rows)

    def to_dict(self) -> dict:
        promotable, note = self.promotable
        return {
            "kind": "supervised_fraud_gbm",
            "scope": self.scope.value,
            "scope_note": self.scope_note,
            "taxonomy_ratified": self.labels.taxonomy_ratified,
            "taxonomy_provenance": self.labels.taxonomy_provenance,
            "confirmed_frauds": self.labels.confirmed,
            "anomaly_feature_stacked": self.anomaly_feature_used,
            "alert_budget": str(ALERT_BUDGET),
            "promotable": promotable,
            "promotion_note": note,
            "gbm": self.gbm.to_dict(),
        }


def fit_fraud_model(
    rows: Sequence[dict],
    labels: FraudLabels,
    features: Sequence[str],
    constraints: MonotoneConstraints,
    *,
    scale_pos_weight: float | None = None,
    **kwargs,
) -> FraudModel:
    """Fit Layer 1.

    ``scale_pos_weight`` defaults to the inverse base rate, which is the standard
    handling for the imbalance and the one the phase file names. It is computed
    rather than fixed so it tracks the sample it was fitted on.
    """
    from .anomaly import ANOMALY_FEATURE

    if len(rows) != len(labels.labels):
        raise FraudModelError("rows and labels must be the same length")

    positives = labels.confirmed
    negatives = len(labels.labels) - positives
    if positives == 0 or negatives == 0:
        raise FraudModelError("a fraud model needs both confirmed and non-fraud cases")

    scope, note = supervised_layer_scope(
        taxonomy_ratified=labels.taxonomy_ratified,
        confirmed_frauds=positives if labels.taxonomy_ratified else None,
    )

    weight = scale_pos_weight if scale_pos_weight is not None else negatives / positives
    model = fit_gbm(
        rows, labels.labels, features, constraints, scale_pos_weight=weight, **kwargs
    )
    return FraudModel(
        gbm=model,
        labels=labels,
        scope=scope,
        scope_note=note,
        anomaly_feature_used=ANOMALY_FEATURE in features,
    )


def precision_recall_curve(
    labels: Sequence[int], scores: Sequence[float]
) -> list[tuple[float, float, float]]:
    """``(threshold, precision, recall)`` at every distinct score, high to low."""
    if len(labels) != len(scores):
        raise FraudModelError("labels and scores must be the same length")
    positives = sum(labels)
    if positives == 0:
        raise FraudModelError("precision-recall is undefined with no positives")

    order = sorted(range(len(scores)), key=lambda i: -scores[i])
    true_positives = false_positives = 0
    curve: list[tuple[float, float, float]] = []
    index = 0
    while index < len(order):
        stop = index
        while stop + 1 < len(order) and scores[order[stop + 1]] == scores[order[index]]:
            stop += 1
        for position in range(index, stop + 1):
            if labels[order[position]] == 1:
                true_positives += 1
            else:
                false_positives += 1
        curve.append(
            (
                scores[order[index]],
                true_positives / (true_positives + false_positives),
                true_positives / positives,
            )
        )
        index = stop + 1
    return curve


def average_precision(labels: Sequence[int], scores: Sequence[float]) -> float:
    """AUC-PR by the step-wise sum ``Σ (Rₙ − Rₙ₋₁)·Pₙ``.

    The step-wise definition, not trapezoidal interpolation: interpolating between
    PR points overstates the area, and on a rare positive class the overstatement
    is largest exactly where the model is being judged.
    """
    curve = precision_recall_curve(labels, scores)
    total = 0.0
    previous_recall = 0.0
    for _, precision, recall in curve:
        total += (recall - previous_recall) * precision
        previous_recall = recall
    return total


def recall_at_alert_rate(
    labels: Sequence[int], scores: Sequence[float], rate: float = EVALUATION_ALERT_RATE
) -> float:
    """Recall when the top ``rate`` fraction of applications is alerted.

    The metric that matches how the desk works: the queue has a fixed size, and
    the question is how much fraud fits inside it.
    """
    return _at_alert_rate(labels, scores, rate)[1]


def precision_at_alert_rate(
    labels: Sequence[int], scores: Sequence[float], rate: float = EVALUATION_ALERT_RATE
) -> float:
    return _at_alert_rate(labels, scores, rate)[0]


def _at_alert_rate(
    labels: Sequence[int], scores: Sequence[float], rate: float
) -> tuple[float, float]:
    if not 0 < rate <= 1:
        raise FraudModelError("alert rate must be in (0, 1]")
    if len(labels) != len(scores):
        raise FraudModelError("labels and scores must be the same length")
    positives = sum(labels)
    if positives == 0:
        raise FraudModelError("recall is undefined with no confirmed frauds")

    budget = max(1, round(rate * len(labels)))
    order = sorted(range(len(scores)), key=lambda i: -scores[i])
    alerted = order[:budget]
    caught = sum(labels[i] for i in alerted)
    return caught / len(alerted), caught / positives


def step_up_friction(labels: Sequence[int], stepped_up: Sequence[int]) -> float:
    """Fraction of eventual-good customers sent through step-up verification.

    Phase 1 §7 caps this at 3%. It is the customer-experience side of the same
    threshold that sets recall, and leaving it out of the evaluation is how a
    fraud stack ships with excellent recall and an origination funnel that has
    quietly stopped converting.
    """
    if len(labels) != len(stepped_up):
        raise FraudModelError("labels and step-up flags must be the same length")
    goods = [i for i, label in enumerate(labels) if label == 0]
    if not goods:
        raise FraudModelError("no eventual-good customers to measure friction on")
    return sum(stepped_up[i] for i in goods) / len(goods)


@dataclass
class FraudEvaluation:
    """Phase 1 §4 WS-1.2 Step 3 evaluation — never accuracy."""

    n: int
    confirmed_frauds: int
    average_precision: float
    recall_at_evaluation_rate: float
    precision_at_evaluation_rate: float
    step_up_friction: float | None = None
    out_of_time: bool = False
    incumbent_precision: float | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def friction_within_tolerance(self) -> bool | None:
        if self.step_up_friction is None:
            return None
        return self.step_up_friction < MAX_STEP_UP_FRICTION

    def to_dict(self) -> dict:
        return {
            "n": self.n,
            "confirmed_frauds": self.confirmed_frauds,
            "base_rate": self.confirmed_frauds / self.n if self.n else None,
            "average_precision": self.average_precision,
            "evaluation_alert_rate": EVALUATION_ALERT_RATE,
            "recall_at_evaluation_rate": self.recall_at_evaluation_rate,
            "precision_at_evaluation_rate": self.precision_at_evaluation_rate,
            "operating_alert_budget": str(ALERT_BUDGET),
            "step_up_friction": self.step_up_friction,
            "step_up_friction_limit": MAX_STEP_UP_FRICTION,
            "friction_within_tolerance": self.friction_within_tolerance,
            "incumbent_precision": self.incumbent_precision,
            "out_of_time": self.out_of_time,
            "accuracy": (
                "deliberately not reported: on a sub-1% base rate, predicting "
                "nobody is a fraudster scores above 99%"
            ),
            "notes": self.notes,
        }


def evaluate(
    labels: Sequence[int],
    scores: Sequence[float],
    *,
    out_of_time: bool,
    stepped_up: Sequence[int] | None = None,
    incumbent_precision: float | None = None,
    notes: Sequence[str] = (),
) -> FraudEvaluation:
    """Assemble the Step 3 evaluation."""
    return FraudEvaluation(
        n=len(labels),
        confirmed_frauds=sum(labels),
        average_precision=average_precision(labels, scores),
        recall_at_evaluation_rate=recall_at_alert_rate(labels, scores),
        precision_at_evaluation_rate=precision_at_alert_rate(labels, scores),
        step_up_friction=(
            step_up_friction(labels, stepped_up) if stepped_up is not None else None
        ),
        out_of_time=out_of_time,
        incumbent_precision=incumbent_precision,
        notes=list(notes),
    )

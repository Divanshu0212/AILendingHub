"""Fairness measurement for the application scorecard.

Phase 1 §4 WS-1.1 Step 7: "Fairlearn metrics — demographic parity difference,
equalized-odds difference (Hardt et al.) — on gender, age band, geography
(pincode as proxy probe). Results in the model card; mitigation only via the SRS
§4.3.3 ladder; action threshold `[POLICY: Fair-Lending Committee]`."

This module measures and refuses to judge
-----------------------------------------
Every function here returns a number and a sample size. None of them returns
"fair" or "unfair", because the threshold at which a disparity requires action is
`[POLICY: Fair-Lending Committee]` (LH-205) and does not exist yet.
:meth:`FairnessReport.verdict` raises rather than defaulting to a
plausible-looking bar — the four-fifths rule is a US employment-law convention,
not this committee's decision, and a report that quietly adopted it would be
quoted for years as though it had been ratified.

Two measurement decisions worth review
--------------------------------------
**Protected attributes arrive through :class:`ProtectedAttributeAccess`.** Not
through the feature store, not through the row dict. The training path cannot
reach them, so "gender is not a feature" is a property of the wiring rather than
a claim in a document.

**Small groups are flagged, not silently reported.** A 40-applicant group has a
selection rate with a confidence interval wider than most disparities anyone
would act on. Reporting the point estimate alone invites action on noise in one
direction and false reassurance in the other, and the smallest groups are usually
the ones fairness testing exists to protect. Each group therefore carries a Wilson
interval, and the report marks a disparity that is not distinguishable from
sampling variation.

Workstream: WS-1.1 Step 7 · SRS §4.3.3, §11.3
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence

from lending_hub.definitions import Pending, Ungrounded

from .features import PROTECTED_NAMES, ProtectedAttributeAccess

#: Phase 1 §8 and SRS §11.3: the level of disparity that triggers action is the
#: Fair-Lending Committee's to set. Named here so every report can cite it.
FAIRNESS_ACTION_THRESHOLD = Pending(
    owner="Fair-Lending Committee",
    ticket="LH-205",
    note=(
        "the disparity at which a model requires mitigation, and which metric it "
        "is measured on. Phase 1 §8 do-not-invent. The four-fifths rule is a US "
        "employment-law convention, not a ratified Indian lending policy, and "
        "adopting it by default would put an unratified bar into a model card"
    ),
)

#: SRS §4.3.3, in order. The ladder is ordered for a reason: each rung costs more
#: in accuracy and in legal exposure than the one above it.
MITIGATION_LADDER: tuple[str, ...] = (
    "remove_or_neutralise_offending_features",
    "in_processing_reduction",
    "threshold_adjustment",
)


class FairnessError(Exception):
    """The fairness measurement cannot be made as requested."""


class Metric(str, Enum):
    DEMOGRAPHIC_PARITY_DIFFERENCE = "demographic_parity_difference"
    DEMOGRAPHIC_PARITY_RATIO = "demographic_parity_ratio"
    EQUALIZED_ODDS_DIFFERENCE = "equalized_odds_difference"
    EQUAL_OPPORTUNITY_DIFFERENCE = "equal_opportunity_difference"


def _wilson(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a proportion.

    Wilson rather than the normal approximation because approval rates in small
    groups sit near 0 or 1, where the normal interval runs outside [0, 1] and
    understates the uncertainty exactly where it matters most.
    """
    if total == 0:
        return (0.0, 1.0)
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    spread = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return (max(0.0, centre - spread), min(1.0, centre + spread))


@dataclass(frozen=True)
class GroupRates:
    """One group's outcome rates, with the uncertainty on each."""

    group: object
    n: int
    selected: int
    positives: int
    """Actual bads in the group — the denominator for TPR."""

    true_positives: int
    false_positives: int

    @property
    def selection_rate(self) -> float | None:
        return self.selected / self.n if self.n else None

    @property
    def true_positive_rate(self) -> float | None:
        return self.true_positives / self.positives if self.positives else None

    @property
    def false_positive_rate(self) -> float | None:
        negatives = self.n - self.positives
        return self.false_positives / negatives if negatives else None

    @property
    def selection_interval(self) -> tuple[float, float]:
        return _wilson(self.selected, self.n)

    @property
    def interval_width(self) -> float:
        low, high = self.selection_interval
        return high - low

    def to_dict(self) -> dict:
        low, high = self.selection_interval
        return {
            "group": self.group,
            "n": self.n,
            "selection_rate": self.selection_rate,
            "selection_ci_low": low,
            "selection_ci_high": high,
            "true_positive_rate": self.true_positive_rate,
            "false_positive_rate": self.false_positive_rate,
            "positives": self.positives,
        }


def group_rates(
    groups: Sequence[object],
    predictions: Sequence[int],
    labels: Sequence[int] | None = None,
) -> list[GroupRates]:
    """Per-group counts. ``predictions`` is 1 for the *favourable* outcome.

    Favourable, not adverse. Demographic parity is conventionally stated on the
    selection (approval) rate, and flipping the convention halfway through a
    report turns every sign around without changing a single number's magnitude.
    """
    if len(groups) != len(predictions):
        raise FairnessError("groups and predictions must be the same length")
    if labels is not None and len(labels) != len(groups):
        raise FairnessError("labels must be the same length as groups")
    if any(p not in (0, 1) for p in predictions):
        raise FairnessError("predictions must be 0 (adverse) or 1 (favourable)")

    buckets: dict[object, dict] = {}
    for index, group in enumerate(groups):
        if group is None:
            # An applicant with no recorded protected attribute is excluded from
            # the disparity, and the exclusion is counted rather than hidden —
            # missingness that correlates with the attribute is itself a finding.
            continue
        bucket = buckets.setdefault(
            group, {"n": 0, "selected": 0, "positives": 0, "tp": 0, "fp": 0}
        )
        bucket["n"] += 1
        bucket["selected"] += predictions[index]
        if labels is not None:
            label = labels[index]
            bucket["positives"] += label
            # "Positive" here is the adverse outcome (default), so a true positive
            # is a bad the model declined.
            if label == 1 and predictions[index] == 0:
                bucket["tp"] += 1
            if label == 0 and predictions[index] == 0:
                bucket["fp"] += 1

    return [
        GroupRates(
            group=group,
            n=bucket["n"],
            selected=bucket["selected"],
            positives=bucket["positives"],
            true_positives=bucket["tp"],
            false_positives=bucket["fp"],
        )
        for group, bucket in sorted(buckets.items(), key=lambda pair: str(pair[0]))
    ]


def demographic_parity_difference(rates: Sequence[GroupRates]) -> float | None:
    """Largest minus smallest selection rate across groups."""
    values = [r.selection_rate for r in rates if r.selection_rate is not None]
    if len(values) < 2:
        return None
    return max(values) - min(values)


def demographic_parity_ratio(rates: Sequence[GroupRates]) -> float | None:
    """Smallest over largest selection rate — the adverse-impact ratio (SRS §4.3.3)."""
    values = [r.selection_rate for r in rates if r.selection_rate is not None]
    if len(values) < 2 or max(values) == 0:
        return None
    return min(values) / max(values)


def equalized_odds_difference(rates: Sequence[GroupRates]) -> float | None:
    """Hardt et al.: the larger of the TPR gap and the FPR gap across groups."""
    tprs = [r.true_positive_rate for r in rates if r.true_positive_rate is not None]
    fprs = [r.false_positive_rate for r in rates if r.false_positive_rate is not None]
    if len(tprs) < 2 or len(fprs) < 2:
        return None
    return max(max(tprs) - min(tprs), max(fprs) - min(fprs))


def equal_opportunity_difference(rates: Sequence[GroupRates]) -> float | None:
    """TPR gap alone — the half of equalized odds about missed defaults."""
    tprs = [r.true_positive_rate for r in rates if r.true_positive_rate is not None]
    if len(tprs) < 2:
        return None
    return max(tprs) - min(tprs)


@dataclass
class AttributeFinding:
    """Everything measured for one protected attribute."""

    attribute: str
    rates: list[GroupRates]
    metrics: dict[str, float | None]
    excluded_unknown: int = 0
    noisy_groups: list[object] = field(default_factory=list)
    """Groups whose selection-rate interval is wider than the measured disparity —
    the disparity is not distinguishable from sampling variation for them."""

    def to_dict(self) -> dict:
        return {
            "attribute": self.attribute,
            "metrics": self.metrics,
            "excluded_unknown": self.excluded_unknown,
            "noisy_groups": [str(g) for g in self.noisy_groups],
            "groups": [r.to_dict() for r in self.rates],
        }


@dataclass
class FairnessReport:
    """The §4 Step 7 output. It measures; it does not decide."""

    model: str
    findings: list[AttributeFinding]
    n_scored: int

    def verdict(self) -> str:
        raise Ungrounded(
            f"{FAIRNESS_ACTION_THRESHOLD} — this report measures disparity and "
            "cannot say whether it requires action. The metric and the level are "
            "the Fair-Lending Committee's decision. Put the measurements in the "
            "model card and take them to the committee."
        )

    def worst(self, metric: Metric) -> tuple[str, float] | None:
        """The attribute with the largest value of one metric."""
        candidates = [
            (f.attribute, f.metrics.get(metric.value))
            for f in self.findings
            if f.metrics.get(metric.value) is not None
        ]
        if not candidates:
            return None
        if metric is Metric.DEMOGRAPHIC_PARITY_RATIO:
            return min(candidates, key=lambda pair: pair[1])
        return max(candidates, key=lambda pair: pair[1])

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "n_scored": self.n_scored,
            "action_threshold": str(FAIRNESS_ACTION_THRESHOLD),
            "verdict": "not computable: action threshold is [POLICY] (LH-205)",
            "mitigation_ladder": list(MITIGATION_LADDER),
            "findings": [f.to_dict() for f in self.findings],
        }


def assess(
    entity_ids: Sequence[str],
    predictions: Sequence[int],
    access: ProtectedAttributeAccess,
    *,
    model: str,
    labels: Sequence[int] | None = None,
    attributes: Sequence[str] = tuple(sorted(PROTECTED_NAMES)),
) -> FairnessReport:
    """Measure disparity for each protected attribute.

    Protected attributes come only from ``access``. There is deliberately no
    parameter accepting them inline: a signature that took them as a list would
    let a training pipeline pass its own feature dict and turn the whole
    separation into a convention.
    """
    if len(entity_ids) != len(predictions):
        raise FairnessError("entity_ids and predictions must be the same length")

    findings: list[AttributeFinding] = []
    for attribute in attributes:
        values = access.series(attribute, entity_ids)
        rates = group_rates(values, predictions, labels)
        metrics = {
            Metric.DEMOGRAPHIC_PARITY_DIFFERENCE.value: demographic_parity_difference(rates),
            Metric.DEMOGRAPHIC_PARITY_RATIO.value: demographic_parity_ratio(rates),
            Metric.EQUALIZED_ODDS_DIFFERENCE.value: equalized_odds_difference(rates),
            Metric.EQUAL_OPPORTUNITY_DIFFERENCE.value: equal_opportunity_difference(rates),
        }
        disparity = metrics[Metric.DEMOGRAPHIC_PARITY_DIFFERENCE.value]
        noisy = (
            [r.group for r in rates if r.interval_width > disparity]
            if disparity is not None
            else [r.group for r in rates]
        )
        findings.append(
            AttributeFinding(
                attribute=attribute,
                rates=rates,
                metrics=metrics,
                excluded_unknown=sum(1 for value in values if value is None),
                noisy_groups=noisy,
            )
        )

    return FairnessReport(model=model, findings=findings, n_scored=len(entity_ids))


def next_mitigation(applied: Sequence[str]) -> str:
    """The next rung of the SRS §4.3.3 ladder, refusing to let a rung be skipped.

    The order is not a preference. Threshold adjustment means group-specific
    cutoffs — a different decision boundary for a protected class — which in most
    jurisdictions is the intervention with the largest legal exposure, and it is
    also the easiest to reach for because it needs no retraining. Reaching it
    without having tried the two rungs above is a decision that has to be made
    deliberately, in writing.
    """
    for rung in MITIGATION_LADDER:
        if rung not in applied:
            return rung
    raise FairnessError(
        "every rung of the SRS §4.3.3 ladder has been applied and the disparity "
        "remains: this is a model-approval decision, not an engineering one"
    )

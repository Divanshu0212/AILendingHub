"""Independent validation, and the Phase 1 exit criteria as executable checks.

Phase 1 §4 WS-1.1 Step 9: "Validator reproduces: AUC/Gini/KS on test vintages;
calibration by decile; train↔test PSI; monotonicity spot-checks; ±10% sensitivity
perturbations; swap-set analysis vs. the rebuilt legacy scorecard."

Phase 1 §7 (v1.1) then states the gate. The numeric ones are evaluated here; the
one without a number is not, and the difference is preserved rather than smoothed
over:

* **Champion** ≥ rebuilt legacy on out-of-time Gini, and Brier ≤ legacy — `[SPEC]`.
  Added in Phase 1 v1.1 after finding P1-F9: the champion decides all traffic the
  challenger is not canarying, and previously had no bar at all, so the model
  deciding most applications passed the gate on a different model's numbers.
* Challenger ≥ **+3 Gini** over the rebuilt legacy scorecard, out-of-time — `[SPEC]`.
* Brier ≤ legacy — `[SPEC]`.
* Decision-log spot audit: re-scored decisions identical — `[SPEC]`, and already
  implemented by :mod:`lending_hub.decisionlog.replay` at zero tolerance.
* "Swap-set shows no adverse-segment concentration" — **no number**. What counts
  as concentration, and in which segments, is a fair-lending judgement
  `[POLICY: Fair-Lending Committee]` (LH-205). :meth:`SwapSetAnalysis.concentration`
  computes every segment's over-representation and :meth:`ValidationReport.exit_criteria`
  returns the criterion as *unevaluated* rather than guessing a bar.

Which score each metric is computed on
--------------------------------------
Discrimination is a property of the **ranking**; calibration is a property of the
**level**. They are therefore measured on different things, and conflating them
understates the model:

* AUC / Gini / KS come from the raw model score.
* Brier / ECE / the reliability diagram come from the calibrated PD.

An isotonic calibrator is a monotone *step* function, so it quantises the score —
on the Track P run it collapsed 8,969 distinct scores to 31 and cost 0.9 Gini
points. Nothing about the model changed; only the number of distinct values it
could express. Report discrimination on the calibrated PD and the loss looks like
a weaker model, when it is an artifact of how many rows the calibrator was fitted
on. :func:`validate` therefore takes both series, and falls back to one only when
the caller has genuinely only one.

An out-of-time claim that is not out of time
--------------------------------------------
The Gini criterion is stated "on out-of-time test". A :class:`Splits` produced by
``holdout_without_time_axis`` is not out of time, so
:func:`validate` carries the flag through and the report says so on the same line
as the number. Otherwise the criterion is met by a metric that cannot answer the
question it was written for.

Workstream: WS-1.1 Step 9 · SRS §4.3.4, Phase 1 §7
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Sequence

from lending_hub.definitions import Pending
from lending_hub.modeling.metrics import auc, ks

from .calibration import brier_score, expected_calibration_error, reliability
from .features import psi, screen_psi

#: Phase 1 §7 [SPEC]: "Challenger ≥ +3 Gini over rebuilt legacy scorecard on
#: out-of-time test." In Gini *points* — Gini is 2·AUC − 1, so this is 0.03 in
#: Gini units.
GINI_UPLIFT_REQUIRED = 3.0

#: Phase 1 §4 WS-1.1 Step 9 [SPEC]: "±10% sensitivity perturbations".
SENSITIVITY_PERTURBATION = 0.10

#: Phase 1 §7 [SPEC]: "Decision-log spot audit: 100 random logged decisions".
SPOT_AUDIT_SAMPLE = 100

#: The one exit criterion with no number attached.
SWAP_SET_CONCENTRATION_LIMIT = Pending(
    owner="Fair-Lending Committee",
    ticket="LH-205",
    note=(
        "what counts as 'adverse-segment concentration' in a swap set, and which "
        "segments it is measured over. Phase 1 §7 states the criterion without a "
        "bar; the analysis computes every segment's over-representation and the "
        "committee sets the level"
    ),
)


class ValidationError(Exception):
    """The validation cannot be performed as requested."""


def gini(labels: Sequence[int], scores: Sequence[float]) -> float | None:
    """Gini coefficient in *points*: ``(2·AUC − 1) × 100``.

    Points because the Phase 1 criterion is written in them. Returning the
    fraction and comparing it against 3 would silently demand a 300-point uplift.
    """
    area = auc(list(labels), list(scores))
    return None if area is None else (2 * area - 1) * 100


@dataclass
class Discrimination:
    n: int
    positives: int
    auc: float | None
    gini: float | None
    ks: float | None

    def to_dict(self) -> dict:
        return {
            "n": self.n,
            "positives": self.positives,
            "auc": self.auc,
            "gini_points": self.gini,
            "ks": self.ks,
        }


def discrimination(labels: Sequence[int], scores: Sequence[float]) -> Discrimination:
    labels, scores = list(labels), list(scores)
    if len(labels) != len(scores):
        raise ValidationError("labels and scores must be the same length")
    return Discrimination(
        n=len(labels),
        positives=sum(labels),
        auc=auc(labels, scores),
        gini=gini(labels, scores),
        ks=ks(labels, scores),
    )


def score_psi(reference: Sequence[float], current: Sequence[float], *, bins: int = 10) -> float:
    """Score PSI, with bin edges taken from the *reference* distribution.

    From the reference, always. Cutting bins on the current population makes PSI
    approach zero by construction — every bin holds a tenth of it — and the
    stability metric stops being able to detect instability.
    """
    if not reference or not current:
        raise ValidationError("PSI needs a non-empty distribution on both sides")
    edges = _edges(reference, bins)
    return psi(_proportions(reference, edges), _proportions(current, edges))


def _edges(values: Sequence[float], bins: int) -> list[float]:
    ordered = sorted(values)
    edges: list[float] = []
    for k in range(1, bins):
        candidate = ordered[min(len(ordered) - 1, int(k * len(ordered) / bins))]
        if not edges or candidate > edges[-1]:
            edges.append(candidate)
    return edges


def _proportions(values: Sequence[float], edges: Sequence[float]) -> list[float]:
    from bisect import bisect_right

    counts = [0] * (len(edges) + 1)
    for value in values:
        counts[bisect_right(edges, value)] += 1
    return [count / len(values) for count in counts]


@dataclass
class MonotonicityCheck:
    feature: str
    expected: str
    violations: int
    points: int
    worst_violation: float = 0.0

    @property
    def passed(self) -> bool:
        return self.violations == 0

    def to_dict(self) -> dict:
        return {
            "feature": self.feature,
            "expected": self.expected,
            "points": self.points,
            "violations": self.violations,
            "worst_violation": self.worst_violation,
            "passed": self.passed,
        }


def monotonicity_spot_check(
    predict: Callable[[dict], float],
    base_row: dict,
    feature: str,
    grid: Sequence[float],
    *,
    expect_increasing: bool,
) -> MonotonicityCheck:
    """Walk one feature across a grid, holding everything else fixed.

    A spot check, not a proof: it fixes the other features at one row's values, so
    it can only find violations along that slice. That is the honest limit of the
    method and the reason the constraint is enforced during fitting rather than
    discovered here.
    """
    if len(grid) < 2:
        raise ValidationError("a monotonicity check needs at least two grid points")

    predictions = [predict({**base_row, feature: value}) for value in grid]
    violations = 0
    worst = 0.0
    for previous, current in zip(predictions, predictions[1:]):
        gap = current - previous if expect_increasing else previous - current
        if gap < -1e-12:
            violations += 1
            worst = min(worst, gap)

    return MonotonicityCheck(
        feature=feature,
        expected="increasing" if expect_increasing else "decreasing",
        violations=violations,
        points=len(grid),
        worst_violation=worst,
    )


@dataclass
class SensitivityResult:
    feature: str
    mean_absolute_shift: float
    max_absolute_shift: float
    direction_flips: int
    """Rows where a +10% and a −10% perturbation moved the score the same way.

    A model whose response to a feature has the same sign in both directions is
    locally non-monotone in it, whatever the fitted constraint says about the
    global shape."""

    def to_dict(self) -> dict:
        return {
            "feature": self.feature,
            "mean_absolute_shift": self.mean_absolute_shift,
            "max_absolute_shift": self.max_absolute_shift,
            "direction_flips": self.direction_flips,
        }


def sensitivity(
    predict: Callable[[dict], float],
    rows: Sequence[dict],
    features: Sequence[str],
    *,
    perturbation: float = SENSITIVITY_PERTURBATION,
) -> list[SensitivityResult]:
    """Perturb each numeric feature by ±``perturbation`` and measure the response."""
    if not rows:
        raise ValidationError("sensitivity analysis needs at least one row")

    results: list[SensitivityResult] = []
    for feature in features:
        shifts: list[float] = []
        flips = 0
        for row in rows:
            value = row.get(feature)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            base = predict(row)
            up = predict({**row, feature: value * (1 + perturbation)})
            down = predict({**row, feature: value * (1 - perturbation)})
            shifts.extend((abs(up - base), abs(down - base)))
            if (up - base) * (down - base) > 0 and abs(up - base) > 1e-12:
                flips += 1
        if not shifts:
            continue
        results.append(
            SensitivityResult(
                feature=feature,
                mean_absolute_shift=sum(shifts) / len(shifts),
                max_absolute_shift=max(shifts),
                direction_flips=flips,
            )
        )
    return results


@dataclass
class SwapSetAnalysis:
    """Who the challenger decides differently from the champion, and how they perform."""

    both_approve: int = 0
    both_decline: int = 0
    swap_in: int = 0
    """Champion declines, challenger approves."""

    swap_out: int = 0
    """Champion approves, challenger declines."""

    swap_in_bads: int = 0
    swap_out_bads: int = 0
    segment_swap_out: dict[str, int] = field(default_factory=dict)
    segment_population: dict[str, int] = field(default_factory=dict)

    @property
    def swap_in_bad_rate(self) -> float | None:
        return self.swap_in_bads / self.swap_in if self.swap_in else None

    @property
    def swap_out_bad_rate(self) -> float | None:
        return self.swap_out_bads / self.swap_out if self.swap_out else None

    def concentration(self) -> dict[str, float]:
        """Each segment's share of the swap-out set divided by its population share.

        Above 1.0 means the challenger's new declines fall on that segment more
        than its size explains. This is the *measurement* Phase 1 §7 needs; the
        level at which it is unacceptable is LH-205.
        """
        total_swap_out = sum(self.segment_swap_out.values())
        total_population = sum(self.segment_population.values())
        if not total_swap_out or not total_population:
            return {}
        out: dict[str, float] = {}
        for segment, population in self.segment_population.items():
            if population == 0:
                continue
            swap_share = self.segment_swap_out.get(segment, 0) / total_swap_out
            population_share = population / total_population
            out[segment] = swap_share / population_share
        return dict(sorted(out.items(), key=lambda pair: -pair[1]))

    def to_dict(self) -> dict:
        return {
            "both_approve": self.both_approve,
            "both_decline": self.both_decline,
            "swap_in": self.swap_in,
            "swap_out": self.swap_out,
            "swap_in_bad_rate": self.swap_in_bad_rate,
            "swap_out_bad_rate": self.swap_out_bad_rate,
            "segment_concentration": self.concentration(),
            "concentration_limit": str(SWAP_SET_CONCENTRATION_LIMIT),
        }


def swap_sets(
    champion_approves: Sequence[int],
    challenger_approves: Sequence[int],
    labels: Sequence[int],
    segments: Sequence[str] | None = None,
) -> SwapSetAnalysis:
    """Compare two decision sets on the same population.

    A useful swap set needs the *same* applicants scored both ways, which is why
    this takes three parallel sequences and refuses ragged input: comparing a
    champion's decisions on one month to a challenger's on another measures the
    months, not the models.
    """
    if not (len(champion_approves) == len(challenger_approves) == len(labels)):
        raise ValidationError(
            "swap-set analysis needs the same applicants decided both ways"
        )
    if segments is not None and len(segments) != len(labels):
        raise ValidationError("segments must cover every applicant")

    analysis = SwapSetAnalysis()
    for index, (champion, challenger, label) in enumerate(
        zip(champion_approves, challenger_approves, labels)
    ):
        segment = segments[index] if segments is not None else None
        if segment is not None:
            analysis.segment_population[segment] = (
                analysis.segment_population.get(segment, 0) + 1
            )
        if champion == 1 and challenger == 1:
            analysis.both_approve += 1
        elif champion == 0 and challenger == 0:
            analysis.both_decline += 1
        elif champion == 0 and challenger == 1:
            analysis.swap_in += 1
            analysis.swap_in_bads += label
        else:
            analysis.swap_out += 1
            analysis.swap_out_bads += label
            if segment is not None:
                analysis.segment_swap_out[segment] = (
                    analysis.segment_swap_out.get(segment, 0) + 1
                )
    return analysis


@dataclass
class ValidationReport:
    """The Phase 1 §6 deliverable: one independent validation report per model."""

    model: str
    out_of_time: bool
    train: Discrimination
    test: Discrimination
    brier: float
    ece: float
    calibration_deciles: list
    score_psi: float
    monotonicity: list[MonotonicityCheck] = field(default_factory=list)
    sensitivity: list[SensitivityResult] = field(default_factory=list)
    swap_set: SwapSetAnalysis | None = None
    legacy_gini: float | None = None
    legacy_brier: float | None = None
    dataset: str = ""
    track: str = ""
    role: str = "challenger"
    """``"champion"`` or ``"challenger"``. They face different §7 bars: the
    challenger must beat the legacy scorecard by 3 Gini points, the champion must
    merely not be worse than it."""

    @property
    def gini_uplift(self) -> float | None:
        if self.legacy_gini is None or self.test.gini is None:
            return None
        return self.test.gini - self.legacy_gini

    def exit_criteria(self) -> dict[str, dict]:
        """Phase 1 §7, criterion by criterion, with the ungrounded one left open."""
        uplift = self.gini_uplift
        psi_verdict, psi_note = screen_psi(self.score_psi)

        required = GINI_UPLIFT_REQUIRED if self.role == "challenger" else 0.0
        name = f"{self.role}_gini_uplift"

        criteria: dict[str, dict] = {
            name: {
                "required": (
                    f">= +{required} Gini points over the rebuilt legacy scorecard, "
                    "out-of-time"
                ),
                "measured": uplift,
                # "Out-of-time" is part of the criterion, not a caveat beside it.
                # An in-time uplift can be large and still say nothing about how
                # the model travels across a macro regime, which is the whole
                # question the criterion asks — so it leaves the criterion
                # unevaluated rather than passing it.
                "evaluated": uplift is not None and self.out_of_time,
                "met": (
                    None
                    if uplift is None or not self.out_of_time
                    else uplift >= required
                ),
                "note": (
                    "no rebuilt legacy scorecard supplied"
                    if uplift is None
                    else (
                        "measured on a test set that is NOT out of time; this "
                        "number cannot satisfy the criterion as written"
                        if not self.out_of_time
                        else "measured on the out-of-time test vintages"
                    )
                ),
            },
            "brier_no_worse_than_legacy": {
                "required": "<= legacy Brier",
                "measured": self.brier,
                "legacy": self.legacy_brier,
                "evaluated": self.legacy_brier is not None,
                "met": None if self.legacy_brier is None else self.brier <= self.legacy_brier,
            },
            "monotonicity_holds": {
                "required": "no violations on the ratified directions",
                "measured": sum(check.violations for check in self.monotonicity),
                "evaluated": bool(self.monotonicity),
                "met": (
                    all(check.passed for check in self.monotonicity)
                    if self.monotonicity
                    else None
                ),
            },
            "score_stability": {
                "required": "PSI within the SRS §4.3.4 tolerance",
                "measured": self.score_psi,
                "evaluated": True,
                "met": psi_verdict.value == "pass",
                "note": psi_note,
            },
            "swap_set_no_adverse_concentration": {
                "required": str(SWAP_SET_CONCENTRATION_LIMIT),
                "measured": self.swap_set.concentration() if self.swap_set else None,
                "evaluated": False,
                "met": None,
                "note": (
                    "Phase 1 §7 states this criterion without a bar. The "
                    "over-representation of each segment in the swap-out set is "
                    "computed; the level that fails is the Fair-Lending Committee's "
                    "to set (LH-205)."
                ),
            },
        }
        return criteria

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "dataset": self.dataset,
            "track": self.track,
            "out_of_time": self.out_of_time,
            "train": self.train.to_dict(),
            "test": self.test.to_dict(),
            "gini_uplift_points": self.gini_uplift,
            "brier": self.brier,
            "ece": self.ece,
            "score_psi": self.score_psi,
            "calibration_deciles": [b.to_dict() for b in self.calibration_deciles],
            "monotonicity": [check.to_dict() for check in self.monotonicity],
            "sensitivity": [result.to_dict() for result in self.sensitivity],
            "swap_set": self.swap_set.to_dict() if self.swap_set else None,
            "exit_criteria": self.exit_criteria(),
        }


def validate(
    *,
    model: str,
    train_labels: Sequence[int],
    train_scores: Sequence[float],
    test_labels: Sequence[int],
    test_scores: Sequence[float],
    out_of_time: bool,
    test_probabilities: Sequence[float] | None = None,
    train_probabilities: Sequence[float] | None = None,
    dataset: str = "",
    track: str = "",
    role: str = "challenger",
    legacy_test_scores: Sequence[float] | None = None,
    legacy_test_probabilities: Sequence[float] | None = None,
    monotonicity: Sequence[MonotonicityCheck] = (),
    sensitivity_results: Sequence[SensitivityResult] = (),
    swap_set: SwapSetAnalysis | None = None,
    bins: int = 10,
) -> ValidationReport:
    """Assemble the WS-1.1 Step 9 report from a model's scores.

    ``role`` decides which §7 bar the uplift criterion applies: ``"challenger"``
    needs +3 Gini over the rebuilt legacy scorecard, ``"champion"`` needs only to
    be no worse than it. Passing the wrong one silently applies the wrong bar,
    which is why it is named rather than inferred from the model's name.

    ``*_scores`` are the raw model scores and drive discrimination; ``*_probabilities``
    are the calibrated PDs and drive Brier, ECE, the reliability diagram and PSI —
    PSI on the calibrated PD because that is the artifact production monitors and
    the bands read. Omitting the probabilities measures everything on the scores,
    which is right only when no calibrator has been fitted.
    """
    test_pd = list(test_probabilities) if test_probabilities is not None else list(test_scores)
    train_pd = (
        list(train_probabilities) if train_probabilities is not None else list(train_scores)
    )

    legacy_gini = legacy_brier = None
    if legacy_test_scores is not None:
        # The comparator obeys the same split as the model under test: its Gini
        # from its raw score, its Brier from its calibrated PD. Comparing a
        # calibrated Brier against an uncalibrated one is not a comparison of two
        # models — it is a comparison of one model against an uncalibrated version
        # of another, and it flatters whichever side was calibrated.
        legacy_gini = gini(test_labels, legacy_test_scores)
        legacy_brier = brier_score(
            test_labels,
            legacy_test_probabilities
            if legacy_test_probabilities is not None
            else legacy_test_scores,
        )

    return ValidationReport(
        model=model,
        out_of_time=out_of_time,
        train=discrimination(train_labels, train_scores),
        test=discrimination(test_labels, test_scores),
        brier=brier_score(test_labels, test_pd),
        ece=expected_calibration_error(test_labels, test_pd, bins),
        calibration_deciles=reliability(test_labels, test_pd, bins),
        score_psi=score_psi(train_pd, test_pd, bins=bins),
        monotonicity=list(monotonicity),
        sensitivity=list(sensitivity_results),
        swap_set=swap_set,
        legacy_gini=legacy_gini,
        legacy_brier=legacy_brier,
        dataset=dataset,
        track=track,
        role=role,
    )

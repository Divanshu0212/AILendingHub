"""Model A — boundary delineation: the contract, not the network (WS-2.2).

Phase 2 §4 specifies fine-tuning SAM or U-Net on peak-season max-NDVI
composites, post-processing with watershed and polygonisation, snapping to
cadastral layers, and gating on median IoU >= 0.75 against held-out GPS-walk
polygons.

**The network is not ported here, and that is a decision, not an omission.**
ADR-0013 sets it out: SAM and U-Net are fine-tuned foundation models, Master §2
rule 2 allows "use that library, or port it with unit tests reproducing the
library's outputs on fixture data", and neither branch exists with no imagery to
reproduce outputs on. A stdlib re-derivation would be a different model wearing
the paper's name — the worst of the available options, because it would look
like Model A on a deliverables checklist.

What ships is everything the model's *consumers* need, which turns out to be
most of the risk:

* the gate itself (:func:`evaluate_gate`) — a **median** IoU over held-out
  walked polygons, with the sample size, because a median over eleven plots is
  not a gate;
* the per-plot admission rule (:func:`admissible`) — below the gate, Phase 2 §4
  says a plot "requires a manual walk", so it is not an input at all;
* the area-mismatch fraud flag (:func:`area_flag`), including its direction;
* cadastral snapping (:func:`snap_to_cadastral`), which is where a plausible
  boundary quietly becomes the wrong parcel.

Why the gate is a median and what that hides
---------------------------------------------
Phase 2 §4 says median IoU, and a median is the right central statistic for a
skewed metric. But a median that clears 0.75 is compatible with a quarter of
plots below 0.5, and those are not random — delineation fails on small,
irregular and intercropped fields, which is to say on the smallest borrowers.
:class:`GateResult` therefore carries the quartiles and the below-gate share
alongside the median, so the distribution is in front of whoever signs the gate
rather than one number from it. This is raised as a Phase 2 finding.

What this does not port
-----------------------
No SAM, no U-Net, no PyTorch, no watershed transform, no GDAL polygonisation.
:func:`snap_to_cadastral` matches an existing candidate parcel rather than
performing topological snapping. There is no training loop and no inference
path; :class:`Delineation` is the shape a Track B model must return.

Workstream: WS-2.2 Model A (SRS §3.4.1)
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date
from typing import Sequence

from lending_hub.agri.geometry import GeometryError, Polygon, area_mismatch, iou
from lending_hub.agri.registry import Plot, PlotSource

#: Median IoU a delineation model must reach before its output may be shown.
#: `[SPEC]` — Phase 2 §4 WS-2.2 Model A states 0.75 explicitly. Unlike most
#: thresholds in this repository it is written down, so it is a constant rather
#: than a `Pending`.
MODEL_A_IOU_GATE = 0.75

#: Claimed-vs-observed area mismatch that raises an underwriter flag. `[SPEC]` —
#: Phase 2 §4 WS-2.2 Model A: ">20% claimed-vs-observed area mismatch →
#: underwriter flag (fraud signal)".
AREA_MISMATCH_FLAG = 0.20

#: The smallest held-out sample this will call a gate result. Not from the phase
#: file, which sets a threshold without a sample size. A median IoU over a dozen
#: plots has a confidence interval wide enough to span the gate in both
#: directions, and "median 0.78" reads identically whether it came from 12 plots
#: or 1,200. Raised as a Phase 2 finding.
MIN_GATE_SAMPLE = 100


class BoundaryError(Exception):
    """A delineation cannot be evaluated or admitted."""


@dataclass(frozen=True)
class Delineation:
    """One model-produced boundary — the shape Track B must return.

    ``confidence`` is the model's own score for this polygon, not an IoU: at
    inference there is no walked polygon to compare against, which is the whole
    difficulty. The gate is established on held-out walked plots and then
    *applied* through this score, and that substitution is an assumption worth
    naming — it holds only while the confidence is calibrated against IoU, which
    is a validation obligation on the model card, not a property of any score.
    """

    plot_id: str
    boundary: Polygon
    confidence: float
    composite_start: date
    composite_end: date
    snapped_to_cadastral: bool = False

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise BoundaryError(
                f"{self.plot_id}: confidence {self.confidence} outside [0, 1]"
            )
        if self.composite_start > self.composite_end:
            raise BoundaryError(
                f"{self.plot_id}: composite window "
                f"{self.composite_start}..{self.composite_end} is inverted"
            )

    def to_plot(self, *, surveyed: date, borrower_id: str | None = None) -> Plot:
        """Register this delineation as an auto-delineated plot.

        The only path from a model output into the registry, and it stamps
        ``PlotSource.AUTO_DELINEATED`` with the confidence attached. There is no
        way to enter a delineation as a walked boundary.
        """
        return Plot(
            plot_id=self.plot_id,
            boundary=self.boundary,
            source=PlotSource.AUTO_DELINEATED,
            surveyed=surveyed,
            borrower_id=borrower_id,
            confidence=self.confidence,
        )


@dataclass(frozen=True)
class GateResult:
    """Model A's gate, with the distribution behind it.

    ``passed`` answers the phase file's question. The rest answers the question
    the phase file does not ask: *which plots is it failing on?*
    """

    median_iou: float
    mean_iou: float
    p25_iou: float
    p10_iou: float
    below_gate_share: float
    sample_size: int
    gate: float

    @property
    def passed(self) -> bool:
        return self.median_iou >= self.gate and self.sample_size >= MIN_GATE_SAMPLE

    @property
    def why_not(self) -> str:
        """Why the gate did not pass, or the empty string.

        Mirrors the Phase 1 and Phase 3 pattern (``GBM.promotable``,
        ``BandConfig.effective``): a gate script reads a reason rather than a
        reviewer noticing a footnote.
        """
        reasons = []
        if self.sample_size < MIN_GATE_SAMPLE:
            reasons.append(
                f"held-out sample is {self.sample_size} plots, below the "
                f"{MIN_GATE_SAMPLE} needed for the median to mean anything"
            )
        if self.median_iou < self.gate:
            reasons.append(
                f"median IoU {self.median_iou:.3f} is below the {self.gate:.2f} gate"
            )
        return "; ".join(reasons)


def evaluate_gate(
    pairs: Sequence[tuple[Polygon, Polygon]], *, gate: float = MODEL_A_IOU_GATE
) -> GateResult:
    """Evaluate Model A against held-out GPS-walk polygons.

    ``pairs`` is ``(walked, delineated)``. The order matters only for
    readability — IoU is symmetric — but keeping ground truth first is the habit
    that stops a later reviewer wondering which arm was which.

    Every pair must be a *held-out* walked polygon. Nothing here can check that,
    which is precisely why it is stated: a gate computed on the training plots
    is a statement about memorisation, and it is the same mistake Phase 3 caught
    in its own §7 comparison (finding P3-F14).
    """
    if not pairs:
        raise BoundaryError(
            "no held-out pairs; an ungated model is not a passing one. Report "
            "the absence of the walk set (LH-407) rather than an empty gate."
        )

    scores = []
    for walked, delineated in pairs:
        try:
            scores.append(iou(walked, delineated))
        except GeometryError as exc:
            raise BoundaryError(f"cannot score a held-out pair: {exc}") from exc

    scores.sort()
    return GateResult(
        median_iou=statistics.median(scores),
        mean_iou=statistics.fmean(scores),
        p25_iou=_percentile(scores, 0.25),
        p10_iou=_percentile(scores, 0.10),
        below_gate_share=sum(1 for s in scores if s < gate) / len(scores),
        sample_size=len(scores),
        gate=gate,
    )


def _percentile(sorted_scores: Sequence[float], q: float) -> float:
    """Nearest-rank percentile on an already-sorted sequence."""
    if not sorted_scores:
        raise BoundaryError("percentile of an empty sample")
    index = max(0, min(len(sorted_scores) - 1, int(-(-q * len(sorted_scores) // 1)) - 1))
    return sorted_scores[index]


def admissible(delineation: Delineation, gate_result: GateResult) -> bool:
    """Whether this delineation may be shown to an underwriter or scored on.

    Two conditions, both required. The **model** must have cleared its gate at
    all — Phase 2 §4: "before auto-delineations are shown" — and *this*
    delineation's confidence must reach the gate. A model that passed on its
    held-out median still produces individual boundaries it is unsure of, and
    those are the ones Phase 2 §4 sends for a manual walk.
    """
    return gate_result.passed and delineation.confidence >= gate_result.gate


@dataclass(frozen=True)
class AreaFlag:
    """The claimed-vs-observed area check (Phase 2 §4, a fraud signal)."""

    plot_id: str
    claimed_hectares: float
    observed_hectares: float
    mismatch: float
    threshold: float

    @property
    def flagged(self) -> bool:
        return abs(self.mismatch) > self.threshold

    @property
    def direction(self) -> str:
        """Over-claim, under-claim, or within tolerance.

        Kept separate from ``flagged`` because the two directions are different
        conversations. Over-claiming is the fraud pattern — a larger plot
        supports a larger loan. Under-claiming is usually a plot subdivided or
        partly sold since the last survey, which is a limit review rather than a
        fraud referral, and routing both to the fraud desk wastes the capacity
        that makes the flag useful.
        """
        if not self.flagged:
            return "within_tolerance"
        return "over_claim" if self.mismatch > 0 else "under_claim"


def area_flag(
    plot_id: str,
    claimed_hectares: float,
    observed: Polygon,
    *,
    threshold: float = AREA_MISMATCH_FLAG,
) -> AreaFlag:
    """Compare a claimed area against an observed boundary.

    The observed polygon must come from a boundary that cleared the gate. This
    function cannot check that either — it takes a polygon — so the caller's
    obligation is stated here and exercised in ``agri.experiment``: flagging a
    borrower for fraud on the basis of a delineation the model itself was unsure
    about is the single worst outcome available in this workstream.
    """
    mismatch = area_mismatch(claimed_hectares, observed)
    return AreaFlag(
        plot_id=plot_id,
        claimed_hectares=claimed_hectares,
        observed_hectares=observed.area_hectares,
        mismatch=mismatch,
        threshold=threshold,
    )


def snap_to_cadastral(
    delineation: Delineation,
    candidates: Sequence[Polygon],
    *,
    min_iou: float,
) -> Delineation:
    """Snap a delineation to the best-matching digitised cadastral parcel.

    Phase 2 §4: "snap to digitized cadastral layers where available". Returns
    the delineation unchanged when no candidate reaches ``min_iou``, rather than
    snapping to the nearest one — which is the failure mode worth guarding.
    Cadastral parcels tile the landscape, so there is *always* a nearest one,
    and snapping to it relocates the plot onto the neighbour's field while
    raising the apparent precision of the boundary.

    ``min_iou`` has no default. It is the threshold that decides how often that
    happens, and no phase document supplies it — the phase file says "snap
    where available" and stops. Raised as a Phase 2 finding under LH-407.
    """
    if not 0.0 < min_iou <= 1.0:
        raise BoundaryError(f"min_iou must be in (0, 1], got {min_iou}")
    if not candidates:
        return delineation

    best = max(candidates, key=lambda parcel: iou(delineation.boundary, parcel))
    if iou(delineation.boundary, best) < min_iou:
        return delineation

    return Delineation(
        plot_id=delineation.plot_id,
        boundary=best,
        confidence=delineation.confidence,
        composite_start=delineation.composite_start,
        composite_end=delineation.composite_end,
        snapped_to_cadastral=True,
    )

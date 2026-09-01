"""Model A's contract — WS-2.2, Model A (SRS §3.4.1).

The network is not ported (ADR-0013). What is tested is everything its consumers
depend on: the gate and what it hides, the per-plot admission rule, the fraud
flag and its direction, and cadastral snapping — where a plausible boundary
quietly becomes the neighbour's field.
"""

from __future__ import annotations

import unittest
from datetime import date

from lending_hub.agri.boundary import (
    AREA_MISMATCH_FLAG,
    MIN_GATE_SAMPLE,
    MODEL_A_IOU_GATE,
    AreaFlag,
    BoundaryError,
    Delineation,
    GateResult,
    admissible,
    area_flag,
    evaluate_gate,
    snap_to_cadastral,
)
from lending_hub.agri.geometry import Point, Polygon
from lending_hub.agri.registry import PlotSource, RegistryError

EAST, NORTH = 500_000.0, 2_300_000.0
WINDOW = (date(2024, 8, 1), date(2024, 9, 15))


def _square(side: float, dx: float = 0.0, dy: float = 0.0) -> Polygon:
    x0, y0 = EAST + dx, NORTH + dy
    return Polygon(
        (Point(x0, y0), Point(x0 + side, y0), Point(x0 + side, y0 + side), Point(x0, y0 + side))
    )


def _delineation(confidence: float = 0.9, side: float = 200.0, dx: float = 0.0) -> Delineation:
    return Delineation(
        plot_id="P1",
        boundary=_square(side, dx=dx),
        confidence=confidence,
        composite_start=WINDOW[0],
        composite_end=WINDOW[1],
    )


def _pairs(count: int, shift: float) -> list[tuple[Polygon, Polygon]]:
    """`count` walked/delineated pairs, each offset by `shift` metres."""
    return [(_square(200), _square(200, dx=shift)) for _ in range(count)]


class TestPhaseFileConstants(unittest.TestCase):
    def test_the_gate_is_the_number_the_phase_file_states(self):
        self.assertEqual(MODEL_A_IOU_GATE, 0.75)

    def test_the_area_flag_is_the_number_the_phase_file_states(self):
        self.assertEqual(AREA_MISMATCH_FLAG, 0.20)


class TestDelineation(unittest.TestCase):
    def test_confidence_must_be_a_probability(self):
        for bad in (-0.1, 1.2):
            with self.assertRaises(BoundaryError):
                _delineation(confidence=bad)

    def test_an_inverted_composite_window_is_refused(self):
        with self.assertRaises(BoundaryError):
            Delineation(
                plot_id="P1",
                boundary=_square(200),
                confidence=0.9,
                composite_start=date(2024, 9, 15),
                composite_end=date(2024, 8, 1),
            )

    def test_to_plot_stamps_the_source_and_carries_the_confidence(self):
        """The only path from a model output into the registry."""
        plot = _delineation(confidence=0.82).to_plot(surveyed=date(2024, 9, 20))
        self.assertIs(plot.source, PlotSource.AUTO_DELINEATED)
        self.assertEqual(plot.confidence, 0.82)

    def test_there_is_no_path_to_entering_a_delineation_as_a_walk(self):
        """The registry refuses the combination even if someone builds it."""
        with self.assertRaises(RegistryError):
            from lending_hub.agri.registry import Plot

            Plot(
                plot_id="P1",
                boundary=_square(200),
                source=PlotSource.GPS_WALK,
                surveyed=date(2024, 9, 20),
                confidence=0.82,
            )


class TestGate(unittest.TestCase):
    def test_a_perfect_model_passes(self):
        result = evaluate_gate(_pairs(150, shift=0.0))
        self.assertAlmostEqual(result.median_iou, 1.0, places=9)
        self.assertTrue(result.passed)
        self.assertEqual(result.why_not, "")

    def test_a_shifted_model_fails(self):
        result = evaluate_gate(_pairs(150, shift=40.0))
        self.assertFalse(result.passed)
        self.assertIn("below the 0.75 gate", result.why_not)

    def test_a_small_sample_is_not_a_gate(self):
        """A median over a dozen plots spans the gate in both directions.

        The phase file sets the threshold and no sample size, so "median 0.78"
        reads identically whether it came from 12 plots or 1,200. Raised as a
        Phase 2 finding.
        """
        result = evaluate_gate(_pairs(11, shift=0.0))
        self.assertAlmostEqual(result.median_iou, 1.0, places=9)
        self.assertFalse(result.passed)
        self.assertIn("below the", result.why_not)
        self.assertIn("11 plots", result.why_not)

    def test_both_failures_are_reported_together(self):
        """A small sample AND a failing median: the reader gets both.

        Reporting only the first would send someone off to collect more walked
        plots for a model that is going to miss the gate anyway.
        """
        result = evaluate_gate(_pairs(10, shift=60.0))
        self.assertIn("sample is 10 plots", result.why_not)
        self.assertIn("median IoU", result.why_not)

    def test_the_distribution_the_median_hides_is_reported(self):
        """A passing median with a failing tail.

        Three quarters of plots delineate perfectly and a quarter are badly
        shifted. The median clears 0.75 comfortably; p25 does not, and the
        below-gate share is a quarter. Delineation fails on small, irregular and
        intercropped fields — which is to say on the smallest borrowers — so the
        distribution belongs in front of whoever signs the gate.
        """
        good = _pairs(120, shift=0.0)
        bad = _pairs(40, shift=120.0)
        result = evaluate_gate(good + bad)

        self.assertTrue(result.passed)
        self.assertAlmostEqual(result.median_iou, 1.0, places=9)
        self.assertAlmostEqual(result.below_gate_share, 0.25, places=9)
        self.assertLess(result.p25_iou, MODEL_A_IOU_GATE)
        self.assertLess(result.p10_iou, result.p25_iou + 1e-9)

    def test_mean_and_median_diverge_on_a_skewed_sample(self):
        result = evaluate_gate(_pairs(120, shift=0.0) + _pairs(40, shift=150.0))
        self.assertGreater(result.median_iou, result.mean_iou)

    def test_an_empty_held_out_set_is_refused(self):
        with self.assertRaises(BoundaryError) as ctx:
            evaluate_gate([])
        self.assertIn("LH-407", str(ctx.exception))

    def test_the_gate_threshold_is_overridable_for_sensitivity_work(self):
        result = evaluate_gate(_pairs(150, shift=40.0), gate=0.4)
        self.assertEqual(result.gate, 0.4)
        self.assertTrue(result.passed)

    def test_sample_size_is_reported(self):
        self.assertEqual(evaluate_gate(_pairs(137, shift=0.0)).sample_size, 137)

    def test_the_minimum_sample_is_the_documented_one(self):
        self.assertEqual(MIN_GATE_SAMPLE, 100)
        self.assertTrue(evaluate_gate(_pairs(MIN_GATE_SAMPLE, shift=0.0)).passed)
        self.assertFalse(evaluate_gate(_pairs(MIN_GATE_SAMPLE - 1, shift=0.0)).passed)


class TestAdmissibility(unittest.TestCase):
    def _passing_gate(self) -> GateResult:
        return evaluate_gate(_pairs(150, shift=0.0))

    def _failing_gate(self) -> GateResult:
        return evaluate_gate(_pairs(150, shift=60.0))

    def test_a_confident_delineation_from_a_gated_model_is_admissible(self):
        self.assertTrue(admissible(_delineation(confidence=0.88), self._passing_gate()))

    def test_an_unsure_delineation_is_not_admissible_even_from_a_gated_model(self):
        """A model that passed still produces boundaries it is unsure of.

        Phase 2 §4 sends those for a manual walk — they are not weaker inputs to
        down-weight, they are not inputs.
        """
        self.assertFalse(admissible(_delineation(confidence=0.61), self._passing_gate()))

    def test_no_delineation_is_admissible_from_an_ungated_model(self):
        """"Before auto-delineations are shown" — the model gate comes first."""
        self.assertFalse(admissible(_delineation(confidence=0.99), self._failing_gate()))

    def test_confidence_exactly_at_the_gate_is_admissible(self):
        self.assertTrue(admissible(_delineation(confidence=0.75), self._passing_gate()))


class TestAreaFlag(unittest.TestCase):
    def test_an_over_claim_beyond_the_threshold_is_flagged_as_fraud_shaped(self):
        flag = area_flag("P1", claimed_hectares=5.2, observed=_square(200))  # 4 ha
        self.assertTrue(flag.flagged)
        self.assertEqual(flag.direction, "over_claim")

    def test_an_under_claim_is_flagged_but_routed_differently(self):
        """Usually a subdivided or partly sold plot — a limit review, not fraud.

        Routing both directions to the fraud desk wastes the capacity that makes
        the flag useful.
        """
        flag = area_flag("P1", claimed_hectares=2.8, observed=_square(200))
        self.assertTrue(flag.flagged)
        self.assertEqual(flag.direction, "under_claim")

    def test_a_small_mismatch_is_within_tolerance(self):
        flag = area_flag("P1", claimed_hectares=4.3, observed=_square(200))
        self.assertFalse(flag.flagged)
        self.assertEqual(flag.direction, "within_tolerance")

    def test_the_threshold_boundary_matches_the_phase_file(self):
        """Phase 2 §4 says ">20%", so 20% exactly is not flagged."""
        exactly = area_flag("P1", claimed_hectares=4.8, observed=_square(200))
        self.assertAlmostEqual(exactly.mismatch, 0.20, places=9)
        self.assertFalse(exactly.flagged)

        over = area_flag("P1", claimed_hectares=4.81, observed=_square(200))
        self.assertTrue(over.flagged)

    def test_observed_hectares_is_reported(self):
        flag = area_flag("P1", claimed_hectares=5.0, observed=_square(200))
        self.assertAlmostEqual(flag.observed_hectares, 4.0, places=9)


class TestCadastralSnapping(unittest.TestCase):
    def test_snaps_to_a_close_parcel(self):
        parcel = _square(200, dx=6.0)
        snapped = snap_to_cadastral(_delineation(), [parcel], min_iou=0.6)
        self.assertTrue(snapped.snapped_to_cadastral)
        self.assertEqual(snapped.boundary, parcel)

    def test_does_not_snap_to_a_distant_parcel(self):
        """The failure worth guarding: parcels tile, so there is always a nearest.

        Snapping to it relocates the plot onto the neighbour's field while
        *raising* the apparent precision of the boundary.
        """
        neighbour = _square(200, dx=260.0)
        result = snap_to_cadastral(_delineation(), [neighbour], min_iou=0.6)
        self.assertFalse(result.snapped_to_cadastral)
        self.assertEqual(result.boundary, _delineation().boundary)

    def test_picks_the_best_candidate_not_the_first(self):
        far, near = _square(200, dx=90.0), _square(200, dx=8.0)
        snapped = snap_to_cadastral(_delineation(), [far, near], min_iou=0.5)
        self.assertEqual(snapped.boundary, near)

    def test_no_candidates_returns_the_delineation_unchanged(self):
        result = snap_to_cadastral(_delineation(), [], min_iou=0.6)
        self.assertFalse(result.snapped_to_cadastral)

    def test_snapping_preserves_confidence_and_the_composite_window(self):
        snapped = snap_to_cadastral(
            _delineation(confidence=0.83), [_square(200, dx=5.0)], min_iou=0.6
        )
        self.assertEqual(snapped.confidence, 0.83)
        self.assertEqual(snapped.composite_start, WINDOW[0])

    def test_min_iou_has_no_default(self):
        """The threshold that decides how often a plot lands on the neighbour.

        No phase document supplies it — §4 says "snap where available" and
        stops. Raised as a Phase 2 finding under LH-407.
        """
        with self.assertRaises(TypeError):
            snap_to_cadastral(_delineation(), [_square(200)])

    def test_rejects_an_out_of_range_min_iou(self):
        for bad in (0.0, 1.5, -0.3):
            with self.assertRaises(BoundaryError):
                snap_to_cadastral(_delineation(), [_square(200)], min_iou=bad)


if __name__ == "__main__":
    unittest.main()

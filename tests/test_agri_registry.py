"""Plot registry — WS-2.1 Step 2.

The centre of gravity here is one rule from Phase 2 §4: *never geocode a village
centroid and store it as a plot*. Every test in :class:`TestCentroidIsNotAPlot`
is an attempt to violate it through a different door, which is the only way to
show that the rule is structural rather than a convention someone remembered.
"""

from __future__ import annotations

import unittest
from datetime import date

from lending_hub.agri.geometry import Point, Polygon
from lending_hub.agri.registry import (
    CentroidAsPlot,
    Granularity,
    InMemoryPlotStore,
    Plot,
    PlotRegistry,
    PlotSource,
    RegistryError,
    VillageLocation,
)

EAST, NORTH = 500_000.0, 2_300_000.0


def _square(side: float, dx: float = 0.0, dy: float = 0.0) -> Polygon:
    x0, y0 = EAST + dx, NORTH + dy
    return Polygon(
        (Point(x0, y0), Point(x0 + side, y0), Point(x0 + side, y0 + side), Point(x0, y0 + side))
    )


def _plot(
    plot_id: str = "P1",
    *,
    source: PlotSource = PlotSource.GPS_WALK,
    confidence: float | None = None,
    borrower: str | None = "B1",
    side: float = 200.0,
) -> Plot:
    return Plot(
        plot_id=plot_id,
        boundary=_square(side),
        source=source,
        surveyed=date(2024, 6, 1),
        borrower_id=borrower,
        confidence=confidence,
    )


class TestCentroidIsNotAPlot(unittest.TestCase):
    """Phase 2 §4's rule, attacked from every direction it can be attacked."""

    def test_a_village_location_has_no_area(self):
        location = VillageLocation("B1", "VC-1", Point(EAST, NORTH), claimed_hectares=2.5)
        with self.assertRaises(CentroidAsPlot) as ctx:
            location.area_hectares
        self.assertIn("wrong land", str(ctx.exception))

    def test_a_village_location_is_not_a_plot(self):
        location = VillageLocation("B1", "VC-1")
        self.assertNotIsInstance(location, Plot)

    def test_a_claimed_area_never_becomes_an_observed_one(self):
        """The form number stays named as a form number.

        ``claimed_hectares`` exists because an application states an area, and
        the field name is the only thing that will still say "unverified" in two
        years. It must not be reachable through the property every other object
        uses for a real area.
        """
        location = VillageLocation("B1", "VC-1", claimed_hectares=3.0)
        self.assertEqual(location.claimed_hectares, 3.0)
        with self.assertRaises(CentroidAsPlot):
            location.area_hectares

    def test_granularity_is_reported_honestly(self):
        self.assertEqual(VillageLocation("B1", "VC-1").granularity, Granularity.VILLAGE)
        self.assertEqual(_plot().granularity, Granularity.PLOT)

    def test_a_village_location_needs_a_village_code_not_just_a_point(self):
        """A centroid alone cannot even join to village-level features."""
        with self.assertRaises(RegistryError) as ctx:
            VillageLocation("B1", "", Point(EAST, NORTH))
        self.assertIn("village code", str(ctx.exception))

    def test_a_borrower_with_no_plots_is_village_granularity(self):
        registry = PlotRegistry()
        registry.register_village(VillageLocation("B9", "VC-9"))
        self.assertEqual(registry.granularity_for("B9"), Granularity.VILLAGE)

    def test_a_borrower_with_no_location_at_all_raises(self):
        with self.assertRaises(RegistryError):
            PlotRegistry().granularity_for("nobody")


class TestPlotConstruction(unittest.TestCase):
    def test_a_tiny_boundary_is_a_gps_artefact(self):
        with self.assertRaises(RegistryError) as ctx:
            _plot(side=5.0)
        self.assertIn("GPS artefact", str(ctx.exception))

    def test_an_auto_delineated_plot_must_carry_its_confidence(self):
        with self.assertRaises(RegistryError) as ctx:
            _plot(source=PlotSource.AUTO_DELINEATED, confidence=None)
        self.assertIn("IoU gate", str(ctx.exception))

    def test_an_observed_plot_must_not_carry_a_confidence(self):
        """A walked perimeter is not a probabilistic claim.

        Giving it 1.0 would put ground truth and model output on one scale, and
        the next person to sort by confidence would see them interleaved.
        """
        for source in (PlotSource.GPS_WALK, PlotSource.CADASTRAL):
            with self.assertRaises(RegistryError) as ctx:
                _plot(source=source, confidence=1.0)
            self.assertIn("probabilistic claim", str(ctx.exception))

    def test_confidence_outside_the_unit_interval_is_refused(self):
        with self.assertRaises(RegistryError):
            _plot(source=PlotSource.AUTO_DELINEATED, confidence=1.4)

    def test_area_is_read_from_the_boundary(self):
        self.assertAlmostEqual(_plot(side=200.0).area_hectares, 4.0, places=9)


class TestRegistration(unittest.TestCase):
    def test_a_model_cannot_overwrite_a_walked_boundary(self):
        """The direction the overwrite always happens in.

        A re-delineation runs across a whole district, and the walked plots are
        inside it. Ground truth is not superseded by a model.
        """
        registry = PlotRegistry()
        registry.register_plot(_plot("P1", source=PlotSource.GPS_WALK))
        with self.assertRaises(RegistryError) as ctx:
            registry.register_plot(
                _plot("P1", source=PlotSource.AUTO_DELINEATED, confidence=0.9)
            )
        self.assertIn("Ground truth", str(ctx.exception))

    def test_a_walk_may_replace_a_walk(self):
        """A re-survey is legitimate; only the downgrade is refused."""
        registry = PlotRegistry()
        registry.register_plot(_plot("P1", side=200.0))
        registry.register_plot(_plot("P1", side=300.0))
        self.assertAlmostEqual(registry.plot("P1").area_hectares, 9.0, places=9)

    def test_a_walk_may_replace_a_delineation(self):
        registry = PlotRegistry()
        registry.register_plot(
            _plot("P1", source=PlotSource.AUTO_DELINEATED, confidence=0.8)
        )
        registry.register_plot(_plot("P1", source=PlotSource.GPS_WALK))
        self.assertIs(registry.plot("P1").source, PlotSource.GPS_WALK)

    def test_an_unregistered_plot_raises_rather_than_returning_none(self):
        with self.assertRaises(RegistryError):
            PlotRegistry().plot("nope")

    def test_an_unregistered_village_raises(self):
        with self.assertRaises(RegistryError):
            PlotRegistry().village("nope")

    def test_plots_for_a_borrower(self):
        registry = PlotRegistry()
        registry.register_plot(_plot("P1", borrower="B1"))
        registry.register_plot(_plot("P2", borrower="B1"))
        registry.register_plot(_plot("P3", borrower="B2"))
        self.assertEqual({p.plot_id for p in registry.plots_for("B1")}, {"P1", "P2"})

    def test_len_and_iteration(self):
        registry = PlotRegistry()
        registry.register_plot(_plot("P1"))
        registry.register_plot(_plot("P2"))
        self.assertEqual(len(registry), 2)
        self.assertEqual({p.plot_id for p in registry}, {"P1", "P2"})


class TestScoringGate(unittest.TestCase):
    def test_a_walked_plot_is_always_usable(self):
        registry = PlotRegistry()
        self.assertTrue(registry.usable_for_scoring(_plot(), iou_gate=0.75))

    def test_a_cadastral_plot_is_usable(self):
        registry = PlotRegistry()
        self.assertTrue(
            registry.usable_for_scoring(_plot(source=PlotSource.CADASTRAL), iou_gate=0.75)
        )

    def test_a_delineation_below_the_gate_is_not_an_input_at_all(self):
        """Phase 2 §4: below the gate, plots require a manual walk.

        Not a weaker input to down-weight. Not an input.
        """
        registry = PlotRegistry()
        below = _plot(source=PlotSource.AUTO_DELINEATED, confidence=0.62)
        self.assertFalse(registry.usable_for_scoring(below, iou_gate=0.75))

    def test_a_delineation_at_the_gate_is_usable(self):
        registry = PlotRegistry()
        at_gate = _plot(source=PlotSource.AUTO_DELINEATED, confidence=0.75)
        self.assertTrue(registry.usable_for_scoring(at_gate, iou_gate=0.75))

    def test_the_gate_has_no_default(self):
        """Passing it every time keeps a changed gate from being half-applied."""
        registry = PlotRegistry()
        with self.assertRaises(TypeError):
            registry.usable_for_scoring(_plot())


class TestGranularityForMixedBorrowers(unittest.TestCase):
    def test_one_walked_plot_does_not_make_the_whole_holding_plot_level(self):
        """The partial-boundary trap, stated as the registry sees it.

        A borrower with one walked plot and three unwalked ones is village
        granularity for anything that *sums* over their land. This test pins the
        current behaviour — the registry reports PLOT because a plot exists —
        and the consuming code in agri.features is where the sum is refused;
        see its aggregation tests.
        """
        registry = PlotRegistry()
        registry.register_plot(_plot("P1", borrower="B1"))
        registry.register_village(VillageLocation("B1", "VC-1", claimed_hectares=10.0))
        self.assertEqual(registry.granularity_for("B1"), Granularity.PLOT)
        self.assertEqual(len(registry.plots_for("B1")), 1)
        self.assertEqual(registry.village("B1").claimed_hectares, 10.0)


class TestInMemoryStore(unittest.TestCase):
    def test_satisfies_the_port(self):
        from lending_hub.agri.ports import PlotStore

        self.assertIsInstance(InMemoryPlotStore(), PlotStore)

    def test_get_returns_none_for_an_unknown_id(self):
        self.assertIsNone(InMemoryPlotStore().get("nope"))

    def test_put_and_all(self):
        store = InMemoryPlotStore()
        store.put(_plot("P1"))
        store.put(_plot("P2"))
        self.assertEqual(len(store.all()), 2)


if __name__ == "__main__":
    unittest.main()

"""Plot geometry — WS-2.1 Step 2.

Area, IoU and containment against closed forms, plus the two refusals that carry
real weight: unprojected coordinates, and a claimed-vs-observed area mismatch
whose sign is preserved.
"""

from __future__ import annotations

import math
import unittest

from lending_hub.agri.geometry import (
    DEGREE_LIKE_LIMIT,
    GeometryError,
    Point,
    Polygon,
    area_mismatch,
    intersection_area,
    iou,
)


def _square(x0: float, y0: float, side: float) -> Polygon:
    return Polygon(
        (
            Point(x0, y0),
            Point(x0 + side, y0),
            Point(x0 + side, y0 + side),
            Point(x0, y0 + side),
        )
    )


class TestPolygonConstruction(unittest.TestCase):
    def test_needs_three_vertices(self):
        with self.assertRaises(GeometryError):
            Polygon((Point(0, 0), Point(1000, 0)))

    def test_refuses_a_repeated_closing_vertex(self):
        """A duplicated last vertex passes every check and shifts the count."""
        with self.assertRaises(GeometryError) as ctx:
            Polygon(
                (Point(0, 0), Point(1000, 0), Point(1000, 1000), Point(0, 0))
            )
        self.assertIn("implicit", str(ctx.exception))

    def test_refuses_unprojected_lat_lon(self):
        """The refusal that stops an area coming out in square degrees.

        A field near Nagpur in lat/lon. Every coordinate is inside +/-180, so
        the constructor refuses rather than returning an area that is wrong by a
        latitude-dependent factor — which would make the same field in two
        districts have two different areas, straight into ExpectedIncome.
        """
        with self.assertRaises(GeometryError) as ctx:
            Polygon(
                (
                    Point(79.0882, 21.1458),
                    Point(79.0892, 21.1458),
                    Point(79.0892, 21.1468),
                    Point(79.0882, 21.1468),
                )
            )
        self.assertIn("ExpectedIncome", str(ctx.exception))

    def test_a_projected_polygon_straddling_the_origin_is_accepted(self):
        """One coordinate outside the degree band is enough to prove projection."""
        polygon = Polygon(
            (Point(-50, -50), Point(500, -50), Point(500, 500), Point(-50, 500))
        )
        self.assertGreater(polygon.area, 0)

    def test_the_projection_heuristic_has_a_known_blind_spot(self):
        """A small plot near the coordinate origin is refused, correctly-ish.

        A 100 m field sitting at (0, 0) in a projected CRS has every coordinate
        inside the degree band, so the heuristic cannot tell it from lat/lon and
        refuses it. That is the conservative direction — it costs a false
        refusal, where the alternative costs a silent square-degree area — but
        it is a real limitation and is pinned here so nobody "fixes" it by
        loosening the check.

        Real projected agri coordinates do not land here: a UTM easting is a
        six-digit number and an Indian northing a seven-digit one.
        """
        with self.assertRaises(GeometryError):
            _square(0, 0, 100)


class TestArea(unittest.TestCase):
    def test_square_area(self):
        self.assertEqual(_square(0, 0, 1000).area, 1_000_000.0)

    def test_hectares_conversion(self):
        self.assertEqual(_square(0, 0, 1000).area_hectares, 100.0)

    def test_triangle_area(self):
        triangle = Polygon((Point(0, 0), Point(1000, 0), Point(0, 800)))
        self.assertEqual(triangle.area, 400_000.0)

    def test_winding_order_does_not_change_the_unsigned_area(self):
        clockwise = Polygon(
            (Point(0, 0), Point(0, 1000), Point(1000, 1000), Point(1000, 0))
        )
        self.assertEqual(clockwise.area, _square(0, 0, 1000).area)
        self.assertLess(clockwise.signed_area, 0)
        self.assertGreater(_square(0, 0, 1000).signed_area, 0)

    def test_translation_invariance(self):
        self.assertAlmostEqual(
            _square(0, 0, 400).area, _square(9000, -3000, 400).area, places=6
        )

    def test_concave_l_shape(self):
        # An L: 1000x1000 square with a 400x400 bite out of the top right.
        polygon = Polygon(
            (
                Point(0, 0),
                Point(1000, 0),
                Point(1000, 600),
                Point(600, 600),
                Point(600, 1000),
                Point(0, 1000),
            )
        )
        self.assertEqual(polygon.area, 1_000_000.0 - 160_000.0)


class TestPerimeterAndCompactness(unittest.TestCase):
    def test_square_perimeter(self):
        self.assertEqual(_square(0, 0, 1000).perimeter, 4000.0)

    def test_a_square_has_the_textbook_compactness(self):
        self.assertAlmostEqual(_square(0, 0, 1000).compactness, math.pi / 4, places=12)

    def test_a_sliver_is_far_less_compact_than_a_square(self):
        """The sort order for boundaries an officer should look at first."""
        sliver = Polygon(
            (Point(0, 0), Point(4000, 0), Point(4000, 250), Point(0, 250))
        )
        self.assertLess(sliver.compactness, _square(0, 0, 1000).compactness)

    def test_compactness_approaches_one_for_a_many_sided_regular_polygon(self):
        vertices = tuple(
            Point(5000 * math.cos(2 * math.pi * i / 64), 5000 * math.sin(2 * math.pi * i / 64))
            for i in range(64)
        )
        self.assertAlmostEqual(Polygon(vertices).compactness, 1.0, delta=0.01)


class TestCentroid(unittest.TestCase):
    def test_square_centroid(self):
        centroid = _square(0, 0, 1000).centroid
        self.assertAlmostEqual(centroid.x, 500.0, places=9)
        self.assertAlmostEqual(centroid.y, 500.0, places=9)

    def test_triangle_centroid_is_the_vertex_mean(self):
        triangle = Polygon((Point(0, 0), Point(900, 0), Point(0, 600)))
        centroid = triangle.centroid
        self.assertAlmostEqual(centroid.x, 300.0, places=9)
        self.assertAlmostEqual(centroid.y, 200.0, places=9)

    def test_a_degenerate_polygon_has_no_centroid(self):
        collinear = Polygon((Point(0, 0), Point(500, 0), Point(1000, 0)))
        with self.assertRaises(GeometryError):
            collinear.centroid


class TestContains(unittest.TestCase):
    def test_interior_point(self):
        self.assertTrue(_square(0, 0, 1000).contains(Point(500, 500)))

    def test_exterior_point(self):
        self.assertFalse(_square(0, 0, 1000).contains(Point(1500, 500)))

    def test_concave_notch_is_outside(self):
        polygon = Polygon(
            (
                Point(0, 0),
                Point(1000, 0),
                Point(1000, 600),
                Point(600, 600),
                Point(600, 1000),
                Point(0, 1000),
            )
        )
        self.assertTrue(polygon.contains(Point(300, 800)))
        self.assertFalse(polygon.contains(Point(800, 800)))


class TestIntersectionAndIou(unittest.TestCase):
    def test_identical_polygons_have_iou_one(self):
        self.assertAlmostEqual(iou(_square(0, 0, 1000), _square(0, 0, 1000)), 1.0, places=9)

    def test_disjoint_polygons_have_iou_zero(self):
        self.assertEqual(iou(_square(0, 0, 1000), _square(5000, 5000, 1000)), 0.0)

    def test_half_overlap(self):
        """Two unit squares offset by half a side: overlap 1/2, union 3/2."""
        self.assertAlmostEqual(
            iou(_square(0, 0, 1000), _square(500, 0, 1000)), 1 / 3, places=9
        )

    def test_quarter_overlap(self):
        self.assertAlmostEqual(
            iou(_square(0, 0, 1000), _square(500, 500, 1000)), 1 / 7, places=9
        )

    def test_a_contained_polygon_gives_the_area_ratio(self):
        outer, inner = _square(0, 0, 1000), _square(250, 250, 500)
        self.assertAlmostEqual(iou(outer, inner), 250_000 / 1_000_000, places=9)

    def test_iou_is_symmetric(self):
        a, b = _square(0, 0, 1000), _square(300, 200, 800)
        self.assertAlmostEqual(iou(a, b), iou(b, a), places=9)

    def test_iou_is_bounded(self):
        for offset in (0, 100, 400, 900, 1200):
            value = iou(_square(0, 0, 1000), _square(offset, 0, 1000))
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)

    def test_intersection_area_of_disjoint_polygons_is_zero(self):
        self.assertEqual(
            intersection_area(_square(0, 0, 500), _square(9000, 9000, 500)), 0.0
        )

    def test_iou_of_a_delineation_that_missed_by_a_shift(self):
        """The realistic Model A failure: right size, wrong place.

        A 15 m shift on a 1 ha field (100 m square) drops IoU to about 0.57 —
        a 43% loss for a displacement of one and a half Sentinel-2 pixels. IoU
        is far harsher on translation than intuition suggests, which is what
        makes 0.75 a demanding gate rather than a formality: a delineation must
        be within roughly 7 m of the walked boundary to clear it.

        Placed at a UTM-like easting so the projection heuristic sees a
        projected polygon.
        """
        walked = _square(500_000, 2_300_000, 100)
        delineated = _square(500_015, 2_300_015, 100)
        self.assertAlmostEqual(iou(walked, delineated), 0.566, delta=0.01)
        self.assertLess(iou(walked, delineated), 0.75)


class TestAreaMismatch(unittest.TestCase):
    def test_over_claim_is_positive(self):
        """The fraud direction: a larger plot supports a larger loan."""
        observed = _square(0, 0, 1000)  # 100 ha
        self.assertAlmostEqual(area_mismatch(130.0, observed), 0.30, places=9)

    def test_under_claim_is_negative(self):
        observed = _square(0, 0, 1000)
        self.assertAlmostEqual(area_mismatch(80.0, observed), -0.20, places=9)

    def test_an_exact_claim_is_zero(self):
        self.assertAlmostEqual(area_mismatch(100.0, _square(0, 0, 1000)), 0.0, places=9)

    def test_the_phase_file_threshold_is_crossed_where_expected(self):
        """Phase 2 §4: >20% claimed-vs-observed mismatch is an underwriter flag."""
        observed = _square(0, 0, 1000)
        self.assertLess(abs(area_mismatch(119.0, observed)), 0.20)
        self.assertGreater(abs(area_mismatch(121.0, observed)), 0.20)

    def test_a_non_positive_claim_is_refused(self):
        for bad in (0.0, -5.0):
            with self.assertRaises(GeometryError):
                area_mismatch(bad, _square(0, 0, 1000))


if __name__ == "__main__":
    unittest.main()

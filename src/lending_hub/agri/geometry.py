"""Planar polygon geometry for plot boundaries (WS-2.1 Step 2).

Everything Phase 2 does with a polygon reduces to four operations: area,
intersection-over-union (Model A's gate metric), containment, and a validity
check. This module is those four, on the plane.

Why planar, and what that costs
--------------------------------
Field boundaries are lat/lon, and lat/lon is not a plane. The right answer is a
projected CRS — for India, one of the UTM zones or an equal-area projection —
applied before any area is computed. That projection is a Track B concern
(pyproj/GDAL), so this module takes **already-projected metre coordinates** and
says so in its signatures, rather than quietly treating degrees as metres.

The cost of getting this wrong is not academic. A degree of longitude is about
111 km at the equator and about 96 km at 30°N, so an area computed in degrees
and multiplied by a constant is wrong by a latitude-dependent factor — which
means a plot in one district and an identical plot in another get different
areas, and area multiplies straight through ``ExpectedIncome``. :func:`area`
therefore refuses coordinates that look like degrees.

What this does not port
-----------------------
No Shapely, no GEOS, no GDAL. There is no union, no buffer, no convex hull, no
topology repair and no spatial index. Intersection is implemented for convex
and simple concave polygons by Sutherland-Hodgman clipping, which is exact for
the convex case and can over-report for concave-on-concave — a limitation
stated rather than hidden, because a field boundary from a GPS walk is usually
near-convex and a delineated one always is after polygonisation.

Workstream: WS-2.1 Step 2 (SRS §3.1)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

#: Coordinates in metres. A polygon whose every coordinate is inside +/- 180 is
#: almost certainly unprojected lat/lon, and computing an area from it silently
#: produces square degrees. The check is a heuristic and it is deliberately a
#: refusal rather than an auto-projection: guessing the CRS is how a plot ends
#: up in the wrong hemisphere.
DEGREE_LIKE_LIMIT = 180.0

#: Smallest polygon this will treat as a plot, in square metres. Below roughly a
#: hundredth of a hectare a "field boundary" is a GPS artefact — an officer's
#: walk that closed on itself, or a delineation that latched onto a bund. It is
#: `[SPEC]`-free and stated as an engineering floor, not a policy minimum plot
#: size, which would be a `[POLICY]` value.
MIN_PLOT_AREA_SQM = 100.0


class GeometryError(Exception):
    """The polygon cannot support the operation asked of it."""


@dataclass(frozen=True)
class Point:
    """A projected coordinate, in metres."""

    x: float
    y: float


@dataclass(frozen=True)
class Polygon:
    """A simple closed polygon in projected metre coordinates.

    The ring is stored without a repeated closing vertex — the closure is
    implicit. Accepting both conventions is how a duplicated last point ends up
    contributing a zero-length edge to a shoelace sum that then reads fine, and
    an off-by-one vertex count that nothing notices.
    """

    vertices: tuple[Point, ...]

    def __post_init__(self) -> None:
        if len(self.vertices) < 3:
            raise GeometryError(
                f"a polygon needs at least 3 vertices, got {len(self.vertices)}"
            )
        if self.vertices[0] == self.vertices[-1]:
            raise GeometryError(
                "the ring is stored open — do not repeat the first vertex as "
                "the last. The closure is implicit, and a repeated vertex adds "
                "a zero-length edge that passes every check while shifting the "
                "vertex count."
            )
        if all(
            abs(v.x) <= DEGREE_LIKE_LIMIT and abs(v.y) <= DEGREE_LIKE_LIMIT
            for v in self.vertices
        ):
            raise GeometryError(
                "every coordinate is within +/-180, so these are almost "
                "certainly unprojected lat/lon degrees. Project to metres "
                "first: an area in square degrees is wrong by a "
                "latitude-dependent factor, so the same field measured in two "
                "districts returns two different areas — and area multiplies "
                "straight into ExpectedIncome."
            )

    @property
    def signed_area(self) -> float:
        """Shoelace signed area: positive counter-clockwise, negative clockwise."""
        total = 0.0
        n = len(self.vertices)
        for i in range(n):
            a, b = self.vertices[i], self.vertices[(i + 1) % n]
            total += a.x * b.y - b.x * a.y
        return total / 2.0

    @property
    def area(self) -> float:
        """Unsigned area in square metres."""
        return abs(self.signed_area)

    @property
    def area_hectares(self) -> float:
        """Area in hectares — the unit every agri credit conversation uses."""
        return self.area / 10_000.0

    @property
    def perimeter(self) -> float:
        n = len(self.vertices)
        return sum(
            math.dist(
                (self.vertices[i].x, self.vertices[i].y),
                (self.vertices[(i + 1) % n].x, self.vertices[(i + 1) % n].y),
            )
            for i in range(n)
        )

    @property
    def compactness(self) -> float:
        """Polsby-Popper compactness: ``4*pi*A / P^2``, 1.0 for a circle.

        A cheap sanity signal on an auto-delineated boundary. A polygon that
        snakes along a canal or wraps two fields joined by a track has low
        compactness, and while a genuinely irregular field is common enough that
        this can never be a rejection rule, it is a good sort order for the
        boundaries an officer should look at first.
        """
        perimeter = self.perimeter
        if perimeter == 0:
            raise GeometryError("degenerate polygon: zero perimeter")
        return 4.0 * math.pi * self.area / (perimeter * perimeter)

    @property
    def centroid(self) -> Point:
        """Area centroid of the polygon.

        Present for map rendering and nearest-neighbour work. It is emphatically
        **not** a substitute for a boundary: see
        :class:`lending_hub.agri.registry.PlotRegistry`, which refuses to store
        a point as a plot.
        """
        signed = self.signed_area
        if abs(signed) < 1e-12:
            raise GeometryError("degenerate polygon: zero area has no centroid")
        cx = cy = 0.0
        n = len(self.vertices)
        for i in range(n):
            a, b = self.vertices[i], self.vertices[(i + 1) % n]
            cross = a.x * b.y - b.x * a.y
            cx += (a.x + b.x) * cross
            cy += (a.y + b.y) * cross
        return Point(cx / (6.0 * signed), cy / (6.0 * signed))

    def contains(self, point: Point) -> bool:
        """Ray-casting point-in-polygon test.

        Boundary cases are not specified and not tested: a GPS fix landing
        exactly on a field edge to floating-point precision does not occur, and
        pretending to a rule about it would be a claim the implementation does
        not earn.
        """
        inside = False
        n = len(self.vertices)
        for i in range(n):
            a, b = self.vertices[i], self.vertices[(i + 1) % n]
            if (a.y > point.y) != (b.y > point.y):
                x_cross = a.x + (point.y - a.y) / (b.y - a.y) * (b.x - a.x)
                if point.x < x_cross:
                    inside = not inside
        return inside


def _clip(subject: Sequence[Point], clipper: Sequence[Point]) -> list[Point]:
    """Sutherland-Hodgman polygon clipping against a convex clipper."""
    output = list(subject)
    n = len(clipper)

    # Orient the clipper counter-clockwise so the inside test has one sign.
    if Polygon(tuple(clipper)).signed_area < 0:
        clipper = list(reversed(clipper))

    for i in range(n):
        if not output:
            return []
        edge_a, edge_b = clipper[i], clipper[(i + 1) % n]

        def inside(p: Point) -> bool:
            return (edge_b.x - edge_a.x) * (p.y - edge_a.y) - (
                edge_b.y - edge_a.y
            ) * (p.x - edge_a.x) >= 0

        def intersect(p: Point, q: Point) -> Point:
            x1, y1, x2, y2 = edge_a.x, edge_a.y, edge_b.x, edge_b.y
            x3, y3, x4, y4 = p.x, p.y, q.x, q.y
            denominator = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
            if abs(denominator) < 1e-12:
                return q
            a = x1 * y2 - y1 * x2
            b = x3 * y4 - y3 * x4
            return Point(
                (a * (x3 - x4) - (x1 - x2) * b) / denominator,
                (a * (y3 - y4) - (y1 - y2) * b) / denominator,
            )

        clipped: list[Point] = []
        previous = output[-1]
        for current in output:
            if inside(current):
                if not inside(previous):
                    clipped.append(intersect(previous, current))
                clipped.append(current)
            elif inside(previous):
                clipped.append(intersect(previous, current))
            previous = current
        output = clipped

    return output


def intersection_area(a: Polygon, b: Polygon) -> float:
    """Area of the overlap between two polygons.

    Exact when at least one is convex, which covers the case this is used for:
    IoU between a GPS-walk polygon and an auto-delineated one. Concave-on-concave
    can over-report, and no caller in Phase 2 is in that position — the
    polygonised output of a watershed segmentation is convex by construction
    after simplification.
    """
    clipped = _clip(a.vertices, b.vertices)
    if len(clipped) < 3:
        return 0.0
    # The clipped ring can carry duplicate vertices where an edge grazed the
    # clipper; the shoelace sum is unaffected, so no cleanup is needed. Build
    # the area directly rather than through Polygon, whose constructor
    # legitimately rejects such rings.
    total = 0.0
    n = len(clipped)
    for i in range(n):
        p, q = clipped[i], clipped[(i + 1) % n]
        total += p.x * q.y - q.x * p.y
    return abs(total) / 2.0


def iou(a: Polygon, b: Polygon) -> float:
    """Intersection over union — Model A's gate metric (Phase 2 §4 WS-2.2).

    The metric the phase file sets a threshold on: median IoU vs. held-out
    GPS-walk polygons must reach 0.75 before auto-delineations are shown at all.
    Defined on areas, so it is scale-free and comparable across plot sizes,
    which a boundary-distance metric would not be.
    """
    overlap = intersection_area(a, b)
    union = a.area + b.area - overlap
    if union <= 0:
        raise GeometryError("both polygons have zero area; IoU is undefined")
    return overlap / union


def area_mismatch(claimed_hectares: float, observed: Polygon) -> float:
    """Relative mismatch between a claimed area and an observed boundary.

    Phase 2 §4 makes ``> 20%`` an underwriter fraud flag. Returned as a signed
    relative difference so the *direction* survives: over-claiming is the fraud
    pattern (a larger plot supports a larger loan), while under-claiming is
    usually a plot that was subdivided or partly sold, which is a different
    conversation.
    """
    if claimed_hectares <= 0:
        raise GeometryError(
            f"claimed area must be positive, got {claimed_hectares} ha"
        )
    observed_hectares = observed.area_hectares
    if observed_hectares <= 0:
        raise GeometryError("observed polygon has zero area")
    return (claimed_hectares - observed_hectares) / observed_hectares

"""Plot registry — the rule that a centroid is not a plot (WS-2.1 Step 2).

Phase 2 §4 states it in prose:

    Where no polygon exists: **never geocode a village centroid and store it as
    a plot** — village-granularity features are stored at village level and
    flagged as such.

Prose survives exactly as long as the first officer under a deadline with a
disbursal to clear. Here it is a type: a :class:`VillageLocation` is not a
:class:`Plot`, does not have an area, and cannot be handed to anything that
computes one. The registry has two stores and no path between them.

Why this specific rule earns an enforcement mechanism
------------------------------------------------------
A geocoded centroid is not merely imprecise, it is *confidently wrong in a way
that propagates*. Give it a nominal area and it acquires an ``ExpectedIncome``,
a ``LandQualityIndex`` and an NDVI series — the NDVI of whatever happens to sit
at the village centre, which is frequently the village itself. Every one of
those numbers is well-formed, plausible, and about the wrong land. Nothing
downstream can distinguish it from a walked plot, which is why the distinction
has to be made upstream and structurally.

Phase 2 §8 also puts it on the do-not-invent list — "any plot polygon not
observed or walked" — and it is the only entry on that list an implementer can
violate by accident rather than by guessing a number.

Confidence is not a score
--------------------------
:class:`PlotSource` records *how* a boundary was obtained, and the ordering
between the three is a fact about provenance, not a tunable. An auto-delineated
boundary below the Model A IoU gate is not a low-confidence plot to be used with
care; Phase 2 §4 says those plots "require a manual walk", so
:meth:`PlotRegistry.usable_for_scoring` refuses them.

What this does not port
-----------------------
No PostGIS, no spatial index, no R-tree, no topology validation beyond the
polygon's own. The Track B store is PostGIS behind
:class:`~lending_hub.agri.ports.PlotStore`; this is a dict, which is what makes
the *rules* testable without a database.

Workstream: WS-2.1 Step 2 (SRS §3.1)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Iterator

from lending_hub.agri.geometry import MIN_PLOT_AREA_SQM, GeometryError, Point, Polygon


class RegistryError(Exception):
    """A registry invariant was violated."""


class CentroidAsPlot(RegistryError):
    """Someone tried to store a point-derived location as a plot boundary.

    Its own exception type, because it is the one registry error that must never
    be handled by widening the input. A caller catching this and retrying with a
    square drawn around the centroid has defeated the rule completely, and the
    exception name is the last chance to say so.
    """


class PlotSource(str, Enum):
    """How a boundary was obtained. Phase 2 §4 WS-2.1 Step 2 names all three."""

    GPS_WALK = "gps_walk"
    """An officer walked the perimeter with the field app. The ground truth
    channel — Model A is trained and gated against these, and they are the only
    boundaries admissible as labels."""

    CADASTRAL = "cadastral"
    """Digitised from the revenue record. Authoritative on *ownership*, which is
    not the same as authoritative on what is currently farmed: cadastral parcels
    lag subdivision by years and are frequently a different shape from the
    working field."""

    AUTO_DELINEATED = "auto_delineated"
    """Model A output. Usable only above the IoU gate, per Phase 2 §4 — below
    it, the plot requires a manual walk."""


class Granularity(str, Enum):
    """The spatial resolution a feature is honest at."""

    PLOT = "plot"
    VILLAGE = "village"


@dataclass(frozen=True)
class Plot:
    """A registered plot with an observed boundary.

    There is no constructor path that produces a ``Plot`` without a
    :class:`~lending_hub.agri.geometry.Polygon`. That is the enforcement: the
    absence of a "point plus nominal area" constructor is what makes the §4 rule
    a property of the type rather than a convention.
    """

    plot_id: str
    boundary: Polygon
    source: PlotSource
    surveyed: date
    borrower_id: str | None = None
    confidence: float | None = None
    """Model A's confidence for an auto-delineated boundary; ``None`` for an
    observed one, because a walked perimeter is not a probabilistic claim and
    giving it a 1.0 would put it on the same scale as a model output."""

    def __post_init__(self) -> None:
        if self.boundary.area < MIN_PLOT_AREA_SQM:
            raise RegistryError(
                f"{self.plot_id}: boundary area {self.boundary.area:.1f} m2 is "
                f"below the {MIN_PLOT_AREA_SQM:.0f} m2 floor. At that size this "
                "is a GPS artefact — a walk that closed on itself, or a "
                "delineation that latched onto a bund."
            )
        if self.source is PlotSource.AUTO_DELINEATED and self.confidence is None:
            raise RegistryError(
                f"{self.plot_id}: an auto-delineated boundary must carry the "
                "model confidence that produced it. Without it the IoU gate "
                "cannot be applied per plot, and the gate is what stands "
                "between a delineation and an underwriter."
            )
        if self.source is not PlotSource.AUTO_DELINEATED and self.confidence is not None:
            raise RegistryError(
                f"{self.plot_id}: an observed boundary ({self.source.value}) "
                "must not carry a model confidence — a walked perimeter is not "
                "a probabilistic claim, and scoring it alongside model output "
                "makes the two look comparable."
            )
        if not 0.0 <= (self.confidence if self.confidence is not None else 0.0) <= 1.0:
            raise RegistryError(
                f"{self.plot_id}: confidence {self.confidence} is outside [0, 1]"
            )

    @property
    def area_hectares(self) -> float:
        return self.boundary.area_hectares

    @property
    def granularity(self) -> Granularity:
        return Granularity.PLOT


@dataclass(frozen=True)
class VillageLocation:
    """Village-granularity location for a borrower with no observed boundary.

    Deliberately **not** a :class:`Plot` and deliberately without an area. It
    carries a centroid for map rendering and a village code for joining
    village-level features, and there is no method here that returns a boundary.

    The declared hectares a borrower states is kept as ``claimed_hectares`` —
    unverified, and named so. It is a number from an application form, and the
    field name is the only thing that will still say so in two years.
    """

    borrower_id: str
    village_code: str
    centroid: Point | None = None
    claimed_hectares: float | None = None

    def __post_init__(self) -> None:
        if not self.village_code:
            raise RegistryError(
                f"{self.borrower_id}: a village location needs a village code; "
                "a centroid alone cannot be joined to village-level features"
            )
        if self.claimed_hectares is not None and self.claimed_hectares <= 0:
            raise RegistryError(
                f"{self.borrower_id}: claimed area must be positive if given"
            )

    @property
    def granularity(self) -> Granularity:
        return Granularity.VILLAGE

    @property
    def area_hectares(self) -> float:
        raise CentroidAsPlot(
            f"{self.borrower_id} has village-level location only, not a plot "
            "boundary. There is no area here to compute with. Phase 2 §4: never "
            "geocode a village centroid and store it as a plot — a nominal area "
            "around a centroid acquires an ExpectedIncome and an NDVI series "
            "for whatever sits at the village centre, and every one of those "
            "numbers is well-formed, plausible and about the wrong land."
        )


class InMemoryPlotStore:
    """Track A implementation of :class:`~lending_hub.agri.ports.PlotStore`."""

    def __init__(self) -> None:
        self._plots: dict[str, Plot] = {}

    def put(self, plot: Plot) -> None:
        self._plots[plot.plot_id] = plot

    def get(self, plot_id: str) -> Plot | None:
        return self._plots.get(plot_id)

    def all(self) -> tuple[Plot, ...]:
        return tuple(self._plots.values())


class PlotRegistry:
    """Two stores, no path between them.

    Plots hold observed boundaries. Village locations hold everything else. A
    borrower can appear in both — some of their land walked, some not — and the
    registry reports which features are honest at which granularity rather than
    resolving it silently in either direction.
    """

    def __init__(self, store: InMemoryPlotStore | None = None) -> None:
        self._store = store or InMemoryPlotStore()
        self._villages: dict[str, VillageLocation] = {}

    # -- registration -----------------------------------------------------

    def register_plot(self, plot: Plot) -> None:
        existing = self._store.get(plot.plot_id)
        if existing is not None and existing.source is PlotSource.GPS_WALK:
            if plot.source is not PlotSource.GPS_WALK:
                raise RegistryError(
                    f"{plot.plot_id}: refusing to overwrite a GPS-walk boundary "
                    f"with a {plot.source.value} one. Ground truth is not "
                    "superseded by a model, and this is the direction the "
                    "overwrite always happens in — a re-delineation runs over "
                    "the whole district and the walked plots are in it."
                )
        self._store.put(plot)

    def register_village(self, location: VillageLocation) -> None:
        self._villages[location.borrower_id] = location

    # -- lookup -----------------------------------------------------------

    def plot(self, plot_id: str) -> Plot:
        plot = self._store.get(plot_id)
        if plot is None:
            raise RegistryError(f"no plot registered as {plot_id!r}")
        return plot

    def village(self, borrower_id: str) -> VillageLocation:
        location = self._villages.get(borrower_id)
        if location is None:
            raise RegistryError(f"no village location for borrower {borrower_id!r}")
        return location

    def plots_for(self, borrower_id: str) -> tuple[Plot, ...]:
        return tuple(
            p for p in self._store.all() if p.borrower_id == borrower_id
        )

    def granularity_for(self, borrower_id: str) -> Granularity:
        """The finest granularity at which this borrower's features are honest.

        A borrower with one walked plot and three unwalked ones is **village**
        granularity for anything that sums over their land, and plot granularity
        only for the walked plot itself. Returning PLOT because *a* plot exists
        is how a partial boundary set becomes a total income estimate.
        """
        if self.plots_for(borrower_id):
            return Granularity.PLOT
        if borrower_id in self._villages:
            return Granularity.VILLAGE
        raise RegistryError(f"borrower {borrower_id!r} has no location at all")

    # -- the gate ---------------------------------------------------------

    def usable_for_scoring(self, plot: Plot, *, iou_gate: float) -> bool:
        """Whether this boundary may be shown or scored against.

        Phase 2 §4 WS-2.2 Model A: below the IoU gate, "plots require a manual
        walk". So an auto-delineated boundary whose confidence is under the gate
        is not a weaker input to be down-weighted — it is not an input.

        ``iou_gate`` is required with no default. The phase file states 0.75
        `[SPEC]`, and :data:`MODEL_A_IOU_GATE` carries it; making the caller
        pass it keeps a *changed* gate from being applied in one place and
        forgotten in another.
        """
        if plot.source in (PlotSource.GPS_WALK, PlotSource.CADASTRAL):
            return True
        if plot.confidence is None:  # pragma: no cover - constructor prevents it
            raise RegistryError(f"{plot.plot_id}: auto-delineated with no confidence")
        return plot.confidence >= iou_gate

    def __iter__(self) -> Iterator[Plot]:
        return iter(self._store.all())

    def __len__(self) -> int:
        return len(self._store.all())

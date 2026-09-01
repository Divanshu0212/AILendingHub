"""The Track B seam for everything Phase 2 cannot hold in a laptop.

Phase 2 is the most backend-dependent phase in the programme: it wants a raster
archive (Copernicus), a spatial database (PostGIS), a gridded weather store
(CHIRPS/ERA5/IMD) and a mobile capture channel. ADR-0003 says none of those may
be imported by core code, so each one appears here as a protocol that Track A
satisfies in memory and Track B satisfies with the real backend.

Why these are protocols and not stubs
-------------------------------------
A stub returns a plausible value. Every port here either returns data it was
given or raises :class:`SceneUnavailable` — because the failure mode this phase
must not have is a model that scores a plot from a scene that was never
acquired. Cloud cover means a Sentinel-2 revisit routinely yields *nothing* over
a district, and a pipeline that quietly substitutes the previous scene turns a
missing observation into a stale one, which reads identically downstream and is
worse: a stale NDVI says the crop is fine.

What this does not port
-----------------------
No GDAL, no rasterio, no psycopg, no boto. There is no reprojection, no tiling
and no COG reader here; :class:`SceneSource` is where those live on Track B. The
in-memory implementations exist so the *pipeline* is testable, not so anyone can
process imagery without them.

Workstream: WS-2.1 (SRS §3.2, §3.3)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol, Sequence, runtime_checkable


class SceneUnavailable(Exception):
    """No observation exists for this plot on this date.

    Deliberately an exception rather than a ``None`` that flows onward. An
    unacquired scene and a scene showing bare soil are different facts about a
    plot, and only one of them means the crop failed.
    """


class PortNotConfigured(Exception):
    """A Track B backend was requested and no adapter is bound.

    Raised rather than falling back to an in-memory implementation: a
    production job that silently ran against an empty in-memory registry would
    report every plot as unregistered, which looks like a data problem rather
    than a configuration one.
    """


@dataclass(frozen=True)
class Observation:
    """One sensor reading for one plot on one date.

    ``value`` is the band or index value; ``valid`` records whether the pixel
    survived cloud masking. An invalid observation is *kept* rather than
    dropped, because the count of masked revisits is itself a data-quality
    signal — a plot under monsoon cloud for six weeks has a defensible NDVI
    series only if the gap is visible.
    """

    plot_id: str
    acquired: date
    value: float
    valid: bool = True
    sensor: str = ""


@runtime_checkable
class SceneSource(Protocol):
    """Access to imagery-derived observations for a plot.

    Track B: Copernicus Data Space (Sentinel-2 L2A, Sentinel-1 GRD) behind a COG
    store. Track A: whatever a test hands it.
    """

    def series(self, plot_id: str, start: date, end: date) -> Sequence[Observation]:
        """Observations for ``plot_id`` in ``[start, end]``, ascending by date.

        Must raise :class:`SceneUnavailable` if the archive holds no acquisition
        in the window at all — an empty series and an unqueried archive must not
        be the same return value.
        """
        ...


@runtime_checkable
class WeatherSource(Protocol):
    """Gridded weather for a location.

    Track B: CHIRPS rainfall, ERA5 reanalysis, IMD gridded. Track A: a mapping.
    """

    def monthly_totals(self, cell_id: str, start: date, end: date) -> Sequence[float]:
        """Monthly accumulations (mm) for a grid cell, ascending by month."""
        ...


@runtime_checkable
class PlotStore(Protocol):
    """Persistence for the plot registry.

    Track B: PostGIS. Track A: :class:`lending_hub.agri.registry.InMemoryPlotStore`.
    """

    def put(self, plot) -> None: ...

    def get(self, plot_id: str): ...

    def all(self) -> Sequence: ...

"""Ingestion contracts and completeness monitors (WS-2.1 Step 1).

Phase 2 §4 asks for "per-source ingestion DAGs with missing-tile completeness
monitors". The DAGs are Airflow and therefore Track B (ADR-0002). What ships
here is the part that has to be right whatever the orchestrator is: the
**contract each source must satisfy**, and the monitor that says whether a day's
ingest actually happened.

Why a completeness monitor is not a nice-to-have here
------------------------------------------------------
Every other source in this programme fails loudly. A CBS extract that does not
arrive leaves a table with yesterday's max date and somebody notices by lunch.
Imagery does not work that way: a Sentinel-2 revisit legitimately produces
nothing over a district — wrong orbit day, or total cloud — so *absence is
normal*, and the pipeline cannot distinguish "no acquisition today" from "the
ingest job died three weeks ago" without an expected-count model. Absent that,
the failure mode is a plot whose NDVI series simply stops, scored against
whatever the last observation was, indefinitely.

The three completeness questions are different questions
---------------------------------------------------------
* **Tile completeness** — did we get the tiles the orbit should have produced?
  A job-health question.
* **Usable completeness** — of what arrived, how much survived cloud masking?
  A climate question, and it is *supposed* to be low in monsoon.
* **Plot coverage** — what share of registered plots have a usable observation
  in the window? The only one that gates a credit decision.

Reporting one number for all three is how a monsoon gets escalated as an outage
and an outage gets dismissed as monsoon.

The revision problem
---------------------
ERA5 and CHIRPS are *reanalysis* products: values are revised after first
publication, sometimes months later. The source registry already records this
(`config/sources/weather.yaml`). :class:`IngestRecord` carries the provider
vintage for the same reason — a point-in-time join on observation date alone
picks up a revised value that did not exist at the decision point, and a
backtest built that way looks better than the system could ever have performed.

What this does not port
-----------------------
No Airflow, no scheduler, no retry policy, no object store. There is no tile
grid arithmetic (MGRS) here either — the expected tile count per district is a
Track B question about the operating footprint, and a wrong constant would make
every completeness figure wrong in the same direction.

Workstream: WS-2.1 Step 1 (SRS §2.1, §3.2)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
from typing import Iterable, Mapping, Sequence


class IngestError(Exception):
    """An ingest contract was violated, or a monitor cannot be computed."""


class Sensor(str, Enum):
    """The sources Phase 2 §4 WS-2.1 Step 1 names."""

    SENTINEL2_L2A = "sentinel2_l2a"
    SENTINEL1_GRD = "sentinel1_grd"
    CHIRPS = "chirps"
    ERA5 = "era5"
    IMD_GRIDDED = "imd_gridded"
    SOILGRIDS = "soilgrids"
    COPERNICUS_DEM = "copernicus_dem"


#: Nominal revisit interval in days, per sensor. `[SPEC]` from each mission's
#: published specification, not tuned.
#:
#: These are **constellation** figures and they move: Sentinel-2's 5-day revisit
#: assumes both 2A and 2B operating, and Sentinel-1's 6-day assumed 1A and 1B
#: before 1B failed in December 2021. A monitor that hard-coded them would have
#: reported that failure as a data-quality collapse across every plot at once,
#: which is why :func:`tile_completeness` takes the interval as an argument and
#: this mapping is only the default starting point.
NOMINAL_REVISIT_DAYS: Mapping[Sensor, int] = {
    Sensor.SENTINEL2_L2A: 5,
    Sensor.SENTINEL1_GRD: 6,
    Sensor.CHIRPS: 1,
    Sensor.ERA5: 1,
    Sensor.IMD_GRIDDED: 1,
}

#: Sources with no revisit cadence at all — static rasters published once and
#: revised on the publisher's schedule. Asking a completeness monitor about them
#: is a category error, and :func:`tile_completeness` says so rather than
#: dividing by an invented interval.
STATIC_SOURCES = frozenset({Sensor.SOILGRIDS, Sensor.COPERNICUS_DEM})


@dataclass(frozen=True)
class IngestRecord:
    """One ingest of one source for one day over one footprint.

    ``vintage`` is the provider's product version for this observation date. It
    is required for reanalysis sources and is the field that makes a
    point-in-time join honest — see the module docstring.
    """

    sensor: Sensor
    observation_date: date
    footprint_id: str
    tiles_expected: int
    tiles_received: int
    ingested_at: date
    vintage: str | None = None

    def __post_init__(self) -> None:
        if self.tiles_expected < 0 or self.tiles_received < 0:
            raise IngestError(
                f"{self.sensor.value} {self.observation_date}: tile counts must "
                f"be non-negative ({self.tiles_expected}, {self.tiles_received})"
            )
        if self.tiles_received > self.tiles_expected:
            raise IngestError(
                f"{self.sensor.value} {self.observation_date}: received "
                f"{self.tiles_received} tiles against {self.tiles_expected} "
                "expected. More than expected is not a windfall — it means the "
                "footprint model is wrong, and every completeness figure "
                "computed from it is wrong too."
            )
        if self.ingested_at < self.observation_date:
            raise IngestError(
                f"{self.sensor.value}: ingested_at {self.ingested_at} precedes "
                f"observation_date {self.observation_date}. A tile cannot be "
                "ingested before it was acquired; this is a clock or a "
                "column-mapping fault, and either one invalidates the "
                "point-in-time join."
            )
        if self.sensor in (Sensor.ERA5, Sensor.CHIRPS) and not self.vintage:
            raise IngestError(
                f"{self.sensor.value} is a reanalysis product and must record "
                "its provider vintage. Values are revised after publication, so "
                "a point-in-time join on observation date alone picks up a "
                "figure that did not exist at the decision point — and a "
                "backtest built that way outperforms anything the live system "
                "could have achieved."
            )

    @property
    def publication_lag_days(self) -> int:
        return (self.ingested_at - self.observation_date).days

    @property
    def is_complete(self) -> bool:
        return self.tiles_expected > 0 and self.tiles_received == self.tiles_expected


@dataclass(frozen=True)
class CompletenessReport:
    """The three questions, answered separately.

    ``plot_coverage`` is ``None`` when no plot registry was supplied. It is not
    zero: "we did not ask" and "no plot was covered" are different, and only the
    second should stop a disbursal.
    """

    sensor: Sensor
    start: date
    end: date
    tile_completeness: float
    usable_fraction: float | None
    plot_coverage: float | None
    days_with_no_ingest: tuple[date, ...]
    expected_ingest_days: int

    @property
    def has_gap(self) -> bool:
        """Whether any expected ingest day produced no record at all.

        This is the job-health signal, and it is deliberately separate from a
        low ``usable_fraction``: monsoon cloud drives the second to near zero
        while the first stays clean, and conflating them is how a dead DAG hides
        behind the weather.
        """
        return bool(self.days_with_no_ingest)


def expected_ingest_days(start: date, end: date, revisit_days: int) -> int:
    """How many acquisitions the orbit should have produced in the window."""
    if revisit_days < 1:
        raise IngestError(f"revisit interval must be >= 1 day, got {revisit_days}")
    if start > end:
        raise IngestError(f"window {start}..{end} is inverted")
    return ((end - start).days // revisit_days) + 1


def tile_completeness(
    records: Sequence[IngestRecord],
    sensor: Sensor,
    start: date,
    end: date,
    *,
    revisit_days: int | None = None,
    usable_tiles: Mapping[date, int] | None = None,
    plots_total: int | None = None,
    plots_covered: int | None = None,
) -> CompletenessReport:
    """The WS-2.1 completeness monitor.

    ``revisit_days`` defaults to :data:`NOMINAL_REVISIT_DAYS` for the sensor but
    should be passed explicitly whenever the constellation state is known — see
    the note on that mapping.

    Static sources are refused rather than given a nominal interval: SoilGrids
    has no revisit, and a completeness figure for it would be arithmetic
    performed on a category error.
    """
    if sensor in STATIC_SOURCES:
        raise IngestError(
            f"{sensor.value} is a static raster with no revisit cadence. "
            "A completeness ratio for it has no denominator — check its "
            "publication vintage instead."
        )

    if revisit_days is None:
        if sensor not in NOMINAL_REVISIT_DAYS:
            raise IngestError(f"no nominal revisit interval known for {sensor.value}")
        revisit_days = NOMINAL_REVISIT_DAYS[sensor]

    window = [
        r
        for r in records
        if r.sensor is sensor and start <= r.observation_date <= end
    ]

    expected_tiles = sum(r.tiles_expected for r in window)
    received_tiles = sum(r.tiles_received for r in window)
    expected_days = expected_ingest_days(start, end, revisit_days)

    if expected_tiles == 0:
        # No record claimed to expect anything. That is itself the finding.
        completeness = 0.0
    else:
        completeness = received_tiles / expected_tiles

    observed_days = {r.observation_date for r in window}
    missing = tuple(
        start + timedelta(days=offset * revisit_days)
        for offset in range(expected_days)
        if start + timedelta(days=offset * revisit_days) not in observed_days
    )

    usable_fraction = None
    if usable_tiles is not None:
        usable = sum(count for day, count in usable_tiles.items() if start <= day <= end)
        usable_fraction = usable / received_tiles if received_tiles else 0.0

    coverage = None
    if plots_total is not None:
        if plots_total <= 0:
            raise IngestError(
                "plot coverage over zero registered plots is undefined; report "
                "the empty registry rather than a ratio"
            )
        if plots_covered is None:
            raise IngestError("plots_total was given without plots_covered")
        if plots_covered > plots_total:
            raise IngestError(
                f"{plots_covered} plots covered exceeds {plots_total} registered"
            )
        coverage = plots_covered / plots_total

    return CompletenessReport(
        sensor=sensor,
        start=start,
        end=end,
        tile_completeness=completeness,
        usable_fraction=usable_fraction,
        plot_coverage=coverage,
        days_with_no_ingest=missing,
        expected_ingest_days=expected_days,
    )


def publication_lag_percentile(
    records: Iterable[IngestRecord], percentile: float
) -> int:
    """Publication lag at a percentile, in days.

    The freshness figure the P2 monitoring loop reports. Nearest-rank rather
    than interpolated, because a lag is a whole number of days and an
    interpolated 2.4-day lag describes nothing that happened.
    """
    if not 0.0 < percentile <= 1.0:
        raise IngestError(f"percentile must be in (0, 1], got {percentile}")
    lags = sorted(r.publication_lag_days for r in records)
    if not lags:
        raise IngestError(
            "no ingest records; an empty window is not a fast one. Report the "
            "absence rather than a percentile over nothing."
        )
    index = max(0, min(len(lags) - 1, int(-(-percentile * len(lags) // 1)) - 1))
    return lags[index]

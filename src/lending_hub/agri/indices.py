"""Vegetation and backscatter time series per plot (WS-2.1 Step 3).

NDVI is the workhorse: ``(NIR - Red)/(NIR + Red)``, bounded in [-1, 1], high
where there is dense green biomass. EVI is its correction for the two places
NDVI misleads — it saturates over dense canopy, and it responds to soil
brightness and aerosol on sparse cover, which is most of a smallholder plot for
half the season.

Two things dominate the design, and neither is about the arithmetic.

Cloud masking is not a filter, it is a census
---------------------------------------------
Sentinel-2's scene-classification layer labels every pixel, and the phase file
says to mask on it. The temptation is to drop masked observations and carry on.
That is wrong here, because **the number of masked revisits is itself the
signal**: a plot under monsoon cloud for six weeks has an NDVI series with a
six-week hole, and a model that cannot see the hole reads the pre-cloud value
as current. :class:`IndexSeries` therefore keeps the invalid observations and
reports :attr:`IndexSeries.valid_fraction`, and every derived statistic states
how many observations it actually saw.

Gaps are never filled silently
-------------------------------
:func:`interpolate` exists, and it is opt-in and labelled. An interpolated NDVI
is a *model output*, not an observation, and the distinction is the whole basis
on which the crop verification stream can be used as evidence: "the plot was
green on 14 July" and "the plot was probably green on 14 July given it was green
on 2 July and 26 July" are different claims to put in front of an underwriter.

What this does not port
-----------------------
No GDAL, no rasterio, no scene reading, no reprojection, no cloud-shadow
geometry. Per-pixel work happens on Track B behind :class:`~lending_hub.agri.ports.SceneSource`;
what arrives here is already a per-plot reduction. There is no Savitzky-Golay
or Whittaker smoother — the phenology literature's standard smoothers assume a
regular grid, and an optical revisit series under cloud is anything but.

Workstream: WS-2.1 Step 3 (SRS §3.2, §3.3)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from enum import IntEnum
from typing import Iterable, Sequence

from lending_hub.agri.ports import Observation


class VegetationIndexError(Exception):
    """The observations cannot support the statistic being asked of them."""


class SceneClass(IntEnum):
    """Sentinel-2 Level-2A scene-classification layer values.

    `[SPEC]` — these are the published SCL codes from the Sentinel-2 L2A product
    definition, not a local convention. They are an ESA product specification
    rather than a bank policy value, which is why they are constants here and
    not a `[POLICY]` placeholder.
    """

    NO_DATA = 0
    SATURATED_DEFECTIVE = 1
    DARK_AREA_PIXELS = 2
    CLOUD_SHADOWS = 3
    VEGETATION = 4
    NOT_VEGETATED = 5
    WATER = 6
    UNCLASSIFIED = 7
    CLOUD_MEDIUM_PROBABILITY = 8
    CLOUD_HIGH_PROBABILITY = 9
    THIN_CIRRUS = 10
    SNOW_ICE = 11


#: Classes on which a vegetation index is not interpretable.
#:
#: Medium-probability cloud is included deliberately. It is the marginal call:
#: excluding it costs observations in exactly the season when revisits are
#: scarcest, and including it admits pixels whose NDVI is depressed by thin
#: cloud — which looks like crop stress and is the more expensive error, because
#: it fires a distress flag on a healthy plot.
UNUSABLE_SCENE_CLASSES = frozenset(
    {
        SceneClass.NO_DATA,
        SceneClass.SATURATED_DEFECTIVE,
        SceneClass.CLOUD_SHADOWS,
        SceneClass.CLOUD_MEDIUM_PROBABILITY,
        SceneClass.CLOUD_HIGH_PROBABILITY,
        SceneClass.THIN_CIRRUS,
        SceneClass.SNOW_ICE,
    }
)

#: EVI coefficients from Huete et al. (2002), the MODIS EVI product definition
#: that Sentinel-2 EVI follows. `[SPEC]`: published constants, not tuned.
EVI_GAIN = 2.5
EVI_C1 = 6.0
EVI_C2 = 7.5
EVI_SOIL_ADJUSTMENT = 1.0


def ndvi(nir: float, red: float) -> float:
    """Normalised Difference Vegetation Index.

    Raises on a zero denominator rather than returning 0.0. ``NIR + Red == 0``
    means both bands read zero — a no-data pixel, not a plot with no vegetation
    — and 0.0 is a perfectly ordinary NDVI for bare soil, so the two would be
    indistinguishable downstream.
    """
    denominator = nir + red
    if denominator == 0:
        raise VegetationIndexError(
            "NDVI is undefined when NIR + Red == 0; that is a no-data pixel, "
            "and returning 0.0 would make it indistinguishable from bare soil"
        )
    return (nir - red) / denominator


def evi(nir: float, red: float, blue: float) -> float:
    """Enhanced Vegetation Index (Huete et al., 2002).

    Corrects NDVI's two failure modes: canopy saturation (the ``C1``/``C2``
    aerosol terms) and soil-brightness sensitivity (the ``L`` adjustment). Worth
    the extra band on agri plots specifically, because a smallholder field
    spends much of the season at the sparse-cover end where NDVI is most
    soil-contaminated.
    """
    denominator = nir + EVI_C1 * red - EVI_C2 * blue + EVI_SOIL_ADJUSTMENT
    if denominator == 0:
        raise VegetationIndexError("EVI denominator is zero; the reflectances are unusable")
    return EVI_GAIN * (nir - red) / denominator


def backscatter_db(linear_power: float) -> float:
    """Sentinel-1 backscatter in decibels: ``10 log10(sigma0)``.

    SAR is the reason this phase is viable in a monsoon at all — it penetrates
    cloud, so a Sentinel-1 revisit produces an observation on a day when every
    optical band is white. It answers a different question (structure and
    moisture, not greenness), which is why VV/VH is carried alongside NDVI
    rather than substituted for it.

    Values are converted to dB because backscatter spans orders of magnitude in
    linear power and every published threshold in the SAR literature is in dB.
    """
    if linear_power <= 0:
        raise VegetationIndexError(
            f"backscatter power must be positive, got {linear_power}; zero or "
            "negative linear power is a calibration failure, not a dark target"
        )
    return 10.0 * math.log10(linear_power)


@dataclass(frozen=True)
class IndexSeries:
    """A per-plot index time series, invalid observations included.

    The invalid ones are kept, not dropped — see the module docstring. Every
    statistic below reports the count it was computed from, so a peak NDVI drawn
    from three cloud-free revisits is not silently comparable with one drawn
    from thirty.
    """

    plot_id: str
    index_name: str
    observations: tuple[Observation, ...]

    def __post_init__(self) -> None:
        dates = [o.acquired for o in self.observations]
        if dates != sorted(dates):
            raise VegetationIndexError(
                f"{self.plot_id}: observations are not in ascending date order. "
                "Every trailing-window statistic here assumes they are, and an "
                "out-of-order series produces wrong answers rather than errors."
            )

    @property
    def valid(self) -> tuple[Observation, ...]:
        return tuple(o for o in self.observations if o.valid)

    @property
    def valid_fraction(self) -> float:
        """Share of revisits that survived masking.

        A data-quality figure that belongs on every derived feature. Below
        roughly half, an NDVI-based crop assessment is an assessment of the
        cloud climatology.
        """
        if not self.observations:
            return 0.0
        return len(self.valid) / len(self.observations)

    @property
    def longest_gap_days(self) -> int:
        """Longest stretch between consecutive *valid* observations.

        The statistic that says whether a season was actually observed. A
        45-day gap over the grain-filling window means the plot was not seen
        during the period that determines the yield.
        """
        valid = self.valid
        if len(valid) < 2:
            raise VegetationIndexError(
                f"{self.plot_id}: a gap needs two valid observations, got "
                f"{len(valid)}. An unobserved plot has no gap — it has no series."
            )
        return max(
            (b.acquired - a.acquired).days for a, b in zip(valid, valid[1:])
        )

    def peak(self, start: date | None = None, end: date | None = None) -> Observation:
        """The maximum-value valid observation in the window.

        Peak NDVI is the single most-used input downstream — it drives the
        fallback yield regression, the max-NDVI composite Model A segments on,
        and the LandQualityIndex percentile. Raises on an empty window rather
        than returning a sentinel, because a "peak NDVI of 0" flows into a yield
        regression as a real number.
        """
        window = [
            o
            for o in self.valid
            if (start is None or o.acquired >= start)
            and (end is None or o.acquired <= end)
        ]
        if not window:
            raise VegetationIndexError(
                f"{self.plot_id}: no valid {self.index_name} observation in "
                f"[{start}, {end}]. The plot was not observed in that window; "
                "that is a fact to report, not a zero to compute with."
            )
        return max(window, key=lambda o: o.value)

    def mean(self, start: date | None = None, end: date | None = None) -> float:
        window = [
            o
            for o in self.valid
            if (start is None or o.acquired >= start)
            and (end is None or o.acquired <= end)
        ]
        if not window:
            raise VegetationIndexError(
                f"{self.plot_id}: no valid observation in [{start}, {end}]"
            )
        return sum(o.value for o in window) / len(window)

    def amplitude(self) -> float:
        """Seasonal max minus min over the valid observations.

        Separates a cropped plot from a permanent feature more cleanly than any
        single value: a fallow field and a mature orchard can share a mean NDVI,
        and only one of them swings through the season.
        """
        valid = self.valid
        if len(valid) < 2:
            raise VegetationIndexError(
                f"{self.plot_id}: amplitude needs at least 2 valid observations"
            )
        values = [o.value for o in valid]
        return max(values) - min(values)


def mask_scene(
    observations: Iterable[Observation],
    scene_classes: Sequence[int],
    *,
    unusable: frozenset = UNUSABLE_SCENE_CLASSES,
) -> list[Observation]:
    """Mark observations invalid per the Sentinel-2 scene-classification layer.

    Returns the full list with ``valid`` set, never a filtered one. Filtering
    here is what makes a cloud gap invisible three modules downstream.
    """
    observations = list(observations)
    if len(observations) != len(scene_classes):
        raise VegetationIndexError(
            f"{len(observations)} observations against {len(scene_classes)} "
            "scene classes; they must be paired one to one, and a length "
            "mismatch means the classes belong to different acquisitions"
        )
    out = []
    for observation, scene_class in zip(observations, scene_classes):
        usable = scene_class not in unusable
        out.append(
            Observation(
                plot_id=observation.plot_id,
                acquired=observation.acquired,
                value=observation.value,
                valid=observation.valid and usable,
                sensor=observation.sensor,
            )
        )
    return out


def interpolate(
    series: IndexSeries, target: date, *, max_gap_days: int = 30
) -> tuple[float, bool]:
    """Linearly interpolate the index at ``target``.

    Returns ``(value, is_observed)``. The second element is the point: a caller
    that ignores it has turned a model output into an observation, and the
    crop-verification stream's whole evidential value rests on the distinction.

    ``max_gap_days`` bounds how far apart the bracketing observations may be.
    Beyond it the function raises rather than drawing a straight line across
    the grain-filling window — the period whose NDVI trajectory carries most of
    the yield signal is precisely the one a long interpolation erases.
    """
    valid = series.valid
    if not valid:
        raise VegetationIndexError(f"{series.plot_id}: no valid observations to interpolate")

    exact = [o for o in valid if o.acquired == target]
    if exact:
        return exact[0].value, True

    before = [o for o in valid if o.acquired < target]
    after = [o for o in valid if o.acquired > target]
    if not before or not after:
        raise VegetationIndexError(
            f"{series.plot_id}: {target} is outside the observed range "
            f"[{valid[0].acquired}, {valid[-1].acquired}]. Extrapolating a "
            "vegetation index past the observations invents phenology."
        )

    lower, upper = before[-1], after[0]
    gap = (upper.acquired - lower.acquired).days
    if gap > max_gap_days:
        raise VegetationIndexError(
            f"{series.plot_id}: bracketing observations are {gap} days apart "
            f"(limit {max_gap_days}). A straight line across that long a gap is "
            "not an estimate of the crop, it is an erasure of it."
        )

    span = (upper.acquired - lower.acquired).days
    if span == 0:
        return lower.value, False
    weight = (target - lower.acquired).days / span
    return lower.value + weight * (upper.value - lower.value), False


def temporal_max_composite(
    series: IndexSeries, start: date, end: date
) -> float:
    """Peak-season maximum-value composite — the input Model A segments on.

    Max-value compositing is the standard way to build a cloud-free image from a
    revisit stack: for each pixel, take the highest index value in the window,
    on the reasoning that cloud and shadow both *depress* an optical vegetation
    index, so the maximum is the observation least contaminated by them.

    That reasoning has a limit worth stating: it is not robust to a positively
    biased artefact, and it makes the composite a biased estimator of the mean.
    It is right for delineating field boundaries, which is what it is used for
    here, and wrong for estimating a level.
    """
    if start > end:
        raise VegetationIndexError(f"composite window {start}..{end} is inverted")
    return series.peak(start, end).value


def revisit_completeness(
    series: IndexSeries, start: date, end: date, expected_days: int
) -> float:
    """Observed valid revisits ÷ revisits the orbit should have produced.

    The WS-2.1 completeness monitor at plot granularity. ``expected_days`` is the
    sensor's revisit interval — 5 days for the Sentinel-2 constellation, 6 or 12
    for Sentinel-1 depending on the mission phase — and is passed in rather than
    hard-coded because it changed when Sentinel-1B failed, and a monitor with a
    stale constant would have reported a fleet-wide outage as a data-quality
    collapse.
    """
    if expected_days < 1:
        raise VegetationIndexError(f"revisit interval must be >= 1 day, got {expected_days}")
    if start > end:
        raise VegetationIndexError(f"window {start}..{end} is inverted")

    expected = ((end - start).days // expected_days) + 1
    observed = sum(1 for o in series.valid if start <= o.acquired <= end)
    return observed / expected

"""Ingestion contracts and completeness monitors — WS-2.1 Step 1.

The monitor exists because imagery fails silently: a Sentinel-2 revisit
legitimately produces nothing, so absence is normal and a dead DAG looks exactly
like a cloudy fortnight. The tests that carry the weight are the ones separating
the three completeness questions, and the reanalysis-vintage contract.
"""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from lending_hub.agri.ingest import (
    NOMINAL_REVISIT_DAYS,
    STATIC_SOURCES,
    CompletenessReport,
    IngestError,
    IngestRecord,
    Sensor,
    expected_ingest_days,
    publication_lag_percentile,
    tile_completeness,
)

START = date(2024, 6, 1)


def _record(
    day: int,
    *,
    sensor: Sensor = Sensor.SENTINEL2_L2A,
    expected: int = 10,
    received: int = 10,
    lag: int = 1,
    vintage: str | None = None,
) -> IngestRecord:
    observed = START + timedelta(days=day)
    return IngestRecord(
        sensor=sensor,
        observation_date=observed,
        footprint_id="D1",
        tiles_expected=expected,
        tiles_received=received,
        ingested_at=observed + timedelta(days=lag),
        vintage=vintage,
    )


class TestIngestRecordContract(unittest.TestCase):
    def test_receiving_more_tiles_than_expected_is_a_footprint_bug(self):
        """Not a windfall — it means every completeness figure is wrong."""
        with self.assertRaises(IngestError) as ctx:
            _record(0, expected=10, received=12)
        self.assertIn("footprint model is wrong", str(ctx.exception))

    def test_negative_counts_are_refused(self):
        with self.assertRaises(IngestError):
            _record(0, expected=-1)

    def test_ingesting_before_acquisition_is_a_clock_fault(self):
        with self.assertRaises(IngestError) as ctx:
            _record(0, lag=-2)
        self.assertIn("point-in-time join", str(ctx.exception))

    def test_reanalysis_sources_must_record_a_vintage(self):
        """The revision problem, as a constructor invariant.

        ERA5 and CHIRPS revise published values. Without the vintage a
        point-in-time join picks up a figure that did not exist at the decision
        point, and the backtest built on it outperforms anything the live system
        could have achieved.
        """
        for sensor in (Sensor.ERA5, Sensor.CHIRPS):
            with self.assertRaises(IngestError) as ctx:
                _record(0, sensor=sensor, vintage=None)
            self.assertIn("did not exist at the decision point", str(ctx.exception))

    def test_a_vintage_satisfies_the_reanalysis_contract(self):
        record = _record(0, sensor=Sensor.ERA5, vintage="ERA5-2024-06-v2")
        self.assertEqual(record.vintage, "ERA5-2024-06-v2")

    def test_imagery_sources_do_not_require_a_vintage(self):
        """Sentinel L2A products are reprocessed, not silently revised in place."""
        self.assertIsNone(_record(0, sensor=Sensor.SENTINEL2_L2A).vintage)

    def test_publication_lag(self):
        self.assertEqual(_record(0, lag=3).publication_lag_days, 3)

    def test_is_complete(self):
        self.assertTrue(_record(0, expected=10, received=10).is_complete)
        self.assertFalse(_record(0, expected=10, received=7).is_complete)

    def test_zero_expected_is_not_complete(self):
        """Expecting nothing and receiving nothing is not a healthy ingest."""
        self.assertFalse(_record(0, expected=0, received=0).is_complete)


class TestExpectedDays(unittest.TestCase):
    def test_counts_inclusive_of_both_ends(self):
        self.assertEqual(expected_ingest_days(START, START, 5), 1)
        self.assertEqual(expected_ingest_days(START, START + timedelta(days=25), 5), 6)

    def test_partial_interval_does_not_add_an_acquisition(self):
        self.assertEqual(expected_ingest_days(START, START + timedelta(days=24), 5), 5)

    def test_rejects_an_inverted_window(self):
        with self.assertRaises(IngestError):
            expected_ingest_days(START + timedelta(days=5), START, 5)

    def test_rejects_a_nonsensical_interval(self):
        with self.assertRaises(IngestError):
            expected_ingest_days(START, START + timedelta(days=5), 0)


class TestCompleteness(unittest.TestCase):
    def _full_stack(self, days=range(0, 26, 5), **kwargs):
        return [_record(d, **kwargs) for d in days]

    def test_a_full_stack_is_complete_with_no_gaps(self):
        report = tile_completeness(
            self._full_stack(), Sensor.SENTINEL2_L2A, START, START + timedelta(days=25)
        )
        self.assertEqual(report.tile_completeness, 1.0)
        self.assertFalse(report.has_gap)
        self.assertEqual(report.expected_ingest_days, 6)

    def test_partial_tiles_reduce_completeness(self):
        records = [_record(d, expected=10, received=6) for d in range(0, 26, 5)]
        report = tile_completeness(
            records, Sensor.SENTINEL2_L2A, START, START + timedelta(days=25)
        )
        self.assertAlmostEqual(report.tile_completeness, 0.6, places=9)

    def test_a_missing_acquisition_day_is_named(self):
        records = [_record(d) for d in (0, 5, 15, 20, 25)]
        report = tile_completeness(
            records, Sensor.SENTINEL2_L2A, START, START + timedelta(days=25)
        )
        self.assertTrue(report.has_gap)
        self.assertEqual(report.days_with_no_ingest, (START + timedelta(days=10),))

    def test_a_dead_dag_is_visible_as_consecutive_missing_days(self):
        """The failure the monitor exists for.

        Nothing since day 5. Tile completeness over what arrived is a perfect
        1.0 — every record that exists is complete — and only the gap list says
        the job stopped.
        """
        records = [_record(d) for d in (0, 5)]
        report = tile_completeness(
            records, Sensor.SENTINEL2_L2A, START, START + timedelta(days=25)
        )
        self.assertEqual(report.tile_completeness, 1.0)
        self.assertEqual(len(report.days_with_no_ingest), 4)

    def test_no_records_at_all_is_zero_completeness(self):
        report = tile_completeness(
            [], Sensor.SENTINEL2_L2A, START, START + timedelta(days=25)
        )
        self.assertEqual(report.tile_completeness, 0.0)
        self.assertEqual(len(report.days_with_no_ingest), 6)

    def test_records_from_another_sensor_are_ignored(self):
        records = self._full_stack() + [
            _record(d, sensor=Sensor.SENTINEL1_GRD) for d in range(0, 26, 6)
        ]
        report = tile_completeness(
            records, Sensor.SENTINEL2_L2A, START, START + timedelta(days=25)
        )
        self.assertEqual(report.tile_completeness, 1.0)

    def test_the_revisit_interval_is_overridable(self):
        """Sentinel-1B failed and the constellation revisit doubled.

        A monitor with the interval hard-coded would have reported that as a
        data-quality collapse across every plot simultaneously.
        """
        records = [_record(d, sensor=Sensor.SENTINEL1_GRD) for d in range(0, 25, 12)]
        report = tile_completeness(
            records,
            Sensor.SENTINEL1_GRD,
            START,
            START + timedelta(days=24),
            revisit_days=12,
        )
        self.assertFalse(report.has_gap)

    def test_the_nominal_intervals_are_the_published_ones(self):
        self.assertEqual(NOMINAL_REVISIT_DAYS[Sensor.SENTINEL2_L2A], 5)
        self.assertEqual(NOMINAL_REVISIT_DAYS[Sensor.SENTINEL1_GRD], 6)
        self.assertEqual(NOMINAL_REVISIT_DAYS[Sensor.CHIRPS], 1)

    def test_a_static_source_has_no_completeness_ratio(self):
        """SoilGrids has no revisit; a ratio for it is a category error."""
        for sensor in STATIC_SOURCES:
            with self.assertRaises(IngestError) as ctx:
                tile_completeness([], sensor, START, START + timedelta(days=25))
            self.assertIn("no denominator", str(ctx.exception))


class TestThreeQuestionsAreSeparate(unittest.TestCase):
    """The design claim, tested: monsoon and an outage must not look alike."""

    def test_monsoon_shows_low_usable_fraction_with_clean_job_health(self):
        records = [_record(d) for d in range(0, 26, 5)]
        usable = {START + timedelta(days=d): 1 for d in range(0, 26, 5)}
        report = tile_completeness(
            records,
            Sensor.SENTINEL2_L2A,
            START,
            START + timedelta(days=25),
            usable_tiles=usable,
        )
        self.assertEqual(report.tile_completeness, 1.0)
        self.assertFalse(report.has_gap)
        self.assertAlmostEqual(report.usable_fraction, 6 / 60, places=9)

    def test_an_outage_shows_a_gap_with_a_healthy_usable_fraction(self):
        records = [_record(d) for d in (0, 5)]
        usable = {START + timedelta(days=d): 9 for d in (0, 5)}
        report = tile_completeness(
            records,
            Sensor.SENTINEL2_L2A,
            START,
            START + timedelta(days=25),
            usable_tiles=usable,
        )
        self.assertTrue(report.has_gap)
        self.assertAlmostEqual(report.usable_fraction, 18 / 20, places=9)

    def test_plot_coverage_is_none_when_not_asked(self):
        """"We did not ask" is not "no plot was covered"."""
        report = tile_completeness(
            [_record(0)], Sensor.SENTINEL2_L2A, START, START
        )
        self.assertIsNone(report.plot_coverage)
        self.assertIsNone(report.usable_fraction)

    def test_plot_coverage_is_computed_when_asked(self):
        report = tile_completeness(
            [_record(0)],
            Sensor.SENTINEL2_L2A,
            START,
            START,
            plots_total=200,
            plots_covered=150,
        )
        self.assertAlmostEqual(report.plot_coverage, 0.75, places=9)

    def test_an_empty_registry_is_reported_not_divided_by(self):
        with self.assertRaises(IngestError) as ctx:
            tile_completeness(
                [_record(0)],
                Sensor.SENTINEL2_L2A,
                START,
                START,
                plots_total=0,
                plots_covered=0,
            )
        self.assertIn("empty registry", str(ctx.exception))

    def test_covering_more_plots_than_exist_is_refused(self):
        with self.assertRaises(IngestError):
            tile_completeness(
                [_record(0)],
                Sensor.SENTINEL2_L2A,
                START,
                START,
                plots_total=10,
                plots_covered=11,
            )

    def test_total_without_covered_is_refused(self):
        with self.assertRaises(IngestError):
            tile_completeness(
                [_record(0)], Sensor.SENTINEL2_L2A, START, START, plots_total=10
            )


class TestPublicationLag(unittest.TestCase):
    def test_percentile_is_nearest_rank(self):
        records = [_record(d, lag=lag) for d, lag in zip(range(0, 50, 5), [1, 1, 2, 2, 3, 4, 4, 9, 9, 12])]
        self.assertEqual(publication_lag_percentile(records, 0.5), 3)
        self.assertEqual(publication_lag_percentile(records, 1.0), 12)

    def test_a_single_record(self):
        self.assertEqual(publication_lag_percentile([_record(0, lag=4)], 0.95), 4)

    def test_an_empty_window_is_not_a_fast_one(self):
        with self.assertRaises(IngestError) as ctx:
            publication_lag_percentile([], 0.95)
        self.assertIn("not a fast one", str(ctx.exception))

    def test_rejects_a_percentile_outside_the_range(self):
        for bad in (0.0, 1.5, -0.2):
            with self.assertRaises(IngestError):
                publication_lag_percentile([_record(0)], bad)


if __name__ == "__main__":
    unittest.main()

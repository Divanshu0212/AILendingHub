"""Tests for event-time velocity counters (WS-1.2 Step 2).

The load-bearing tests are about clocks. A velocity counter built on the wrong
one still produces plausible counts, and the error only surfaces weeks later as
an unexplained metric drop in shadow.

Workstream: WS-1.2 Step 2
"""

import unittest
from datetime import UTC, datetime, timedelta

from lending_hub.fraud.velocity import (
    DEFAULT_ALLOWED_LATENESS,
    WINDOWS,
    ApplicationEvent,
    Dimension,
    VelocityCounter,
    VelocityError,
    VelocityFeatures,
    skew_check,
)

BASE = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def event(index, key="D1", *, minutes=0, lag_seconds=30, dimension=Dimension.DEVICE):
    return ApplicationEvent(
        application_id=f"A{index}",
        key=key,
        dimension=dimension,
        event_time=BASE + timedelta(minutes=minutes),
        ingest_time=BASE + timedelta(minutes=minutes, seconds=lag_seconds),
    )


class TestEventShape(unittest.TestCase):
    def test_the_phase_1_windows_are_the_declared_ones(self):
        self.assertEqual(sorted(WINDOWS), ["1h", "24h", "7d"])
        self.assertEqual(WINDOWS["7d"], timedelta(days=7))

    def test_ingestion_before_the_event_is_refused_as_clock_skew(self):
        with self.assertRaises(VelocityError) as caught:
            ApplicationEvent("A", "D1", Dimension.DEVICE, BASE, BASE - timedelta(minutes=1))
        self.assertIn("clock-skew", str(caught.exception))

    def test_an_event_of_the_wrong_dimension_is_refused(self):
        counter = VelocityCounter(Dimension.PHONE)
        with self.assertRaises(VelocityError):
            counter.ingest(event(1))


class TestWindowedCounting(unittest.TestCase):
    def setUp(self):
        self.counter = VelocityCounter(Dimension.DEVICE)
        self.counter.ingest_all(event(i, minutes=5 * i) for i in range(6))

    def test_it_counts_events_inside_the_window(self):
        decision = BASE + timedelta(minutes=30)
        self.assertEqual(
            self.counter.count(
                "D1", as_of_event_time=decision,
                known_at=decision + timedelta(minutes=1), window=WINDOWS["1h"],
            ),
            6,
        )

    def test_events_outside_the_window_are_excluded(self):
        # Events at minutes 0, 5, 10, 15, 20, 25; a 10-minute window ending at
        # minute 30 covers [20, 30], so only two of them.
        decision = BASE + timedelta(minutes=30)
        self.assertEqual(
            self.counter.count(
                "D1", as_of_event_time=decision,
                known_at=decision + timedelta(minutes=1),
                window=timedelta(minutes=10),
            ),
            2,
        )

    def test_the_window_lower_edge_is_inclusive(self):
        decision = BASE + timedelta(minutes=25)
        self.assertEqual(
            self.counter.count(
                "D1", as_of_event_time=decision,
                known_at=decision + timedelta(minutes=1),
                window=timedelta(minutes=5),
            ),
            2,
        )

    def test_an_unknown_key_counts_zero(self):
        decision = BASE + timedelta(minutes=30)
        self.assertEqual(
            self.counter.count("UNSEEN", as_of_event_time=decision,
                               known_at=decision, window=WINDOWS["1h"]),
            0,
        )

    def test_a_non_positive_window_is_refused(self):
        with self.assertRaises(VelocityError):
            self.counter.count("D1", as_of_event_time=BASE, known_at=BASE,
                               window=timedelta(0))

    def test_knowing_before_observing_is_refused(self):
        with self.assertRaises(VelocityError):
            self.counter.count(
                "D1", as_of_event_time=BASE + timedelta(hours=1), known_at=BASE,
                window=WINDOWS["1h"],
            )


class TestTwoTimestampDiscipline(unittest.TestCase):
    """The half of the design that stops training/serving skew being manufactured."""

    def test_count_requires_an_ingestion_cutoff(self):
        import inspect
        parameter = inspect.signature(VelocityCounter.count).parameters["known_at"]
        self.assertIs(parameter.default, inspect.Parameter.empty)

    def test_an_event_that_had_not_arrived_yet_is_not_counted(self):
        counter = VelocityCounter(Dimension.DEVICE)
        counter.ingest(event(1, minutes=1, lag_seconds=30))
        counter.ingest(event(2, minutes=2, lag_seconds=7200))  # arrived two hours late
        decision = BASE + timedelta(minutes=10)
        self.assertEqual(
            counter.count("D1", as_of_event_time=decision, known_at=decision,
                          window=WINDOWS["1h"]),
            1,
        )

    def test_skew_check_reports_what_a_backtest_would_have_used(self):
        counter = VelocityCounter(Dimension.DEVICE)
        counter.ingest(event(1, minutes=1, lag_seconds=30))
        counter.ingest(event(2, minutes=2, lag_seconds=7200))
        decision = BASE + timedelta(minutes=10)
        report = skew_check(
            counter, "D1", as_of_event_time=decision, known_at=decision,
            window=WINDOWS["1h"],
        )
        self.assertEqual(report["online_count"], 1)
        self.assertEqual(report["offline_count"], 2)
        self.assertEqual(report["skew"], 1)

    def test_no_skew_when_everything_arrived_promptly(self):
        counter = VelocityCounter(Dimension.DEVICE)
        counter.ingest_all(event(i, minutes=i) for i in range(5))
        decision = BASE + timedelta(minutes=10)
        report = skew_check(
            counter, "D1", as_of_event_time=decision, known_at=decision,
            window=WINDOWS["1h"],
        )
        self.assertEqual(report["skew"], 0)


class TestWatermarks(unittest.TestCase):
    def test_the_watermark_trails_the_newest_event_by_the_allowed_lateness(self):
        counter = VelocityCounter(Dimension.DEVICE, allowed_lateness=timedelta(minutes=5))
        counter.ingest(event(1, minutes=60))
        self.assertEqual(counter.watermark, BASE + timedelta(minutes=55))

    def test_the_watermark_never_moves_backwards(self):
        # A late event must not reopen a window already declared complete.
        counter = VelocityCounter(Dimension.DEVICE)
        counter.ingest(event(1, minutes=60))
        high = counter.watermark
        counter.ingest(event(2, minutes=1))
        self.assertEqual(counter.watermark, high)

    def test_a_late_event_is_counted_and_reported_not_dropped(self):
        counter = VelocityCounter(Dimension.DEVICE)
        counter.ingest(event(1, minutes=60))
        counter.ingest(event(2, minutes=1))
        self.assertEqual(counter.late_events, 1)
        self.assertEqual(counter.total_events, 2)
        self.assertAlmostEqual(counter.to_dict()["late_fraction"], 0.5)

    def test_an_on_time_event_reports_true(self):
        counter = VelocityCounter(Dimension.DEVICE)
        self.assertTrue(counter.ingest(event(1, minutes=0)))

    def test_the_default_allowed_lateness_is_visible(self):
        self.assertEqual(VelocityCounter(Dimension.PHONE).allowed_lateness,
                         DEFAULT_ALLOWED_LATENESS)


class TestFeatureAssembly(unittest.TestCase):
    def test_features_carry_one_count_per_window(self):
        counter = VelocityCounter(Dimension.PHONE)
        counter.ingest_all(
            event(i, key="9000000001", minutes=i, dimension=Dimension.PHONE)
            for i in range(4)
        )
        decision = BASE + timedelta(minutes=10)
        features = counter.features(
            "9000000001", as_of_event_time=decision, known_at=decision
        )
        self.assertEqual(
            sorted(features),
            ["velocity_phone_1h", "velocity_phone_24h", "velocity_phone_7d"],
        )
        self.assertEqual(features["velocity_phone_1h"], 4)

    def test_a_missing_dimension_is_absent_not_zero(self):
        # "No device fingerprint captured" and "one application from this device"
        # are different facts, and a zero merges the first into the second — which
        # reads as the safest possible applicant.
        features = VelocityFeatures.build()
        decision = BASE + timedelta(minutes=10)
        row = features.for_application(
            {Dimension.DEVICE: "", Dimension.PHONE: "9000000001"},
            as_of_event_time=decision, known_at=decision,
        )
        self.assertNotIn("velocity_device_1h", row)
        self.assertIn("velocity_phone_1h", row)

    def test_all_three_dimensions_are_counted_together(self):
        features = VelocityFeatures.build()
        features.ingest_all([
            event(1, key="D1", minutes=1, dimension=Dimension.DEVICE),
            event(2, key="P1", minutes=2, dimension=Dimension.PHONE),
            event(3, key="G1", minutes=3, dimension=Dimension.ADDRESS),
        ])
        decision = BASE + timedelta(minutes=10)
        row = features.for_application(
            {Dimension.DEVICE: "D1", Dimension.PHONE: "P1", Dimension.ADDRESS: "G1"},
            as_of_event_time=decision, known_at=decision,
        )
        self.assertEqual(len(row), 9)
        self.assertEqual(row["velocity_address_24h"], 1)

    def test_the_counter_serialises_its_lateness_diagnostics(self):
        counter = VelocityCounter(Dimension.DEVICE)
        counter.ingest(event(1, minutes=0))
        payload = counter.to_dict()
        for key in ("dimension", "total_events", "late_events", "watermark", "windows"):
            self.assertIn(key, payload)


if __name__ == "__main__":
    unittest.main()

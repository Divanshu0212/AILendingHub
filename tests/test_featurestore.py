"""Point-in-time join tests.

These are the tests that decide whether the platform's central anti-leakage claim
is true. Each one encodes a real way a training set gets contaminated.

Workstream: WS-0.2.1
"""

import unittest
from datetime import UTC, datetime, timedelta

from lending_hub.featurestore import (
    EntityRow,
    FeatureSource,
    FeatureSpec,
    FeatureValue,
    LeakageError,
    LocalFeatureStore,
    compare,
    get_historical_features,
)


def ts(day, hour=0):
    return datetime(2026, 3, day, hour, tzinfo=UTC)


def spec(name="bureau_score", ttl=None):
    return FeatureSpec(name=name, ttl=ttl, owner="Credit DS", source_id="bureau")


def source_with(*values, name="bureau_score", ttl=None, entity="CU-1"):
    src = FeatureSource(spec(name, ttl))
    src.extend(entity, values)
    return src


class TestKnowability(unittest.TestCase):
    """event_timestamp alone is not enough — the value also has to have landed."""

    def test_value_that_had_not_landed_yet_is_not_returned(self):
        # Dated 3 March, arrived 20 March. On 10 March production could not have
        # seen it, so training must not either. This is the leakage that shows up
        # as offline lift and vanishes in shadow.
        src = source_with(FeatureValue(ts(3), ts(20), 700))
        self.assertIsNone(src.as_of("CU-1", ts(10)))

    def test_same_value_is_returned_once_it_has_landed(self):
        src = source_with(FeatureValue(ts(3), ts(20), 700))
        self.assertEqual(src.as_of("CU-1", ts(21)).value, 700)

    def test_future_dated_value_is_never_returned(self):
        src = source_with(FeatureValue(ts(25), ts(25), 700))
        self.assertIsNone(src.as_of("CU-1", ts(10)))

    def test_latest_knowable_value_wins(self):
        src = source_with(
            FeatureValue(ts(1), ts(1), 600),
            FeatureValue(ts(5), ts(5), 650),
            FeatureValue(ts(9), ts(9), 700),
        )
        self.assertEqual(src.as_of("CU-1", ts(6)).value, 650)

    def test_late_correction_to_an_earlier_fact_is_used_once_known(self):
        # Two rows for the same event date; the later-created one is the
        # correction and should win after it lands, but not before.
        src = source_with(
            FeatureValue(ts(5), ts(5), 650),
            FeatureValue(ts(5), ts(12), 655),
        )
        self.assertEqual(src.as_of("CU-1", ts(8)).value, 650)
        self.assertEqual(src.as_of("CU-1", ts(15)).value, 655)

    def test_created_before_event_is_rejected(self):
        # The platform cannot have learned a fact before it was true; this is a
        # source clock problem and must not be silently normalised away.
        with self.assertRaises(ValueError):
            FeatureValue(ts(10), ts(5), 700)


class TestTTL(unittest.TestCase):
    def test_value_past_its_ttl_is_not_carried_forward(self):
        # A four-year-old bureau score is not "the current bureau score". Carrying
        # it forward backtests beautifully and degrades on day one.
        src = source_with(FeatureValue(ts(1), ts(1), 700), ttl=timedelta(days=5))
        self.assertIsNone(src.as_of("CU-1", ts(20)))

    def test_value_inside_its_ttl_is_returned(self):
        src = source_with(FeatureValue(ts(1), ts(1), 700), ttl=timedelta(days=5))
        self.assertEqual(src.as_of("CU-1", ts(4)).value, 700)

    def test_ttl_boundary_is_inclusive(self):
        src = source_with(FeatureValue(ts(1), ts(1), 700), ttl=timedelta(days=5))
        self.assertEqual(src.as_of("CU-1", ts(6)).value, 700)

    def test_ttl_must_be_positive(self):
        with self.assertRaises(ValueError):
            FeatureSpec("x", ttl=timedelta(0), owner="o", source_id="s")


class TestHistoricalJoin(unittest.TestCase):
    def test_joins_each_row_at_its_own_observation_point(self):
        src = source_with(
            FeatureValue(ts(1), ts(1), 600),
            FeatureValue(ts(10), ts(10), 700),
        )
        result = get_historical_features(
            [EntityRow("CU-1", ts(5), label=0), EntityRow("CU-1", ts(15), label=1)],
            [src],
        )
        self.assertEqual([r["bureau_score"] for r in result.rows], [600, 700])
        self.assertEqual([r["label"] for r in result.rows], [0, 1])

    def test_strict_mode_raises_on_a_leaked_value(self):
        class Leaky(FeatureSource):
            def as_of(self, entity_key, observation_point):
                return FeatureValue(ts(28), ts(28), 999)

        with self.assertRaises(LeakageError):
            get_historical_features([EntityRow("CU-1", ts(5))], [Leaky(spec())])

    def test_missing_and_expired_are_counted_separately(self):
        # "Never had a value" and "had one, but it went stale" need different
        # fixes — a broken join versus a TTL that does not match refresh cadence.
        fresh = source_with(FeatureValue(ts(1), ts(1), 700), name="stale", ttl=timedelta(days=2))
        absent = FeatureSource(spec("absent"))
        result = get_historical_features([EntityRow("CU-1", ts(20))], [fresh, absent])
        self.assertEqual(result.expired.get("stale"), 1)
        self.assertEqual(result.missing.get("absent"), 1)

    def test_unknown_entity_yields_none_not_an_error(self):
        src = source_with(FeatureValue(ts(1), ts(1), 700))
        result = get_historical_features([EntityRow("CU-UNSEEN", ts(5))], [src])
        self.assertIsNone(result.rows[0]["bureau_score"])
        self.assertEqual(result.missing["bureau_score"], 1)

    def test_coverage_reports_none_for_an_empty_dataset(self):
        result = get_historical_features([], [source_with(FeatureValue(ts(1), ts(1), 1))])
        self.assertIsNone(result.coverage("bureau_score"))

    def test_coverage_fraction(self):
        src = source_with(FeatureValue(ts(1), ts(1), 700))
        result = get_historical_features(
            [EntityRow("CU-1", ts(5)), EntityRow("CU-2", ts(5))], [src]
        )
        self.assertEqual(result.coverage("bureau_score"), 0.5)


class TestStoreContract(unittest.TestCase):
    def test_unregistered_feature_is_rejected(self):
        store = LocalFeatureStore([source_with(FeatureValue(ts(1), ts(1), 700))])
        with self.assertRaises(KeyError):
            store.get_historical_features([EntityRow("CU-1", ts(5))], ["not_a_feature"])

    def test_store_join_matches_the_reference_join(self):
        src = source_with(FeatureValue(ts(1), ts(1), 700))
        store = LocalFeatureStore([src])
        rows = EntityRow("CU-1", ts(5)),
        self.assertEqual(
            store.get_historical_features(rows, ["bureau_score"]).rows,
            get_historical_features(rows, [src]).rows,
        )


class TestSkew(unittest.TestCase):
    def test_matching_paths_report_no_skew(self):
        src = source_with(FeatureValue(ts(1), ts(1), 700))
        store = LocalFeatureStore([src])
        rows = [EntityRow("CU-1", ts(5))]
        offline = store.get_historical_features(rows, ["bureau_score"]).rows
        report = compare(offline, store.as_of_lookup, ["bureau_score"])
        self.assertEqual(report.skew_rate, 0.0)

    def test_disagreement_is_reported(self):
        src = source_with(FeatureValue(ts(1), ts(1), 700))
        store = LocalFeatureStore([src])
        offline = [{"entity_key": "CU-1", "observation_point": ts(5), "bureau_score": 999}]
        report = compare(offline, store.as_of_lookup, ["bureau_score"])
        self.assertEqual(report.skew_rate, 1.0)
        self.assertEqual(len(report.findings), 1)

    def test_none_on_one_side_only_is_still_skew(self):
        # The most common real case, and the easiest to dismiss as "just missing".
        store = LocalFeatureStore([FeatureSource(spec())])
        offline = [{"entity_key": "CU-1", "observation_point": ts(5), "bureau_score": 700}]
        report = compare(offline, store.as_of_lookup, ["bureau_score"])
        self.assertEqual(report.missing_online["bureau_score"], 1)
        self.assertEqual(report.skew_rate, 1.0)

    def test_empty_comparison_reports_none_not_zero(self):
        report = compare([], lambda *a: None, ["bureau_score"])
        self.assertIsNone(report.skew_rate)


if __name__ == "__main__":
    unittest.main()

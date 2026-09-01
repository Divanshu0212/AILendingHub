"""Model B's baseline and its ship/no-ship rule — WS-2.2 (SRS §3.4.2).

Presto is not ported (ADR-0013). What is tested is the half of Phase 2 §4's
instruction that decides whether it would ever deploy — the RF baseline, macro-F1
and the +5-point margin — plus the two output rules the phase file attaches to
the classifier: fallow is a class, and below 0.6 the answer is "unsure".
"""

from __future__ import annotations

import math
import random
import unittest
from datetime import date, timedelta

from lending_hub.agri.crop import (
    COMPLEXITY_EARNED_MARGIN_POINTS,
    FALLOW,
    UNSURE_THRESHOLD,
    ZONE_CROP_LIST,
    ClassSet,
    ClassificationReport,
    CropError,
    Prediction,
    RandomForest,
    classification_report,
    complexity_earned,
    fit_random_forest,
    fit_temperature,
    phenology_features,
    _temperature_apply,
)
from lending_hub.agri.indices import IndexSeries, VegetationIndexError
from lending_hub.agri.ports import Observation
from lending_hub.definitions.provenance import Ungrounded

FEATURES = ["ndvi_peak", "days_to_peak", "green_up_rate", "ndvi_amplitude"]

#: Phenological signatures for a synthetic four-crop zone. Separable but
#: overlapping — a perfectly separable problem would make every calibration and
#: abstention test vacuous, because nothing would ever be near a boundary.
SIGNATURES = {
    "rice": (0.85, 110, 0.010),
    "cotton": (0.70, 135, 0.006),
    "soybean": (0.78, 95, 0.012),
    FALLOW: (0.22, 60, 0.001),
}


def _class_set(*crops: str) -> ClassSet:
    return ClassSet.from_policy(
        "zone-1", crops or ("rice", "cotton", "soybean"), decision_reference="AC-2026-01"
    )


def _sample(n: int, seed: int, *, noise: float = 1.0):
    rng = random.Random(seed)
    rows, labels = [], []
    for _ in range(n):
        crop = rng.choice(list(SIGNATURES))
        peak, timing, rate = SIGNATURES[crop]
        rows.append(
            {
                "ndvi_peak": peak + rng.gauss(0, 0.06 * noise),
                "days_to_peak": timing + rng.gauss(0, 12 * noise),
                "green_up_rate": rate + rng.gauss(0, 0.002 * noise),
                "ndvi_amplitude": peak - 0.15 + rng.gauss(0, 0.05 * noise),
            }
        )
        labels.append(crop)
    return rows, labels


class TestClassSet(unittest.TestCase):
    def test_fallow_is_added_when_a_committee_list_omits_it(self):
        """`[SPEC]`, not policy — a list without it is incomplete, not wrong."""
        class_set = ClassSet.from_policy(
            "zone-1", ["rice", "cotton"], decision_reference="AC-1"
        )
        self.assertIn(FALLOW, class_set.crops)
        self.assertEqual(len(class_set), 3)

    def test_a_class_set_without_fallow_cannot_be_constructed_directly(self):
        with self.assertRaises(CropError) as ctx:
            ClassSet(zone="z", crops=("rice", "cotton"), decision_reference="AC-1")
        self.assertIn("unsown plot from an unfamiliar one", str(ctx.exception))

    def test_a_class_set_needs_its_ratification_reference(self):
        with self.assertRaises(CropError) as ctx:
            ClassSet(zone="z", crops=("rice", FALLOW), decision_reference="")
        self.assertIn("LH-404", str(ctx.exception))

    def test_an_empty_class_set_is_refused(self):
        with self.assertRaises(CropError):
            ClassSet(zone="z", crops=(), decision_reference="AC-1")

    def test_duplicate_classes_are_refused(self):
        with self.assertRaises(CropError):
            ClassSet(zone="z", crops=("rice", "rice", FALLOW), decision_reference="AC-1")

    def test_a_crop_outside_the_label_space_cannot_be_indexed(self):
        with self.assertRaises(CropError) as ctx:
            _class_set().index("maize")
        self.assertIn("widening the set means retraining", str(ctx.exception))

    def test_the_ratified_list_itself_is_ungrounded(self):
        """LH-404: the label space is a policy choice, not an engineering one."""
        with self.assertRaises(Ungrounded):
            ZONE_CROP_LIST.value
        self.assertEqual(ZONE_CROP_LIST.ticket, "LH-404")


class TestPhenologyFeatures(unittest.TestCase):
    def _series(self, values, start=date(2024, 6, 1), step=10, valid=True):
        return IndexSeries(
            plot_id="P1",
            index_name="ndvi",
            observations=tuple(
                Observation("P1", start + timedelta(days=i * step), v, valid)
                for i, v in enumerate(values)
            ),
        )

    def test_extracts_the_shape_of_a_season(self):
        series = self._series([0.20, 0.45, 0.78, 0.85, 0.60, 0.25])
        features = phenology_features(series, date(2024, 6, 1), date(2024, 8, 30))
        self.assertAlmostEqual(features["ndvi_peak"], 0.85, places=9)
        self.assertAlmostEqual(features["days_to_peak"], 30.0, places=9)
        self.assertAlmostEqual(features["ndvi_amplitude"], 0.65, places=9)
        self.assertGreater(features["green_up_rate"], 0)
        self.assertLess(features["senescence_rate"], 0)

    def test_the_integral_separates_a_long_season_from_a_short_one(self):
        """Accumulated biomass, the most discriminative single statistic.

        Same peak, same number of revisits, same amplitude — the two crops
        differ only in how long they hold green. Peak NDVI cannot tell them
        apart and the integral can, which is why a summary carrying both is a
        hard baseline to beat.
        """
        brief = self._series([0.2, 0.85, 0.85, 0.2], step=15)
        sustained = self._series([0.2, 0.85, 0.85, 0.2], step=40)

        brief_features = phenology_features(brief, date(2024, 6, 1), date(2025, 1, 30))
        sustained_features = phenology_features(sustained, date(2024, 6, 1), date(2025, 1, 30))

        self.assertAlmostEqual(
            brief_features["ndvi_peak"], sustained_features["ndvi_peak"], places=9
        )
        self.assertGreater(
            sustained_features["ndvi_integral"], brief_features["ndvi_integral"]
        )

    def test_too_few_observations_classifies_the_cloud(self):
        series = self._series([0.3, 0.8])
        with self.assertRaises(CropError) as ctx:
            phenology_features(series, date(2024, 6, 1), date(2024, 8, 30))
        self.assertIn("classifies the cloud", str(ctx.exception))

    def test_masked_observations_do_not_count_towards_the_minimum(self):
        series = self._series([0.3, 0.8, 0.7, 0.2, 0.1], valid=False)
        with self.assertRaises(CropError):
            phenology_features(series, date(2024, 6, 1), date(2024, 8, 30))

    def test_observations_outside_the_season_are_excluded(self):
        series = self._series([0.2, 0.5, 0.9, 0.6, 0.2, 0.1], step=30)
        with self.assertRaises(CropError):
            phenology_features(series, date(2024, 6, 1), date(2024, 7, 15))


class TestRandomForest(unittest.TestCase):
    def test_learns_a_separable_four_crop_zone(self):
        rows, labels = _sample(400, seed=1)
        forest = fit_random_forest(rows, labels, _class_set(), FEATURES, n_trees=40, seed=3)
        test_rows, test_labels = _sample(300, seed=99)
        report = classification_report(
            [forest.predict(r) for r in test_rows], test_labels, _class_set()
        )
        self.assertGreater(report.macro_f1_points, 80.0)

    def test_probabilities_sum_to_one(self):
        rows, labels = _sample(200, seed=2)
        forest = fit_random_forest(rows, labels, _class_set(), FEATURES, n_trees=20, seed=1)
        for row in rows[:20]:
            self.assertAlmostEqual(sum(forest.probabilities(row)), 1.0, places=9)

    def test_a_missing_feature_raises_rather_than_defaulting(self):
        rows, labels = _sample(150, seed=4)
        forest = fit_random_forest(rows, labels, _class_set(), FEATURES, n_trees=10, seed=1)
        with self.assertRaises(CropError) as ctx:
            forest.probabilities({"ndvi_peak": 0.8})
        self.assertIn("missing features", str(ctx.exception))

    def test_fitting_on_one_class_is_refused(self):
        """It would predict that class everywhere and report perfect recall."""
        rows = [{f: 0.5 for f in FEATURES} for _ in range(50)]
        with self.assertRaises(CropError) as ctx:
            fit_random_forest(rows, ["rice"] * 50, _class_set(), FEATURES)
        self.assertIn("predicts that class everywhere", str(ctx.exception))

    def test_an_empty_sample_is_refused(self):
        with self.assertRaises(CropError):
            fit_random_forest([], [], _class_set(), FEATURES)

    def test_row_and_label_length_mismatch_is_refused(self):
        rows, labels = _sample(20, seed=5)
        with self.assertRaises(CropError):
            fit_random_forest(rows, labels[:10], _class_set(), FEATURES)

    def test_fitting_is_reproducible_from_the_seed(self):
        rows, labels = _sample(200, seed=6)
        a = fit_random_forest(rows, labels, _class_set(), FEATURES, n_trees=15, seed=42)
        b = fit_random_forest(rows, labels, _class_set(), FEATURES, n_trees=15, seed=42)
        self.assertEqual(a.probabilities(rows[0]), b.probabilities(rows[0]))


class TestAbstention(unittest.TestCase):
    def test_the_threshold_is_the_phase_file_number(self):
        self.assertEqual(UNSURE_THRESHOLD, 0.6)

    def test_below_the_threshold_the_label_is_unsure(self):
        prediction = Prediction(
            crop="rice", confidence=0.55, distribution=(0.55, 0.25, 0.1, 0.1),
            class_set=_class_set(),
        )
        self.assertTrue(prediction.is_unsure)
        self.assertEqual(prediction.label, "unsure")

    def test_at_the_threshold_the_prediction_stands(self):
        prediction = Prediction(
            crop="rice", confidence=0.6, distribution=(0.6, 0.2, 0.1, 0.1),
            class_set=_class_set(),
        )
        self.assertFalse(prediction.is_unsure)
        self.assertEqual(prediction.label, "rice")

    def test_fallow_is_reported_as_fallow_not_as_unsure(self):
        """Opposite claims: 'not sown' against 'could not tell'.

        The non-sowing flag in WS-2.4(c) is built entirely on keeping them
        apart — one fires an early-warning trigger, the other sends someone to
        look.
        """
        prediction = Prediction(
            crop=FALLOW, confidence=0.91, distribution=(0.03, 0.03, 0.03, 0.91),
            class_set=_class_set(),
        )
        self.assertFalse(prediction.is_unsure)
        self.assertEqual(prediction.label, FALLOW)


class TestTemperatureScaling(unittest.TestCase):
    def test_temperature_one_is_the_identity(self):
        original = (0.6, 0.25, 0.1, 0.05)
        scaled = _temperature_apply(original, 1.0)
        for a, b in zip(original, scaled):
            self.assertAlmostEqual(a, b, places=9)

    def test_a_high_temperature_flattens_the_distribution(self):
        flattened = _temperature_apply((0.9, 0.05, 0.03, 0.02), 5.0)
        self.assertLess(max(flattened), 0.9)

    def test_a_low_temperature_sharpens_it(self):
        sharpened = _temperature_apply((0.5, 0.3, 0.15, 0.05), 0.4)
        self.assertGreater(max(sharpened), 0.5)

    def test_scaling_preserves_the_ranking(self):
        original = (0.4, 0.3, 0.2, 0.1)
        for temperature in (0.3, 0.8, 2.0, 6.0):
            scaled = _temperature_apply(original, temperature)
            self.assertEqual(
                sorted(range(4), key=lambda i: -scaled[i]), [0, 1, 2, 3]
            )

    def test_scaling_keeps_the_distribution_normalised(self):
        for temperature in (0.2, 1.0, 3.0):
            self.assertAlmostEqual(
                sum(_temperature_apply((0.5, 0.3, 0.15, 0.05), temperature)), 1.0, places=9
            )

    def test_fitting_improves_held_out_log_loss(self):
        """The property calibration must have, whatever temperature it picks."""
        train_rows, train_labels = _sample(400, seed=11)
        validation_rows, validation_labels = _sample(250, seed=12)
        class_set = _class_set()

        forest = fit_random_forest(
            train_rows, train_labels, class_set, FEATURES, n_trees=40, seed=5
        )
        calibrated = fit_temperature(forest, validation_rows, validation_labels)

        def nll(model):
            total = 0.0
            for row, label in zip(validation_rows, validation_labels):
                p = model.probabilities(row)[class_set.index(label)]
                total -= math.log(max(p, 1e-12))
            return total / len(validation_rows)

        self.assertLessEqual(nll(calibrated), nll(forest) + 1e-9)

    def test_calibration_carries_the_forest_through_unchanged(self):
        rows, labels = _sample(200, seed=13)
        forest = fit_random_forest(rows, labels, _class_set(), FEATURES, n_trees=20, seed=7)
        calibrated = fit_temperature(forest, *_sample(150, seed=14))
        self.assertIs(calibrated.trees, forest.trees)
        self.assertEqual(calibrated.features, forest.features)

    def test_calibrating_on_an_empty_set_is_refused(self):
        rows, labels = _sample(100, seed=15)
        forest = fit_random_forest(rows, labels, _class_set(), FEATURES, n_trees=10, seed=1)
        with self.assertRaises(CropError):
            fit_temperature(forest, [], [])


class TestClassificationReport(unittest.TestCase):
    def _perfect(self, class_set):
        crops = [c for c in class_set.crops]
        predictions = [
            Prediction(crop=c, confidence=0.99, distribution=(1.0,), class_set=class_set)
            for c in crops
        ]
        return predictions, crops

    def test_a_perfect_classifier_scores_one(self):
        class_set = _class_set()
        predictions, truth = self._perfect(class_set)
        report = classification_report(predictions, truth, class_set)
        self.assertAlmostEqual(report.macro_f1, 1.0, places=9)
        self.assertAlmostEqual(report.accuracy, 1.0, places=9)

    def test_macro_f1_is_reported_in_points(self):
        class_set = _class_set()
        predictions, truth = self._perfect(class_set)
        self.assertAlmostEqual(
            classification_report(predictions, truth, class_set).macro_f1_points,
            100.0,
            places=9,
        )

    def test_macro_penalises_ignoring_a_minority_crop_where_micro_would_not(self):
        """Why the phase file says macro, on an imbalanced agri class set.

        Ninety plots of rice and ten of cotton. A model that never predicts
        cotton gets 90% accuracy and a macro-F1 near half of it.
        """
        class_set = _class_set("rice", "cotton")
        truth = ["rice"] * 90 + ["cotton"] * 10
        predictions = [
            Prediction(crop="rice", confidence=0.95, distribution=(1.0,), class_set=class_set)
            for _ in truth
        ]
        report = classification_report(predictions, truth, class_set)
        self.assertAlmostEqual(report.accuracy, 0.90, places=9)
        self.assertLess(report.macro_f1, 0.50)

    def test_abstentions_count_as_errors(self):
        """A metric that excluded them would improve as the model gave up.

        Abstention has an operational cost — somebody must go and look (LH-409)
        — so it cannot be free in the score.
        """
        class_set = _class_set()
        truth = ["rice"] * 20
        confident = [
            Prediction(crop="rice", confidence=0.9, distribution=(1.0,), class_set=class_set)
            for _ in range(20)
        ]
        half_unsure = confident[:10] + [
            Prediction(crop="rice", confidence=0.4, distribution=(1.0,), class_set=class_set)
            for _ in range(10)
        ]
        self.assertAlmostEqual(
            classification_report(confident, truth, class_set).macro_f1, 1.0, places=9
        )
        self.assertLess(
            classification_report(half_unsure, truth, class_set).macro_f1, 1.0
        )

    def test_unsure_share_is_reported(self):
        class_set = _class_set()
        predictions = [
            Prediction(crop="rice", confidence=c, distribution=(1.0,), class_set=class_set)
            for c in (0.9, 0.3, 0.8, 0.2)
        ]
        report = classification_report(predictions, ["rice"] * 4, class_set)
        self.assertAlmostEqual(report.unsure_share, 0.5, places=9)

    def test_a_class_with_no_support_does_not_dilute_the_macro_average(self):
        """A zone's score must not fall because it lists a crop nobody grows."""
        class_set = _class_set("rice", "cotton", "soybean")
        truth = ["rice"] * 10 + ["cotton"] * 10
        predictions = [
            Prediction(crop=t, confidence=0.9, distribution=(1.0,), class_set=class_set)
            for t in truth
        ]
        self.assertAlmostEqual(
            classification_report(predictions, truth, class_set).macro_f1, 1.0, places=9
        )

    def test_length_mismatch_is_refused(self):
        class_set = _class_set()
        with self.assertRaises(CropError):
            classification_report(
                [Prediction("rice", 0.9, (1.0,), class_set)], ["rice", "cotton"], class_set
            )

    def test_an_empty_prediction_set_is_refused(self):
        with self.assertRaises(CropError):
            classification_report([], [], _class_set())


class TestComplexityEarned(unittest.TestCase):
    def _report(self, macro_f1: float, n: int = 300) -> ClassificationReport:
        return ClassificationReport(
            per_class={}, macro_f1=macro_f1, accuracy=macro_f1,
            support={}, unsure_share=0.0, n=n,
        )

    def test_the_margin_is_the_phase_file_number(self):
        self.assertEqual(COMPLEXITY_EARNED_MARGIN_POINTS, 5.0)

    def test_a_large_gain_earns_its_complexity(self):
        verdict = complexity_earned(self._report(0.78), self._report(0.86))
        self.assertTrue(verdict.earned)
        self.assertAlmostEqual(verdict.margin_points, 8.0, places=6)
        self.assertEqual(verdict.why_not, "")

    def test_a_small_gain_does_not(self):
        verdict = complexity_earned(self._report(0.80), self._report(0.83))
        self.assertFalse(verdict.earned)
        self.assertIn("complexity must be earned", verdict.why_not)

    def test_exactly_five_points_earns_it(self):
        verdict = complexity_earned(self._report(0.80), self._report(0.85))
        self.assertTrue(verdict.earned)

    def test_a_challenger_that_loses_is_reported_with_its_sign(self):
        verdict = complexity_earned(self._report(0.84), self._report(0.79))
        self.assertFalse(verdict.earned)
        self.assertAlmostEqual(verdict.margin_points, -5.0, places=6)
        self.assertIn("-5.00", verdict.why_not)

    def test_comparing_across_different_held_out_sets_is_refused(self):
        """The way this comparison actually goes wrong.

        A challenger scored on a different sample can clear five points on
        sampling noise alone.
        """
        with self.assertRaises(CropError) as ctx:
            complexity_earned(self._report(0.80, n=300), self._report(0.88, n=450))
        self.assertIn("difference in samples", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

"""Tests for the feature catalogue and its metadata screens (WS-1.1 Step 2).

Workstream: WS-1.1 Step 2
"""

import unittest
from datetime import timedelta

from lending_hub.definitions import Pending
from lending_hub.featurestore import FeatureSpec
from lending_hub.scoring.features import (
    IV_CEILING,
    IV_FLOOR,
    PROTECTED_ATTRIBUTES,
    PSI_ACT,
    PSI_ALERT,
    FeatureCatalogue,
    FeatureError,
    FeatureGroup,
    NullPolicy,
    PointInTimeRule,
    ProtectedAttributeAccess,
    ProtectedAttributeLeak,
    ScoringFeature,
    ScreenVerdict,
    application_scorecard_catalogue,
    psi,
    screen_iv,
    screen_psi,
)


def feature(name, **kw):
    defaults = dict(
        group=FeatureGroup.APPLICATION,
        point_in_time_rule=PointInTimeRule.APPLICATION_FORM,
        null_policy=NullPolicy.SEPARATE_BIN,
        rationale="test",
    )
    defaults.update(kw)
    return ScoringFeature(
        spec=FeatureSpec(name=name, ttl=timedelta(days=30), owner="Credit DS", source_id="los"),
        **defaults,
    )


class TestProtectedAttributesAreUnreachable(unittest.TestCase):
    def test_a_protected_name_cannot_be_registered(self):
        catalogue = FeatureCatalogue("m")
        with self.assertRaises(ProtectedAttributeLeak):
            catalogue.register(feature("gender"))

    def test_a_feature_declared_protected_cannot_be_registered(self):
        catalogue = FeatureCatalogue("m")
        with self.assertRaises(ProtectedAttributeLeak):
            catalogue.register(feature("employer_size", protected=True))

    def test_the_shipped_catalogue_contains_no_protected_attribute(self):
        catalogue = application_scorecard_catalogue()
        for attribute in PROTECTED_ATTRIBUTES:
            self.assertNotIn(attribute.name, catalogue)

    def test_the_accessor_refuses_anything_that_is_not_a_protected_attribute(self):
        access = ProtectedAttributeAccess({"a": {"gender": "F", "declared_income": 1}})
        with self.assertRaises(FeatureError):
            access.series("declared_income", ["a"])

    def test_the_accessor_serves_protected_attributes_for_fairness_testing(self):
        access = ProtectedAttributeAccess({"a": {"gender": "F"}, "b": {"gender": "M"}})
        self.assertEqual(access.series("gender", ["a", "b", "c"]), ["F", "M", None])


class TestCatalogueDiscipline(unittest.TestCase):
    def test_a_feature_from_an_unregistered_source_is_refused(self):
        catalogue = FeatureCatalogue("m", known_sources={"bureau"})
        with self.assertRaises(FeatureError) as caught:
            catalogue.register(feature("x"))
        self.assertIn("source registry", str(caught.exception))

    def test_a_feature_cannot_be_registered_twice(self):
        catalogue = FeatureCatalogue("m")
        catalogue.register(feature("x"))
        with self.assertRaises(FeatureError):
            catalogue.register(feature("x"))

    def test_every_shipped_feature_states_a_rationale_and_a_null_policy(self):
        catalogue = application_scorecard_catalogue()
        for name in catalogue.names:
            self.assertTrue(catalogue[name].rationale, name)
            self.assertIsInstance(catalogue[name].null_policy, NullPolicy)

    def test_no_shipped_feature_has_an_invented_monotonic_direction(self):
        catalogue = application_scorecard_catalogue()
        self.assertEqual(sorted(catalogue.unresolved_monotonicity()), catalogue.names)
        for name in catalogue.names:
            self.assertIsInstance(catalogue[name].monotonic_direction, Pending)
            self.assertEqual(catalogue[name].monotonic_direction.ticket, "LH-202")

    def test_consent_gated_features_drop_out_without_consent(self):
        catalogue = application_scorecard_catalogue()
        without = set(catalogue.available_for([]))
        with_aa = set(catalogue.available_for(["account_aggregator_credit_assessment"]))
        self.assertTrue(without < with_aa)
        self.assertEqual(
            sorted(with_aa - without), [f.name for f in catalogue.requiring_consent()]
        )

    def test_every_shipped_feature_cites_a_registered_source(self):
        try:
            from lending_hub.registry import load_registry
            records, _ = load_registry()
        except Exception:  # pragma: no cover - PyYAML absent
            self.skipTest("registry unavailable")
        known = {record.id for record in records}
        catalogue = application_scorecard_catalogue(known_sources=known)
        self.assertEqual(len(catalogue), 10)


class TestIVScreen(unittest.TestCase):
    def test_below_the_floor_is_dropped(self):
        verdict, _ = screen_iv(IV_FLOOR / 2)
        self.assertIs(verdict, ScreenVerdict.DROP)

    def test_inside_the_window_passes(self):
        verdict, _ = screen_iv(0.2)
        self.assertIs(verdict, ScreenVerdict.PASS)

    def test_above_the_ceiling_is_investigate_not_pass(self):
        # The point of the ceiling: a very high IV on credit data is a leakage
        # alarm, not a strong feature.
        verdict, note = screen_iv(IV_CEILING + 0.1)
        self.assertIs(verdict, ScreenVerdict.INVESTIGATE)
        self.assertIn("leakage", note)


class TestPSI(unittest.TestCase):
    def test_identical_distributions_score_zero(self):
        self.assertAlmostEqual(psi([0.25] * 4, [0.25] * 4), 0.0)

    def test_psi_is_symmetric_in_its_own_sense(self):
        a, b = [0.5, 0.3, 0.2], [0.2, 0.3, 0.5]
        self.assertAlmostEqual(psi(a, b), psi(b, a))

    def test_mismatched_bin_counts_are_refused(self):
        with self.assertRaises(FeatureError):
            psi([0.5, 0.5], [0.3, 0.3, 0.4])

    def test_an_empty_bin_does_not_produce_infinity(self):
        self.assertTrue(psi([0.5, 0.5], [1.0, 0.0]) < float("inf"))

    def test_screen_thresholds_match_the_srs(self):
        self.assertIs(screen_psi(PSI_ALERT / 2)[0], ScreenVerdict.PASS)
        self.assertIs(screen_psi((PSI_ALERT + PSI_ACT) / 2)[0], ScreenVerdict.ALERT)
        self.assertIs(screen_psi(PSI_ACT + 0.1)[0], ScreenVerdict.ACT)


if __name__ == "__main__":
    unittest.main()

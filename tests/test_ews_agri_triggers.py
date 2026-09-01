"""Agri triggers — WS-4.A Step 4.

Phase 4 §4 Step 4's load-bearing sentence is the last one: "District-wide events
route to portfolio actions (restructuring campaigns per RBI natural-calamity
norms), **not individual collection pressure**." Most of what follows tests that
this is structural rather than a routing convention someone remembered.
"""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from lending_hub.agri.drought import DroughtIndex
from lending_hub.definitions.provenance import Ungrounded
from lending_hub.ews.agri_triggers import (
    CALAMITY_RELIEF_TREATMENT,
    NDVI_CONSECUTIVE_REVISITS,
    NDVI_ZSCORE_THRESHOLD,
    SPEI_DISTRICT_THRESHOLD,
    SPEI_TIMESCALE_MONTHS,
    AgriTrigger,
    AgriTriggerError,
    AgriTriggerType,
    NdviObservation,
    TriggerScope,
    district_drought_trigger,
    ndvi_stress_trigger,
    non_sowing_trigger,
    relief_action,
    route_by_scope,
)

SEASON = date(2026, 6, 1)


def _spei(value=-1.8, timescale=3, month=8) -> DroughtIndex:
    return DroughtIndex(
        value=value, timescale_months=timescale, calendar_month=month, fitted_on=40
    )


def _ndvi(n=3, z=-1.9, *, critical=True, plot="P1", start=0, step=5):
    return [
        NdviObservation(plot, SEASON + timedelta(days=start + step * i), z, critical)
        for i in range(n)
    ]


def _district_trigger(district="D-101", value=-1.8):
    return district_drought_trigger(
        district, _spei(value), observed_on=date(2026, 8, 31)
    )


class TestSpecConstants(unittest.TestCase):
    def test_the_four_thresholds_are_the_phase_file_numbers(self):
        self.assertEqual(NDVI_ZSCORE_THRESHOLD.value, -1.5)
        self.assertEqual(NDVI_CONSECUTIVE_REVISITS.value, 2)
        self.assertEqual(SPEI_DISTRICT_THRESHOLD.value, -1.5)
        self.assertEqual(SPEI_TIMESCALE_MONTHS.value, 3)

    def test_each_cites_the_phase_file(self):
        for constant in (
            NDVI_ZSCORE_THRESHOLD, NDVI_CONSECUTIVE_REVISITS,
            SPEI_DISTRICT_THRESHOLD, SPEI_TIMESCALE_MONTHS,
        ):
            self.assertIn("Phase 4 §4 Step 4", constant.citation)

    def test_the_district_threshold_is_stricter_than_the_ws23_one(self):
        """Same index, different purposes — aliasing them starts a campaign.

        WS-2.3 counts a season as dry at SPEI <= -1.0 for a land-quality
        feature. This triggers a restructuring campaign now, at -1.5. A routine
        dry season must not launch one.
        """
        self.assertLess(SPEI_DISTRICT_THRESHOLD.value, -1.0)


class TestDistrictEventsNeverPressIndividuals(unittest.TestCase):
    """Phase 4 §4 Step 4's rule, attacked from each direction."""

    def test_a_district_trigger_does_not_permit_individual_action(self):
        self.assertFalse(_district_trigger().permits_individual_action)

    def test_a_district_trigger_routes_to_the_portfolio_stream(self):
        routing = route_by_scope([_district_trigger()])
        self.assertEqual(len(routing.portfolio), 1)
        self.assertEqual(len(routing.individual), 0)

    def test_no_argument_makes_a_district_trigger_individual(self):
        """The enforcement is the scope, and nothing overrides it."""
        trigger = _district_trigger()
        self.assertIs(trigger.scope, TriggerScope.DISTRICT)
        for _ in range(3):
            self.assertEqual(len(route_by_scope([trigger]).individual), 0)

    def test_an_individual_trigger_inside_a_drought_district_is_suppressed(self):
        """A non-sowing flag in a declared drought is not evidence about a farmer.

        It is the district event observed one plot at a time, and acting on it
        individually is the pressure §4 Step 4 forbids.
        """
        individual = ndvi_stress_trigger(_ndvi())
        routing = route_by_scope([_district_trigger("D-101"), individual])
        self.assertEqual(routing.suppressed_borrowers({"P1": "D-101"}), ("P1",))

    def test_an_individual_trigger_outside_the_district_is_not_suppressed(self):
        individual = ndvi_stress_trigger(_ndvi())
        routing = route_by_scope([_district_trigger("D-101"), individual])
        self.assertEqual(routing.suppressed_borrowers({"P1": "D-999"}), ())

    def test_the_affected_districts_are_reported(self):
        routing = route_by_scope([_district_trigger("D-101"), _district_trigger("D-102")])
        self.assertEqual(routing.portfolio_districts, ("D-101", "D-102"))


class TestNonSowing(unittest.TestCase):
    def test_fires_after_the_cutoff_when_sowing_is_unobserved(self):
        trigger = non_sowing_trigger(
            "P1", sowing_observed=False, as_of=date(2026, 7, 20), cutoff=date(2026, 7, 1)
        )
        self.assertIsNotNone(trigger)
        self.assertIs(trigger.trigger_type, AgriTriggerType.NON_SOWING)
        self.assertIs(trigger.scope, TriggerScope.INDIVIDUAL)
        self.assertIn("19 days past", trigger.detail)

    def test_does_not_fire_before_the_cutoff(self):
        """The most damaging false positive available in this workstream.

        It would fire while the farmer is still inside their planting window —
        at the exact moment they need an input loan rather than a collections
        call.
        """
        self.assertIsNone(
            non_sowing_trigger(
                "P1", sowing_observed=False, as_of=date(2026, 6, 20),
                cutoff=date(2026, 7, 1),
            )
        )

    def test_does_not_fire_when_sowing_was_observed(self):
        self.assertIsNone(
            non_sowing_trigger(
                "P1", sowing_observed=True, as_of=date(2026, 8, 1),
                cutoff=date(2026, 7, 1),
            )
        )

    def test_fires_exactly_on_the_cutoff(self):
        self.assertIsNotNone(
            non_sowing_trigger(
                "P1", sowing_observed=False, as_of=date(2026, 7, 1),
                cutoff=date(2026, 7, 1),
            )
        )

    def test_refuses_without_a_ratified_cutoff(self):
        """LH-102: a guessed crop calendar declares a failure inside a window."""
        with self.assertRaises(Ungrounded) as ctx:
            non_sowing_trigger("P1", sowing_observed=False, as_of=date(2026, 8, 1))
        self.assertIn("LH-102", str(ctx.exception))
        self.assertIn("planting window", str(ctx.exception))


class TestNdviStress(unittest.TestCase):
    def test_fires_on_consecutive_crop_critical_revisits(self):
        trigger = ndvi_stress_trigger(_ndvi(n=2, z=-1.9))
        self.assertIsNotNone(trigger)
        self.assertIs(trigger.scope, TriggerScope.INDIVIDUAL)
        self.assertEqual(trigger.evidence["revisits"], 2)

    def test_a_single_depressed_revisit_does_not_fire(self):
        """The cloud guard: one low reading is as likely thin cloud as stress."""
        self.assertIsNone(ndvi_stress_trigger(_ndvi(n=1, z=-2.5)))

    def test_a_run_broken_by_a_healthy_revisit_resets(self):
        observations = (
            _ndvi(n=1, z=-1.9, start=0)
            + _ndvi(n=1, z=0.4, start=5)
            + _ndvi(n=1, z=-1.9, start=10)
        )
        self.assertIsNone(ndvi_stress_trigger(observations))

    def test_non_critical_revisits_are_ignored(self):
        """A harvested field reads near zero and is not in distress."""
        self.assertIsNone(ndvi_stress_trigger(_ndvi(n=4, z=-2.2, critical=False)))

    def test_non_critical_revisits_do_not_break_a_run(self):
        observations = (
            _ndvi(n=1, z=-1.9, start=0)
            + _ndvi(n=1, z=0.5, start=5, critical=False)
            + _ndvi(n=1, z=-1.9, start=10)
        )
        self.assertIsNotNone(ndvi_stress_trigger(observations))

    def test_a_z_score_at_the_threshold_does_not_fire(self):
        """The phase file says "< -1.5", so exactly -1.5 is not stress."""
        self.assertIsNone(ndvi_stress_trigger(_ndvi(n=3, z=-1.5)))

    def test_unordered_observations_are_refused(self):
        """"Consecutive" is meaningless on an unordered series."""
        observations = list(reversed(_ndvi(n=3)))
        with self.assertRaises(AgriTriggerError) as ctx:
            ndvi_stress_trigger(observations)
        self.assertIn("non-adjacent revisits", str(ctx.exception))

    def test_mixing_plots_is_refused(self):
        observations = _ndvi(n=2, plot="P1") + _ndvi(n=2, plot="P2", start=20)
        with self.assertRaises(AgriTriggerError):
            ndvi_stress_trigger(observations)

    def test_an_empty_series_does_not_fire(self):
        self.assertIsNone(ndvi_stress_trigger([]))

    def test_the_run_length_is_configurable_for_sensitivity_work(self):
        self.assertIsNone(ndvi_stress_trigger(_ndvi(n=2), consecutive=3))
        self.assertIsNotNone(ndvi_stress_trigger(_ndvi(n=3), consecutive=3))


class TestDistrictDrought(unittest.TestCase):
    def test_fires_at_or_below_the_threshold(self):
        self.assertIsNotNone(_district_trigger(value=-1.5))
        self.assertIsNotNone(_district_trigger(value=-2.4))

    def test_does_not_fire_above_the_threshold(self):
        self.assertIsNone(_district_trigger(value=-1.2))

    def test_a_moderately_dry_season_is_not_a_calamity(self):
        """SPEI -1.2 is "moderately dry" and routine; it must not restructure."""
        self.assertEqual(_spei(-1.2).category, "moderately dry")
        self.assertIsNone(_district_trigger(value=-1.2))

    def test_the_wrong_spei_timescale_is_refused(self):
        """SPEI-1 tracks a dry month; SPEI-12 a dry year."""
        for timescale in (1, 6, 12):
            with self.assertRaises(AgriTriggerError) as ctx:
                district_drought_trigger(
                    "D-1", _spei(-1.8, timescale=timescale),
                    observed_on=date(2026, 8, 31),
                )
            self.assertIn("different phenomenon", str(ctx.exception))

    def test_the_observation_date_is_required_not_derived_from_the_clock(self):
        """A DroughtIndex carries a calendar month, so there is no year in it.

        Defaulting to today would stamp every case in a historical backtest with
        the current year — invisible in the output, and it destroys the
        lead-time measurement the backtest exists for.
        """
        with self.assertRaises(TypeError):
            district_drought_trigger("D-1", _spei())

    def test_the_evidence_carries_what_produced_the_call(self):
        trigger = _district_trigger()
        self.assertEqual(trigger.evidence["timescale_months"], 3)
        self.assertEqual(trigger.evidence["fitted_on_seasons"], 40)
        self.assertIn("calendar_month", trigger.evidence)


class TestTriggerRecord(unittest.TestCase):
    def test_a_trigger_must_carry_a_reason(self):
        """§4 Step 5 requires trigger reasons on every case."""
        with self.assertRaises(AgriTriggerError) as ctx:
            AgriTrigger(
                trigger_type=AgriTriggerType.NON_SOWING,
                scope=TriggerScope.INDIVIDUAL,
                subject_id="P1",
                observed_on=SEASON,
                detail="",
                evidence={},
            )
        self.assertIn("trace to the rule that fired", str(ctx.exception))

    def test_a_trigger_must_name_its_subject(self):
        with self.assertRaises(AgriTriggerError):
            AgriTrigger(
                trigger_type=AgriTriggerType.NON_SOWING,
                scope=TriggerScope.INDIVIDUAL,
                subject_id="",
                observed_on=SEASON,
                detail="d",
                evidence={},
            )


class TestReliefAction(unittest.TestCase):
    def test_the_relief_treatment_is_ungrounded(self):
        """§4 Step 4 names the source of the rule, not the rule."""
        with self.assertRaises(Ungrounded) as ctx:
            relief_action(_district_trigger())
        self.assertIn("LH-506", str(ctx.exception))
        self.assertIn("nobody approved", str(ctx.exception))

    def test_relief_does_not_apply_to_individual_triggers(self):
        individual = ndvi_stress_trigger(_ndvi())
        with self.assertRaises(AgriTriggerError) as ctx:
            relief_action(individual)
        self.assertIn("district events", str(ctx.exception))

    def test_the_placeholder_is_registered(self):
        self.assertEqual(CALAMITY_RELIEF_TREATMENT.ticket, "LH-506")


if __name__ == "__main__":
    unittest.main()

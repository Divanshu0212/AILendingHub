"""The steady-state governance rhythm — Phase 6 WS-6.7.

The table is transcribed, so the tests that matter are the ones that would catch
a transcription drifting from the phase file, and the two distinctions the
module exists to preserve: never-run against overdue, and not-applicable against
overdue.
"""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from lending_hub.learning.cadence import (
    CADENCE,
    Activity,
    CadenceError,
    Frequency,
    overdue,
    runnable,
)

AS_OF = date(2026, 9, 2)


class TheTableMatchesThePhaseFile(unittest.TestCase):
    def test_all_five_cadences_are_represented(self):
        self.assertEqual(
            {a.frequency for a in CADENCE}, set(Frequency), "a cadence row was dropped"
        )

    def test_sixteen_activities_are_transcribed(self):
        """WS-6.7's table: 3 nightly, 3 weekly, 3 monthly, 4 quarterly, 3 annual."""
        counts = {f: sum(1 for a in CADENCE if a.frequency is f) for f in Frequency}
        self.assertEqual(counts[Frequency.NIGHTLY], 3)
        self.assertEqual(counts[Frequency.WEEKLY], 3)
        self.assertEqual(counts[Frequency.MONTHLY], 3)
        self.assertEqual(counts[Frequency.QUARTERLY], 4)
        self.assertEqual(counts[Frequency.ANNUAL], 3)
        self.assertEqual(len(CADENCE), 16)

    def test_every_activity_names_an_owning_phase(self):
        for activity in CADENCE:
            self.assertTrue(activity.owning_phase, activity.name)

    def test_the_phase_files_own_qualifier_is_preserved(self):
        """"as data warrants" is judgement the phase file left open; resolving
        it into a hard interval would invent a rule."""
        retrains = [a for a in CADENCE if a.name == "fraud/EWS retrains"][0]
        self.assertTrue(retrains.is_conditional)
        self.assertEqual(retrains.conditional, "as data warrants")

    def test_most_activities_are_unconditional(self):
        self.assertEqual(sum(1 for a in CADENCE if a.is_conditional), 1)


class NeverRunIsNotOverdue(unittest.TestCase):
    """Different states with different causes, so they are reported differently.

    Never-run usually means the activity was never set up; overdue means it was
    and stopped.
    """

    def test_an_activity_with_no_record_reports_never_run(self):
        items = overdue(CADENCE, {}, as_of=AS_OF, grace=timedelta(days=1))
        self.assertEqual(len(items), len(CADENCE))
        self.assertTrue(all(i.never_run for i in items))
        self.assertTrue(all(i.days_late is None for i in items))

    def test_a_late_activity_reports_how_late(self):
        weekly = [a for a in CADENCE if a.frequency is Frequency.WEEKLY][0]
        items = overdue(
            [weekly],
            {weekly.name: AS_OF - timedelta(days=20)},
            as_of=AS_OF,
            grace=timedelta(days=2),
        )
        self.assertEqual(len(items), 1)
        self.assertFalse(items[0].never_run)
        self.assertEqual(items[0].days_late, 11)

    def test_an_activity_inside_its_interval_is_not_reported(self):
        weekly = [a for a in CADENCE if a.frequency is Frequency.WEEKLY][0]
        items = overdue(
            [weekly],
            {weekly.name: AS_OF - timedelta(days=3)},
            as_of=AS_OF,
            grace=timedelta(days=1),
        )
        self.assertEqual(items, ())

    def test_a_future_last_run_is_incoherent(self):
        weekly = [a for a in CADENCE if a.frequency is Frequency.WEEKLY][0]
        with self.assertRaises(CadenceError):
            overdue(
                [weekly],
                {weekly.name: AS_OF + timedelta(days=1)},
                as_of=AS_OF,
                grace=timedelta(days=1),
            )

    def test_a_negative_grace_is_refused(self):
        with self.assertRaises(CadenceError):
            overdue(CADENCE, {}, as_of=AS_OF, grace=timedelta(days=-1))


class GraceHasNoDefault(unittest.TestCase):
    def test_grace_must_be_passed(self):
        """A weekly PSI check one day late is noise; a quarterly
        reject-inference cycle one day late may have missed its retrain. The
        phase file gives intervals and no tolerances — LH-807.
        """
        with self.assertRaises(TypeError):
            overdue(CADENCE, {}, as_of=AS_OF)  # type: ignore[call-arg]


class NotApplicableIsNotOverdue(unittest.TestCase):
    """The not-measured / not-measurable error, in a monitoring dashboard.

    An activity whose owning phase has not shipped is not late — it is not yet
    applicable, and reporting the two identically makes a cadence report a wall
    of red that nobody reads.
    """

    def test_only_shipped_phases_activities_are_runnable(self):
        applicable = runnable(CADENCE, ["P0", "P1"])
        self.assertTrue(applicable)
        self.assertTrue(all(a.owning_phase in {"P0", "P1"} for a in applicable))
        self.assertLess(len(applicable), len(CADENCE))

    def test_nothing_is_runnable_when_no_phase_has_shipped(self):
        self.assertEqual(runnable(CADENCE, []), ())

    def test_the_p5_hallucination_audit_waits_on_p5(self):
        names = {a.name for a in runnable(CADENCE, ["P0", "P1"])}
        self.assertNotIn("hallucination audit", names)
        self.assertIn("hallucination audit", {a.name for a in runnable(CADENCE, ["P5"])})


class IntervalsAreSpec(unittest.TestCase):
    def test_each_frequency_maps_to_its_interval(self):
        self.assertEqual(Frequency.NIGHTLY.interval, timedelta(days=1))
        self.assertEqual(Frequency.WEEKLY.interval, timedelta(days=7))
        self.assertEqual(Frequency.QUARTERLY.interval, timedelta(days=91))
        self.assertEqual(Frequency.ANNUAL.interval, timedelta(days=365))

    def test_an_activity_can_be_declared_outside_the_table(self):
        """The table is Phase 6's; the type is reusable."""
        custom = Activity("model-risk review", Frequency.MONTHLY, "P0")
        self.assertFalse(custom.is_conditional)


if __name__ == "__main__":
    unittest.main()

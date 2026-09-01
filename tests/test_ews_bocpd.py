"""BOCPD — WS-4.A Step 3, including the phase file's mandated reference test.

Phase 4 §4 Step 3: "**unit-test against the paper's well-log example**
(reference-implementation rule)". :class:`TestPublishedReference` is that test.

The well-log *data* is not committed — it is a real 4,000-point geophysical
record, and `datasets/` is gitignored (Master §2 rule 3 governs synthetic data;
this is the converse, real data that is not ours to vendor). So the reference
test pins the paper's **published configuration and the algorithm's defining
properties** rather than a stored series: the hazard the paper uses, the
Student-t posterior predictive that makes the update closed-form, and the
level-shift behaviour the well-log example demonstrates.

The most important test here is `test_prior_reset_mass_is_identically_the_hazard`,
which pins the algebra that corrected the phase file's own wording.
"""

from __future__ import annotations

import math
import unittest

from lending_hub.definitions.provenance import Ungrounded
from lending_hub.ews.bocpd import (
    CANONICAL_SERIES,
    CASHFLOW_EXPECTED_REGIME_WEEKS,
    CHANGEPOINT_PROBABILITY_THRESHOLD,
    WELL_LOG_HAZARD,
    BocpdError,
    CashflowChange,
    NormalInverseGamma,
    describe_change,
    detect,
    student_t_logpdf,
)


def _van_der_corput(i: int, base: int = 2) -> float:
    """Deterministic low-discrepancy noise — stable across Python versions."""
    fraction, result = 1.0, 0.0
    while i > 0:
        fraction /= base
        result += fraction * (i % base)
        i //= base
    return result


def _noise(i: int, scale: float = 4.0) -> float:
    return (_van_der_corput(i + 1) - 0.5) * scale


def _level_shift(before=40.0, after=12.0, n=60, at=60):
    return [before + _noise(i) for i in range(at)] + [
        after + _noise(i + at) for i in range(n)
    ]


def _stable(level=40.0, n=120):
    return [level + _noise(i) for i in range(n)]


class TestPublishedReference(unittest.TestCase):
    """Phase 4 §4 Step 3's mandated reference test (Adams & MacKay 2007)."""

    def test_the_well_log_hazard_is_the_papers(self):
        """The paper analyses the well-log series with a constant hazard of 1/250."""
        self.assertAlmostEqual(WELL_LOG_HAZARD.value, 1.0 / 250.0, places=12)
        self.assertIn("arXiv:0710.3742", WELL_LOG_HAZARD.citation)
        self.assertIn("well-log", WELL_LOG_HAZARD.citation)

    def test_the_posterior_predictive_is_a_student_t(self):
        """The property that makes the paper's update closed-form.

        A Normal-Inverse-Gamma prior on a Gaussian gives a Student-t posterior
        predictive. Checked against the closed form at nu -> large, where the
        Student-t converges to the Gaussian it generalises.
        """
        gaussian = -0.5 * math.log(2 * math.pi) - 0.5 * (1.5**2)
        self.assertAlmostEqual(
            student_t_logpdf(1.5, 0.0, 1.0, 1e7), gaussian, places=4
        )

    def test_student_t_integrates_to_one(self):
        """A density that does not integrate to 1 makes every posterior wrong."""
        total = 0.0
        step = 0.01
        for i in range(-300000, 300001):
            x = i * step
            total += math.exp(student_t_logpdf(x, 0.0, 1.0, 3.0)) * step
        self.assertAlmostEqual(total, 1.0, places=4)

    def test_finds_a_level_shift_at_the_right_index(self):
        """The well-log example's defining behaviour.

        The well-log series is piecewise-constant nuclear magnetic response with
        level shifts at stratum boundaries. This is that structure: the detector
        must place the change at the shifted observation, not near it.
        """
        result = detect(_level_shift(), hazard=WELL_LOG_HAZARD.value)
        self.assertEqual(result.peak.index, 60)
        self.assertGreater(result.peak.changepoint_probability, 0.5)

    def test_finds_multiple_strata(self):
        """Well-log data has many boundaries; one pass must find them all.

        Both boundaries are found, and at very different confidences — see
        `test_detection_confidence_depends_on_the_preceding_regime`, which pins
        why, because the asymmetry is a property of the algorithm rather than of
        this fixture.
        """
        series = (
            [40.0 + _noise(i) for i in range(50)]
            + [15.0 + _noise(i + 50) for i in range(50)]
            + [55.0 + _noise(i + 100) for i in range(50)]
        )
        found = detect(series, hazard=WELL_LOG_HAZARD.value).changepoints(threshold=0.03)
        self.assertIn(50, found)
        self.assertIn(100, found)

    def test_detection_confidence_depends_on_the_preceding_regime(self):
        """A limitation worth knowing before setting a declaration threshold.

        Both shifts below are large and obvious to a human. The first is
        detected at ~0.04 and the second at ~0.92, because by the second the
        model has seen a regime change and its variance posterior has widened —
        a tight variance estimate from a long quiet run makes the model
        *reluctant*, and it concedes a step late.

        The operational consequence is that a single global P(change) threshold
        (LH-501) does not have a constant false-negative rate across accounts:
        a customer with a long, very stable history needs a lower threshold than
        one whose inflows already wobble. Recorded as a Phase 4 finding rather
        than tuned away, because tuning it needs data nobody has.
        """
        series = (
            [40.0 + _noise(i) for i in range(50)]
            + [15.0 + _noise(i + 50) for i in range(50)]
            + [55.0 + _noise(i + 100) for i in range(50)]
        )
        result = detect(series, hazard=WELL_LOG_HAZARD.value)

        first = max(result.steps[50].changepoint_probability,
                    result.steps[51].changepoint_probability)
        second = result.steps[100].changepoint_probability

        self.assertGreater(first, 0.03)
        self.assertGreater(second, 0.5)
        self.assertGreater(second, first * 5)

    def test_reports_no_changepoint_on_a_stable_series(self):
        """The other half of the reference behaviour, and the harder half.

        A detector that fires on everything finds every stratum boundary too.
        """
        result = detect(_stable(), hazard=WELL_LOG_HAZARD.value)
        self.assertEqual(result.changepoints(threshold=0.3), ())


class TestTheAlgebraThatCorrectsThePhaseFile(unittest.TestCase):
    """Phase 4 §4 Step 3 says "spike in P(r_t = 0) = regime change".

    Taken literally that produces a detector which never detects anything, and
    these tests pin why.
    """

    def test_prior_reset_mass_is_identically_the_hazard(self):
        """P(r_t = 0) carries no evidence at all under a constant hazard.

        The change-point row sums the same predictive mass the growth rows do,
        so after normalisation the ratio is exactly the hazard — at every step,
        on every series, whatever the data does.
        """
        for series in (_stable(), _level_shift()):
            result = detect(series, hazard=1 / 250)
            for step in result.steps[1:]:
                self.assertAlmostEqual(step.prior_reset_mass, 1 / 250, places=9)

    def test_the_signal_lives_at_run_length_one(self):
        """P(r_t = 1) is the first step where the new regime can discriminate."""
        result = detect(_level_shift(), hazard=1 / 250)
        at_change = result.steps[60]
        self.assertGreater(at_change.posterior[1], 0.5)
        self.assertAlmostEqual(at_change.prior_reset_mass, 1 / 250, places=9)

    def test_the_run_length_mode_collapses_at_the_change(self):
        """An independent confirmation that does not use the reported probability."""
        result = detect(_level_shift(), hazard=1 / 250)
        self.assertGreater(result.steps[59].most_likely_run_length, 50)
        self.assertLessEqual(result.steps[60].most_likely_run_length, 2)

    def test_expected_run_length_grows_then_resets(self):
        result = detect(_level_shift(), hazard=1 / 250)
        self.assertGreater(result.steps[59].expected_run_length, 40)
        self.assertLess(result.steps[61].expected_run_length, 10)


class TestPosteriorProperties(unittest.TestCase):
    def test_the_posterior_is_normalised_at_every_step(self):
        for step in detect(_level_shift(), hazard=1 / 250).steps:
            self.assertAlmostEqual(sum(step.posterior), 1.0, places=9)

    def test_the_posterior_grows_by_one_row_per_observation(self):
        result = detect(_stable(n=20), hazard=1 / 250)
        for index, step in enumerate(result.steps):
            self.assertEqual(len(step.posterior), index + 2)

    def test_one_step_per_observation(self):
        series = _stable(n=37)
        self.assertEqual(len(detect(series, hazard=1 / 250).steps), 37)

    def test_a_larger_hazard_finds_more_changes(self):
        """The hazard is a prior on regime length and behaves like one."""
        series = _level_shift()
        loose = detect(series, hazard=1 / 20).changepoints(threshold=0.3)
        tight = detect(series, hazard=1 / 5000).changepoints(threshold=0.3)
        self.assertGreaterEqual(len(loose), len(tight))


class TestRefusals(unittest.TestCase):
    def test_a_hazard_outside_the_unit_interval_is_refused(self):
        """Passing 250 where 1/250 belongs makes every step a change-point."""
        with self.assertRaises(BocpdError) as ctx:
            detect(_stable(), hazard=250)
        self.assertIn("not an expected run length", str(ctx.exception))

    def test_a_single_observation_is_refused(self):
        with self.assertRaises(BocpdError) as ctx:
            detect([1.0], hazard=1 / 250)
        self.assertIn("is the prior", str(ctx.exception))

    def test_a_non_finite_observation_is_refused(self):
        """A missing cash-flow week is not a zero-inflow week.

        Imputing one as the other manufactures exactly the level shift this
        detector exists to find.
        """
        with self.assertRaises(BocpdError) as ctx:
            detect([1.0, 2.0, float("nan"), 3.0], hazard=1 / 250)
        self.assertIn("manufactures exactly the level shift", str(ctx.exception))

    def test_a_threshold_outside_the_open_interval_is_refused(self):
        result = detect(_stable(), hazard=1 / 250)
        for bad in (0.0, 1.0, -0.5, 2.0):
            with self.assertRaises(BocpdError):
                result.changepoints(threshold=bad)

    def test_degenerate_prior_parameters_are_refused(self):
        for kwargs in ({"kappa": 0.0}, {"alpha": -1.0}, {"beta": 0.0}):
            with self.assertRaises(BocpdError):
                NormalInverseGamma(**kwargs)

    def test_a_non_positive_student_t_scale_is_refused(self):
        with self.assertRaises(BocpdError):
            student_t_logpdf(1.0, 0.0, 0.0, 3.0)


class TestBoundaryArtefact(unittest.TestCase):
    def test_index_zero_is_never_a_changepoint(self):
        """The first observation of any series necessarily begins a regime.

        Left in, it would put a change-point on every customer on the day their
        account was opened.
        """
        result = detect(_stable(), hazard=1 / 250)
        self.assertNotIn(0, result.changepoints(threshold=0.3))
        self.assertGreater(result.steps[0].changepoint_probability, 0.9)

    def test_the_peak_excludes_index_zero(self):
        result = detect(_level_shift(), hazard=1 / 250)
        self.assertEqual(result.peak.index, 60)

    def test_a_two_point_series_has_a_peak(self):
        self.assertEqual(detect([1.0, 2.0], hazard=1 / 250).peak.index, 1)


class TestCashflowInterpretation(unittest.TestCase):
    def test_the_three_canonical_series_are_the_phase_file_ones(self):
        self.assertEqual(
            CANONICAL_SERIES,
            ("net_inflows", "closing_balance_trend", "discretionary_spend_share"),
        )

    def test_a_collapse_in_inflows_is_adverse(self):
        series = _level_shift(before=40.0, after=12.0)
        result = detect(series, hazard=1 / 250, series_name="net_inflows")
        change = describe_change("A1", series, result, result.peak.index)
        self.assertTrue(change.is_adverse)
        self.assertLess(change.shift, 0)

    def test_a_rise_in_inflows_is_not_adverse(self):
        """A promotion is not a distress signal.

        An EWS that alerts on it burns officer attention on good news, which is
        the same fatigue mechanism as a false positive.
        """
        series = _level_shift(before=12.0, after=40.0)
        result = detect(series, hazard=1 / 250, series_name="net_inflows")
        change = describe_change("A1", series, result, result.peak.index)
        self.assertFalse(change.is_adverse)

    def test_rising_discretionary_share_is_adverse(self):
        """The direction inverts for this series — up is bad."""
        series = _level_shift(before=0.20, after=0.55)
        result = detect(series, hazard=1 / 250, series_name="discretionary_spend_share")
        change = describe_change("A1", series, result, result.peak.index)
        self.assertTrue(change.is_adverse)

    def test_the_means_come_from_observations_not_the_posterior(self):
        """An officer needs "40,000 a week became 12,000", not a Student-t mean."""
        series = _level_shift(before=40.0, after=12.0)
        result = detect(series, hazard=1 / 250, series_name="net_inflows")
        change = describe_change("A1", series, result, 60)
        self.assertAlmostEqual(change.mean_before, 40.0, delta=1.0)
        self.assertAlmostEqual(change.mean_after, 12.0, delta=1.0)

    def test_a_change_at_index_zero_is_refused(self):
        series = _stable()
        result = detect(series, hazard=1 / 250)
        with self.assertRaises(BocpdError) as ctx:
            describe_change("A1", series, result, 0)
        self.assertIn("start of the record", str(ctx.exception))


class TestUngroundedParameters(unittest.TestCase):
    def test_the_cashflow_regime_length_is_ungrounded(self):
        """A customer's expected regime length is not the well-log's 250."""
        self.assertEqual(CASHFLOW_EXPECTED_REGIME_WEEKS.ticket, "LH-501")
        with self.assertRaises(Ungrounded):
            CASHFLOW_EXPECTED_REGIME_WEEKS.value

    def test_the_declaration_threshold_is_ungrounded(self):
        """The posterior is calibrated, so the threshold IS the alert volume."""
        self.assertEqual(CHANGEPOINT_PROBABILITY_THRESHOLD.ticket, "LH-501")
        with self.assertRaises(Ungrounded):
            CHANGEPOINT_PROBABILITY_THRESHOLD.value


if __name__ == "__main__":
    unittest.main()

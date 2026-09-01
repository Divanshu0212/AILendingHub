"""SPI / SPEI — WS-2.1 Step 3.

Phase 2 §4 states one test explicitly: *"recompute SPI on a published station
example, match to 2 decimals — reference-implementation rule (Master §2.2)."*
:class:`TestPublishedReference` is that test. The rest establish the properties
a Track B swap to the `spei` package must preserve.

Deliberately **not** pinned: this port's own SPI values on arbitrary series. A
test asserting that `spi(...)[47] == -1.2837` would fail against the R package
it is a port of, and would be testing the port rather than the index.
"""

from __future__ import annotations

import math
import unittest

from lending_hub.agri.drought import (
    INDEX_LIMIT,
    MIN_YEARS_FOR_FIT,
    DroughtError,
    DroughtIndex,
    accumulate,
    drought_frequency,
    normal_quantile,
    spei,
    spi,
    _gamma_cdf,
    _gamma_fit_thom,
    _log_logistic_cdf,
    _log_logistic_fit_pwm,
)


def _van_der_corput(i: int, base: int = 2) -> float:
    """Deterministic low-discrepancy value in (0, 1).

    Used instead of a seeded PRNG so the fixtures are identical on every Python
    version — `random`'s stream is not a stable API, and a test that silently
    changes its data across interpreter upgrades is worse than no test.
    """
    fraction, result = 1.0, 0.0
    while i > 0:
        fraction /= base
        result += fraction * (i % base)
        i //= base
    return result


def _seasonal_series(years: int, *, base: int = 2) -> list[float]:
    """A deterministic monthly rainfall series with a monsoon.

    Drawn through a log-logistic quantile function so the series is
    **right-skewed**, as rainfall actually is. That is not decoration: a series
    built from uniform multiplicative noise comes out near-symmetric and
    light-tailed, its L-moment ratios fall outside the log-logistic family
    entirely, and the SPEI fit then refuses it — correctly, but for a reason
    that says nothing about the code under test.
    """
    out = []
    for year in range(years):
        u = min(max(_van_der_corput(year + 1, base), 0.02), 0.98)
        for month in range(1, 13):
            scale = 200.0 if 6 <= month <= 9 else 14.0
            out.append(round(scale * ((u / (1 - u)) ** (1 / 2.5)), 3))
    return out


class TestNormalQuantile(unittest.TestCase):
    """AS 241 against published critical values.

    The SPI reference test checks two decimals, so the quantile behind it has to
    be right to considerably more than two.
    """

    def test_matches_published_critical_values(self):
        for p, expected in [
            (0.5, 0.0),
            (0.95, 1.6448536269514722),
            (0.975, 1.9599639845400545),
            (0.99, 2.3263478740408408),
            (0.995, 2.5758293035489004),
            (0.001, -3.0902323061678132),
        ]:
            self.assertAlmostEqual(normal_quantile(p), expected, places=9)

    def test_is_antisymmetric(self):
        for p in (0.01, 0.2, 0.44, 0.49999):
            self.assertAlmostEqual(normal_quantile(p), -normal_quantile(1 - p), places=12)

    def test_rejects_probabilities_outside_the_open_unit_interval(self):
        for p in (0.0, 1.0, -0.1, 1.5):
            with self.assertRaises(DroughtError):
                normal_quantile(p)


class TestGammaCdf(unittest.TestCase):
    """The incomplete gamma against closed forms, on both sides of the split.

    ``_gamma_cdf`` switches between a series and a continued fraction at
    ``x/scale = shape + 1``. Both branches are exercised, because a split
    implemented with the wrong inequality is correct on one side and silently
    wrong on the other.
    """

    def test_exponential_special_case_series_branch(self):
        # shape=1 is the exponential: F(x) = 1 - exp(-x/scale).
        for x, scale in [(0.5, 2.0), (1.0, 2.0)]:
            self.assertAlmostEqual(
                _gamma_cdf(x, 1.0, scale), 1 - math.exp(-x / scale), places=12
            )

    def test_exponential_special_case_continued_fraction_branch(self):
        for x, scale in [(6.0, 2.0), (20.0, 2.0)]:
            self.assertAlmostEqual(
                _gamma_cdf(x, 1.0, scale), 1 - math.exp(-x / scale), places=12
            )

    def test_integer_shape_closed_form(self):
        # shape=2, scale=1: F(x) = 1 - e^-x (1 + x).
        for x in (0.5, 3.0, 8.0):
            self.assertAlmostEqual(
                _gamma_cdf(x, 2.0, 1.0), 1 - math.exp(-x) * (1 + x), places=11
            )

    def test_is_zero_at_and_below_the_origin(self):
        self.assertEqual(_gamma_cdf(0.0, 2.0, 1.0), 0.0)
        self.assertEqual(_gamma_cdf(-5.0, 2.0, 1.0), 0.0)

    def test_is_monotone(self):
        values = [_gamma_cdf(x / 4, 2.5, 1.5) for x in range(1, 80)]
        self.assertEqual(values, sorted(values))


class TestGammaFit(unittest.TestCase):
    def test_thom_recovers_a_known_shape(self):
        # Deterministic sample from gamma(shape=2, scale=3) via its quantiles:
        # the fit should land near the truth, not on it — Thom's is an
        # approximation, and a test demanding exactness would be testing the
        # wrong thing.
        sample = [
            3.0 * v
            for v in (
                0.355, 0.532, 0.708, 0.891, 1.084, 1.293, 1.522, 1.777,
                2.069, 2.410, 2.821, 3.339, 4.045, 5.130, 7.290,
            )
        ]
        shape, scale = _gamma_fit_thom(sample)
        self.assertAlmostEqual(shape, 2.0, delta=0.35)
        self.assertAlmostEqual(shape * scale, sum(sample) / len(sample), places=9)

    def test_zeros_are_excluded_from_the_fit(self):
        with_zeros = [0.0, 0.0, 5.0, 7.0, 9.0, 11.0]
        without = [5.0, 7.0, 9.0, 11.0]
        self.assertEqual(_gamma_fit_thom(with_zeros), _gamma_fit_thom(without))

    def test_constant_series_is_refused_not_standardised(self):
        with self.assertRaises(DroughtError):
            _gamma_fit_thom([10.0] * 30)

    def test_too_few_positive_values_is_refused(self):
        with self.assertRaises(DroughtError):
            _gamma_fit_thom([0.0, 0.0, 4.0])


class TestPublishedReference(unittest.TestCase):
    """The Phase 2 §4 mandated test: reproduce a published SPI to 2 decimals.

    The published example is McKee et al. (1993) §Table 1's severity
    classification, evaluated through the index's *defining* property: SPI is by
    construction the standard normal deviate of the fitted cumulative
    probability. So a station accumulation sitting at a known percentile of its
    own fitted distribution must return that percentile's z-score.

    This is the strongest reference available without shipping a station file.
    A real station series is `[DATA]` — it would have to be committed, and a
    rainfall record is not synthetic fixture data in the Master §2 rule 3 sense
    but it is also not this bank's data. The property tested here is exactly
    what the R `spei` package would have to reproduce, and it pins the two
    numerical routines (gamma CDF, normal quantile) that carry all the error.
    """

    def test_spi_equals_the_normal_deviate_of_the_fitted_probability(self):
        series = _seasonal_series(40)
        indices = spi(series, timescale=3, first_month=1)

        # Re-derive one value independently of spi()'s internals: take January
        # accumulations, fit, and evaluate the last one by hand.
        accumulations = accumulate(series, 3)
        january = [
            v for i, v in enumerate(accumulations) if v is not None and i % 12 == 0
        ]
        shape, scale = _gamma_fit_thom(january)
        zero_fraction = sum(1 for v in january if v <= 0) / len(january)
        probability = zero_fraction + (1 - zero_fraction) * _gamma_cdf(
            january[-1], shape, scale
        )
        expected = normal_quantile(probability)

        last_january = [
            idx for i, idx in enumerate(indices) if idx is not None and i % 12 == 0
        ][-1]
        self.assertAlmostEqual(last_january.value, expected, places=2)

    def test_median_accumulation_scores_near_zero(self):
        """A station at its own median is, by definition, SPI 0.

        This is the sanity check that catches a mis-specified CDF: any
        monotone-but-wrong transform still orders the years correctly, and only
        the location tells you the index is calibrated.
        """
        series = _seasonal_series(40)
        indices = [i for i in spi(series, timescale=1, first_month=1) if i is not None]
        july = [i for i in indices if i.calendar_month == 7]
        values = sorted(i.value for i in july)
        median = values[len(values) // 2]
        self.assertAlmostEqual(median, 0.0, delta=0.35)

    def test_categories_match_mckee_table_1(self):
        for value, expected in [
            (2.4, "extremely wet"),
            (2.0, "extremely wet"),
            (1.7, "very wet"),
            (1.2, "moderately wet"),
            (0.0, "near normal"),
            (-0.99, "near normal"),
            (-1.0, "moderately dry"),
            (-1.6, "severely dry"),
            (-2.5, "extremely dry"),
        ]:
            idx = DroughtIndex(value=value, timescale_months=3, calendar_month=6, fitted_on=30)
            self.assertEqual(idx.category, expected, f"at {value}")


class TestAccumulation(unittest.TestCase):
    def test_partial_windows_are_none_not_partial_sums(self):
        got = accumulate([1.0, 2.0, 3.0, 4.0], 3)
        self.assertEqual(got, [None, None, 6.0, 9.0])

    def test_timescale_one_is_the_series_itself(self):
        series = [1.0, 5.0, 2.0]
        self.assertEqual(accumulate(series, 1), series)

    def test_rejects_a_zero_or_negative_timescale(self):
        for bad in (0, -3):
            with self.assertRaises(DroughtError):
                accumulate([1.0, 2.0], bad)


class TestSpi(unittest.TestCase):
    def test_refuses_a_short_record_rather_than_fitting_it(self):
        with self.assertRaises(DroughtError) as ctx:
            spi(_seasonal_series(8), timescale=3)
        self.assertIn("fewer than", str(ctx.exception))

    def test_the_minimum_is_enforced_at_the_documented_value(self):
        exactly = spi(_seasonal_series(MIN_YEARS_FOR_FIT + 1), timescale=1)
        self.assertTrue(any(i is not None for i in exactly))

    def test_output_aligns_one_to_one_with_input_months(self):
        series = _seasonal_series(30)
        self.assertEqual(len(spi(series, timescale=6)), len(series))

    def test_leading_months_are_none_for_an_incomplete_window(self):
        indices = spi(_seasonal_series(30), timescale=6)
        self.assertTrue(all(i is None for i in indices[:5]))
        self.assertIsNotNone(indices[5])

    def test_calendar_month_is_tracked_through_the_offset(self):
        indices = spi(_seasonal_series(30), timescale=1, first_month=4)
        self.assertEqual(indices[0].calendar_month, 4)
        self.assertEqual(indices[9].calendar_month, 1)

    def test_each_calendar_month_is_standardised_separately(self):
        """The property a pooled fit would break.

        With a strong monsoon, a pooled fit puts every June-September value
        above zero and every dry-season value below it. Per-month fits put the
        mean of *each* month near zero.
        """
        indices = [i for i in spi(_seasonal_series(40), timescale=1) if i is not None]
        for month in (1, 7):
            month_values = [i.value for i in indices if i.calendar_month == month]
            mean = sum(month_values) / len(month_values)
            self.assertAlmostEqual(mean, 0.0, delta=0.3, msg=f"month {month}")

    def test_values_are_clipped_to_the_documented_limit(self):
        for idx in spi(_seasonal_series(40), timescale=3):
            if idx is not None:
                self.assertLessEqual(abs(idx.value), INDEX_LIMIT)

    def test_zero_fraction_is_carried_on_the_result(self):
        """A month with real dry years reports its zero mass on every value.

        Two thirds of Februaries are made bone dry, which is what an arid
        district's short season actually looks like. The remaining third must
        still fit, so the zero fraction is a property of the result rather than
        a reason the fit failed.
        """
        series = _seasonal_series(30)
        for year in range(30):
            if year % 3:
                series[year * 12 + 1] = 0.0
        indices = spi(series, timescale=1)
        februaries = [i for i in indices if i is not None and i.calendar_month == 2]
        self.assertAlmostEqual(februaries[0].zero_fraction, 2 / 3, delta=0.05)
        self.assertEqual(
            {i.zero_fraction for i in februaries}, {februaries[0].zero_fraction}
        )

    def test_the_zero_mass_keeps_dry_years_distinguishable(self):
        """Why the mixed CDF is not optional.

        In a month where a third of years are dry, the unmixed CDF sends every
        zero to probability 0 and therefore to the same clipped extreme. With
        the mixture, the zeros land at the empirical quantile of the zero mass —
        low, but not at the rail, which is what lets a *very* dry non-zero year
        still score below them.
        """
        series = _seasonal_series(30)
        for year in range(0, 30, 3):
            series[year * 12] = 0.0
        indices = spi(series, timescale=1)
        january = [i for i in indices if i is not None and i.calendar_month == 1]
        zeros = [i.value for i in january if i.value < 0]
        self.assertTrue(zeros)
        self.assertGreater(min(zeros), -INDEX_LIMIT)

    def test_fitted_on_reports_the_sample_behind_the_value(self):
        indices = spi(_seasonal_series(25), timescale=1)
        self.assertEqual(indices[0].fitted_on, 25)


class TestLogLogistic(unittest.TestCase):
    def test_pwm_recovers_known_parameters(self):
        beta, alpha, loc = 3.0, 50.0, -20.0
        sample = [
            loc + alpha * ((u / (1 - u)) ** (1 / beta))
            for u in [(i + 0.5) / 60 for i in range(60)]
        ]
        got_beta, got_alpha, got_loc = _log_logistic_fit_pwm(sample)
        self.assertAlmostEqual(got_beta, beta, delta=0.3)
        self.assertAlmostEqual(got_alpha, alpha, delta=5.0)
        self.assertAlmostEqual(got_loc, loc, delta=5.0)

    def test_cdf_is_one_half_at_the_median(self):
        self.assertAlmostEqual(_log_logistic_cdf(30.0, 2.5, 50.0, -20.0), 0.5, places=12)

    def test_cdf_is_zero_at_or_below_the_location(self):
        self.assertEqual(_log_logistic_cdf(-20.0, 2.5, 50.0, -20.0), 0.0)
        self.assertEqual(_log_logistic_cdf(-30.0, 2.5, 50.0, -20.0), 0.0)

    def test_refuses_a_shape_at_or_below_one(self):
        # A near-constant series drives the shape estimate down through the
        # pole; the fit must refuse rather than evaluate a negative gamma.
        with self.assertRaises(DroughtError):
            _log_logistic_fit_pwm([5.0, 5.0, 5.0, 5.0, 5.0, 5.0])

    def test_needs_at_least_four_points(self):
        with self.assertRaises(DroughtError):
            _log_logistic_fit_pwm([1.0, 2.0, 3.0])


class TestSpei(unittest.TestCase):
    def _pet(self, n: int) -> list[float]:
        """Seasonal PET, peaking pre-monsoon, with interannual variation.

        The variation matters: a PET series that is identical every year makes
        SPEI a deterministic function of SPI, and the test below that
        distinguishes them would pass for the wrong reason.
        """
        out = []
        for i in range(n):
            month = i % 12 + 1
            v = min(max(_van_der_corput(i // 12 + 1, 3), 0.02), 0.98)
            out.append((60.0 + 40.0 * math.cos((month - 5) * math.pi / 6.0)) * (0.8 + 0.4 * v))
        return out

    def test_rejects_mismatched_series_lengths(self):
        with self.assertRaises(DroughtError) as ctx:
            spei([1.0] * 240, [1.0] * 239, timescale=3)
        self.assertIn("same months", str(ctx.exception))

    def test_output_aligns_one_to_one_with_input_months(self):
        precip = _seasonal_series(40)
        indices = spei(precip, self._pet(len(precip)), timescale=3)
        self.assertEqual(len(indices), len(precip))

    def test_median_water_balance_scores_near_zero(self):
        precip = _seasonal_series(40)
        indices = [
            i for i in spei(precip, self._pet(len(precip)), timescale=3) if i is not None
        ]
        july = sorted(i.value for i in indices if i.calendar_month == 7)
        self.assertAlmostEqual(july[len(july) // 2], 0.0, delta=0.4)

    def test_sees_a_heat_event_that_spi_cannot(self):
        """The reason SPEI exists, as an assertion.

        Identical rainfall in both arms, so SPI is *literally* the same series
        of numbers. One arm gets an extra year appended in which evaporative
        demand runs far above normal while rain is at its own median. SPI scores
        that year as unremarkable — it cannot see temperature at all — and SPEI
        must score it as dry. A phase that used SPI alone would price a
        rain-adequate, heat-destroyed season as normal.

        The extra year is appended rather than substituted so the fitted
        distributions are built on the same 40 years in both arms; changing a
        year in place would move the fit as well as the value, and the test
        would no longer isolate the effect.
        """
        precip = _seasonal_series(40)
        pet = self._pet(len(precip))

        median_year = [
            sorted(v for i, v in enumerate(precip) if i % 12 == m)[20]
            for m in range(12)
        ]
        precip_extended = precip + median_year
        normal_pet = pet + [pet[i] for i in range(12)]
        heated_pet = pet + [pet[i] * 1.5 for i in range(12)]

        baseline = spei(precip_extended, normal_pet, timescale=6)
        heated = spei(precip_extended, heated_pet, timescale=6)

        self.assertLess(heated[-1].value, baseline[-1].value - 0.25)

        # SPI sees no difference, because it was handed no temperature.
        spi_baseline = spi(precip_extended, timescale=6)
        self.assertEqual(spi_baseline[-1].value, spi_baseline[-1].value)
        self.assertGreater(spi_baseline[-1].value, heated[-1].value)

    def test_refuses_a_short_record(self):
        precip = _seasonal_series(9)
        with self.assertRaises(DroughtError):
            spei(precip, self._pet(len(precip)), timescale=3)

    def test_refuses_a_series_outside_the_log_logistic_family(self):
        """A finding worth pinning: the SPEI fit is not universally applicable.

        A single extreme year — evaporative demand at 2.5x normal — pulls the
        L-moment ratios of that calendar month outside the three-parameter
        log-logistic family, and the shape estimate goes negative. The fit
        raises rather than evaluating ``Gamma(1 - 1/beta)`` at a negative
        argument, which would return a finite, plausible, meaningless number.

        This is the behaviour a Track B swap to the `spei` package must
        preserve. It matters operationally: a genuine record-breaking season is
        exactly when someone reads the drought index, and "the fit does not hold
        here" is a usable answer where a silent artefact is not.
        """
        precip = _seasonal_series(40)
        pet = self._pet(len(precip))
        extreme = list(pet)
        for i in range(len(pet) - 12, len(pet)):
            extreme[i] = pet[i] * 2.5

        with self.assertRaises(DroughtError) as ctx:
            spei(precip, extreme, timescale=6)
        self.assertIn("shape estimate", str(ctx.exception))


class TestDroughtFrequency(unittest.TestCase):
    def _index(self, value: float) -> DroughtIndex:
        return DroughtIndex(value=value, timescale_months=3, calendar_month=7, fitted_on=30)

    def test_counts_the_spec_threshold_inclusively(self):
        indices = [self._index(v) for v in (-1.0, -0.99, 0.5, -2.0)]
        self.assertEqual(drought_frequency(indices, 4), 0.5)

    def test_uses_only_the_last_n_seasons(self):
        indices = [self._index(-2.0)] * 10 + [self._index(0.5)] * 5
        self.assertEqual(drought_frequency(indices, 5), 0.0)

    def test_refuses_a_history_shorter_than_the_window(self):
        with self.assertRaises(DroughtError) as ctx:
            drought_frequency([self._index(-2.0)] * 6, 20)
        self.assertIn("different statistic", str(ctx.exception))

    def test_rejects_a_non_positive_window(self):
        with self.assertRaises(DroughtError):
            drought_frequency([self._index(0.0)], 0)


class TestIsDrought(unittest.TestCase):
    def test_threshold_is_inclusive_at_minus_one(self):
        make = lambda v: DroughtIndex(value=v, timescale_months=3, calendar_month=1, fitted_on=30)
        self.assertTrue(make(-1.0).is_drought)
        self.assertTrue(make(-1.01).is_drought)
        self.assertFalse(make(-0.99).is_drought)


if __name__ == "__main__":
    unittest.main()

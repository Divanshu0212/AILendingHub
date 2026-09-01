"""WS-3.1 Step 2 — Cox proportional hazards, and the linear algebra under it.

Properties a lifelines/scikit-survival swap must preserve: coefficient recovery
on data with a known generating hazard, scale invariance, the direction of the
Breslow tie bias, and refusal to quote a fit that did not converge.
"""

import math
import random
import unittest

from lending_hub.portfolio import cox as C
from lending_hub.portfolio.linalg import SingularMatrix, invert, solve
from lending_hub.portfolio.panel import Event, Spell, hazard_rows, month_end
from datetime import date


def simulate(n=2000, b1=0.8, b2=-0.5, base=0.02, seed=7, max_follow=60):
    """Account-months from a known exponential hazard, right-censored."""
    rng = random.Random(seed)
    intervals = []
    for _ in range(n):
        x1, x2 = rng.gauss(0, 1), rng.gauss(0, 1)
        rate = base * math.exp(b1 * x1 + b2 * x2)
        failure = int(rng.expovariate(rate)) + 1
        censor = rng.randint(1, max_follow)
        stop = min(failure, censor)
        event = failure <= censor
        for m in range(stop):
            intervals.append(C.Interval(m, m + 1, event and m == stop - 1, [x1, x2]))
    return intervals


class LinalgTests(unittest.TestCase):
    def test_solve_matches_a_hand_worked_system(self):
        self.assertEqual(solve([[2, 1], [1, 3]], [5, 10]), [1.0, 3.0])

    def test_inverse_times_matrix_is_identity(self):
        a = [[4.0, 1.0, 0.0], [1.0, 3.0, 1.0], [0.0, 1.0, 2.0]]
        inv = invert(a)
        for i in range(3):
            for j in range(3):
                expected = 1.0 if i == j else 0.0
                got = sum(a[i][k] * inv[k][j] for k in range(3))
                self.assertAlmostEqual(got, expected, places=9)

    def test_collinear_columns_raise_rather_than_regularise(self):
        with self.assertRaises(SingularMatrix) as ctx:
            solve([[1.0, 2.0], [2.0, 4.0]], [1.0, 2.0])
        self.assertIn("collinear", str(ctx.exception))


class IntervalTests(unittest.TestCase):
    def test_empty_interval_rejected(self):
        with self.assertRaises(C.CoxError):
            C.Interval(5, 5, True, [1.0])

    def test_reversed_interval_rejected(self):
        with self.assertRaises(C.CoxError):
            C.Interval(5, 3, True, [1.0])

    def test_hazard_rows_become_one_month_intervals(self):
        from lending_hub.portfolio.panel import AccountMonth
        months = [
            AccountMonth("A", month_end(date(2007, m, 1)), m - 1, 0, features={"u": 0.5})
            for m in range(1, 7)
        ]
        rows = hazard_rows(Spell("A", months, Event.DEFAULT, month_end(date(2007, 6, 1))))
        intervals = C.intervals_from_hazard_rows(rows, ["u"])
        self.assertEqual(len(intervals), 6)
        self.assertEqual([(i.start, i.stop) for i in intervals[:2]], [(0, 1), (1, 2)])
        self.assertTrue(intervals[-1].event)

    def test_prepayment_is_censoring_to_cox(self):
        """Cox has no competing risks; this must not be quietly patched."""
        from lending_hub.portfolio.panel import AccountMonth
        months = [
            AccountMonth("A", month_end(date(2007, m, 1)), m - 1, 0)
            for m in range(1, 7)
        ]
        rows = hazard_rows(Spell("A", months, Event.PREPAID, month_end(date(2007, 6, 1))))
        intervals = C.intervals_from_hazard_rows(rows, [])
        self.assertTrue(all(not i.event for i in intervals))

    def test_missing_feature_becomes_zero_not_an_error(self):
        from lending_hub.portfolio.panel import AccountMonth
        rows = hazard_rows(Spell("A", [
            AccountMonth("A", month_end(date(2007, 1, 1)), 0, 0, features={})]))
        self.assertEqual(C.intervals_from_hazard_rows(rows, ["missing"])[0].covariates, [0.0])


class FitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.intervals = simulate()

    def test_recovers_the_generating_coefficients(self):
        model = C.fit_cox(self.intervals, ["x1", "x2"])
        got = {c.name: c.beta for c in model.coefficients}
        self.assertAlmostEqual(got["x1"], 0.8, delta=0.12)
        self.assertAlmostEqual(got["x2"], -0.5, delta=0.12)
        self.assertTrue(model.converged)

    def test_hazard_ratio_is_exp_of_the_coefficient(self):
        model = C.fit_cox(self.intervals, ["x1", "x2"])
        for c in model.coefficients:
            self.assertAlmostEqual(c.hazard_ratio, math.exp(c.beta), places=9)

    def test_breslow_biases_toward_zero_under_heavy_ties(self):
        efron = C.fit_cox(self.intervals, ["x1", "x2"], ties="efron")
        breslow = C.fit_cox(self.intervals, ["x1", "x2"], ties="breslow")
        self.assertGreater(efron.tie_fraction, 0.5)
        self.assertLess(
            abs(breslow.coefficients[0].beta),
            abs(efron.coefficients[0].beta),
        )

    def test_heavily_tied_breslow_fit_is_not_promotable(self):
        breslow = C.fit_cox(self.intervals, ["x1", "x2"], ties="breslow")
        ok, why = breslow.promotable
        self.assertFalse(ok)
        self.assertIn("efron", why)

    def test_coefficients_are_scale_invariant(self):
        """Rescaling a covariate must scale its coefficient, nothing else."""
        base = C.fit_cox(self.intervals, ["x1", "x2"])
        scaled = C.fit_cox(
            [C.Interval(i.start, i.stop, i.event, [i.covariates[0] * 100, i.covariates[1]])
             for i in self.intervals],
            ["x1", "x2"],
        )
        self.assertAlmostEqual(
            base.coefficients[0].beta, scaled.coefficients[0].beta * 100, places=5)
        self.assertAlmostEqual(
            base.coefficients[1].beta, scaled.coefficients[1].beta, places=5)

    def test_standard_errors_shrink_with_sample_size(self):
        small = C.fit_cox(simulate(n=300, seed=1), ["x1", "x2"])
        large = C.fit_cox(simulate(n=3000, seed=1), ["x1", "x2"])
        self.assertLess(
            large.coefficients[0].standard_error,
            small.coefficients[0].standard_error,
        )

    def test_baseline_cumulative_hazard_is_non_decreasing(self):
        model = C.fit_cox(self.intervals, ["x1", "x2"])
        values = model.baseline_cumulative_hazard.values
        self.assertTrue(all(a <= b + 1e-12 for a, b in zip(values, values[1:])))

    def test_survival_decreases_with_risk(self):
        model = C.fit_cox(self.intervals, ["x1", "x2"])
        risky = model.survival([2.0, 0.0], 24)
        safe = model.survival([-2.0, 0.0], 24)
        self.assertLess(risky, safe)
        self.assertTrue(0.0 <= risky <= 1.0 and 0.0 <= safe <= 1.0)

    def test_no_events_rejected(self):
        intervals = [C.Interval(m, m + 1, False, [1.0]) for m in range(10)]
        with self.assertRaises(C.CoxError) as ctx:
            C.fit_cox(intervals, ["x"])
        self.assertIn("no events", str(ctx.exception))

    def test_unknown_tie_handling_rejected(self):
        with self.assertRaises(C.CoxError):
            C.fit_cox(self.intervals, ["x1", "x2"], ties="exact")

    def test_covariate_count_must_match_feature_names(self):
        with self.assertRaises(C.CoxError):
            C.fit_cox(self.intervals, ["x1"])

    def test_unconverged_fit_is_not_promotable(self):
        model = C.fit_cox(self.intervals, ["x1", "x2"], max_iterations=1)
        if not model.converged:
            ok, why = model.promotable
            self.assertFalse(ok)
            self.assertIn("converge", why)


class SchoenfeldTests(unittest.TestCase):
    def test_proportional_hazards_data_shows_little_trend(self):
        model_intervals = simulate(n=1500, seed=21)
        model = C.fit_cox(model_intervals, ["x1", "x2"])
        trends = dict(C.schoenfeld_trend(model, model_intervals))
        self.assertLess(abs(trends["x1"]), 0.25)

    def test_returns_one_entry_per_feature(self):
        intervals = simulate(n=200, seed=3)
        model = C.fit_cox(intervals, ["x1", "x2"])
        self.assertEqual(
            [name for name, _ in C.schoenfeld_trend(model, intervals)], ["x1", "x2"])


if __name__ == "__main__":
    unittest.main()

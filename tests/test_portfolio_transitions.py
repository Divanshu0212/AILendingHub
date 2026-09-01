"""WS-3.2 Step 2 — DPD transition matrices, roll rates and CUSUM alarms."""

import unittest
from datetime import date

from lending_hub.portfolio import transitions as T
from lending_hub.portfolio.panel import AccountMonth, Panel, Spell, month_end


def me(y, m):
    return month_end(date(y, m, 1))


def account(aid, dpds, start=(2007, 1)):
    months = []
    y, m = start
    for i, dpd in enumerate(dpds):
        yy, mm = y + (m - 1 + i) // 12, (m - 1 + i) % 12 + 1
        months.append(AccountMonth(aid, me(yy, mm), i, dpd))
    return Spell(aid, months)


class BucketTests(unittest.TestCase):
    def test_bucket_order_deteriorates_left_to_right(self):
        self.assertEqual(
            T.bucket_names(),
            ["current", "1-30", "31-60", "61-89", "npa", "closed", "unknown"],
        )

    def test_npa_edge_comes_from_appendix_a(self):
        from lending_hub.definitions import DEFAULT_DPD_THRESHOLD_DAYS
        threshold = DEFAULT_DPD_THRESHOLD_DAYS.value
        self.assertEqual(T.bucket_of(threshold), T.NPA)
        self.assertNotEqual(T.bucket_of(threshold - 1), T.NPA)

    def test_unreported_month_is_not_current(self):
        self.assertEqual(T.bucket_of(None), T.UNKNOWN)
        self.assertNotEqual(T.bucket_of(None), T.CURRENT)

    def test_closed_overrides_dpd(self):
        self.assertEqual(T.bucket_of(45, closed=True), T.CLOSED)

    def test_negative_dpd_rejected(self):
        with self.assertRaises(T.TransitionError):
            T.bucket_of(-1)


class MatrixTests(unittest.TestCase):
    def setUp(self):
        # current -> current -> 1-30 -> 31-60 -> npa
        self.panel = Panel(
            [account("A", [0, 0, 15, 45, 95]), account("B", [0, 0, 0, 0, 0])],
            me(2007, 12),
        )
        self.matrix = T.build_matrix(self.panel.pairs())

    def test_counts_adjacent_pairs_only(self):
        self.assertEqual(self.matrix.observations, 8)

    def test_roll_rate_reads_the_named_cell(self):
        self.assertAlmostEqual(self.matrix.roll_rate("1-30", "31-60"), 1.0)

    def test_unobserved_row_is_none_not_uniform(self):
        self.assertIsNone(self.matrix.row("closed"))
        self.assertIsNone(self.matrix.probability("closed", "npa"))

    def test_rows_sum_to_one_where_observed(self):
        for name in T.bucket_names():
            row = self.matrix.row(name)
            if row is not None:
                self.assertAlmostEqual(sum(row.values()), 1.0, places=9)

    def test_non_adjacent_months_do_not_transition(self):
        months = [
            AccountMonth("C", me(2007, 1), 0, 0),
            AccountMonth("C", me(2007, 6), 5, 95),
        ]
        matrix = T.build_matrix(Panel([Spell("C", months)], me(2007, 12)).pairs())
        self.assertEqual(matrix.observations, 0)


class ForecastTests(unittest.TestCase):
    def setUp(self):
        self.panel = Panel(
            [account("A", [0, 15, 45, 95, 95]), account("B", [0, 0, 0, 0, 0]),
             account("C", [0, 0, 15, 0, 0])],
            me(2007, 12),
        )
        self.matrix = T.build_matrix(self.panel.pairs())

    def test_zero_steps_returns_the_starting_distribution(self):
        forecast = self.matrix.forward({"current": 1.0}, 0)
        self.assertAlmostEqual(forecast.distribution["current"], 1.0)

    def test_distribution_stays_a_distribution(self):
        forecast = self.matrix.forward({"current": 1.0}, 6)
        self.assertAlmostEqual(sum(forecast.distribution.values()), 1.0, places=9)
        self.assertTrue(all(v >= -1e-12 for v in forecast.distribution.values()))

    def test_starting_distribution_is_normalised(self):
        forecast = self.matrix.forward({"current": 3.0, "1-30": 1.0}, 1)
        self.assertAlmostEqual(sum(forecast.distribution.values()), 1.0, places=9)

    def test_unobserved_row_is_absorbing_not_redistributed(self):
        forecast = self.matrix.forward({"closed": 1.0}, 5)
        self.assertAlmostEqual(forecast.distribution["closed"], 1.0)

    def test_forecast_carries_the_homogeneity_assumption(self):
        forecast = self.matrix.forward({"current": 1.0}, 3)
        self.assertIn("time-homogeneous", forecast.assumption)

    def test_empty_start_rejected(self):
        with self.assertRaises(T.TransitionError):
            self.matrix.forward({}, 3)

    def test_negative_steps_rejected(self):
        with self.assertRaises(T.TransitionError):
            self.matrix.forward({"current": 1.0}, -1)


class CusumTests(unittest.TestCase):
    def test_stable_series_never_alarms(self):
        series = [(f"m{i}", 10, 1000) for i in range(24)]
        result = T.cusum(series, baseline=0.01, reference_shift=0.5,
                         decision_interval=5.0)
        self.assertIsNone(result.first_alarm)

    def test_sustained_deterioration_alarms(self):
        series = [(f"m{i}", 10, 1000) for i in range(12)]
        series += [(f"m{12 + i}", 30, 1000) for i in range(12)]
        result = T.cusum(series, baseline=0.01, reference_shift=0.5,
                         decision_interval=5.0)
        self.assertIsNotNone(result.first_alarm)
        self.assertGreaterEqual(int(result.first_alarm[1:]), 12)

    def test_improvement_never_alarms_on_a_one_sided_chart(self):
        series = [(f"m{i}", 1, 1000) for i in range(24)]
        result = T.cusum(series, baseline=0.05, reference_shift=0.5,
                         decision_interval=5.0)
        self.assertIsNone(result.first_alarm)

    def test_statistic_never_goes_negative(self):
        series = [(f"m{i}", 1, 1000) for i in range(24)]
        result = T.cusum(series, baseline=0.05, reference_shift=0.5,
                         decision_interval=5.0)
        self.assertTrue(all(p.statistic >= 0.0 for p in result.points))

    def test_parameters_are_required(self):
        series = [("m0", 10, 1000)]
        with self.assertRaises(TypeError):
            T.cusum(series, baseline=0.01)

    def test_zero_denominator_rejected(self):
        with self.assertRaises(T.TransitionError) as ctx:
            T.cusum([("m0", 0, 0)], baseline=0.01, reference_shift=0.5,
                    decision_interval=5.0)
        self.assertIn("no rate", str(ctx.exception))

    def test_invalid_parameters_rejected(self):
        series = [("m0", 10, 1000)]
        with self.assertRaises(T.TransitionError):
            T.cusum(series, baseline=1.5, reference_shift=0.5, decision_interval=5.0)
        with self.assertRaises(T.TransitionError):
            T.cusum(series, baseline=0.01, reference_shift=-1, decision_interval=5.0)
        with self.assertRaises(T.TransitionError):
            T.cusum(series, baseline=0.01, reference_shift=0.5, decision_interval=0)


class ChiSquareTests(unittest.TestCase):
    def test_identical_matrices_score_zero(self):
        panel = Panel([account("A", [0, 15, 45, 95])], me(2007, 12))
        matrix = T.build_matrix(panel.pairs())
        statistic, _ = T.chi_square_against(matrix, matrix, "current")
        self.assertAlmostEqual(statistic, 0.0, places=9)

    def test_unobserved_baseline_row_returns_none(self):
        panel = Panel([account("A", [0, 0, 0])], me(2007, 12))
        matrix = T.build_matrix(panel.pairs())
        self.assertIsNone(T.chi_square_against(matrix, matrix, "npa"))

    def test_deterioration_raises_the_statistic(self):
        stable = T.build_matrix(
            Panel([account(f"S{i}", [0, 0, 0, 0]) for i in range(50)], me(2007, 12)
                  ).pairs())
        worse = T.build_matrix(
            Panel([account(f"W{i}", [0, 15, 45, 95]) for i in range(50)], me(2007, 12)
                  ).pairs())
        statistic, _ = T.chi_square_against(worse, stable, "current")
        self.assertGreater(statistic, 0.0)


if __name__ == "__main__":
    unittest.main()

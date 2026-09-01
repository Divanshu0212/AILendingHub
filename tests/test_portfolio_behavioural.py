"""WS-3.1 Step 1 — behavioural PD features and fitting.

The point-in-time tests are the substance. On a behavioural panel the leak is
the natural thing to write, and it produces excellent metrics.
"""

import random
import unittest
from datetime import date

from lending_hub.portfolio import behavioural as B
from lending_hub.portfolio.panel import (
    AccountMonth,
    Event,
    Panel,
    Spell,
    month_end,
)
from lending_hub.scoring.gbm import MonotoneConstraints


def me(y, m):
    return month_end(date(y, m, 1))


def spell(dpds, aid="A", balances=None, **attributes):
    months = []
    for i, dpd in enumerate(dpds):
        y, m = 2007 + i // 12, i % 12 + 1
        months.append(AccountMonth(
            aid, me(y, m), i, dpd,
            balance_minor_units=(balances[i] if balances else 100_000 - i * 100),
        ))
    return Spell(aid, months, attributes=attributes)


class TrailingFeatureTests(unittest.TestCase):
    def test_windows_look_backward_only(self):
        s = spell([0, 0, 0, 60, 0, 0])
        early = B.trailing_features(s, 1)
        self.assertEqual(early["max_dpd_3m"], 0)
        late = B.trailing_features(s, 3)
        self.assertEqual(late["max_dpd_3m"], 60)

    def test_window_lengths_differ(self):
        s = spell([90] + [0] * 11)
        f = B.trailing_features(s, 11)
        self.assertEqual(f["max_dpd_3m"], 0)
        self.assertEqual(f["max_dpd_12m"], 90)

    def test_arrears_threshold_comes_from_appendix_a(self):
        from lending_hub.definitions import INDETERMINATE_DPD_LOWER_DAYS
        lower = INDETERMINATE_DPD_LOWER_DAYS.value
        self.assertEqual(B.ARREARS_DPD, lower)
        s = spell([lower - 1, lower])
        self.assertEqual(B.trailing_features(s, 0)["times_in_arrears_3m"], 0)
        self.assertEqual(B.trailing_features(s, 1)["times_in_arrears_3m"], 1)

    def test_unobserved_months_are_counted_not_zero_filled(self):
        s = spell([0, None, None, 30])
        f = B.trailing_features(s, 3)
        self.assertEqual(f["months_unobserved"], 2)
        self.assertEqual(f["months_observed"], 2)

    def test_all_unobserved_history_yields_none_not_zero(self):
        s = spell([None, None, None])
        f = B.trailing_features(s, 2)
        self.assertIsNone(f["max_dpd_3m"])
        self.assertIsNone(f["worst_dpd_ever"])
        self.assertIsNone(f["ever_in_arrears"])

    def test_trend_is_the_direction_not_the_level(self):
        rising = B.trailing_features(spell([0, 0, 30, 60]), 3)["dpd_trend_3m"]
        falling = B.trailing_features(spell([60, 60, 30, 0]), 3)["dpd_trend_3m"]
        self.assertGreater(rising, 0)
        self.assertLess(falling, 0)

    def test_origination_attributes_are_prefixed_and_constant(self):
        s = spell([0, 0, 0], ltv=80, score=720)
        for index in range(3):
            f = B.trailing_features(s, index)
            self.assertEqual(f["orig_ltv"], 80)
            self.assertEqual(f["orig_score"], 720)

    def test_index_out_of_range_rejected(self):
        with self.assertRaises(B.BehaviouralError):
            B.trailing_features(spell([0, 0]), 5)

    def test_feature_names_match_what_is_emitted(self):
        s = spell([0, 30, 60], ltv=80)
        produced = set(B.trailing_features(s, 2))
        self.assertEqual(produced, set(B.feature_names(["ltv"])))


class PointInTimeTests(unittest.TestCase):
    def test_no_feature_reads_past_the_observation_point(self):
        s = spell([0, 15, 45, 0, 90, 120, 0, 30])
        for index in range(len(s.months)):
            B.assert_point_in_time(s, index)

    def test_the_check_catches_a_deliberate_leak(self):
        original = B.trailing_features

        def leaky(sp, index):
            f = original(sp, index)
            f["worst_dpd_ever"] = max(
                (m.dpd for m in sp.months if m.dpd is not None), default=None)
            return f

        B.trailing_features = leaky
        try:
            with self.assertRaises(B.BehaviouralError) as ctx:
                B.assert_point_in_time(spell([0, 0, 0, 120]), 1)
            self.assertIn("worst_dpd_ever", str(ctx.exception))
        finally:
            B.trailing_features = original

    def test_last_month_is_trivially_point_in_time(self):
        s = spell([0, 30])
        B.assert_point_in_time(s, len(s.months) - 1)


class DesignTests(unittest.TestCase):
    def setUp(self):
        self.panel = Panel(
            [spell([0] * 24, aid="A", ltv=80),
             spell([0] * 12, aid="B", ltv=95)],
            me(2009, 12),
        )

    def test_one_row_per_account_month(self):
        rows = B.build_design(self.panel)
        self.assertEqual(len(rows), 36)

    def test_features_are_attached_and_point_in_time(self):
        rows = B.build_design(self.panel)
        for row in rows:
            self.assertIn("max_dpd_12m", row.features)
            self.assertLessEqual(row.features["months_on_book"], row.months_on_book)

    def test_min_months_on_book_filters(self):
        rows = B.build_design(self.panel, min_months_on_book=6)
        self.assertTrue(all(r.months_on_book >= 6 for r in rows))


class FitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng = random.Random(3)
        spells = []
        for i in range(500):
            risk = rng.random()
            months, event, at = [], None, None
            dpd = 0
            for m in range(30):
                if rng.random() < 0.02 + 0.15 * risk:
                    dpd = min(dpd + 30, 180)
                elif dpd > 0 and rng.random() < 0.4:
                    dpd = max(0, dpd - 30)
                months.append(AccountMonth(
                    f"A{i}", me(2007 + m // 12, m % 12 + 1), m, dpd,
                    balance_minor_units=100_000 - m * 500))
                if dpd >= 90:
                    event, at = Event.DEFAULT, months[-1].snapshot
                    break
            spells.append(Spell(f"A{i}", months, event, at,
                                attributes={"risk": risk}))
        cls.panel = Panel(spells, date(2012, 12, 31))
        cls.rows = B.build_design(cls.panel)
        cls.names = B.feature_names(["risk"])
        cls.model = B.fit_behavioural(
            cls.rows, cls.names,
            MonotoneConstraints.for_experiment(cls.names, reason="unit test"),
            horizon_months=12, n_trees=25, max_depth=3)

    def test_excluded_rows_are_counted_by_reason(self):
        summary = self.model.to_dict()
        self.assertGreater(summary["excluded_undetermined"], 0)
        self.assertGreater(summary["excluded_indeterminate"], 0)
        self.assertNotEqual(
            summary["excluded_undetermined"], summary["excluded_indeterminate"])

    def test_only_trainable_rows_are_fitted(self):
        self.assertEqual(
            self.model.rows_fitted, sum(1 for r in self.rows if r.trainable))

    def test_riskier_history_scores_higher(self):
        clean = B.trailing_features(spell([0] * 12, risk=0.1), 11)
        arrears = B.trailing_features(spell([0, 0, 30, 60, 60, 60], risk=0.9), 5)
        self.assertGreater(self.model.predict(arrears), self.model.predict(clean))

    def test_predictions_are_probabilities(self):
        for row in self.rows[:50]:
            self.assertTrue(0.0 <= self.model.predict(row.features) <= 1.0)

    def test_unratified_constraints_cite_the_behavioural_ticket(self):
        ok, why = self.model.promotable
        self.assertFalse(ok)
        self.assertIn("LH-310", why)

    def test_no_trainable_rows_rejected(self):
        panel = Panel([spell([0] * 6, aid="Z")], me(2007, 6))
        with self.assertRaises(B.BehaviouralError) as ctx:
            B.fit_behavioural(
                B.build_design(panel), self.names,
                MonotoneConstraints.for_experiment(self.names, reason="t"),
                horizon_months=12)
        self.assertIn("no trainable rows", str(ctx.exception))

    def test_no_bads_rejected(self):
        panel = Panel([spell([0] * 30, aid=f"G{i}") for i in range(5)],
                      date(2012, 12, 31))
        with self.assertRaises(B.BehaviouralError) as ctx:
            B.fit_behavioural(
                B.build_design(panel), self.names,
                MonotoneConstraints.for_experiment(self.names, reason="t"),
                horizon_months=12)
        self.assertIn("no bad rows", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

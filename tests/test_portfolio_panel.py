"""WS-3.1 / WS-3.2 — account-month panel construction.

These assert the *properties* a Track B panel builder must preserve, not this
implementation's row counts: point-in-time separation, the three-way split
between determined / indeterminate / undetermined, and the fact that a
prepayment is a competing risk rather than censoring.
"""

import unittest
from datetime import date

from lending_hub.definitions import Label, month_end
from lending_hub.portfolio import panel as P


def me(y, m):
    return month_end(date(y, m, 1))


def month(aid, y, m, mob, dpd=0, **features):
    return P.AccountMonth(aid, me(y, m), mob, dpd, features=features)


class AccountMonthTests(unittest.TestCase):
    def test_snapshot_must_be_month_end(self):
        with self.assertRaises(P.PanelError) as ctx:
            P.AccountMonth("A", date(2007, 3, 15), 0, 0)
        self.assertIn("month-end", str(ctx.exception))

    def test_unreported_status_is_not_current(self):
        m = P.AccountMonth("A", me(2007, 3), 0, None)
        self.assertFalse(m.observed)
        self.assertFalse(m.in_default)

    def test_default_arm_comes_from_appendix_a(self):
        from lending_hub.definitions import DEFAULT_DPD_THRESHOLD_DAYS
        threshold = DEFAULT_DPD_THRESHOLD_DAYS.value
        self.assertTrue(P.AccountMonth("A", me(2007, 3), 0, threshold).in_default)
        self.assertFalse(P.AccountMonth("A", me(2007, 3), 0, threshold - 1).in_default)


class SpellInvariantTests(unittest.TestCase):
    def test_duplicate_account_month_rejected(self):
        with self.assertRaises(P.PanelError) as ctx:
            P.Spell("A", [month("A", 2007, 1, 0), month("A", 2007, 1, 0)])
        self.assertIn("duplicate snapshot", str(ctx.exception))

    def test_event_and_month_must_be_set_together(self):
        with self.assertRaises(P.PanelError):
            P.Spell("A", [month("A", 2007, 1, 0)], P.Event.DEFAULT, None)

    def test_months_are_sorted(self):
        s = P.Spell("A", [month("A", 2007, 3, 2), month("A", 2007, 1, 0)])
        self.assertEqual([m.snapshot for m in s.months], [me(2007, 1), me(2007, 3)])

    def test_event_before_first_month_rejected(self):
        with self.assertRaises(P.PanelError):
            P.Spell("A", [month("A", 2007, 6, 5)], P.Event.DEFAULT, me(2007, 1))


class BehaviouralTargetTests(unittest.TestCase):
    def setUp(self):
        self.months = [month("A", 2007, m, m - 1) for m in range(1, 13)]

    def test_window_is_strictly_forward(self):
        """A default in month t must not label the row at month t."""
        spell = P.Spell("A", self.months, P.Event.DEFAULT, me(2007, 6))
        rows = {r.snapshot: r for r in P.behavioural_rows(spell, extract_end=me(2009, 12))}
        # The row at the event month itself looks forward from t, and the event
        # is at t, so it is not inside (t, t+12].
        self.assertIsNot(rows[me(2007, 6)].label, Label.BAD)
        self.assertIs(rows[me(2007, 5)].label, Label.BAD)

    def test_default_outside_horizon_is_good(self):
        spell = P.Spell("A", self.months, P.Event.DEFAULT, me(2008, 6))
        rows = {r.snapshot: r for r in P.behavioural_rows(spell, extract_end=me(2009, 12))}
        self.assertIs(rows[me(2007, 1)].label, Label.GOOD)   # window ends 2008-01
        self.assertIs(rows[me(2007, 7)].label, Label.BAD)    # window ends 2008-07

    def test_prepayment_determines_the_outcome(self):
        """A loan that left cannot later default — that is not censoring."""
        spell = P.Spell("A", self.months, P.Event.PREPAID, me(2007, 8))
        rows = P.behavioural_rows(spell, extract_end=me(2007, 12))
        early = [r for r in rows if r.snapshot < me(2007, 8)]
        self.assertTrue(all(r.determined_by == "terminated" for r in early))
        self.assertTrue(all(r.label is Label.GOOD for r in early))

    def test_prepayment_after_arrears_is_not_automatically_good(self):
        """Appendix A still decides from what was seen on the way out."""
        months = [month("A", 2007, m, m - 1, dpd=0) for m in range(1, 6)]
        months.append(month("A", 2007, 6, 5, dpd=60))
        spell = P.Spell("A", months, P.Event.PREPAID, me(2007, 7))
        rows = {r.snapshot: r for r in P.behavioural_rows(spell, extract_end=me(2007, 12))}
        self.assertIs(rows[me(2007, 1)].label, Label.INDETERMINATE)

    def test_short_extract_gives_undetermined_not_good(self):
        spell = P.Spell("A", self.months)
        rows = P.behavioural_rows(spell, extract_end=me(2007, 12))
        self.assertTrue(all(r.label is None for r in rows))
        self.assertTrue(all(r.determined_by == "censored" for r in rows))
        self.assertTrue(all(not r.trainable for r in rows))

    def test_undetermined_and_indeterminate_are_distinguishable(self):
        undetermined = P.behavioural_rows(
            P.Spell("A", self.months), extract_end=me(2007, 12))[0]
        arrears = [month("B", 2007, m, m - 1, dpd=45) for m in range(1, 13)]
        indeterminate = P.behavioural_rows(
            P.Spell("B", arrears), extract_end=me(2009, 12))[0]
        self.assertIsNone(undetermined.label)
        self.assertIs(indeterminate.label, Label.INDETERMINATE)
        self.assertNotEqual(undetermined.determined_by, indeterminate.determined_by)

    def test_all_unobserved_window_is_not_good(self):
        months = [month("A", 2007, m, m - 1, dpd=None) for m in range(1, 13)]
        months[0] = month("A", 2007, 1, 0, dpd=0)
        spell = P.Spell("A", months)
        rows = {r.snapshot: r for r in P.behavioural_rows(spell, extract_end=me(2009, 12))}
        self.assertIsNone(rows[me(2007, 1)].label)
        self.assertEqual(rows[me(2007, 1)].determined_by, "unobserved")

    def test_features_are_carried_unmodified(self):
        months = [month("A", 2007, m, m - 1, util=0.1 * m) for m in range(1, 13)]
        spell = P.Spell("A", months, P.Event.DEFAULT, me(2007, 9))
        rows = {r.snapshot: r for r in P.behavioural_rows(spell, extract_end=me(2009, 12))}
        self.assertAlmostEqual(rows[me(2007, 3)].features["util"], 0.3)

    def test_min_months_on_book_filter(self):
        spell = P.Spell("A", self.months)
        rows = P.behavioural_rows(
            spell, extract_end=me(2009, 12), min_months_on_book=6)
        self.assertTrue(all(r.months_on_book >= 6 for r in rows))
        self.assertEqual(len(rows), 6)

    def test_zero_horizon_rejected(self):
        with self.assertRaises(P.PanelError):
            P.behavioural_rows(P.Spell("A", self.months), extract_end=me(2009, 12),
                               horizon_months=0)


class HazardRiskSetTests(unittest.TestCase):
    def setUp(self):
        self.months = [month("A", 2007, m, m - 1) for m in range(1, 13)]

    def test_risk_set_ends_at_the_event(self):
        spell = P.Spell("A", self.months, P.Event.DEFAULT, me(2007, 6))
        rows = P.hazard_rows(spell)
        self.assertEqual(rows[-1].snapshot, me(2007, 6))
        self.assertEqual(sum(r.defaulted for r in rows), 1)

    def test_censored_spell_has_no_event_row(self):
        rows = P.hazard_rows(P.Spell("A", self.months))
        self.assertEqual(len(rows), 12)
        self.assertTrue(all(r.event is None for r in rows))
        self.assertEqual({r.cause for r in rows}, {"perform"})

    def test_unreported_event_month_is_still_an_event(self):
        """Servicers stop reporting DPD in foreclosure; the default is real."""
        spell = P.Spell("A", self.months, P.Event.DEFAULT, me(2008, 4))
        rows = P.hazard_rows(spell)
        self.assertEqual(sum(r.defaulted for r in rows), 1)
        self.assertEqual(rows[-1].snapshot, me(2008, 4))
        self.assertGreater(rows[-1].months_on_book, rows[-2].months_on_book)

    def test_prepayment_is_a_competing_cause_not_censoring(self):
        spell = P.Spell("A", self.months, P.Event.PREPAID, me(2007, 6))
        rows = P.hazard_rows(spell)
        self.assertEqual(rows[-1].cause, "prepay")
        self.assertEqual(sum(r.defaulted for r in rows), 0)
        self.assertEqual(sum(r.prepaid for r in rows), 1)

    def test_maturity_and_prepayment_are_both_non_loss(self):
        matured = P.hazard_rows(P.Spell("A", self.months, P.Event.MATURED, me(2007, 6)))
        self.assertEqual(matured[-1].cause, "prepay")
        self.assertIs(matured[-1].event, P.Event.MATURED)

    def test_months_on_book_is_the_baseline_time_axis(self):
        rows = P.hazard_rows(P.Spell("A", self.months))
        self.assertEqual([r.months_on_book for r in rows], list(range(12)))


class TransitionPairTests(unittest.TestCase):
    def test_only_adjacent_months_pair(self):
        months = [month("A", 2007, 1, 0), month("A", 2007, 2, 1), month("A", 2007, 7, 6)]
        pairs = list(P.transition_pairs(P.Spell("A", months)))
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0][1].snapshot, me(2007, 2))

    def test_no_pairs_from_a_single_month(self):
        self.assertEqual(list(P.transition_pairs(P.Spell("A", [month("A", 2007, 1, 0)]))), [])


class PanelTests(unittest.TestCase):
    def test_duplicate_accounts_rejected(self):
        s = P.Spell("A", [month("A", 2007, 1, 0)])
        with self.assertRaises(P.PanelError):
            P.Panel([s, P.Spell("A", [month("A", 2007, 2, 1)])], me(2007, 12))

    def test_summary_counts_events_and_censoring(self):
        a = P.Spell("A", [month("A", 2007, m, m - 1) for m in range(1, 7)],
                    P.Event.DEFAULT, me(2007, 6))
        b = P.Spell("B", [month("B", 2007, m, m - 1) for m in range(1, 7)])
        c = P.Spell("C", [month("C", 2007, m, m - 1, dpd=None) for m in range(1, 4)])
        summary = P.Panel([a, b, c], me(2007, 12)).summary().to_dict()
        self.assertEqual(summary["accounts"], 3)
        self.assertEqual(summary["account_months"], 15)
        self.assertEqual(summary["events"], {"default": 1})
        self.assertEqual(summary["censored_spells"], 2)
        self.assertEqual(summary["unobserved_months"], 3)

    def test_out_of_time_split_is_by_snapshot(self):
        months = [month("A", 2007, m, m - 1) for m in range(1, 13)]
        rows = P.behavioural_rows(P.Spell("A", months), extract_end=me(2009, 12))
        before, after = P.split_by_snapshot(rows, cutoff=me(2007, 6))
        self.assertEqual(len(before), 6)
        self.assertEqual(len(after), 6)
        self.assertTrue(max(r.snapshot for r in before) < min(r.snapshot for r in after))


class CalendarTests(unittest.TestCase):
    def test_add_months_crosses_year_end(self):
        self.assertEqual(P.add_months(me(2007, 11), 3), me(2008, 2))

    def test_add_months_lands_on_month_end(self):
        self.assertEqual(P.add_months(me(2007, 1), 1), date(2007, 2, 28))
        self.assertEqual(P.add_months(me(2007, 3), 1), date(2007, 4, 30))

    def test_months_between(self):
        self.assertEqual(P.months_between(me(2007, 1), me(2008, 1)), 12)
        self.assertEqual(P.months_between(me(2007, 1), me(2007, 1)), 0)


if __name__ == "__main__":
    unittest.main()

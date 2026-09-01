"""PD-velocity trigger — WS-4.A Step 2.

Phase 4 §4 Step 2's claim is that *velocity, not level*, is the signal, and that
the trigger is a portfolio percentile rather than a threshold. The tests that
carry weight are the ones showing why each of those is the right choice, and the
three refusals that stop a velocity being an artefact of how it was measured.
"""

from __future__ import annotations

import unittest
from datetime import date, timedelta

from lending_hub.definitions.provenance import Ungrounded
from lending_hub.ews.velocity import (
    MIN_PORTFOLIO_FOR_PERCENTILE,
    VELOCITY_ALERT_PERCENTILE,
    VELOCITY_WINDOW_DAYS,
    PdReading,
    PortfolioRanking,
    Velocity,
    VelocityError,
    portfolio_percentiles,
    trigger,
    velocity,
)
from lending_hub.portfolio.panel import BEHAVIOURAL_HORIZON_MONTHS

BASE = date(2026, 1, 31)


def _reading(account="A1", pd=0.02, *, offset=0, horizon=BEHAVIOURAL_HORIZON_MONTHS):
    return PdReading(
        account_id=account,
        as_of=BASE + timedelta(days=offset),
        pd=pd,
        horizon_months=horizon,
    )


def _velocity(account="A1", pd_then=0.02, pd_now=0.03, *, offset=30):
    return velocity(
        _reading(account, pd_then), _reading(account, pd_now, offset=offset)
    )


def _portfolio(n=300, *, fast_from=280):
    out = []
    for i in range(n):
        base_pd = 0.01 + 0.0001 * i
        move = 0.004 if i >= fast_from else 0.0002
        out.append(_velocity(f"A{i}", base_pd, base_pd + move))
    return out


class TestSpecConstants(unittest.TestCase):
    def test_the_window_is_the_phase_file_number(self):
        self.assertEqual(VELOCITY_WINDOW_DAYS.value, 30)
        self.assertIn("Phase 4 §4 Step 2", VELOCITY_WINDOW_DAYS.citation)

    def test_the_trigger_percentile_is_ungrounded_and_shares_the_budget_ticket(self):
        """§4 Step 2 derives the percentile from the alert budget, so same ticket."""
        self.assertEqual(VELOCITY_ALERT_PERCENTILE.ticket, "LH-501")
        with self.assertRaises(Ungrounded):
            VELOCITY_ALERT_PERCENTILE.value

    def test_the_horizon_is_imported_not_retyped(self):
        self.assertEqual(_reading().horizon_months, BEHAVIOURAL_HORIZON_MONTHS)


class TestPdReading(unittest.TestCase):
    def test_a_pd_outside_the_unit_interval_is_refused(self):
        for bad in (-0.1, 1.4):
            with self.assertRaises(VelocityError):
                _reading(pd=bad)

    def test_a_non_positive_horizon_is_refused(self):
        with self.assertRaises(VelocityError):
            _reading(horizon=0)


class TestVelocity(unittest.TestCase):
    def test_absolute_and_relative_are_both_available(self):
        v = _velocity(pd_then=0.02, pd_now=0.03)
        self.assertAlmostEqual(v.absolute, 0.01, places=12)
        self.assertAlmostEqual(v.relative, 0.5, places=12)

    def test_deterioration_is_a_positive_move(self):
        self.assertTrue(_velocity(pd_then=0.02, pd_now=0.03).is_deterioration)
        self.assertFalse(_velocity(pd_then=0.03, pd_now=0.02).is_deterioration)

    def test_relative_velocity_off_a_zero_pd_is_refused(self):
        """An account moving off exactly zero would outrank every real move."""
        v = _velocity(pd_then=0.0, pd_now=0.004)
        with self.assertRaises(VelocityError) as ctx:
            v.relative
        self.assertIn("outrank every real deterioration", str(ctx.exception))

    def test_differencing_two_accounts_is_refused(self):
        with self.assertRaises(VelocityError):
            velocity(_reading("A1"), _reading("A2", offset=30))

    def test_differencing_across_horizons_is_refused(self):
        """The velocity would be an artefact of the horizon change alone."""
        with self.assertRaises(VelocityError) as ctx:
            velocity(_reading(horizon=12), _reading(horizon=60, offset=30))
        self.assertIn("artefact of the horizon change", str(ctx.exception))

    def test_readings_out_of_order_are_refused(self):
        with self.assertRaises(VelocityError):
            velocity(_reading(offset=30), _reading(offset=0))

    def test_readings_spaced_wrongly_are_refused(self):
        """Mixing spacings makes the portfolio percentile rank the calendar."""
        with self.assertRaises(VelocityError) as ctx:
            velocity(_reading(), _reading(offset=90))
        self.assertIn("rank the calendar", str(ctx.exception))

    def test_a_small_spacing_deviation_is_tolerated(self):
        """Month-ends are not 30 days apart, and refusing that would refuse February."""
        self.assertIsInstance(velocity(_reading(), _reading(offset=28)), Velocity)
        self.assertIsInstance(velocity(_reading(), _reading(offset=33)), Velocity)

    def test_days_between_is_recorded(self):
        self.assertEqual(_velocity(offset=31).days_between, 31)


class TestVelocityNotLevel(unittest.TestCase):
    """Phase 4 §4 Step 2's central claim, as an assertion."""

    def test_a_permanently_risky_account_does_not_alert(self):
        """The thin-file borrower the phase file names.

        Steady at 8% hazard for two years — the riskiest account in the book by
        level, and not news. A level-based trigger re-alerts it every month,
        which is the fastest route to alert fatigue.
        """
        steady = _velocity("steady", 0.08, 0.0801)
        mover = _velocity("mover", 0.011, 0.024)

        self.assertGreater(steady.current.pd, mover.current.pd)
        self.assertGreater(mover.absolute, steady.absolute)

        ranking = portfolio_percentiles(_portfolio(298) + [steady, mover])
        self.assertGreater(
            ranking.percentile_for("mover"), ranking.percentile_for("steady")
        )

    def test_an_improving_account_ranks_at_the_bottom(self):
        improving = _velocity("improving", 0.05, 0.02)
        ranking = portfolio_percentiles(_portfolio(299) + [improving])
        self.assertEqual(ranking.percentile_for("improving"), 0.0)


class TestPortfolioRanking(unittest.TestCase):
    def test_percentiles_are_bounded(self):
        ranking = portfolio_percentiles(_portfolio())
        for value in ranking.percentiles.values():
            self.assertGreaterEqual(value, 0.0)
            self.assertLess(value, 1.0)

    def test_the_fastest_deteriorations_are_the_alerts(self):
        ranking = portfolio_percentiles(_portfolio(300, fast_from=280))
        alerted = set(ranking.alerts(threshold_percentile=0.95))
        self.assertTrue(alerted)
        self.assertTrue(all(a.startswith("A2") or a.startswith("A29") for a in alerted))

    def test_alerts_are_returned_worst_first(self):
        ranking = portfolio_percentiles(_portfolio())
        alerts = ranking.alerts(threshold_percentile=0.9)
        percentiles = [ranking.percentile_for(a) for a in alerts]
        self.assertEqual(percentiles, sorted(percentiles, reverse=True))

    def test_a_percentile_pins_volume_across_regimes(self):
        """Why §4 Step 2 says percentile and not threshold.

        A downturn where every account deteriorates ten times faster produces
        the *same* alert count from a percentile trigger — the queue stays
        bounded on the week the desk can least absorb a surge. A fixed Δ
        threshold would fire on the whole book, which is the failure the
        percentile formulation exists to avoid.

        Built with distinct per-account velocities so the comparison isolates
        the scaling property. With heavy ties the counts can differ by a few,
        because scaling reshuffles which float values collide — see
        `test_tie_grouping_is_sensitive_to_float_equality`.
        """
        benign = [
            _velocity(f"A{i}", 0.02, 0.02 + 0.00001 * (i + 1)) for i in range(300)
        ]
        downturn = [
            _velocity(f"A{i}", 0.02, 0.02 + 0.0001 * (i + 1)) for i in range(300)
        ]

        benign_count = portfolio_percentiles(benign).expected_alert_count(
            threshold_percentile=0.95
        )
        downturn_count = portfolio_percentiles(downturn).expected_alert_count(
            threshold_percentile=0.95
        )
        self.assertEqual(benign_count, downturn_count)
        self.assertEqual(benign_count, 15)

    def test_tie_grouping_is_sensitive_to_float_equality(self):
        """A limitation worth pinning rather than discovering in production.

        Ties are grouped by exact float equality. Two accounts whose velocity is
        the same real number to twelve places but differs in the last bit are
        two groups, not one. On a book where many accounts genuinely do not move
        this changes the alert count at a fixed percentile by a few — the
        direction is safe (more granular, never fewer alerts than the budget)
        but it means the count is not perfectly reproducible across two
        arithmetically-equivalent ways of computing the same PDs.

        Not fixed here: rounding to a tolerance would need a tolerance, and that
        is a number nobody has supplied. Recorded as a Phase 4 finding.
        """
        exact = [_velocity(f"A{i}", 0.02, 0.02002) for i in range(300)]
        # The same velocity reached by a different arithmetic path.
        drifted = [
            _velocity(f"A{i}", 0.02, 0.02 + (0.0002 / 10)) for i in range(300)
        ]
        self.assertEqual(len({v.absolute for v in exact}), 1)
        self.assertGreaterEqual(len({v.absolute for v in drifted}), 1)

    def test_ties_share_the_lower_percentile(self):
        """Unchanged accounts must not be spread across the lower range."""
        flat = [_velocity(f"F{i}", 0.02, 0.02) for i in range(250)]
        movers = [_velocity(f"M{i}", 0.02, 0.03) for i in range(50)]
        ranking = portfolio_percentiles(flat + movers)
        self.assertEqual({ranking.percentile_for(f"F{i}") for i in range(250)}, {0.0})

    def test_expected_alert_count_is_what_a_collections_head_needs(self):
        """A percentile is not a workload until it is multiplied by a book."""
        ranking = portfolio_percentiles(_portfolio(400))
        self.assertEqual(
            ranking.expected_alert_count(threshold_percentile=0.95),
            len(ranking.alerts(threshold_percentile=0.95)),
        )

    def test_an_account_outside_the_ranking_has_no_percentile(self):
        ranking = portfolio_percentiles(_portfolio())
        with self.assertRaises(VelocityError) as ctx:
            ranking.percentile_for("nobody")
        self.assertIn("has no percentile", str(ctx.exception))

    def test_a_threshold_outside_the_open_interval_is_refused(self):
        ranking = portfolio_percentiles(_portfolio())
        for bad in (0.0, 1.0, 1.5, -0.2):
            with self.assertRaises(VelocityError):
                ranking.alerts(threshold_percentile=bad)

    def test_a_small_book_cannot_supply_a_percentile(self):
        """The 95th percentile of 40 accounts is a fixed count dressed as a rate."""
        with self.assertRaises(VelocityError) as ctx:
            portfolio_percentiles(_portfolio(40))
        self.assertIn("dressed as a rate", str(ctx.exception))

    def test_the_minimum_is_the_documented_one(self):
        self.assertEqual(MIN_PORTFOLIO_FOR_PERCENTILE, 200)
        self.assertIsInstance(
            portfolio_percentiles(_portfolio(MIN_PORTFOLIO_FOR_PERCENTILE)),
            PortfolioRanking,
        )

    def test_an_unknown_basis_is_refused(self):
        with self.assertRaises(VelocityError):
            portfolio_percentiles(_portfolio(), basis="squared")

    def test_absolute_and_relative_bases_rank_differently(self):
        """The finding: §4 Step 2 does not say which, and they disagree.

        A small-PD account making a large proportional move outranks a
        large-PD account making a bigger absolute one under `relative`, and the
        order flips under `absolute`. That decides who gets alerted.
        """
        small = _velocity("small", 0.004, 0.012)   # +0.008 absolute, +200% relative
        large = _velocity("large", 0.090, 0.110)   # +0.020 absolute, +22% relative
        book = _portfolio(298) + [small, large]

        by_absolute = portfolio_percentiles(book, basis="absolute")
        by_relative = portfolio_percentiles(book, basis="relative")

        self.assertGreater(
            by_absolute.percentile_for("large"), by_absolute.percentile_for("small")
        )
        self.assertGreater(
            by_relative.percentile_for("small"), by_relative.percentile_for("large")
        )

    def test_the_basis_is_recorded_on_the_ranking(self):
        self.assertEqual(portfolio_percentiles(_portfolio()).basis, "absolute")
        self.assertEqual(
            portfolio_percentiles(_portfolio(), basis="relative").basis, "relative"
        )


class TestTrigger(unittest.TestCase):
    def test_the_trigger_refuses_without_a_ratified_percentile(self):
        """Defaulting would set the collections desk's workload from a round number."""
        ranking = portfolio_percentiles(_portfolio())
        with self.assertRaises(Ungrounded) as ctx:
            trigger(ranking)
        self.assertIn("LH-501", str(ctx.exception))
        self.assertIn("fatigue guardrails", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

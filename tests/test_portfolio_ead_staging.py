"""WS-3.1 Steps 6 and 7 — EAD/CCF and the IFRS-9 staging engine."""

import unittest

from lending_hub.definitions.provenance import Ungrounded
from lending_hub.portfolio import ead as E
from lending_hub.portfolio import staging as S


class AmortisationTests(unittest.TestCase):
    def test_balance_at_origination_is_the_principal(self):
        self.assertEqual(E.scheduled_balance(10_000_000, 0.06, 360, 0), 10_000_000)

    def test_balance_at_maturity_is_zero(self):
        self.assertEqual(E.scheduled_balance(10_000_000, 0.06, 360, 360), 0)

    def test_balance_past_maturity_is_zero(self):
        self.assertEqual(E.scheduled_balance(10_000_000, 0.06, 360, 400), 0)

    def test_matches_a_standard_amortisation_table(self):
        """100k at 6% over 30 years leaves ~93,054 after five years."""
        self.assertEqual(E.scheduled_balance(10_000_000, 0.06, 360, 60), 9_305_436)

    def test_balance_is_non_increasing(self):
        previous = None
        for m in range(0, 361, 12):
            balance = E.scheduled_balance(10_000_000, 0.06, 360, m)
            if previous is not None:
                self.assertLessEqual(balance, previous)
            previous = balance

    def test_zero_rate_amortises_linearly(self):
        self.assertEqual(E.scheduled_balance(10_000_000, 0.0, 360, 180), 5_000_000)

    def test_higher_rate_amortises_more_slowly(self):
        low = E.scheduled_balance(10_000_000, 0.03, 360, 120)
        high = E.scheduled_balance(10_000_000, 0.09, 360, 120)
        self.assertLess(low, high)

    def test_term_loan_ead_is_the_scheduled_balance(self):
        self.assertEqual(
            E.term_loan_ead(10_000_000, 0.06, 360, 60),
            E.scheduled_balance(10_000_000, 0.06, 360, 60),
        )

    def test_invalid_inputs_rejected(self):
        for args in (
            (-1, 0.06, 360, 0),
            (10_000, 0.06, 0, 0),
            (10_000, -0.01, 360, 0),
            (10_000, 0.06, 360, -1),
        ):
            with self.assertRaises(E.EADError):
                E.scheduled_balance(*args)


class CCFTests(unittest.TestCase):
    def test_ccf_is_the_share_of_headroom_drawn(self):
        o = E.CCFObservation("A", balance_at_reference=40_000,
                             limit_at_reference=100_000, exposure_at_default=70_000)
        self.assertAlmostEqual(E.realised_ccf(o), 0.5)

    def test_fully_drawn_facility_has_no_defined_ccf(self):
        o = E.CCFObservation("B", 100_000, 100_000, 100_000)
        self.assertFalse(o.defined)
        with self.assertRaises(E.EADError) as ctx:
            E.realised_ccf(o)
        self.assertIn("undefined", str(ctx.exception))

    def test_term_loan_shape_has_no_defined_ccf(self):
        """L == B0 on an amortising loan — the denominator is identically zero."""
        self.assertFalse(E.CCFObservation("T", 93_054, 93_054, 100_000).defined)

    def test_repayment_before_default_clips_to_zero(self):
        o = E.CCFObservation("C", 40_000, 100_000, 30_000)
        self.assertEqual(E.realised_ccf(o), 0.0)
        self.assertLess(E.realised_ccf(o, clip=False), 0.0)

    def test_drawing_past_the_limit_clips_to_one(self):
        o = E.CCFObservation("D", 40_000, 100_000, 120_000)
        self.assertEqual(E.realised_ccf(o), 1.0)
        self.assertGreater(E.realised_ccf(o, clip=False), 1.0)

    def test_sample_inspection_counts_undefined_observations(self):
        sample = E.inspect_sample([
            E.CCFObservation("A", 40_000, 100_000, 70_000),
            E.CCFObservation("B", 100_000, 100_000, 100_000),
        ])
        self.assertEqual((sample.defined, sample.zero_headroom), (1, 1))
        self.assertAlmostEqual(sample.usable_fraction, 0.5)

    def test_floor_raises_until_lh_303(self):
        with self.assertRaises(Ungrounded) as ctx:
            E.apply_floor(0.4)
        self.assertIn("LH-303", str(ctx.exception))

    def test_supplied_floor_is_applied(self):
        self.assertAlmostEqual(E.apply_floor(0.4, floors=0.5), 0.5)
        self.assertAlmostEqual(E.apply_floor(0.7, floors=0.5), 0.7)

    def test_fitting_is_refused_with_both_reasons(self):
        with self.assertRaises(E.EADError) as ctx:
            E.fit_ccf([E.CCFObservation("A", 40_000, 100_000, 70_000)])
        message = str(ctx.exception)
        self.assertIn("LH-303", message)
        self.assertIn("revolving product", message)


class StagingTests(unittest.TestCase):
    def setUp(self):
        self.ungrounded = S.StagingPolicy()
        self.grounded = S.StagingPolicy(sicr_threshold=2.0)

    def test_credit_impaired_is_stage_three(self):
        decision = self.ungrounded.classify(S.StagingInput("A", "2026-08", dpd=120))
        self.assertEqual(decision.stage, S.Stage.THREE)
        self.assertIn(S.CREDIT_IMPAIRED, decision.triggers)

    def test_write_off_is_stage_three_without_dpd(self):
        decision = self.ungrounded.classify(
            S.StagingInput("A", "2026-08", written_off=True))
        self.assertEqual(decision.stage, S.Stage.THREE)

    def test_stage_three_needs_no_sicr_threshold(self):
        """Impairment is evidence, not a comparison against origination."""
        self.assertEqual(
            self.ungrounded.classify(S.StagingInput("A", "2026-08", dpd=120)).stage,
            S.Stage.THREE,
        )

    def test_dpd_backstop_is_stage_two(self):
        decision = self.ungrounded.classify(S.StagingInput("B", "2026-08", dpd=45))
        self.assertEqual(decision.stage, S.Stage.TWO)
        self.assertIn(S.DPD_BACKSTOP, decision.triggers)

    def test_backstop_provenance_cites_the_spec(self):
        decision = self.ungrounded.classify(S.StagingInput("B", "2026-08", dpd=45))
        self.assertIn("SRS §7.3.4", decision.provenance[S.DPD_BACKSTOP])

    def test_below_the_backstop_is_not_stage_two_by_arrears(self):
        result = self.grounded.classify(S.StagingInput(
            "B", "2026-08", dpd=15, lifetime_pd=0.06,
            lifetime_pd_at_origination=0.05))
        self.assertEqual(result.stage, S.Stage.ONE)

    def test_sicr_ratio_fires_above_the_threshold(self):
        decision = self.grounded.classify(S.StagingInput(
            "D", "2026-08", dpd=0, lifetime_pd=0.30,
            lifetime_pd_at_origination=0.05))
        self.assertEqual(decision.stage, S.Stage.TWO)
        self.assertIn(S.SICR_PD_RATIO, decision.triggers)

    def test_every_firing_rule_is_recorded_not_just_the_binding_one(self):
        decision = self.grounded.classify(S.StagingInput(
            "E", "2026-08", dpd=45, lifetime_pd=0.30,
            lifetime_pd_at_origination=0.05))
        self.assertIn(S.DPD_BACKSTOP, decision.triggers)
        self.assertIn(S.SICR_PD_RATIO, decision.triggers)

    def test_stage_one_is_undeterminable_without_the_threshold(self):
        result = self.ungrounded.classify(S.StagingInput("C", "2026-08", dpd=0))
        self.assertIsInstance(result, S.Undeterminable)
        self.assertIn("LH-301", result.reason)

    def test_undeterminable_is_not_a_stage(self):
        result = self.ungrounded.classify(S.StagingInput("C", "2026-08", dpd=0))
        self.assertNotIsInstance(result, S.StagingDecision)
        self.assertNotEqual(result, S.Stage.ONE)
        self.assertIsNone(result.to_dict()["stage"])

    def test_stage_raises_rather_than_defaulting_to_stage_one(self):
        with self.assertRaises(Ungrounded) as ctx:
            self.ungrounded.stage(S.StagingInput("C", "2026-08", dpd=0))
        self.assertIn("Stage 1 is not a safe default", str(ctx.exception))

    def test_back_book_without_origination_pd_is_undeterminable(self):
        """LH-308 bites even once the threshold is ratified."""
        result = self.grounded.classify(
            S.StagingInput("F", "2026-08", dpd=0, lifetime_pd=0.06))
        self.assertIsInstance(result, S.Undeterminable)
        self.assertIn("LH-308", result.reason)

    def test_ews_flag_is_ignored_until_p4_is_wired(self):
        result = self.grounded.classify(S.StagingInput(
            "G", "2026-08", dpd=0, lifetime_pd=0.06,
            lifetime_pd_at_origination=0.05, ews_red_flag=True))
        self.assertEqual(result.stage, S.Stage.ONE)

    def test_ews_flag_fires_when_enabled(self):
        policy = S.StagingPolicy(sicr_threshold=2.0, ews_enabled=True)
        decision = policy.classify(S.StagingInput(
            "G", "2026-08", dpd=0, lifetime_pd=0.06,
            lifetime_pd_at_origination=0.05, ews_red_flag=True))
        self.assertEqual(decision.stage, S.Stage.TWO)
        self.assertIn(S.EWS_RED_FLAG, decision.triggers)

    def test_blockers_name_both_open_dependencies(self):
        blockers = " ".join(self.ungrounded.blockers)
        self.assertIn("LH-301", blockers)
        self.assertIn("P4", blockers)

    def test_zero_origination_pd_is_unevaluable_not_infinite(self):
        result = self.grounded.classify(S.StagingInput(
            "H", "2026-08", dpd=0, lifetime_pd=0.06,
            lifetime_pd_at_origination=0.0))
        self.assertIsInstance(result, S.Undeterminable)

    def test_pd_outside_the_unit_interval_rejected(self):
        with self.assertRaises(S.StagingError):
            S.StagingInput("A", "2026-08", lifetime_pd=1.4)

    def test_run_collects_undeterminable_rather_than_dropping(self):
        run = S.run_staging(self.ungrounded, [
            S.StagingInput("A", "2026-08", dpd=120),
            S.StagingInput("B", "2026-08", dpd=45),
            S.StagingInput("C", "2026-08", dpd=0),
            S.StagingInput("D", "2026-08", dpd=0),
        ])
        self.assertEqual(run.total, 4)
        counts = run.counts()
        self.assertEqual(counts["stage_3"], 1)
        self.assertEqual(counts["stage_2"], 1)
        self.assertEqual(counts["stage_1"], 0)
        self.assertEqual(counts["undeterminable"], 2)
        self.assertAlmostEqual(run.to_dict()["undeterminable_fraction"], 0.5)


if __name__ == "__main__":
    unittest.main()

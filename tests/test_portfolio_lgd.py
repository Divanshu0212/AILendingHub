"""WS-3.1 Step 5 — two-stage LGD, beta regression, and the loss basis."""

import math
import random
import unittest

from lending_hub.definitions.provenance import Pending, Ungrounded
from lending_hub.portfolio import lgd as L


def workout(exposure=100_000, costs=5_000, proceeds=60_000, enhancement=0, aid="A"):
    return L.WorkoutCashflows(
        account_id=aid,
        exposure_at_default=exposure,
        costs=costs,
        proceeds=proceeds,
        credit_enhancement_proceeds=enhancement,
    )


class WorkoutTests(unittest.TestCase):
    def test_zero_exposure_is_not_a_loss_observation(self):
        with self.assertRaises(L.LGDError) as ctx:
            L.WorkoutCashflows("A", 0)
        self.assertIn("undefined at zero", str(ctx.exception))

    def test_negative_exposure_rejected(self):
        with self.assertRaises(L.LGDError):
            L.WorkoutCashflows("A", -1)

    def test_negative_costs_are_accepted_as_credits(self):
        """Servicers post holding expenses net of credits."""
        w = workout(costs=-500)
        self.assertLess(w.net_loss(L.LossBasis.GROSS_OF_ENHANCEMENT), 45_000)

    def test_negative_proceeds_are_accepted_as_reversals(self):
        self.assertIsInstance(workout(proceeds=-100), L.WorkoutCashflows)


class LossBasisTests(unittest.TestCase):
    def test_basis_is_required_and_has_no_default(self):
        with self.assertRaises(TypeError):
            L.realised_lgd(workout())

    def test_a_string_basis_is_rejected(self):
        with self.assertRaises(L.LGDError) as ctx:
            L.realised_lgd(workout(), basis="net")
        self.assertIn("LH-311", str(ctx.exception))

    def test_enhancement_lowers_the_net_basis_only(self):
        w = workout(enhancement=20_000)
        gross = L.realised_lgd(w, basis=L.LossBasis.GROSS_OF_ENHANCEMENT)
        net = L.realised_lgd(w, basis=L.LossBasis.NET_OF_ENHANCEMENT)
        self.assertAlmostEqual(gross, 0.45)
        self.assertAlmostEqual(net, 0.25)

    def test_bases_agree_when_there_is_no_enhancement(self):
        w = workout(enhancement=0)
        self.assertEqual(
            L.realised_lgd(w, basis=L.LossBasis.GROSS_OF_ENHANCEMENT),
            L.realised_lgd(w, basis=L.LossBasis.NET_OF_ENHANCEMENT),
        )

    def test_clipping_bounds_the_ratio(self):
        recovered = workout(proceeds=200_000)
        self.assertEqual(
            L.realised_lgd(recovered, basis=L.LossBasis.GROSS_OF_ENHANCEMENT), 0.0)
        self.assertLess(
            L.realised_lgd(recovered, basis=L.LossBasis.GROSS_OF_ENHANCEMENT,
                           clip=False), 0.0)

    def test_costs_alone_can_push_lgd_above_one(self):
        expensive = workout(costs=60_000, proceeds=50_000)
        self.assertGreater(
            L.realised_lgd(expensive, basis=L.LossBasis.GROSS_OF_ENHANCEMENT,
                           clip=False), 1.0)


class DistributionTests(unittest.TestCase):
    def test_boundary_masses_are_counted_separately(self):
        workouts = (
            [workout(proceeds=200_000, aid=f"z{i}") for i in range(3)]      # LGD 0
            + [workout(proceeds=0, aid=f"o{i}") for i in range(2)]          # LGD 1
            + [workout(aid=f"m{i}") for i in range(5)]                      # interior
        )
        d = L.describe(workouts, basis=L.LossBasis.GROSS_OF_ENHANCEMENT)
        self.assertEqual((d.at_zero, d.at_one, d.interior), (3, 2, 5))
        self.assertAlmostEqual(d.boundary_fraction, 0.5)

    def test_heavy_boundary_mass_raises_a_caveat(self):
        workouts = [workout(proceeds=200_000, aid=f"z{i}") for i in range(8)] + [
            workout(aid=f"m{i}") for i in range(2)]
        d = L.describe(workouts, basis=L.LossBasis.GROSS_OF_ENHANCEMENT)
        self.assertIn("open interval", d.beta_regression_caveat)

    def test_reversals_are_counted_not_dropped(self):
        workouts = [workout(aid="a"), workout(costs=-100, aid="b")]
        d = L.describe(workouts, basis=L.LossBasis.GROSS_OF_ENHANCEMENT)
        self.assertEqual(d.count, 2)
        self.assertEqual(d.reversals, 1)

    def test_empty_input_rejected(self):
        with self.assertRaises(L.LGDError):
            L.describe([], basis=L.LossBasis.GROSS_OF_ENHANCEMENT)


class SpecialFunctionTests(unittest.TestCase):
    def test_digamma_matches_known_values(self):
        self.assertAlmostEqual(L.digamma(1.0), -0.5772156649015329, places=9)
        self.assertAlmostEqual(L.digamma(0.5), -1.9635100260214235, places=9)
        self.assertAlmostEqual(L.digamma(10.0), 2.251752589066721, places=9)

    def test_trigamma_matches_known_values(self):
        self.assertAlmostEqual(L.trigamma(1.0), math.pi ** 2 / 6, places=9)
        self.assertAlmostEqual(L.trigamma(0.5), math.pi ** 2 / 2, places=9)

    def test_digamma_recurrence_holds(self):
        for x in (0.3, 1.7, 4.2, 9.9):
            self.assertAlmostEqual(
                L.digamma(x + 1) - L.digamma(x), 1.0 / x, places=9)

    def test_trigamma_recurrence_holds(self):
        for x in (0.3, 1.7, 4.2, 9.9):
            self.assertAlmostEqual(
                L.trigamma(x) - L.trigamma(x + 1), 1.0 / (x * x), places=9)

    def test_undefined_at_non_positive_integers(self):
        with self.assertRaises(L.LGDError):
            L.digamma(0.0)
        with self.assertRaises(L.LGDError):
            L.trigamma(-2.0)


class SqueezeTests(unittest.TestCase):
    def test_boundaries_move_inside_the_open_interval(self):
        out = L.squeeze([0.0, 0.5, 1.0])
        self.assertTrue(all(0.0 < v < 1.0 for v in out))

    def test_the_transform_shrinks_with_sample_size(self):
        small = L.squeeze([0.0] * 10)[0]
        large = L.squeeze([0.0] * 1000)[0]
        self.assertLess(large, small)

    def test_single_observation_rejected(self):
        with self.assertRaises(L.LGDError):
            L.squeeze([0.5])

    def test_empty_rejected(self):
        with self.assertRaises(L.LGDError):
            L.squeeze([])


class BetaRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng = random.Random(3)
        cls.rows, cls.targets = [], []
        for _ in range(2500):
            ltv = rng.random()
            mu = 1.0 / (1.0 + math.exp(-(-1.0 + 2.0 * ltv)))
            phi = 8.0
            y = rng.betavariate(mu * phi, (1.0 - mu) * phi)
            cls.rows.append({"ltv": ltv})
            cls.targets.append(min(max(y, 1e-6), 1 - 1e-6))
        cls.model = L.fit_beta_regression(
            cls.rows, cls.targets, ["ltv"], apply_squeeze=False)

    def test_recovers_the_generating_parameters(self):
        self.assertTrue(self.model.converged)
        self.assertAlmostEqual(self.model.intercept, -1.0, delta=0.2)
        self.assertAlmostEqual(self.model.coefficients[0], 2.0, delta=0.3)
        self.assertAlmostEqual(self.model.precision, 8.0, delta=1.5)

    def test_predictions_are_in_the_unit_interval(self):
        for ltv in (0.0, 0.5, 1.0, -5.0, 5.0):
            p = self.model.predict({"ltv": ltv})
            self.assertTrue(0.0 < p < 1.0)

    def test_missing_feature_predicts_at_zero_not_an_error(self):
        self.assertTrue(0.0 < self.model.predict({}) < 1.0)

    def test_standard_errors_are_reported(self):
        self.assertIsNotNone(self.model.standard_errors[0])
        self.assertGreater(self.model.standard_errors[0], 0.0)

    def test_boundary_targets_rejected_without_the_squeeze(self):
        with self.assertRaises(L.LGDError) as ctx:
            L.fit_beta_regression(
                [{"x": 1.0}, {"x": 2.0}], [0.0, 0.5], ["x"], apply_squeeze=False)
        self.assertIn("open interval", str(ctx.exception))

    def test_boundary_targets_are_fitted_with_the_squeeze(self):
        rng = random.Random(8)
        rows = [{"x": rng.random()} for _ in range(200)]
        targets = [0.0 if r["x"] < 0.3 else (1.0 if r["x"] > 0.8 else r["x"])
                   for r in rows]
        model = L.fit_beta_regression(rows, targets, ["x"])
        self.assertEqual(model.observations, 200)

    def test_length_mismatch_rejected(self):
        with self.assertRaises(L.LGDError):
            L.fit_beta_regression([{"x": 1.0}], [0.5, 0.5], ["x"])

    def test_too_few_observations_rejected(self):
        with self.assertRaises(L.LGDError):
            L.fit_beta_regression([{"x": 1.0}], [0.5], ["x"])

    def test_unconverged_fit_is_not_promotable(self):
        model = L.fit_beta_regression(
            self.rows, self.targets, ["ltv"], apply_squeeze=False, max_iterations=1)
        if not model.converged:
            self.assertFalse(model.promotable[0])


class PolicyGateTests(unittest.TestCase):
    def setUp(self):
        rng = random.Random(5)
        rows, targets = [], []
        for _ in range(600):
            x = rng.random()
            mu = 1.0 / (1.0 + math.exp(-(-0.5 + 1.5 * x)))
            targets.append(rng.betavariate(mu * 10.0, (1.0 - mu) * 10.0))
            rows.append({"x": x})
        self.recovery = L.fit_beta_regression(rows, targets, ["x"])

    def test_discounted_lgd_raises_until_lh_305(self):
        with self.assertRaises(Ungrounded) as ctx:
            L.discounted_lgd(workout())
        self.assertIn("LH-305", str(ctx.exception))

    def test_downturn_lgd_raises_until_lh_302(self):
        with self.assertRaises(Ungrounded) as ctx:
            L.downturn_lgd(0.4)
        self.assertIn("LH-302", str(ctx.exception))

    def test_downturn_lgd_applies_a_supplied_add_on(self):
        self.assertAlmostEqual(L.downturn_lgd(0.4, add_on=0.15), 0.55)

    def test_downturn_lgd_is_capped_at_one(self):
        self.assertEqual(L.downturn_lgd(0.95, add_on=0.4), 1.0)

    def test_stage_two_alone_is_computable(self):
        stage = L.TwoStageLGD(recovery=self.recovery)
        self.assertTrue(0.0 < stage.loss_given_no_cure({"x": 0.5}) < 1.0)

    def test_expected_lgd_raises_until_lh_309(self):
        stage = L.TwoStageLGD(recovery=self.recovery)
        with self.assertRaises(Ungrounded) as ctx:
            stage.expected_lgd({"x": 0.5})
        self.assertIn("LH-309", str(ctx.exception))

    def test_two_stage_is_not_promotable_without_a_cure_definition(self):
        stage = L.TwoStageLGD(recovery=self.recovery)
        ok, why = stage.promotable
        self.assertFalse(ok)
        self.assertIn("cure", why)

    def test_supplying_both_stages_makes_expected_lgd_computable(self):
        class Cure:
            def predict(self, row):
                return 0.25
        stage = L.TwoStageLGD(
            recovery=self.recovery,
            cure_definition="90 consecutive days performing (CP-2026-3)",
            cure_model=Cure(),
        )
        expected = stage.expected_lgd({"x": 0.5})
        self.assertAlmostEqual(
            expected, 0.75 * stage.loss_given_no_cure({"x": 0.5}), places=12)
        self.assertTrue(stage.promotable[0])


if __name__ == "__main__":
    unittest.main()

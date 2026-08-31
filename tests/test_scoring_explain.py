"""Tests for SHAP attribution and the reason-code dictionary (WS-1.1 Step 6).

Local accuracy is the load-bearing test. It is the one property that catches
almost every implementation error in an attribution method, and an attribution
that violates it is not an explanation of the score — it is a story next to it.

Workstream: WS-1.1 Step 6
"""

import math
import random
import unittest
from itertools import combinations

from lending_hub.definitions import Ungrounded
from lending_hub.scoring.binning import fit_binning
from lending_hub.scoring.explain import (
    MAX_EXACT_FEATURES_PER_TREE,
    ExplainError,
    explain_gbm,
    explain_scorecard,
    global_importance,
    tree_shap,
)
from lending_hub.scoring.gbm import (
    DECREASING,
    INCREASING,
    MonotoneConstraints,
    Node,
    fit_gbm,
)
from lending_hub.scoring.reasons import (
    ReasonTableError,
    UnmappedReason,
    check_directions,
    load_table,
    map_reasons,
    unratified_codes,
)
from lending_hub.scoring.scorecard import fit_scorecard

FEATURES = ["bureau_score", "utilisation", "enquiries"]
RATIFIED = MonotoneConstraints.from_policy(
    {"bureau_score": DECREASING, "utilisation": INCREASING, "enquiries": INCREASING},
    decision_reference="test fixture",
)


def make(n, seed):
    rng = random.Random(seed)
    rows, labels = [], []
    for _ in range(n):
        score = rng.uniform(300, 850)
        util = rng.uniform(0, 1.2)
        enquiries = rng.randint(0, 12)
        z = -3.0 + (700 - score) / 120 + util * 1.4 + enquiries * 0.12
        rows.append({
            "bureau_score": score, "utilisation": util, "enquiries": float(enquiries)
        })
        labels.append(1 if rng.random() < 1 / (1 + math.exp(-z)) else 0)
    return rows, labels


class TestLocalAccuracy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.labels = make(800, 101)
        cls.model = fit_gbm(
            cls.rows, cls.labels, FEATURES, RATIFIED, n_trees=25, max_bins=16
        )

    def test_attributions_sum_to_the_score_minus_the_base(self):
        for row in self.rows[:25]:
            self.assertTrue(explain_gbm(self.model, row).reconciles)

    def test_the_base_value_is_the_score_of_a_fully_unknown_row(self):
        # E[f] with nothing known: every feature marginalised by cover.
        explanation = explain_gbm(self.model, self.rows[0])
        empty_paths = sum(
            self.model.learning_rate * tree_shap(tree, {})[0]
            for tree in self.model.trees[: self.model.best_iteration]
        )
        self.assertAlmostEqual(
            explanation.base_value, self.model.base_score + empty_paths, places=9
        )

    def test_a_feature_the_trees_never_use_gets_exactly_zero(self):
        rows = [dict(row, unused=random.random()) for row in self.rows[:5]]
        for row in rows:
            attribution = next(
                (a for a in explain_gbm(self.model, row).attributions
                 if a.feature == "unused"), None
            )
            self.assertIsNone(attribution)

    def test_shap_matches_a_brute_force_shapley_computation(self):
        # The independent oracle: Shapley's definition, evaluated directly over
        # every coalition. If the fast path and the definition disagree, the fast
        # path is wrong.
        tree = self.model.trees[0]
        row = self.rows[3]
        _, fast = tree_shap(tree, row)

        features = sorted(fast)
        n = len(features)

        def value(subset):
            from lending_hub.scoring.explain import _expected_value
            return _expected_value(tree, row, frozenset(subset))

        for feature in features:
            rest = [f for f in features if f != feature]
            total = 0.0
            for size in range(n):
                weight = (
                    math.factorial(size) * math.factorial(n - size - 1) / math.factorial(n)
                )
                for subset in combinations(rest, size):
                    total += weight * (value(set(subset) | {feature}) - value(subset))
            self.assertAlmostEqual(fast[feature], total, places=10)


class TestAdverseDirection(unittest.TestCase):
    def test_positive_shap_is_adverse_for_a_pd_model(self):
        rows, labels = make(600, 111)
        model = fit_gbm(rows, labels, FEATURES, RATIFIED, n_trees=25, max_bins=16)
        riskiest = max(rows, key=model.predict)
        adverse = explain_gbm(model, riskiest).adverse(3)
        self.assertTrue(adverse)
        self.assertTrue(all(a.shap > 0 for a in adverse))

    def test_the_safest_applicant_has_few_or_no_adverse_drivers(self):
        rows, labels = make(600, 112)
        model = fit_gbm(rows, labels, FEATURES, RATIFIED, n_trees=25, max_bins=16)
        safest = min(rows, key=model.predict)
        riskiest = max(rows, key=model.predict)
        self.assertLess(
            len(explain_gbm(model, safest).adverse()),
            len(explain_gbm(model, riskiest).adverse()) + 1,
        )

    def test_adverse_ordering_is_deterministic(self):
        rows, labels = make(400, 113)
        model = fit_gbm(rows, labels, FEATURES, RATIFIED, n_trees=15, max_bins=16)
        first = [a.feature for a in explain_gbm(model, rows[0]).adverse()]
        second = [a.feature for a in explain_gbm(model, rows[0]).adverse()]
        self.assertEqual(first, second)


class TestScorecardExplanation(unittest.TestCase):
    def setUp(self):
        self.rows, self.labels = make(800, 121)
        binnings = [
            fit_binning([r[f] for r in self.rows], self.labels, feature=f) for f in FEATURES
        ]
        self.card = fit_scorecard(self.rows, self.labels, binnings)

    def test_the_linear_attribution_reconciles_exactly(self):
        for row in self.rows[:20]:
            self.assertTrue(explain_scorecard(self.card, row).reconciles)

    def test_signs_agree_with_the_gbm_convention(self):
        # Positive means "pushes toward default" for both models, so one
        # reason-code mapping serves both.
        riskiest = max(self.rows, key=self.card.predict)
        safest = min(self.rows, key=self.card.predict)
        self.assertGreater(
            sum(a.shap for a in explain_scorecard(self.card, riskiest).attributions),
            sum(a.shap for a in explain_scorecard(self.card, safest).attributions),
        )


class TestExactnessGuard(unittest.TestCase):
    def test_a_wide_tree_is_refused_rather_than_run_slowly(self):
        node = Node(cover=1.0, count=1)
        current = node
        for index in range(MAX_EXACT_FEATURES_PER_TREE + 1):
            current.feature = f"f{index}"
            current.threshold = 0.5
            current.left = Node(value=0.0, cover=0.5, count=1)
            current.right = Node(value=1.0, cover=0.5, count=1)
            current = current.right
        with self.assertRaises(ExplainError) as caught:
            tree_shap(node, {f"f{i}": 1.0 for i in range(MAX_EXACT_FEATURES_PER_TREE + 2)})
        self.assertIn("TreeSHAP", str(caught.exception))


class TestGlobalImportance(unittest.TestCase):
    def test_it_ranks_the_dominant_feature_first(self):
        rows, labels = make(600, 131)
        model = fit_gbm(rows, labels, FEATURES, RATIFIED, n_trees=30, max_bins=16)
        ranking = global_importance(model, rows, limit=60)
        self.assertEqual(ranking[0][0], "bureau_score")

    def test_zero_rows_is_refused(self):
        rows, labels = make(200, 132)
        model = fit_gbm(rows, labels, FEATURES, RATIFIED, n_trees=5, max_bins=8)
        with self.assertRaises(ExplainError):
            global_importance(model, [])


class TestReasonCodeTable(unittest.TestCase):
    def setUp(self):
        try:
            self.table = load_table()
        except ReasonTableError as exc:  # pragma: no cover - PyYAML absent
            self.skipTest(str(exc))

    def test_the_shipped_table_has_no_ratified_wording(self):
        # Reason-code wording is [POLICY: Compliance], LH-203.
        self.assertFalse(self.table.ratified)
        self.assertEqual(len(unratified_codes(self.table)), len(self.table.entries))

    def test_rendering_an_unratified_sentence_raises(self):
        with self.assertRaises(Ungrounded) as caught:
            self.table.render(self.table.entries[0].code)
        self.assertIn("LH-203", str(caught.exception))

    def test_every_shipped_feature_has_a_code(self):
        from lending_hub.scoring.features import application_scorecard_catalogue
        catalogue = application_scorecard_catalogue()
        mapped = set(self.table.by_feature)
        self.assertEqual(sorted(mapped), catalogue.names)

    def test_the_table_version_is_a_content_hash(self):
        self.assertEqual(len(self.table.version()), 16)

    def test_directions_are_cross_checked_against_the_monotonicity_list(self):
        contradictory = {"bureau_utilisation": DECREASING}
        problems = check_directions(self.table, contradictory)
        self.assertEqual(len(problems), 1)
        self.assertIn("CS_BUREAU_UTILISATION_HIGH", problems[0])

    def test_a_consistent_direction_list_produces_no_problems(self):
        consistent = {"bureau_utilisation": INCREASING, "declared_income": DECREASING}
        self.assertEqual(check_directions(self.table, consistent), [])


class TestMapReasons(unittest.TestCase):
    def setUp(self):
        try:
            self.table = load_table()
        except ReasonTableError as exc:  # pragma: no cover - PyYAML absent
            self.skipTest(str(exc))
        self.rows, self.labels = make(500, 141)
        self.model = fit_gbm(self.rows, self.labels, FEATURES, RATIFIED,
                             n_trees=15, max_bins=16)

    def test_an_unmapped_top_driver_raises_rather_than_being_dropped(self):
        riskiest = max(self.rows, key=self.model.predict)
        explanation = explain_gbm(self.model, riskiest)
        with self.assertRaises(UnmappedReason):
            map_reasons(explanation, self.table)

    def test_reason_codes_carry_no_wording(self):
        from lending_hub.decisionlog import ReasonCode
        code = ReasonCode("CS_BUREAU_UTILISATION_HIGH", contribution=0.4)
        self.assertFalse(hasattr(code, "wording"))
        self.assertFalse(hasattr(code, "text"))

    def test_a_duplicate_feature_in_the_table_is_refused(self):
        import tempfile, pathlib as _pathlib
        try:
            import yaml  # noqa: F401
        except ModuleNotFoundError:  # pragma: no cover
            self.skipTest("PyYAML absent")
        body = (
            'schema_version: "1.0"\nmodel: m\nowner: Compliance\nstatus: draft\n'
            "codes:\n"
            "  - code: A\n    feature: x\n    direction: adverse_when_high\n"
            '    wording: "TBD[Compliance, LH-203]"\n'
            "  - code: B\n    feature: x\n    direction: adverse_when_low\n"
            '    wording: "TBD[Compliance, LH-203]"\n'
        )
        with tempfile.TemporaryDirectory() as directory:
            path = _pathlib.Path(directory) / "t.yaml"
            path.write_text(body, encoding="utf-8")
            with self.assertRaises(ReasonTableError):
                load_table(path)


if __name__ == "__main__":
    unittest.main()

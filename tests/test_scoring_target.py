"""Tests for target engineering and vintage splits (WS-1.1 Step 1).

The tests that matter here are the refusals. A target builder that silently drops
rows and a splitter that silently randomises both produce plausible numbers, and
neither failure is visible in the output — so each one is pinned by a test that
fails if the refusal is ever softened.

Workstream: WS-1.1 Step 1
"""

import unittest
from datetime import date

from lending_hub.definitions import Label, OutcomeObservation
from lending_hub.scoring.splits import (
    MINIMUM_BADS_FOR_CHALLENGER,
    Part,
    carve_calibration,
    RandomSplitForbidden,
    SplitError,
    holdout_without_time_axis,
    manifest,
    split_by_vintage,
)
from lending_hub.scoring.target import (
    PHASE_1_EXCLUSIONS,
    Application,
    Exclusion,
    LabelProvenance,
    TargetError,
    TargetTable,
    UnenforceableExclusion,
    build_target_table,
)

BAD = OutcomeObservation(max_dpd=120)
GOOD = OutcomeObservation(max_dpd=0)
MIDDLE = OutcomeObservation(max_dpd=45)

FLAGS = {"fraud_confirmed": False, "staff_loan": False, "restructured": False}


def app(app_id, *, observation=GOOD, vintage="2020Q1", day=1, flags=None, **kw):
    return Application(
        application_id=app_id,
        decided_at=date(2020, 1, day),
        vintage=vintage,
        observation=observation,
        flags={**FLAGS, **(flags or {})},
        **kw,
    )


class TestExclusions(unittest.TestCase):
    def test_phase_1_names_exactly_three_exclusions(self):
        self.assertEqual(
            sorted(e.code for e in PHASE_1_EXCLUSIONS),
            ["FRAUD_TAGGED", "RESTRUCTURE", "STAFF_LOAN"],
        )

    def test_every_exclusion_states_its_grounding(self):
        for exclusion in PHASE_1_EXCLUSIONS:
            self.assertTrue(exclusion.grounding, exclusion.code)
            self.assertTrue(exclusion.reason, exclusion.code)

    def test_excluded_rows_are_attributed_not_just_dropped(self):
        table = build_target_table(
            [
                app("a"),
                app("b", flags={"staff_loan": True}),
                app("c", flags={"fraud_confirmed": True}),
            ],
            dataset="fixture",
        )
        self.assertEqual(table.ledger.excluded, {"STAFF_LOAN": 1, "FRAUD_TAGGED": 1})
        self.assertEqual(table.ledger.kept, 1)
        self.assertTrue(table.ledger.reconciles())

    def test_an_exclusion_whose_flag_is_absent_is_refused(self):
        # The whole point: a filter that matched nothing because its column is
        # missing looks identical, in the ledger, to a clean population.
        with self.assertRaises(UnenforceableExclusion) as caught:
            build_target_table(
                [Application("a", date(2020, 1, 1), "2020Q1", observation=GOOD)],
                dataset="fixture",
            )
        self.assertIn("FRAUD_TAGGED", str(caught.exception))

    def test_unenforceable_exclusions_can_be_accepted_deliberately(self):
        table = build_target_table(
            [Application("a", date(2020, 1, 1), "2020Q1", observation=GOOD)],
            dataset="fixture",
            require_enforceable=False,
        )
        self.assertEqual(len(table.ledger.unenforceable), 3)
        self.assertEqual(table.ledger.kept, 1)

    def test_blocked_exclusions_name_their_ticket(self):
        blocked = {e.code: e.blocked_by for e in PHASE_1_EXCLUSIONS if e.blocked_by}
        self.assertEqual(blocked["FRAUD_TAGGED"].ticket, "LH-101")
        self.assertEqual(blocked["RESTRUCTURE"].ticket, "LH-103")


class TestLabelling(unittest.TestCase):
    def test_indeterminates_stay_in_the_table_and_out_of_training(self):
        table = build_target_table([app("a", observation=MIDDLE)], dataset="fixture")
        self.assertEqual(len(table), 1)
        self.assertIs(table.rows[0].label, Label.INDETERMINATE)
        self.assertFalse(table.rows[0].trainable)
        self.assertEqual(table.trainable_rows, [])

    def test_reading_y_on_an_indeterminate_raises(self):
        table = build_target_table([app("a", observation=MIDDLE)], dataset="fixture")
        with self.assertRaises(TargetError):
            table.rows[0].y

    def test_undetermined_outcomes_are_counted_not_labelled_good(self):
        table = build_target_table([app("a", observation=None)], dataset="fixture")
        self.assertEqual(table.ledger.undetermined, 1)
        self.assertEqual(len(table), 0)

    def test_bad_rate_is_none_not_zero_when_nothing_is_trainable(self):
        table = build_target_table([app("a", observation=MIDDLE)], dataset="fixture")
        self.assertIsNone(table.ledger.bad_rate)

    def test_a_vendor_label_must_state_its_definition(self):
        with self.assertRaises(TargetError):
            build_target_table(
                [Application("a", date(2020, 1, 1), "2020Q1", vendor_label=1, flags=FLAGS)],
                dataset="home_credit",
                provenance=LabelProvenance.VENDOR,
            )

    def test_a_vendor_label_is_never_marked_appendix_a_aligned(self):
        table = build_target_table(
            [Application("a", date(2020, 1, 1), "2020Q1", vendor_label=1, flags=FLAGS)],
            dataset="home_credit",
            provenance=LabelProvenance.VENDOR,
            label_note="Home Credit TARGET: the vendor's own payment-difficulty flag",
        )
        self.assertFalse(table.manifest()["appendix_a_aligned"])
        self.assertIs(table.rows[0].label, Label.BAD)

    def test_a_row_cannot_carry_both_an_outcome_and_a_vendor_label(self):
        with self.assertRaises(TargetError):
            Application("a", date(2020, 1, 1), "2020Q1", observation=GOOD, vendor_label=0)

    def test_the_table_records_the_definitions_fingerprint(self):
        table = build_target_table([app("a")], dataset="fixture")
        self.assertEqual(len(table.definitions_fingerprint), 16)


class TestLedgerReconciles(unittest.TestCase):
    def test_a_filter_that_drops_rows_silently_is_caught(self):
        # A predicate that raises no error but removes rows outside the exclusion
        # machinery is the undocumented filter Phase 1 forbids. The ledger identity
        # is what makes it impossible to add one without failing this test.
        rows = [app(f"a{i}") for i in range(5)]
        table = build_target_table(rows, dataset="fixture")
        self.assertTrue(table.ledger.reconciles())
        self.assertEqual(
            table.ledger.applications_in,
            table.ledger.kept + table.ledger.undetermined + table.ledger.excluded_total,
        )


def population(counts):
    """Build a table with `counts` = {vintage: (goods, bads)}."""
    apps = []
    for index, (vintage, (goods, bads)) in enumerate(sorted(counts.items())):
        year = 2018 + index
        for i in range(goods):
            apps.append(
                Application(f"{vintage}-g{i}", date(year, 6, 1), vintage,
                            observation=GOOD, flags=FLAGS)
            )
        for i in range(bads):
            apps.append(
                Application(f"{vintage}-b{i}", date(year, 6, 1), vintage,
                            observation=BAD, flags=FLAGS)
            )
    return build_target_table(apps, dataset="fixture")


class TestVintageSplit(unittest.TestCase):
    def setUp(self):
        self.table = population(
            {f"20{18 + i}Q1": (100, 10) for i in range(10)}
        )

    def test_oldest_vintages_train_newest_test(self):
        splits = split_by_vintage(self.table)
        self.assertTrue(splits.out_of_time)
        newest = max(row.vintage for row in splits.test)
        oldest = min(row.vintage for row in splits.train)
        self.assertGreater(newest, oldest)
        self.assertLess(max(r.vintage for r in splits.train),
                        min(r.vintage for r in splits.test))

    def test_no_vintage_is_split_across_parts(self):
        splits = split_by_vintage(self.table)
        seen = {}
        for part in Part:
            for row in splits.part(part):
                self.assertEqual(seen.setdefault(row.vintage, part), part,
                                 f"{row.vintage} landed in two parts")

    def test_fewer_than_three_vintages_is_refused(self):
        with self.assertRaises(SplitError):
            split_by_vintage(population({"2018Q1": (50, 5), "2019Q1": (50, 5)}))

    def test_a_vintage_key_that_does_not_sort_chronologically_is_refused(self):
        apps = [
            Application("a", date(2021, 1, 1), "Q1-2021", observation=GOOD, flags=FLAGS),
            Application("b", date(2019, 1, 1), "Q1-2019", observation=GOOD, flags=FLAGS),
            Application("c", date(2020, 1, 1), "Q2-2020", observation=GOOD, flags=FLAGS),
        ]
        with self.assertRaises(SplitError) as caught:
            split_by_vintage(build_target_table(apps, dataset="fixture"))
        self.assertIn("chronolog", str(caught.exception))

    def test_challenger_scope_follows_the_phase_1_bad_floor(self):
        splits = split_by_vintage(self.table)
        in_scope, note = splits.challenger_in_scope()
        self.assertFalse(in_scope)
        self.assertIn(str(MINIMUM_BADS_FOR_CHALLENGER), note)

    def test_challenger_is_in_scope_above_the_floor(self):
        big = population({f"20{18 + i}Q1": (10_000, 400) for i in range(10)})
        in_scope, _ = split_by_vintage(big).challenger_in_scope()
        self.assertTrue(in_scope)

    def test_manifest_is_hashable_and_records_the_strategy(self):
        splits = split_by_vintage(self.table)
        record = manifest(self.table, splits)
        self.assertEqual(record.strategy, "vintage")
        self.assertTrue(record.out_of_time)
        self.assertEqual(len(record.hash()), 16)
        self.assertEqual(record.target_manifest_hash, self.table.manifest_hash())


class TestCalibrationBlock(unittest.TestCase):
    """Phase 1 §4 Step 5 (v1.1): the calibrator is not fitted on the selection set."""

    def setUp(self):
        self.table = population({f"20{18 + i}Q1": (100, 10) for i in range(10)})

    def test_a_splitter_leaves_calibration_empty(self):
        # It is carved from train afterwards, not filled by the splitter — and an
        # empty calibration part is not an unfilled split.
        splits = split_by_vintage(self.table)
        self.assertEqual(splits.calibration, [])

    def test_carving_moves_rows_out_of_train_rather_than_copying(self):
        splits = split_by_vintage(self.table)
        before = len(splits.train)
        carve_calibration(splits, fraction=0.2)
        self.assertLess(len(splits.train), before)
        self.assertEqual(len(splits.train) + len(splits.calibration), before)
        train_ids = {row.application_id for row in splits.train}
        calibration_ids = {row.application_id for row in splits.calibration}
        self.assertEqual(train_ids & calibration_ids, set())

    def test_it_takes_the_newest_end_of_train(self):
        # Calibrating against the oldest regime the model will never score in is
        # the wrong end to take.
        splits = carve_calibration(split_by_vintage(self.table), fraction=0.2)
        self.assertGreater(
            min(row.vintage for row in splits.calibration),
            min(row.vintage for row in splits.train),
        )

    def test_it_snaps_to_a_vintage_boundary(self):
        splits = carve_calibration(split_by_vintage(self.table), fraction=0.2)
        shared = {r.vintage for r in splits.train} & {r.vintage for r in splits.calibration}
        self.assertEqual(shared, set())

    def test_carving_twice_is_refused(self):
        splits = carve_calibration(split_by_vintage(self.table), fraction=0.2)
        with self.assertRaises(SplitError):
            carve_calibration(splits, fraction=0.1)

    def test_a_fraction_that_yields_no_rows_is_refused(self):
        splits = split_by_vintage(self.table)
        with self.assertRaises(SplitError) as caught:
            carve_calibration(splits, fraction=0.0001)
        self.assertIn("cross-fitted", str(caught.exception))

    def test_the_manifest_reports_the_calibration_block(self):
        splits = carve_calibration(split_by_vintage(self.table), fraction=0.2)
        record = manifest(self.table, splits)
        self.assertGreater(record.sizes["calibration"], 0)

    def test_carving_shrinks_the_bad_count_the_challenger_sees(self):
        # challenger_in_scope counts training bads, and the calibration rows are
        # no longer training rows.
        splits = split_by_vintage(self.table)
        before = splits.bads(Part.TRAIN)
        carve_calibration(splits, fraction=0.2)
        self.assertLess(splits.bads(Part.TRAIN), before)


class TestRandomHoldoutIsGated(unittest.TestCase):
    def setUp(self):
        self.table = population({f"20{18 + i}Q1": (100, 10) for i in range(10)})

    def test_refused_for_a_source_with_a_usable_time_axis(self):
        with self.assertRaises(RandomSplitForbidden):
            holdout_without_time_axis(
                self.table, source_id="cbs", seed=0,
                registry_lookup=lambda _: False,
            )

    def test_allowed_only_for_a_registry_declared_clockless_source(self):
        splits = holdout_without_time_axis(
            self.table, source_id="home_credit_default_risk", seed=7,
            registry_lookup=lambda _: True,
        )
        self.assertFalse(splits.out_of_time)
        self.assertIn("point_in_time_unsafe", splits.limitation)

    def test_the_manifest_carries_the_not_out_of_time_stamp(self):
        splits = holdout_without_time_axis(
            self.table, source_id="home_credit_default_risk", seed=7,
            registry_lookup=lambda _: True,
        )
        record = manifest(self.table, splits)
        self.assertFalse(record.out_of_time)
        self.assertTrue(record.limitation)

    def test_the_same_seed_gives_the_same_partition(self):
        first = holdout_without_time_axis(
            self.table, source_id="x", seed=3, registry_lookup=lambda _: True
        )
        second = holdout_without_time_axis(
            self.table, source_id="x", seed=3, registry_lookup=lambda _: True
        )
        self.assertEqual(
            [r.application_id for r in first.test], [r.application_id for r in second.test]
        )


class TestHomeCreditIsDeclaredUnsafe(unittest.TestCase):
    """The registry statement the random-holdout path depends on must be real."""

    def test_registry_declares_home_credit_point_in_time_unsafe(self):
        try:
            from lending_hub.registry import load_registry
        except Exception:  # pragma: no cover - PyYAML absent
            self.skipTest("registry unavailable")
        try:
            records, _ = load_registry()
        except Exception:  # pragma: no cover - PyYAML absent
            self.skipTest("registry unavailable")
        record = next(r for r in records if r.id == "home_credit_default_risk")
        self.assertTrue(record.point_in_time_unsafe)


if __name__ == "__main__":
    unittest.main()

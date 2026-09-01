"""The golden set as a typed, versioned artifact — WS-5.1.3.

Phase 5 §4 calls the golden set "the phase's measuring stick", and that phrase
has a consequence the phase file does not draw out: if the set decides whether
the phase passes, the set needs a standard of its own. These tests are mostly
about that standard, and about the one refusal it implies — a hit-rate of 0.97
measured on 40 questions is not a rougher version of the gate number, it is a
different quantity carrying the same name.

The harness exists before the set (LH-602), and the ordering is deliberate: a
measuring stick built after the thing it measures is built to fit it.
"""

from __future__ import annotations

import unittest

from lending_hub.assistant.goldenset import (
    GOLDEN_SET,
    MIN_TRIPLES,
    MIN_TRIPLES_PER_LANGUAGE,
    GoldenSet,
    GoldenSetError,
    Triple,
    evaluate,
    harness_report,
)


def _triple(i=0, *, language="en", product="personal_loan", tricky=False, sources=("C1",)) -> Triple:
    return Triple(
        triple_id=f"T{i:04d}",
        question=f"Question {i}?",
        answer=f"Answer {i}.",
        source_chunks=tuple(sources),
        product=product,
        language=language,
        tricky=tricky,
    )


def _set(n, **kwargs) -> GoldenSet:
    return GoldenSet([_triple(i, **kwargs) for i in range(n)], version="v1")


class TripleInvariants(unittest.TestCase):
    def test_a_triple_without_a_source_passage_is_refused(self):
        """An unanswerable question is not a hard question; it is a refusal case.

        Phase 5 §8 sends "any answer where retrieval returned nothing" to the
        refusal path. Scoring such a question as a retrieval miss blames the
        retriever for correct behaviour, and a set full of them makes the gate
        unreachable for reasons unrelated to retrieval.
        """
        with self.assertRaises(GoldenSetError):
            Triple(
                triple_id="T1", question="q", answer="a",
                source_chunks=(), product="personal_loan",
            )

    def test_a_triple_without_a_reference_answer_is_refused(self):
        """The set measures faithfulness too, not only retrieval.

        A question with sources and no answer scores hit-rate and nothing else,
        and the missing half would not be noticed until the faithfulness gate
        needed it.
        """
        with self.assertRaises(GoldenSetError):
            Triple(
                triple_id="T1", question="q", answer="  ",
                source_chunks=("C1",), product="personal_loan",
            )

    def test_a_triple_without_a_product_is_refused(self):
        """Coverage per product is an admission criterion and needs the field."""
        with self.assertRaises(GoldenSetError):
            Triple(
                triple_id="T1", question="q", answer="a",
                source_chunks=("C1",), product="",
            )

    def test_a_duplicate_id_is_refused(self):
        """One question scored twice is one question weighted twice.

        Nobody chose that weighting, and it is invisible in the resulting
        hit-rate.
        """
        golden = GoldenSet([_triple(1)])
        with self.assertRaises(GoldenSetError):
            golden.add(_triple(1))


class Admission(unittest.TestCase):
    """If the set decides whether the phase passes, the set needs a standard."""

    def test_the_minimum_is_spec_and_not_this_module_to_move(self):
        self.assertEqual(MIN_TRIPLES, 500)

    def test_a_small_set_is_not_admissible(self):
        admission = _set(40, tricky=True).admission()
        self.assertFalse(admission.meets_minimum)
        self.assertFalse(admission.admissible)

    def test_a_set_with_no_tricky_cases_is_not_admissible(self):
        """§4 names fee edge cases and eligibility boundaries specifically.

        A 500-triple set of straightforward questions passes at 95% and says
        nothing about the queries that actually go wrong.
        """
        admission = _set(MIN_TRIPLES, tricky=False).admission()
        self.assertTrue(admission.meets_minimum)
        self.assertFalse(admission.has_tricky_cases)
        self.assertFalse(admission.admissible)

    def test_a_sufficient_set_is_admissible(self):
        golden = GoldenSet(
            [_triple(i, tricky=(i % 10 == 0)) for i in range(MIN_TRIPLES)], version="v1"
        )
        self.assertTrue(golden.admission().admissible)

    def test_per_language_sufficiency_is_unassessable_rather_than_failing(self):
        """Three states, and the third is the honest one — LH-610.

        A 20-triple Hindi slice is not "failing"; nobody has said what a slice
        needs. Reporting False would make LH-610 look like a curation backlog;
        reporting True would let that slice publish a 95% next to English's 500.
        """
        golden = GoldenSet(
            [_triple(i, language="hi" if i < 20 else "en", tricky=True) for i in range(MIN_TRIPLES)],
            version="v1",
        )
        admission = golden.admission()
        hindi = next(s for s in admission.per_language if s.name == "hi")
        self.assertEqual(hindi.triples, 20)
        self.assertIsNone(hindi.sufficient)
        self.assertIn("LH-610", admission.to_dict()["per_language_note"])

    def test_admissible_does_not_silently_cover_the_unratified_criterion(self):
        """A check that skips an unratified criterion while looking complete is
        how an unmeasured thing becomes a passed thing.

        ``admissible`` covers only the three checkable criteria, and the report
        names the fourth separately.
        """
        golden = GoldenSet(
            [_triple(i, language="hi" if i < 5 else "en", tricky=True) for i in range(MIN_TRIPLES)],
            version="v1",
        )
        self.assertTrue(golden.admission().admissible)
        self.assertIn("LH-610", golden.admission().to_dict()["per_language_note"])

    def test_whether_the_tricky_cases_are_the_right_ones_is_not_checked(self):
        """A count of SME-marked triples is not a judgement about coverage.

        Saying so in the report keeps the count from being quoted as if it were.
        """
        record = _set(10, tricky=True).admission().to_dict()
        self.assertIn("LH-601", record["unmeasured_criterion"])


class Evaluation(unittest.TestCase):
    def setUp(self):
        self.golden = GoldenSet(
            [_triple(i, tricky=(i % 10 == 0), sources=(f"C{i}",)) for i in range(MIN_TRIPLES)],
            version="v1",
        )

    def test_a_hit_rate_on_an_inadmissible_set_is_refused(self):
        """The module's central refusal.

        0.97 on 40 questions and 0.97 on 500 are different quantities with the
        same name, and once the first is in a report nothing distinguishes them.
        """
        small = _set(40, tricky=True)
        with self.assertRaises(GoldenSetError):
            evaluate(small, {t.triple_id: ["C1"] for t in small})

    def test_a_development_run_may_opt_out_and_is_still_identifiable(self):
        """Not a loophole: the result carries the set's size and hash.

        A number produced this way can be traced back to the 40-triple set it
        came from, which is the property that makes the opt-out safe.
        """
        small = _set(40, tricky=True)
        result = evaluate(
            small, {t.triple_id: ["C1"] for t in small}, require_admission=False
        )
        self.assertEqual(result.triples_scored, 40)
        self.assertEqual(result.set_hash, small.content_hash())

    def test_a_triple_with_no_retrieval_result_scores_as_a_miss(self):
        """Skipping is the failure that inflates.

        A retriever that errored on the hardest 10% would report a hit-rate over
        the easy 90% and look *better* for having failed.
        """
        retrieved = {t.triple_id: [t.source_chunks[0]] for t in list(self.golden)[:250]}
        result = evaluate(self.golden, retrieved)
        self.assertAlmostEqual(result.hit_rate, 0.5, places=6)

    def test_a_perfect_retriever_passes_the_gate(self):
        retrieved = {t.triple_id: [t.source_chunks[0]] for t in self.golden}
        result = evaluate(self.golden, retrieved)
        self.assertEqual(result.hit_rate, 1.0)
        self.assertTrue(result.passes)
        self.assertEqual(result.gate, 0.95)

    def test_an_empty_language_slice_raises_rather_than_scoring_zero(self):
        """Zero questions is undefined, not 0.0 and not 1.0.

        A language with no triples reporting 1.0 is how a language ships without
        ever being measured.
        """
        with self.assertRaises(GoldenSetError):
            evaluate(self.golden, {}, language="ta")

    def test_the_result_carries_the_sets_version_and_hash(self):
        """Quarterly refresh means the measuring stick moves.

        A hit-rate that changed between quarters could be the retriever or the
        set, and the hash is what makes the two distinguishable afterwards.
        """
        retrieved = {t.triple_id: [t.source_chunks[0]] for t in self.golden}
        record = evaluate(self.golden, retrieved).to_dict()
        self.assertEqual(record["golden_set_version"], "v1")
        self.assertEqual(record["golden_set_hash"], self.golden.content_hash())


class Versioning(unittest.TestCase):
    def test_the_diff_reports_added_removed_and_changed(self):
        old = GoldenSet([_triple(0), _triple(1)], version="v1")
        new = GoldenSet([_triple(1), _triple(2)], version="v2")
        diff = new.diff(old)
        self.assertEqual(diff["added"], ["T0002"])
        self.assertEqual(diff["removed"], ["T0000"])
        self.assertEqual(diff["from_version"], "v1")

    def test_an_edited_triple_shows_as_changed_not_unchanged(self):
        old = GoldenSet([_triple(0, sources=("C1",))], version="v1")
        new = GoldenSet([_triple(0, sources=("C2",))], version="v2")
        self.assertEqual(new.diff(old)["changed"], ["T0000"])

    def test_the_hash_changes_when_a_source_changes(self):
        self.assertNotEqual(
            GoldenSet([_triple(0, sources=("C1",))]).content_hash(),
            GoldenSet([_triple(0, sources=("C2",))]).content_hash(),
        )


class HarnessReport(unittest.TestCase):
    def test_an_absent_set_names_its_ticket_and_its_dependency(self):
        """LH-602 depends on LH-601, and reporting only the first hides that.

        A triple's answer is only correct relative to a corpus, so the set
        cannot be curated before the documents exist — which changes the
        sequencing question from "when will SMEs write it" to "when will there
        be something to write it against".
        """
        report = harness_report()
        self.assertFalse(report["present"])
        self.assertEqual(report["blocking_ticket"], "LH-602")
        self.assertEqual(report["depends_on"], "LH-601")
        self.assertIn("LH-610", report["per_language_minimum"])

    def test_the_report_states_why_the_harness_precedes_the_set(self):
        """A measuring stick built after the thing it measures is built to fit it.

        A golden set authored while a pipeline is being tuned drifts towards
        questions the pipeline answers well, and nobody involved intends it.
        """
        self.assertIn("built to fit it", harness_report()["note"])

    def test_the_set_and_the_slice_minimum_are_both_pending(self):
        self.assertIn("LH-602", str(GOLDEN_SET))
        self.assertIn("LH-610", str(MIN_TRIPLES_PER_LANGUAGE))


if __name__ == "__main__":
    unittest.main()

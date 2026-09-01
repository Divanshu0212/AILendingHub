"""Groundedness scoring and the suppression path — WS-5.4.

RAGAS has three steps and only two of them are code. Decomposition and
aggregation are deterministic and are tested here in full. The middle step —
does this passage entail this claim — is a model, and this module's most
important behaviour is refusing to fake it.

The fallback everyone reaches for is lexical overlap, and it is worse than no
score at all: "the fee is waived for accounts under six months" and "the fee
applies to accounts under six months" share every content word and mean opposite
things. An overlap-based groundedness score is therefore *highest* exactly where
a negation has been flipped — inverted rather than degraded, and reported as a
0.97.
"""

from __future__ import annotations

import unittest

from lending_hub.assistant.answer import validate
from lending_hub.assistant.faithfulness import (
    CONTAINMENT_TARGET,
    FAITHFULNESS_GATE,
    WEEKLY_AUDIT_SAMPLE_RATE,
    Disposition,
    FaithfulnessError,
    audit_sample_size,
    containment,
    extract_claims,
    score_faithfulness,
    suppress_if_unfaithful,
)
from lending_hub.assistant.ports import UnboundPort

CONTEXT = ["The processing fee is 1.5% of the sanctioned amount."]


class _Entailment:
    """A stub entailment model. Returns what the test tells it to.

    Not a model and not pretending to be one — it exists to exercise the
    aggregation and the suppression path, which are the deterministic halves.
    No score produced with it is reported anywhere.
    """

    def __init__(self, scores):
        self._scores = list(scores)
        self._calls = 0

    def entails(self, premise, claim):
        value = self._scores[min(self._calls, len(self._scores) - 1)]
        self._calls += 1
        return value


class TheModelIsNotFaked(unittest.TestCase):
    def test_scoring_without_a_model_raises(self):
        """The refusal that carries the module.

        A lexical-overlap fallback peaks where a negation was flipped, which is
        the case that matters most — so it is not a degraded scorer, it is an
        inverted one, and it would be reported as a passing faithfulness number.
        """
        with self.assertRaises(UnboundPort) as caught:
            score_faithfulness(
                "The fee is 1.5%.", CONTEXT, model=None, support_threshold=0.5
            )
        self.assertIn("negation", str(caught.exception))

    def test_the_support_threshold_has_no_default(self):
        """It is a property of the bound model, not of this code.

        A threshold calibrated for one NLI model means something else on
        another, so a default would be a number carried over from a model
        nobody is using.
        """
        with self.assertRaises(TypeError):
            score_faithfulness("x.", CONTEXT, model=_Entailment([0.9]))  # type: ignore[call-arg]

    def test_no_overlap_based_scoring_exists_in_the_module(self):
        """Checked by reading the source, because the temptation is real.

        Somebody will want a score during development and reach for word
        overlap; this fails if they add one.
        """
        import inspect

        import lending_hub.assistant.faithfulness as module

        source = inspect.getsource(module)
        self.assertNotIn("jaccard", source.lower())
        self.assertNotIn("set(claim", source)


class Decomposition(unittest.TestCase):
    def test_claims_are_extracted_per_sentence(self):
        claims = extract_claims("The fee is 1.5%. Documents are required. Apply online.")
        self.assertEqual(len(claims), 3)
        self.assertEqual([c.sentence_index for c in claims], [0, 1, 2])

    def test_the_granularity_deviation_is_stated_as_conservative(self):
        """This score is not comparable with a published RAGAS number.

        RAGAS splits a multi-claim sentence further. Sentence granularity scores
        a two-claim sentence with one unsupported half as one unsupported claim
        — lower than a finer decomposition, never higher — and saying so stops
        the comparison being made silently.
        """
        doc = extract_claims.__doc__ or ""
        self.assertIn("conservative", doc)
        self.assertIn("never higher", doc)

    def test_a_claim_carries_the_sentence_a_human_auditor_will_read(self):
        """The weekly audit turns a low score into a prompt, retrieval or corpus fix.

        "Claim 7 was unsupported" points at none of the three.
        """
        claims = extract_claims("First. Second.")
        self.assertEqual(claims[1].text, "Second.")


class Aggregation(unittest.TestCase):
    def test_the_gate_is_spec(self):
        """Phase 5 §7: answer faithfulness ≥ 97%."""
        self.assertEqual(FAITHFULNESS_GATE, 0.97)

    def test_the_score_is_supported_claims_over_total(self):
        score = score_faithfulness(
            "A. B. C. D.",
            CONTEXT,
            model=_Entailment([0.9, 0.9, 0.9, 0.1]),
            support_threshold=0.5,
        )
        self.assertAlmostEqual(score.score, 0.75)
        self.assertTrue(score.suppress)
        self.assertEqual(len(score.unsupported), 1)

    def test_a_fully_supported_answer_is_not_suppressed(self):
        score = score_faithfulness(
            "A. B.", CONTEXT, model=_Entailment([0.9]), support_threshold=0.5
        )
        self.assertEqual(score.score, 1.0)
        self.assertFalse(score.suppress)

    def test_an_answer_with_no_claims_is_refused_rather_than_scoring_one(self):
        """An empty answer is perfectly faithful by the formula and useless.

        A 1.0 from it would lift the weekly average exactly when the assistant
        was answering nothing — the metric moving in the wrong direction for the
        worst possible reason.
        """
        with self.assertRaises(FaithfulnessError):
            score_faithfulness("", CONTEXT, model=_Entailment([1.0]), support_threshold=0.5)

    def test_an_answer_with_no_context_is_refused(self):
        """Ungrounded is not unfaithful, and the two need different responses.

        Phase 5 §8 refuses and escalates where retrieval returned nothing; a
        faithfulness score of 0.0 would instead route it through the
        suppression path as a quality problem.
        """
        with self.assertRaises(FaithfulnessError):
            score_faithfulness("A.", [], model=_Entailment([1.0]), support_threshold=0.5)

    def test_the_best_supporting_passage_is_recorded(self):
        score = score_faithfulness(
            "A.",
            ["irrelevant", "the fee is 1.5%"],
            model=_Entailment([0.2, 0.95]),
            support_threshold=0.5,
        )
        self.assertEqual(score.verdicts[0].best_passage_index, 1)


class Suppression(unittest.TestCase):
    """§4: "below-threshold answers suppressed automatically"."""

    def test_a_suppressed_answer_carries_no_text(self):
        """Not a hedge, not a caveat, not a partial answer.

        §4 names the fallback as "let me connect you to an officer". A caveat on
        an unfaithful answer is an unfaithful answer that has been made harder
        to challenge.
        """
        answer = validate("The fee is 1.5%. [D@v1]", resolvable=["D@v1"])
        score = score_faithfulness(
            answer.text, CONTEXT, model=_Entailment([0.1]), support_threshold=0.5
        )
        disposition = suppress_if_unfaithful(answer, score)
        self.assertFalse(disposition.served)
        self.assertEqual(disposition.text, "")
        self.assertIn("withheld rather than hedged", disposition.handoff_reason)

    def test_the_type_refuses_a_suppressed_answer_that_still_holds_text(self):
        """The control is structural, so no caller can implement a soft version."""
        with self.assertRaises(FaithfulnessError):
            Disposition(served=False, text="here it is anyway", handoff_reason="unfaithful")

    def test_a_suppression_must_say_why(self):
        with self.assertRaises(FaithfulnessError):
            Disposition(served=False, text="")

    def test_a_faithful_answer_is_served(self):
        answer = validate("The fee is 1.5%. [D@v1]", resolvable=["D@v1"])
        score = score_faithfulness(
            answer.text, CONTEXT, model=_Entailment([0.99]), support_threshold=0.5
        )
        disposition = suppress_if_unfaithful(answer, score)
        self.assertTrue(disposition.served)
        self.assertIn("1.5%", disposition.text)

    def test_an_answer_already_handed_off_stays_handed_off(self):
        """The two controls compose; the validator's verdict is not re-litigated."""
        answer = validate("The rate is 12.5%.", resolvable=[])
        score = score_faithfulness(
            "anything.", CONTEXT, model=_Entailment([0.99]), support_threshold=0.5
        )
        self.assertFalse(suppress_if_unfaithful(answer, score).served)


class WeeklyAudit(unittest.TestCase):
    def test_the_sample_rate_is_spec(self):
        """SRS GA-6 and §4 WS-5.4: ≥ 2% of sessions weekly."""
        self.assertEqual(WEEKLY_AUDIT_SAMPLE_RATE, 0.02)

    def test_the_sample_rounds_up_because_the_requirement_is_a_floor(self):
        """2% of 1,050 is 21 sessions, and 20 is nearly meeting a floor."""
        self.assertEqual(audit_sample_size(1050), 21)
        self.assertEqual(audit_sample_size(1000), 20)

    def test_a_small_week_still_reviews_at_least_one_session(self):
        """30 sessions gives a mathematical sample of 0.6.

        An audit reviewing nothing that week would report full compliance with a
        2% rate, which is the arithmetic being correct and the control being
        absent.
        """
        self.assertEqual(audit_sample_size(30), 1)
        self.assertEqual(audit_sample_size(0), 0)


class Containment(unittest.TestCase):
    def test_containment_reports_a_rate_and_refuses_a_verdict(self):
        """LH-605, and the reason is sharper than "the target is unratified".

        Containment is the one metric in this phase that improves when the
        assistant gets more reckless — every handoff lowers it. A target set
        without the correct-escalation rate beside it rewards answering
        questions the assistant should refuse.
        """
        result = containment(sessions=1000, handoffs=200)
        self.assertAlmostEqual(result["containment_rate"], 0.8)
        self.assertIsNone(result["verdict"])
        self.assertIn("LH-605", result["target"])
        self.assertIn("more reckless", result["verdict_note"])

    def test_the_target_is_visible_in_the_criterion_text_itself(self):
        """Phase 5 §7 literally writes "containment ≥ [POLICY: target]".

        The only exit criterion in the programme that ships with its own
        placeholder inside the criterion.
        """
        self.assertIn("LH-605", str(CONTAINMENT_TARGET))

    def test_impossible_counts_are_refused(self):
        with self.assertRaises(FaithfulnessError):
            containment(sessions=10, handoffs=11)
        with self.assertRaises(FaithfulnessError):
            containment(sessions=-1, handoffs=0)


if __name__ == "__main__":
    unittest.main()

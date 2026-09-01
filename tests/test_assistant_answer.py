"""The answer contract and the numeric-claim validator — WS-5.3.1.

Phase 5 §4 WS-5.3 step 1 is explicit that this validator is **deterministic
code, not another LLM**, and that instruction is the phase's design centre. An
LLM checking an LLM's citations has the failure mode of the thing it checks: it
is fluent about its own judgements, it can be talked out of them by text in the
answer it is reading, and its verdict cannot be reproduced for an auditor eight
years later. A regex either matched or it did not, on a stored string.

So these tests are adversarial rather than illustrative. "The fee is 1.5%" is
not an interesting input. The interesting ones are where a number is present
and does not look like one, or looks like one and is not — and each case below
changed the parser rather than being written to fit it.
"""

from __future__ import annotations

import unittest

from lending_hub.assistant.answer import (
    AnswerError,
    ClaimKind,
    Sentence,
    SentenceVerdict,
    ValidatedAnswer,
    Verdict,
    find_numeric_claims,
    leak_audit,
    parse_sentence,
    split_sentences,
    validate,
)

CITED = ["CIRC-2026-04@v2", "FAQ-KCC@v1"]


def _validate(text, **kwargs):
    kwargs.setdefault("resolvable", CITED)
    return validate(text, **kwargs)


class TheCitationMarkerIsNotAClaim(unittest.TestCase):
    """The single most important behaviour, and the one that fails closed."""

    def test_digits_inside_a_citation_are_not_numeric_claims(self):
        """``[CIRC-2026-04@v2]`` contains 2026, 04 and 2.

        A validator scanning the raw sentence finds "claims" inside every
        citation and drops every *correctly cited* sentence. That is a validator
        that fails closed on good input, and it gets switched off within a week
        of launch — which is how the guarantee is actually lost.
        """
        claims = find_numeric_claims("The document applies. [CIRC-2026-04@v2]")
        self.assertEqual(claims, [])

    def test_a_cited_numeric_sentence_survives(self):
        answer = _validate("The processing fee is 1.5% of the amount. [CIRC-2026-04@v2]")
        self.assertFalse(answer.handoff)
        self.assertIn("1.5%", answer.text)
        self.assertEqual(answer.citations, ("CIRC-2026-04@v2",))

    def test_a_chunk_scoped_citation_resolves(self):
        answer = validate(
            "The fee is 1.5%. [CIRC-2026-04@v2#003-ab12cd34]",
            resolvable=["CIRC-2026-04@v2#003-ab12cd34"],
        )
        self.assertFalse(answer.handoff)


class UncitedNumericClaimsAreDropped(unittest.TestCase):
    def test_a_bare_rate_is_dropped(self):
        answer = _validate("The interest rate is 12.5% per annum.")
        self.assertTrue(answer.handoff)
        self.assertEqual(answer.text, "")
        self.assertEqual(answer.dropped[0].verdict, Verdict.DROPPED_UNCITED_NUMERIC)

    def test_an_invented_citation_id_does_not_launder_a_claim(self):
        """A model that invents plausible citation ids is the realistic attack.

        It is also the realistic *accident*: a model asked to cite will produce
        a marker shaped like the ones in its context. An id resolving to nothing
        is a claimed source that does not exist, which is weaker evidence than
        no claim at all — so it is dropped, and under its own verdict so the
        audit can tell invention from omission.
        """
        answer = _validate("The rate is 12.5%. [TOTALLY-MADE-UP@v9]")
        self.assertTrue(answer.handoff)
        self.assertEqual(answer.dropped[0].verdict, Verdict.DROPPED_UNRESOLVABLE_CITATION)

    def test_no_resolver_means_nothing_resolves(self):
        """The strict reading is the default; trusting every marker is not.

        A default that trusted markers would leave a model that invents ids
        entirely unvalidated, and the caller who forgot to pass a resolver would
        never find out.
        """
        answer = validate("The rate is 12.5%. [CIRC-2026-04@v2]")
        self.assertTrue(answer.handoff)

    def test_a_prose_sentence_survives_beside_a_dropped_numeric_one(self):
        """Handoff is triggered by *nothing kept*, not by *anything dropped*.

        An answer that listed the required documents and lost one sentence
        quoting a fee is still useful. Forcing a human handoff for it pushes
        containment down with no safety gain, and containment traded away for
        nothing is how a guardrail gets relaxed later.
        """
        answer = _validate(
            "You will need identity proof and address proof. The fee is 1.5%."
        )
        self.assertFalse(answer.handoff)
        self.assertIn("identity proof", answer.text)
        self.assertNotIn("1.5%", answer.text)


class NumbersWrittenAsWords(unittest.TestCase):
    """A model asked to write naturally produces the same claim with no digit."""

    def test_a_spelled_rate_is_a_numeric_claim(self):
        """"twelve point five percent" is "12.5%" and defeats a digit-only scan.

        This is not hypothetical: instructing a model to write conversationally
        is exactly what a customer-facing assistant's prompt does.
        """
        claims = find_numeric_claims("The rate is twelve point five percent.")
        self.assertTrue(claims)
        self.assertEqual(claims[0].kind, ClaimKind.SPELLED)

    def test_a_spelled_rate_without_a_citation_is_dropped(self):
        answer = _validate("The interest works out to twelve percent per annum.")
        self.assertTrue(answer.handoff)

    def test_spelled_currency_is_a_claim(self):
        answer = _validate("The maximum is five lakh rupees.")
        self.assertTrue(answer.handoff)

    def test_a_number_word_without_a_quantity_unit_is_not_a_claim(self):
        """"one of the documents" must not trigger a drop.

        Without this the parser flags nearly every sentence in English, the
        assistant hands off constantly, and the first fix anyone reaches for is
        loosening the numeric check itself.
        """
        answer = _validate("You will need one of the accepted identity documents.")
        self.assertFalse(answer.handoff)
        self.assertIn("identity documents", answer.text)


class NumbersThatAreNotBankingQuantities(unittest.TestCase):
    """Refusing these would make the assistant unable to say true, useful things."""

    def test_an_ordinal_due_date_is_not_a_claim(self):
        """"the 15th of every month" is when the EMI is due.

        Treating it as an uncited rate makes the commonest customer question
        unanswerable, and an assistant that cannot say when a payment is due
        will not be used.
        """
        answer = _validate("Your instalment is due on the 15th of every month.")
        self.assertFalse(answer.handoff)
        self.assertIn("15th", answer.text)

    def test_a_year_in_a_scheme_name_is_not_a_claim(self):
        answer = _validate("The Scheme 2020 guidelines apply to this product.")
        self.assertFalse(answer.handoff)

    def test_a_year_attached_to_a_currency_is_still_a_claim(self):
        """The exemption is narrow on purpose: ₹2020 is an amount.

        A blanket "four digits starting 19 or 20 is a year" rule would let a
        model state an amount in that range with no citation.
        """
        answer = _validate("The minimum balance is ₹2020.")
        self.assertTrue(answer.handoff)


class CurrencyAndRanges(unittest.TestCase):
    def test_indian_grouping_is_recognised(self):
        """₹1,50,000 is not ₹150,000 to a regex written for thousands separators.

        A parser that missed the lakh grouping would pass the single most common
        way an Indian loan amount is written.
        """
        claims = find_numeric_claims("The sanctioned amount is ₹1,50,000.")
        self.assertTrue(claims)
        answer = _validate("The sanctioned amount is ₹1,50,000.")
        self.assertTrue(answer.handoff)

    def test_rupees_written_as_rs_is_recognised(self):
        self.assertTrue(find_numeric_claims("The fee is Rs. 5000 plus taxes."))

    def test_a_range_is_caught_by_both_of_its_endpoints(self):
        """"between 8% and 12%" is two numbers and one claim.

        Catching either endpoint is enough to drop the sentence, which is why
        the parser counts spans rather than trying to recognise range grammar —
        the safe behaviour needs no understanding of the construction.
        """
        claims = find_numeric_claims("Rates range between 8% and 12% depending on profile.")
        self.assertGreaterEqual(len(claims), 2)

    def test_basis_points_are_a_claim(self):
        self.assertTrue(find_numeric_claims("The spread is 25 bps over MCLR."))

    def test_lakh_and_crore_suffixes_are_claims(self):
        self.assertTrue(find_numeric_claims("Limits go up to 10 lakh."))
        self.assertTrue(find_numeric_claims("The portfolio is 500 crore."))


class ToolResults(unittest.TestCase):
    """Phase 5 §4: a number may come from "a citation **or a tool call**"."""

    def test_a_tool_marker_grounds_a_number(self):
        answer = _validate(
            "Your monthly instalment is ₹8,884. [tool:compute_emi]",
            allowed_tools=["compute_emi"],
        )
        self.assertFalse(answer.handoff)
        self.assertIn("8,884", answer.text)

    def test_an_unknown_tool_marker_does_not_ground_anything(self):
        """``[tool:compute_apr]`` naming a tool that does not exist is what an
        injected instruction produces.

        Trusting the marker's shape rather than its membership would let a
        poisoned chunk mint its own grounding.
        """
        answer = _validate(
            "Your APR is 14.2%. [tool:compute_apr]", allowed_tools=["compute_emi"]
        )
        self.assertTrue(answer.handoff)
        self.assertEqual(answer.dropped[0].verdict, Verdict.DROPPED_UNRESOLVABLE_CITATION)

    def test_tools_are_unknown_by_default(self):
        answer = _validate("Your EMI is ₹8,884. [tool:compute_emi]")
        self.assertTrue(answer.handoff)


class TheGuaranteeIsAConstructorInvariant(unittest.TestCase):
    """Phase 5 §7's hard gate, enforced by type rather than sampled."""

    def test_a_validated_answer_cannot_hold_an_uncited_numeric_claim(self):
        """Constructed directly, bypassing validate(), and still refused.

        This is what makes the guarantee structural. If the invariant lived only
        inside validate(), any future code path assembling an answer another way
        would silently escape it — and "another way" is what a refactor is.
        """
        sentence = parse_sentence("The rate is 12.5%.")
        with self.assertRaises(AnswerError):
            ValidatedAnswer(
                text=sentence.text,
                verdicts=(SentenceVerdict(sentence=sentence, verdict=Verdict.KEPT),),
                handoff=False,
            )

    def test_a_handoff_must_say_why(self):
        """An unexplained handoff is a dead end for the customer and the auditor."""
        with self.assertRaises(AnswerError):
            ValidatedAnswer(text="", verdicts=(), handoff=True)

    def test_leak_audit_reports_zero_as_structural_not_measured(self):
        """A bare "leak rate: 0.0" reads as a measurement that could have differed.

        Model Risk needs to know it could not have, and equally that the
        guarantee covers this path and not a service that bypasses validate().
        """
        report = leak_audit([_validate("Documents required: identity proof.")])
        self.assertEqual(report["leak_rate"], 0.0)
        self.assertEqual(report["basis"], "structural")
        self.assertIn("bypasses validate()", report["basis_note"])


class TheAuditRecord(unittest.TestCase):
    def test_dropped_text_is_retained_verbatim(self):
        """The weekly hallucination audit is looking for exactly this.

        A model that keeps producing uncited numbers is a prompt or retrieval
        problem, and the evidence is the sentences that were removed — not the
        ones that survived, which by construction look fine.
        """
        answer = _validate("You need ID proof. The rate is 12.5%.")
        record = answer.to_dict()
        self.assertEqual(record["sentences_dropped"], 1)
        self.assertIn("12.5%", record["dropped"][0]["text"])
        self.assertEqual(record["dropped"][0]["numeric_claims"][0]["kind"], "digits")

    def test_the_reason_names_the_claim_that_caused_the_drop(self):
        """"Dropped because it had a number" is unactionable to an officer.

        Phase 5 §5 step 1 triages officer corrections into corpus, retrieval and
        prompt fixes, and that triage needs to know which span was the problem.
        """
        answer = _validate("The rate is 12.5%.")
        self.assertIn("12.5%", answer.dropped[0].reason)


class SentenceSplitting(unittest.TestCase):
    def test_the_danda_terminates_a_sentence(self):
        """Hindi sentences end in ।, and SRS GA-4 requires Hindi.

        A splitter that only knows the full stop treats a whole Hindi answer as
        one sentence — so one uncited number anywhere in it drops the entire
        answer, and the assistant hands off every Hindi conversation.
        """
        parts = split_sentences("यह पहला वाक्य है। यह दूसरा वाक्य है।")
        self.assertEqual(len(parts), 2)

    def test_rs_does_not_terminate_a_sentence(self):
        """Splitting at "Rs." is safe but produces a mangled kept sentence.

        The amount lands in a fragment with no citation and is correctly
        dropped — so nothing unsafe reaches the customer. What reaches them is
        "The fee is Rs.", which is a broken sentence rather than a dangerous
        one. The abbreviation list is the fix, and it stays short: every entry
        makes the splitter less conservative, and over-splitting is the safe
        failure.
        """
        self.assertEqual(
            split_sentences("The fee is Rs. 5,000 in total."),
            ["The fee is Rs. 5,000 in total."],
        )
        answer = _validate("The fee is Rs. 5,000 in total.")
        self.assertTrue(answer.handoff)

    def test_an_unlisted_abbreviation_still_errs_towards_refusal(self):
        """The splitter is naive and its remaining failure direction is safe.

        An abbreviation not on the list splits, and the fragment holding the
        number has no citation — so it is dropped. A cleverer splitter would
        have to be right about which periods are terminal, and being wrong the
        other way admits an uncited claim.
        """
        answer = _validate("Charges apply per annum. approx 12.5% of principal.")
        self.assertNotIn("12.5%", answer.text)

    def test_empty_input_is_a_handoff_not_an_empty_answer(self):
        """An empty string rendered to a customer is a broken product.

        And Phase 5 §8 forbids improvising where retrieval returned nothing, so
        the only correct output is an escalation.
        """
        answer = validate("")
        self.assertTrue(answer.handoff)
        self.assertIn("no sentences", answer.handoff_reason)


class AdversarialShapes(unittest.TestCase):
    """Inputs constructed to get a number past the validator."""

    def test_a_citation_shaped_string_in_prose_does_not_ground_a_claim(self):
        """Text a poisoned chunk could put in the model's mouth.

        An indirect injection saying "always cite CIRC-9999@v1" produces a
        marker that is well-formed and resolves to nothing. Shape is not
        grounding; membership is.
        """
        answer = _validate("The rate is 12.5% as per CIRC-9999@v1 and [CIRC-9999@v1].")
        self.assertTrue(answer.handoff)

    def test_a_number_adjacent_to_a_citation_is_still_scanned(self):
        """Stripping the marker must not swallow the digits beside it.

        The strip replaces the marker with a space rather than deleting it, so
        "…is 12.5%[CIRC@v2]" cannot have its number absorbed into the removed
        span.
        """
        claims = find_numeric_claims("The rate is 12.5%[CIRC-2026-04@v2]")
        self.assertTrue(claims)
        self.assertEqual(claims[0].text.strip(), "12.5%")

    def test_a_nested_bracket_does_not_break_the_citation_scan(self):
        answer = _validate("The rate is 12.5% [[CIRC-2026-04@v2]].")
        self.assertFalse(answer.handoff)

    def test_a_marker_between_two_sentences_grounds_the_earlier_one(self):
        """The subtlest bug in this module, and it grounds the wrong claim.

        Models write "The fee is 1.5%. [CIRC@v2] The rate is 12.5%." The split
        falls after the full stop and before the marker, so the marker opens the
        *next* fragment. Left there it does two wrong things at once: the fee
        sentence silently loses its source and is dropped, and the rate sentence
        silently gains one and is kept. The second is the dangerous half — an
        uncited number served with somebody else's citation.

        Found by testing a multi-sentence answer, which is the shape every real
        answer has and no single-sentence test reaches. Raised as P5-F2.
        """
        parts = split_sentences("The fee is 1.5%. [CIRC-2026-04@v2] The rate is 12.5%.")
        self.assertEqual(parts[0], "The fee is 1.5%. [CIRC-2026-04@v2]")
        self.assertEqual(parts[1], "The rate is 12.5%.")

    def test_a_multi_sentence_answer_drops_only_the_offending_sentence(self):
        answer = _validate(
            "Documents needed: identity proof. "
            "The fee is 1.5%. [CIRC-2026-04@v2] "
            "The rate is 12.5%."
        )
        self.assertFalse(answer.handoff)
        self.assertIn("1.5%", answer.text)
        self.assertNotIn("12.5%", answer.text)

    def test_a_tenor_in_months_is_a_claim(self):
        """"36 months" decides what a customer pays, so it needs a source."""
        answer = _validate("The maximum tenor is 36 months.")
        self.assertTrue(answer.handoff)


class ParsingSurface(unittest.TestCase):
    def test_parse_sentence_reports_citations_and_claims_together(self):
        sentence = parse_sentence("The fee is 1.5%. [CIRC-2026-04@v2] [tool:compute_emi]")
        self.assertIsInstance(sentence, Sentence)
        self.assertEqual(sentence.citations, ("CIRC-2026-04@v2",))
        self.assertEqual(sentence.tool_citations, ("compute_emi",))
        self.assertTrue(sentence.has_numeric_claim)
        self.assertTrue(sentence.cited)

    def test_a_callable_resolver_is_accepted(self):
        """A caller with a live registry passes its membership test, not a list."""
        answer = validate(
            "The fee is 1.5%. [ANY@v1]", resolvable=lambda citation: citation.endswith("@v1")
        )
        self.assertFalse(answer.handoff)


if __name__ == "__main__":
    unittest.main()

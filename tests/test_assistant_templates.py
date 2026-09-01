"""Adverse-action templates keyed to P1 reason codes — WS-5.3.3.

SRS GA-3 and Phase 5 §4 WS-5.3 step 3: the assistant explains decisions only by
selecting and ordering pre-approved templates, and never composes a new
decision-explanation sentence.

The rule is absolute rather than a quality bar, and the reason is worth keeping
in view while reading these tests. An adverse-action statement is a legal
communication in a specific form. A model that paraphrased an approved sentence
into something clearer would produce a sentence Compliance never approved — and
it would be *better written*, which makes it more likely to survive review and
reach a customer.
"""

from __future__ import annotations

import unittest

from lending_hub.definitions.provenance import Pending, Ungrounded
from lending_hub.assistant.templates import (
    Explanation,
    Template,
    TemplateError,
    TemplateLibrary,
    UnmappedCode,
    explain_decision,
    from_reason_table,
    library_report,
    load_default_library,
)
from lending_hub.scoring.reasons import load_table

APPROVED = "Your recent credit enquiries were higher than we can accept."


def _pending(code="CS_BUREAU_ENQUIRIES_HIGH", language="en") -> Template:
    return Template(
        code=code,
        language=language,
        body=Pending(owner="Compliance", ticket="LH-603", note=f"sentence for {code}"),
    )


def _approved(code="CS_BUREAU_ENQUIRIES_HIGH", language="en", body=APPROVED, slots=()) -> Template:
    return Template(code=code, language=language, body=body, slots=slots)


class NothingIsComposed(unittest.TestCase):
    """The guarantee, checked as a property of the module rather than a promise."""

    def test_an_unratified_template_raises_rather_than_rendering(self):
        """A plausible draft rendered "just for the demo" outlives the demo.

        And unlike a draft number, a draft sentence looks finished — it is
        grammatical, it is in the right register, and nothing about it says it
        was never approved.
        """
        with self.assertRaises(Ungrounded):
            _pending().render()

    def test_an_explanation_will_not_render_a_ratified_subset(self):
        """All-or-nothing, because the partial mode is the failure itself.

        Stating some principal reasons and silently dropping the rest is exactly
        what adverse-action rules forbid — and it would look like a working
        feature, which is why there is no partial mode to be tempted by.
        """
        library = TemplateLibrary([_approved("A"), _pending("B")])
        explanation = explain_decision([("A", 0.4), ("B", 0.3)], library, language="en")
        self.assertFalse(explanation.renderable)
        with self.assertRaises(Ungrounded) as caught:
            explanation.render()
        self.assertIn("B", str(caught.exception))

    def test_the_explanation_holds_templates_not_text(self):
        """Selection is auditable and correct even when the sentences do not exist.

        A type holding strings could not be constructed here at all, and the
        ordering logic would have gone untested until Compliance delivered —
        which is when it would first be exercised, under launch pressure.
        """
        library = TemplateLibrary([_pending("A"), _pending("B")])
        explanation = explain_decision([("A", 0.4), ("B", 0.3)], library, language="en")
        self.assertEqual([s.code for s in explanation.selected], ["A", "B"])
        self.assertFalse(explanation.renderable)

    def test_an_undeclared_slot_is_refused(self):
        """Substituting a value the template did not declare is composition.

        It is the smallest possible way to compose — one word — and it is the
        one that would be argued for as "just personalisation".
        """
        template = _approved(body="Your enquiries were {n} in the last year.", slots=("n",))
        self.assertIn("5", template.render({"n": 5}))
        with self.assertRaises(TemplateError):
            template.render({"n": 5, "name": "A"})

    def test_an_unfilled_slot_is_refused(self):
        """A template with a hole in it is a different sentence, not a shorter one."""
        template = _approved(body="Your enquiries were {n}.", slots=("n",))
        with self.assertRaises(TemplateError):
            template.render()

    def test_the_audit_record_says_nothing_was_composed(self):
        library = TemplateLibrary([_pending("A")])
        record = explain_decision([("A", 0.4)], library, language="en").to_dict()
        self.assertIn("composed", record["composition_note"])
        self.assertEqual(record["codes"][0]["code"], "A")


class OrderingIsCompliance(unittest.TestCase):
    """Adverse-action rules require the *principal* reasons, in that order."""

    def test_the_contribution_order_is_preserved_not_re_derived(self):
        """Re-sorting on severity, brevity or readability states the wrong reasons.

        P1's map_reasons already ordered by SHAP contribution. Any other order
        would put a reason that is not principal in the first position, which is
        the specific failure the rules exist to prevent — and the tempting
        re-sorts (shortest first, most serious first) all read as improvements.
        """
        library = TemplateLibrary([_approved(c) for c in ("A", "B", "C")])
        explanation = explain_decision(
            [("C", 0.5), ("A", 0.3), ("B", 0.1)], library, language="en"
        )
        self.assertEqual([s.code for s in explanation.selected], ["C", "A", "B"])
        self.assertEqual([s.position for s in explanation.selected], [1, 2, 3])

    def test_truncation_drops_the_least_influential_reasons(self):
        """Safe only because the incoming order is by contribution.

        Truncating any other order would drop principal reasons and keep
        incidental ones, which is why max_reasons takes from the front rather
        than selecting.
        """
        library = TemplateLibrary([_approved(c) for c in ("A", "B", "C")])
        explanation = explain_decision(
            [("C", 0.5), ("A", 0.3), ("B", 0.1)], library, language="en", max_reasons=2
        )
        self.assertEqual([s.code for s in explanation.selected], ["C", "A"])

    def test_zero_reasons_requested_is_refused(self):
        library = TemplateLibrary([_approved("A")])
        with self.assertRaises(TemplateError):
            explain_decision([("A", 0.4)], library, language="en", max_reasons=0)


class MissingTemplatesEscalate(unittest.TestCase):
    def test_a_missing_code_escalates_the_whole_explanation(self):
        """A partial explanation omits a principal reason, which is worse than none.

        There is no branch here that explains what it can and stays quiet about
        the rest, and adding one would be the single easiest way to reintroduce
        the failure.
        """
        library = TemplateLibrary([_approved("A")])
        explanation = explain_decision([("A", 0.4), ("MISSING", 0.3)], library, language="en")
        self.assertTrue(explanation.escalate)
        self.assertEqual(explanation.selected, ())
        self.assertIn("MISSING", explanation.escalation_reason)

    def test_a_language_with_no_templates_escalates_rather_than_falling_back(self):
        """Falling back to English is a decision explained in a language the
        customer may not read.

        And it is the fallback everybody reaches for, because it produces
        *something*. SRS GA-4 requires the customer's language; an explanation
        they cannot read is not one.
        """
        library = TemplateLibrary([_approved("A", language="en")])
        explanation = explain_decision([("A", 0.4)], library, language="hi")
        self.assertTrue(explanation.escalate)

    def test_no_reason_codes_at_all_escalates(self):
        """A decision explained with no reasons is not an explanation."""
        explanation = explain_decision([], TemplateLibrary(), language="en")
        self.assertTrue(explanation.escalate)

    def test_an_explanation_cannot_be_silently_empty(self):
        """The constructor refuses the state, so no path can produce it."""
        with self.assertRaises(TemplateError):
            Explanation(language="en", selected=())

    def test_an_escalation_must_say_why(self):
        with self.assertRaises(TemplateError):
            Explanation(language="en", selected=(), escalate=True)


class LibraryShape(unittest.TestCase):
    def test_two_templates_for_one_code_and_language_are_refused(self):
        """Two approved sentences means the choice between them is made in code.

        Which is the thing the whole library exists to prevent: once code picks,
        the picking logic is an unreviewed part of an adverse-action
        communication.
        """
        library = TemplateLibrary([_approved("A")])
        with self.assertRaises(TemplateError):
            library.add(_approved("A", body="A different approved sentence."))

    def test_the_library_shape_comes_from_the_p1_dictionary(self):
        """The code→feature mapping has one home, and it is P1's.

        A second list of codes here would drift the moment a reason code is
        added, and the drift surfaces as a decline nobody can explain.
        """
        table = load_table()
        library = from_reason_table(table)
        self.assertEqual(set(library.codes), {entry.code for entry in table.entries})

    def test_every_body_from_the_p1_table_is_pending_on_lh_603(self):
        """This is the library's *shape*, not a stub of it.

        Compliance receives an exact list of the sentences they owe, per code
        and per language, rather than a request to "write the templates".
        """
        library = load_default_library()
        for code in library.codes:
            self.assertFalse(library.get(code, "en").ratified)

    def test_coverage_reports_holes_before_launch_rather_than_during(self):
        """§4 WS-5.3.4 says a language ships only when its slice passes the gates.

        A language whose template set has holes cannot pass anything, and
        finding the hole in a live conversation with a declined applicant is the
        expensive way to learn it.
        """
        library = TemplateLibrary([_approved("A"), _pending("B")])
        coverage = library.coverage(["A", "B", "C"], "en")
        self.assertEqual(coverage["missing_template"], ["C"])
        self.assertEqual(coverage["template_unratified"], ["B"])
        self.assertFalse(coverage["complete"])


class Report(unittest.TestCase):
    def test_the_report_says_nothing_is_ratified_and_names_all_three_tickets(self):
        """LH-603, LH-203 and LH-610 are different blockers on one deliverable.

        LH-203 is one sentence per code for a letter; LH-603 is the
        conversational set with its ordering rules and disclosures; LH-610 is
        which languages. Ratifying any one of them does not produce the others,
        and a report naming only the first would read as nearly done.
        """
        report = library_report(load_default_library())
        self.assertFalse(report["any_ratified"])
        self.assertEqual(report["blocking_tickets"], ["LH-603", "LH-203", "LH-610"])
        self.assertIn("composes", report["note"])

    def test_the_report_pins_the_reason_table_version(self):
        """A template set is only correct against one version of the code list."""
        table = load_table()
        report = library_report(from_reason_table(table), table)
        self.assertEqual(report["reason_table_version"], table.version())


if __name__ == "__main__":
    unittest.main()

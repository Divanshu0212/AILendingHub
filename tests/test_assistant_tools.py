"""Allow-listed, schema-validated tools — WS-5.3.2.

Phase 5 §4 WS-5.3 step 2: "LLM arithmetic is forbidden — EMIs and eligibility
amounts always come from tools." The obvious reading is a prompt rule, and a
prompt rule is a request. The structural reading is that there must be exactly
one place an EMI can come from, and these tests pin that it is
``lending_hub.reco.feasible.emi`` rather than a second implementation written
for the assistant.

The other half is the allow-list. An unknown tool name is denied before
dispatch, because Greshake et al.'s indirect injection produces exactly that — a
retrieved chunk asking for a function nobody registered — and the difference
between a deny-list and an allow-list is whether the attacker chooses the
vocabulary.
"""

from __future__ import annotations

import unittest

from lending_hub.assistant.tools import (
    Effect,
    RateLimiter,
    SchemaError,
    Tool,
    ToolDenied,
    ToolError,
    ToolRegistry,
    ToolUnavailable,
    compute_emi,
    launch_registry,
    validate_arguments,
)
from lending_hub.reco.feasible import emi as reference_emi


class OneReferenceImplementation(unittest.TestCase):
    """Master §2 rule 2 — and why a second EMI is worse than no EMI."""

    def test_compute_emi_agrees_with_the_reference_exactly(self):
        """Not "closely" — exactly, up to the tool's own rounding.

        A second EMI function would agree on the happy path and diverge on the
        edges: a zero rate, a rounding convention, whether the first instalment
        is due immediately. The customer is then told one number in chat and
        quoted another in the sanction letter, both by the bank's own code, and
        reconciling them means discovering neither was authoritative.
        """
        for principal, rate, months in [
            (500_000, 0.125, 60),
            (1_500_000, 0.0875, 240),
            (100_000, 0.0, 12),
            (250_000, 0.24, 6),
        ]:
            with self.subTest(principal=principal, rate=rate, months=months):
                self.assertAlmostEqual(
                    compute_emi(principal, rate, months)["emi"],
                    round(reference_emi(principal, rate, months), 2),
                    places=2,
                )

    def test_the_tool_module_contains_no_emi_arithmetic(self):
        """The guarantee is delegation, and delegation is checkable.

        If someone later inlines the formula "for speed", this fails — which is
        the only way the rule survives a refactor by a person who has not read
        Master §2.
        """
        import inspect

        import lending_hub.assistant.tools as module

        source = inspect.getsource(module)
        self.assertNotIn("** months", source)
        self.assertIn("from lending_hub.reco.feasible import", source)

    def test_the_reference_implementations_errors_surface_as_tool_errors(self):
        """A negative rate is a data error, and the reference already refuses it.

        The tool must not soften that into a plausible instalment: an EMI
        computed from a negative rate is below the straight-line repayment and
        passes every affordability test.
        """
        with self.assertRaises(ToolError):
            compute_emi(100_000, -0.05, 12)

    def test_the_tool_does_not_look_up_a_rate(self):
        """A rate-fetching tool is the easiest place to reintroduce staleness.

        The number would carry a tool citation and never touch the
        effective-date filter — a stale rate laundered into groundedness.
        """
        result = compute_emi(500_000, 0.125, 60)
        self.assertIn("retrieval-only", result["rate_source"])
        self.assertIn("annual_rate", result)


class TheAllowList(unittest.TestCase):
    def test_an_unregistered_name_is_denied_before_dispatch(self):
        """The injection case, and it must not be attempted-then-failed.

        "Call transfer_funds" arriving from a retrieved chunk should never reach
        a dispatcher at all, and the denial is its own exception type so it can
        be counted as a security event rather than lost among argument errors.
        """
        registry = launch_registry()
        with self.assertRaises(ToolDenied):
            registry.call("transfer_funds", {"amount": 1})

    def test_the_denial_names_what_is_registered(self):
        registry = launch_registry()
        with self.assertRaises(ToolDenied) as caught:
            registry.get("nope")
        self.assertIn("compute_emi", str(caught.exception))

    def test_the_four_launch_tools_are_exactly_the_four_named(self):
        """Phase 5 §4 WS-5.3 step 2 names four; a fifth is a scope change."""
        self.assertEqual(
            launch_registry().names,
            ("book_branch_slot", "compute_emi", "get_application_status", "get_document_checklist"),
        )

    def test_the_registry_cannot_be_extended_through_launch_registry(self):
        """Adding a tool is a deliberate act at a reviewable call site.

        A keyword argument that accepted extra tools would make the allow-list
        configurable by whoever assembles the service, which is the same as not
        having one.
        """
        with self.assertRaises(TypeError):
            launch_registry(extra_tools=[])  # type: ignore[call-arg]

    def test_effects_are_recorded_per_tool(self):
        """Phase 5 §4: "all read-only or workflow-safe".

        Three of the four read and one books an appointment. A registry that
        could not tell them apart could not enforce the rule, so the claim would
        live in a document rather than in the code.
        """
        registry = launch_registry()
        self.assertEqual(registry.get("compute_emi").effect, Effect.READ_ONLY)
        self.assertEqual(registry.get("book_branch_slot").effect, Effect.WORKFLOW_SAFE)

    def test_a_tool_name_that_could_forge_a_citation_marker_is_refused(self):
        """The name appears inside the answer's grounding marker.

        A name carrying brackets could close the marker early and open a
        document citation, which is a tool minting its own document evidence.
        """
        with self.assertRaises(ToolError):
            Tool(
                name="evil]tool",
                description="x",
                schema={"type": "object"},
                effect=Effect.READ_ONLY,
                function=lambda: None,
            )

    def test_duplicate_registration_is_refused(self):
        registry = ToolRegistry()
        tool = Tool(
            name="t", description="d", schema={"type": "object"},
            effect=Effect.READ_ONLY, function=lambda: 1,
        )
        registry.register(tool)
        with self.assertRaises(ToolError):
            registry.register(tool)


class SchemaValidation(unittest.TestCase):
    SCHEMA = {
        "type": "object",
        "properties": {
            "principal": {"type": "number", "exclusiveMinimum": 0},
            "months": {"type": "integer", "minimum": 1, "maximum": 480},
            "product": {"type": "string", "enum": ["kcc", "personal_loan"]},
        },
        "required": ["principal"],
        "additionalProperties": False,
    }

    def test_an_unsupported_keyword_raises_rather_than_being_ignored(self):
        """The worst possible outcome for a validator is silent partial coverage.

        A skipped keyword is a validator reporting a success it did not perform,
        and the caller has no way to know which constraints were actually
        checked.
        """
        with self.assertRaises(SchemaError):
            validate_arguments({"type": "object", "oneOf": []}, {})
        with self.assertRaises(SchemaError):
            validate_arguments(
                {"type": "object", "properties": {"x": {"format": "email"}}}, {"x": "a"}
            )

    def test_extra_arguments_are_rejected_by_default(self):
        """JSON Schema defaults to permissive; here it must not.

        An undeclared argument is a model hallucinating a parameter or an
        injection attempting one, and neither should reach a function.
        """
        with self.assertRaises(SchemaError):
            validate_arguments(self.SCHEMA, {"principal": 1.0, "secret": True})

    def test_missing_required_arguments_are_rejected(self):
        with self.assertRaises(SchemaError):
            validate_arguments(self.SCHEMA, {})

    def test_a_boolean_is_not_an_integer(self):
        """``bool`` subclasses ``int`` in Python, so this passes without a check.

        A boolean accepted where a tenor is expected then computes an EMI over
        one month, which is a real number for the wrong question.
        """
        with self.assertRaises(SchemaError):
            validate_arguments(self.SCHEMA, {"principal": 1.0, "months": True})

    def test_bounds_and_enums_are_enforced(self):
        with self.assertRaises(SchemaError):
            validate_arguments(self.SCHEMA, {"principal": 0})
        with self.assertRaises(SchemaError):
            validate_arguments(self.SCHEMA, {"principal": 1.0, "months": 600})
        with self.assertRaises(SchemaError):
            validate_arguments(self.SCHEMA, {"principal": 1.0, "product": "gold"})

    def test_a_valid_call_passes(self):
        validate_arguments(self.SCHEMA, {"principal": 1.0, "months": 60, "product": "kcc"})

    def test_the_launch_schemas_reject_an_absurd_tenor(self):
        """Bounds on the launch tools are not decoration.

        A 10,000-month tenor produces a tiny EMI and a plausible-looking answer,
        and nothing downstream of the tool would question it.
        """
        registry = launch_registry()
        with self.assertRaises(SchemaError):
            registry.call("compute_emi", {"principal": 1e6, "annual_rate": 0.1, "months": 10_000})

    def test_the_launch_schemas_reject_a_rate_given_as_a_percentage(self):
        """12.5 instead of 0.125 is the commonest possible caller error.

        Unbounded it computes an EMI at 1250% and returns it without complaint,
        and the customer sees a number that is wrong by two orders of magnitude
        but perfectly formatted.
        """
        registry = launch_registry()
        with self.assertRaises(SchemaError):
            registry.call("compute_emi", {"principal": 1e6, "annual_rate": 12.5, "months": 60})


class UnboundBackends(unittest.TestCase):
    """Three of the four launch tools reach systems that are not deployed."""

    def test_application_status_refuses_rather_than_inventing_one(self):
        """"Your application is under review" is a claim about a real customer.

        Invented by a chat assistant, it is indistinguishable to that customer
        from the truth — which is a sharper version of the usual port argument,
        because the subject of the false statement is the person reading it.
        """
        registry = launch_registry()
        with self.assertRaises(ToolUnavailable):
            registry.call("get_application_status", {"application_id": "APP-1"})

    def test_the_checklist_refuses_and_names_the_corpus_ticket(self):
        registry = launch_registry()
        with self.assertRaises(ToolUnavailable) as caught:
            registry.call("get_document_checklist", {"product": "kcc"})
        self.assertIn("LH-601", str(caught.exception))

    def test_unavailable_is_distinct_from_denied(self):
        """The assistant's correct response differs: escalate, versus refuse.

        Folding them together means a missing backend looks like an attack, and
        an attack looks like an outage.
        """
        registry = launch_registry()
        with self.assertRaises(ToolUnavailable):
            registry.call("book_branch_slot", {
                "branch_id": "B1", "slot_iso": "2026-07-01T10:00", "application_id": "A1",
            })

    def test_a_bound_port_is_used(self):
        class _Status:
            def status(self, application_id):
                return {"application_id": application_id, "stage": "underwriting"}

        registry = launch_registry(status_port=_Status())
        result = registry.call("get_application_status", {"application_id": "APP-7"})
        self.assertEqual(result.value["stage"], "underwriting")


class Grounding(unittest.TestCase):
    def test_a_tool_result_carries_the_marker_that_grounds_it(self):
        """The marker is produced here, not composed by the model.

        A model that writes its own tool markers can write one for a call it
        never made — the tool-layer version of an invented document citation.
        """
        result = launch_registry().call(
            "compute_emi", {"principal": 500_000, "annual_rate": 0.125, "months": 60}
        )
        self.assertEqual(result.citation, "[tool:compute_emi]")

    def test_the_marker_matches_what_the_answer_validator_accepts(self):
        """The two modules must agree or grounding silently fails on every call."""
        from lending_hub.assistant.answer import validate

        result = launch_registry().call(
            "compute_emi", {"principal": 500_000, "annual_rate": 0.125, "months": 60}
        )
        answer = validate(
            f"Your monthly instalment is ₹{result.value['emi']:,.0f}. {result.citation}",
            allowed_tools=["compute_emi"],
        )
        self.assertFalse(answer.handoff)


class RateLimits(unittest.TestCase):
    """Phase 5 §4 WS-5.4 requires them and names no number — LH-612."""

    def test_the_ceiling_is_a_required_argument(self):
        """A default here would be the number every deployment ran with.

        Chosen by whoever typed it, and consequential in both directions: too
        low throttles a customer mid-comparison, too high lets a scripted client
        walk the EMI grid until the pricing model falls out.
        """
        with self.assertRaises(TypeError):
            RateLimiter()  # type: ignore[call-arg]

    def test_launch_registry_attaches_no_limiter(self):
        """Because there is no ratified limit to attach (LH-612)."""
        registry = launch_registry()
        self.assertFalse(hasattr(registry, "rate_limiter"))

    def test_a_session_over_its_ceiling_is_denied(self):
        clock = iter([0.0, 0.1, 0.2, 0.3])
        limiter = RateLimiter(max_calls=2, window_seconds=60, clock=lambda: next(clock))
        limiter.check("s1")
        limiter.check("s1")
        with self.assertRaises(ToolDenied):
            limiter.check("s1")

    def test_sessions_are_limited_independently(self):
        """One abusive session must not lock out every other customer."""
        clock = iter([0.0, 0.1, 0.2, 0.3])
        limiter = RateLimiter(max_calls=1, window_seconds=60, clock=lambda: next(clock))
        limiter.check("s1")
        limiter.check("s2")
        with self.assertRaises(ToolDenied):
            limiter.check("s1")

    def test_the_window_expires(self):
        clock = iter([0.0, 100.0])
        limiter = RateLimiter(max_calls=1, window_seconds=60, clock=lambda: next(clock))
        limiter.check("s1")
        limiter.check("s1")


if __name__ == "__main__":
    unittest.main()

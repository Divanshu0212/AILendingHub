"""The route table's own invariants — the gateway's central safety property.

The most important test in this file is
:meth:`TestModelDerivedRoutes.test_no_model_derived_route_serves_a_payload`. It
is the executable form of the reason this gateway exists in the shape it does:

    A response the client classifies model-derived must carry
    {model_id, model_version, decision_log_id} naming a real model. No model
    artifact is fitted in this repository. Therefore every such route returns
    unavailable — and the day one is fitted, this assertion must be CHANGED
    rather than deleted.

That last clause is why it is a test rather than a comment. A comment saying "we
don't fabricate scores" is true until someone adds a handler; a test that fails
when they do is what makes the property survive the person who wrote it.
"""

from __future__ import annotations

import unittest

from lending_hub.gateway import blocked, computed, contract
from lending_hub.gateway.contract import Unavailable
from lending_hub.gateway.routes import (
    CLIENT_DECLARED_PATHS,
    GATEWAY_ONLY_PATHS,
    ROUTES,
    Route,
    RouteError,
    Router,
    audit_routes,
)

#: Handlers whose output is a computed payload rather than a refusal.
COMPUTED_HANDLERS = {
    computed.quote_instalment,
    computed.detect_communities,
    computed.evaluate_offpolicy,
    computed.learning_cadence,
}


class TestModelDerivedRoutes(unittest.TestCase):
    def test_no_model_derived_route_serves_a_payload(self):
        """The property the whole gateway rests on.

        Checked by calling each handler rather than by reading its module, so a
        handler moved between `blocked` and `computed` cannot slip past: this is
        the one assertion where being keyed on a name would defeat the purpose.
        """
        for route in ROUTES:
            if not route.model_derived:
                continue
            with self.subTest(route=f"{route.method} {route.pattern}"):
                with self.assertRaises(
                    Unavailable,
                    msg=(
                        f"{route.pattern} is classified model-derived and its "
                        "handler returned a payload. Either it now has a fitted "
                        "model behind it — in which case assert the triplet "
                        "here instead of deleting this test — or it is about to "
                        "serve a score with a forged provenance."
                    ),
                ):
                    route.handler(path_params={}, query={}, body={})

    def test_audit_reports_no_violations(self):
        """`audit_routes` runs at server startup; this proves it passes today."""
        self.assertEqual(audit_routes(), ())

    def test_audit_catches_a_model_derived_route_that_computes(self):
        """The audit must actually fail when the property is violated.

        A guard that has never been seen to fire is indistinguishable from one
        that cannot. This constructs the exact mistake — a computed handler under
        a model-derived path — and asserts R1 names it.
        """
        bad = (
            Route(
                "GET",
                "/v1/applications/{applicationId}/decision",
                computed.quote_instalment,
                model_derived=True,
                takes=("body",),
            ),
        )
        violations = audit_routes(bad)
        self.assertTrue(violations)
        self.assertIn("R1", violations[0])

    def test_audit_catches_a_route_no_client_call_declares(self):
        """R2: dead surface is where an unclassified endpoint accretes."""
        bad = (Route("GET", "/v1/invented/thing", blocked.fetch_queue, False),)
        violations = audit_routes(bad)
        self.assertTrue(any("R2" in v for v in violations))


class TestComputedRoutes(unittest.TestCase):
    def test_no_computed_route_is_classified_model_derived(self):
        """A computed handler cannot produce a triplet, so it must not need one.

        Louvain is an algorithm, the DR estimator is an estimator, the cadence
        table is a transcription and `emi` is a formula. None came from a fitted
        model, so attaching an attribution would name a model that does not
        exist — and the client would happily render it.
        """
        for route in ROUTES:
            if route.handler in COMPUTED_HANDLERS:
                with self.subTest(route=route.pattern):
                    self.assertFalse(route.model_derived)

    def test_every_computed_handler_names_what_computed_it(self):
        """`computedBy` is the audit trail for a value with no model card.

        These four values have no attribution triplet because they have no
        model, which leaves a reader with no way to ask where a number came from
        — unless the response names the function. It does.
        """
        payloads = [
            computed.quote_instalment(
                {"amount": 100000, "annualRate": 0.1, "tenorMonths": 12}
            ),
            computed.detect_communities(
                {
                    "nodes": [
                        {"nodeId": "a", "kind": "applicant"},
                        {"nodeId": "b", "kind": "applicant"},
                    ],
                    "edges": [{"from": "a", "to": "b", "kind": "shares_device"}],
                }
            ),
            computed.learning_cadence(
                {}, {"graceDays": 1, "shippedPhases": ["P0"], "asOf": "2026-09-02"}
            ),
        ]
        for payload in payloads:
            self.assertTrue(payload["computedBy"].startswith("lending_hub."))


class TestInstalmentUnits(unittest.TestCase):
    """The rate unit, which is the one place this endpoint can be silently wrong.

    `reco.feasible.emi` takes a DECIMAL annual rate and the field is called
    `annualRate`, which invites the percentage. Sending 12.5 does not raise: it
    returns 520,833.33 on a principal of 500,000, correct arithmetic for a 1250%
    rate and nonsense as an answer — a plausible-looking number that survives
    review, which is exactly what Master §2 exists to stop.

    Found by calling the running server rather than by reading the code.
    """

    def test_a_decimal_rate_matches_the_hand_computed_emi(self):
        """500,000 at 12.5% over 60 months = 11,248.97.

        Computed independently from the closed form, not read off this
        implementation.
        """
        payload = computed.quote_instalment(
            {"amount": 500000, "annualRate": 0.125, "tenorMonths": 60}
        )
        self.assertAlmostEqual(payload["emi"]["amount"], 11248.97, places=2)

    def test_a_percentage_rate_is_refused_rather_than_answered(self):
        with self.assertRaises(computed.BadRequest) as caught:
            computed.quote_instalment(
                {"amount": 500000, "annualRate": 12.5, "tenorMonths": 60}
            )
        message = str(caught.exception)
        self.assertIn("decimal fraction", message)
        self.assertIn("0.125", message, "the refusal must say what to send instead")

    def test_the_boundary_is_one(self):
        """No consumer rate is >= 1.0 as a decimal or < 0.01 as a percentage, so
        1.0 separates the two unambiguously."""
        with self.assertRaises(computed.BadRequest):
            computed.quote_instalment(
                {"amount": 100000, "annualRate": 1.0, "tenorMonths": 12}
            )
        payload = computed.quote_instalment(
            {"amount": 100000, "annualRate": 0.99, "tenorMonths": 12}
        )
        self.assertGreater(payload["emi"]["amount"], 0)

    def test_the_echoed_rate_renders_as_a_percentage(self):
        payload = computed.quote_instalment(
            {"amount": 500000, "annualRate": 0.125, "tenorMonths": 60}
        )
        self.assertEqual(payload["annualRate"]["display"], "12.5%")


class TestRouter(unittest.TestCase):
    def test_path_parameters_are_extracted(self):
        match = Router().match("GET", "/v1/workbench/cases/APP-42")
        self.assertIsNotNone(match)
        self.assertEqual(match.path_params["applicationId"], "APP-42")

    def test_a_path_parameter_does_not_swallow_a_slash(self):
        """`{id}` matches one segment.

        Otherwise `/v1/workbench/cases/{applicationId}` would match
        `/v1/workbench/cases/a/b`, and an id containing a slash would silently
        resolve to a different case than the caller asked for.
        """
        self.assertIsNone(Router().match("GET", "/v1/workbench/cases/a/b"))

    def test_wrong_method_is_distinguishable_from_unknown_path(self):
        """405 and 404 are different answers to different questions.

        Answering 404 to a GET on a POST-only route sends a client looking for a
        typo in a path that is correct.
        """
        router = Router()
        self.assertIsNone(router.match("POST", "/v1/workbench/queue"))
        self.assertEqual(router.allowed_methods("/v1/workbench/queue"), ("GET",))
        self.assertEqual(router.allowed_methods("/v1/nope"), ())

    def test_duplicate_routes_are_refused(self):
        r = ROUTES[0]
        with self.assertRaises(RouteError):
            Router((r, r))

    def test_an_unversioned_route_is_refused(self):
        """Every route is under /v1/ so it can be deprecated without breaking."""
        with self.assertRaises(RouteError):
            Route("GET", "/workbench/queue", blocked.fetch_queue, False)


class TestTableCoversTheClient(unittest.TestCase):
    def test_every_path_the_client_calls_is_served(self):
        """The client is the contract until LH-706 publishes one.

        A path in `endpoints.ts` with no route here is a call that 404s at
        runtime — and because the frontend ships `AbsentAdapter` by default,
        nobody would find out until someone wired the real adapter.
        """
        served = {r.pattern for r in ROUTES}
        self.assertEqual(CLIENT_DECLARED_PATHS - served, set())

    def test_gateway_only_paths_are_disjoint_from_client_paths(self):
        """'The client asked for this' and 'we added this' stay separable.

        The second category is the one that grows without anyone deciding to
        grow it, which is only visible while the two lists are distinct.
        """
        self.assertEqual(CLIENT_DECLARED_PATHS & GATEWAY_ONLY_PATHS, set())


class TestBlockedHandlers(unittest.TestCase):
    def test_every_refusal_cites_a_registered_ticket(self):
        """A ticket id that is in no register is a ticket nobody is tracking.

        `make grounding` enforces this for `TBD[...]` placeholders in source;
        these ids live in response bodies where that scan does not reach, so the
        check is repeated here against the same registers.
        """
        import pathlib
        import re

        repo = pathlib.Path(__file__).resolve().parents[1]
        registered: set[str] = set()
        for register in repo.glob("docs/phase*/blocking_tickets.md"):
            registered.update(re.findall(r"LH-\d+", register.read_text()))

        self.assertTrue(registered, "no ticket registers found")
        for route in ROUTES:
            try:
                route.handler(path_params={}, query={}, body={})
            except Unavailable as u:
                with self.subTest(route=route.pattern):
                    self.assertIn(u.ticket, registered)
            except Exception:
                continue

    def test_refusals_name_an_owner_who_can_close_them(self):
        for route in ROUTES:
            try:
                route.handler(path_params={}, query={}, body={})
            except Unavailable as u:
                with self.subTest(route=route.pattern):
                    self.assertTrue(u.owner.strip())
            except Exception:
                continue


if __name__ == "__main__":
    unittest.main()

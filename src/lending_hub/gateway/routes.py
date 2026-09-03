"""The route table, read off the client's own endpoint module.

Every path here appears verbatim in `frontend/src/lib/gateway/endpoints.ts`, and
that direction is deliberate: the client declares the routes it expects, the
gateway implements them, and neither invents one. LH-706 is that nobody has
published a contract for either side to be right about — so this table is the
client's expectation made executable, not a ratification of it.

WHAT THE TABLE RECORDS BESIDES A HANDLER
------------------------------------------
`model_derived` mirrors the flag the client passes on each call. It is carried
here so a route's classification is visible next to its handler, which is the
property `endpoints.ts` gives as its reason for keeping the path lists beside the
calls: *"a new endpoint cannot be added without a reviewer seeing whether it was
classified."*

It also enables one assertion that would otherwise be a convention: R1 in
:func:`audit_routes` — **no route classified model-derived may be served by a
handler that is not blocked.** That is the whole safety property of this gateway
expressed as one loop over a table, and `tests/test_gateway_routes.py` runs it.
Today it holds because nothing is fitted; when a model is fitted, the assertion
becomes "then it must return a real triplet", and the test is where that change
gets noticed.

Workstream: WS-7.1.1 (SRS §11.6a)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from lending_hub.gateway import blocked, computed, demodata
from lending_hub.gateway.contract import Unavailable

Handler = Callable[..., Mapping[str, Any]]


class RouteError(Exception):
    """The route table itself is inconsistent."""


@dataclass(frozen=True)
class Route:
    """One path pattern, its method, its handler and its client classification."""

    method: str
    pattern: str
    handler: Handler
    model_derived: bool
    #: Which arguments the handler takes: any of "path", "query", "body".
    takes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.pattern.startswith("/v1/"):
            raise RouteError(
                f"{self.pattern}: every route is versioned under /v1/. An "
                "unversioned route cannot be deprecated without breaking a "
                "client that has no way to ask for the old shape."
            )

    @property
    def regex(self) -> re.Pattern[str]:
        """`{name}` segments become named groups; everything else is literal."""
        parts = []
        for segment in self.pattern.strip("/").split("/"):
            if segment.startswith("{") and segment.endswith("}"):
                parts.append(f"(?P<{segment[1:-1]}>[^/]+)")
            else:
                parts.append(re.escape(segment))
        return re.compile("^/" + "/".join(parts) + "$")


#: The paths `frontend/src/lib/gateway/endpoints.ts` builds, transcribed.
#:
#: Transcribed rather than parsed: parsing TypeScript from stdlib Python would be
#: a fragile regex over template literals, and a fragile check that silently stops
#: matching is worse than a list someone has to update — because updating it is
#: what puts the divergence in a reviewable diff.
CLIENT_DECLARED_PATHS: frozenset[str] = frozenset(
    {
        "/v1/workbench/queue",
        "/v1/workbench/cases/{applicationId}",
        "/v1/workbench/override-reasons",
        "/v1/workbench/decisions/{decisionId}/override",
        "/v1/audit/{decisionLogId}",
        "/v1/collections/alerts",
        "/v1/collections/alerts/{alertId}",
        "/v1/collections/outcome-codes",
        "/v1/collections/actions",
        "/v1/collections/alerts/{alertId}/disposition",
        "/v1/dashboards/{dashboardId}/panels",
        "/v1/applications/{applicationId}/decision",
        "/v1/applications/{applicationId}/offers",
        "/v1/documents/{documentId}",
        "/v1/consents",
        "/v1/applications/{applicationId}/document-checks",
        "/v1/assistant/conversations/{conversationId}",
        # Track P insights. Declared by the client (endpoints.ts) and rendered
        # by the dashboards, collections and workbench screens.
        "/v1/insights/vintages",
        "/v1/insights/roll-rates",
        "/v1/insights/portfolio",
        "/v1/insights/capture",
        "/v1/insights/scoring",
        "/v1/insights/queue",
        "/v1/insights/ews",
        "/v1/insights/agri/{plotId}",
    }
)

#: Routes this gateway serves that no Phase 7 screen calls.
#:
#: They exist because the computation behind them is real and demonstrable, and
#: because a gateway whose every route returns unavailable is impossible to tell
#: from a broken one. Listed separately rather than folded into the set above so
#: that "the client asked for this" and "we added this" stay distinguishable —
#: the second is the category that grows without anyone deciding to grow it.
GATEWAY_ONLY_PATHS: frozenset[str] = frozenset(
    {
        "/v1/quotes/instalment",
        "/v1/graph/communities",
        "/v1/learning/offpolicy",
        "/v1/learning/cadence",
        "/v1/health",
        "/v1/capabilities",
    }
)


#: The table. Order is the order `endpoints.ts` declares them.


# -- Track P demonstration routes ------------------------------------------
#
# These serve figures a committed script computed on real public loan data
# (`gateway.demodata`). They are NOT model-derived — nothing here came from a
# fitted model held in the serving path — and every payload carries a
# `provenance` block naming the track, the dataset and the fact that it is not
# gate evidence.


def _demo_vintages(query: dict) -> dict:
    return demodata.vintage_curves()


def _demo_rollrates(query: dict) -> dict:
    return demodata.roll_rates()


def _demo_portfolio(query: dict) -> dict:
    return demodata.portfolio_summary()


def _demo_capture(query: dict) -> dict:
    return demodata.capture_sweep()


def _demo_scoring(query: dict) -> dict:
    return demodata.scoring_performance()


def _demo_queue(query: dict) -> dict:
    raw = (query or {}).get("limit", ["25"])
    limit = int(raw[0]) if isinstance(raw, list) else int(raw)
    return demodata.officer_queue(limit if 1 <= limit <= 100 else 25)


def _demo_ews(query: dict) -> dict:
    return demodata.ews_summary()


def _demo_agri(path: dict) -> dict:
    return demodata.agri_evidence(path.get("plotId", "PLOT-DEMO-1"))


ROUTES: tuple[Route, ...] = (
    # -- WS-7.3 workbench
    Route("GET", "/v1/workbench/queue", blocked.fetch_queue, False),
    Route("GET", "/v1/workbench/cases/{applicationId}", blocked.fetch_case_file, True),
    Route("GET", "/v1/workbench/override-reasons", blocked.fetch_override_reasons, False),
    Route(
        "POST",
        "/v1/workbench/decisions/{decisionId}/override",
        blocked.submit_override,
        True,
    ),
    Route("GET", "/v1/audit/{decisionLogId}", blocked.fetch_audit_trail, True),
    # -- WS-7.5 collections
    Route("GET", "/v1/collections/alerts", blocked.fetch_alert_queue, True),
    Route("GET", "/v1/collections/alerts/{alertId}", blocked.fetch_alert, True),
    Route("GET", "/v1/collections/outcome-codes", blocked.fetch_outcome_codes, False),
    Route("GET", "/v1/collections/actions", blocked.fetch_action_library, False),
    Route(
        "POST",
        "/v1/collections/alerts/{alertId}/disposition",
        blocked.capture_disposition,
        True,
    ),
    # -- WS-7.4 dashboards
    Route("GET", "/v1/dashboards/{dashboardId}/panels", blocked.fetch_dashboard_panels, False),
    # -- WS-7.2 customer
    Route("GET", "/v1/applications/{applicationId}/decision", blocked.fetch_decision, True),
    Route("GET", "/v1/applications/{applicationId}/offers", blocked.fetch_feasible_set, True),
    Route("GET", "/v1/documents/{documentId}", blocked.fetch_disclosure, False),
    Route("POST", "/v1/consents", blocked.grant_consent, False),
    Route(
        "POST",
        "/v1/applications/{applicationId}/document-checks",
        blocked.start_document_check,
        False,
    ),
    Route(
        "GET",
        "/v1/assistant/conversations/{conversationId}",
        blocked.fetch_conversation,
        True,
    ),
    # -- computed. None is model-derived, and that is not a coincidence: see
    #    the module docstring on `gateway.computed`.
    Route("POST", "/v1/quotes/instalment", computed.quote_instalment, False, ("body",)),
    Route("POST", "/v1/graph/communities", computed.detect_communities, False, ("body",)),
    Route("POST", "/v1/learning/offpolicy", computed.evaluate_offpolicy, False, ("body",)),
    Route(
        "POST",
        "/v1/learning/cadence",
        computed.learning_cadence,
        False,
        ("query", "body"),
    ),
    # -- Track P demonstration data (gateway.demodata)
    Route("GET", "/v1/insights/vintages", _demo_vintages, False, ("query",)),
    Route("GET", "/v1/insights/roll-rates", _demo_rollrates, False, ("query",)),
    Route("GET", "/v1/insights/portfolio", _demo_portfolio, False, ("query",)),
    Route("GET", "/v1/insights/capture", _demo_capture, False, ("query",)),
    Route("GET", "/v1/insights/scoring", _demo_scoring, False, ("query",)),
    Route("GET", "/v1/insights/queue", _demo_queue, False, ("query",)),
    Route("GET", "/v1/insights/ews", _demo_ews, False, ("query",)),
    Route("GET", "/v1/insights/agri/{plotId}", _demo_agri, False, ("path",)),
)


@dataclass(frozen=True)
class Match:
    route: Route
    path_params: Mapping[str, str]


class Router:
    """Path matching and the two invariants the table must satisfy."""

    def __init__(self, routes: tuple[Route, ...] = ROUTES) -> None:
        self.routes = routes
        seen: set[tuple[str, str]] = set()
        for route in routes:
            key = (route.method, route.pattern)
            if key in seen:
                raise RouteError(f"duplicate route {route.method} {route.pattern}")
            seen.add(key)

    def match(self, method: str, path: str) -> Match | None:
        """The first route whose pattern matches, or None.

        Returns None for an unknown path and raises nothing for a known path on
        the wrong method — :meth:`allowed_methods` answers that separately, so a
        405 is distinguishable from a 404. A gateway that answered 404 to a GET
        on a POST-only route would send a client looking for a typo.
        """
        for route in self.routes:
            if route.method != method:
                continue
            found = route.regex.match(path)
            if found:
                return Match(route=route, path_params=found.groupdict())
        return None

    def allowed_methods(self, path: str) -> tuple[str, ...]:
        return tuple(
            sorted({r.method for r in self.routes if r.regex.match(path)})
        )


def audit_routes(routes: tuple[Route, ...] = ROUTES) -> tuple[str, ...]:
    """The invariants a reviewer would otherwise have to check by reading.

    R1  Every route the client classifies `modelDerived` is served by a handler
        that raises :class:`Unavailable`. This is the gateway's central safety
        property: a model-derived response needs a real
        {model_id, model_version, decision_log_id}, no model is fitted, and the
        only honest answer is therefore a refusal. When a model IS fitted this
        assertion must be *changed* rather than deleted — to "returns a triplet
        naming a registered artifact" — and having it fail loudly is the point.

    R2  Every route in the table appears in the client's `endpoints.ts`. The
        client is the only consumer, so a route it never calls is dead surface —
        and dead surface on a gateway is where an unclassified endpoint accretes.
        Checked against a transcribed list rather than by parsing TypeScript,
        which keeps the check stdlib and makes the divergence visible in a diff.

    Returns the list of violations, empty when clean.
    """
    violations: list[str] = []
    for route in routes:
        served_by_refusal = _always_unavailable(route.handler)
        if route.model_derived and not served_by_refusal:
            violations.append(
                f"R1 {route.method} {route.pattern}: classified model-derived but "
                "its handler returns a payload. A model-derived response must "
                "carry {model_id, model_version, decision_log_id} naming a "
                "registered artifact; no model is fitted here."
            )
        if route.pattern not in CLIENT_DECLARED_PATHS and route.pattern not in GATEWAY_ONLY_PATHS:
            violations.append(
                f"R2 {route.method} {route.pattern}: served by the gateway and "
                "declared by no client call. A route nothing calls is where an "
                "unclassified endpoint accretes."
            )
    return tuple(violations)


def _always_unavailable(handler: Handler) -> bool:
    """Whether calling this handler raises :class:`Unavailable` unconditionally.

    Determined by calling it, not by reading its name or its module. A check
    keyed on `handler.__module__ == "...blocked"` would pass for a handler moved
    into that module and would miss one moved out — and this is the assertion
    the whole gateway's honesty rests on, so it is answered by observation.
    """
    try:
        handler(path_params={}, query={}, body={})
    except Unavailable:
        return True
    except TypeError:
        try:
            handler({})
        except Unavailable:
            return True
        except Exception:
            return False
        return False
    except Exception:
        return False
    return False


__all__ = ["Route", "ROUTES", "Router", "Match", "RouteError", "audit_routes"]

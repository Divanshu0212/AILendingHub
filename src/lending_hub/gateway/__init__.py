"""The HTTP API gateway — the one origin all four Phase 7 surfaces call.

Phase 7 §4 WS-7.1.1 / SRS §11.6a: "All four surfaces call ONE API gateway —
never an underlying model service directly." `frontend/src/lib/gateway/client.ts`
enforces the client half of that (it is the only module in the frontend that
calls `fetch`); this package is the server half.

WHAT THIS GATEWAY IS ALLOWED TO PUT IN A RESPONSE
--------------------------------------------------
Exactly two things, and the split is the whole design:

1. A value some module under `src/lending_hub/` **computed**, on inputs the
   caller supplied. `reco.feasible.emi()` is the clean case — pure arithmetic on
   a principal, a rate and a tenor, with a reference implementation that already
   exists and is already tested (Master §2 rule 2, so this package never
   recomputes it).
2. A structured **unavailable** response naming the ticket that blocks it. See
   :mod:`lending_hub.gateway.contract`.

There is no third branch. In particular there is no branch that returns a
plausible score, PD, EMI, rate, fee, eligibility amount, reason sentence, fraud
score or alert precision that nothing computed — which is the same refusal
`frontend/src/adapters/port.ts` makes when it declines to ship a fixture
adapter, moved one layer in. A gateway is a worse place to fake a number than a
frontend is, because a frontend fixture is visibly a fixture in the diff and a
gateway response is indistinguishable from a real one on the wire.

THE ATTRIBUTION TRIPLET IS NOT DECORATION
-------------------------------------------
`frontend/src/lib/gateway/provenance.ts` throws `MissingAttributionError` on any
response classified model-derived that lacks `{modelId, modelVersion,
decisionLogId}`. That gives this package a property worth stating plainly: it
**cannot** serve a score without naming a model, because the client would refuse
to render it. So every endpoint whose payload the client marks `modelDerived`
either has a real model behind it or returns unavailable — a synthesised triplet
to satisfy the guard would be forging a model identity, which is a worse lie
than the number it was attached to.

No model artifact is fitted in this repository (ADR-0016 for P6; the P1/P3
scorers ship as ports with no trained weights committed), so today that means
every attributed endpoint returns unavailable and the honest count of fabricated
numbers served is zero. :mod:`lending_hub.gateway.computed` is the list of what
is *not* blocked.

WHAT THIS IS NOT
----------------
Not a Track B deployment. `http.server` is single-threaded and has no auth
backend, no TLS, no rate limiting and no idempotency store that survives a
restart; the bearer token is checked for presence and role shape, never
verified. It is a Track A implementation of the route contract (ADR-0003) —
enough for the Phase 7 surfaces to exercise their loading, error and unavailable
states against a real socket, and it says so in `X-Track: A` on every response
so a screenshot taken against it is identifiable as such.

The route table itself is unratified: LH-706 asks for the published contract and
the routes here are read off `frontend/src/lib/gateway/endpoints.ts`, which
declares itself provisional for the same reason.

Workstream: WS-7.1.1 (SRS §11.6a) — the gateway half of the Phase 7 client contract.
"""

from lending_hub.gateway.contract import (
    Attributed,
    FormattedNumber,
    ModelAttribution,
    Unavailable,
    UnavailableResponse,
)
from lending_hub.gateway.routes import ROUTES, Router
from lending_hub.gateway.server import GatewayHTTPServer, build_server, main

__all__ = [
    "Attributed",
    "FormattedNumber",
    "ModelAttribution",
    "Unavailable",
    "UnavailableResponse",
    "ROUTES",
    "Router",
    "GatewayHTTPServer",
    "build_server",
    "main",
]

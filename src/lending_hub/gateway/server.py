"""The stdlib HTTP server. `http.server`, no framework, no dependency.

ADR-0003 keeps heavy dependencies out of core logic so Track A stays runnable on
a clean clone with no install step. A gateway is exactly the component that
would justify FastAPI, which is why it does not get one: the route table is
twenty-odd entries, the request handling is JSON in and JSON out, and the value
of `make serve` working immediately after `git clone` is higher than the value of
dependency injection.

WHAT THE AUTH CHECK IS AND IS NOT
-----------------------------------
`GatewayClient` sends `Authorization: Bearer <token>` and `X-Acting-Role` on
every call, and this server checks that both are *present and well-formed*. It
does not verify the token, because there is no identity provider to verify it
against (LH-120), and a check that accepted any string while looking like
authentication would be the worst of both: a reviewer reading `if not token: 401`
concludes the route is protected.

So the refusal is explicit. Every response carries `X-Auth-Verified: false`, and
`/v1/capabilities` says so in the body. This server is not deployable, and the
header is there so that a capture taken against it cannot be mistaken for one
taken against something that is.

WHAT IDEMPOTENCY IS NOT
-----------------------
`endpoints.ts` sends `Idempotency-Key` on the three state-changing calls and
this server accepts the header in CORS and honours nothing. That is safe only
because all three routes are blocked: a refusal is idempotent by construction.
It stops being safe the day one of them starts writing, and the contract that
would make it safe — retention window, replay response, and what a key replayed
with a different body means — is LH-714. A header nobody honours is worse than
no header, because the caller believes it is protected.

WHY CORS IS NARROW
------------------
`http://localhost:3000` only, and configurable to one origin at a time via
`--origin`. A wildcard would let any page a developer has open call this gateway
from their browser with their session — and on a Track B build the same code
path would do it with real bureau data.

Workstream: WS-7.1.1 (SRS §11.6a)
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse

from lending_hub.gateway import blocked
from lending_hub.gateway.computed import BadRequest
from lending_hub.gateway.contract import GatewayContractError, Unavailable
from lending_hub.gateway.routes import ROUTES, Route, Router, audit_routes

#: The frontend's dev origin. One value, not a wildcard — see the module docstring.
DEFAULT_ALLOWED_ORIGIN = "http://localhost:3000"

#: Port 8787, chosen to not collide with Next.js on 3000 or the common 8000/8080.
DEFAULT_PORT = 8787

#: Bytes. A request body larger than this is refused unread.
MAX_BODY_BYTES = 1 << 20

#: The four roles Phase 7 §4 WS-7.1.3 names. [SPEC]
ROLES = frozenset({"customer", "officer", "risk-viewer", "collections-agent"})


class UnauthenticatedRequest(Exception):
    """No bearer token, or no acting role."""


def _capabilities() -> dict[str, Any]:
    """``GET /v1/capabilities`` — what this gateway can and cannot serve.

    Exists so that "what is blocked and on which ticket" is a machine-readable
    answer rather than a document someone has to find. A screen, a CI check or a
    reviewer with curl can all read the same list, and it is generated from the
    route table rather than maintained beside it — so a route added without a
    classification shows up here immediately.
    """
    served: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []
    for route in ROUTES:
        entry = {
            "method": route.method,
            "path": route.pattern,
            "modelDerived": route.model_derived,
        }
        try:
            route.handler(body={}, query={}, path_params={})
        except Unavailable as u:
            unavailable.append({**entry, "ticket": u.ticket, "owner": u.owner, "reason": u.reason})
            continue
        except Exception:
            pass
        served.append(entry)

    return {
        "track": "A",
        "authVerified": False,
        "authNote": (
            "Bearer tokens are checked for presence and shape and are NEVER "
            "verified: there is no identity provider to verify them against "
            "(LH-120). This gateway is not deployable."
        ),
        "servedFromRealComputation": served,
        "unavailable": unavailable,
        "fabricatedValuesServed": 0,
        "fabricationNote": (
            "No endpoint returns a score, PD, LGD, EAD, EMI, rate, fee, "
            "eligibility amount, reason sentence, fraud score or alert precision "
            "that a committed module did not compute from caller-supplied input. "
            "Every route the client classifies model-derived returns unavailable, "
            "because a model-derived value needs a real "
            "{model_id, model_version, decision_log_id} and no model artifact is "
            "fitted in this repository."
        ),
        "routeContractRatified": False,
        "routeContractTicket": "LH-706",
    }


class GatewayRequestHandler(BaseHTTPRequestHandler):
    """One request. Every branch ends in a JSON body with a track stamp."""

    server_version = "LendingHubGateway/0.1"
    protocol_version = "HTTP/1.1"

    router: Router = Router()
    allowed_origin: str = DEFAULT_ALLOWED_ORIGIN
    quiet: bool = False

    # -- plumbing ---------------------------------------------------------

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        if not self.quiet:
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", self.allowed_origin)
        self.send_header("Vary", "Origin")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Authorization, Content-Type, X-Acting-Role, Idempotency-Key",
        )
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, OPTIONS")
        self.send_header("Access-Control-Max-Age", "600")

    def _respond(self, status: int, payload: Mapping[str, Any]) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        # Stamped on every response, per ADR-0003: "every number in reports/ is
        # stamped with the track that produced it". A screenshot taken against
        # this server is identifiable as Track A from the wire.
        self.send_header("X-Track", "A")
        self.send_header("X-Auth-Verified", "false")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, code: str, message: str) -> None:
        # Mirrors what `GatewayClient` reads off a non-2xx body.
        self._respond(status, {"errorCode": code, "message": message})

    # -- auth -------------------------------------------------------------

    def _check_session(self) -> None:
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or not auth[7:].strip():
            raise UnauthenticatedRequest(
                "every gateway call is role-scoped (WS-7.1.3): send "
                "'Authorization: Bearer <token>'. The token is NOT verified — "
                "there is no identity provider (LH-120) — but a request without "
                "one is refused so the client's unauthenticated path is real."
            )
        role = self.headers.get("X-Acting-Role", "")
        if role not in ROLES:
            raise UnauthenticatedRequest(
                f"X-Acting-Role must be one of {sorted(ROLES)}, got {role!r}. "
                "Phase 7 §4 WS-7.1.3 names the four roles [SPEC]."
            )

    # -- body -------------------------------------------------------------

    def _read_body(self) -> dict[str, Any]:
        raw_len = self.headers.get("Content-Length")
        if not raw_len:
            return {}
        try:
            length = int(raw_len)
        except ValueError as error:
            raise BadRequest("malformed Content-Length") from error
        if length > MAX_BODY_BYTES:
            raise BadRequest(f"request body exceeds {MAX_BODY_BYTES} bytes")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BadRequest(f"body is not valid JSON: {error}") from error
        if not isinstance(parsed, dict):
            raise BadRequest("body must be a JSON object")
        return parsed

    # -- dispatch ---------------------------------------------------------

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def do_PATCH(self) -> None:  # noqa: N802
        self._dispatch("PATCH")

    def _dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}

        # Unauthenticated by design: a liveness probe that needs a token cannot
        # tell "down" from "misconfigured client".
        if path == "/v1/health" and method == "GET":
            self._respond(200, {"status": "ok", "track": "A"})
            return

        try:
            self._check_session()
        except UnauthenticatedRequest as error:
            self._error(401, "unauthenticated", str(error))
            return

        if path == "/v1/capabilities" and method == "GET":
            self._respond(200, _capabilities())
            return

        match = self.router.match(method, path)
        if match is None:
            allowed = self.router.allowed_methods(path)
            if allowed:
                self._error(
                    405,
                    "method_not_allowed",
                    f"{path} accepts {', '.join(allowed)}. Answering 404 here "
                    "would send a client looking for a typo in a correct path.",
                )
                return
            self._error(
                404,
                "no_such_route",
                f"no route for {method} {path}. The route contract is LH-706 and "
                "unpublished; the routes this gateway serves are read off "
                "frontend/src/lib/gateway/endpoints.ts. GET /v1/capabilities "
                "lists every one.",
            )
            return

        try:
            body = self._read_body() if method in {"POST", "PATCH"} else {}
        except BadRequest as error:
            self._error(400, "malformed_request", str(error))
            return

        try:
            payload = _invoke(match.route, dict(match.path_params), query, body)
        except Unavailable as unavailable:
            # 200, not 5xx. An unratified policy value is not a server fault, and
            # rendering it as one puts a governance stop in the same bucket as a
            # crashed process — see `gateway.contract`.
            self._respond(200, unavailable.to_json())
            return
        except BadRequest as error:
            self._error(400, "malformed_request", str(error))
            return
        except GatewayContractError as error:
            self._error(500, "contract_violation", str(error))
            return
        except Exception as error:  # pragma: no cover - defensive
            self._error(500, "internal_error", f"{type(error).__name__}: {error}")
            return

        self._respond(200, payload)


def _invoke(
    route: Route,
    path_params: Mapping[str, str],
    query: Mapping[str, str],
    body: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Call a handler with the arguments its route declares it takes.

    Positional by declaration rather than by introspecting the signature: a
    handler's parameter names are an implementation detail, and binding on them
    means renaming a parameter silently changes what a route passes.
    """
    args: list[Any] = []
    for want in route.takes:
        if want == "path":
            args.append(path_params)
        elif want == "query":
            args.append(query)
        elif want == "body":
            args.append(body)
    if not route.takes:
        return route.handler(path_params=path_params, query=query, body=body)
    return route.handler(*args)


class GatewayHTTPServer(ThreadingHTTPServer):
    """Threaded so a slow handler cannot block the frontend's other panels.

    The unified case file fetches several panels concurrently; on a
    single-threaded server they would serialise and the screen's loading states
    would be untestable.
    """

    daemon_threads = True
    allow_reuse_address = True


def build_server(
    port: int = DEFAULT_PORT,
    *,
    host: str = "127.0.0.1",
    origin: str = DEFAULT_ALLOWED_ORIGIN,
    quiet: bool = False,
) -> GatewayHTTPServer:
    """Construct the server without starting it. The seam every test uses.

    Binds to loopback by default. A gateway that checks no token and serves no
    verified identity must not be reachable off the machine it runs on, and
    `--host` exists so that widening it is a visible act.
    """
    violations = audit_routes()
    if violations:
        raise GatewayContractError(
            "route table failed its own audit before serving a request:\n  "
            + "\n  ".join(violations)
        )

    handler = type(
        "BoundGatewayRequestHandler",
        (GatewayRequestHandler,),
        {"router": Router(), "allowed_origin": origin, "quiet": quiet},
    )
    return GatewayHTTPServer((host, port), handler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m lending_hub.gateway.server",
        description="The Phase 7 API gateway (Track A). Serves computed values "
        "and ticket-bearing refusals, and nothing else.",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--origin",
        default=DEFAULT_ALLOWED_ORIGIN,
        help="the single CORS origin to allow (no wildcard is accepted)",
    )
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    if args.origin == "*":
        parser.error(
            "a wildcard CORS origin lets any page in the developer's browser "
            "call this gateway with their session. Name the origin."
        )

    server = build_server(args.port, host=args.host, origin=args.origin, quiet=args.quiet)
    caps = _capabilities()
    print(
        f"gateway (Track A) on http://{args.host}:{args.port}  "
        f"CORS: {args.origin}\n"
        f"  {len(caps['servedFromRealComputation'])} route(s) served from real computation\n"
        f"  {len(caps['unavailable'])} route(s) unavailable, each with a ticket\n"
        f"  auth is NOT verified (LH-120); route contract is unratified (LH-706)\n"
        f"  GET /v1/capabilities for the full list",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

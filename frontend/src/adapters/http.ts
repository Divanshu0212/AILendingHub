/**
 * The opt-in HTTP adapter — the seam where a real gateway gets wired in.
 *
 * `GatewayAdapter` (in `gateway.ts`) is already the thin pass-through to
 * `endpoints.ts`, and this does not duplicate it. What this module adds is the
 * *selection* rule: which adapter a build gets, decided from one environment
 * variable, with `AbsentAdapter` as the answer when nothing is configured.
 *
 * WHY THE DEFAULT STAYS ABSENT
 * ----------------------------
 * `port.ts` argues at length that there is no fixture adapter because a
 * plausible screen survives review with a wider audience than a plausible
 * number. A gateway does not change that argument — it satisfies it. The
 * gateway serves computed values or ticket-bearing refusals and nothing else,
 * so a screen filled from it is showing either arithmetic someone can re-derive
 * or a governance gap someone owns.
 *
 * But that property belongs to *this* gateway, not to whatever is listening on
 * the configured origin. So the default is unchanged: a build with no
 * `NEXT_PUBLIC_GATEWAY_BASE_URL` gets `AbsentAdapter`, and pointing at a
 * backend stays a deliberate act rather than a fallback. `client.ts` makes the
 * same choice for the same reason — it refuses to invent an origin.
 *
 * THE TWO HEADERS
 * ---------------
 * The gateway requires `Authorization: Bearer <token>` AND `X-Acting-Role`
 * (one of customer / officer / risk-viewer / collections-agent), and rejects a
 * request missing either with a 401. `GatewayClient` already sends both from
 * the `Session` — token and role are fields on it — so an adapter built without
 * a session cannot make a call at all, which is the WS-7.1.3 property stated as
 * a construction requirement rather than a runtime check.
 *
 * Worth stating plainly, because it is the sort of thing a reader assumes went
 * the other way: the gateway does NOT verify the token. There is no identity
 * provider (LH-120), and `server.py` says so in its own docstring and on every
 * response via `X-Auth-Verified: false`. The header check makes the client's
 * unauthenticated path real; it is not authentication.
 */

import { AbsentAdapter, type Adapter } from "./port";
import { GatewayAdapter } from "./gateway";
import { GatewayClient } from "../lib/gateway/client";
import type { Session } from "../lib/auth/session";

/**
 * Whether this build has a gateway configured.
 *
 * Reads the same variable `client.ts` reads, so the two cannot disagree about
 * whether a gateway exists. A build where this is false and the client was
 * constructed anyway throws `GatewayConfigError` on the first request — which
 * is the correct outcome, and this exists so that it never gets that far.
 */
export function isGatewayConfigured(): boolean {
  const url = process.env.NEXT_PUBLIC_GATEWAY_BASE_URL;
  return typeof url === "string" && url.length > 0;
}

/**
 * The adapter this build should use.
 *
 * One decision, in one place, with no branch that returns something other than
 * these two. A third option would have to be a fixture adapter, which is the
 * decision `port.ts` records refusing.
 *
 * @param session the authenticated session, or null. A null session yields
 *   `AbsentAdapter` even when a gateway IS configured: every gateway call is
 *   role-scoped, so an adapter with no session would reject every call anyway —
 *   with `UnauthenticatedError` from deep inside the client instead of the
 *   ticket-bearing `BackendAbsentError` a screen can render.
 */
export function selectAdapter(session: Session | null, transport?: typeof fetch): Adapter {
  if (!isGatewayConfigured() || session === null) {
    return new AbsentAdapter();
  }
  return new HttpAdapter(session, transport);
}

/**
 * `GatewayAdapter` bound to a session and a transport.
 *
 * A subclass rather than a wrapper with sixteen delegating methods: the port has
 * sixteen calls, and a hand-written delegation for each is sixteen chances to
 * drop an argument. `GatewayAdapter` is already documented as "thin by design.
 * Every method is one endpoints.ts call with no branching, no caching and no
 * shaping" — inheriting keeps that true rather than adding a second layer that
 * could start shaping.
 */
export class HttpAdapter extends GatewayAdapter {
  constructor(session: Session, transport?: typeof fetch) {
    super(transport ? new GatewayClient(session, transport) : new GatewayClient(session));
  }
}

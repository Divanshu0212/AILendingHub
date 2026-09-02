/**
 * The development session, and the two guards that keep it out of production.
 *
 * WHY THIS EXISTS
 * ---------------
 * `selectAdapter` returns `AbsentAdapter` when the session is null, so with no
 * identity provider (LH-120) the gateway is configured, reachable, answering —
 * and never called. The adapter wiring was complete and inert.
 *
 * WHAT THIS IS NOT
 * ----------------
 * Not authentication, and not a step toward it. The gateway does not verify
 * bearer tokens either (its own `authVerified: false` says so), so this pairs a
 * client that cannot prove who it is with a server that would not check. That
 * combination is fine for a local walkthrough and is not a security posture.
 *
 * It is also NOT a fixture: it produces no score, no rate, no reason sentence
 * and no data of any kind. It carries a role so that role-scoped routes can be
 * exercised, and every value on screen still comes from the gateway or from a
 * ticket-bearing refusal. That is the line `port.ts` draws when it declines to
 * ship a fixture adapter, and this stays on the right side of it.
 *
 * THE TWO GUARDS
 * --------------
 * 1. `process.env.NODE_ENV !== "production"` — a production build gets `null`
 *    and therefore `AbsentAdapter`, whatever else is configured.
 * 2. `NEXT_PUBLIC_DEV_SESSION_ROLE` must be set explicitly. A developer opts in
 *    per-run; nothing is assumed. An unset variable is not "default to officer",
 *    because a default role is a permission decision made by whoever typed it.
 *
 * Registered as LH-714: real session establishment is a Security deliverable
 * and this file is what stands in for it until that lands.
 */

import type { Role, Session } from "../lib/auth/session";

const ROLES: readonly Role[] = ["customer", "officer", "risk-viewer", "collections-agent"];

function isRole(value: string): value is Role {
  return (ROLES as readonly string[]).includes(value);
}

/**
 * A session for local development, or `null`.
 *
 * `null` is the common case and the safe one: it yields `AbsentAdapter`, which
 * is exactly what the build did before this file existed.
 */
export function devSession(): Session | null {
  if (process.env.NODE_ENV === "production") return null;

  const role = process.env.NEXT_PUBLIC_DEV_SESSION_ROLE;
  if (role === undefined || role === "" || !isRole(role)) return null;

  return {
    // Tokenised, per SRS §11.4 — never a customer identifier, even here.
    subjectToken: "tok_dev_local",
    role,
    token: "dev-local-unverified",
    // Far future: an expiry the client computed would be the client deciding
    // its own session lifetime, which is LH-704.
    expiresAt: "2099-01-01T00:00:00Z",
    displayName: role === "customer" ? null : "Local development",
    officerId: role === "officer" ? "ofc_dev_local" : null,
  };
}

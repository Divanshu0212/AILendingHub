/**
 * WS-7.1.3 - role-based access, session, and the PII-logging prohibition.
 *
 * Phase 7 §4 WS-7.1.3: "Role-based access (customer / officer / risk-viewer /
 * collections-agent); session timeout [POLICY: Security]; no PII in client-side
 * logs or analytics events."
 *
 * The four roles are [SPEC] - the phase file names them. The session timeout is
 * [POLICY: Security] and is NOT in this file, in any form, including as a
 * "reasonable default". See `sessionTimeoutMs`.
 */

/** The four roles, exactly as Phase 7 §4 WS-7.1.3 names them. [SPEC] */
export const ROLES = ["customer", "officer", "risk-viewer", "collections-agent"] as const;

export type Role = (typeof ROLES)[number];

export function isRole(v: string): v is Role {
  return (ROLES as readonly string[]).includes(v);
}

export interface Session {
  /** Tokenised subject. SRS §11.4 - never a customer identifier. */
  readonly subjectToken: string;
  readonly role: Role;
  readonly token: string;
  /** ISO-8601. Server-issued; the client does not compute an expiry. */
  readonly expiresAt: string;
  /** Display name for the acting user. Officer-side only; never a customer name. */
  readonly displayName: string | null;
  readonly officerId: string | null;
}

/**
 * Session-timeout is [POLICY: Security] and unratified (LH-704).
 *
 * This function RAISES rather than returning a default, following the pattern
 * CLAUDE.md §6 sets out for every missing policy value: "A default in a
 * signature is how an ungrounded number becomes the production one - nobody
 * passes the argument, and by the time anyone asks it has been in a report for a
 * year."
 *
 * A session timeout is the sharpest case of that. Fifteen minutes and eight
 * hours are both plausible, they differ by a factor of thirty-two, and the
 * difference is a security control on a screen showing bureau data. The client
 * therefore reads the value the SERVER issues, and this exists so that a caller
 * reaching for a constant finds an exception instead.
 */
export function sessionTimeoutMs(): never {
  throw new UngroundedPolicyError(
    "session timeout",
    "Security",
    "LH-704",
    "Phase 7 §4 WS-7.1.3 marks the session timeout [POLICY: Security] and it is " +
      "unratified. The client must use the server-issued `expiresAt` on the " +
      "session rather than any local duration."
  );
}

export class UngroundedPolicyError extends Error {
  constructor(
    readonly value: string,
    readonly owner: string,
    readonly ticket: string,
    detail: string
  ) {
    super(`${value} is ungrounded [POLICY: ${owner}, ${ticket}] - ${detail}`);
    this.name = "UngroundedPolicyError";
  }
}

/**
 * Whether the server-issued session has expired, judged against a server-issued
 * expiry. This is a comparison, not a computation of a policy duration.
 */
export function isExpired(session: Session, now: Date): boolean {
  return new Date(session.expiresAt).getTime() <= now.getTime();
}

/**
 * The capability model. Roles do not map to screens directly - they map to
 * capabilities, and screens require capabilities.
 *
 * WS-7.4.2 is the reason: "role differences are permission and layout, never
 * different numbers for the same metric." A role->screen map invites a fork
 * where the CRO view and the portfolio-manager view compute the same figure two
 * ways. A role->capability map cannot, because both views call the same endpoint
 * and differ only in whether they are allowed to.
 */
export type Capability =
  | "application:submit"
  | "application:view-own"
  | "offer:select-own"
  | "consent:grant"
  | "queue:view"
  | "case:view"
  | "decision:override"
  | "offer:construct"
  | "audit:view"
  | "dashboard:view"
  | "dashboard:drill-through"
  | "alert:view"
  | "alert:dispose"
  | "assistant:converse";

const CAPABILITIES: Readonly<Record<Role, readonly Capability[]>> = {
  customer: [
    "application:submit",
    "application:view-own",
    "offer:select-own",
    "consent:grant",
    "assistant:converse",
  ],
  officer: [
    "queue:view",
    "case:view",
    "decision:override",
    "offer:construct",
    "audit:view",
    "assistant:converse",
  ],
  "risk-viewer": ["dashboard:view", "dashboard:drill-through", "audit:view"],
  "collections-agent": ["alert:view", "alert:dispose", "case:view", "audit:view"],
};

export function can(session: Session | null, capability: Capability): boolean {
  if (!session) return false;
  return CAPABILITIES[session.role].includes(capability);
}

/**
 * Client-side telemetry. Deliberately narrow.
 *
 * Phase 7 §2 lists "UI-side telemetry (non-PII)" as an output. The safest shape
 * for that is an allowlist of event names with no free-form payload at all -
 * every field is a string enum or a count. The gateway client's `logSafe` is the
 * second layer; this is the first, and the first is the one that works, because
 * a redactor only redacts what it recognises.
 */
export interface TelemetryEvent {
  readonly name: string;
  readonly surface: "customer" | "workbench" | "dashboards" | "collections";
  readonly role: Role;
  /** Screen identifier, never a URL - URLs carry ids. */
  readonly screen: string;
  /** Counts only. No free-form values, no identifiers. */
  readonly counts?: Readonly<Record<string, number>>;
}

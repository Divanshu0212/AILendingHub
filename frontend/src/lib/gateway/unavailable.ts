/**
 * The gateway's refusal shape, and why it is not an error.
 *
 * `src/lending_hub/gateway/` answers 17 of its 21 routes with a 200 carrying
 * `{status:"unavailable", capability, ticket, owner, reason}` rather than a 4xx
 * or a 5xx. The reasoning is in `gateway/contract.py` and it transfers directly
 * to this side of the wire:
 *
 *   An unratified FOIR cap is not a server fault. Rendering it as one puts a
 *   governance stop in the same bucket as a crashed process.
 *
 * That distinction only survives if the client preserves it. `GatewayError`
 * drives the red `role="alert"` box every screen already has, which is the right
 * treatment for a 500 and the wrong one for "Credit Policy has not ratified
 * LH-504" — the first says try again, the second says stop and go and ask
 * someone. A screen that shows them identically teaches an officer to ignore
 * both.
 *
 * So `CapabilityUnavailableError` is a separate class with the ticket and the
 * owner as fields, and `<UnavailableNotice>` renders it in the neutral dashed
 * frame the case-file panels already use for the same state. Phase 3's
 * "not measured / not measurable" split is the same argument one layer down: two
 * states in one column means the second never gets escalated.
 *
 * WHY THIS IS PARSED AND NOT TRUSTED
 * ----------------------------------
 * `isUnavailableBody` checks all five fields. A response that merely had a
 * `status` key would otherwise be read as a refusal and its payload dropped —
 * and a payload silently dropped is indistinguishable, on screen, from a
 * backend that had nothing to send.
 */

/** Mirrors `Unavailable.to_json()` in `src/lending_hub/gateway/contract.py`. */
export interface UnavailableBody {
  readonly status: "unavailable";
  /** What was asked for, in the caller's vocabulary. */
  readonly capability: string;
  /** The blocking-ticket id, registered under the phase blocking-ticket registers. */
  readonly ticket: string;
  /** The committee or squad that can close it. A ticket with no owner is untracked. */
  readonly owner: string;
  /** Why, in a sentence a screen can render to a reviewer. */
  readonly reason: string;
}

/**
 * Whether a decoded response body is a refusal.
 *
 * Every field is checked and every one must be a non-empty string, mirroring the
 * Python constructor's own refusal to build an `Unavailable` missing any of
 * them. A partial match is treated as a payload rather than a refusal, because
 * the failure mode of guessing wrong in that direction is a visible type error
 * rather than a blank screen.
 */
export function isUnavailableBody(v: unknown): v is UnavailableBody {
  if (typeof v !== "object" || v === null) return false;
  const r = v as Record<string, unknown>;
  if (r.status !== "unavailable") return false;
  for (const field of ["capability", "ticket", "owner", "reason"]) {
    const value = r[field];
    if (typeof value !== "string" || value.length === 0) return false;
  }
  return true;
}

/**
 * A capability this deployment cannot serve, carrying who can change that.
 *
 * Deliberately NOT a subclass of `GatewayError`: the screens branch on
 * `instanceof`, and making this an error subtype would put it back in the red
 * box by inheritance the first time someone wrote `catch (e) { if (e instanceof
 * GatewayError) ... }`.
 */
export class CapabilityUnavailableError extends Error {
  readonly capability: string;
  readonly ticket: string;
  readonly owner: string;
  readonly reason: string;

  constructor(readonly endpoint: string, body: UnavailableBody) {
    super(`${endpoint}: ${body.capability} is unavailable (${body.ticket}, ${body.owner})`);
    this.name = "CapabilityUnavailableError";
    this.capability = body.capability;
    this.ticket = body.ticket;
    this.owner = body.owner;
    this.reason = body.reason;
  }
}

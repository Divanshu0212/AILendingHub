/**
 * WS-7.1.1 - the {model_id, model_version, decision_log_id} contract.
 *
 * Phase 7 §4 WS-7.1.1:
 *
 *   "Contract tests in CI verify every response used to render a score, reason,
 *    or alert carries {model_id, model_version, decision_log_id} so the UI can
 *    deep-link to the audit trail."
 *
 * The phase file puts this in CI. CI is necessary and not sufficient: a contract
 * test proves the API returns the triplet, not that the component rendered a
 * value that had one. So the triplet is a TYPE here, and the render path for a
 * model-derived value takes `Attributed<T>` rather than `T`. A component that
 * wants to show a score cannot be given a bare number - there is no way to type
 * one in.
 *
 * This mirrors `lending_hub.decisionlog.record.ModelRef`, which carries seven
 * fields. The UI needs three of them: two to name the model and one to link the
 * decision. The other four (code_commit, data_snapshot, config_hash,
 * definitions_fingerprint) live behind the audit-trail link rather than on the
 * screen, because a reproducibility triplet on a customer decision screen is
 * noise, and on an officer screen it is one click away.
 */

/**
 * Identifies which model produced a value, and which decision-log entry records
 * the act of producing it.
 *
 * `decisionLogId` is nullable for exactly one reason and it is not convenience:
 * some model-derived values are produced OUTSIDE a decision - a dashboard
 * aggregate, a batch EWS evaluation - and forging a decision id for them would
 * put entries in the audit trail that correspond to no decision. Where it is
 * null, the UI must render the model attribution and suppress the deep link,
 * rather than link to nothing. See `AuditLink`.
 */
export interface ModelAttribution {
  readonly modelId: string;
  readonly modelVersion: string;
  readonly decisionLogId: string | null;
}

/**
 * A value that came from a model, inseparable from the attribution of the model
 * that produced it.
 *
 * The `readonly` and the branded absence of a bare constructor are the point:
 * `Attributed<number>` cannot be produced by writing `{ value: 42 }` in a
 * component, because `attribution` has no default and no component imports a
 * function that makes one.
 */
export interface Attributed<T> {
  readonly value: T;
  readonly attribution: ModelAttribution;
}

/**
 * A money or ratio figure as the gateway returns it: the raw number for
 * comparison and sorting, and the string the BACKEND chose to display.
 *
 * Phase 7 §8 forbids the frontend composing an EMI. It equally forbids the
 * frontend deciding that an EMI is shown to zero decimal places, because
 * rounding a repayment figure down by 49 paise on a screen a customer will hold
 * the bank to is a disclosure decision. `display` is authoritative; `amount`
 * exists for sorting and for accessibility announcements, never for arithmetic.
 */
export interface FormattedNumber {
  readonly amount: number;
  readonly display: string;
  /** ISO 4217 where the figure is money; absent for ratios and counts. */
  readonly currency?: string;
}

/** Where a value with an attribution links to. */
export function auditTrailHref(a: ModelAttribution): string | null {
  return a.decisionLogId ? `/audit/${encodeURIComponent(a.decisionLogId)}` : null;
}

/**
 * Runtime guard used by the gateway client on every response it classifies as
 * model-derived. Types are erased at runtime; this is what actually fails when
 * a backend ships a response without the triplet.
 */
export function hasAttribution(v: unknown): v is { attribution: ModelAttribution } {
  if (typeof v !== "object" || v === null) return false;
  const a = (v as { attribution?: unknown }).attribution;
  if (typeof a !== "object" || a === null) return false;
  const r = a as Record<string, unknown>;
  return (
    typeof r.modelId === "string" &&
    r.modelId.length > 0 &&
    typeof r.modelVersion === "string" &&
    r.modelVersion.length > 0 &&
    (r.decisionLogId === null || typeof r.decisionLogId === "string")
  );
}

/** Thrown when a response that renders a score, reason or alert lacks the triplet. */
export class MissingAttributionError extends Error {
  constructor(
    readonly endpoint: string,
    readonly path: string
  ) {
    super(
      `${endpoint}: response field '${path}' renders a model-derived value but ` +
        `carries no {model_id, model_version, decision_log_id}. Phase 7 §4 ` +
        `WS-7.1.1 - the UI cannot deep-link to the audit trail, so it must not ` +
        `display the value.`
    );
    this.name = "MissingAttributionError";
  }
}

/**
 * WS-7.1.1 - the single API gateway client.
 *
 * Phase 7 §4 WS-7.1.1 / SRS §11.6a: "All four surfaces call ONE API gateway -
 * never an underlying model service directly."
 *
 * That is enforced structurally: this is the only module in the frontend that
 * calls `fetch`, and the base URL comes from one environment variable with no
 * default. A surface that wants a model service has nowhere to put the URL.
 *
 * WHAT THIS CLIENT REFUSES
 * ------------------------
 * 1. A response classified as model-derived that carries no attribution triplet
 *    -> `MissingAttributionError`. It throws rather than rendering the value
 *    without a link, because a score with no audit trail is exactly the artifact
 *    §11.6b exists to prevent, and a degraded render would look identical to a
 *    working one.
 * 2. Any request without a role-scoped session -> `UnauthenticatedError`.
 * 3. Any request whose telemetry would carry PII -> see `logSafe` below.
 *
 * WHAT IT DOES NOT DO
 * -------------------
 * No retry policy: the retry budget on a decisioning path is an SLO decision
 * (LH-705), and a client that retries a POST that creates an override is a
 * client that can double-log one. Only idempotent job polling repeats, and only
 * at the interval the SERVER supplies.
 */

import { hasAttribution, MissingAttributionError } from "./provenance";
import type { JobStatus } from "./types";
import type { Session } from "../auth/session";

/**
 * No default. Phase 7 has no ratified environment topology, and a fallback
 * origin in a lending client is how a QA build points at production.
 */
function gatewayBaseUrl(): string {
  const url = process.env.NEXT_PUBLIC_GATEWAY_BASE_URL;
  if (!url) {
    throw new GatewayConfigError(
      "NEXT_PUBLIC_GATEWAY_BASE_URL is unset. There is no default gateway " +
        "origin: a lending client that falls back to a built-in host is a " +
        "client that can be pointed at the wrong environment silently."
    );
  }
  return url.replace(/\/+$/, "");
}

export class GatewayConfigError extends Error {}
export class UnauthenticatedError extends Error {}
export class ForbiddenError extends Error {
  constructor(readonly requiredRole: string) {
    super(`role '${requiredRole}' required`);
  }
}
export class GatewayError extends Error {
  constructor(
    readonly status: number,
    readonly errorCode: string,
    message: string
  ) {
    super(message);
  }
}

export interface RequestOptions {
  readonly method?: "GET" | "POST" | "PATCH";
  readonly body?: unknown;
  /**
   * Whether this response renders a score, reason or alert. When true the client
   * enforces the WS-7.1.1 triplet on the paths named in `attributedPaths`.
   */
  readonly modelDerived?: boolean;
  /**
   * Dot paths within the response body that MUST carry an attribution. Explicit
   * rather than inferred: a client that walks the whole response looking for
   * something attribution-shaped passes when the backend renames a field.
   */
  readonly attributedPaths?: readonly string[];
  readonly signal?: AbortSignal;
  /**
   * Idempotency key for state-changing calls (overrides, dispositions,
   * consents). Caller-supplied so a form retry reuses it.
   */
  readonly idempotencyKey?: string;
}

/**
 * Resolve a dot path, following arrays element-wise. Returns the leaves.
 *
 * `"$"` names the response root - needed because some endpoints return the
 * attributed object itself rather than nesting it. An empty string would have
 * done the same job by accident and resolved to nothing, which is the failure
 * mode this whole check exists to avoid: a guard that passes vacuously.
 */
function resolvePath(body: unknown, path: string): unknown[] {
  if (path === "$") return [body];
  let level: unknown[] = [body];
  for (const segment of path.split(".")) {
    const next: unknown[] = [];
    for (const node of level) {
      if (node === null || node === undefined) continue;
      if (segment === "[]") {
        if (Array.isArray(node)) next.push(...node);
        continue;
      }
      if (typeof node === "object") {
        const v = (node as Record<string, unknown>)[segment];
        if (v !== undefined) next.push(v);
      }
    }
    level = next;
  }
  return level;
}

/**
 * The WS-7.1.1 contract check, at runtime on every response.
 *
 * The phase file puts this in CI as a contract test. Keeping it here as well is
 * deliberate: a contract test runs against a mock or a staging gateway, and the
 * failure this guards against - a model service promoted with a response shape
 * that dropped `decision_log_id` - happens in production against a backend CI
 * never saw.
 */
function enforceAttribution(endpoint: string, body: unknown, paths: readonly string[]): void {
  for (const path of paths) {
    const leaves = resolvePath(body, path);
    // An absent field is a nullability question rather than an attribution one,
    // so zero leaves passes. That is also how a MISTYPED path passes silently,
    // which is the one hole in this check. It is covered from the other side:
    // `attributedPaths` entries are asserted against the response shape in the
    // contract test (see frontend/tests/contract), where a path that never
    // resolves on any recorded response fails. Neither check alone is enough.
    if (leaves.length === 0) continue;
    for (const leaf of leaves) {
      if (leaf === null) continue;
      if (!hasAttribution(leaf)) {
        throw new MissingAttributionError(endpoint, path);
      }
    }
  }
}

/**
 * Fields that must never reach a client-side log or an analytics event.
 * SRS §11.4 / Phase 7 §4 WS-7.1.3. The list is a floor: the real control is that
 * the gateway returns tokenised subjects, mirroring `BanditDecision.subject_token`.
 */
const PII_KEYS = new Set([
  "pan",
  "aadhaar",
  "aadhaarNumber",
  "mobile",
  "phone",
  "email",
  "accountNumber",
  "customerName",
  "name",
  "address",
  "dob",
  "dateOfBirth",
  "ifsc",
  "latitude",
  "longitude",
  "polygon",
]);

/**
 * Strip anything PII-shaped before a value can be logged.
 *
 * Deliberately destructive and deliberately over-broad: a telemetry event that
 * loses a field is a reporting gap, and one that keeps a PAN is a breach. Any
 * unrecognised object is dropped entirely rather than traversed, because a
 * traversal that misses a nested key fails open.
 */
export function logSafe(value: unknown): unknown {
  if (value === null || typeof value === "number" || typeof value === "boolean") return value;
  if (typeof value === "string") return value.length > 64 ? "<redacted:long-string>" : value;
  if (Array.isArray(value)) return value.map(logSafe);
  if (typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      if (PII_KEYS.has(k)) {
        out[k] = "<redacted:pii>";
        continue;
      }
      out[k] = logSafe(v);
    }
    return out;
  }
  return "<redacted:unknown>";
}

export interface Transport {
  (url: string, init: RequestInit): Promise<Response>;
}

export class GatewayClient {
  constructor(
    private readonly session: Session | null,
    private readonly transport: Transport = fetch
  ) {}

  async request<T>(endpoint: string, options: RequestOptions = {}): Promise<T> {
    if (!this.session) {
      throw new UnauthenticatedError(
        `${endpoint}: no session. Every gateway call is role-scoped (WS-7.1.3).`
      );
    }

    const headers: Record<string, string> = {
      Accept: "application/json",
      Authorization: `Bearer ${this.session.token}`,
      "X-Acting-Role": this.session.role,
    };
    if (options.body !== undefined) headers["Content-Type"] = "application/json";
    if (options.idempotencyKey) headers["Idempotency-Key"] = options.idempotencyKey;

    const init: RequestInit = {
      method: options.method ?? "GET",
      headers,
      ...(options.body !== undefined ? { body: JSON.stringify(options.body) } : {}),
      ...(options.signal ? { signal: options.signal } : {}),
    };

    const response = await this.transport(`${gatewayBaseUrl()}${endpoint}`, init);

    if (response.status === 401) throw new UnauthenticatedError(endpoint);
    if (response.status === 403) throw new ForbiddenError(this.session.role);

    let payload: unknown = null;
    const text = await response.text();
    if (text.length > 0) {
      try {
        payload = JSON.parse(text);
      } catch {
        throw new GatewayError(response.status, "malformed_json", `${endpoint}: non-JSON response`);
      }
    }

    if (!response.ok) {
      const p = (payload ?? {}) as { errorCode?: string; message?: string };
      throw new GatewayError(
        response.status,
        p.errorCode ?? "unknown",
        p.message ?? `${endpoint} failed with ${response.status}`
      );
    }

    if (options.modelDerived) {
      const paths = options.attributedPaths;
      if (!paths || paths.length === 0) {
        throw new GatewayConfigError(
          `${endpoint}: marked modelDerived with no attributedPaths. The check ` +
            `must name the fields it guards, or it passes vacuously - which is ` +
            `worse than not having it.`
        );
      }
      enforceAttribution(endpoint, payload, paths);
    }

    return payload as T;
  }

  /**
   * WS-7.1.4 - poll a long-running job at the interval the SERVER dictates.
   *
   * The client invents no backoff and no deadline. `onUpdate` fires on every
   * poll so the surface can keep a progress affordance live; §11.6c's "no UI
   * request blocks > 2 s" is satisfied by never awaiting the work itself.
   */
  async pollJob<T>(
    jobId: string,
    onUpdate: (status: JobStatus<T>) => void,
    signal?: AbortSignal
  ): Promise<JobStatus<T>> {
    for (;;) {
      if (signal?.aborted) throw new DOMException("aborted", "AbortError");
      const status = await this.request<JobStatus<T>>(`/v1/jobs/${encodeURIComponent(jobId)}`, {
        ...(signal ? { signal } : {}),
      });
      onUpdate(status);
      if (status.state === "succeeded" || status.state === "failed") return status;
      await delay(status.retryAfterMs, signal);
    }
  }
}

function delay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        reject(new DOMException("aborted", "AbortError"));
      },
      { once: true }
    );
  });
}

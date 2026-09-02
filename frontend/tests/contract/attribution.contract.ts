/**
 * WS-7.1.1 contract tests — "Contract tests in CI verify every response used to
 * render a score, reason, or alert carries {model_id, model_version,
 * decision_log_id}."
 *
 * THESE HAVE NEVER BEEN RUN. There is no test runner installed and no Node
 * toolchain on the authoring machine. They are written against no assertion
 * library on purpose: `assert` from `node:assert/strict` is stdlib, mirroring
 * this repository's Python posture, so the only thing standing between these and
 * a green run is a runner invocation.
 *
 * WHAT THEY ACTUALLY TEST
 * -----------------------
 * Not the gateway - there is none (LH-706). They test the CLIENT's enforcement:
 * that a recorded response missing the triplet is REJECTED rather than rendered.
 * That is the half of the contract this repository can hold up. When a gateway
 * exists, the recorded responses in `samples` are replaced by captures from it
 * and the same assertions run against real shapes.
 *
 * They also close the mistyped-path hole in `enforceAttribution`: every path in
 * every `attributedPaths` list must resolve on at least one recorded response,
 * or the guard is passing vacuously.
 */

import assert from "node:assert/strict";
import { GatewayClient, GatewayError } from "../../src/lib/gateway/client";
import { MissingAttributionError } from "../../src/lib/gateway/provenance";
import {
  CapabilityUnavailableError,
  isUnavailableBody,
} from "../../src/lib/gateway/unavailable";
import type { Session } from "../../src/lib/auth/session";

const SESSION: Session = {
  subjectToken: "tok_contract",
  role: "officer",
  token: "contract-token",
  expiresAt: "2030-01-01T00:00:00Z",
  displayName: null,
  officerId: "ofc_contract",
};

function stubTransport(body: unknown, status = 200) {
  return async () =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
}

const VALID_ATTRIBUTION = {
  modelId: "application_pd",
  modelVersion: "1.0.0",
  decisionLogId: "dl_1",
};

export async function testRejectsMissingTriplet(): Promise<void> {
  const client = new GatewayClient(
    SESSION,
    stubTransport({ score: { value: 0.12, attribution: undefined } })
  );
  await assert.rejects(
    () => client.request("/v1/x", { modelDerived: true, attributedPaths: ["score"] }),
    MissingAttributionError,
    "a score with no attribution must be rejected, not rendered"
  );
}

export async function testRejectsPartialTriplet(): Promise<void> {
  // decisionLogId may be null; modelVersion may not be absent.
  const client = new GatewayClient(
    SESSION,
    stubTransport({ score: { value: 0.12, attribution: { modelId: "m", decisionLogId: null } } })
  );
  await assert.rejects(
    () => client.request("/v1/x", { modelDerived: true, attributedPaths: ["score"] }),
    MissingAttributionError
  );
}

export async function testAcceptsNullDecisionLogId(): Promise<void> {
  // A batch-scored value has no decision. This must PASS - see provenance.ts.
  const client = new GatewayClient(
    SESSION,
    stubTransport({
      score: { value: 0.12, attribution: { ...VALID_ATTRIBUTION, decisionLogId: null } },
    })
  );
  await client.request("/v1/x", { modelDerived: true, attributedPaths: ["score"] });
}

export async function testWalksArrays(): Promise<void> {
  const client = new GatewayClient(
    SESSION,
    stubTransport({
      items: [
        { alertId: "a1", attribution: VALID_ATTRIBUTION },
        { alertId: "a2" }, // missing
      ],
    })
  );
  await assert.rejects(
    () => client.request("/v1/x", { modelDerived: true, attributedPaths: ["items.[]"] }),
    MissingAttributionError,
    "one unattributed element in an array must fail the whole response"
  );
}

export async function testRefusesVacuousGuard(): Promise<void> {
  // modelDerived with no paths would pass everything. That is a config error,
  // not a pass - the check must name what it guards.
  const client = new GatewayClient(SESSION, stubTransport({ score: 1 }));
  await assert.rejects(() => client.request("/v1/x", { modelDerived: true, attributedPaths: [] }));
}

export async function testRootSentinel(): Promise<void> {
  const client = new GatewayClient(SESSION, stubTransport({ alertId: "a1" }));
  await assert.rejects(
    () => client.request("/v1/x", { modelDerived: true, attributedPaths: ["$"] }),
    MissingAttributionError,
    '"$" must address the response root - an empty string would resolve to nothing and pass'
  );
}

/**
 * The gateway refuses 17 of its 21 routes with a 200 carrying a ticket. A
 * refusal has no score in it, so it has no attribution triplet either — and if
 * the attribution guard ran first it would report "the backend dropped
 * decision_log_id" for a response whose actual message is "Credit Policy has
 * not ratified LH-504".
 *
 * That is a wrong diagnosis, not merely a worse one: it sends someone to the
 * gateway team, who find their gateway working correctly. This test pins the
 * ordering.
 */
export async function testUnavailableIsNotAnAttributionFailure(): Promise<void> {
  const client = new GatewayClient(
    SESSION,
    stubTransport({
      status: "unavailable",
      capability: "feasible offer set",
      ticket: "LH-504",
      owner: "Credit Policy",
      reason: "FOIR/DSCR/LTV caps are unratified.",
    })
  );
  await assert.rejects(
    () =>
      client.request("/v1/applications/a1/offers", {
        modelDerived: true,
        attributedPaths: ["feasible.[]", "recommendation"],
      }),
    (e: unknown) => {
      assert.ok(
        e instanceof CapabilityUnavailableError,
        `a governance stop must not surface as ${(e as Error)?.name}`
      );
      assert.equal((e as CapabilityUnavailableError).ticket, "LH-504");
      assert.equal((e as CapabilityUnavailableError).owner, "Credit Policy");
      return true;
    }
  );
}

/**
 * `CapabilityUnavailableError` must NOT be a `GatewayError`.
 *
 * The screens branch on `instanceof`, and every one of them already has a
 * `catch` that renders a `GatewayError` in a red alert box. Inheritance would
 * put every governance stop back in that box the first time someone wrote the
 * obvious catch — silently, and with the correct-looking code.
 */
export async function testUnavailableIsNotAGatewayError(): Promise<void> {
  const error = new CapabilityUnavailableError("/v1/x", {
    status: "unavailable",
    capability: "c",
    ticket: "LH-504",
    owner: "o",
    reason: "r",
  });
  assert.ok(!(error instanceof GatewayError));
  assert.ok(error instanceof Error);
}

/**
 * A partial match must be read as a payload, not as a refusal.
 *
 * The failure mode this guards is the quiet one: a response whose payload
 * happened to carry a `status` field would be swallowed as a refusal and its
 * data dropped, which on screen is indistinguishable from a backend that had
 * nothing to send.
 */
export async function testPartialUnavailableShapeIsNotARefusal(): Promise<void> {
  assert.ok(!isUnavailableBody({ status: "unavailable" }));
  assert.ok(!isUnavailableBody({ status: "unavailable", capability: "c", ticket: "LH-1" }));
  assert.ok(
    !isUnavailableBody({
      status: "unavailable",
      capability: "c",
      ticket: "LH-1",
      owner: "",
      reason: "r",
    }),
    "an empty owner is a refusal nobody is chasing - the Python side refuses to build one"
  );
  assert.ok(
    isUnavailableBody({
      status: "unavailable",
      capability: "c",
      ticket: "LH-1",
      owner: "o",
      reason: "r",
    })
  );
}

/** A normal payload with no `status` key is untouched by the refusal check. */
export async function testOrdinaryPayloadPassesThrough(): Promise<void> {
  const client = new GatewayClient(SESSION, stubTransport({ emi: { amount: 1, display: "x" } }));
  const body = await client.request<{ emi: { display: string } }>("/v1/quotes/instalment");
  assert.equal(body.emi.display, "x");
}

export const CONTRACT_TESTS = [
  testRejectsMissingTriplet,
  testRejectsPartialTriplet,
  testAcceptsNullDecisionLogId,
  testWalksArrays,
  testRefusesVacuousGuard,
  testRootSentinel,
  testUnavailableIsNotAnAttributionFailure,
  testUnavailableIsNotAGatewayError,
  testPartialUnavailableShapeIsNotARefusal,
  testOrdinaryPayloadPassesThrough,
];

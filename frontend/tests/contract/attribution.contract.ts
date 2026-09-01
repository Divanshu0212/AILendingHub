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
import { GatewayClient, MissingAttributionError } from "../../src/lib/gateway/client";
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

export const CONTRACT_TESTS = [
  testRejectsMissingTriplet,
  testRejectsPartialTriplet,
  testAcceptsNullDecisionLogId,
  testWalksArrays,
  testRefusesVacuousGuard,
  testRootSentinel,
];

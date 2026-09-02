#!/usr/bin/env node
/**
 * The contract-test runner.
 *
 * `attribution.contract.ts` exports six tests and nothing invoked them, so
 * importing the module ran zero assertions and exited 0 — a suite that cannot
 * fail, which is worse than no suite because CI reports it green.
 *
 * This runs each exported test, reports per-test status, and exits non-zero on
 * the first failure so a CI step fails visibly.
 *
 * Run with `npm test` (which uses tsx to strip the TypeScript types — the tests
 * themselves import only `node:assert/strict`, per the repository's stdlib
 * posture).
 */

// The client refuses to construct without a gateway origin — deliberately, so a
// lending client cannot silently fall back to a built-in host. These tests never
// make a request (the transport is a stub returning recorded responses), so an
// unroutable placeholder satisfies the constructor without pointing anywhere.
// It is set before the import because the check runs at module load.
process.env.NEXT_PUBLIC_GATEWAY_BASE_URL ??= "https://gateway.invalid";

const { CONTRACT_TESTS } = await import("./contract/attribution.contract.ts");

let failed = 0;

for (const test of CONTRACT_TESTS) {
  try {
    await test();
    console.log(`  ok   ${test.name}`);
  } catch (error) {
    failed += 1;
    console.error(`  FAIL ${test.name}`);
    console.error(`       ${error instanceof Error ? error.message : String(error)}`);
  }
}

const total = CONTRACT_TESTS.length;
if (failed) {
  console.error(`\n${failed} of ${total} contract test(s) failed.`);
  process.exit(1);
}
console.log(`\n${total} contract tests passed.`);

# ADR-0003 — Two-track execution: local reference implementation and bank deployment

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-08-31 |
| Decider | Data Platform Lead |
| Workstream | WS-0 (all) |
| Consulted | Model Risk, Credit DS |

## Context

Every Phase 0 deliverable as written assumes bank infrastructure: a Kafka cluster, a
lakehouse over five years of CBS history, a Feast deployment, an MLflow server, an
existing production scorecard to rebuild. None of it exists yet, and Phase 0 §3 lists
the data-sharing approvals that would unlock it as *entry* criteria that have not landed
(LH-120).

Two failure modes follow, and both are common enough to name:

1. **Wait for the bank.** Engineering stalls for months behind a committee. When access
   finally arrives, the platform is written under time pressure against real data, which
   is the worst possible moment to be discovering that a point-in-time join is subtly
   wrong.
2. **Mock the bank.** Build against invented data and invented thresholds. The code
   works, the numbers are fiction, and by the time real data arrives nobody remembers
   which constants were real — the exact outcome Master §2 exists to prevent.

## Options considered

### A. Single track, blocked on bank access

Honest about the dependency, and it keeps synthetic data out of the tree entirely. But it
converts a four-month phase into a four-month wait, and it front-loads all platform risk
into the period when it is most expensive to find.

### B. Single track, on synthetic data shaped like the bank's

Fast, and it exercises the code paths. But a synthetic-data platform accumulates
implicit assumptions about distributions, key cardinality and join behaviour that the
real data will violate, and Master §2 rule 3 forbids the resulting data from entering a
training table anyway. The deeper problem is that a number computed on synthetic data
looks exactly like a gate number.

### C. Two tracks against one interface

Build every Phase 0 component twice at the boundary but once in substance: a Track A
local implementation over fixtures, and a Track B adapter to the real backend, meeting at
an explicit port. Costs an interface per component, and the discipline to keep Track A
results out of gate evidence.

## Decision

**Option C.** Each platform package exposes a `ports.py` interface; Track A implements it
in stdlib Python over `tests/fixtures/`, Track B implements it against the real backend
(Delta/Iceberg, Kafka, Feast, MLflow, the orchestrator).

The rule that makes this safe: **a Track A number is evidence about the code, never
evidence about the portfolio.** A join rate computed on fixtures tests the audit script's
arithmetic; it says nothing about whether 99.5% of real loans join. Every number in
`reports/` is stamped with the track that produced it, and the Phase 0 gate accepts only
Track B numbers for its four numeric criteria.

A consequence worth stating plainly: **Phase 0 cannot be exited on Track A.** The gate
needs real join rates, a real GL reconciliation, real stream freshness and real scorecard
parity. What Track A buys is that when access lands, the remaining work is running the
scripts, not writing them.

## Consequences

- The test suite runs on a clean clone with no install step, so a new contributor is
  productive in one command and CI has a job (`clean-clone`) that keeps it that way.
- Heavy dependencies cannot creep into core logic — they live behind ports and in the
  `platform` extra. This is a real constraint, not a preference: it is what keeps Track A
  runnable.
- Two implementations of each port can drift. Mitigated by contract tests that run the
  same assertions against whichever implementation is configured.
- Someone will eventually paste a Track A number into a gate pack. The track stamp in
  every report exists so that a reviewer catches it.

## Revisit if

Bank access lands for all sources (LH-120 closed) and Track A stops earning its keep as a
fast test substrate — at which point Track A narrows to a test fixture layer rather than a
parallel implementation.

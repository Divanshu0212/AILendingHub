# Phase 0 — status and traceability

Maps every item on the Phase 0 §6 deliverables checklist to the artifact that
satisfies it, the track it runs on (ADR-0003), and its honest state.

**Read the track column before quoting any number.** A Track A result is evidence
about the code; only Track B counts as gate evidence.

Last updated: 2026-08-31.

## Deliverables checklist

| # | Phase 0 §6 item | Artifact | Track | State |
|---|---|---|---|---|
| 1 | Source registry (YAML, CI-validated) | [config/sources/](../../config/sources/) · [registry/](../../src/lending_hub/registry/) · `make registry` | A+B | **done** — 10 sources, schema-validated in CI |
| 2 | Lakehouse live; ADR-001, ADR-002 merged | [ADR-0001](../adr/0001-lakehouse-table-format.md) · [ADR-0002](../adr/0002-pipeline-orchestrator.md) · [lakehouse/layers.py](../../src/lending_hub/lakehouse/layers.py) | A | **partial** — layer contract built and enforced; ADRs Proposed pending ratification; no cluster (LH-120) |
| 3 | Identity spine + join-rate audit (≥ 99.5%) | [identity/](../../src/lending_hub/identity/) · `make audit-joins` | A | **partial** — spine, survivorship and root-caused audit built; gate needs real extracts (LH-120). Metric corrected — see LH-122 |
| 4 | GL reconciliation (≤ 0.1%) + committed script | [lakehouse/reconcile.py](../../src/lending_hub/lakehouse/reconcile.py) · `make reconcile` | — | **blocked** — logic built and tested; needs the GL mapping (LH-150) and balances (LH-120) |
| 5 | Kafka + schema registry; 2 streams < 60 s | [streaming/](../../src/lending_hub/streaming/) · `make schemas` | A | **partial** — both schemas defined, backward-compat enforced in CI, freshness measurement built; no cluster (LH-120) |
| 6 | Feast deployed; point-in-time training-join demo | [featurestore/](../../src/lending_hub/featurestore/) | A | **partial** — reference PIT join + skew detection built and tested; Feast deployment pending (LH-120) |
| 7 | MLflow + CI promotion pipelines; repro test green | [mlops/](../../src/lending_hub/mlops/) · `make repro` | A | **partial** — promotion gate and reproducibility test green in CI; MLflow server pending (LH-120) |
| 8 | Serving skeleton load-test report | [serving/](../../src/lending_hub/serving/) · `make loadtest` | A | **partial** — orchestrator + load test built; Track A bounds platform overhead only, not the gate |
| 9 | Ratified model-risk policy; templates merged | [docs/governance/](../governance/) | — | **partial** — all three templates merged; policy ratification is LH-160 |
| 10 | Consent schema + tokenization; retention config | [privacy/](../../src/lending_hub/privacy/) · [config/retention.yaml](../../config/retention.yaml) | A | **partial** — all three built; every retention period and PII class pending (LH-110, LH-111, LH-140) |
| 11 | Definitions package v1 tagged and ratified | [definitions/](../../src/lending_hub/definitions/) | A+B | **partial** — v1 implemented, fingerprinted, test-pinned; Risk ratification outstanding; 2 terms pending (LH-101, LH-102) |
| 12 | Legacy scorecard rebuilt; ≥ 99.9% parity | [serving/parity.py](../../src/lending_hub/serving/parity.py) · `make parity` | A | **partial** — comparator + discrepancy classification built and passing batch-vs-serving; the gate needs legacy outputs (LH-120) |

## The four numeric gates (Phase 0 §7)

None can be met on Track A. This is the honest headline of Phase 0.

| Gate | Threshold | State |
|---|---|---|
| Join rate | ≥ 99.5% | Script built, gate-blocked on LH-120 |
| GL delta | ≤ 0.1% | Script built, gate-blocked on LH-150 + LH-120 |
| Stream freshness | < 60 s | Measurement built, gate-blocked on LH-120 |
| Scorecard parity | ≥ 99.9% | Comparator built, gate-blocked on LH-120 |

## What is actually finished

Engineering that does not depend on bank access, and is done:

- Master Appendix A as importable, fingerprinted constants — the P1-unblocking deliverable.
- Master §2 grounding rules as a CI gate that has already caught two of its author's own defects.
- Source registry with `[POLICY]`-aware schema validation.
- Identity spine with root-caused join auditing, and a corrected gate metric (LH-122).
- Point-in-time join with two-timestamp knowability, TTL, and skew detection.
- Stream schemas with CI-enforced backward compatibility.
- Tamper-evident decision log with replay spot-audit.
- Promotion gate encoding Master §3.2 and WS-0.2.2.
- Reproducibility test asserting both halves of the triplet contract.
- Tokenization, consent artifacts, retention validation.
- Orchestrator with structural policy precedence and graceful degradation.
- Parity comparator with discrepancy classification.

233 tests, stdlib only, green on a clean clone.

## What is blocked, and on whom

See [blocking_tickets.md](blocking_tickets.md). The critical path is **LH-120**
— written data-sharing approvals. It is a Phase 0 *entry* criterion (§3), which
means Phase 0 has not formally started; what exists is everything buildable
before it does.

## Findings raised against the docs

Per Master §1, conflicts become tickets rather than silent fixes.

| Ticket | Finding |
|---|---|
| LH-121 | SRS §2.1 omits LOS and collections, but Phase 0 §2 requires both and WS-0.1.3 joins across all three |
| LH-122 | The WS-0.1.3 join metric as written measures the delinquency rate, because a healthy loan has no collections record |
| LH-103 | Appendix A names write-off and distress restructure as default triggers but never says which CBS codes carry those meanings |

See [Phase_0_FINDINGS.md](../../Lending_Hub_Phase_Docs/Phase_0_FINDINGS.md) for
the full set, including the ones that did not become tickets.

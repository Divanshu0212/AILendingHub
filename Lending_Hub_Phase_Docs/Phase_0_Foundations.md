# Phase 0 — Foundations: Data Platform, Feature Store, Governance

| Phase card | |
|---|---|
| Duration | Months 1–4 |
| SRS modules | §2 (architecture), §11 (cross-cutting) |
| Depends on | — (first phase) |
| Unblocks | Every later phase |
| Squads | Data platform (R), Model Risk (governance), DPO/Compliance |
| Governing contract | `00_MASTER_Implementation_Guide.md` §2 (grounding rules), §3 (protocols), §4 (definitions) — binding |

> **Implementation addendum (2026-08-31).** Phase 0 is being built in this
> repository. Nothing in this document has been edited — Master §1 requires
> conflicts to be raised as tickets, not resolved silently by an implementer.
>
> - [Phase_0_FINDINGS.md](Phase_0_FINDINGS.md) — findings against this document,
>   including two corrections (the join-rate gate and the default definition) and
>   the point-in-time contract gap.
> - [docs/phase0/STATUS.md](../docs/phase0/STATUS.md) — checklist traceability:
>   which artifact satisfies each item and its honest state.
> - [docs/phase0/blocking_tickets.md](../docs/phase0/blocking_tickets.md) — every
>   `[POLICY]` value the phase is waiting on.
> - [docs/adr/0003-two-track-execution-model.md](../docs/adr/0003-two-track-execution-model.md)
>   — how the phase proceeds while its §3 entry criteria are unmet.

**Objective.** Stand up the platform every later phase depends on — lakehouse, feature store, streaming backbone, model registry, governance scaffolding — and **prove** it by rebuilding one existing scorecard with bit-for-bit reproducibility. Phase 0 ships no new ML on purpose: it ships trust in the plumbing.

---

## 2. Position in the program

**Inputs:** access to core banking (CBS), loan origination (LOS), collections, bureau extracts, KYC store; executive sponsorship; draft model-risk policy.

**Outputs consumed by later phases:**

| Output | Consumed by |
|---|---|
| Lakehouse (Bronze/Silver/Gold) + 5-yr performance history | P1–P4 training data |
| Feast feature store (offline+online, point-in-time joins) | Every model, every phase |
| Kafka + schema registry, 2 live event streams | P1 velocity features, P3 dashboards, P4 EWS |
| MLflow registry + CI train/deploy pipelines | Every model promotion |
| Identity spine (customer/account/loan keys) | All joins; P1 entity resolution builds on it |
| Definitions package v1 (Master Appendix A) | P1 target engineering onward |
| Model card / validation / decision-log templates | Every gate review |

---

## 3. Entry criteria

- Executive sponsor named; squad staffing confirmed.
- Written data-sharing approvals from CBS, bureau, collections, LOS owners.
- Model-risk policy exists in draft (ratification is a P0 deliverable).

**If the approvals do not land on time.** This is common, and the two instinctive
responses are both wrong: idling wastes the phase, and building against invented
data violates Master §2 outright. The sanctioned path is the **two-track execution
model** ([ADR-0003](../docs/adr/0003-two-track-execution-model.md)) — every
component is built once against an explicit interface, with a local
reference implementation over `tests/fixtures/` and an adapter to the real
backend. The rule that keeps it honest: **a Track A number is evidence about the
code, never about the portfolio**, and the phase **cannot be exited on Track A**
because all four numeric gates below require real data. What the track buys is
that when access lands, the remaining work is running the scripts rather than
writing them.

---

## 4. Workstreams

### WS-0.1 Data platform

1. **Source inventory & contracts.** Enumerate every source in SRS §2.1 — **including LOS and collections**, which the identity spine joins. Per source: owner, extract mechanism (CDC / API / SFTP batch), refresh cadence, PII classification `[POLICY: DPO]`, and the **point-in-time block**: which column carries `event_timestamp` (when the fact became true) and which carries `created_timestamp` (when the platform learned it). A source that cannot supply the second is point-in-time unsafe and must be declared as such — see WS-0.2.1. Deliverable: machine-readable source registry (one YAML per source, schema-validated in CI).
2. **Lakehouse.** Bronze (raw immutable) → Silver (cleaned, conformed) → Gold (feature-ready) on an ACID table format — Delta Lake or Apache Iceberg, decision recorded as **ADR-001**. Time-travel/versioning enabled on every table (this is what makes SRS CS-7 "reproducible for 8 years" physically possible).
3. **Identity spine.** Deterministic customer/account/loan keys across CBS↔LOS↔collections; survivorship rules documented (attribute-level exceptions to system-of-record precedence are `[POLICY: Data Governance Council]`). Fuzzy matching is deliberately **out of scope** (it belongs to P1 fraud entity resolution) — a spine that quietly fuzzy-matches inflates its own join rate, so the gate below would measure the matcher's optimism rather than the data.

   `[DATA]` audit target: **≥ 99.5% on each of three separately mandatory join directions.** A single "joins across all three systems" rate is the wrong metric: a healthy loan has no collections record, so that number would be approximately `1 − delinquency_rate` — a clean book fails the gate and a deteriorating one appears to improve.

   | Check | Direction | Mandatory because |
   |---|---|---|
   | `loan_to_application` | CBS → LOS | every active loan traces to an originating application |
   | `collections_to_loan` | collections → CBS | referential integrity; an orphan case is a real break |
   | `customer_consistency` | across all three | one loan must not carry different customer keys |

   Note the asymmetry: LOS legitimately holds applications that never became loans (declines, withdrawals), so CBS → LOS is mandatory while the reverse is not. Failures are **root-caused as they are counted** — `missing_application`, `orphan_collections_case`, `customer_disagreement`, `unusable_key` (null / placeholder / charset / truncation) — because a bare percentage tells an engineer nothing about what to fix.
4. **Streaming backbone.** Kafka cluster + schema registry (Avro/Protobuf; backward-compatible evolution enforced in CI). Prove it end-to-end with exactly two streams: **repayment postings** and **application submissions** → Flink job → online feature with freshness < 60 s.
5. **Historical backfill.** ≥ 5 years (7+ where available) into Silver: applications, disbursals, monthly account snapshots, DPD histories, write-offs, recoveries, collections actions. `[DATA]` reconciliation: portfolio totals vs. finance GL within 0.1%; the reconciliation script is committed and rerunnable. **Amounts are integer minor units throughout** — summing decimal currency as floating point across millions of rows accumulates error at the same order of magnitude as the 0.1% tolerance, so a float reconciliation measures its own arithmetic. The product/balance-type → GL account mapping is `[POLICY: Finance Controller]`; a reconciliation on a guessed mapping produces agreement that means nothing. An **unmapped product fails the run** rather than appearing as a note: dropping a product silently removes balances from the platform total and makes the reconciliation look *better*.

### WS-0.2 Feature store & MLOps

1. **Feast** deployment: offline store = lakehouse Gold; online store = Redis/DynamoDB-class KV. **Contract for all phases:** production models read features *only* through Feast; training datasets are built *only* via `get_historical_features` point-in-time joins (kills future leakage and training/serving skew at the platform level).

   **What point-in-time correctness means here — two timestamps, not one.** The usual formulation, "latest value with `event_timestamp ≤ observation_point`", is *insufficient*, and the insufficiency is the most expensive defect in credit modelling. Every feature record carries `event_timestamp` (when the fact became true) and `created_timestamp` (when the platform learned it), and the join filters on **both**. A bureau refresh dated 3 March that landed in the warehouse on 20 March was not knowable on 10 March; joining on event time alone hands the model a value production could never have had, and the resulting lift is leakage that no offline metric distinguishes from skill — it evaporates in shadow, after months of work.

   Delegating to Feast does **not** close this on its own: Feast supports the two-timestamp join, but only if the ingestion pipeline carries `created_timestamp`. It is an extract requirement (WS-0.1.1), and it is the field extract teams drop because it looks redundant.

   Also required: a **TTL per feature**, so a stale value is not carried forward indefinitely (a four-year-old bureau score is not "the current bureau score" — it backtests beautifully and degrades on day one), and "never had a value" must be counted separately from "had one, but it expired", since the two need different fixes.
2. **MLflow** registry + experiment tracking. Stage moves (`None → Staging → Production → Archived`) happen only via CI pipelines — direct UI/manual promotion disabled.
3. **Training pipelines as code.** Airflow or Dagster DAGs (ADR-002); container-pinned environments with lockfiles; config-as-code. A registered model artifact = {code commit SHA, data snapshot version, config hash}. CI reproducibility test, **both halves**: (a) retrain a toy model twice from the same triplet → assert identical metrics; and (b) change any *one* triplet element → assert the metrics change. Half (a) alone is passed by a constant function, and by any pipeline that ignores its config; it demonstrates determinism but says nothing about whether the triplet *determines* the model, which is the property the whole reproducibility story rests on. Every source of randomness in training must trace to the triplet, or reproducibility is luck.
4. **Serving skeleton.** Model server (FastAPI + native LightGBM/ONNX) behind a Decision Orchestrator API stub. Load test with fixture keys (Master rule 3 — synthetic data in `tests/fixtures/` only): p99 feature-fetch < 100 ms, p99 score < 500 ms.

### WS-0.3 Governance scaffolding

1. Model-risk policy ratified — SR 11-7-aligned ([Fed SR 11-7](https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm)); model inventory; validation independence; model tiering (customer-affecting = Tier 1).
2. Templates committed to the repo: model card ([Mitchell et al., arXiv:1810.03993](https://arxiv.org/abs/1810.03993)), validation report, monitoring plan, decision-log schema (inputs, feature values, model versions, score, reasons, overrides).
3. Privacy: DPDP consent-artifact schema; PII tokenization service in the platform; per-table retention config `[POLICY: DPO + Compliance]`.

   **Blocking sub-item — the retention/erasure collision.** SRS CS-7 requires any decision reconstructable for ≥ 8 years and WS-0.1.2 mandates time travel to make that possible; DPDP gives the data principal an erasure right; a snapshot retained for reproducibility preserves rows an erasure request covers. Which duty overrides must be settled **per table, in writing, before Silver is loaded** — retrofitting row-level erasure into an existing tagged snapshot history is materially harder than designing for it. This is a legal position, not an engineering choice, and it is the actual blocker behind the retention config (not "how many years").
4. **Definitions package v1** (Master Appendix A) implemented as an importable code package and ratified by Risk — this is the P1 unblocking deliverable.

### WS-0.4 Proof-of-platform: rebuild the legacy scorecard

Rebuild the bank's current production scorecard (or bureau-score cutoff policy) on-platform from Silver data, serving through the orchestrator stub.

**Exit test:** on a frozen 12-month application sample, on-platform scores match legacy decisioning for **≥ 99.9%** of cases; every discrepancy root-caused in writing. This exercise is deliberately boring — it validates joins, point-in-time logic, and the serving path before any new ML exists.

---

## 5. Shipping ladder (P0 variant)

P0 ships infrastructure, not decisions, so the ladder is: dev → staging with production-shaped data → parallel-run of the rebuilt scorecard (shadow vs. legacy) → gate review. Nothing in P0 alters a customer outcome.

---

## 6. Deliverables checklist

- [ ] Source registry (YAML, CI-validated) — all SRS §2.1 sources
- [ ] Lakehouse live; ADR-001 (table format), ADR-002 (orchestrator) merged
- [ ] Identity spine + join-rate audit report (≥ 99.5%)
- [ ] GL reconciliation report (≤ 0.1% delta) + committed script
- [ ] Kafka + schema registry; 2 streams live with < 60 s freshness dashboards
- [ ] Feast deployed; point-in-time training-join demo notebook
- [ ] MLflow + CI promotion pipelines; reproducibility test green
- [ ] Serving skeleton load-test report (p99 targets met)
- [ ] Ratified model-risk policy; templates merged
- [ ] Consent schema + tokenization service; retention config loaded
- [ ] Definitions package v1 tagged and ratified
- [ ] Legacy scorecard rebuilt; ≥ 99.9% parity report

## 7. Exit criteria (gate review)

All checklist items evidenced; specifically the four numeric gates: join rate ≥ 99.5% (on each of the three directions in WS-0.1.3), GL delta ≤ 0.1%, stream freshness < 60 s, scorecard parity ≥ 99.9%. Model Risk Committee sign-off recorded.

**An unmeasurable gate is a fail, not a pass.** A join audit over an empty extract, a freshness window with no events, a parity run over an empty sample and a load test with zero requests all produce "no failures", and a naive implementation reports 100%, 0 s and PASS. That is the standard signature of an upstream pipeline that broke over a weekend. Every rate must return "not measured" on an empty denominator, and "not measured" must never satisfy a gate.

**Every gate number is produced by a committed, rerunnable script, and stamped with the track that produced it.** Only Track B output (real data, per ADR-0003) is gate evidence.

## 8. Do-not-invent list (P0)

Retention periods · consent wording · PII classifications · survivorship rule exceptions · GL mapping rules · **write-off and distress-restructure code sets** (Appendix A names both as default triggers but the source-system codes that identify them are bank mappings) · **fraud disposition taxonomy** · **tokenization key custody and rotation**. All `[POLICY]` — blocking ticket if missing.

Enforced mechanically by [`tools/check_grounding.py`](../tools/check_grounding.py): a placeholder must be well formed (`TBD[owner, TICKET-N]`), its ticket must exist in the phase's blocking-ticket register, and no placeholder may survive onto a release branch.

## 9. References for this phase

- Fed/OCC — *SR 11-7 Model Risk Guidance* — [link](https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm)
- Mitchell et al. — *Model Cards for Model Reporting* — [arXiv:1810.03993](https://arxiv.org/abs/1810.03993)
- Carbone et al. — *Apache Flink* — [PDF](http://sites.computer.org/debull/A15dec/p28.pdf)
- Open-source: [Feast](https://feast.dev) · [MLflow](https://mlflow.org) · [Delta Lake](https://delta.io) / [Apache Iceberg](https://iceberg.apache.org)

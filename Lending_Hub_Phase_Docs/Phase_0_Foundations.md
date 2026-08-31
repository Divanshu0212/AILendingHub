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

---

## 4. Workstreams

### WS-0.1 Data platform

1. **Source inventory & contracts.** Enumerate every source in SRS §2.1. Per source: owner, extract mechanism (CDC / API / SFTP batch), refresh cadence, PII classification `[POLICY: DPO]`. Deliverable: machine-readable source registry (one YAML per source, schema-validated in CI).
2. **Lakehouse.** Bronze (raw immutable) → Silver (cleaned, conformed) → Gold (feature-ready) on an ACID table format — Delta Lake or Apache Iceberg, decision recorded as **ADR-001**. Time-travel/versioning enabled on every table (this is what makes SRS CS-7 "reproducible for 8 years" physically possible).
3. **Identity spine.** Deterministic customer/account/loan keys across CBS↔LOS↔collections; survivorship rules documented. Fuzzy matching is deliberately **out of scope** (it belongs to P1 fraud entity resolution). `[DATA]` audit target: ≥ 99.5% of active loans join across the three systems on exact keys; failures root-caused in a written report.
4. **Streaming backbone.** Kafka cluster + schema registry (Avro/Protobuf; backward-compatible evolution enforced in CI). Prove it end-to-end with exactly two streams: **repayment postings** and **application submissions** → Flink job → online feature with freshness < 60 s.
5. **Historical backfill.** ≥ 5 years (7+ where available) into Silver: applications, disbursals, monthly account snapshots, DPD histories, write-offs, recoveries, collections actions. `[DATA]` reconciliation: portfolio totals vs. finance GL within 0.1%; the reconciliation script is committed and rerunnable.

### WS-0.2 Feature store & MLOps

1. **Feast** deployment: offline store = lakehouse Gold; online store = Redis/DynamoDB-class KV. **Contract for all phases:** production models read features *only* through Feast; training datasets are built *only* via `get_historical_features` point-in-time joins (kills future leakage and training/serving skew at the platform level).
2. **MLflow** registry + experiment tracking. Stage moves (`None → Staging → Production → Archived`) happen only via CI pipelines — direct UI/manual promotion disabled.
3. **Training pipelines as code.** Airflow or Dagster DAGs (ADR-002); container-pinned environments with lockfiles; config-as-code. A registered model artifact = {code commit SHA, data snapshot version, config hash}. CI reproducibility test: retrain a toy model twice from the same triplet → assert identical metrics.
4. **Serving skeleton.** Model server (FastAPI + native LightGBM/ONNX) behind a Decision Orchestrator API stub. Load test with fixture keys (Master rule 3 — synthetic data in `tests/fixtures/` only): p99 feature-fetch < 100 ms, p99 score < 500 ms.

### WS-0.3 Governance scaffolding

1. Model-risk policy ratified — SR 11-7-aligned ([Fed SR 11-7](https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm)); model inventory; validation independence; model tiering (customer-affecting = Tier 1).
2. Templates committed to the repo: model card ([Mitchell et al., arXiv:1810.03993](https://arxiv.org/abs/1810.03993)), validation report, monitoring plan, decision-log schema (inputs, feature values, model versions, score, reasons, overrides).
3. Privacy: DPDP consent-artifact schema; PII tokenization service in the platform; per-table retention config `[POLICY: DPO + Compliance]`.
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

All checklist items evidenced; specifically the four numeric gates: join rate ≥ 99.5%, GL delta ≤ 0.1%, stream freshness < 60 s, scorecard parity ≥ 99.9%. Model Risk Committee sign-off recorded.

## 8. Do-not-invent list (P0)

Retention periods · consent wording · PII classifications · survivorship rule exceptions · GL mapping rules. All `[POLICY]` — blocking ticket if missing.

## 9. References for this phase

- Fed/OCC — *SR 11-7 Model Risk Guidance* — [link](https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm)
- Mitchell et al. — *Model Cards for Model Reporting* — [arXiv:1810.03993](https://arxiv.org/abs/1810.03993)
- Carbone et al. — *Apache Flink* — [PDF](http://sites.computer.org/debull/A15dec/p28.pdf)
- Open-source: [Feast](https://feast.dev) · [MLflow](https://mlflow.org) · [Delta Lake](https://delta.io) / [Apache Iceberg](https://iceberg.apache.org)

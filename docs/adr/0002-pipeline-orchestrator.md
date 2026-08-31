# ADR-0002 — Pipeline orchestrator: Dagster

| Field | Value |
|---|---|
| Status | **Proposed** — awaiting Data Platform Lead ratification |
| Date | 2026-08-31 |
| Decider | Data Platform Lead |
| Workstream | WS-0.2.3 |
| Consulted | Credit DS, Model Risk, Platform SRE |

## Context

Phase 0 WS-0.2.3 requires "training pipelines as code — Airflow or Dagster DAGs
(ADR-002); container-pinned environments with lockfiles; config-as-code", such that
"a registered model artifact = {code commit SHA, data snapshot version, config hash}"
and a CI test can retrain the same triplet twice and assert identical metrics.

So the orchestrator is not only a scheduler here. It is the component that has to make
the reproducibility triplet true, and it has to keep making it true for eight years.

## Options considered

### A. Apache Airflow

The default in most banks, and that matters more than any technical argument: if the
bank already runs Airflow, the platform team, the on-call rota, and the deployment
tooling all exist on day one. Enormous operator ecosystem.

Against it for this use: Airflow's unit of work is a task, not a dataset. Lineage
("which data version produced this model") is something you build on top with XComs and
convention, and conventions decay. Local testing of a DAG is awkward enough that in
practice pipelines get tested in a staging scheduler rather than in unit tests — which
directly weakens the WS-0.2.3 requirement for a CI reproducibility test.

### B. Dagster

Asset-centric: the unit of work is the data asset produced, which maps onto
Bronze/Silver/Gold and onto "data snapshot version" without a translation layer. Lineage
between assets is structural rather than conventional, so "what fed this model" is a
property of the graph, not a query someone has to write. Pipelines are ordinary Python
that runs in-process, which makes the CI reproducibility test a normal unit test instead
of an integration environment.

Against it: a smaller operations community, fewer engineers who have run it in
production, and — if the bank already operates Airflow — a second orchestrator to staff,
patch and secure. That last cost is easy to underestimate and is usually what decides it.

### C. Airflow for platform ETL, Dagster for ML pipelines

Each tool where it is strongest. Rejected: two orchestrators means two lineage stories
and two answers to "what produced this model", and the seam lands exactly where the audit
trail must be continuous.

## Decision

**Dagster**, on the strength of one requirement: the reproducibility triplet and its CI
test are structural in an asset-centric orchestrator and conventional in a task-centric
one. A convention that must hold for eight years across staff turnover is not a control
Model Risk should be asked to accept.

This decision is genuinely close, and it is conditional — see *Revisit if*. It is
recorded as Proposed rather than Accepted because the deciding input is a fact about the
bank that we do not have yet: whether Airflow is already an operated platform service.

## Consequences

- Training pipelines are importable Python, so `make repro` runs the WS-0.2.3
  reproducibility test locally with no scheduler at all.
- Asset lineage feeds the model card automatically rather than being transcribed, which
  removes a class of documentation drift that validation reliably finds.
- If the bank runs Airflow, Phase 0 adds an orchestrator to the estate. That is a real
  operational cost owed to Platform SRE, and it should be surfaced at the gate review
  rather than discovered afterwards.
- Container pinning and lockfiles are required either way and are independent of this
  choice.

## Revisit if

Airflow turns out to be an established, well-operated bank platform service. In that case
the staffing and security cost of a second orchestrator likely outweighs the lineage
advantage, and the correct answer is Airflow plus an explicit, tested lineage convention —
with the reproducibility test kept as a first-class CI job so the convention has teeth.

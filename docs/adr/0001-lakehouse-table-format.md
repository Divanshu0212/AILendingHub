# ADR-0001 — Lakehouse table format: Apache Iceberg

| Field | Value |
|---|---|
| Status | **Proposed** — awaiting Data Platform Lead ratification |
| Date | 2026-08-31 |
| Decider | Data Platform Lead |
| Workstream | WS-0.1.2 |
| Consulted | Model Risk (reproducibility), Streaming Platform Lead, BI/Dashboards (P3) |

## Context

Phase 0 WS-0.1.2 requires Bronze/Silver/Gold on an ACID table format with
"time-travel/versioning enabled on every table — this is what makes SRS CS-7
'reproducible for 8 years' physically possible", and records the choice as ADR-001.

The constraints that actually decide this:

| Constraint | Source |
|---|---|
| Any decision reconstructable for ≥ 8 years from stored features and the registered model | SRS §12 auditability, CS-7; Master §3.3 |
| A registered model = {code commit SHA, **data snapshot version**, config hash} | Phase 0 WS-0.2.3 |
| Flink writes repayment/application streams into the lakehouse | Phase 0 WS-0.1.4 |
| Trino/BI reads Gold for risk dashboards | SRS §2.1, P3 |
| Feast offline store reads Gold | Phase 0 WS-0.2.1 |
| Per-table retention and DPDP erasure must be executable as row-level deletes | SRS §11.4; LH-111 |

The 8-year duty is the sharp one. It is not "we keep history"; it is "a named snapshot
from 2026 is still readable in 2034".

## Options considered

### A. Delta Lake

Mature ACID layer, excellent Spark integration, well-understood time travel, and the
obvious choice if the bank is already standardised on Databricks — where it is
operationally cheaper than anything else by a wide margin.

Against it here: time travel is bounded by the table's retention configuration, and
history is reclaimed by `VACUUM`. Reproducing a 2026 training set in 2034 means
guaranteeing that no vacuum ever reclaimed the files behind that version, across eight
years of operations staff who will reasonably be trying to control storage cost. That is
a process guarantee, not a structural one, and process guarantees are exactly what SR
11-7 validation probes. Engine access outside the Spark ecosystem has improved (UniForm,
Delta Kernel) but remains the weaker side.

### B. Apache Iceberg

Engine-neutral by construction: Spark, Flink, Trino, and most warehouse engines read it
through a shared catalog. Two properties matter directly here:

- **Named snapshot tags and branches.** A training run can tag the exact snapshot it
  read (`train-2026-11-pd-retail`), and a tag is a durable named reference with its own
  retention, not a version number that ages out of a rolling window. That turns "data
  snapshot version" in the WS-0.2.3 reproducibility triplet into a first-class object.
- **First-class Flink sink**, which WS-0.1.4 needs on day one.

Hidden partitioning also removes a recurring correctness hazard: consumers cannot silently
full-scan (or mis-filter) because they did not know the physical partition transform.

Against it: more moving parts — a catalog service must be chosen and operated — and a
smaller pool of engineers with production experience than Delta-on-Databricks.

### C. Both, via format interop

Technically possible and occasionally sensible. Rejected for Phase 0: two metadata layers
means two sets of retention semantics and two answers to "what did this table look like on
that date", which is the one question the platform exists to answer.

## Decision

**Apache Iceberg**, with the catalog choice deferred to its own ADR once the bank's
existing metastore is known.

The deciding reason is narrow and worth stating alone: **snapshot tags make the 8-year
reproducibility duty structural rather than procedural.** Every other difference between
the two formats is smaller than that, and every other difference could be lived with.

## Consequences

- The reproducibility triplet gains a concrete referent: training pipelines tag the
  snapshot they read and record the tag in MLflow, and `lending_hub.lakehouse.ports`
  exposes `snapshot_tag` as part of the read contract.
- Retention and DPDP erasure run as row-level deletes plus snapshot expiry, with tagged
  snapshots explicitly excluded from expiry — which means **the erasure design and the
  reproducibility design collide**, and the collision is real, not theoretical: a tagged
  snapshot preserves rows a data principal asked to erase. This needs a written
  resolution from DPO and Compliance before Silver is loaded (**LH-111**).
- A catalog becomes an operated service with its own availability requirement.
- Engineers unfamiliar with Iceberg need ramp-up; budget it in WS-0.1.2.

## Revisit if

The bank is already standardised on Databricks with an operating Unity Catalog. In that
case Delta's operational advantage likely outweighs the tag argument, and the 8-year duty
is met with an explicit, audited retention policy that forbids vacuuming tagged versions —
a process control the Model Risk Committee would have to accept in writing.

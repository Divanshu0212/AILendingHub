# ADR-0013 — Phase 2 without imagery, a portfolio, or a calendar

| Field | Value |
|---|---|
| Status | Accepted (Track A scope) · Blocked (Track P and Track B scope) |
| Date | 2026-09-01 |
| Decider | Geospatial DS Lead (Track A) · Model Risk (Track B) |
| Workstream | WS-2.1, WS-2.2, WS-2.3, WS-2.4 |
| Consulted | Agri Credit (policy owner), Platform, Fair Lending |
| Related | [ADR-0003](0003-two-track-execution-model.md), [ADR-0004](0004-public-reference-data-track.md), [ADR-0012](0012-phase3-panel-source.md) |

## Context

Phase 2 is the first phase in this repository whose **entry criteria are
categorically unsatisfiable**, and it is worth being precise about why, because
"blocked" has meant three different things across P0, P1 and P3.

Phase 2 §3 requires three things:

1. P0 gate passed — it has not, and cannot (Phase 0's own entry criteria are
   `[POLICY]`-blocked on LH-120).
2. A `[DATA]` inventory of the historical agri portfolio with outcomes and
   location granularity — **LH-406**. No such portfolio exists here.
3. `[POLICY: Agri Credit Head]` ratification of agro-climatic zones, per-zone
   crop lists, sowing windows and input costs — **LH-102, LH-402, LH-404,
   LH-401**. None ratified.

And it needs a fourth thing the §3 list does not mention because it is assumed:
**satellite imagery**. `datasets/` holds three tabular credit datasets and no
raster of any kind. Sentinel-2 and Sentinel-1 are freely available from the
Copernicus Data Space, but a Phase 2 scene stack over a bank's operating
districts across three seasons is measured in terabytes, and the phase card says
the phase "must overlap one full crop season" — a calendar constraint no amount
of engineering removes.

This is materially different from Phase 3's situation. Phase 3 had no bank panel
but a **real 19-year mortgage panel** stood in, and the resulting numbers, while
not gate evidence, were facts about real lending. Phase 2 has no equivalent:
there is no substitute agri book, and the policy values it needs are not
approximable from any public source, because a crop calendar for the wrong
agro-zone is not an approximation of the right one — it is a different calendar
that produces a confidently wrong sowing flag.

## Decision

**Build Phase 2 on Track A only, and state the absence of Track P as a
structural gate state rather than an unrun job.**

Concretely:

1. **Every computation ships, in full**, on the interfaces Track B swaps out:
   SPI/SPEI, NDVI/EVI and backscatter series, cloud masking, plot geometry, the
   IoU metric and its gate, the RF baseline and its earn-your-complexity
   comparison, temperature scaling, the fallback yield regression and the
   P50/P25/P10 contract, the three credit-feature formulas, and the three
   backtests. These are testable against known-answer cases without a single
   satellite scene.
2. **The imagery boundary is a port, not a stub.** `agri.ports` defines the
   scene-access interface Copernicus fills on Track B. Nothing in the core
   packages imports a geospatial library, and no fixture raster is ever
   presented as a scene.
3. **The three deep-learning models are not ported.** SAM, U-Net and Presto are
   fine-tuned foundation models; a stdlib re-derivation of them would be a
   different model wearing the paper's name. Master §2 rule 2 permits "use that
   library, or port it with unit tests reproducing the library's outputs" — and
   neither branch is available with no imagery to reproduce outputs *on*. What
   ships instead is what each model's **contract** requires of its consumers:
   the evaluation metric, the gate, the post-processing, the calibration, the
   abstention rule, and the baseline each is required to beat. See §"What is
   deliberately not built" below.
4. **No number in Phase 2 is labelled Track P**, because none is. The
   `agri` gate pack reports every exit criterion as `not measurable` with the
   reason, and `make gate2` will not print a metric it did not compute.

## What this genuinely establishes

Less than Phase 3 did, and the list is short on purpose:

* **The SPI computation is verified against a published reference**, which is
  the one thing in WS-2.1 that has a known answer independent of any bank
  (Phase 2 §4 mandates exactly this test).
* **The credit-feature formulas refuse to compute** rather than producing an
  income figure from an invented input cost. On a smallholder plot the input
  cost is the same order as gross revenue, so this is the difference between a
  wrong number and no number.
* **The plot registry cannot store a village centroid as a plot.** Phase 2 §4
  states the rule in prose; here it is an invariant that raises, because the
  prose version survives exactly as long as the first officer under a deadline.
* **The three backtests have a runnable harness with no data**, which makes
  "(a), (b), (c) unmeasured" a fact about LH-406 rather than about the
  engineering.

## What is deliberately not built

Stated plainly, because a phase whose gaps are implicit reads as complete:

| Not built | Why | Ticket |
|---|---|---|
| Model A (SAM/U-Net fine-tune) | No imagery, no GPS-walk labels. The IoU gate, watershed post-processing contract and area-mismatch fraud flag **are** built | LH-407 |
| Model B (Presto fine-tune) | No imagery, no ground-truth crop labels, no ratified class set. The RF baseline, calibration, abstention rule and the +5 macro-F1 comparison **are** built | LH-404, LH-406 |
| Model C (histogram-CNN/LSTM + GP) | No imagery, no government yield series joined to districts. The **auditable fallback regression is built first**, as §4 instructs, and the P50/P25/P10 contract with it | LH-406 |
| Ingestion DAGs | Airflow is Track B (ADR-0002). The **completeness monitors** and source contracts are built | LH-120 |
| PostGIS plot registry | The registry logic is built in memory against `agri.ports`; PostGIS is the Track B backend | LH-120 |
| Underwriter evidence UI | No rendering surface exists anywhere in this repository — the same gap Phase 3 recorded for its dashboards. Adoption telemetry is meaningless without it | — |

## Consequences

* Phase 2's gate pack will report **0 of 6 exit criteria measured**, and five of
  the six as *not measurable* rather than *not measured*. That distinction, new
  in Phase 3, is what stops a structural gap being scheduled as a task.
* CLAUDE.md's statement that "P2 was skipped deliberately" is superseded: the
  phase is now **built to the boundary of what is groundable**, which is a
  better artifact than a skip, because it makes the boundary itself explicit and
  reviewable.
* A Track B team receives working code for every deterministic component and a
  precise, ticketed list of the three models and one dataset they must supply.

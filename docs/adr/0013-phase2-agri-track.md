# ADR-0013 — Phase 2 without imagery, a portfolio, or a calendar

| Field | Value |
|---|---|
| Status | Accepted (Track A scope) · **Amended 2026-09-01** (Track P scope, see §Amendment) · Blocked (Track B scope) |
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
| Model A (SAM/U-Net fine-tune) | No GPS-walk labels for the bank's book. The IoU gate, watershed post-processing contract and area-mismatch fraud flag **are** built. **Amended**: a Track P benchmark is now available (Fields of The World, ~10k Indian polygons) — see the Amendment | LH-407 |
| Model B (Presto fine-tune) | No imagery, no ground-truth crop labels, no ratified class set. The RF baseline, calibration, abstention rule and the +5 macro-F1 comparison **are** built | LH-404, LH-406 |
| Model C (histogram-CNN/LSTM + GP) | No imagery, no government yield series joined to districts. The **auditable fallback regression is built first**, as §4 instructs, and the P50/P25/P10 contract with it | LH-406 |
| Ingestion DAGs | Airflow is Track B (ADR-0002). The **completeness monitors** and source contracts are built | LH-120 |
| PostGIS plot registry | The registry logic is built in memory against `agri.ports`; PostGIS is the Track B backend | LH-120 |
| Underwriter evidence UI | No rendering surface exists anywhere in this repository — the same gap Phase 3 recorded for its dashboards. Adoption telemetry is meaningless without it | — |

## Amendment (2026-09-01) — one blocker was a sourcing gap, not a structural one

A dataset search conducted after the build found that **this ADR overstated the
Track P position for Model A**, and that its imagery argument was framed in the
wrong unit. Full detail and verification in
[docs/phase2/DATA_SOURCING.md](../phase2/DATA_SOURCING.md); the corrections are:

1. **Field boundaries exist.** [Fields of The
   World](https://fieldsofthe.world/) publishes ~10,000 hand-delineated Indian
   smallholder field polygons as a single 7.8 MB CC-BY-4.0 GeoParquet, columns
   `id`/`area`/`geometry`/`determination_datetime`, bbox 68.8-96.2°E by
   9.2-34.5°N. Downloaded and inspected. Model A's gate needs 100 held-out
   polygons and this is a hundred times that, so **a Track P benchmark for Model
   A is now possible.** It is not the GPS-walk set: these are photo-interpreted,
   which Phase 2 §8 does not admit as a plot boundary, so LH-407 stands for the
   bank's own book and a `PlotSource.PHOTO_INTERPRETED` member would be needed.

2. **The imagery argument used the wrong unit.** This ADR said a scene stack "is
   measured in terabytes". True of raw L2A, and irrelevant: nothing in `agri/`
   consumes a scene. `SceneSource` returns per-plot reductions, and those come
   from CropHarvest's 68 MB pre-extracted feature archive, the Sentinel Hub
   Statistical API, or Earth Engine `reduceRegions` — kilobytes per plot. The
   real binding constraint on the index pipeline is **LH-102**, because without a
   crop calendar there is no season window to reduce over.

3. **Two blockers were confirmed, one of them by measurement.** CropHarvest is
   named in the phase file and does not solve Model B: of 95,186 global labels,
   2,597 fall inside India's bounding box and **34 carry a crop type** across
   seven crops. Against a §7 criterion of macro-F1 ≥ 0.85 on five majority crops
   per zone, that is not a small sample, it is no sample. And no public
   loan-level agri credit outcome data exists anywhere — RBI publishes
   aggregates only — so LH-406 is confirmed structural.

**The decision below is unchanged and so is the gate.** All six exit criteria
remain not measurable, because each depends on LH-406 or LH-102 and neither
moved. What changed is the *reason* Model A is blocked, and conflating a
sourcing gap with a structural one is precisely the error the not-measured /
not-measurable distinction exists to prevent — so recording it here matters more
than it changes.

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

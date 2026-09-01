# Phase 2 — status and traceability

Maps every item on the Phase 2 §6 deliverables checklist to the artifact that
satisfies it, the track it runs on, and its honest state.

**Phase 2 has no Track P.** That is the single most important thing on this
page. Phase 1 and Phase 3 each had real public data standing in for the bank's
— real applications, a real 19-year panel — so their numbers, while never gate
evidence, were facts about real lending. Phase 2 has no imagery, no agri
portfolio and no ratified crop calendar, and none of the three is approximable:
a crop calendar for the wrong agro-zone is not an approximation of the right
one. See [ADR-0013](../adr/0013-phase2-agri-track.md).

Last updated: 2026-09-01.

## The headline

Every **deterministic** component of Phase 2 is built and unit-tested on Track
A. **None** of its three models is trained, and **none** of its three backtests
has a denominator. That split is not a schedule position — it is where the
grounding contract cuts:

| What ships | What does not | Why |
|---|---|---|
| SPI/SPEI, NDVI/EVI, backscatter, cloud masking, plot geometry, IoU + its gate, RF baseline, temperature scaling, fallback yield regression, P50/P25/P10 contract, the three feature formulas, the three backtest harnesses | Model A (SAM/U-Net), Model B (Presto), Model C (histogram-CNN + GP), ingestion DAGs, PostGIS, the evidence UI | No imagery exists in this repository, and no agri book with outcomes. Both are ticketed, neither is engineering work |

Ten Phase 2 tickets are open ([register](blocking_tickets.md)), LH-401 to
LH-410. Five are the Phase 2 §8 do-not-invent values. **Four were found by
building** and are not on that list — LH-407 (the GPS-walk label set nobody
scheduled), LH-408 (the mandi price *window*, as opposed to the feed), LH-409
(where an abstaining model's cases actually go), LH-410 (the geographic units a
disparate-impact memo compares).

## Deliverables checklist (Phase 2 §6)

| # | Item | Artifact | Track | State |
|---|---|---|---|---|
| 1 | Ingestion DAGs (S2/S1/CHIRPS/ERA5/IMD/SoilGrids/DEM) + completeness monitors | — | — | **not started** |
| 2 | Plot registry (PostGIS) + officer GPS-walk capture | — | — | **not started** |
| 3 | Index pipelines with SPI unit test green | — | — | **not started** |
| 4 | Model A/B/C registered in MLflow with model cards | — | — | **not started** |
| 5 | RF baseline + fallback yield regression | — | — | **not started** |
| 6 | Feature aggregation package with policy sign-off record | — | — | **not started** |
| 7 | Backtest report (a)/(b)/(c) with scripts | — | — | **not started** |
| 8 | Underwriter evidence UI live; adoption telemetry | — | — | **not measurable** — no rendering surface exists in this repository, and adoption telemetry without a UI measures nothing |
| 9 | Geographic disparate-impact analysis of agri features | — | — | **not started** |

## Exit criteria (Phase 2 §7)

| # | Criterion | State |
|---|---|---|
| 1 | Backtests (a) LQI monotone, (b) ≥ +4 Gini, (c) non-sowing ≥ 60% at ≥ 45 days | **not measurable** — no agri portfolio with outcomes (LH-406) |
| 2 | Crop classifier macro-F1 ≥ 0.85 on 5 majority crops per zone | **not measurable** — no ground truth, no ratified class set (LH-404) |
| 3 | Boundary IoU ≥ 0.75 vs held-out GPS-walk polygons | **not measurable** — no walk set (LH-407) |
| 4 | Underwriter adoption ≥ 70% of agri files opened in the evidence UI | **not measurable** — no UI, no agri files |
| 5 | Model cards + independent validation for Models A/B/C | **not measurable** — no models; Master §3.1 also requires a validator who is not the developer |
| 6 | Disparate-impact memo filed | **not measurable** — needs both the features and the ratified comparison units (LH-410) |

**Track B evidence: 0 of 6. Not measurable: 6 of 6.**

Phase 3 reported two of six as not-measurable and treated that as notable.
Phase 2 reports all six, which says something the individual rows do not: this
phase's gate is not blocked on effort anywhere.

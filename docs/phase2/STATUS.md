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

Twelve Phase 2 tickets are open ([register](blocking_tickets.md)), LH-401 to
LH-412. Five are the Phase 2 §8 do-not-invent values. **Five were found by
building** and are on no §8 list — LH-407 (the GPS-walk label set nobody
scheduled), LH-408 (the mandi price *window*, as opposed to the feed), LH-409
(where an abstaining model's cases actually go), LH-411 (the function combining
LandQualityIndex's six named inputs), LH-412 (which crop season a default
belongs to). LH-410 (the geographic comparison units) was likewise not on the
list.

`make gate2` assembles the pack. There is no `make trackp-p2`, and there will
not be one.

## Deliverables checklist (Phase 2 §6)

| # | Item | Artifact | Track | State |
|---|---|---|---|---|
| 1 | Ingestion DAGs (S2/S1/CHIRPS/ERA5/IMD/SoilGrids/DEM) + completeness monitors | [ingest.py](../../src/lending_hub/agri/ingest.py) · [ports.py](../../src/lending_hub/agri/ports.py) | A | **partial** — the completeness monitor is built and answers its three questions separately (job health, cloud, plot coverage); reanalysis records must carry a provider vintage. DAGs are Airflow, i.e. Track B (ADR-0002); the three source contracts were registered in Phase 0 |
| 2 | Plot registry (PostGIS) + officer GPS-walk capture | [registry.py](../../src/lending_hub/agri/registry.py) · [geometry.py](../../src/lending_hub/agri/geometry.py) | A | **partial** — registry logic built on the `PlotStore` seam, with "a centroid is not a plot" as a type rather than a convention. PostGIS is Track B; the field app is not in this repository and the walk set it produces is LH-407 |
| 3 | Index pipelines with SPI unit test green | [drought.py](../../src/lending_hub/agri/drought.py) · [indices.py](../../src/lending_hub/agri/indices.py) | A | **done** — SPI/SPEI, NDVI/EVI, backscatter, cloud masking. Phase 2 §4 names one explicit unit test in the whole phase and it is green |
| 4 | Model A/B/C registered in MLflow with model cards | [model_cards/](model_cards/) | — | **not measurable** — none of the three models is built (ADR-0013): no imagery, no labels, and Master §2 rule 2 admits neither branch. Each model's *contract* is built and each has a card recording what a Track B team must supply. MLflow is Track B |
| 5 | RF baseline + fallback yield regression (kept, documented) | [crop.py](../../src/lending_hub/agri/crop.py) · [yield_model.py](../../src/lending_hub/agri/yield_model.py) | A | **done** — both built and unit-tested. The fallback satisfies the full P50/P25/P10 contract without the GP, from its own residual distribution, and says on every prediction that it is not a posterior |
| 6 | Feature aggregation package with policy sign-off record | [features.py](../../src/lending_hub/agri/features.py) | A | **partial** — the formulas are implemented as §4 writes them and refuse to evaluate: income needs input costs (LH-401) and LandQualityIndex has no combining function at all (LH-411). No sign-off record, because there is nothing signed to record |
| 7 | Backtest report (a)/(b)/(c) with scripts | [backtest.py](../../src/lending_hub/agri/backtest.py) | A | **partial** — the harness is built including the point-in-time proof against *publication* dates, and takes no threshold arguments. No report: LH-406 supplies no denominator |
| 8 | Underwriter evidence UI live; adoption telemetry | — | — | **not measurable** — no rendering surface exists in this repository, and adoption telemetry without a UI measures nothing |
| 9 | Geographic disparate-impact analysis of agri features | [disparate.py](../../src/lending_hub/agri/disparate.py) | A | **partial** — measurement built; it refuses a verdict without LH-410 and reports the land-quality gap beside the disparity, because in this phase the agronomic signal and the disparity are one number |

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

Generated live by `make gate2` into `reports/phase2_gate.md`.

Phase 3 reported two of six as not-measurable and treated that as notable.
Phase 2 reports all six, which says something the individual rows do not: this
phase's gate is not blocked on effort anywhere.

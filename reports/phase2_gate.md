# Phase 2 — gate evidence pack

Generated 2026-09-01T17:42:01.140840+00:00 by `tools/phase2_gate_report.py`.

**Phase 2 has no Track P.** Phase 1 and Phase 3 each had real public
data standing in for the bank's, so their numbers — never gate evidence —
were at least facts about real lending. Phase 2 has no imagery, no agri
portfolio and no ratified crop calendar, and none is approximable: a crop
calendar for the wrong agro-zone is a different calendar, not a noisy
version of the right one. See [ADR-0013](../docs/adr/0013-phase2-agri-track.md).

This pack therefore quotes **no metrics**. A Measured column filled with
figures computed on fixtures would teach the reader that the column
contains evidence.

## Exit criteria (Phase 2 §7)

| # | Criterion | Workstream | Track | State |
|---|---|---|---|---|
| 1 | Backtests (a) LQI quartiles order agri NPA monotonically, (b) >= +4 Gini from agri features, (c) non-sowing flag on >= 60% of season-linked defaults at >= 45 days | WS-2.4 | — | **not measurable** — all three need this bank's historical agri portfolio with outcomes and location granularity over >= 3 seasons (LH-406). No public dataset substitutes: the criteria are statements about this bank's agri book. (c) additionally needs the season-attribution rule (LH-412) |
| 2 | Crop classifier macro-F1 >= 0.85 on the 5 majority crops per zone, on held-out ground truth | WS-2.2 Model B | — | **not measurable** — needs ground-truth crop labels from crop-cutting experiments and officer visits (LH-406) and the ratified per-zone class set that defines what 'the 5 majority crops' means (LH-404). The RF baseline, macro-F1 and the +5-point earn-it rule are built and unit-tested |
| 3 | Boundary IoU gate met (median >= 0.75 vs held-out GPS-walk polygons) | WS-2.2 Model A | — | **not measurable** — needs the officer GPS-walk polygon set (LH-407), which is field work with a season's lead time and which no workstream in the programme plan schedules. The IoU metric, the gate and its distribution reporting are built and unit-tested |
| 4 | Underwriter adoption >= 70% of agri files opened in the evidence UI | Phase 2 §5 step 1 | — | **not measurable** — there is no rendering surface of any kind in this repository — the same gap Phase 3 recorded for its dashboards — and no agri files to open. Adoption telemetry without a UI measures nothing |
| 5 | Model cards + independent validation for Models A/B/C | Master §2 rule 5, §3.1 | — | **not measurable** — none of the three models exists (ADR-0013), so there is nothing to validate. Master §3.1 separately requires a validator who is not the developer, and there is none |
| 6 | Geographic disparate-impact memo filed | WS-2.4 / SRS §11.3 | — | **not measurable** — needs both the agri features on a real book (LH-406) and the ratified geographic comparison units and disparity bar (LH-410). The measurement code is built and refuses to reach a verdict without them |

**Track B evidence: 0 of 6. Not measurable: 6 of 6.**

## Why every criterion, and not just some

Phase 3 reported two of six as not measurable and treated the distinction
as worth carrying through the pack. Phase 2 reports all six, and the
aggregate says something the individual rows do not: **this phase's gate
is not blocked on effort anywhere.** There is no task in this repository
whose completion moves any of the six.

Three of the six are blocked on one thing — LH-406, the historical agri
portfolio — which is Phase 2 §3's own entry criterion. A phase whose entry
criteria are unmet cannot have exit criteria met, and stating that once at
the top is more useful than discovering it six rows down.

## Deliverables (Phase 2 §6)

The distinction this column carries: *blocked on data or policy* against
*is a Track B backend*. They call for different responses.

| # | Deliverable | State |
|---|---|---|
| 1 | Ingestion DAGs + completeness monitors | **monitors built** (`agri.ingest`); DAGs are Airflow, i.e. Track B (ADR-0002). The three source contracts were registered in Phase 0 (`config/sources/satellite.yaml`, `weather.yaml`, `soil_geo.yaml`) |
| 2 | Plot registry (PostGIS) + officer GPS-walk capture | **registry logic built** (`agri.registry`, `agri.geometry`) against the `agri.ports.PlotStore` seam; PostGIS is Track B. The field app is not in this repository, and the walk set it would produce is LH-407 |
| 3 | Index pipelines with SPI unit test green | **built, and the mandated test is green** (`agri.drought`, `agri.indices`). Phase 2 §4 names one explicit unit test in the whole phase and this is it |
| 4 | Models A/B/C registered in MLflow with model cards | **not built** (ADR-0013). Each model's *contract* is built — the IoU gate, the calibration and abstention rules, the P50/P25/P10 output — and each has a card recording that the model behind it does not exist |
| 5 | RF baseline + fallback yield regression (kept, documented) | **both built** (`agri.crop`, `agri.yield_model`). Phase 2 §4 orders the fallback built first and kept forever; it is, and it satisfies the P50/P25/P10 contract without the GP |
| 6 | Feature aggregation package with policy sign-off record | **built** (`agri.features`); no sign-off record, because the two income formulas cannot be evaluated without input costs (LH-401) and LandQualityIndex has no ratified combining function at all (LH-411) |
| 7 | Backtest report (a)/(b)/(c) with scripts | **harness built** (`agri.backtest`), including the point-in-time proof against publication dates. No report: LH-406 supplies no denominator |
| 8 | Underwriter evidence UI live; adoption telemetry | **not built** — no rendering surface in this repository |
| 9 | Geographic disparate-impact analysis | **measurement built** (`agri.disparate`); it refuses a verdict without LH-410, and reports the land-quality gap beside the disparity because in this phase the agronomic signal and the disparity are one number |

## Model cards (Master §2 rule 5)

| Card | Signed |
|---|---|
| boundary_delineation.md | **no** |
| crop_classification.md | **no** |
| yield_estimation.md | **no** |

A card is written for each of Models A, B and C recording what the
contract requires and that the model behind it does not exist. None is
signed: Master §3.1 requires an independent validator, and a card for
an unbuilt model has nothing to validate.

## Open blocking tickets

| Ticket | Owner |
|---|---|
| LH-401 | Agri Credit Head |
| LH-402 | Agri Credit Head |
| LH-403 | Agri Credit Head + Credit Policy |
| LH-404 | Agri Credit Head |
| LH-405 | Credit Policy + Compliance |
| LH-406 | Agri Credit Head + Data Platform |
| LH-407 | Geospatial DS + Agri Credit Head |
| LH-408 | Agri Credit Head + Market Data |
| LH-409 | Model Risk + Geospatial DS |
| LH-411 | Credit Policy + Agri Credit Head |
| LH-412 | Agri Credit Head + Credit Policy |
| LH-410 | Fair Lending + Agri Credit Head |

12 open. Five are Phase 2 §8 do-not-invent values.
**Five were found by building** and are on no §8 list — LH-407 (the
GPS-walk label set nobody scheduled), LH-408 (the mandi price window,
as distinct from the feed), LH-409 (where an abstaining model's cases
go), LH-411 (the function combining LandQualityIndex's six named
inputs), LH-412 (which season a default belongs to).

## Gate outcome

**Fail — not presentable.** Master §3.1 offers pass / conditional pass /
fail, and none fits a phase with no measurable criterion. The honest
statement is that Phase 2 should not be taken to a Gate Review at all
until LH-406 and LH-102 land; a review with nothing to review consumes
committee time and produces a remediation list identical to the ticket
register above.

What a Track B team receives instead: every deterministic computation in
the phase, built and tested against the interfaces their backends occupy,
and a ticketed list of exactly three models and one dataset they must
supply.

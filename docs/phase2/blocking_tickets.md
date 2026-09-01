# Phase 2 — Blocking ticket register

Every `TBD[owner, ticket-id]` placeholder raised by Phase 2 work appears here.
`make grounding` reads every `docs/phase*/blocking_tickets.md` and fails on any
placeholder that appears in none of them.

Earlier registers: [Phase 0](../phase0/blocking_tickets.md) ·
[Phase 1](../phase1/blocking_tickets.md) · [Phase 3](../phase3/blocking_tickets.md).
Tickets from those still block Phase 2 — **LH-102** (the ratified zone crop
calendar) is Phase 2's own entry criterion held in Phase 0's register because
Appendix A's *Agri season* row depends on it, and **LH-120** (data-sharing
approvals) is why there is no agri portfolio to backtest against.

Phase 2 §8 puts these on the do-not-invent list: crop calendars & sowing windows ·
per-crop input costs · disbursal-tranching rules · qualifying-crop lists ·
natural-calamity relief treatment · **any plot polygon not observed or walked**.
Each one below is a stop, not a gap in the engineering.

| Ticket | Owner | Blocks | What is needed | Status |
|---|---|---|---|---|
| LH-401 | Agri Credit Head | `agri.features` `ExpectedIncome` / `StressedIncome`; every affordability cap built on them | Per-crop, per-zone **input costs** — the subtracted term in both income formulas. Phase 2 §4 WS-2.3 marks them `[POLICY: Agri Credit Head]` and §8 forbids inventing them. They are not a small correction: on a smallholder plot input costs are the same order of magnitude as gross revenue, so an invented figure does not perturb `ExpectedIncome`, it *determines its sign*. `expected_income()` raises without them. | open |
| LH-402 | Agri Credit Head | `agri.season`; sowing verification; the non-sowing flag in WS-2.4(c) | The **sowing windows** per zone and crop — the calendar dates within which sowing must be observed for a season to count as sown. Distinct from LH-102's Kharif/Rabi/Zaid *season* boundaries, which say when a season runs; a sowing window says when planting is expected inside it, and the non-sowing flag fires off the window, not the season. Phase 2 §8 do-not-invent. | open |
| LH-403 | Agri Credit Head + Credit Policy | Disbursal tranching; the shipping-ladder step 3 two-season rule | The **disbursal-tranching rules**: how much of a sanctioned limit releases against which verified sowing/crop-stage evidence, and what happens when verification fails mid-season. Phase 2 §8 do-not-invent and §5 step 3 names the rule without stating it. | open |
| LH-404 | Agri Credit Head | Crop classifier class set (Model B); qualifying-crop eligibility | The **qualifying-crop list** per agro-zone. This is the classifier's label space, so it is not a downstream filter — a class set chosen by an engineer decides what the model can *ever* predict, and adding a class later means retraining, not reconfiguring. Phase 2 §4 WS-2.2 requires "ratified zone crop list + fallow". | open |
| LH-405 | Credit Policy + Compliance | Any agri exposure treatment during a declared calamity | **Natural-calamity relief treatment** — how declared-calamity periods affect DPD ageing, staging and the default label. RBI norms apply and the bank's implementation of them is a policy mapping. Phase 2 §8 do-not-invent. Untreated, a drought season reads as a credit event in every model that shares Appendix A's default definition. | open |
| LH-406 | Agri Credit Head + Data Platform | Every `agri` model; WS-2.4 backtest (a), (b) and (c) | The **historical agri portfolio with outcomes and location granularity** — Phase 2 §3 entry criterion. Not a policy value but a data-availability stop: without plot GPS / village / pincode joined to agri NPA outcomes over ≥ 3 seasons, none of the three backtests has a denominator. No public dataset substitutes, because the backtests are statements about *this bank's* agri book. | open |
| LH-407 | Geospatial DS + Agri Credit Head | Model A training and its IoU gate; the plot registry's ground-truth channel | The **officer GPS-walk polygon set** — the ground truth Model A is fine-tuned on and evaluated against. Phase 2 §8 forbids storing any polygon not observed or walked, which makes this the only admissible label source, and collecting it is field work with a season's lead time. Raised as a Phase 2 finding: the phase file treats the walk set as an input without scheduling its collection. | open |
| LH-408 | Agri Credit Head + Market Data | `agri.features` price terms | The **mandi price distribution source and its P50/P25 convention**. WS-2.3 names Agmarknet as `[DATA]`, but the formulas need a *distribution* (P50 for expected, P25 for stressed) over a horizon nobody has specified — price at harvest, over the marketing season, or a forward. Raised as a Phase 2 finding: "Price_P50" reads as specified until code has to pick a window. | open |
| LH-409 | Model Risk + Geospatial DS | Model B "unsure" routing; Model A sub-gate plots | What the **operational fallback** is when a model declines to answer — a crop prediction below 0.6 confidence, or a plot whose delineation misses the IoU gate. Phase 2 §4 says such cases "require a manual walk" and "surface as unsure", which names the output but not who acts on it or within what SLA. Without it the models' abstention paths have no destination. | open |
| LH-411 | Credit Policy + Agri Credit Head | `agri.features.land_quality_index`; Phase 2 §7 exit criterion (a) | The **function** combining LandQualityIndex's six inputs — the weights, the direction of each term, and the normalisation. Phase 2 §4 WS-2.3 names the six inputs (soil organic carbon, slope, irrigation proxy, 5-yr mean peak-NDVI percentile, yield volatility, drought frequency) and never the function over them. Not on the §8 list; found by building — six named inputs read as a specification right up until code has to return a number. It cannot be filled in by an engineer, because LQI is precisely what exit criterion (a) tests: "LandQualityIndex quartiles order historical agri NPA rates monotonically" is not a test of anything if whoever runs it also chose the weights. `land_quality_index()` raises without a ratified formula; `land_quality_components()` returns the six normalised inputs, which are `[DATA]` and useful to an underwriter unweighted. | open |
| LH-410 | Fair Lending + Agri Credit Head | WS-2.4 disparate-impact memo; Phase 2 §6 deliverable 9 | The **protected geographic units and the disparity bar** for the agri disparate-impact analysis (SRS §11.3). LH-205 sets the bar for P1's application model; a geographic analysis needs its own unit of comparison (district? agro-zone? tribal-area designation?) and nothing ratifies one. A disparate-impact memo whose comparison units were chosen by the analyst measures the choice. | open |

## Why this register is committed before the placeholders

`make grounding` fails a placeholder that cites an unregistered ticket, and the
fix for that failure must never be "delete the placeholder". The register lands
first so that the first Phase 2 `TBD` has somewhere to go.

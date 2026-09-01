# Phase 3 — status and traceability

Maps every item on the Phase 3 §6 deliverables checklist to the artifact that
satisfies it, the track it runs on, and its honest state.

**Read the track column before quoting any number.** Track A is evidence about
the code, Track P is evidence that the code survives real data
([ADR-0004](../adr/0004-public-reference-data-track.md),
[ADR-0012](../adr/0012-phase3-panel-source.md)); only **Track B** counts as gate
evidence, and there is none.

Last updated: 2026-09-01.

## The headline

Every Phase 3 workstream is **built and exercised on a real 19-year mortgage
panel** — 5,081 loans and 338,210 account-months from the Fannie Mae 2007Q1
vintage, spanning both the 2008-11 credit event and the 2020-21 refinance wave.
No Phase 3 exit criterion has Track B evidence, and none can: Phase 3's entry
criteria require a bank panel (LH-120) and verified P1 decision logs (LH-204),
and neither exists.

Two of the six exit criteria are **not measurable** rather than not measured, and
so is the whole CCF workstream. That distinction is new in this phase and is
carried through the gate pack — a structural gap and an unrun job should not
appear in the same column.

`make trackp-p3` reproduces the run; `make gate3` assembles the pack.

## What the Track P run established

| Result | Where |
|---|---|
| Competing risks are decisive on a prepayment-heavy book: 60-month CIF of default **0.115** against a naive **0.169** — a **47% relative overstatement** | `observed_incidence` |
| The **LGD loss basis flips the sign of the LTV effect** (`oltv` −0.76 net of credit enhancement, **+2.55** gross) — a value nobody specified, now LH-311 | `lgd.by_basis`, `lgd.credit_enhancement_finding` |
| **84% of accounts cannot be staged at all** (4,253 of 5,081), and 0 are Stage 1 | `staging` |
| Cox ties at ~0.85 on a monthly panel; Efron and Breslow disagree materially | `cox`, `cox_tie_sensitivity` |
| The §7 challenger-vs-Cox comparison was **in-sample** and therefore favoured the ensemble by its own memorisation; it flipped sign with sample size until accounts were held out | `survival_metrics`; finding D6 |
| Current DPD **separates** a Cox model at monthly granularity | `cox_excluded_covariates` |
| A behavioural Gini and an origination C-index are not comparable — the ablation shows why | `behavioural_pd.ablation_without_arrears_features` |

Full narrative: [Phase_3_FINDINGS.md](../../Lending_Hub_Phase_Docs/Phase_3_FINDINGS.md).

## Deliverables checklist (Phase 3 §6)

| # | Item | Artifact | Track | State |
|---|---|---|---|---|
| 1 | Behavioural PD, Cox baseline, hazard GBM, competing-risks variant — registered + cards | [behavioural.py](../../src/lending_hub/portfolio/behavioural.py) · [cox.py](../../src/lending_hub/portfolio/cox.py) · [hazard.py](../../src/lending_hub/portfolio/hazard.py) · [competing.py](../../src/lending_hub/portfolio/competing.py) | A+P | **partial** — all four built and fitted on the real panel; three cards written and **unsigned**; none promotable (LH-310, and no independent validator) |
| 2 | LGD (two-stage) + EAD/CCF models + downturn memo | [lgd.py](../../src/lending_hub/portfolio/lgd.py) · [ead.py](../../src/lending_hub/portfolio/ead.py) | A+P | **partial** — LGD **stage 2 only** on 20,407 real workouts (stage 1 is LH-309); term-loan EAD is arithmetic and done; **CCF is not measurable** (no revolving product on any track, plus LH-303); downturn add-on is LH-302 |
| 3 | Staging service with provenance logging | [staging.py](../../src/lending_hub/portfolio/staging.py) | A+P | **partial** — every decision carries the rule that produced it; Stage 3 and the DPD-backstop arm work; **Stage 1 is unassignable** (LH-301, LH-308) and the engine says so rather than defaulting |
| 4 | Macro-conditioning models + scenario configs | [macro.py](../../src/lending_hub/portfolio/macro.py) | A | **partial** — Wilson-style logit regression fitted and validated against known coefficients; `shift()` works for sensitivity; `apply_scenario()` raises until LH-304 ratifies the scenario set |
| 5 | Flink aggregate jobs; OLAP store; ADR-030 | [aggregates.py](../../src/lending_hub/portfolio/aggregates.py) | A | **partial** — aggregation, freshness against the 5-minute SLO, and drill-through built in memory; Flink and the OLAP store are Track B (LH-120); ADR-030 not written, since the store choice is a deployment decision with no deployment |
| 6 | Dashboards: portfolio, concentration/weather, model-health, scenario widget | [aggregates.py](../../src/lending_hub/portfolio/aggregates.py) · [health.py](../../src/lending_hub/portfolio/health.py) · [opsanomaly.py](../../src/lending_hub/portfolio/opsanomaly.py) | A+P | **partial** — every *computation* behind the panels exists (PSI, ADWIN, calibration CUSUM, S-H-ESD, vintage curves, EAD by bucket). There is **no rendering surface of any kind**. Concentration cuts need LH-306; the weather overlay needs Phase 2 |
| 7 | Transition-matrix job + CUSUM alarms | [transitions.py](../../src/lending_hub/portfolio/transitions.py) | A+P | **partial** — matrices, roll rates and forward multiplication run on the real panel; the alarms have **no parameters** (LH-307) and `cusum()` requires them |
| 8 | Backtest report; ECL parallel-run reconciliation memo | `reports/trackP_p3_fannie_mae.json` | P | **partial** — the backtest runs out of time (split 2012-12-31) on Track P; the **ECL parallel run is not measurable** without a live provisioning process and a Finance signatory |
| 9 | Independent validation for all P3 models | [phase3_gate_report.py](../../tools/phase3_gate_report.py) | — | **not done** — Master §3.1 requires a validator who is not the developer; none exists on Track P, and `lending_hub.mlops.promotion` refuses the transition on that basis |

## Exit criteria (Phase 3 §7)

Generated live by `make gate3` into `reports/phase3_gate.md`. Summary:

| # | Criterion | State |
|---|---|---|
| 1 | Hazard C-index ≥ Cox + 0.02 and ≥ 0.75 | formable and now measured **out of sample** on held-out accounts (finding D6). Not gate evidence |
| 2 | PD calibration by grade within ±15% | not evaluable — grades need the bands LH-204 has not ratified |
| 3 | LGD MAE ≤ incumbent | **not measurable** — there is no incumbent |
| 4 | Dashboard freshness over 30 consecutive days | not evaluable — needs a live streaming surface |
| 5 | ECL parallel-run memo signed | **not measurable** — needs a bank deployment |
| 6 | Staging provenance audit clean | not evaluable — 84% of accounts have no stage to audit |

**Track B evidence: 0 of 6.**

## Open blockers

Eleven Phase 3 tickets, [registered here](blocking_tickets.md): LH-301 to LH-311.
Six are the Phase 3 §8 do-not-invent values. **Five were found by building** and
are not on that list — LH-307 (alarm parameters), LH-308 (origination lifetime
PD), LH-309 (cure definition), LH-310 (behavioural monotonicity), LH-311 (LGD
loss basis).

That ratio is the same one Phase 1 produced, and the Master's note on it applies
again: *"treat a short do-not-invent list as a sign the phase has not been
attempted rather than a sign it is simple."*

Earlier tickets that block Phase 3 too: **LH-103** (default code sets — they
decide the hazard model's numerator), **LH-120** (data-sharing approvals),
**LH-204** (no logged decisions, so no SICR baseline).

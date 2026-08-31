# Phase 3 — Portfolio Brain: PD/LGD/EAD + Risk Dashboards

| Phase card | |
|---|---|
| Duration | Months 7–10 |
| SRS modules | §7 (default prediction), §9 (real-time risk dashboards) |
| Depends on | Phase 1 shipped (decision logs flowing) |
| Unblocks | P4 (hazard model powers EWS; LGD/EAD powers pricing), P6 (survival challengers) |
| Squads | Credit DS (R), Platform/streaming (R for dashboards), Finance (C — ECL), Model Risk (A) |
| Governing contract | `00_MASTER_Implementation_Guide.md` §2–§4 — binding |

**Objective.** Give the bank a live view of book risk: behavioral PD, survival curves S(t), LGD/EAD, an IFRS-9 staging feed, and streaming risk dashboards with model-health monitoring. This is the read-side of the entire hub — P4's actions and P6's learning all consume what P3 builds.

---

## 2. Position in the program

**Inputs:** P0 platform + snapshots history; P1 decision logs and origination PDs; P2 district weather/NDVI layers (for macro conditioning and map overlays, when available).

**Outputs to later phases:**

| Output | Consumed by |
|---|---|
| Discrete-time hazard model + S(t) per account | P4 EWS (PD-velocity trigger), P6 challengers' benchmark |
| Behavioral PD (monthly + on-event) | Dashboards, staging, collections prioritization |
| LGD / EAD / CCF models | P4 risk-based pricing, ECL |
| Staging engine (Stage 1/2/3 with provenance) | Finance/ECL, dashboards |
| Streaming aggregates + OLAP store + dashboards | Risk users, P4 alert surfaces |
| Model-health panel (PSI/ADWIN/calibration) | All model owners, gate reviews |

---

## 3. Entry criteria

- P1 gate passed; decision logs verified complete.
- `[DATA]` ≥ 5 years of monthly account snapshots in Silver; collections/recovery cashflows reconciled to GL.
- Scenario set and SICR threshold proposals drafted for `[POLICY]` ratification (§8).

---

## 4. Workstreams

### WS-3.1 Models (SRS §7)

**Step 1 — Behavioral PD (ship first — it powers dashboards immediately).**
LightGBM on account-month rows; target = 90+ DPD within next 12 months (definitions package); features: DPD trajectory (max DPD 3/6/12m, times-in-arrears), utilization trend, payment-to-minimum ratio, bounce counts, enquiries since disbursal, deposit cash-flow aggregates, and (agri) current-season NDVI/SPEI status. Out-of-time validation by snapshot month. Calibration as in P1.

**Step 2 — Cox PH baseline (build before the challenger).**
Cox proportional hazards with time-varying covariates (`lifelines` / [scikit-survival](https://github.com/sebp/scikit-survival)): `λ(t|x) = λ₀(t)·exp(βᵀx_t)`. This is the interpretable reference every survival challenger must beat, and the model auditors will read first.

**Step 3 — Discrete-time hazard GBM (production challenger).**
Recast survival as discrete-time hazard: one row per account-month, target = "defaults this month", month-on-book dummies for the baseline hazard, monotone-constrained LightGBM (SRS §7.3.2c; methodology: [Tutz & Schmid, Springer 2016](https://link.springer.com/book/10.1007/978-3-319-28158-2); credit benchmark: [Dirick, Claeskens & Baesens, JORS 2017](https://d-nb.info/1122167008/34)). Survival curve S(t) via cumulative product of (1 − hazard). Metrics: Harrell's C-index, time-dependent AUC, integrated Brier, S(12m) calibration by decile.

**Step 4 — Competing risks.**
Prepayment competes with default. Production: multinomial discrete-time target {perform, prepay, default}. Sensitivity check on prepay-heavy products with **Fine–Gray** subdistribution hazards ([Fine & Gray, JASA 1999](https://www.tandfonline.com/doi/abs/10.1080/01621459.1999.10474144)).

**Step 5 — LGD.**
Two-stage (SRS §7.3.3): (i) cure probability (logistic/GBM); (ii) recovery rate on non-cured via **beta regression** ([Ferrari & Cribari-Neto, 2004](https://www.tandfonline.com/doi/abs/10.1081/STA-120037418)) or GBM on [0,1]; workout cashflows discounted at contract rate to default date. Drivers: collateral type & LTV, seasoning, geography, legal-recovery route, land quality (agri). Downturn add-on `[POLICY: Risk Committee, evidence-backed]`. Benchmark context: [Loterman et al., IJF 2012](https://www.sciencedirect.com/science/article/abs/pii/S0169207011000586).

**Step 6 — EAD/CCF (revolving products: KCC, OD, lines).**
`CCF = (EAD − B₀)/(L − B₀)`; GBM/tobit on limit, utilization, behavior ([Moral, in *The Basel II Risk Parameters*, Springer](https://link.springer.com/chapter/10.1007/978-3-642-16114-8_10)). Regulatory CCF floors `[POLICY]`.

**Step 7 — Staging engine (deterministic service).**
Stage 2 = lifetime-PD ratio vs. origination > threshold `[POLICY: Finance + Risk]` OR 30-DPD backstop OR P4 red flag (wired when P4 ships). Stage 3 = credit-impaired per definitions package. Every staging decision logged with rule provenance.

**Step 8 — Macro conditioning.**
Segment default-rate regressions on macro factors + district weather (SPEI, monsoon deviation) — Wilson-style ([Wilson, FRBNY EPR 1998](https://www.newyorkfed.org/research/epr/98v04n3/9810wils.html)). Scenario sets `[POLICY: ICAAP]`; used by the dashboard scenario widget and stress testing.

### WS-3.2 Dashboards (SRS §9)

1. **Streaming aggregates.** Flink jobs → OLAP store (Druid or ClickHouse, **ADR-030**): EAD, expected loss Σ PD·LGD·EAD, DPD buckets, roll-rate counters. Freshness SLO ≤ 5 min; **every panel shows a data-as-of timestamp** (a dashboard that hides staleness manufactures false confidence).
2. **Transition matrices.** Monthly + daily-incremental DPD-bucket Markov matrices per segment; CUSUM alarms on the 30→60 and 60→90 cells (earliest portfolio-level warning); forward-multiplication for short-horizon NPA forecasts.
3. **Model-health panel.** Weekly PSI/CSI per model and feature (alert > 0.1, act > 0.25); **ADWIN** streaming change detection on score distributions ([Bifet & Gavaldà, SDM 2007](https://www.cs.upc.edu/~gavalda/papers/adwin06.pdf), via [River](https://github.com/online-ml/river)); rolling calibration (observed vs expected by band) with CUSUM.
4. **Concentration & weather maps.** District choropleths of exposure; P2 SPEI/NDVI anomaly overlays ("monsoon risk map of the book"); limit-utilization alerts on concentration dimensions.
5. **Ops anomaly surfacing.** Seasonal-Hybrid ESD ([arXiv:1704.07706](https://arxiv.org/abs/1704.07706)) on operational metrics: application volumes per channel, approval rates, alert rates — catches pipeline breaks and agent-level manipulation without bespoke alerts.
6. **Drill-through everywhere.** Every aggregate resolves to the account list behind it, with lineage.

---

## 5. Shipping ladder

1. **Backtest** PD/hazard on 3 historical years, walk-forward.
2. **Parallel run** vs. incumbent provisioning models for one full quarter; Finance reconciles ECL deltas in a signed memo.
3. **Dashboards GA** to risk users (read-only path — can go live as soon as freshness SLO holds).
4. **Staging feed becomes system-of-record** only after auditor review `[POLICY: CFO]`.

## 6. Deliverables checklist

- [ ] Behavioral PD, Cox baseline, hazard GBM, competing-risks variant — registered + cards
- [ ] LGD (two-stage) + EAD/CCF models + downturn memo
- [ ] Staging service with provenance logging
- [ ] Macro-conditioning models + scenario configs
- [ ] Flink aggregate jobs; OLAP store; ADR-030
- [ ] Dashboards: portfolio, concentration/weather, model-health, scenario widget
- [ ] Transition-matrix job + CUSUM alarms
- [ ] Backtest report; ECL parallel-run reconciliation memo
- [ ] Independent validation for all P3 models

## 7. Exit criteria (gate review)

Hazard GBM C-index ≥ Cox + 0.02 and ≥ 0.75 absolute · PD calibration by grade within ±15% relative on backtest years · LGD MAE ≤ incumbent · dashboard freshness SLO met over 30 consecutive days · ECL parallel-run memo signed · staging provenance audit clean.

## 8. Do-not-invent list (P3)

SICR thresholds · downturn LGD add-ons · CCF floors · macro scenarios · discount-rate conventions · segment definitions for reporting. All `[POLICY]`.

## 9. References for this phase

- Dirick, Claeskens, Baesens — survival benchmark for credit — [PDF](https://d-nb.info/1122167008/34)
- Katzman et al. — *DeepSurv* (P6 challenger) — [arXiv:1606.00931](https://arxiv.org/abs/1606.00931)
- Fine & Gray — competing risks — [JASA 1999](https://www.tandfonline.com/doi/abs/10.1080/01621459.1999.10474144) · [scikit-survival](https://github.com/sebp/scikit-survival)
- Tutz & Schmid — discrete time-to-event — [Springer](https://link.springer.com/book/10.1007/978-3-319-28158-2)
- Loterman et al. — LGD benchmark — [IJF 2012](https://www.sciencedirect.com/science/article/abs/pii/S0169207011000586); Ferrari & Cribari-Neto — beta regression — [link](https://www.tandfonline.com/doi/abs/10.1081/STA-120037418)
- Wilson — *Portfolio Credit Risk* — [FRBNY 1998](https://www.newyorkfed.org/research/epr/98v04n3/9810wils.html)
- Bifet & Gavaldà — *ADWIN* — [PDF](https://www.cs.upc.edu/~gavalda/papers/adwin06.pdf) · [River](https://github.com/online-ml/river)
- Hochenbaum et al. — S-H-ESD anomaly detection — [arXiv:1704.07706](https://arxiv.org/abs/1704.07706)
- Carbone et al. — *Apache Flink* — [PDF](http://sites.computer.org/debull/A15dec/p28.pdf)

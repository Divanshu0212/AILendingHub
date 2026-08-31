# Phase 6 — Learning Loops & Advanced Challengers (Ongoing)

| Phase card | |
|---|---|
| Duration | Month 13 onward — steady-state operating rhythm, not a fixed project |
| SRS modules | §5 (fraud layer 3–4 full), §6–§7 (challengers), §10 (action uplift), §11 (governance rhythm) |
| Depends on | P1–P5 shipped (each workstream lists its specific feed) |
| Squads | All DS squads; Model Risk (A on every promotion) |
| Governing contract | `00_MASTER_Implementation_Guide.md` §2–§4 — binding. **Standing rule: no promotion without measured out-of-time lift + model card + independent validation + rollback plan; prefer online A/B over offline lift wherever feasible.** |

**Objective.** The compounding phase: activate the feedback loops earlier phases were built to feed (dispositions, propensities, action outcomes), and promote the advanced challengers deliberately deferred until their training data existed. Each workstream below runs the standard shipping ladder independently.

---

## 2. Workstreams

### WS-6.1 Graph fraud — full Layer 3 (feeds: P1 entity graph + ≥ 18 months of fraud-desk dispositions)

1. **Louvain community scoring** ([Blondel et al., arXiv:0803.0476](https://arxiv.org/abs/0803.0476)): dense clusters scored by fraud-label density and shared-attribute entropy; cheap and explainable — deploy first.
2. **GraphSAGE nightly node scores** ([Hamilton et al., arXiv:1706.02216](https://arxiv.org/abs/1706.02216)): inductive aggregation so *new* applications are scorable without retraining; per-node graph-risk score cached in the online feature store, consumed by the P1 real-time fraud GBM as a feature.
3. **CARE-GNN challenger** ([Dou et al., CIKM 2020, arXiv:2008.08692](https://arxiv.org/abs/2008.08692)): reinforcement-learned neighbor filtering against camouflage — fraudsters padding their neighborhoods with legitimate links. Trained on the disposition labels P1 enforced from day one. Context survey: [GNNs for financial fraud, arXiv:2411.05815](https://arxiv.org/abs/2411.05815); public money-flow benchmark: [Elliptic, arXiv:1908.02591](https://arxiv.org/abs/1908.02591).
4. **Operating rule:** every graph alert ships with its subgraph visualization — an unexplained GNN alert will not be actioned by the fraud desk.

**Promotion gate:** +recall at the fixed alert budget vs. the P1 stack, on out-of-time months.

### WS-6.2 Document tamper CNNs (feeds: P1 document store)

**Noiseprint** ([Cozzolino & Verdoliva, arXiv:1808.08396](https://arxiv.org/abs/1808.08396)) camera-fingerprint inconsistency localization + copy-move forgery detection on uploaded documents; template pHash edges added to the entity graph (same forged template reused across applicants = ring evidence). Gate: precision on a labeled forged-document set `[DATA]` ≥ agreed floor `[POLICY: Fraud Head]`.

### WS-6.3 Survival & sequence challengers (feeds: P3 hazard benchmark + transaction streams)

- **DeepSurv** ([Katzman et al., arXiv:1606.00931](https://arxiv.org/abs/1606.00931)): neural Cox partial-likelihood; challenger to the P3 discrete-time GBM.
- **Transaction-sequence models** (E.T.-RNN line, [Babaev et al., KDD 2019, arXiv:1911.02496](https://arxiv.org/abs/1911.02496)): GRU/transformer over time-stamped event embeddings for 60-day delinquency — challenger to P4's ranking model where event data is rich.
- **Promotion gate:** C-index / capture-rate lift on out-of-time data **and** an explainability review; a sequence model never fires an EWS alert without a human-readable co-signal (P4 two-key rule extends to it).

### WS-6.4 Collections & action uplift (feeds: P4 action-outcome logs + randomized holdouts)

Causal effect of each action on cure: `τ(x) = E[cure|action,x] − E[cure|control,x]` via meta-learners ([Künzel et al., arXiv:1706.03461](https://arxiv.org/abs/1706.03461)) or causal forests ([Wager & Athey, arXiv:1510.04342](https://arxiv.org/abs/1510.04342)); libraries: [CausalML](https://github.com/uber/causalml) / [EconML](https://github.com/py-why/EconML). Randomized action holdouts are **standing policy** (without them, uplift is unidentifiable — an AI assistant must never estimate uplift from purely observational action logs and present it as causal). Promotion gate: Qini coefficient + online cure-rate lift.

### WS-6.5 Off-policy improvement of offers (feeds: P4 propensity logs)

Candidate offer policies evaluated with **doubly-robust off-policy estimation** ([Dudík, Langford & Li, arXiv:1103.4601](https://arxiv.org/abs/1103.4601)) on logged propensities before any traffic; only positive-DR-estimate policies proceed to canary. Exploration cell maintained at its `[POLICY]` percentage forever — the learning loop dies without it.

### WS-6.6 Scoring maturation

- **Reject-inference upgrade:** bureau-retro program (how our rejects performed elsewhere) institutionalized at every retrain; parceling as fallback; documented uplift each cycle.
- **Alternative-data expansion** (consent-gated, DPDP-compliant): AA depth, telco/behavioral where cleared `[POLICY: Compliance + DPO]` — evidence base [Björkegren & Grissen, arXiv:1712.05840](https://arxiv.org/abs/1712.05840).
- **Fairness re-audit** with every retrain, not just annually.

### WS-6.7 The steady-state governance rhythm (SRS §11)

| Cadence | Activity |
|---|---|
| Nightly | Graph scores; agri revisit processing; feature freshness checks |
| Weekly | PSI/CSI + calibration monitors; hallucination audit (P5); alert-precision tracking (P4) |
| Monthly | Fraud/EWS retrains as data warrants; suitability audit; fairness dashboards |
| Quarterly | Scoring retrain calendar; golden-set refresh (P5); reject-inference cycle; exploration-cell review |
| Annually | Full model revalidation (SR 11-7 rhythm); definitions-package review; DR test of decisioning fallback |

---

## 3. Deliverables (rolling)

- [ ] Louvain + GraphSAGE in production; CARE-GNN challenger report
- [ ] Noiseprint document-forensics service + graph pHash edges
- [ ] DeepSurv & sequence-model challenger evaluations vs. P3/P4 champions
- [ ] Uplift models with Qini reports; standing holdout policy ratified
- [ ] DR off-policy evaluation harness wired to P4 logs
- [ ] Retrain calendar + annual revalidation schedule adopted by Model Risk

## 4. Standing exit criterion (every promotion, forever)

Measured lift on out-of-time data · model card · independent validation · rollback plan · online A/B where feasible. **Offline lift alone never promotes a model that could have been A/B tested.**

## 5. Do-not-invent list (P6)

Causal claims from observational data (holdouts required) · alert budgets, floors, exploration % (all `[POLICY]`) · any "improvement" not evidenced on out-of-time or online data · training on undispositioned alerts (label discipline holds).

## 6. References for this phase

- Dou et al. — *CARE-GNN* — [arXiv:2008.08692](https://arxiv.org/abs/2008.08692); Hamilton et al. — *GraphSAGE* — [arXiv:1706.02216](https://arxiv.org/abs/1706.02216); Blondel et al. — Louvain — [arXiv:0803.0476](https://arxiv.org/abs/0803.0476); GNN fraud review — [arXiv:2411.05815](https://arxiv.org/abs/2411.05815); Elliptic — [arXiv:1908.02591](https://arxiv.org/abs/1908.02591)
- Cozzolino & Verdoliva — *Noiseprint* — [arXiv:1808.08396](https://arxiv.org/abs/1808.08396)
- Katzman et al. — *DeepSurv* — [arXiv:1606.00931](https://arxiv.org/abs/1606.00931); Babaev et al. — *E.T.-RNN* — [arXiv:1911.02496](https://arxiv.org/abs/1911.02496)
- Künzel et al. — meta-learners — [arXiv:1706.03461](https://arxiv.org/abs/1706.03461); Wager & Athey — causal forests — [arXiv:1510.04342](https://arxiv.org/abs/1510.04342) · [CausalML](https://github.com/uber/causalml) · [EconML](https://github.com/py-why/EconML)
- Dudík et al. — doubly-robust OPE — [arXiv:1103.4601](https://arxiv.org/abs/1103.4601)
- Björkegren & Grissen — [arXiv:1712.05840](https://arxiv.org/abs/1712.05840)
- Fed SR 11-7 — [link](https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm)

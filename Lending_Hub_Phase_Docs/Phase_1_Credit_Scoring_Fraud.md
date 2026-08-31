# Phase 1 — Core Credit Scoring + Fraud Layers 1–2

| Phase card | |
|---|---|
| Duration | Months 4–7 |
| SRS modules | §4 (credit scoring), §5 (fraud — layers 1–2 + doc checks v1) |
| Depends on | Phase 0 gate passed |
| Unblocks | P3 (decision logs, PD), P4 (scores for pricing), P5 (status APIs), P6 (fraud labels, entity graph) |
| Squads | Credit DS (R), Fraud DS (R), Platform (C), Model Risk (A) |
| Governing contract | `00_MASTER_Implementation_Guide.md` §2–§4 — binding |

**Objective.** For **one retail product** (highest-volume unsecured product; decision recorded as **ADR-010**), ship: (a) a calibrated PD model — WOE scorecard champion + monotonic LightGBM challenger — with reason codes; (b) fraud Layers 1–2 (supervised GBM + anomaly detection) with entity resolution and velocity features; both live behind the Decision Orchestrator with human-review bands.

---

## 2. Position in the program

**Inputs from P0:** lakehouse Silver history, Feast, MLflow/CI, identity spine, definitions package v1, serving skeleton, 2 live Kafka streams.

**Outputs to later phases:**

| Output | Consumed by |
|---|---|
| Calibrated application PD + reason codes | P3 (origination PD anchor), P4 (pricing `E[loss]`) |
| Decision logs (complete, reproducible) | P3 dashboards, P6 off-policy learning |
| Entity graph tables (nodes/edges in Gold) | P6 GNN fraud (GraphSAGE / CARE-GNN) |
| Fraud-desk disposition labels (enforced completeness) | P6 supervised graph training |
| Orchestrator with policy-band config | P2 agri scoring, P4 recommendations |

---

## 3. Entry criteria

- P0 gate passed (all four numeric gates).
- `[DATA]` label audit: ≥ 1,500 *bads* for the chosen product per Master Appendix A definition. If fewer → scope reduces to scorecard-only; challenger deferred and the limitation recorded in the gate pack.
- Reason-code dictionary and monotonicity-direction list drafted for `[POLICY]` ratification (see §8).

---

## 4. Workstreams

### WS-1.1 Credit scoring (SRS §4)

**Step 1 — Target engineering.**
Versioned SQL script builds the target table: unit = application; *bad* = max(DPD) ≥ 90 within 12 months of disbursal (import from definitions package — never re-type). Exclusions (fraud-tagged, staff loans, restructures) listed explicitly in the script; no undocumented filters. Split by vintage: train = oldest 70%, validation = next 15%, test (out-of-time) = newest 15%. **Random splits are forbidden** — macro leakage.

**Step 2 — Feature engineering.**
Features exist only as Feast definitions. Groups: bureau (enquiries, utilization, DPD history, file age), application (income, obligations, tenure, LTV), AA bank-statement aggregates where consented (income regularity, balance volatility, bounce counts). Each feature carries metadata: source, point-in-time rule, null policy, IV screen, PSI screen.

**Step 3 — Champion: WOE scorecard.**
Library: [OptBinning](https://github.com/guillermo-navas-palencia/optbinning) (monotonic optimal binning) → WOE transform → scikit-learn logistic regression → PDO-20 score scaling (SRS §4.3.1). IV window [0.02, 0.5]; IV > 0.5 → leakage-investigation ticket before use. Reason codes = largest negative point contributions.

**Step 4 — Challenger: LightGBM.**
Library: LightGBM ([Ke et al., NeurIPS 2017](https://papers.nips.cc/paper/2017/hash/6449f44a102fde848669bdd9eb6b76fa-Abstract.html)). `monotone_constraints` applied to every feature on the ratified direction list `[POLICY: Credit Risk Head]`. Hyperparameter search on validation vintages only; early stopping; seeds fixed.

**Step 5 — Calibration.**
Isotonic regression on the validation set ([Niculescu-Mizil & Caruana, ICML 2005](https://www.cs.cornell.edu/~alexn/papers/calibration.icml05.crc.rev3.pdf)). Both models output calibrated PD; reliability diagram + Brier score go in the validation report.

**Step 6 — Explainability.**
TreeSHAP ([Lundberg et al., arXiv:1905.04610](https://arxiv.org/abs/1905.04610); original SHAP [arXiv:1705.07874](https://arxiv.org/abs/1705.07874)) at score time; top-5 negative SHAP features → approved reason-code dictionary `[POLICY: Compliance]`. The mapping table is *data* (editable by legal), not code.

**Step 7 — Fairness testing.**
[Fairlearn](https://fairlearn.org) metrics — demographic parity difference, equalized-odds difference ([Hardt et al., arXiv:1610.02413](https://arxiv.org/abs/1610.02413)) — on gender, age band, geography (pincode as proxy probe). Results in the model card; mitigation only via the SRS §4.3.3 ladder; action threshold `[POLICY: Fair-Lending Committee]`.

**Step 8 — Reject inference.**
First release: bureau-retro based (how our rejects performed on loans elsewhere) if retro data is purchasable `[DATA]`; otherwise document the selection-bias limitation in the model card and schedule parceling/fuzzy augmentation for the first retrain. **Never fabricate outcomes for rejects.**

**Step 9 — Independent validation.**
Validator reproduces: AUC/Gini/KS on test vintages; calibration by decile; train↔test PSI; monotonicity spot-checks; ±10% sensitivity perturbations; swap-set analysis vs. the rebuilt legacy scorecard.

### WS-1.2 Fraud layers 1–2 (SRS §5.3.1–5.3.2, §5.3.4 v1)

**Step 1 — Entity resolution v1.**
Blocking + fuzzy matching: name Jaro–Winkler with threshold tuned on labeled duplicate pairs `[DATA]`; phone/account exact; address normalized + geohash. Library: `splink` or `recordlinkage` (**ADR-011**). Output: entity nodes/edges tables in Gold — schema designed jointly with P6 (GNN reuse).

**Step 2 — Velocity counters (Flink).**
Applications per device / phone / address over 1h / 24h / 7d windows; event-time watermarks for late events; counters written to the online feature store.

**Step 3 — Supervised fraud GBM.**
LightGBM on confirmed-fraud labels (historical fraud-desk dispositions). If `[DATA]` confirmed frauds < 200 → ship rules + anomaly layer only; log limitation. Imbalance: `scale_pos_weight`. Evaluation: AUC-PR and **recall @ 0.5% alert rate** on out-of-time months — never accuracy.

**Step 4 — Anomaly layer.**
scikit-learn **IsolationForest** ([Liu, Ting & Zhou, ICDM 2008](https://cs.nju.edu.cn/zhouzh/zhouzh.files/publication/icdm08b.pdf)), default hyperparameters, trained on 12 months of applications. Its score is a **feature into the GBM** (semi-supervised stacking) — it does not raise alerts on its own (single tunable alert queue).

**Step 5 — Document checks v1.**
OCR (docTR/Tesseract) + deterministic cross-field arithmetic: salary-slip totals, bank-statement balance continuity across months, IFSC validity. **AA-first rule:** where Account-Aggregator consent exists, AA data overrides uploaded PDFs; "AA refused + PDF uploaded" becomes a model feature. (Tamper-detection CNNs are Phase 6.)

**Step 6 — Alert routing.**
Orchestrator outcomes: pass / step-up verification / refer-to-fraud-desk. Case-management queue with **mandatory disposition codes** — these labels are P6's training set; completeness is enforced from day one (no case closes without a code).

---

## 5. Shipping ladder

1. **Shadow (≥ 4 weeks).** Both scoring models + fraud stack score 100% of live applications; legacy policy still decides. Daily automated comparison: score PSI vs. training, champion-vs-challenger swap sets, fraud alert volumes.
2. **Canary.** Challenger decisions applied to `[POLICY: Credit Risk Committee]`% of traffic, mid-score bands only. Cutoffs and review-band edges are orchestrator *config* with dual-control change approval — never code constants.
3. **Champion.** Full traffic after ≥ 4 clean canary weeks. Legacy path stays warm as automatic fallback.

## 6. Deliverables checklist

- [ ] ADR-010 (product), ADR-011 (ER library)
- [ ] Target script + split manifest (versioned)
- [ ] Feast feature definitions + metadata screens
- [ ] Champion scorecard + challenger LightGBM in MLflow (calibrated)
- [ ] SHAP reason-code service + editable mapping table
- [ ] Fairness report; reject-inference memo
- [ ] Independent validation report (both models)
- [ ] Entity graph tables + ER tuning report
- [ ] Flink velocity jobs live; fraud GBM + IsolationForest registered
- [ ] Document-check service v1; AA-first rule wired
- [ ] Case-management routing with mandatory dispositions
- [ ] Shadow/canary comparison dashboards

## 7. Exit criteria (gate review)

- Challenger ≥ **+3 Gini** over rebuilt legacy scorecard on out-of-time test; Brier ≤ legacy; swap-set shows no adverse-segment concentration.
- Fraud precision at operating alert budget ≥ incumbent rules; step-up friction on eventual-good customers < 3%.
- Decision-log spot audit: 100 random logged decisions re-scored → identical outputs.
- Model cards + independent validation signed for every shipped model.

## 8. Do-not-invent list (P1)

Approve/decline cutoffs · review-band edges · canary % · monotonicity direction list · reason-code wording · fairness action thresholds · fraud alert budget · step-up friction tolerance. All `[POLICY]`.

## 9. References for this phase

- Ke et al. — *LightGBM*, NeurIPS 2017 — [paper](https://papers.nips.cc/paper/2017/hash/6449f44a102fde848669bdd9eb6b76fa-Abstract.html); Chen & Guestrin — *XGBoost* — [arXiv:1603.02754](https://arxiv.org/abs/1603.02754)
- Lessmann et al. — credit-scoring benchmark, EJOR 2015 — [link](https://www.sciencedirect.com/science/article/abs/pii/S0377221715004208)
- Lundberg & Lee — *SHAP* — [arXiv:1705.07874](https://arxiv.org/abs/1705.07874); TreeSHAP — [arXiv:1905.04610](https://arxiv.org/abs/1905.04610)
- Niculescu-Mizil & Caruana — calibration, ICML 2005 — [PDF](https://www.cs.cornell.edu/~alexn/papers/calibration.icml05.crc.rev3.pdf)
- Hardt et al. — equalized odds — [arXiv:1610.02413](https://arxiv.org/abs/1610.02413) · [Fairlearn](https://fairlearn.org)
- Liu, Ting, Zhou — *Isolation Forest*, ICDM 2008 — [PDF](https://cs.nju.edu.cn/zhouzh/zhouzh.files/publication/icdm08b.pdf)
- Björkegren & Grissen — phone-behavior credit signal — [arXiv:1712.05840](https://arxiv.org/abs/1712.05840)
- [OptBinning](https://github.com/guillermo-navas-palencia/optbinning) · [splink](https://github.com/moj-analytical-services/splink)

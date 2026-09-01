# Phase 1 — Core Credit Scoring + Fraud Layers 1–2

| Phase card | |
|---|---|
| Duration | Months 4–7 |
| SRS modules | §4 (credit scoring), §5 (fraud — layers 1–2 + doc checks v1) |
| Depends on | Phase 0 gate passed |
| Unblocks | P3 (decision logs, PD), P4 (scores for pricing), P5 (status APIs), P6 (fraud labels, entity graph) |
| Squads | Credit DS (R), Fraud DS (R), Platform (C), Model Risk (A) |
| Governing contract | `00_MASTER_Implementation_Guide.md` §2–§4 (v1.2) — binding |
| Revision | v1.1 · 1 September 2026 — Phase 1 implementation findings applied |

> **Implementation addendum (2026-09-01, revised).** Phase 1 is being built in
> this repository. Twelve findings were raised against this document per Master §1;
> **the document owner has accepted them and they are now applied** — to §3, §4
> Steps 3, 5, 7 and 8, §4 WS-1.2 Steps 1, 3 and 5, §7 and §8 here, and to SRS
> **v1.2** and Master **v1.2**. This file is the corrected version; the findings
> file records why each change exists, which outlives the edit.
>
> - [Phase_1_FINDINGS.md](Phase_1_FINDINGS.md) — the twelve findings and their
>   reasoning. The four that changed the most: the score scale was not computable
>   (§4 Step 3 fixed PDO and nothing fixed the anchor), calibration was fitted on
>   the set the model was selected on (§4 Steps 4 and 5 shared the validation
>   split), "largest negative point contribution" was the wrong reason-code rule,
>   and §4 Step 8 scheduled parcelling in the paragraph that forbids it.
> - [docs/phase1/STATUS.md](../docs/phase1/STATUS.md) — §6 checklist traceability:
>   which artifact satisfies each item, on which track, and its honest state.
> - [docs/phase1/blocking_tickets.md](../docs/phase1/blocking_tickets.md) — ten
>   `[POLICY]` values this phase is waiting on, four of them not on the §8 list.
> - [docs/phase1/model_cards/](../docs/phase1/model_cards/) — both models, with
>   what they may and may not be used for (Master §2 rule 5).
> - [docs/adr/0010-scored-product-and-track-p-standin.md](../docs/adr/0010-scored-product-and-track-p-standin.md)
>   — why §1's "one retail product" is a registered placeholder, and what the phase
>   is built against meanwhile.
> - [docs/adr/0011-entity-resolution-library.md](../docs/adr/0011-entity-resolution-library.md)
>   — ADR-011 as §4 WS-1.2 Step 1 requires.
>
> `make trackp-p1` runs all of WS-1.1 against 60,000 real applications;
> `make gate1` assembles the §7 evidence pack. Neither produces gate evidence —
> see [ADR-0004](../docs/adr/0004-public-reference-data-track.md).

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
- `[DATA]` label audit: ≥ 1,500 *bads* for the chosen product per Master Appendix A definition, counted on the **training split** — counting the whole table passes the test on bads the challenger never sees. If fewer → scope reduces to scorecard-only; challenger deferred and the limitation recorded in the gate pack. Note that Appendix A's *Default / Bad* has three arms that are not yet computable (write-off, fraud-confirmed, distress-restructure code sets), so this count is a lower bound until those land.
- Reason-code dictionary and monotonicity-direction list drafted for `[POLICY]` ratification (see §8).

---

## 4. Workstreams

### WS-1.1 Credit scoring (SRS §4)

**Step 1 — Target engineering.**
Versioned SQL script builds the target table: unit = application; *bad* = max(DPD) ≥ 90 within 12 months of disbursal (import from definitions package — never re-type). Exclusions (fraud-tagged, staff loans, restructures) listed explicitly in the script; no undocumented filters. Split by vintage: train = oldest 70%, validation = next 15%, test (out-of-time) = newest 15%. **Random splits are forbidden** — macro leakage.

**Step 2 — Feature engineering.**
Features exist only as Feast definitions. Groups: bureau (enquiries, utilization, DPD history, file age), application (income, obligations, tenure, LTV), AA bank-statement aggregates where consented (income regularity, balance volatility, bounce counts). Each feature carries metadata: source, point-in-time rule, null policy, IV screen, PSI screen.

**Step 3 — Champion: WOE scorecard.**
Library: [OptBinning](https://github.com/guillermo-navas-palencia/optbinning) (monotonic optimal binning) → WOE transform → scikit-learn logistic regression → PDO-20 score scaling (SRS §4.3.1). IV window [0.02, 0.5]; IV > 0.5 → leakage-investigation ticket before use.

*Binning direction* comes from the **same ratified monotonicity list as the challenger** (Step 4), not from OptBinning's data-driven default. Otherwise the champion may encode a direction read off the training sample while the challenger encodes the committee's, and where they disagree the two models represent opposite risk relationships for the same characteristic — which makes the Step 9 swap-set analysis a comparison between models that disagree about the direction of risk, with nothing in the process surfacing it. Until the list is ratified, a binning fitted on an inferred direction must record that it was inferred; an inferred direction is a restatement of the fit, not a constraint.

*Score scaling* has three constants and PDO fixes one of them. `factor = PDO / ln 2` is the slope; the **anchor** — a reference score and the good:bad odds at it — is the intercept, and it is `[POLICY: Credit Risk Head]` (see §8). Until it is supplied the scorecard **must refuse to emit a score** rather than choose a plausible anchor. The calibrated PD is unaffected and is what pricing and IFRS-9 consume.

*Reason codes* rank by **points below max** — the distance from the applicant's bin points to the best points attainable on that characteristic — not by the largest raw negative contribution. The latter ranks characteristics by the width of their weight range, so a heavily-weighted characteristic on which the applicant is merely average outranks a lightly-weighted one on which they are in the worst bin (SRS §4.3.1).

**Step 4 — Challenger: LightGBM.**
Library: LightGBM ([Ke et al., NeurIPS 2017](https://papers.nips.cc/paper/2017/hash/6449f44a102fde848669bdd9eb6b76fa-Abstract.html)). `monotone_constraints` applied to every feature on the ratified direction list `[POLICY: Credit Risk Head]`. Hyperparameter search on validation vintages only; early stopping; seeds fixed.

**Step 5 — Calibration.**
Both models output calibrated PD; reliability diagram + Brier score go in the validation report ([Niculescu-Mizil & Caruana, ICML 2005](https://www.cs.cornell.edu/~alexn/papers/calibration.icml05.crc.rev3.pdf)). Two constraints on *how*, because PDs feed pricing and IFRS-9 and an optimistic calibration is a systematic mispricing:

- **Not the validation set.** Step 4 selects the challenger on the validation vintages, so a calibrator fitted there is fitted where the model was chosen to look good. Use **out-of-fold predictions cross-fitted over the training vintages** — preferred on a thin-bad portfolio, because it uses the largest sample available — or a dedicated fourth split carved from the train block. A calibration fitted on the selection set must be reported with that fact attached.
- **Isotonic is not automatic.** The paper above is also the source of the caveat: isotonic needs more data than Platt and overfits small samples. On a rare default the binding constraint is the **event count**, not the row count. Choose isotonic where the calibration sample supports it and Platt otherwise, and record which was used and why.

**Step 6 — Explainability.**
TreeSHAP ([Lundberg et al., arXiv:1905.04610](https://arxiv.org/abs/1905.04610); original SHAP [arXiv:1705.07874](https://arxiv.org/abs/1705.07874)) at score time; top-5 negative SHAP features → approved reason-code dictionary `[POLICY: Compliance]`. The mapping table is *data* (editable by legal), not code.

**Step 7 — Fairness testing.**
[Fairlearn](https://fairlearn.org) metrics — demographic parity difference, equalized-odds difference ([Hardt et al., arXiv:1610.02413](https://arxiv.org/abs/1610.02413)) — on gender, age band, geography (pincode as proxy probe). Results in the model card; mitigation only via the SRS §4.3.3 ladder; action threshold `[POLICY: Fair-Lending Committee]`.

Protected attributes are held in a **separate store with its own access path** (SRS §4.3.3). The feature catalogue refuses to register one; fairness code receives an accessor that no training or serving path is handed. This is architectural rather than procedural because "gender is not a feature" enforced by a review checklist survives exactly as long as the reviewer who remembers it — and under DPDP purpose limitation, an attribute collected for fairness monitoring is not thereby available for scoring.

Run the proxy probe on **every** feature group, not only geography. Elapsed-time features — months employed, months since registration, age of the credit file — are age proxies, and excluding age as a feature does not remove it.

Report a disparity alongside its **sampling uncertainty**. The smallest groups are usually the ones fairness testing exists to protect, and a point estimate on a small group invites action on noise in one direction and false reassurance in the other.

**Step 8 — Reject inference.**
First release: bureau-retro based (how our rejects performed on loans elsewhere) if retro data is purchasable `[DATA: LH-207]`; otherwise document the selection-bias limitation in the model card. **Never fabricate outcomes for rejects.**

The two methods are not a preference ordering (SRS §4.3.2.4). **Bureau retro is inference from evidence** — someone else lent and observed the outcome — and belongs in the training target, flagged as externally observed. **Parceling is inference from belief**: it assigns each reject an outcome from the current model's own prediction, so presented as a correction it is circular. It is scheduled as a **sensitivity analysis** at the first retrain, never as a label, and the two must not be reported under one heading.

Where neither is available, the honest deliverable is a measurement of the *size* of the bias — the distributional distance between the booked and declined populations, which needs no reject outcomes — plus the model-card limitation.

**Step 9 — Independent validation.**
Validator reproduces: AUC/Gini/KS on test vintages; calibration by decile; train↔test PSI; monotonicity spot-checks; ±10% sensitivity perturbations; swap-set analysis vs. the rebuilt legacy scorecard.

### WS-1.2 Fraud layers 1–2 (SRS §5.3.1–5.3.2, §5.3.4 v1)

**Step 1 — Entity resolution v1.**
Blocking + fuzzy matching: name Jaro–Winkler with threshold tuned on labeled duplicate pairs `[DATA: LH-209]`; phone/account exact; address normalized + geohash. Library: `splink` or `recordlinkage` (**ADR-011**). Output: entity nodes/edges tables in Gold — schema designed jointly with P6 (GNN reuse).

**The labelled pair set is a scheduled task with an owner, not an assumption.** No other workstream produces it. It is clerical work — a stratified sample of candidate pairs, adjudicated by fraud operations — and until it exists the fuzzy threshold is a preference and every ER precision claim rests on it. Ship v1 with the **deterministic rules only** (exact phone / account / device) if the labelling has not completed; those need no threshold at all. A fuzzy match threshold must never carry a default value in code.

Every edge records **the attribute and the score that created it**. The output is the graph P6 trains on: a wrong merge is an edge that does not exist, and a GNN trained on it learns a ring that is a data-quality artifact — which will be investigated before anyone doubts the graph.

**Step 2 — Velocity counters (Flink).**
Applications per device / phone / address over 1h / 24h / 7d windows; event-time watermarks for late events; counters written to the online feature store.

**Step 3 — Supervised fraud GBM.**
LightGBM on confirmed-fraud labels (historical fraud-desk dispositions). Imbalance: `scale_pos_weight`. Evaluation: AUC-PR and **recall @ 0.5% alert rate** on out-of-time months — never accuracy.

The scope test is **two-part and three-valued**, because "how many confirmed frauds do we have" is not a countable question until someone has said what a fraud is. Master Appendix A defines confirmed fraud as a disposition code in the approved taxonomy, and that taxonomy is `[POLICY: Fraud Head]`:

| State | Condition | Action |
|---|---|---|
| **Taxonomy blocked** | No ratified disposition taxonomy | The count cannot be produced at all. Escalate the taxonomy; do **not** report this as a data limitation |
| **Below minimum** | Taxonomy ratified, confirmed frauds < 200 | Ship rules + anomaly layer only; log the limitation |
| **In scope** | Taxonomy ratified, confirmed frauds ≥ 200 | Supervised layer proceeds |

Collapsing the first two states lets "we have 150 frauds, so anomaly-only" be reported when the truth is that nobody has said what counts as fraud. Those need different escalations, to different people.

The **0.5% rate is for evaluating recall** and is `[SPEC]`. The alert rate the desk actually operates at is a capacity and risk-appetite decision, `[POLICY: Fraud Head]` (§8). Same units, different number; using the evaluation rate as an operating budget because it is the one written down is an easy and expensive mistake.

**Step 4 — Anomaly layer.**
scikit-learn **IsolationForest** ([Liu, Ting & Zhou, ICDM 2008](https://cs.nju.edu.cn/zhouzh/zhouzh.files/publication/icdm08b.pdf)), default hyperparameters, trained on 12 months of applications. Its score is a **feature into the GBM** (semi-supervised stacking) — it does not raise alerts on its own (single tunable alert queue).

**Step 5 — Document checks v1.**
OCR (docTR/Tesseract) + deterministic cross-field arithmetic: salary-slip totals, bank-statement balance continuity across months, IFSC validity. Money in **integer minor units** — a tolerance on a continuity check is a place for a small forgery to live. A field that could not be extracted is reported as *not checkable*, never as *failed*: a bad scan and a forgery must not arrive at the fraud desk as the same finding.

**IFSC validity is two checks, and only one of them is a control.** Format validity is a regex against the public RBI format. Branch *existence* is a lookup against a bank-branch directory `[POLICY: Payments Operations]` (§8). A forger who knows the format passes the regex every time, so a green "IFSC valid" from the format check alone is close to worthless while reading exactly like a meaningful control on a checklist. Report which of the two was performed.

**AA-first rule:** where Account-Aggregator consent exists, AA data **overrides** uploaded PDFs — no averaging, no tolerance, no preference weighting. AA is fetched from the source bank under consent and never passes through the applicant's hands; when the two disagree, only one of them is evidence. The disagreement is retained as a signal: a *contradicted* document is far stronger evidence than a merely absent one.

"AA refused + PDF uploaded" becomes a model feature — but only where the platform can distinguish **"offered and refused"** from **"never offered"**. That is a product-flow fact, not a document fact, and where the posture was not recorded the feature must be **absent** rather than defaulted; defaulting it makes every application from a flow that forgot to log consent read as the innocent case. (Tamper-detection CNNs are Phase 6.)

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

- **Champion** ≥ rebuilt legacy scorecard on out-of-time Gini, and Brier ≤ legacy. The champion decides all traffic the challenger is not canarying, so it needs a bar of its own; without one, the model deciding most applications passes the gate on a different model's numbers.
- **Challenger** ≥ **+3 Gini** over rebuilt legacy scorecard on out-of-time test; Brier ≤ legacy. Both figures are **only** admissible from a genuinely out-of-time test — an in-time uplift can be large and still say nothing about how the model travels across a regime, which is the whole question. Record what the challenger actually bought, not only whether it cleared the bar: on a feature set dominated by externally-supplied bureau scores the honest answer may be "very little, at the cost of monotonicity and explainability".
- **Swap set** shows no adverse-segment concentration, measured as each segment's share of the swap-out set divided by its share of the population. The level that fails is `[POLICY: Fair-Lending Committee]` — this criterion cannot be evaluated until that number exists, and a gate pack must report it as *unevaluated* rather than as passed.
- **Monotonicity holds** on the ratified directions, checked on the out-of-time test rather than on the training sample, and re-checked at every retrain: violations are a property of a fit, so a refit has different ones.
- Fraud precision at operating alert budget ≥ incumbent rules; step-up friction on eventual-good customers < 3%. Both depend on the ratified disposition taxonomy (Step 3) and are **not evaluable** without it.
- Decision-log spot audit: 100 random logged decisions re-scored → identical outputs, at **zero tolerance**. A replay is a re-execution of the same model on the same stored inputs, so anything but an exact match means the artifact, the features or the log has changed — which is what the audit exists to find.
- Model cards + independent validation **signed** for every shipped model. A card that exists is not a card that is complete: Master §3.1 requires a validator who is not the developer.

## 8. Do-not-invent list (P1)

Approve/decline cutoffs · review-band edges · canary % · monotonicity direction list ·
reason-code wording · fairness action thresholds · fraud alert budget · step-up friction
tolerance.

Added after implementation — each was found by a step that read as fully specified until
code had to produce a value:

| Value | Owner | Why it is not derivable |
|---|---|---|
| **Score-scale anchor** — reference score and the good:bad odds at it | Credit Risk Head | PDO fixes the slope of `points = offset − factor·ln(odds)`; nothing fixes the intercept, and the SRS's "e.g. 300–900" is an illustration. Two of the three scaling constants are ungrounded, so no points value is computable (§4 Step 3) |
| **Fraud-desk disposition taxonomy** | Fraud Head | Master Appendix A defines confirmed fraud by it. Without it, no count of confirmed frauds means anything, so the §4 WS-1.2 Step 3 scope test cannot be evaluated at all |
| **Bureau-retro availability** | Credit Risk Head + Procurement | Whether retro data on this bank's declines is purchasable, at what match rate, under what consent basis. It decides whether the first release corrects selection bias or only documents it (§4 Step 8) |
| **Labelled duplicate-pair set** | Fraud Head + Fraud Operations | The ER threshold is tuned on it and no workstream produces it. A scheduling gap, not a committee decision (§4 WS-1.2 Step 1) |
| **Bank-branch directory** | Payments Operations | Format-valid ≠ real branch. Without it the IFSC check is a regex a forger passes every time (§4 WS-1.2 Step 5) |

All `[POLICY]` except the labelled pair set, which is `[DATA]` and needs scheduling
rather than ratifying. A missing value on this list makes the code **raise** at the point
of use; it never takes a default. A default in a signature is how an ungrounded number
becomes the production one — nobody passes the argument, and by the time anyone asks it
has been in a report for a year.

## 9. References for this phase

- Ke et al. — *LightGBM*, NeurIPS 2017 — [paper](https://papers.nips.cc/paper/2017/hash/6449f44a102fde848669bdd9eb6b76fa-Abstract.html); Chen & Guestrin — *XGBoost* — [arXiv:1603.02754](https://arxiv.org/abs/1603.02754)
- Lessmann et al. — credit-scoring benchmark, EJOR 2015 — [link](https://www.sciencedirect.com/science/article/abs/pii/S0377221715004208)
- Lundberg & Lee — *SHAP* — [arXiv:1705.07874](https://arxiv.org/abs/1705.07874); TreeSHAP — [arXiv:1905.04610](https://arxiv.org/abs/1905.04610)
- Niculescu-Mizil & Caruana — calibration, ICML 2005 — [PDF](https://www.cs.cornell.edu/~alexn/papers/calibration.icml05.crc.rev3.pdf)
- Hardt et al. — equalized odds — [arXiv:1610.02413](https://arxiv.org/abs/1610.02413) · [Fairlearn](https://fairlearn.org)
- Liu, Ting, Zhou — *Isolation Forest*, ICDM 2008 — [PDF](https://cs.nju.edu.cn/zhouzh/zhouzh.files/publication/icdm08b.pdf)
- Björkegren & Grissen — phone-behavior credit signal — [arXiv:1712.05840](https://arxiv.org/abs/1712.05840)
- [OptBinning](https://github.com/guillermo-navas-palencia/optbinning) · [splink](https://github.com/moj-analytical-services/splink)

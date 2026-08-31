# Phase 4 — Early-Warning System + Loan Recommendation Engine

| Phase card | |
|---|---|
| Duration | Months 10–13 |
| SRS modules | §10 (early warning), §6 (recommendation engine) |
| Depends on | Phase 1 (scores, pricing inputs), Phase 3 (hazard model, LGD/EAD) |
| Unblocks | P6 (action-outcome logs for uplift; propensity logs for off-policy learning) |
| Squads | Credit DS (R), Collections (owner of actions), Product/pricing (C), Model Risk (A) |
| Governing contract | `00_MASTER_Implementation_Guide.md` §2–§4 — binding |

**Objective.** Turn the P3 read-side into actions: (a) an account-level early-warning system that flags likely defaulters 30–120 days ahead with a recommended intervention; (b) a recommendation engine that selects product/amount/tenor/price inside hard policy constraints, with a learning (bandit) layer. Both are action systems — every automated action has an owner, an SLA, and a captured outcome.

---

## 2. Position in the program

**Inputs:** P3 hazard model + behavioral PD; P1 PDs + fraud flags; P2 plot monitoring stream (agri); AA/CASA cash-flow features (P0/P1); case-management API; historical offer/campaign logs `[DATA]`.

**Outputs to later phases:**

| Output | Consumed by |
|---|---|
| Alert + disposition + outcome logs | P6 collections-uplift learning |
| Offer decisions with logged propensities | P6 off-policy evaluation |
| Red-flag stream | P3 staging engine (SICR input), dashboards |

---

## 3. Entry criteria

- P3 gate passed; hazard model in production.
- Case-management integration API available and tested.
- `[POLICY: Collections Head]` drafts ready for ratification: action library, alert SLAs, alert budget, signal precision floors.
- `[DATA]` extraction of ≥ 24 months of offer/campaign logs completed (for the take-up model).

---

## 4. Workstream A — Early-Warning System (SRS §10)

**Step 1 — Signal catalog v1.**
Implement the SRS §10.3 signal families (repayment, cash-flow, bureau, agri, behavioral, macro/local) as versioned, individually-toggleable definitions (YAML + SQL/Flink). **Rule: a signal ships only with a backtested precision estimate attached.** Signals without measurable precision do not ship — this is the anti-alert-fatigue contract.

**Step 2 — PD-velocity trigger.**
From the P3 hazard model: Δ(30-day) hazard, expressed as a percentile of the portfolio distribution. Alert when Δ crosses the budget-derived percentile `[POLICY: Collections Head]`. Velocity, not level, is the trigger — a thin-file borrower can be permanently "medium risk"; deterioration is the signal.

**Step 3 — Change-point detection on cash-flow series.**
**BOCPD** — [Adams & MacKay, 2007, arXiv:0710.3742](https://arxiv.org/abs/0710.3742) — run on three canonical weekly series per account with AA/CASA visibility: net inflows, closing-balance trend, discretionary-spend share. Implementation: reference BOCPD code or `bayesian_changepoint_detection`; **unit-test against the paper's well-log example** (reference-implementation rule). Mechanics: posterior over run length r_t; spike in P(r_t = 0) = regime change (salary loss, business interruption) — visible months before a missed EMI.
**Two-key rule:** change-point alone → Amber; change-point + negative direction + PD-velocity confirmation → Red. This keeps Red precision high.

**Step 4 — Agri triggers (deterministic, from P2).**
Non-sowing by policy cutoff date; NDVI z-score < −1.5 at crop-critical stage on ≥ 2 consecutive revisits; district SPEI-3 ≤ −1.5. District-wide events route to **portfolio actions** (restructuring campaigns per RBI natural-calamity norms), not individual collection pressure.

**Step 5 — Tiering, routing, capture.**
Amber (watch) / Red (act) → case management with: trigger reasons, PD delta, recommended action from the action library `[POLICY]`, SLA, owner. Disposition + outcome codes mandatory (P6 training data). Fatigue guardrails: per-officer daily alert cap; auto-retirement of any signal whose rolling 90-day precision < floor `[POLICY]`.

**Step 6 — Backtest.**
Replay 24 months of history: capture rate of eventual 90+ defaulters at ≥ 60-day lead; precision per tier; lead-time distribution. Targets `[SPEC — revisit at gate with measured numbers]`: capture ≥ 55% at ≥ 60-day lead; tier-Red precision ≥ 25%.

---

## 5. Workstream B — Recommendation Engine (SRS §6)

**Step 1 — Feasible-set service (ship first; rules only, immediate value).**
Pure, exhaustively unit-tested library (golden-file tests vs. hand-computed examples):

```
EMI(a, r, n) = a·r(1+r)^n / ((1+r)^n − 1)
Retail:   EMI + existing obligations ≤ FOIR_cap × VerifiedIncome
MSME/agri: DSCR = CashFlow/DebtService ≥ 1.25 on StressedIncome (P2)
Plus: LTV caps, tenor limits, product policy, concentration caps
```

All caps from config `[POLICY: Credit Policy]`.

**Step 2 — Risk-based pricing.**
`rate = cost_of_funds + opex + E[loss] + capital_charge + margin`, with `E[loss] = PD·LGD·EAD` from P1/P3 models. Funds cost, opex, hurdle from ALM tables `[POLICY: ALCO]` — **never hard-coded**. Floors/ceilings per policy and RBI fair-practice norms.

**Step 3 — Take-up propensity model.**
LightGBM `P(accept | customer, offer)` on the extracted offer logs; selection bias (model only sees offers previously made) documented in the card; mitigated by the exploration cell below.

**Step 4 — Contextual bandit.**
**LinUCB** — [Li, Chu, Langford & Schapire, WWW 2010, arXiv:1003.0146](https://arxiv.org/abs/1003.0146) (alternative: Thompson Sampling, [Chapelle & Li, NeurIPS 2011](https://papers.nips.cc/paper/2011/hash/e53a0a2978c28872a4505bdb51db06dc-Abstract.html)). Arms = offer *templates* (auditable, small arm space), chosen **only within the feasible set** — exploration can never breach affordability or policy. Choose arm maximizing `x^T θ̂_a + α √(x^T A_a^{-1} x)`. Reward = take-up blended with a seasoning risk-adjusted value proxy (delayed-reward correction). Exploration cell 1–2% of eligible traffic `[POLICY: Credit Risk Committee]`. **Log propensities for every decision** — this enables P6 off-policy evaluation ([Dudík et al., arXiv:1103.4601](https://arxiv.org/abs/1103.4601)).

**Step 5 — Lifecycle & suitability rules (agri).**
Calendar-driven from P2: sowing confirmed → input top-up eligibility; good harvest → equipment-loan campaign; drought flag → **suppress marketing, offer restructuring** (suitability duty). Monthly human suitability audit: recommended EMIs vs. stressed affordability; drought-flagged customers received support, not sales.

---

## 6. Shipping ladder

**EWS:** backtest → **silent run 6 weeks** (alerts generated, not routed; risk reviews samples) → tier-Amber live → tier-Red live with SLAs.
**Recommendations:** feasible-set + pricing live first (rules only) → take-up ranking in shadow → bandit on canary segment → full traffic.

## 7. Deliverables checklist

- [ ] Signal catalog v1 with per-signal backtested precision
- [ ] PD-velocity trigger; BOCPD service with well-log unit test green
- [ ] Agri trigger rules wired from P2 monitoring
- [ ] Case-management routing; disposition/outcome capture enforced
- [ ] Fatigue guardrails (caps, auto-retirement) configured
- [ ] EWS backtest report + silent-run review memo
- [ ] Feasible-set library + golden-file tests; pricing service on ALM config
- [ ] Take-up model + card; LinUCB layer with propensity logging verified
- [ ] Exploration-cell approval record; suitability audit process live
- [ ] Independent validation for EWS ranking model and bandit design

## 8. Exit criteria (gate review)

EWS backtest + silent-run meet targets · alert SLA compliance ≥ 90% in first live month · recommendation A/B (bandit vs. static policy) shows take-up lift with **no** vintage-risk deterioration at the 3-month checkpoint · suitability audit clean · propensity logging completeness = 100%.

## 9. Do-not-invent list (P4)

Alert budgets & precision floors · action library & SLAs · exploration percentage · FOIR/DSCR/LTV caps · pricing components (funds cost, opex, hurdle, floors/ceilings) · natural-calamity relief treatment. All `[POLICY]`.

## 10. References for this phase

- Adams & MacKay — *Bayesian Online Changepoint Detection* — [arXiv:0710.3742](https://arxiv.org/abs/0710.3742)
- Li et al. — *LinUCB* — [arXiv:1003.0146](https://arxiv.org/abs/1003.0146); Chapelle & Li — Thompson Sampling — [paper](https://papers.nips.cc/paper/2011/hash/e53a0a2978c28872a4505bdb51db06dc-Abstract.html); Russo et al. — tutorial — [arXiv:1707.02038](https://arxiv.org/abs/1707.02038)
- Dudík, Langford, Li — doubly-robust off-policy evaluation — [arXiv:1103.4601](https://arxiv.org/abs/1103.4601)
- EWS literature — systematic review [arXiv:2310.00490](https://arxiv.org/abs/2310.00490); real-time digital-signal EWS [arXiv:2510.22287](https://arxiv.org/abs/2510.22287)
- Phillips — *Pricing Credit Products* — [Stanford Univ. Press](https://www.sup.org/books/business/pricing-credit-products)
- Künzel et al. — uplift meta-learners (used in P6 on this phase's logs) — [arXiv:1706.03461](https://arxiv.org/abs/1706.03461)

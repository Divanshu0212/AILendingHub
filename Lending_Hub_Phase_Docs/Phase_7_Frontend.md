# Phase 7 — Frontend Applications: Customer App, Officer Workbench, Dashboard & Collections UI

| Phase card | |
|---|---|
| Duration | Months 7–11 for the foundation (starts once P1 APIs exist, parallel with P3), then incremental integration through P6 as each backend phase ships |
| SRS modules | §11 (Module 9 — User Experience & Interfaces) |
| Depends on | Phase 0 (platform, orchestrator API gateway); Phase 1 (decision/reason-code/fraud-alert APIs). Each surface's full feature set additionally depends on the phase that produces its data (P2 for agri evidence, P3 for dashboards, P4 for collections/recommendations, P5 for the assistant) |
| Unblocks | Nothing downstream — P7 is the delivery surface for every other phase's output |
| Squads | Frontend/UX (R), Product design (R for IA/flows within the agreed requirements-level scope — no visual design system in this phase), Compliance (A for disclosure copy), Model Risk (A — no client-side model logic), Security (A — session/PII handling) |
| Governing contract | `00_MASTER_Implementation_Guide.md` §2–§4 — binding |

**Objective.** Build the four interface surfaces specified in SRS Module 9 — customer application & servicing app, officer/underwriter workbench, risk & portfolio dashboards, collections/case-management console — as thin, consistent clients over the Decision Orchestrator API gateway. **No business logic, scoring, or eligibility math lives in the frontend**: every number, reason, or recommendation is fetched from the backend engines built in P1–P6. This phase ships incrementally: a surface's skeleton and API contract can be built as soon as its backend phase reaches shadow, with the surface itself gated on that backend phase's own gate review before going live.

**Scope note (per SRS §11.1):** this phase is requirements-level execution — screens, flows, components, API contracts, accessibility, state handling. Visual design (a component style guide, color/typography, high-fidelity mockups) is a separate downstream design workstream, not covered here.

---

## 2. Position in the program

**Inputs:** P0 API gateway and auth; P1 decision/reason-code/fraud-alert/status APIs; P2 agri evidence APIs (map, NDVI/SPEI, crop-verification status) when available; P3 dashboard data APIs and streaming aggregates; P4 recommendation/feasible-set/EWS-alert APIs; P5 assistant conversation API (citation-carrying, tool-mediated); P6 improved models — consumed transparently through the same API contracts, no frontend change required on model promotion.

**Outputs:** the four production interface surfaces; a shared frontend component inventory (SRS §11.5) reused across them; UI-side telemetry (non-PII) feeding product analytics.

---

## 3. Entry criteria

- P0 API gateway live with auth; P1 in shadow or later (decision/reason-code APIs exist even if not yet fully live).
- `[POLICY: Compliance]` disclosure copy (KFS, APR, cooling-off, grievance-officer contact) drafted for the customer app.
- `[POLICY]` language list (≥ 4, per SRS UX-8) and accessibility conformance target (WCAG 2.2 AA, SRS §11.8) ratified.
- Design requirements approved: information architecture and screen inventory from SRS §11.4 signed off by Product.

---

## 4. Workstreams

### WS-7.1 Foundation (build once, shared by all four surfaces)

1. **API gateway contract.** All four surfaces call **one** API gateway — never an underlying model service directly (SRS §11.6a). Contract tests in CI verify every response used to render a score, reason, or alert carries `{model_id, model_version, decision_log_id}` (§11.6b) so the UI can deep-link to the audit trail.
2. **Shared component inventory** (SRS §11.5): reason-code card, evidence map + time-slider, citation-linked chat bubble, freshness badge, alert/subgraph viewer, consent & disclosure banner, offer comparison table. Built once as a shared library; each surface consumes, never forks, these components — this is what keeps the reason-code rendering on the customer decision screen and the officer decision panel provably identical.
3. **Auth & session.** Role-based access (customer / officer / risk-viewer / collections-agent); session timeout `[POLICY: Security]`; no PII in client-side logs or analytics events (SRS §11.8 Security).
4. **Async job handling.** Long-running operations (document OCR, agri evidence load) use job-status polling/webhooks; no UI request blocks > 2 s (§11.6c).
5. **Localization scaffolding.** Full string externalization from day one; ≥ 4 languages `[POLICY]`; disclosure and reason-code copy pulled from the same versioned, dated document registry Module 6/P5 uses for its corpus — **never hardcoded in frontend code** (§11.5 consent-banner requirement). This is a hallucination-adjacent control for UI copy, not just for the assistant: stale/incorrect on-screen rate or fee text is the same failure mode as an ungrounded LLM answer.
6. **Accessibility harness.** Automated WCAG 2.2 AA checks (axe-core or equivalent) wired into CI for every surface; manual screen-reader test added to the release checklist.

### WS-7.2 Customer application & servicing app (depends on P1; full feature set depends on P2/P4/P5)

Screens, in build order (SRS §11.4):

1. Home/product discovery, eligibility pre-check (soft-pull) — depends on P1 shadow scores.
2. KYC & consent, including the **Account Aggregator consent flow** — this screen is where DPDP consent artifacts (P0 WS-0.3) are captured; the consent record is logged with the same rigor as a credit decision.
3. Document upload with real-time OCR feedback — calls P1 document-check service.
4. Offer comparison — renders the P4 feasible-set + bandit-recommended templates via the shared offer-comparison component; **read-only for the customer**, selection only within what the backend returned as feasible (no client-side override of affordability math).
5. Decision & reasons screen — renders P1 SHAP-derived, legally templated reason codes (UX-2); decline path routes to human-review request, never a raw "denied" screen.
6. Loan servicing dashboard — repayment schedule, statements, prepayment, restructure requests (restructure requests route into P4's suitability/action flow once P4 ships).
7. Assistant entry point — embeds the P5 conversation API; every claim renders with its citation affordance or an explicit "unverified" state (UX-3, §11.5) — the frontend never suppresses or paraphrases a missing citation into a confident-looking sentence.
8. Grievance/support — RBI-mandated grievance-officer contact always visible, not buried (UX-9).

**Build note:** screens 1–3 and 6 (partial) can ship once P1 is live even before P4/P5 exist; screens 4, 5's assistant embed, and full restructure flows activate as P4/P5 reach their own gates. Feature-flag each screen behind its backend phase's gate status.

### WS-7.3 Officer / underwriter workbench (depends on P1; full feature set depends on P2/P3/P4)

1. Queue — filterable by product, risk band, SLA.
2. **Unified case file** (UX-4) — the single most important screen in the workbench: bureau summary, AA cash-flow summary, agri evidence map with NDVI/SPEI time-slider (P2), fraud alerts with subgraph visualization (P1/P6), SHAP reason panel (P1) — one screen, no tab-hopping across source systems. Build incrementally: ships with P1 data first, agri panel activates when P2 ships, fraud subgraph viewer activates when P6's graph layer ships (a simpler alert-list view is the P1-era fallback).
3. Decision panel — score, SHAP reasons, policy checklist, **override control**: every override requires a reason code and logs officer ID, timestamp, and the model version overridden (UX-5) — this is a hard requirement, not a nice-to-have, because overrides are the model-risk team's primary signal for where the model is systematically wrong.
4. Offer construction — P4 feasible-set + bandit-recommended template; officer can select only within the feasible set (same constraint as the customer app, different write-permissions — SRS §11.5 offer-comparison-table note).
5. Audit trail view — every decision-log entry for the case, human-readable, linking model version and reason provenance.

### WS-7.4 Risk & portfolio dashboards (depends on P3; foundation can start once P3's streaming aggregates exist)

Thin UI layer over the P3 OLAP store and dashboard API — **this workstream does not reimplement any P3 metric logic**, it renders what P3 computes.

1. Portfolio overview, vintage & roll-rate view, concentration & weather-overlay map, model-health panel, scenario widget, drill-through account list — one screen each, per SRS §11.4.
2. Role-based views (CRO / portfolio manager / model owner) over the **same underlying data** — role differences are permission and layout, never different numbers for the same metric.
3. **Freshness badge** on every panel (shared component, WS-7.1) — a dashboard that hides staleness manufactures false confidence in the viewer; this is non-negotiable per SRS §9.3.1 / §11.5.

### WS-7.5 Collections / case-management console (depends on P4)

1. Prioritized queue by EWS tier (Amber/Red).
2. Account alert detail — trigger reasons, PD delta, recommended action, rendered via the shared alert/subgraph viewer.
3. Action & disposition capture — **mandatory before an alert can be closed** (UX-7); this is the same disposition-completeness discipline P1 established for fraud and P4 depends on for its uplift learning loop (P6 WS-6.4) — a UI that lets an agent close an alert without a disposition silently breaks that loop downstream.
4. SLA/ownership tracker; outcome history feeding back into P8/P6 learning.

---

## 5. Shipping ladder

Each surface ships incrementally, screen-by-screen, gated on its backend dependency's own gate review — **a frontend screen never goes live ahead of the backend phase that supplies its data.** Within a surface: internal alpha (staff only) → pilot branch/officer group or a small customer cohort → full rollout. Every rollout stage repeats the WCAG/localization/accessibility checks (WS-7.1.6) — these are not one-time gates.

## 6. Deliverables checklist

- [ ] API gateway contract tests (model_id/version/decision_log_id on every relevant response)
- [ ] Shared component library (7 components, SRS §11.5) with usage docs
- [ ] Auth/session/PII-logging controls implemented and reviewed by Security
- [ ] Localization scaffolding + ≥ 4 languages live; copy sourced from the document registry, not hardcoded
- [ ] Accessibility CI harness + manual screen-reader test in the release checklist
- [ ] Customer app: 8 screens per WS-7.2, feature-flagged to their backend phase's gate status
- [ ] Officer workbench: unified case file + override-logging + 5 screens per WS-7.3
- [ ] Risk dashboards: 6 views per WS-7.4, freshness badge on every panel
- [ ] Collections console: 4 screens per WS-7.5, mandatory disposition capture enforced
- [ ] Independent accessibility audit report (WCAG 2.2 AA)

## 7. Exit criteria (gate review)

WCAG 2.2 AA conformance verified by independent audit on all four surfaces · customer-app first-meaningful-paint < 2.5 s on 3G-equivalent connections (SRS §11.8) · officer case-file load < 3 s including agri evidence · zero instances in QA of a frontend surface computing or displaying an EMI/eligibility number without a backend call (§11.6d) · disposition-capture completeness = 100% in the collections console pilot · localization parity confirmed across all launch languages.

## 8. Do-not-invent list (P7)

Disclosure/consent copy wording — sourced from the document registry, never drafted in frontend code · accessibility conformance level (fixed at WCAG 2.2 AA per SRS UX-8, not renegotiable per-surface) · language list · session-timeout values · performance budgets · any EMI, eligibility amount, or reason-code sentence composed client-side (always backend/tool-computed, never invented in the UI layer, mirroring SRS §8.3.2's rule for the assistant).

## 9. References for this phase

- W3C — *WCAG 2.2* — [w3.org/TR/WCAG22](https://www.w3.org/TR/WCAG22/)
- Nielsen Norman Group — *10 Usability Heuristics* — [nngroup.com](https://www.nngroup.com/articles/ten-usability-heuristics/)
- ISO 9241-11:2018 — *Usability: Definitions and concepts* — [iso.org](https://www.iso.org/standard/63500.html)
- RBI — *Digital Lending Directions, 2025* (disclosure/UI obligations) — [overview](https://www.argus-p.com/updates/updates/rbi-digital-lending-directions-2025-an-overview/)
- SRS §11 (Module 9) for full functional requirements, information architecture, and component inventory this phase implements
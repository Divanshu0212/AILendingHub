# Phase 7 — Blocking ticket register

Every `TBD[owner, ticket-id]` placeholder raised by Phase 7 work appears here.
`make grounding` reads every `docs/phase*/blocking_tickets.md` and fails on any
placeholder that appears in none of them.

Earlier registers: [Phase 0](../phase0/blocking_tickets.md) ·
[Phase 1](../phase1/blocking_tickets.md) · [Phase 2](../phase2/blocking_tickets.md) ·
[Phase 3](../phase3/blocking_tickets.md) · [Phase 4](../phase4/blocking_tickets.md).

Several of those block Phase 7 directly, and it is worth being precise about
which, because a frontend blocked on its own tickets and a frontend blocked on
someone else's look the same from the screen:

* **LH-203** (reason-code wording) is why the reason-code card renders a code and
  an explicit "wording pending ratification" state rather than a sentence. It is
  the single most visible upstream block in this phase — the decision screen is
  the customer's whole experience of the model, and it has no words on it.
* **LH-204** (cutoffs and bands) is why no screen shows a risk band.
* **LH-502** (action library and SLAs) is why the collections console has no
  action picker and no SLA clock with a target on it.
* **LH-504 / LH-505** (feasibility caps, ALM pricing) are why the offer
  comparison table has nothing to compare.
* **LH-120** (case-management system) is why the collections queue has no
  backend to post a disposition to.

Phase 7 §8 puts these on the do-not-invent list: disclosure/consent copy wording
· accessibility conformance level (fixed at WCAG 2.2 AA, not renegotiable) ·
language list · session-timeout values · performance budgets · any EMI,
eligibility amount or reason-code sentence composed client-side.

| Ticket | Owner | Blocks | What is needed | Status |
|---|---|---|---|---|
| LH-701 | Compliance + Content Ops | Every rendered sentence on all four surfaces | The **versioned, dated document registry** for UI copy. Phase 7 §4 WS-7.1.5 requires disclosure and reason-code copy to come from "the same versioned, dated document registry Module 6/P5 uses for its corpus — never hardcoded in frontend code", and frames stale on-screen rate or fee text as the same failure mode as an ungrounded LLM answer. The registry is listed as an input and is a deliverable of no phase: P5 builds a corpus for the *assistant*, and nothing in P0–P6 creates the UI-copy store or its ratification workflow. Found by building — `i18n/registry.ts` models the interface and `AbsentCopyRegistry` returns a visible missing state for every key, because typing draft English into a component is how an unratified sentence reaches a screenshot in a product review. | open |
| LH-702 | Model Risk + Credit Policy | `submitOverride`; the WS-7.3.3 override control | The **override reason-code taxonomy**. Phase 7 §4 WS-7.3.3 makes a reason code mandatory on every override and calls overrides "the model-risk team's primary signal for where the model is systematically wrong" — which is only true if the codes partition the ways a model can be wrong. The phase file names no codes and no owner for them. Distinct from LH-203, which is *customer-facing decline wording*; this is an *internal* taxonomy read by model risk, and the two have different audiences, different approvers and different revision cadences. Found by building. | open |
| LH-703 | Data Platform + Risk Reporting | `FreshnessBadge`; every WS-7.4 panel | The **staleness tolerance per dashboard panel**. SRS §9.2 RD-1 sets dashboard freshness ≤ 5 min for the streaming path, and Phase 7 §4 WS-7.4.3 makes the badge non-negotiable — but a badge needs a threshold to be a badge rather than a timestamp, and 5 min is the *ingestion* SLO for streaming aggregates, not the tolerance for a vintage curve rebuilt nightly or a scenario widget recomputed on demand. One number cannot serve all six views, and using the streaming figure everywhere would mark the nightly panels permanently stale. Found by building. | open |
| LH-704 | Security | `lib/auth/session.ts`; every surface | The **session timeout**, per role. Phase 7 §4 WS-7.1.3 marks it `[POLICY: Security]` and §8 puts session-timeout values on the do-not-invent list. It is plausibly not one number: a customer app on a personal handset and an officer workbench on a shared branch terminal have different threat models, and the workbench figure is the one that matters. `sessionTimeoutMs()` raises rather than returning a default. | open |
| LH-705 | Platform + SRE | `GatewayClient` retry behaviour | The **client retry budget and timeout** on the decisioning path. SRS §12 sets p95 < 2 s end-to-end and Phase 7 §4 WS-7.1.4 sets "no UI request blocks > 2 s", which together constrain but do not determine what a client does when the gateway is slow — retry, degrade, or surface. The client currently retries nothing, which is the safe direction (a retried override POST can double-log) but is not a ratified policy. Found by building. | open |
| LH-706 | Platform (API gateway squad) | Every function in `lib/gateway/endpoints.ts` | The **published gateway route contract**. Phase 7 §3 lists "P0 API gateway live with auth" as an entry criterion; P0's STATUS records the orchestrator and its ports, and no route table or OpenAPI document exists. Every path in `endpoints.ts` is this client's expectation rather than an agreed route, and the WS-7.1.1 contract tests cannot be written against nothing. Found by building. | open |
| LH-707 | Product + Compliance | Localization scaffolding; the §7 localization-parity exit criterion | The **launch language list**. Phase 7 §3 requires "≥ 4, per SRS UX-8" and §8 puts the language list on the do-not-invent list. Four is a count, not a list — it says how many languages, and choosing which four is a market and a regulatory decision (RBI Digital Lending Directions disclosure obligations attach to the language the customer is served in). `MINIMUM_LAUNCH_LANGUAGES` records the `[SPEC]` floor; the list itself comes from the registry. | open |
| LH-708 | Product + Compliance | WS-7.2 customer app performance work; §7 exit criterion 2 | The **performance budgets**, as testable definitions. Phase 7 §7 states first-meaningful-paint < 2.5 s "on 3G-equivalent connections" and officer case-file load < 3 s, and §8 puts performance budgets on the do-not-invent list. "3G-equivalent" is not a measurement configuration: throughput, RTT and packet loss all have to be fixed before a number is reproducible, and the three common presets differ by more than the margin the budget allows. Found by building — the budget cannot be regression-tested until it names a profile. | open |
| LH-709 | Compliance + Product | WS-7.2.8 grievance screen | The **grievance-officer contact details and escalation ladder**. Phase 7 §4 WS-7.2.8 requires the RBI-mandated grievance-officer contact "always visible, not buried". A name, a telephone number and an email address on a customer screen are the sharpest possible case of copy that must not be invented — a wrong grievance contact is a regulatory finding and a customer who cannot complain. Sourced from the registry (LH-701) but tracked separately because it has a named regulatory owner and its own review cadence. | open |
| LH-710 | Product design + Accessibility | §7 exit criterion 1; WS-7.1.6 | The **independent accessibility audit**, and the manual screen-reader test in the release checklist. WCAG 2.2 AA is fixed by SRS UX-8 and §8 forbids renegotiating it per surface, so the conformance *level* is `[SPEC]` and needs nothing. What is missing is the auditor: Master §3.1's independence principle applies here for the same reason it applies to model validation, and an accessibility audit run by the team that wrote the components tests what they thought about rather than what they missed. Not a policy value — a process stop, like LH-510. | open |

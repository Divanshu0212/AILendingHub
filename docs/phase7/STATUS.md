# Phase 7 — status and traceability

Maps every item on the Phase 7 §6 deliverables checklist to the artifact that
satisfies it, the track it runs on, and its honest state.

Last updated: 2026-09-02.

## The headline

**Phase 7 introduces a track state no previous phase has: `V` — built, not
verified.**

P0–P4 used three states. Track A meant a reference implementation exercised
against fixtures by a test suite that ran. Track P meant real external data.
Track B meant the bank, and no phase has any. Every one of those states carried
an implicit guarantee: *the code was executed*. `make test` runs 1,879 stdlib
tests in about 70 seconds, and a Track A number is a number a machine produced.

Nothing in `frontend/` has been executed. There is **no Node.js toolchain on the
authoring machine**, so `npm install`, `next build`, `tsc --noEmit`, `eslint`,
the accessibility harness and the WS-7.1.1 contract tests have all never run —
not once, not partially. The code was written against the phase file, the SRS and
the Python dataclasses it mirrors, and nothing checked it.

That is a weaker claim than "Track A" and it is given its own column rather than
being folded into one, for the reason CLAUDE.md gives about P3's gate states:
reporting two different things the same way puts them in the same column and the
worse one never gets escalated. A screen that has never rendered and a screen
covered by a passing test suite are not the same artifact, and a checklist that
marks both "done" is lying about the second-largest risk in this phase.

The largest risk is P7-F1.

## The blocker above all the others

**The SRS section Phase 7 implements does not exist.**

Phase 7 names its module as "§11 (Module 9 — User Experience & Interfaces)" and
references §11.4, §11.5, §11.6a–d, §11.8 and UX-1..UX-9 throughout as binding.
The SRS runs Module 1 (§3) to Module 8 (§10); §11 is *Cross-Cutting Concerns*,
§11.4 is *Privacy & data protection*, §11.5 is *Security*, and §11.6 and §11.8 do
not exist. `git grep` finds no "Module 9", no "User Experience", and no `UX-n`
identifier anywhere outside the Phase 7 file.

What survives is what the phase file paraphrases inline: the seven component
*names*, the eight customer screen *names*, the WCAG target, the one-gateway
rule, the attribution triplet, the performance budgets. That was enough to build
WS-7.1, WS-7.3 and WS-7.5.

What does not survive: each component's specification, the information
architecture, and UX-1..UX-9 as traceable requirement ids. Phase 7 §3's entry
criterion — "information architecture and screen inventory from SRS §11.4 signed
off by Product" — references a section about data-protection law and therefore
cannot be met.

Each component's contract was instead derived from the **backend module it
renders**: `ews.routing.Alert`'s constructor refusals became the alert viewer's
required fields, `reco.feasible.Assessment.binding_constraint` became the offer
table's rejected-row content, `decisionlog.record.ReasonCode` became the reason
card. That turned out to be a good source, because those constructors encode
arguments rather than field lists. Where no backend counterpart exists — the
freshness badge has none — there was nothing to derive from, and LH-703 is the
result.

LH-711 · finding [P7-F1](../../Lending_Hub_Phase_Docs/Phase_7_FINDINGS.md).

## Track legend

| | Meaning |
|---|---|
| **A** | Reference implementation, exercised by a test suite that runs |
| **V** | **Written, never executed.** No toolchain — see the headline |
| **B** | Bank deployment. None |
| **—** | Not applicable |

## Deliverables checklist (Phase 7 §6)

| # | Item | Artifact | Track | State |
|---|---|---|---|---|
| 1 | API gateway contract tests (model_id/version/decision_log_id on every relevant response) | [provenance.ts](../../frontend/src/lib/gateway/provenance.ts) · [client.ts](../../frontend/src/lib/gateway/client.ts) · [attribution.contract.ts](../../frontend/tests/contract/attribution.contract.ts) | V | **partial** — the contract is enforced in three layers (a type that cannot hold a bare number, a runtime check that throws, a UI component that links). The tests are written and **have never run**, and they test the client rather than a gateway because no gateway route contract exists (LH-706) |
| 2 | Shared component library (7 components, SRS §11.5) with usage docs | [components/shared/](../../frontend/src/components/shared/) | V | **partial** — all seven built, each mirroring the Python module it renders. Their *specifications* were unrecoverable (LH-711), so each was derived from its backend counterpart; the freshness badge, which has none, is the weakest of the seven. Usage docs are the module docstrings plus the README table |
| 3 | Auth/session/PII-logging controls implemented and reviewed by Security | [session.ts](../../frontend/src/lib/auth/session.ts) · [client.ts](../../frontend/src/lib/gateway/client.ts) | V | **partial** — four roles map to capabilities rather than to screens, so no role gets a different number for the same metric (WS-7.4.2). `logSafe` redacts PII-shaped keys and drops unrecognised objects entirely rather than traversing them. `sessionTimeoutMs()` **raises** (LH-704). No Security review: none exists to conduct one |
| 4 | Localization scaffolding + ≥ 4 languages live; copy sourced from the document registry | [i18n/](../../frontend/src/i18n/) | V | **blocked** — the scaffolding is built and the registry **does not exist and is nobody's deliverable** (LH-701, P7-F2). Zero languages live. `AbsentCopyRegistry` returns a visible missing state for every key, so every screen renders mostly placeholders — the honest state, not an unfinished one |
| 5 | Accessibility CI harness + manual screen-reader test in the release checklist | — | — | **not done** — axe-core needs a toolchain. The design targets WCAG 2.2 AA (focus indicators incl. 2.4.11/2.4.13, skip link, semantic tables, text-not-colour state, 44px targets, `lang` from locale) and **every one of those is an intention, not a measurement** |
| 6 | Customer app: 8 screens per WS-7.2, feature-flagged to their backend phase's gate status | [app/apply/](../../frontend/src/app/apply/) | V | **partial** — 2 of 8. Decision & reasons (screen 5) and offer comparison (screen 4). Screens 1–3, 6–8 not built. No feature-flag mechanism: gate status is not exposed by any API this repository defines |
| 7 | Officer workbench: unified case file + override-logging + 5 screens per WS-7.3 | [workbench/](../../frontend/src/components/workbench/) · [app/workbench/](../../frontend/src/app/workbench/) · [audit](../../frontend/src/app/audit/) | V | **partial** — all 5 screens. The override control logs all four WS-7.3.3 fields, of which only the reason code is a form field; officer id comes from the session and the timestamp from the server, because a client-asserted officer id would sit in model risk's primary signal looking authentic. It **refuses to render** without a ratified reason taxonomy (LH-702) |
| 8 | Risk dashboards: 6 views per WS-7.4, freshness badge on every panel | [app/dashboards/](../../frontend/src/app/dashboards/) | V | **partial** — the panel renderer is built and the badge is structurally unavoidable (`Panel` takes freshness as a required prop). The six views are `dashboardId` routes with no data source, and the weather-overlay map and scenario widget need more than a panel list. The staleness tolerance is LH-703 |
| 9 | Collections console: 4 screens per WS-7.5, mandatory disposition capture enforced | [app/collections/](../../frontend/src/app/collections/) · [DispositionForm](../../frontend/src/components/collections/DispositionForm.tsx) | V | **partial** — 3 of 4 screens; the SLA tracker renders no panels and names the tickets that block it. Disposition capture is enforced in three places: `endpoints.ts` has **no `closeAlert` function**, so the bypass has no name to write; the request type requires an outcome code, mirroring `Disposition.__post_init__`; and the form has no submit path without one. It **refuses to render** without the action library (LH-502) |
| 10 | Independent accessibility audit report (WCAG 2.2 AA) | — | — | **not done** — LH-710. Master §3.1's independence argument applies: an audit run by the team that wrote the components tests what they thought about |

## Exit criteria (Phase 7 §7)

| # | Criterion | State |
|---|---|---|
| 1 | WCAG 2.2 AA verified by independent audit on all four surfaces | **not measured** — no toolchain, no auditor (LH-710). The target is `[SPEC]` and fixed; only the verification is missing |
| 2 | Customer FMP < 2.5 s on 3G-equivalent; officer case-file load < 3 s | **not measurable as written** — "3G-equivalent" is not a measurement configuration, so the budget is not regression-testable by anyone (LH-708, P7-F11). Separately not measured: nothing runs |
| 3 | Zero instances in QA of a surface computing an EMI/eligibility number without a backend call | **structurally satisfied, unverified** — no arithmetic helper exists in the codebase to call, every money field arrives as `{amount, display}` and components render only `display`, and a build gate fails on `Math.*` and on render-layer arithmetic. The gate **has never executed**. The criterion is also stated in the wrong venue (P7-F12): QA sees the screens it opened |
| 4 | Disposition-capture completeness = 100% in the collections console pilot | **not measurable** — no pilot, no case-management system (LH-120), no disposition log (LH-510). Enforced structurally, which is the same shape as P4's propensity criterion: a property of the API surface rather than a measurement |
| 5 | Localization parity across all launch languages | **not measurable** — no registry (LH-701) and no launch language list (LH-707). `copyCoverageGaps()` is written and would check it mechanically |

**Track B evidence: 0 of 5. Track V evidence: 0 of 5** — nothing has run.

## Twelve tickets open

LH-701 to LH-712 ([register](blocking_tickets.md)). Five are Phase 7 §8
do-not-invent values (LH-701 copy, LH-704 session timeout, LH-707 languages,
LH-708 budgets, LH-709 grievance contact — the accessibility level is `[SPEC]`
and needed no ticket).

**Seven were found by building:** LH-702 (override reason taxonomy, which is not
Phase 1's customer-facing dictionary and has a different owner, audience and
revision cadence), LH-703 (per-panel freshness tolerance — the SRS's 5-minute
figure is an ingestion SLO and applying it to weekly PSI panels marks four of six
views permanently stale, which trains the viewer to ignore the badge), LH-705
(client retry budget), LH-706 (the gateway route contract — an entry criterion
with no published artifact), LH-710 (the independent accessibility auditor — a
process stop, like LH-510), LH-711 (the missing SRS module), and LH-712 (the
basemap provider, a DPO decision hiding inside a UI requirement).

Several upstream tickets block this phase harder than its own do. **LH-203** is
why the decision screen — the customer's entire experience of the model — has no
words on it. **LH-502** is why the two most important controls in the build, the
override and the disposition form, both refuse to render.

## What was deliberately not built

**No fixture adapter.** The adapter port has `GatewayAdapter` and
`AbsentAdapter`, which rejects every call with a ticket-bearing error. There is
no third implementation returning plausible applications, and that is a decision
rather than an omission.

A fixture adapter would put a score, a PD, an EMI and reason sentences on screen
— the four things Phase 7 §8 exists to keep from being invented client-side — and
a screenshot of a demo build is indistinguishable from a screenshot of a real
one. This repository's posture is that a plausible number is worse than a missing
one because it survives review; a plausible **screen** is that failure with a
wider audience, because screens are what get shown to committees. It is the same
argument ADR-0014 makes for refusing a simulated collections desk, moved one
layer out.

What `AbsentAdapter` gives instead is four surfaces that exercise their loading,
error and unavailable states — the states this system will be in for most of its
build, and the ones nobody designs.

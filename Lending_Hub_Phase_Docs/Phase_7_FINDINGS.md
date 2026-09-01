# Phase 7 — implementation findings against the phase documents

Produced while building Phase 7. Master §1: "conflicts are raised as tickets,
never resolved silently by an implementer." Every finding below is **raised and
unapplied** — the SRS, the Master and the Phase 7 file are unchanged pending the
document owner's decision, as with the Phase 0–4 findings.

**A note on the evidence behind these.** Phase 7 is the first phase in this
repository built with **no toolchain at all**: there is no Node.js on the
authoring machine, so nothing in `frontend/` has been compiled, run, type-checked
or rendered. That changes what a finding here can be. Phases 1–4 could report
things found by *measurement* — P4-F5's BOCPD confidence result came from running
the detector. Nothing below is measured. Every finding is of one of three kinds:

* a **conflict** between two rank-ordered documents, found by reading them
  against each other while writing code that had to satisfy both;
* an **under-specification**, found because code had to produce a specific thing
  and the document named a category;
* a **structural gap** — something the plan needs and no phase creates.

That is a weaker evidence base than P1–P4's and it is stated up front rather than
buried, because "found by building" means something different when the build was
never executed.

## Status of each finding

| # | Finding | Kind | Ticket |
|---|---|---|---|
| P7-F1 | **The SRS has no Module 9 and no §11.4/§11.5/§11.6/§11.8.** Every requirement reference in Phase 7 points at a section that does not exist, and the component inventory, IA and UX-1..UX-9 requirements it implements are nowhere in the SRS | **Conflict (blocking, rank 1 vs rank 3)** | **LH-711 (new)** |
| P7-F2 | **The document registry is an input to Phase 7 and a deliverable of no phase.** P5 builds a corpus for the assistant; nothing builds the UI-copy store | Structural gap | **LH-701 (new)** |
| P7-F3 | **Override reason codes are mandatory and undefined**, and they are not the same taxonomy as customer-facing decline wording | Gap found by building | **LH-702 (new)** |
| P7-F4 | **"Never hardcoded" has no stated scope**, so it is unclear whether a column header is disclosure copy | Under-specification | LH-701 |
| P7-F5 | **A SHAP contribution on a customer screen and on an officer screen are different objects**, and the shared-component rule as written makes them the same | Gap found by building | — |
| P7-F6 | **Reason-code display rank is a model output**, and a frontend that numbers the array has adopted the transport order as the adverse-action order | Gap found by building | — |
| P7-F7 | **A basemap tile provider is a third-party call from a screen showing personal data**, and the evidence-map requirement does not mention it | Gap found by building | **LH-712 (new)** |
| P7-F8 | **WCAG 2.4.1 and WS-7.1.5 conflict directly** on the skip link, and one of them must lose | **Conflict (rules within the phase)** | LH-701 |
| P7-F9 | **"Read-only for the customer" and "selection only within the feasible set" are not consistent** unless choosing and constructing are separated | Under-specification | — |
| P7-F10 | **One freshness tolerance cannot serve six dashboard views**, and the SRS number is an ingestion SLO rather than a staleness budget | Gap found by building | **LH-703 (new)** |
| P7-F11 | **"3G-equivalent" is not a measurement configuration**, so the §7 performance budget is not regression-testable | Under-specification | **LH-708 (new)** |
| P7-F12 | **The exit criterion "zero instances in QA" puts a build-gate rule in a sampling process** | Method note | — |
| P7-F13 | **An absent panel and an empty panel are the same rectangle**, which the incremental-build instruction makes unavoidable unless availability is a field | Gap found by building | — |

---

## A. Conflicts — documents that disagree

### A1 (P7-F1). The SRS section Phase 7 implements does not exist

**This is the largest finding in the phase and it blocks the gate rather than any
particular screen.**

Phase 7's header states its SRS module as "**§11 (Module 9 — User Experience &
Interfaces)**" and then references, as binding, at least the following:

* §11.4 — "Screens, in build order (SRS §11.4)" and "the screen inventory from
  SRS §11.4"
* §11.5 — the **shared component inventory**, referenced seven times, including
  the enumerated list of seven components and the consent-banner and
  offer-comparison-table notes
* §11.6a/b/c/d — the one-gateway rule, the `{model_id, model_version,
  decision_log_id}` requirement, the 2-second async rule, and the exit criterion
  on client-side EMI computation
* §11.8 — the WCAG 2.2 AA conformance target, the security/PII rules, and the
  first-meaningful-paint budget
* UX-2, UX-3, UX-4, UX-5, UX-7, UX-8, UX-9 — functional requirement ids

**None of these exists.** The SRS (`README.md`, rank 1) runs Module 1 (§3)
through Module 8 (§10) and then §11 is **"Cross-Cutting Concerns"** — MLOps,
model risk, fairness, privacy, security. §11.4 is *Privacy & data protection*.
§11.5 is *Security*. There is no §11.6 and no §11.8. §12 is Non-Functional
Requirements; the SRS ends at §14. `git grep` finds **zero** occurrences of
"Module 9", "User Experience", or any `UX-n` identifier anywhere in the
repository outside the Phase 7 file itself.

**Why this is more than a numbering slip.** Two of the mis-referenced sections
are the substantive content of the phase:

1. **The seven-component inventory.** Phase 7 §4 WS-7.1.2 lists the seven
   components inline, so they are recoverable. But it describes them as "SRS
   §11.5" and defers the *specification* of each to that section — what a
   freshness badge must show, what states the offer-comparison table has, what
   the consent banner's requirement actually is. WS-7.1.2 says "this is what
   keeps the reason-code rendering ... provably identical" without saying what
   the rendering is. Building them meant deriving each component's contract from
   the *backend* modules it renders (`ews.routing.Alert`, `reco.feasible.FeasibleSet`,
   `decisionlog.record.ReasonCode`) rather than from a UI specification. That
   turned out to be a better source — the Python constructors encode real
   refusals — but it is not what the phase file said to do, and where the backend
   is silent (the freshness badge has no backend counterpart at all) there was
   nothing to derive from.

2. **The screen inventory.** WS-7.2 lists eight customer screens "per SRS §11.4",
   which is Privacy & data protection. The eight are named inline, so the
   *inventory* survives; the information architecture, navigation model and
   per-screen requirements do not. Phase 7 §3's entry criteria include
   "information architecture and screen inventory from SRS §11.4 signed off by
   Product" — an entry criterion that references a non-existent document cannot
   be met, and cannot be *known* to be unmet by anyone reading only the phase
   file.

**What is recoverable and what is not.** §11.6a–d and §11.8's requirements are
paraphrased in the phase file at the point of use, so the WS-7.1 foundation could
be built from the phase file alone. That is why `frontend/` exists. What could
not be recovered:

| Referenced | Recoverable from the phase file? |
|---|---|
| The seven component names | Yes — listed inline |
| Each component's specification | **No** |
| The eight customer screens | Yes — listed inline |
| Information architecture / navigation | **No** |
| WCAG 2.2 AA target | Yes — stated in §3 and §8 |
| The one-gateway rule and the triplet | Yes — stated in WS-7.1.1 |
| First-meaningful-paint and case-load budgets | Yes — stated in §7 |
| UX-1..UX-9 as testable requirement ids | **No** — the ids appear with a
  one-clause gloss each and nothing to trace against |

**Recommendation.** Either (a) SRS v1.3 adds Module 9 as §11 and renumbers
Cross-Cutting Concerns, which is a large edit touching every cross-reference in
the repository, or (b) Phase 7 is amended to state its requirements
self-containedly and to drop the §11.x/UX-n references. **(b) is the smaller
change and (a) is the more honest one**: the SRS's own table of contents implies
nine modules and delivers eight, and Module 9 is where the frontend requirements
were supposed to be written down. Raised as LH-711 for the SRS owner rather than
resolved here — an implementer inventing Module 9's contents would be inventing
the very requirements Phase 7 exists to execute against.

### A2 (P7-F8). WCAG 2.4.1 and WS-7.1.5 cannot both be satisfied

WS-7.1.5: "Full string externalization from day one ... **never hardcoded in
frontend code**."

WCAG 2.2 AA 2.4.1 (Bypass Blocks): a mechanism to skip repeated content must
exist, and to be usable it must be the **first focusable element on the page** —
before any asynchronous copy resolution has completed.

These conflict at exactly one point. A skip link whose label renders the
missing-copy placeholder is a skip link a screen-reader user cannot identify,
which fails the criterion the link exists to satisfy. A skip link that waits for
the registry is not the first focusable element. A skip link with hardcoded
English violates WS-7.1.5.

Resolved in `app/layout.tsx` in favour of accessibility — WCAG 2.2 AA is fixed by
Phase 7 §8 and "not renegotiable per-surface", which is a stronger obligation
than WS-7.1.5's — and the string is marked in the source as the single exception.

**The real fix is a registry capability nobody has specified:** a small set of
*chrome* keys resolvable at build time and baked into the bundle, distinct from
*disclosure* keys resolved at runtime with an effective date. That distinction is
also the answer to P7-F4. Folded into LH-701.

---

## B. Under-specification — a category where code needs a value

### B1 (P7-F4). "Never hardcoded" does not say what counts as copy

WS-7.1.5 says "full string externalization" and §8 says "disclosure/consent copy
wording". Those are different scopes and the phase file uses them
interchangeably.

A Key Fact Statement is obviously disclosure copy. A grievance-officer's
telephone number obviously is. But a table column header reading "tier", a
`<caption>` on the offer table, the word "owner" in a definition list — are those
disclosure copy that must survive a registry round-trip with an effective date,
or are they chrome?

The distinction matters in both directions. Treating chrome as disclosure gives
every screen in this build a wall of placeholders (which is what happened —
`i18n/keys.ts` externalises all of it) and puts a governance workflow around the
word "owner". Treating disclosure as chrome is the failure WS-7.1.5 names.

This codebase chose the over-strict direction, which is the safe one to be wrong
in, and it is visibly wrong: every screen renders mostly placeholders. The right
answer is two key namespaces with different resolution and governance, which is
the same conclusion P7-F8 reaches from the accessibility side.

### B2 (P7-F9). "Read-only" and "selection" are stated as both

WS-7.2.4: "Offer comparison — renders the P4 feasible-set ... **read-only for the
customer**, selection only within what the backend returned as feasible."

Read as one sentence this is contradictory. It resolves if *choosing* and
*constructing* are separated: the customer may pick one of the offers the backend
returned and may not alter any offer's terms. That reading is supported by
WS-7.3.4, which says the officer has "the same constraint as the customer app,
different write-permissions" — implying the customer has *some* write.

But the customer's selection is a write that creates something (an application
for that product), and no endpoint for it appears in Phase 7 or in P1's
deliverables. So the screen was built read-only with no selection control, and
the ambiguity is raised rather than resolved by inventing the endpoint. Folded
into LH-706.

### B3 (P7-F11). "3G-equivalent" is not a testable configuration

Phase 7 §7: "customer-app first-meaningful-paint < 2.5 s on **3G-equivalent
connections**". §8 puts performance budgets on the do-not-invent list.

A latency budget is only a budget if the measurement configuration is fixed.
"3G-equivalent" leaves throughput, round-trip time and packet loss unspecified,
and the common presets differ by more than the 2.5 s budget's own margin —
Chrome DevTools' "Slow 3G" and "Fast 3G" alone differ by roughly a factor of
four in RTT. A CI regression test cannot be written against this, which means the
budget can only be checked by someone running a manual test with settings they
chose, and the number will drift with whoever runs it.

Also unspecified: which device class, whether the measurement is cold or warm
cache, and whether it is the first screen or any screen. Raised as LH-708.

---

## C. Gaps found by building

### C1 (P7-F2). The document registry is an input to every phase and a deliverable of none

WS-7.1.5 requires copy to come from "the same versioned, dated document registry
Module 6/P5 uses for its corpus". P5's phase file builds a **RAG corpus** — a
retrieval store for the assistant, with chunking, embeddings and a retriever. A
corpus and a copy registry are not the same artifact:

| | Assistant corpus | UI copy registry |
|---|---|---|
| Retrieval | semantic, top-k | exact, by key |
| Consumer | an LLM | a component |
| Failure mode | a wrong citation | a wrong APR on screen |
| Governance | document effective dates | Compliance ratification per locale per key |
| Missing entry | fewer citations | **a blank screen or an unratified sentence** |

The overlap is real — both need versioning and effective dates — but a
`resolve(key, locale)` interface with a ratification flag is not something a
vector store provides, and nothing in P0–P6 creates it. This is the same class of
finding as P4's LH-510 (dispositions listed as an entry criterion and as nobody's
deliverable), and it has the same consequence: the phase can be built and cannot
be shown. Raised as LH-701.

### C2 (P7-F3). Override reason codes are mandatory, undefined, and not LH-203

WS-7.3.3 makes a reason code mandatory on every override and justifies it: "overrides
are the model-risk team's primary signal for where the model is systematically
wrong."

That justification is only true if the codes **partition the ways a model can be
wrong**. "Officer disagreed" is a code and carries no signal. The phase file names
no codes, no owner and no ratification path for them.

It is tempting to reuse LH-203, Phase 1's reason-code dictionary. That would be
wrong on every axis: LH-203 is *customer-facing decline wording* owned by
Compliance, worded for a legal audience, revised on regulatory deadlines. This is
an *internal* taxonomy owned by Model Risk, worded for analysts, revised when the
model changes. Same shape, different everything. Raised as LH-702.

`OverrideControl` refuses to render at all when the fetched taxonomy is empty,
rather than offering a free-text box — a free-text override reason is not a
taxonomy, and model risk would be reading strings.

### C3 (P7-F5). A SHAP contribution means different things to different readers

WS-7.1.2 requires the reason-code card to be shared so that customer and officer
rendering are "provably identical". Taken literally that means a signed SHAP
contribution appears on the customer decision screen.

It should not. On an officer screen a contribution of `-0.34` is diagnostic: the
officer knows the model, the feature and the scale. On a customer screen it is a
number the customer will try to act on and cannot interpret — there is no scale,
no anchor (LH-208), and no ordering the customer can verify.

Resolved with an `audience` prop that gates the contribution, which keeps the
*sentence and its ordering* provably identical (which is what the requirement is
protecting) while suppressing a model-internal quantity. That is a departure from
the literal instruction and is stated here rather than silently taken. If the
document owner disagrees, the fix is one prop.

### C4 (P7-F6). Reason display rank is a model output, not an array index

This was found by the no-client-math build gate firing on `rank={index + 1}`,
which looked like a false positive.

It is not. SRS §4.3.1 defines the reason-code ranking rule, and the SRS change log
records that rule being **corrected** in v1.2 ("§4.3.1 corrects the reason-code
ranking rule to points-below-max"). A frontend that numbers the received array
1..n has silently adopted the transport order as the adverse-action ordering. If
the backend later re-sorts — or if a JSON serialiser does not preserve order,
which is not guaranteed for a list nested in an object across every stack — the
displayed ordering and the ordering the model risk team believes was shown
disagree, with nothing in the record to say so.

`ReasonCode` therefore carries a server-supplied `rankDisplay`. This is a small
finding with a general shape worth naming: **any ordinal a customer sees is a
claim about ordering, and ordering is a model output.**

### C5 (P7-F7). The evidence map needs a basemap, and a basemap is a third-party call

WS-7.3.2 requires an "agri evidence map with NDVI/SPEI time-slider". A map
implies a basemap, and a basemap implies tile requests to a third party carrying
the tile coordinates — which, for a map centred on a borrower's plot, disclose
the plot's location.

SRS §11.4 (the real one, Privacy & data protection) is explicit that "satellite
plot polygons [are] treated as personal data once linked to a borrower". So
choosing a tile provider is a data-processing decision requiring a DPO position
and a contract, not a library import — and India's data-residency requirement
("all personal data within India") constrains it further.

`EvidenceMap` therefore renders no basemap and imports no mapping library. That
makes it a worse map and keeps the decision with the people who should make it.
Raised as LH-712.

### C6 (P7-F10). One freshness tolerance cannot serve six views

WS-7.4.3 makes the freshness badge non-negotiable. A badge needs a threshold to
be a badge rather than a timestamp.

The obvious source is SRS §9.2 RD-1: "dashboard freshness ≤ 5 min". But read in
context that is the **streaming ingestion SLO** for §9.3.1's Flink-to-OLAP path,
not a staleness budget for a panel. Applying it to all six §9.2 views marks four
of them permanently stale by construction: PSI/CSI are computed by "Flink jobs
**weekly**" (§9.3.3), vintage curves are cohort aggregates, and the scenario
widget (§9.2 RD-6) recomputes on demand and has no age at all.

So a single tolerance produces a dashboard where four of six panels always show
"stale" — which trains the viewer to ignore the badge, and a badge everyone
ignores is worse than no badge because it is on the screen discharging the
requirement. Raised as LH-703: a per-panel tolerance, owned by whoever owns the
pipeline behind each panel.

### C7 (P7-F13). Absent and empty are the same rectangle

WS-7.3.2 builds the unified case file incrementally: P1 data first, agri when P2
ships, the fraud subgraph when P6's graph layer ships.

The natural implementation renders what arrived and omits the rest. That produces
the worst possible screen for an underwriter, because **an absent panel and an
empty panel are visually identical**. "This applicant has no fraud alerts" and
"the fraud layer is not deployed in this environment" lead to opposite
underwriting decisions and render as the same blank space.

Worse, the frontend cannot distinguish them from the payload: a null agri panel
means no plot, no P2, or a timed-out upstream call, and all three arrive as null.

So `UnifiedCaseFile` requires a `panelAvailability` array from the gateway and
renders three distinct states — populated, empty-but-checked,
unavailable-with-a-reason — with distinct `data-panel-state` attributes so a DOM
snapshot preserves the distinction too. The gateway must therefore report, per
panel, whether it *could* answer. That is a requirement on the API contract that
the phase file's "build incrementally" instruction implies and does not state.

---

## D. Method note

### D1 (P7-F12). A build-gate rule stated as a QA sampling criterion

Phase 7 §7 exit criterion 4: "**zero instances in QA** of a frontend surface
computing or displaying an EMI/eligibility number without a backend call".

The rule is right and the venue is wrong. QA observes the screens that were
tested; "zero instances in QA" is satisfied by a QA plan that did not open the
screen where the violation is. And the violation is invisible when it occurs —
a client-computed EMI that happens to match the backend's looks like a correct
screen.

This is a static property of the source, checkable exhaustively:
`frontend/scripts/check-no-client-math.mjs` fails the build on arithmetic in the
render layer, on `Math.*` anywhere, and on client-side number formatting. It
covers the screens nobody opened.

The script is a floor rather than a proof — it cannot see arithmetic reached
through a dependency or an unclassified helper, and its own regexes have never
been executed. The load-bearing control is architectural: **no arithmetic helper
exists in the codebase to call**, and every money field arrives as
`{ amount, display }` with components rendering only `display`.

Recommendation: amend §7 criterion 4 to name a CI gate rather than a QA
observation. The QA check is still worth running; it should not be the only one.

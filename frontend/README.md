# Phase 7 — Frontend Applications

> ## UNVERIFIED — never built or run, no Node toolchain on the authoring machine
>
> **Nothing in this directory has been compiled, executed, type-checked, linted,
> tested, or rendered.** There is no Node.js and no npm on the machine this was
> authored on, so `npm install`, `next build`, `next dev`, `tsc --noEmit`,
> `eslint` and every test in `tests/` have all never run — not once, not
> partially.
>
> This means, concretely:
>
> * The dependency versions in `package.json` were written from memory and no
>   lockfile exists. They may not resolve together.
> * TypeScript types are unchecked. There are almost certainly type errors.
> * JSX and import paths are unverified. A wrong relative path is invisible here.
> * Tailwind class names are unverified against the installed version.
> * The `check-no-client-math.mjs` gate has never executed. Its regexes may not
>   fire, or may fire on the wrong things.
> * The accessibility claims below are **design intentions**, not measurements.
>   No axe-core run, no screen-reader pass, no contrast check. WCAG 2.2 AA is the
>   target this was written toward; nothing here is evidence it is met.
>
> Treat this directory as a design document that happens to be written in
> TypeScript. The first job of anyone picking it up is in
> [Getting it to run](#getting-it-to-run) — expect to fix errors, not to
> find none.

---

## What this is

The four interface surfaces from Phase 7 (`Lending_Hub_Phase_Docs/Phase_7_Frontend.md`),
built as one Next.js App Router application over the Decision Orchestrator API
gateway. Read [`CLAUDE.md`](../CLAUDE.md) first — the grounding contract applies
here exactly as it does to `src/lending_hub/`.

| Surface | Workstream | State |
|---|---|---|
| Foundation (gateway client, 7 shared components, auth, i18n, a11y) | WS-7.1 | built |
| Officer / underwriter workbench | WS-7.3 | built — queue, unified case file, decision panel, override control, audit trail |
| Collections / case-management console | WS-7.5 | built — queue, alert detail, mandatory disposition capture, SLA tracker stub |
| Risk & portfolio dashboards | WS-7.4 | panel renderer + freshness badge; the six views are routes with no data source |
| Customer application & servicing app | WS-7.2 | decision and offer screens only; screens 1–3, 6, 7 not built |

Status and traceability: [`docs/phase7/STATUS.md`](../docs/phase7/STATUS.md).
Open tickets: [`docs/phase7/blocking_tickets.md`](../docs/phase7/blocking_tickets.md).
Findings: [`Lending_Hub_Phase_Docs/Phase_7_FINDINGS.md`](../Lending_Hub_Phase_Docs/Phase_7_FINDINGS.md).

---

## The three architectural rules

Everything else in here follows from these.

### 1. The frontend computes nothing

Phase 7 §8 puts "any EMI, eligibility amount, or reason-code sentence composed
client-side" on the do-not-invent list, and §7 makes "zero instances in QA of a
frontend surface computing or displaying an EMI/eligibility number without a
backend call" an exit criterion.

The architecture makes violating it awkward rather than merely forbidden:

* **There is no arithmetic helper anywhere in the UI layer.** No `formatCurrency`,
  no `calculateEmi`, no `percentage()`. Not one function that takes numbers and
  returns a number.
* **Every money and ratio field is a `FormattedNumber`** — `{ amount, display }`
  — and components render `.display`, the string the *backend* chose. `.amount`
  exists for sorting and accessibility announcements. A frontend that picks the
  rounding on a repayment figure has made a disclosure decision.
* **`npm run check:no-client-math`** (`scripts/check-no-client-math.mjs`) fails
  the build on `Math.*` anywhere under `src/`, on arithmetic operators in
  `src/components/` and `src/app/`, on `toFixed`/`Intl.NumberFormat`/
  `toLocaleString` in the render layer, and on long English string literals in
  components. `.eslintrc.json` carries the same rules as `no-restricted-syntax`,
  so an editor flags them before CI does.

  The script is deliberately blunt and *will* produce false positives — `index + 1`
  is arithmetic by its lights. Every one caught so far turned out to be a real
  finding rather than a nuisance; see P7-F6 in the findings for the best example.

### 2. No copy is written in this codebase

Phase 7 §4 WS-7.1.5 requires disclosure and reason-code copy to come from "the
same versioned, dated document registry Module 6/P5 uses for its corpus — never
hardcoded in frontend code", and frames stale on-screen rate or fee text as the
same failure mode as an ungrounded LLM answer.

The registry does not exist (**LH-701**). So:

* `src/i18n/keys.ts` declares the copy **keys** and contains **no English**.
* `src/i18n/registry.ts` models the registry interface. `AbsentCopyRegistry` —
  the implementation this build uses — returns a missing-copy result for every
  key.
* `<Copy k="..." />` renders a visible, ticket-bearing placeholder when a key
  cannot be resolved. **There is no `fallback` prop and there will not be one.**
  A fallback is where unratified English enters a regulated screen: someone adds
  it for a demo, the demo becomes the pilot, and the sentence is in a screenshot
  before anyone asks who approved it.

Consequence: **every screen in this build renders mostly placeholders.** That is
the honest state of a frontend whose copy registry has not been created, and it
is deliberate rather than unfinished.

There is exactly one hardcoded English string — the WCAG 2.4.1 skip link in
`app/layout.tsx` — and it is a real conflict between two binding rules rather
than an oversight. See P7-F8.

### 3. Nothing model-derived renders without its provenance

Phase 7 §4 WS-7.1.1: every response rendering a score, reason or alert carries
`{model_id, model_version, decision_log_id}`.

Enforced in three layers:

* **Type.** `Attributed<T>` pairs a value with its `ModelAttribution`. A
  component that displays a score takes `Attributed<number>`, so there is no way
  to type in a bare number.
* **Runtime.** `GatewayClient` checks the triplet on every response marked
  `modelDerived`, on the paths that call names, and **throws** rather than
  rendering the value without a link. A degraded render would look identical to a
  working one.
* **UI.** `<AuditLink>` renders beside every attributed value and deep-links to
  `/audit/<decision_log_id>` — which is the screen that makes the triplet worth
  carrying.

`decisionLogId` may be `null`, for batch-scored values that belong to no
decision. The link is then suppressed and the model still named. Fabricating an
id would put entries in the audit trail corresponding to no decision.

---

## Why there is no mock data

The adapter seam (`src/adapters/port.ts`) has two implementations: `GatewayAdapter`
(the real gateway) and `AbsentAdapter` (every method rejects with a
ticket-bearing error).

**There is deliberately no fixture adapter that returns plausible applications.**
A fixture adapter would put a score, a PD, an EMI and reason sentences on screen
— precisely the four things this phase exists to keep from being invented
client-side — and a screenshot of a demo build is indistinguishable from a
screenshot of a real one. This repository's posture throughout is that a
plausible number is worse than a missing one because it survives review; a
plausible *screen* is that failure with a wider audience, because screens are
what get shown to committees.

Master §2 rule 3 confines synthetic data to `tests/fixtures/`. If a clickable
demo is genuinely needed, the fixtures belong there behind an MSW or Playwright
harness mounted only by a test runner — a deliberate build step someone has to
take, which is the property that matters.

What `AbsentAdapter` gives instead is surfaces that exercise their loading, error
and unavailable states. Those are the states this system will be in for most of
its build, and they are the ones nobody designs.

---

## Layout

```
frontend/
  src/
    lib/gateway/
      provenance.ts    the {model_id, model_version, decision_log_id} contract as types
      types.ts         response shapes, each naming the Python dataclass it mirrors
      client.ts        the ONLY module that calls fetch; enforces the triplet at runtime
      endpoints.ts     one function per gateway call; each names its attributed paths
    lib/auth/session.ts  four roles -> capabilities; session timeout raises (LH-704)
    i18n/              copy keys (no English), registry interface, React seam
    adapters/          the port; GatewayAdapter and AbsentAdapter
    components/shared/ the 7 SRS §11.5 components — built once, never forked
    components/workbench/  unified case file, override control
    components/collections/ disposition form
    app/               App Router routes for all four surfaces
  scripts/check-no-client-math.mjs   the §8 do-not-invent rule as a build gate
  tests/contract/      WS-7.1.1 contract tests (never run)
```

### The seven shared components (SRS §11.5)

| Component | File | The interesting behaviour |
|---|---|---|
| Reason-code card | `ReasonCodeCard.tsx` | A null sentence renders the **code** and a pending-ratification state. It does not humanise the code — a de-underscored code reads as approved copy, so nobody files the ticket. |
| Evidence map + time-slider | `EvidenceMap.tsx` | A null polygon draws **no shape**. Not a centroid circle, not a district boundary "for context". Phase 2 §8's last do-not-invent entry. |
| Citation-linked chat bubble | `ChatBubble.tsx` | An uncited claim is **rendered**, marked unverified. Dropping it also hides that the claim was made. |
| Freshness badge | `FreshnessBadge.tsx` | `unknown` stays distinct from `stale`. `Panel` takes freshness as a required prop, so a panel without a badge does not compile. |
| Alert / subgraph viewer | `AlertViewer.tsx` | Owner, SLA, action and every trigger reason, no collapse, no truncation. `slaBreached` is a server field — the browser clock is not the bank's clock. |
| Consent & disclosure banner | `ConsentBanner.tsx` | Contains **no English at all**, including its own button label. An unratified document gets no accept control — not a disabled one, none. |
| Offer comparison table | `OfferComparisonTable.tsx` | No EMI computed, no total payable derived. Rejected offers shown with their binding constraint. The recommendation is marked, never pre-selected. |

---

## Getting it to run

Nothing below has been executed. It is the sequence a developer should expect to
work through, in order.

```bash
cd frontend
npm install          # will likely need version adjustment; there is no lockfile
npx tsc --noEmit     # EXPECT ERRORS. This is the first real signal.
npm run lint
npm run check:no-client-math
npm run dev
```

Realistic expectations for each step:

1. **`npm install`** — the versions in `package.json` were written without a
   registry to check them against. Pin whatever resolves and commit the lockfile.
2. **`npx tsc --noEmit`** — this is where the real work is. Every relative import
   path, every JSX shape and every type in `lib/gateway/types.ts` is unverified.
   Work through the errors before anything else; several will be genuine bugs
   rather than typos.
3. **`npm run check:no-client-math`** — the script has never executed. Its own
   regexes are unverified, so a failure may be the script rather than the code.
   Read `scripts/check-no-client-math.mjs`'s header before "fixing" a violation:
   the check is blunt by design.
4. **`npm run dev`** — every page will render its error state, because
   `NEXT_PUBLIC_GATEWAY_BASE_URL` is unset and `GatewayClient` refuses to invent
   a default. Set it to a stub server, or wire `AppProviders` to `AbsentAdapter`
   and confirm the error states render.

Then, before anything is shown to anyone:

5. **Run axe-core.** Every accessibility claim in this codebase is an intention.
6. **Write the contract tests' runner.** `tests/contract/attribution.contract.ts`
   exports its cases; there is no runner wired up.

### What must be built before this is useful

In dependency order:

1. **The gateway route contract (LH-706).** Every path in `endpoints.ts` is this
   client's *expectation*, not an agreed route. Nothing works until the gateway
   publishes an OpenAPI document and these are reconciled against it.
2. **The document registry (LH-701).** Until it exists every screen is
   placeholders. This is the single largest blocker to anything being shown.
3. **The override reason taxonomy (LH-702)** and **the action library and outcome
   codes (LH-502)** — without them the override control and the disposition form
   both refuse to render, which is correct and also means the two most important
   controls in the build are inert.

---

## Accessibility

Target: **WCAG 2.2 AA**, fixed by SRS UX-8 and not renegotiable per-surface
(Phase 7 §8). What was designed toward it:

* Visible focus indicator on every interactive element, never removed
  (2.4.11, 2.4.13 — the two criteria new in 2.2 that a 2.1-era codebase misses).
* Skip link as the first focusable element (2.4.1).
* Semantic tables with `<th scope>`, `<caption>`; `<dl>` for key-value panels.
* Tier and freshness states carry **text as well as colour** (1.4.1).
* Minimum 44px interactive targets (2.5.8 asks for 24px; 44px is the comfortable
  reading and costs nothing).
* `prefers-reduced-motion` respected — trivially, since there is no motion.
* `lang` is set from the resolved locale and defaults to `und`, not `en`.
  Mislabelling Hindi text as English makes a screen reader pronounce it with
  English phonemes, which is worse than the missing attribute.

**None of this is verified.** The independent audit Phase 7 §7 requires is
LH-710, and Master §3.1's independence argument applies: an accessibility audit
run by the team that wrote the components tests what they thought about rather
than what they missed.

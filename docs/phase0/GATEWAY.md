# The API gateway — what it serves, what it refuses, and how to run it

`src/lending_hub/gateway/` is the server half of the Phase 7 client contract
(WS-7.1.1, SRS §11.6a: *"All four surfaces call ONE API gateway — never an
underlying model service directly"*). `frontend/src/lib/gateway/client.ts` is the
other half and is the only module in the frontend that calls `fetch`.

It is a **Track A** implementation (ADR-0003): stdlib `http.server`, no
framework, no dependency, running on a laptop. Every response carries
`X-Track: A`, so a capture taken against it is identifiable as such.

---

## 1. The rule this gateway follows

A handler returns exactly one of two things, and there is no third branch:

1. A value some module under `src/lending_hub/` **computed**, from inputs the
   caller supplied.
2. A structured **refusal** naming the ticket that blocks it:
   `{status:"unavailable", capability, ticket, owner, reason}`.

There is no branch that returns a plausible score, PD, LGD, EAD, EMI, rate, fee,
eligibility amount, reason sentence, fraud score or alert precision that nothing
computed. `GET /v1/capabilities` reports `fabricatedValuesServed: 0`, and that
number is generated from the route table rather than asserted beside it.

This is the same refusal `frontend/src/adapters/port.ts` makes when it declines
to ship a fixture adapter, moved one layer in — and a gateway is the *worse*
place to fake a number, because a frontend fixture is visibly a fixture in the
diff while a gateway response is indistinguishable from a real one on the wire.

### Why the triplet does the work

`frontend/src/lib/gateway/provenance.ts` throws `MissingAttributionError` on any
response the client classifies model-derived that lacks
`{modelId, modelVersion, decisionLogId}`. That gives the gateway a property
worth stating plainly:

> It **cannot** serve a score without naming a model, because the client would
> refuse to render it.

So every model-derived route either has a real model behind it or returns
unavailable. Synthesising a triplet would forge a model identity — a worse lie
than the number it decorates, because the number is merely wrong while the id
sends an auditor to a model card describing something else.

No model artifact is fitted in this repository (P1/P3 ship stdlib ports with no
trained weights committed; ADR-0013 for P2, ADR-0015 for P5, ADR-0016 for P6).
**Every model-derived route therefore returns unavailable today.** That is
enforced by `routes.audit_routes()` invariant R1, which runs at server startup
and is pinned by `tests/test_gateway_routes.py`. When a model *is* fitted, R1
must be **changed** — to "returns a triplet naming a registered artifact" —
rather than deleted, and having it fail loudly is the point.

---

## 2. Served from real computation — 4 routes

None is classified model-derived, and that is not a coincidence: Louvain is an
algorithm, the DR estimator is an estimator, the cadence table is a
transcription, and `emi` is a formula. None came from a fitted model, so none
carries an attribution triplet — and each names the function that produced it in
a `computedBy` field, which is the audit trail available to a value with no
model card.

Each calls an existing reference implementation and formats the result. None
recomputes anything (Master §2 rule 2).

| Route | Computed by | What it is |
|---|---|---|
| `POST /v1/quotes/instalment` | `reco.feasible.emi` / `total_interest` | A real EMI and total interest from a caller-supplied principal, rate and tenor. |
| `POST /v1/graph/communities` | `learning.graph.louvain` / `score_communities` | Real community detection on a posted entity graph, with modularity, per-community entropy and internal density. |
| `POST /v1/learning/offpolicy` | `learning.offpolicy.evaluate_policy` | A real doubly-robust estimate over a caller-supplied action log, with its positivity report and confidence interval. |
| `POST /v1/learning/cadence` | `learning.cadence.overdue` / `runnable` | The WS-6.7 schedule evaluated against caller-supplied last-run dates. |

### The instalment quote is not an eligibility, and that is the whole point

`POST /v1/quotes/instalment` answers *"what is the instalment on this principal,
at this rate, over this tenor"* — arithmetic, fully determined by three inputs,
with no policy in it. It does **not** answer *"may this borrower have this
loan"*, which needs FOIR/DSCR/LTV caps (LH-504), and it does **not** answer
*"what rate applies"*, which needs ALM pricing (LH-505).

So the caller supplies the rate. That is a deliberate shape: a gateway that
looked up a rate would be serving a price nobody ratified, and one that
defaulted a rate would be worse. The response carries
`feasibilityAssessed: false` and a note saying so, and
`GET /v1/applications/{id}/offers` — the endpoint that would decide both —
returns unavailable.

`annualRate` is a **decimal** (`0.125`, not `12.5`). Values ≥ 1.0 are refused:
sending `12.5` returns correct arithmetic for a 1250% rate, which is nonsense as
an answer and is exactly the kind of plausible-looking number this repository
exists to keep off a screen.

### The refusals inside the computed routes

Two of these four carry a refusal *within* a successful response, which is the
honest shape when part of a computation is groundable and part is not:

* `/v1/graph/communities` returns per-community entropy and density, and reports
  `fraudLabelDensity` as unavailable (LH-810). WS-6.1's scorer names two inputs;
  one needs fraud-desk dispositions that do not exist. Scoring on entropy alone
  would rank communities plausibly and would not be the scorer the workstream
  specifies.
* `/v1/learning/offpolicy` returns `verdict: null`. LH-804 is that *"only
  positive-DR-estimate policies proceed"* is a sign test on a point estimate
  whose interval may span zero, so the response reports the estimate, the
  standard error **and** the interval, and declines to turn them into a decision.

`/v1/learning/cadence` requires `graceDays` and `shippedPhases` with no
defaults, mirroring `cadence.overdue`. LH-807 is precisely that the WS-6.7 table
gives intervals and no tolerances; a default here would silently become the
programme's tolerance without anyone ratifying it.

---

## 3. Unavailable — 17 routes

Each returns HTTP **200** with a ticket and an owner. A 200, not a 5xx: an
unratified FOIR cap is not a server fault, and rendering it as one puts a
governance stop in the same bucket as a crashed process. Phase 3's *not measured
/ not measurable* distinction is the same argument one layer up — two states in
one column means the second never gets escalated.

| Route | Ticket | Owner |
|---|---|---|
| `GET /v1/workbench/queue` | LH-120 | Named source owners |
| `GET /v1/workbench/cases/{applicationId}` | LH-706 | Platform (API gateway squad) |
| `GET /v1/workbench/override-reasons` | LH-702 | Model Risk + Credit Policy |
| `POST /v1/workbench/decisions/{decisionId}/override` | LH-702 | Model Risk + Credit Policy |
| `GET /v1/audit/{decisionLogId}` | LH-706 | Platform (API gateway squad) |
| `GET /v1/collections/alerts` | LH-502 | Collections Head |
| `GET /v1/collections/alerts/{alertId}` | LH-502 | Collections Head |
| `GET /v1/collections/outcome-codes` | LH-502 | Collections Head |
| `GET /v1/collections/actions` | LH-502 | Collections Head |
| `POST /v1/collections/alerts/{alertId}/disposition` | LH-502 | Collections Head |
| `GET /v1/dashboards/{dashboardId}/panels` | LH-703 | Data Platform + Risk Reporting |
| `GET /v1/applications/{applicationId}/decision` | LH-706 | Platform (API gateway squad) |
| `GET /v1/applications/{applicationId}/offers` | LH-504 | Credit Policy |
| `GET /v1/documents/{documentId}` | LH-701 | Compliance + Content Ops |
| `POST /v1/consents` | LH-112 | Compliance |
| `POST /v1/applications/{applicationId}/document-checks` | LH-120 | Named source owners |
| `GET /v1/assistant/conversations/{conversationId}` | LH-601 | Product SMEs + Compliance |

### The three kinds of block, which are not interchangeable

* **No ratified policy value** — LH-504 (caps), LH-502 (action library and
  outcome codes), LH-702 (override taxonomy), LH-703 (freshness tolerances),
  LH-701 (copy registry), LH-112 (consent wording). A committee can close these
  tomorrow.
* **No data** — LH-120 (data-sharing approvals), LH-601 (document corpus). Time
  and collection close these; no decision does.
* **No fitted model** — LH-706 on the routes the client marks `modelDerived`.
  This is the kind that makes `fabricatedValuesServed: 0` true.

Worth noticing: `GET /v1/workbench/queue` is **not** model-derived and is still
blocked — on data. A reader who assumed the absence of a fitted model was the
only thing stopping this gateway would expect the queue to work.

---

## 4. Auth — what is checked, and what is not

Every route except `GET /v1/health` requires **both** headers:

```
Authorization: Bearer <token>
X-Acting-Role: <customer | officer | risk-viewer | collections-agent>
```

The four roles are `[SPEC]` (Phase 7 §4 WS-7.1.3). A request missing either
header, or carrying a role outside that set, gets a **401**.

**The token is never verified.** There is no identity provider to verify it
against (LH-120). The header check makes the client's unauthenticated path real;
it is not authentication. Every response says so in `X-Auth-Verified: false`,
and `GET /v1/capabilities` says so in its body. This gateway is not deployable —
it also has no TLS, no rate limiting, and no idempotency store that survives a
restart.

`GatewayClient` sends both headers from the `Session`, so an adapter built
without a session cannot make a call at all. That is WS-7.1.3's role-scoping
expressed as a construction requirement rather than a runtime check.

CORS allows **one** origin, `http://localhost:3000` by default. A wildcard is
rejected by the CLI: it would let any page a developer has open call the gateway
with their session, and on a Track B build the same code path would do it with
real bureau data.

---

## 5. Running the two together

Two terminals from the repository root.

**Terminal 1 — the gateway** (port 8787, CORS `http://localhost:3000`):

```bash
make serve
```

Overrides go through `ARGS`, e.g. to run on 8080 instead:

```bash
make serve ARGS="--port 8080"
make serve ARGS="--port 8080 --origin http://localhost:3000"
```

It prints what it is serving on startup:

```
gateway (Track A) on http://127.0.0.1:8787  CORS: http://localhost:3000
  4 route(s) served from real computation
  17 route(s) unavailable, each with a ticket
  auth is NOT verified (LH-120); route contract is unratified (LH-706)
  GET /v1/capabilities for the full list
```

**Terminal 2 — the frontend** (port 3000):

```bash
cd frontend
NEXT_PUBLIC_GATEWAY_BASE_URL=http://localhost:8787 \
NEXT_PUBLIC_DEV_SESSION_ROLE=officer \
npm run dev
```

**Both variables are required, and the second is easy to miss.**
`selectAdapter` returns `AbsentAdapter` unless a gateway URL is configured *and*
a session exists, so with only the first set the gateway runs, answers, and is
never called — the wiring is complete and inert. `NEXT_PUBLIC_DEV_SESSION_ROLE`
supplies the local session (`adapters/devSession.ts`); valid values are
`officer`, `customer`, `risk-viewer`, `collections-agent`.

That session is **not authentication and not a fixture**. It carries a role so
role-scoped routes can be exercised and produces no data of any kind; the
gateway does not verify bearer tokens either (`authVerified: false`). It is
guarded twice — `NODE_ENV === "production"` yields `null`, and an unset role
yields `null` — so a production build cannot pick it up. Real session
establishment is LH-714.

Two things worth knowing, both found by running it:

- **Use port 3000.** CORS allows one origin at a time and defaults to
  `http://localhost:3000`. On any other port the preflight succeeds and the
  real request is blocked by the browser, which presents as `Failed to fetch`
  with no server-side error. Pass `--origin` if you need a different port.
- **`npm run dev`, not `npm run build && npm start`.** `next build` sets
  `NODE_ENV=production`, so the dev session is `null` by design and the app
  falls back to `AbsentAdapter`.

The gateway URL has **no default** on either side. `client.ts` refuses to invent an
origin (*"a lending client that falls back to a built-in host is a client that
can be pointed at the wrong environment silently"*), and `adapters/http.ts` reads
the same variable so the two cannot disagree about whether a gateway exists.

Without it, the frontend runs against `AbsentAdapter` exactly as before — every
call rejected with a ticket-bearing `BackendAbsentError`. **That remains the
default**, and pointing at a backend stays a deliberate act.

### Checking it by hand

```bash
curl localhost:8787/v1/health

AUTH=(-H "Authorization: Bearer dev" -H "X-Acting-Role: officer")

# what is served and what is blocked
curl -s "${AUTH[@]}" localhost:8787/v1/capabilities | python3 -m json.tool

# a real EMI — note the DECIMAL rate
curl -s "${AUTH[@]}" -H 'Content-Type: application/json' \
  -d '{"amount":500000,"annualRate":0.12,"tenorMonths":60}' \
  localhost:8787/v1/quotes/instalment

# a refusal, with its ticket
curl -s "${AUTH[@]}" localhost:8787/v1/applications/APP-1/offers
```

---

## 6. How the frontend renders a refusal

The distinction the gateway draws is only worth drawing if the client preserves
it, and preserving it took three pieces:

* `lib/gateway/unavailable.ts` — `CapabilityUnavailableError`, deliberately
  **not** a `GatewayError` subclass. The screens branch on `instanceof`, and
  inheritance would put every governance stop back in the red alert box the
  first time someone wrote the obvious catch.
* `lib/gateway/useLoad.ts` — one load hook returning
  `loading | ready | unavailable | error`, so the branch is written once rather
  than eight times.
* `components/shared/UnavailableNotice.tsx` — the neutral dashed frame
  `UnifiedCaseFile`'s `CasePanel` already uses for the same state, showing the
  reason, the ticket and the owner. No retry affordance: retrying does not
  ratify a policy value.

**One ordering detail is load-bearing.** The refusal check in `client.ts` runs
*before* `enforceAttribution`. A refusal carries no score and therefore no
triplet, so the attribution guard would otherwise report *"the backend dropped
decision_log_id"* for a response whose actual message is *"Credit Policy has not
ratified LH-504"* — a wrong diagnosis, which sends someone to the gateway team,
who find their gateway working correctly.
`testUnavailableIsNotAnAttributionFailure` in
`frontend/tests/contract/attribution.contract.ts` pins it.

---

## 7. Tests

```bash
make check                   # 2318 tests, includes the gateway suites
cd frontend && npm run verify # typecheck, lint, no-client-math, 10 contract tests
```

* `tests/test_gateway_contract.py` — the two answer types. An attribution cannot
  be built without a real model behind it; a refusal cannot be built without a
  ticket and an owner; both survive `to_json` intact.
* `tests/test_gateway_routes.py` — the table's invariants, including R1 (no
  model-derived route serves a payload) and R2 (no route the client never
  calls). R1 is checked by *calling* each handler rather than by reading its
  module, so a handler moved between `blocked` and `computed` cannot slip past.
  Both invariants are also asserted to *fail* on a deliberately broken table: a
  guard never seen to fire is indistinguishable from one that cannot.

## 8. What is not ratified

The route table itself. LH-706 asks for the published gateway contract; every
path here is read off `frontend/src/lib/gateway/endpoints.ts`, which declares
itself provisional for the same reason. The client and the server currently
agree because one was written from the other, not because anyone published a
contract for both to be right about.

# AI-Powered Smart Lending Decision Hub

An integrated lending platform for agriculture-based customers — satellite, weather and
crop intelligence, AI credit scoring, fraud detection, a loan recommendation engine,
default prediction, a GenAI assistant, real-time risk dashboards, and early warning for
defaulters.

Built for the **TVS Credit EPIC 8.0 IT Challenge**.

| | |
|---|---|
| **Phases** | 8 (P0 platform → P7 interfaces), all built |
| **Backend** | 21 packages · ~40,700 lines · standard-library Python only |
| **Frontend** | Next.js + TypeScript · 46 files · ~6,700 lines |
| **Tests** | 2,331, green on every commit |
| **Real data** | 16.8M mortgage performance rows · 150,000 credit applications |
| **Open tickets** | 98, each with a named owner and the decision required |
| **Findings** | 82 raised against the specification while building |

---

## The one idea this project is built on

A credit score is easy to produce. **Knowing whether you are allowed to believe it is the
hard part.**

A plausible-looking cutoff that nobody ratified survives code review, ships, and is still
in a report a year later. An agri model validated on the wrong agro-zone looks identical
to one validated correctly. A default model scored on the window it was trained on
reports excellent numbers and fails in production.

So every number in this repository must trace to exactly one of three sources:

| Source | Meaning |
|---|---|
| `[SPEC]` | Written in the specification — a formula, a threshold the document fixes |
| `[DATA]` | Computed by a committed, rerunnable script |
| `[POLICY: owner]` | Supplied in writing by a named committee |

**A value in none of the three makes the code raise, not default.** `make grounding`
scans 350 files on every commit and fails the build on an ungrounded value or a
malformed placeholder. That check is [tools/check_grounding.py](tools/check_grounding.py),
and it is why the rule is real rather than aspirational.

The consequence shows up everywhere. `expected_income()` raises without ratified input
costs, because on a smallholder plot those costs decide the *sign* of the answer.
`VillageLocation.area_hectares` raises rather than returning a nominal area around a
centroid. `Reward.blended()` raises without a ratified weight, because a bandit rewarded
on take-up alone learns to offer the largest permitted loan to whoever is likeliest to
accept it.

---

## Three tracks, and only one is evidence

This repository has no bank attached to it. Pretending otherwise is the easiest way to
produce a number that looks like evidence and is not. So every deliverable is built on
three tracks against one interface, and **every figure in every report is stamped with
the track that produced it** ([ADR-0003](docs/adr/0003-two-track-execution-model.md)).

| Track | What it is | What it proves |
|---|---|---|
| **A** | Local reference — stdlib, synthetic fixtures | The code paths: joins, point-in-time correctness, serving, audit arithmetic |
| **P** | Public reference data — real loans, real applications | The code survives real missingness, class imbalance, sentinel encodings, key defects |
| **B** | Bank deployment — real backends behind the same ports | **The only track that is gate evidence** |

A join rate computed on fixtures is a test of the audit script. A Gini computed on US
consumer loans is a fact about US consumer lending. Both are useful; neither is a gate
number, and the reports say so on every line.

---

## Architecture

```
                        ┌──────────────────────────────────────────┐
   Customer app         │        Decision Orchestrator             │
   Officer workbench ──▶│           (API gateway)                  │
   Risk dashboards      │  one origin · attribution on every        │
   Collections console  │  model-derived response                  │
                        └───────────────┬──────────────────────────┘
                                        │
        ┌───────────────┬───────────────┼───────────────┬────────────────┐
        ▼               ▼               ▼               ▼                ▼
   ┌─────────┐   ┌───────────┐   ┌───────────┐   ┌───────────┐   ┌────────────┐
   │ scoring │   │   fraud   │   │ portfolio │   │ ews + reco│   │ assistant  │
   │   P1    │   │    P1     │   │    P3     │   │    P4     │   │     P5     │
   └────┬────┘   └─────┬─────┘   └─────┬─────┘   └─────┬─────┘   └──────┬─────┘
        │              │               │               │                │
        └──────────────┴───────┬───────┴───────────────┴────────────────┘
                               ▼
              ┌────────────────────────────────────┐
              │  Platform (P0)                     │
              │  definitions · registry · lakehouse│
              │  identity · streaming · featurestore│
              │  mlops · privacy · decisionlog     │
              └────────────────────────────────────┘
                               ▲
                               │
                    ┌──────────┴───────────┐
                    │  agri (P2)  learning │
                    │             (P6)     │
                    └──────────────────────┘
```

**The core is standard-library Python throughout.** Every algorithm is a reference port
that names the library it replaces in its docstring, so a bank swaps in LightGBM,
lifelines, splink or scikit-survival behind the same interface without touching a call
site. Only PyYAML is required beyond stdlib, and only for the config validators.

### Packages

| Package | Phase | What it does | Lines |
|---|---|---|---|
| [`definitions`](src/lending_hub/definitions/) | P0 | Frozen definitions as importable constants — never retyped | 571 |
| [`registry`](src/lending_hub/registry/) | P0 | Source-registry loader and schema validation | 408 |
| [`lakehouse`](src/lending_hub/lakehouse/) | P0 | Bronze/Silver/Gold contracts, GL reconciliation | 319 |
| [`identity`](src/lending_hub/identity/) | P0 | Identity spine, survivorship, join audit | 756 |
| [`streaming`](src/lending_hub/streaming/) | P0 | Event schemas + backward-compatibility checker | 247 |
| [`featurestore`](src/lending_hub/featurestore/) | P0 | Feature definitions and point-in-time join | 453 |
| [`mlops`](src/lending_hub/mlops/) | P0 | Registry ports, promotion gate, reproducibility triplet | 440 |
| [`privacy`](src/lending_hub/privacy/) | P0 | Tokenisation, consent artifacts, retention | 433 |
| [`decisionlog`](src/lending_hub/decisionlog/) | P0 | Decision-log schema and replay | 413 |
| [`serving`](src/lending_hub/serving/) | P0 | Orchestrator, policy bands, shadow/canary, parity | 1,245 |
| [`sources`](src/lending_hub/sources/) | P0 | Track P dataset adapters | 1,632 |
| [`scoring`](src/lending_hub/scoring/) | **P1** | WoE scorecard, GBM, calibration, SHAP, fairness, rejects | 6,342 |
| [`fraud`](src/lending_hub/fraud/) | **P1** | Entity resolution, velocity, anomaly, documents, routing | 2,464 |
| [`agri`](src/lending_hub/agri/) | **P2** | SPI/SPEI drought, vegetation indices, plot registry, yield | 4,540 |
| [`portfolio`](src/lending_hub/portfolio/) | **P3** | PD/LGD/EAD, Cox, discrete hazard, IFRS 9 staging | 6,436 |
| [`ews`](src/lending_hub/ews/) | **P4** | Signals, velocity, BOCPD change-point, alert routing | 2,940 |
| [`reco`](src/lending_hub/reco/) | **P4** | Feasible set, ALM pricing, LinUCB bandit, suitability | 1,674 |
| [`assistant`](src/lending_hub/assistant/) | **P5** | Registry, chunking, hybrid retrieval, answer validator | 5,005 |
| [`learning`](src/lending_hub/learning/) | **P6** | Promotion gate, uplift, off-policy evaluation, Louvain | 2,276 |
| [`gateway`](src/lending_hub/gateway/) | **P7** | The HTTP API gateway serving the interface surfaces | 1,761 |
| [`modeling`](src/lending_hub/modeling/) | P0 | Shared metrics and the reference logistic model | 536 |

---

## What each module does

### Module 1 — Agricultural intelligence (`agri`, P2)

SPI and SPEI drought indices against the reference test the specification mandates,
NDVI/EVI pipelines with cloud masking, backscatter, the plot registry, credit-feature
formulas and three backtests.

**Three models ship as contracts, not weights** — field delineation, crop classification
and yield estimation are fine-tuned networks with no imagery to fit and no labels to fit
against ([ADR-0013](docs/adr/0013-phase2-agri-track.md)). What is built is each model's
metric, gate, calibration, abstention rule and the baseline it must beat, which is where
most of the risk lives.

The refusals are the design. A plot polygon that was never observed or walked is never
drawn — a circle around a village centroid is a plausible map of a survey nobody did.

### Module 2 — Credit scoring (`scoring`, P1)

Target definition → splits → features → optimal binning → WoE scorecard → GBM challenger
→ calibration → SHAP explanations → reason codes → fairness audit → reject inference →
validation. Stdlib ports of OptBinning, LightGBM, SHAP and Fairlearn, each stating in its
docstring what it deliberately does *not* port.

### Module 3 — Fraud detection (`fraud`, P1)

Four layers, ordered by what each needs rather than by sophistication: deterministic
rules and unsupervised anomaly run on day one; the graph layer runs on real graphs today
because community detection is unsupervised; supervised and camouflage-resistant models
need 18 months of desk dispositions that do not exist yet.

### Module 4 — Loan recommendation (`reco`, P4)

Feasible set → ALM-based pricing → LinUCB contextual bandit → suitability. A
`BanditDecision` **cannot be constructed without a propensity**, which makes off-policy
evaluation possible later by construction rather than by discipline.

### Module 5 — Default prediction (`portfolio`, P3)

PD via discrete-time hazard and Cox models over a monthly account panel, LGD in two
stages, EAD, IFRS 9 staging, macro overlays, transition matrices and portfolio
aggregates. Fitted on a real 19-year mortgage panel.

### Module 6 — GenAI assistant (`assistant`, P5)

Document registry with effective-date filtering, structure-aware chunking, BM25 + dense
hybrid retrieval with reciprocal-rank fusion, the answer contract, guardrails and the
golden-set harness.

**No LLM is called anywhere and no corpus is fabricated**
([ADR-0015](docs/adr/0015-phase5-assistant-track.md)). What holds instead is structural:
`ValidatedAnswer` is the only servable type and cannot be constructed holding an uncited
numeric claim, so the leak rate is zero by construction rather than by weekly audit.

### Module 7 — Risk dashboards (`portfolio` + P7 surfaces)

Portfolio overview, vintage and roll-rate, concentration, model health, scenarios and
drill-through — rendered from metrics the backend computes. The UI reimplements no metric
logic, and a freshness badge sits on every panel.

### Module 8 — Early warning (`ews`, P4)

Signal catalogue, velocity features, Bayesian online change-point detection, agri
triggers, alert routing and the backtest. An `Alert` cannot be constructed without an
owner, an SLA and a recommended action, because an alert missing any of the three is a
notification and the difference stops being visible once it is in a queue.

---

## Results on real public data

Two pipelines run end to end on real datasets. **These are Track P numbers: real loans
and real missingness, but not this bank's book — evidence about the implementation, not
gate evidence.**

### Credit scoring — 150,000 real applications

| Model | Test Gini | Test AUC | Train Gini |
|---|---|---|---|
| WoE scorecard (champion) | 46.86 | 0.7343 | 46.35 |
| GBM (challenger) | 51.94 | 0.7597 | 57.79 |

The GBM's train-test gap is reported rather than tuned away — a challenger whose train
and test numbers match exactly has usually been fitted to its own test set.

### Default prediction — 16.8M rows, 338,210 account-months

| Model | Metric | Value |
|---|---|---|
| Cox proportional hazards | c-index | 0.6967 |
| Discrete-time hazard | AUC | 0.6127 |
| Survival calibration | Integrated Brier | 0.0902 |

### Early warning — does deterioration precede default?

Scored against the 101 defaults the detector could actually have reached:

| Threshold | Capture | Median lead time | Accounts alerted |
|---|---|---|---|
| p90 | 91.1% | 562 days | 917 |
| **p95** | **86.1%** | **365 days** | 641 |
| p98 | 82.2% | 183 days | 433 |
| p99 | 56.4% | 153 days | 330 |

The curve is the operating decision, and it belongs to the Collections Head.

---

## Status, stated plainly

**Zero of thirty-one exit criteria have gate evidence.** Every phase gate reports
`Track B evidence: 0`, because Track B is a bank deployment and there is no bank
attached. Saying so is the point.

| Phase | Gate evidence | Open tickets | Findings |
|---|---|---|---|
| P0 platform | — | 13 | — |
| P1 scoring & fraud | 0 of 8 | 10 | 14 |
| P2 agri | 0 of 6 | 13 | 14 |
| P3 portfolio | 0 of 6 | 11 | 14 |
| P4 EWS & reco | 0 of 5 | 13 | 11 |
| P5 assistant | 0 of 6 | 12 | 9 |
| P6 learning loops | standing criterion | 11 | 7 |
| P7 interfaces | 0 | 15 | 13 |

### Three gate states, not two

- **Not measured** — the job has not run. A scheduling problem.
- **Not measurable** — no reachable data produces it. A sourcing problem.
- **Unidentifiable** — no quantity of data produces it. A design problem.

Reporting all three in one column puts a scheduling problem beside a structural one, and
the structural one never gets escalated. The third state is Phase 6's contribution: uplift
from an unrandomised log is not a *worse* estimate, it is a different quantity, and more
data narrows the interval around the wrong number.

---

## Running it

No install step is needed for the core checks.

```bash
make check          # grounding + registry + 2,331 tests  (~30s)
make help           # every target
```

### See the engines compute

```bash
make demo5                      # the assistant's controls, on text you supply
make demo5 ARGS="--text 'You qualify for 5 lakh at 9.9% interest.'"
make demo6                      # the Phase 6 computations, and the refusals
make demo6 ARGS=uplift          # then --observational, to see it refuse
```

### Run the full app

```bash
# terminal 1 — the API gateway
make serve

# terminal 2 — the interfaces
cd frontend
env NEXT_PUBLIC_GATEWAY_BASE_URL=http://localhost:8787 \
    NEXT_PUBLIC_DEV_SESSION_ROLE=officer \
    npm run dev
```

Open **http://localhost:3000**. Nine surfaces: officer workbench, collections console,
risk dashboards, customer decision and offers, the assistant, and module pages for agri,
fraud and default prediction.

> Use port 3000 — the gateway allows one CORS origin at a time. Use `npm run dev`, not a
> production build: `next build` sets `NODE_ENV=production`, which nulls the development
> session by design and falls back to the refusing adapter.

### Real numbers from real data

```bash
make trackp-p1      # WS-1.1 on 150,000 real applications
make trackp-p3      # WS-3.1/3.2 on a 19-year mortgage panel
make trackp-p4      # does deterioration precede default?
make gate1 … gate6  # the evidence packs, generated never hand-written
```

These need `datasets/`, which is gitignored — see
[docs/phase0/DATA_SOURCING.md](docs/phase0/DATA_SOURCING.md). Everything else runs on a
clean clone.

---

## What building it found

82 findings raised against the specification. Building against a document is the only
reliable way to test it — each finding is a place where the spec read as complete until
code had to produce a number.

| Finding | What it revealed |
|---|---|
| **P4-F1** | The change-point instruction names a quantity that is *identically the hazard rate* under constant hazard. It detects nothing, on any data — the real signal is one index over. |
| **P6-F1** | Uplift from observational logs is *unidentifiable*, not merely unmeasured. More data narrows the interval around a biased number, turning visible uncertainty into invisible bias. |
| **P7-F1** | The frontend phase cites SRS §11.4–§11.8 and UX-1…UX-9 as binding. **None exists.** The screen inventory it depends on is unrecoverable. |
| **P5-F2** | Effective dates cannot express partial supersession — two circulars in force, one amending the other in part. Both pass the filter; the model picks. |
| **P4-F11** | A correction to our own first result: capture was scored against defaults the detector could never have reached, measuring the train/test split rather than the model. |

Full sets: [P0](Lending_Hub_Phase_Docs/Phase_0_FINDINGS.md) ·
[P1](Lending_Hub_Phase_Docs/Phase_1_FINDINGS.md) ·
[P2](Lending_Hub_Phase_Docs/Phase_2_FINDINGS.md) ·
[P3](Lending_Hub_Phase_Docs/Phase_3_FINDINGS.md) ·
[P4](Lending_Hub_Phase_Docs/Phase_4_FINDINGS.md) ·
[P5](Lending_Hub_Phase_Docs/Phase_5_FINDINGS.md) ·
[P6](Lending_Hub_Phase_Docs/Phase_6_FINDINGS.md) ·
[P7](Lending_Hub_Phase_Docs/Phase_7_FINDINGS.md)

---

## Repository map

```
docs/SRS.md                  The Software Requirements & Algorithm Design Document
                             — rank 1, every §-reference points here
CLAUDE.md                    The working agreement — grounding rules, conventions
CONTRIBUTING.md              Day-to-day workflow, commit format, review gates
Lending_Hub_Phase_Docs/      The master implementation guide + 8 phase files + findings

src/lending_hub/             21 packages (see Architecture above)
frontend/                    Next.js interface surfaces
tools/                       CI gates: grounding, registry, schema compatibility,
                             seven gate-report generators, the deck builder
config/                      Source registry, retention, reason codes, policy bands
docs/adr/                    Architecture decision records
docs/phase0…7/               STATUS, blocking tickets, model cards per phase
tests/                       88 test modules, 2,331 tests
reports/                     Generated gate packs and Track P results
datasets/                    Real external data — gitignored, never committed
```

### Start here

| You want to | Read |
|---|---|
| The design intent and algorithms | [docs/SRS.md](docs/SRS.md) |
| The rules every contributor follows | [CLAUDE.md](CLAUDE.md) |
| What is done and what is blocked | [P6](docs/phase6/STATUS.md) · [P5](docs/phase5/STATUS.md) · [P4](docs/phase4/STATUS.md) · [P3](docs/phase3/STATUS.md) · [P2](docs/phase2/STATUS.md) · [P1](docs/phase1/STATUS.md) · [P0](docs/phase0/STATUS.md) |
| Why a phase was not followed literally | The FINDINGS files above |
| What is waiting on a committee | [docs/phase*/blocking_tickets.md](docs/phase4/blocking_tickets.md) |
| What a model may and may not be used for | [docs/phase*/model_cards/](docs/phase4/model_cards/) |
| How to run the gateway with the frontend | [docs/phase0/GATEWAY.md](docs/phase0/GATEWAY.md) |

---

## Why this approach

Lending is a regulated activity. A number on a screen becomes a number in a complaint, a
number in an audit, and a number in front of a regulator.

This build is engineered so that every one of those numbers traces to the script that
produced it — or does not appear at all. The 98 open tickets are not a backlog of missing
work; they are the honest project plan, naming exactly what a bank must decide before any
of this scores a real customer.

Nothing has to be unpicked later because someone guessed. The guesses were never made.

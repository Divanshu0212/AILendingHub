# AI-Powered Smart Lending Decision Hub

An integrated lending platform for agriculture-based customers — satellite, weather and
crop intelligence, AI credit scoring, fraud detection, a loan recommendation engine,
default prediction, a GenAI assistant, real-time risk dashboards, and early warning for
defaulters.

Built for the **TVS Credit EPIC 8.0 IT Challenge**.

| | |
|---|---|
| **Phases** | 8 (P0 platform → P7 interfaces), all built |
| **Backend** | 21 packages · ~41,500 lines · standard-library Python only |
| **Frontend** | Next.js + TypeScript · 48 files · ~8,100 lines |
| **Tests** | 2,331, green on every commit |
| **Real data** | 16.8M mortgage rows · 307,511 applications · 590,540 card transactions · 1,173 crop tiles |
| **Open tickets** | 98, each with a named owner and the decision required |
| **Findings** | 82 raised against the specification while building |
| **Models trained** | 19 across 4 families, on real public data |

---

## Contents

**Understanding it** — [The one idea](#the-one-idea-this-project-is-built-on) ·
[Three tracks](#three-tracks-and-only-one-is-evidence) ·
[Architecture](#architecture) · [The eight modules](#what-each-module-does)

**The evidence** — [Results](#results-on-real-public-data) ·
[Datasets and their limits](#the-datasets-and-what-each-cannot-support) ·
[How the models were trained](#how-the-models-were-trained) ·
[Status](#status-stated-plainly)

**Working on it** — [Running it](#running-it) ·
[What building it found](#what-building-it-found) ·
[Design decisions](#the-decisions-that-shaped-this) ·
[Repository map](#repository-map)

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
| Seven-model ensemble | **55.94** | **0.7797** | — |

The GBM's train-test gap is reported rather than tuned away — a challenger whose train
and test numbers match exactly has usually been fitted to its own test set.

### Default prediction — 16.8M rows, 338,210 account-months

| Model | Metric | Value |
|---|---|---|
| Cox proportional hazards | c-index | 0.6967 |
| Discrete-time hazard | AUC | 0.6127 |
| Survival calibration | Integrated Brier | 0.0902 |
| Behavioural PD, 12-month horizon | test AUC | **0.8818** |

The behavioural model is **not** comparable to the Cox c-index above it: that
c-index covers a 48-month forward window on 1,400 subjects, this AUC a 12-month
window on 230,543. Different horizons and different cohorts, so no lift is
claimed between them.

### Fraud detection — 590,540 real card transactions

| Model | OOF AUC | Time |
|---|---|---|
| LightGBM | 0.95553 | 34 min |
| XGBoost | 0.95421 | 73 min |
| CatBoost | 0.95081 | 184 min |
| **Three-model stack** | **0.95638** | — |

What a review desk would actually see, which is the number that decides staffing:

| review budget | fraud caught | precision | false alerts |
|---|---|---|---|
| top 0.5% | 14.1% | 98.4% | 46 |
| **top 1%** | **27.6%** | **96.4%** | **211** |
| top 2% | 51.3% | 89.8% | 1,204 |
| top 5% | 74.1% | 51.9% | 14,214 |

False alerts are customers stopped wrongly, which is why the alert budget is a
business decision (LH-206) rather than a modelling one.

### Crop classification — 147,409 labelled pixels, 6 classes

| Metric | Value |
|---|---|
| macro-F1 | **0.5225** |
| weighted F1 | 0.6546 |
| accuracy, labelled pixels | 0.6645 |
| per-class F1 | 0.02 · 0.65 · 0.53 · 0.45 · 0.72 · 0.78 |

Macro-F1 rather than accuracy, because labels are sparse and imbalanced 23×: a
model predicting the majority class everywhere scores 99.76% pixel accuracy and
near-zero macro-F1.

Five of six classes work. The sixth is **1.7% of the training pixels and the
model effectively cannot find it** — 583 of its 818 test pixels are called class
2 and 225 class 4. That is a data limit rather than a tuning one: on single-date
imagery those classes are not spectrally separable, and no reweighting invents
a distinction the pixels do not carry. Multi-date imagery would, because crops
separate by *when* they green up rather than by colour on one day.

For context, published AgriFieldNet baselines sit near 0.30–0.45 macro-F1. This
is above them and well short of solved.

---|---|
| macro-F1 | **0.5071** |
| weighted F1 | 0.6189 |
| accuracy, labelled pixels | 0.6151 |
| per-class F1 | 0.045 · 0.68 · 0.494 · 0.416 · 0.66 · 0.748 |

Macro-F1 rather than accuracy, because labels are sparse and imbalanced 23×: a
model predicting the majority class everywhere scores 99.76% pixel accuracy and
near-zero macro-F1. The weakest class has 2,545 training pixels and the model
essentially fails on it — reported rather than averaged away.

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

## The datasets, and what each cannot support

Four real datasets, none of them a bank's own book. Each is listed with the
limit that matters, because a dataset's ceiling is a property of the data rather
than of the model fitted to it.

| Dataset | What it is | What it cannot support |
|---|---|---|
| **Home Credit** | 307,511 loan applications with repayment outcomes, plus credit-bureau and repayment-history tables | Consumer credit, not agricultural. The label is the publisher's definition of *payment difficulty*, not Appendix A's default — so a Gini here is not a Gini on this bank's target. |
| **Fannie Mae** | 16.8M monthly performance rows, 19 years, 230,543 accounts scored | US mortgages. Real censoring, real seasoning, a real crisis in the middle — but a different product, a different economy, and a secured loan where the collateral is a house. |
| **IEEE-CIS** | 590,540 card transactions, 3.5% fraud, six months, 394 raw features | E-commerce card fraud, not loan fraud. The **graph structure** transfers — shared device, address, email domain — the fraud patterns do not. |
| **AgriFieldNet** | 1,173 Sentinel-2 tiles over four Indian states, 147,409 GPS-walked labelled pixels | Real Indian farmland with real ground truth, and **single-date imagery**. Crops separate by *when* they green up; one date caps what any model can distinguish. |

A fifth dataset — Crops3D, 1,180 laser-scanned plant point clouds — was
evaluated and **not used**. It answers "what shape is this plant", which needs a
scanner a metre from the crop. The lending question is "what is growing on this
plot", answered from orbit. The two share no input space, so nothing transfers
between them.

---

## How the models were trained

Nineteen models across four families. Every harness lives in `tools/`, writes to
its own report, and **overwrites no committed run** — a tuning script that
clobbers its baseline makes "we improved the model" unfalsifiable.

### The four harnesses

| Script | Family | Models | What it fits |
|---|---|---|---|
| [`train_ensemble.py`](tools/train_ensemble.py) | Credit scoring | 7 | LightGBM ×3, XGBoost ×2, random forest, extra trees |
| [`train_survival.py`](tools/train_survival.py) | Behavioural PD + EWS | 5 | LightGBM ×2, XGBoost, histogram GB, random forest |
| [`train_fraud.py`](tools/train_fraud.py) | Card fraud | 3 | XGBoost, LightGBM, CatBoost |
| [`train_crop.py`](tools/train_crop.py) | Crop classification | 4 | LightGBM, XGBoost, random forest, extra trees |

### Four decisions that shaped every result

**Splits match the data's shape, never the default.** The credit and fraud
models split by time — fraud folds by calendar month, so a model never sees a
transaction from the month it is scored on. The behavioural model splits by
*account*, with features from months at or before an observation point and
labels strictly after. A random split of a panel puts an account's later months
in train and its earlier months in test, which leaks the outcome backwards and
produces an excellent number that means nothing.

**Blends are fitted out-of-fold.** Stack weights come from predictions each model
made for rows it did not train on. Fitting them on the training split teaches the
blend which model memorised best rather than which generalises best.

**Selection and reporting are separate.** Models are chosen on a validation
split and scored once on a test split neither training nor selection touched.
An earlier version of the crop trainer selected on test — the winner was chosen
on the data its score is reported against, which makes the report a selection
statistic. That was a real defect, found and fixed.

**The metric fits the problem.** Fraud reports AUC *and* an alert-budget table,
because a desk acts on a budget rather than a ranking. Early warning reports
lead time as well as capture, because a detector that fires the month before
default has excellent discrimination and no operational value. Crop reports
macro-F1 rather than accuracy, because predicting the majority class everywhere
scores 99.76% pixel accuracy.

### Watching a run

```bash
open tools/training_monitor.html      # or just double-click it
```

One dependency-free page, four tabs, polling every two seconds. It reads the
progress JSON each trainer writes atomically, so it works offline and survives a
trainer crash. Nothing is served or published.

### Why these use libraries when the core does not

ADR-0003 makes `src/lending_hub/` standard-library only so every algorithm stays
readable and the reference implementation runs anywhere. That constraint is about
the *reference implementation*. These harnesses live in `tools/`, import nothing
from the core, and are exactly the Track B swap the ADR anticipates: same
problem, real backends.

---

## Status, stated plainly

**Zero of thirty-one exit criteria have gate evidence.** Every phase gate reports
`Track B evidence: 0`, because Track B is a bank deployment and there is no bank
attached. Saying so is the point.

| Phase | Gate evidence | Tickets | Findings | The blocker in one line |
|---|---|---|---|---|
| **P0** platform | — | 13 | — | Data-sharing approvals that were never granted |
| **P1** scoring & fraud | 0 of 8 | 10 | 14 | Approve/decline cutoffs are unratified (LH-204) |
| **P2** agri | 0 of 6 | 13 | 14 | No ratified crop calendar; input costs decide the sign of income (LH-102, LH-401) |
| **P3** portfolio | 0 of 6 | 11 | 14 | SICR thresholds and the LGD loss basis (LH-301, LH-311) |
| **P4** EWS & reco | 0 of 5 | 13 | 11 | No collections desk exists, so no alert has ever been dispositioned |
| **P5** assistant | 0 of 6 | 12 | 9 | No corpus, no golden set, no approved templates, no model |
| **P6** learning loops | standing | 11 | 7 | A learning loop with no prior iteration has nothing to learn from |
| **P7** interfaces | 0 | 15 | 13 | The SRS sections it cites do not exist (LH-711) |

**98 tickets, and none is engineering work.** Each names an owner and the exact
decision required: a cutoff, a crop calendar, an alert budget, a set of
sentences a lawyer must approve. That register is the honest project plan — it
says precisely what a bank has to settle before any of this touches a customer.

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

### Sixty seconds

```bash
git clone <this repo> && cd AILendingHub
make check            # grounding + registry + 2,331 tests, ~30s
make demo6            # watch the learning-loop engines compute, and refuse
```

Nothing to install. The core is standard-library Python; only PyYAML is needed
beyond it, and only for the config validators.


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

> **Two traps, both of which look like a broken app.**
>
> *Use port 3000.* The gateway allows one CORS origin at a time. On any other
> port the browser's preflight succeeds and the real request is blocked, which
> shows as `Failed to fetch` with nothing in the gateway log.
>
> *Use `npm run dev`, not a production build.* `next build` sets
> `NODE_ENV=production`, which nulls the development session by design, and the
> app falls back to the adapter that refuses every call.
>
> If a page renders unstyled or throws `Cannot find module './vendor-chunks/…'`,
> the build cache is stale from switching between `dev` and `build`:
> `rm -rf frontend/.next` and start again.

### Real numbers from real data

```bash
make trackp-p1      # WS-1.1 on 150,000 real applications
make trackp-p3      # WS-3.1/3.2 on a 19-year mortgage panel
make trackp-p4      # does deterioration precede default?
make gate1 … gate6  # the evidence packs, generated never hand-written
```

### Stronger models, trained separately

Four research harnesses in `tools/` explore what a production-grade model would
buy. They write to their own files and **overwrite no committed run** — a tuning
script that clobbers its baseline makes "we improved the model" unfalsifiable.

```bash
python3 tools/train_ensemble.py   # credit scoring, 7 models
python3 tools/train_survival.py   # behavioural PD and early warning, 5 models
python3 tools/train_fraud.py      # card fraud, 3 families
python3 tools/train_crop.py       # crop classification, 4 models
```

Open `tools/training_monitor.html` in a browser to watch any of them live — it
polls the progress files and needs no server.

These use LightGBM, XGBoost and CatBoost. That is not a contradiction of the
stdlib-only rule: ADR-0003 constrains `src/lending_hub/`, the *reference
implementation*, so that every algorithm stays readable and portable. These live
in `tools/`, import nothing from the core, and are exactly the Track B swap the
ADR anticipates.

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

## The decisions that shaped this

Twelve architecture decision records sit in [`docs/adr/`](docs/adr/). Six
changed what the code looks like enough to be worth reading:

| ADR | The decision | Why it matters |
|---|---|---|
| [0003](docs/adr/0003-two-track-execution-model.md) | Three tracks against one interface | Everything else follows from it. Track A proves code paths, Track P proves the code survives real data, only Track B is evidence. |
| [0004](docs/adr/0004-public-reference-data-track.md) | Use real public data, label it as such | A Gini on US consumer loans is a fact about US consumer lending. Useful, and not about this bank. |
| [0013](docs/adr/0013-phase2-agri-track.md) | Agri models ship as contracts, not weights | **Since amended.** It recorded that no crop labels existed for India. AgriFieldNet proved that wrong — the honest correction is recorded rather than quietly fixed. |
| [0014](docs/adr/0014-phase4-action-systems-track.md) | Do not simulate a collections desk | A simulator authored by the detector's author makes every signal score well exactly to the extent the simulator shares its theory of default. |
| [0015](docs/adr/0015-phase5-assistant-track.md) | Call no LLM, fabricate no corpus | A faithfulness score over a corpus you wrote measures the author. The easiest phase to demo convincingly is the one most worth refusing to fake. |
| [0016](docs/adr/0016-phase6-learning-loops-track.md) | Build the promotion rule before the first challenger | A rule written under pressure by whoever ships the first challenger is a rule shaped by that challenger. |

### Five refusals worth knowing about

Each is a place where a plausible default would have become the production value,
because nobody would ever have gone back to check it.

- **`expected_income()` raises** without ratified input costs. On a smallholder
  plot those costs decide the *sign* of the answer, not its precision.
- **`VillageLocation.area_hectares` raises** rather than returning a nominal area
  around a centroid. A circle around a village centre is a plausible map of a
  survey nobody did.
- **`Reward.blended()` raises** without a ratified weight. A bandit rewarded on
  take-up alone learns to offer the largest permitted loan to whoever is
  likeliest to accept it.
- **`estimate_uplift()` raises** on an unrandomised log. Uplift from observational
  data is not a worse estimate — it is a different quantity, and more data
  narrows the interval around the wrong number.
- **`templates` composes no sentence.** There is no code path that writes an
  adverse-action explanation. A model that paraphrased an approved sentence into
  something clearer would produce one Compliance never saw, and it would be
  *better written*, which makes it likelier to reach a customer.

### The build gates

Six checks run on every commit. Each exists because of a specific failure it
prevents.

| Gate | What it refuses |
|---|---|
| `check_grounding.py` | A number with no `[SPEC]`, `[DATA]` or `[POLICY]` behind it; a malformed placeholder; a frozen definition retyped instead of imported |
| `validate_source_registry.py` | A data source with no owner, no schema, or no retention position |
| `check_schema_compatibility.py` | A stream change that would break an existing consumer |
| `check-no-client-math.mjs` | Arithmetic on a money figure anywhere in the render layer |
| `attribution.contract.ts` | A response rendering a score without its model id, version and decision-log reference |
| `audit_routes()` | A gateway route no client declares, or a model-derived route that returns a payload instead of a refusal |

Three of these caught defects in this project's own code while it was being
written, which is the only real test of whether a gate works.

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

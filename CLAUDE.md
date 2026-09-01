# CLAUDE.md — working agreement for this repository

Read this before touching anything. It applies to **every contributor, human or AI**.

---

## 1. What this repository is

The **AI-Powered Smart Lending Decision Hub** — a bank lending platform combining credit
scoring, fraud detection, agri-satellite intelligence, PD/LGD/EAD, early warning, and a
GenAI assistant.

Three document layers govern the work, in strict precedence order:

| Rank | Document | Role |
|---|---|---|
| 1 | [README.md](README.md) | The **SRS** — design intent, module algorithms, NFRs. `§`-references everywhere point here. |
| 2 | [Lending_Hub_Phase_Docs/00_MASTER_Implementation_Guide.md](Lending_Hub_Phase_Docs/00_MASTER_Implementation_Guide.md) | The **shared contract** — grounding rules, gate protocol, frozen definitions (Appendix A). |
| 3 | `Lending_Hub_Phase_Docs/Phase_N_*.md` | **Execution detail** for one phase. |

**Conflicts are raised as tickets, never resolved silently by an implementer.** If the
SRS and a phase file disagree, the SRS wins and the phase file gets a ticket.

To work a phase you load: **the Master + that one phase file + this CLAUDE.md.** Nothing
outside them may be assumed.

**Current phase: P4 — EWS + Recommendations (the first phase that *acts*).**
Status: [docs/phase4/STATUS.md](docs/phase4/STATUS.md). P2
([docs/phase2/STATUS.md](docs/phase2/STATUS.md)), P3
([docs/phase3/STATUS.md](docs/phase3/STATUS.md)), P1
([docs/phase1/STATUS.md](docs/phase1/STATUS.md)) and P0
([docs/phase0/STATUS.md](docs/phase0/STATUS.md)) are each built as far as they can
be; every phase's entry criteria trace back to Phase 0's, which is why none is
exitable.

Phase 1 was the first phase with **models**, so two rules that were abstract in
Phase 0 began to bite: every model ships with its card (Master §2 rule 5), and every
number is stamped with the track *and dataset* that produced it.

Phase 3 added a third: **"not measured" and "not measurable" are different gate
states.** Some P3 criteria are unrun; others cannot be produced by any data
reachable from here, and no effort inside this repository changes that. The CCF
model is the clean case — there is no revolving product on any track, so the
denominator is identically zero. Reporting both the same way puts a scheduling
problem and a structural one in the same column, and the second never gets
escalated.

Phase 2 adds a fourth, and it is the sharpest: **a phase can be worth building
when none of its exit criteria is reachable.** P2 has **no Track P at all**
([ADR-0013](docs/adr/0013-phase2-agri-track.md)) — there is no imagery in
`datasets/`, no agri book with outcomes (LH-406), and no ratified crop calendar
(LH-102) — and unlike P1 and P3 nothing substitutes, because a crop calendar for
the wrong agro-zone is a different calendar rather than a noisy version of the
right one. All six exit criteria report *not measurable*.

So what was built is **every deterministic computation in the phase, up to the
boundary of what is groundable**, on the interfaces Track B swaps in: SPI/SPEI
with the reference test §4 mandates, the index pipelines, the plot registry, the
gates and contracts around all three models, the credit-feature formulas, the
three backtests. The three fine-tuned models themselves are not ported, and that
is a decision recorded in ADR-0013 rather than an omission — a stdlib
re-derivation of SAM or Presto would be a different model wearing the paper's
name, which is worse than absence because it looks complete on a checklist.

The payoff is not a gate. It is that the boundary is now explicit and reviewable,
and that **five values nobody had noticed were missing** now have owners
(LH-407 to LH-409, LH-411, LH-412) — each found the same way, by writing code
against a step that read as fully specified until it had to produce a number.

Phase 4 adds a fifth rule, and it changes what a *track* can mean: **an action
system can only be evaluated against actions taken.** Every phase before it
produced a number checkable against an outcome that had already happened. P4
produces an alert routed to a human with an SLA, and an offer made to a customer.
So P4 splits ([ADR-0014](docs/adr/0014-phase4-action-systems-track.md)): its
**detection** layer has real Track P evidence — P3's hazard model is fitted on
338,210 real account-months, so "does deterioration precede default, and by how
long" has a real answer — while its **disposition and action** layers have none
and can have none.

**Nothing in P4 is simulated**, and that is the phase's central refusal. A
simulated collections desk would produce a signal catalogue with precisions, a
passing ship gate and a bandit that visibly learns — every number a property of
the simulator. It would be worse than P3's in-sample error, because the simulator
would be authored by the same person as the detector, so a signal would score
well exactly to the extent that the simulator shared its theory of default.

---

## 2. The grounding contract (Master §2) — non-negotiable

Every number, threshold, rate, or business rule in this repo must come from exactly one of:

- **`[SPEC]`** — written explicitly in the SRS, the Master, or a phase file.
- **`[DATA]`** — computed from real bank data by a versioned, committed script.
- **`[POLICY: <owner>]`** — supplied in writing by the named owning committee.

**If a value is in none of the three: stop and raise a blocking ticket.** Never assume,
never paste a "typical industry value" into code. This is the single rule that matters
most in this repo — a plausible-looking invented cutoff is worse than a build failure,
because it survives review.

Mechanically:

- Unknowns are written **`TBD[owner, ticket-id]`** in code, config, and docs.
  Example: `pii_class = "TBD[DPO, LH-110]"`.
- `make grounding` scans the tree and **fails the build** if a `TBD` reaches a release
  branch, or if a `TBD` is malformed (missing owner or ticket). This is
  [tools/check_grounding.py](tools/check_grounding.py) — it is the executable form of
  Master §2, and it is why the rule is real rather than aspirational.
- Every open placeholder is registered in its **phase's** ticket register:
  [docs/phase0/blocking_tickets.md](docs/phase0/blocking_tickets.md),
  [docs/phase1/blocking_tickets.md](docs/phase1/blocking_tickets.md). `make grounding`
  reads all of them, so a P1 placeholder cites a P1 ticket.

The other five Master §2 rules, in short: one reference implementation per algorithm ·
synthetic data **only** under `tests/fixtures/`, never in a training table · every model
ships with its card · definitions imported from `lending_hub.definitions`, never retyped ·
LLM output is never a fact.

---

## 3. Two-track execution model (ADR-0003)

The phase docs describe a bank deployment. This repo has no bank attached, so every
deliverable is built on **three tracks against one interface**:

- **Track A — local reference implementation.** Runs on a laptop, stdlib-only, on
  synthetic fixtures in `tests/fixtures/`. Proves the *code paths*: joins,
  point-in-time correctness, serving path, reproducibility, audit arithmetic.
- **Track P — public reference data** ([ADR-0004](docs/adr/0004-public-reference-data-track.md)).
  Real loans and real applications from public datasets in `datasets/` (gitignored).
  Proves the code survives what fixtures cannot simulate: real missingness, real class
  imbalance, real sentinel encodings, real key defects. Real data, but **not this
  bank's** data, so not gate evidence either.
- **Track B — bank deployment.** Same interfaces, real backends (Delta/Iceberg, Kafka,
  Feast, MLflow, Airflow). Swapped in via the `ports.py` adapter in each package.

Track A and Track P results **never** substitute for a Track B gate number. A join
rate computed on fixtures is a test of the *audit script*; a Gini computed on US
consumer loans is a fact about US consumer lending. Every gate report labels each
number with the track — and from P1 onward the **dataset** — that produced it.

Read [ADR-0003](docs/adr/0003-two-track-execution-model.md) before adding a dependency,
and [ADR-0010](docs/adr/0010-scored-product-and-track-p-standin.md) before quoting a
Phase 1 number.

---

## 4. Repo map

```
README.md                    SRS (rank 1) — do not edit without a ticket
Lending_Hub_Phase_Docs/      Master + 7 phase files (rank 2 & 3)
CLAUDE.md                    this file — the working agreement
CONTRIBUTING.md              day-to-day workflow, commit format, review gates

src/lending_hub/
  definitions/               Master Appendix A as importable constants (WS-0.3.4)
  registry/                  source-registry loader + schema validation (WS-0.1.1)
  lakehouse/                 Bronze/Silver/Gold contracts, GL reconciliation (WS-0.1.2/5)
  identity/                  identity spine, survivorship, join audit (WS-0.1.3)
  streaming/                 event schemas + backward-compat checker (WS-0.1.4)
  featurestore/              feature definitions + point-in-time join (WS-0.2.1)
  mlops/                     registry ports, promotion gate, reproducibility (WS-0.2.2/3)
  privacy/                   tokenization, consent artifacts, retention (WS-0.3.3)
  decisionlog/               decision-log schema + replay (Master §3.3)
  serving/                   orchestrator, policy bands, shadow/canary, load test, parity
                             (WS-0.2.4, WS-0.4, Phase 1 §5)
  sources/                   Track P dataset adapters — Fannie Mae (outcomes and
                             panel), Home Credit, Home Credit history (ADR-0004)
  modeling/                  shared metrics + the WS-0.2.3 toy logistic model
  scoring/                   P1 credit scoring, WS-1.1 (SRS §4) — see below
  fraud/                     P1 fraud layers 1-2, WS-1.2 (SRS §5) — see below
  portfolio/                 P3 portfolio brain, WS-3.1/3.2 (SRS §7, §9) — see below
  agri/                      P2 agri intelligence, WS-2.1/2.2/2.3/2.4 (SRS §3) — see below
  ews/                       P4 early warning, WS-4.A (SRS §10) — see below
  reco/                      P4 recommendation engine, WS-4.B (SRS §6) — see below

tools/                       CI gates: check_grounding, validate_source_registry,
                             check_schema_compatibility, gate_report,
                             phase1_gate_report, phase2_gate_report,
                             phase3_gate_report, phase4_gate_report
config/sources/              one YAML per SRS §2.1 source
config/retention.yaml        per-table retention (every period pending on LH-111)
config/reason_codes.yaml     reason-code dictionary — DATA, editable by legal (LH-203)
config/policy_bands.yaml     cutoffs and canary bands — dual-control config (LH-204)
docs/adr/                    architecture decision records (0001-0004, 0010-0014)
docs/governance/             model card / validation / monitoring templates (WS-0.3.2)
docs/phase0/                 STATUS, DATA_SOURCING, TRACK_P_FINDINGS, blocking_tickets
docs/phase1/                 STATUS, blocking_tickets, model_cards/
docs/phase2/                 STATUS, blocking_tickets, model_cards/
docs/phase3/                 STATUS, blocking_tickets, model_cards/
docs/phase4/                 STATUS, blocking_tickets, model_cards/
datasets/                    real external data — gitignored, never committed
tests/fixtures/              the ONLY place synthetic data may live (Master §2 rule 3)
reports/                     generated gate output — regenerate, never commit
```

### The Phase 3 package

`portfolio/` is WS-3.1 and WS-3.2. `panel` is the substrate — one `Spell` yields
the four shapes the phase needs (behavioural targets, the discrete-time risk set,
competing-risk causes, adjacent month pairs), so no model slices raw performance
rows itself. Then WS-3.1 in the order the phase file runs it: `behavioural` →
`cox` → `hazard` → `competing` → `lgd` → `ead` → `staging` → `macro`, with
`survival` holding the metric set and `linalg` the solver both Newton-Raphson
fits share. WS-3.2 is `transitions`, `health`, `opsanomaly`, `aggregates`.
`experiment` is the Track P runner.

### The Phase 2 package

`agri/` is WS-2.1 through WS-2.4, and it is the one package with **no Track P
run behind it** — read [ADR-0013](docs/adr/0013-phase2-agri-track.md) before
quoting anything from it. WS-2.1 is `ports` (the Copernicus/PostGIS/weather
seam) → `drought` (SPI/SPEI) → `indices` (NDVI/EVI, backscatter, cloud masking)
→ `geometry` → `registry` → `ingest`. WS-2.2 is `boundary`, `crop` and
`yield_model`. WS-2.3 is `features`; WS-2.4 is `backtest` and `disparate`.

**The three models are absent on purpose.** SAM/U-Net, Presto and the
histogram-CNN + GP are fine-tuned or pretrained networks with no imagery to fit
and no labels to fit against, so Master §2 rule 2 admits neither of its branches
— use the library, or port it with tests reproducing its outputs. What `boundary`,
`crop` and `yield_model` contain instead is each model's **contract**: the metric,
the gate, the calibration, the abstention rule, the output shape, and the
baseline each must beat. That turns out to be where most of the risk lives.

**The refusals are the design.** More than in any other package, the interesting
behaviour here is what does not compute. `VillageLocation.area_hectares` raises
rather than returning a nominal area around a centroid. `expected_income()`
raises without ratified input costs, which on a smallholder plot decide the
*sign* of the result. `land_quality_index()` raises without a ratified formula,
because §4 names six inputs and no function over them. `run_backtest()` accepts
no threshold arguments at all, because §4 says a failed test triggers feature
redesign and never threshold relaxation. Each of those is a place where a
plausible default would have produced a number nobody could later tell from a
real one.

**The point-in-time risk is different here.** On an application table a leak takes
an exotic join. On a behavioural panel it is the natural thing to write, because
the DPD column that defines the target is sitting in the feature row — and it
surfaces as excellent metrics, which is what an unnoticed leak looks like.
`behavioural.assert_point_in_time()` proves the property directly rather than
asserting it: it rewrites every month after the observation point, re-derives, and
names any feature that moved.

### The two Phase 1 packages

`scoring/` is WS-1.1 in the order the phase file runs it: `target` → `splits` →
`features` → `binning` (+`isotonic`) → `scorecard` → `gbm` → `calibration` →
`explain` (+`reasons`) → `fairness` → `rejects` → `validation`, with `parallel`
as a shared helper and `experiment` as the Track P runner. `fraud/` is WS-1.2:
`entity_resolution`, `velocity`, `anomaly`, `supervised`, `documents`, `routing`.

**On speed.** Stdlib-only means no numpy, so every numeric loop is interpreted.
Binning and the hyperparameter search are parallelised across processes
(`scoring/parallel.py` — `concurrent.futures` is stdlib); boosting is sequential
across trees by definition and stays that way. If a fit is too slow the levers, in
order, are `feature_fraction`, fewer trees, and fewer rows — not a dependency.

All three are stdlib-only **ports** of the libraries the phase files name
(OptBinning, LightGBM, SHAP, Fairlearn, scikit-learn, splink, lifelines,
scikit-survival, River). Each module docstring states what it ports **and what it
deliberately does not** — the GBM has no GOSS or EFB, the binning is PAVA rather
than a MIP, SHAP is exact enumeration rather than TreeSHAP, Cox has no penalised
or stratified variant, S-H-ESD uses a seasonal median rather than STL. Tests
assert the *properties* a Track B swap must preserve, never this port's exact
numbers; a test pinned to these cut points would fail on the library it is a port
of.

**Ports still make real choices.** Two are worth knowing about because the named
library's default is wrong here: `portfolio.cox` defaults to **Efron** tie
handling where scikit-survival defaults to Breslow, because a month-end panel ties
most of its events and Breslow biases coefficients toward zero at that density;
and `portfolio.hazard` passes month-on-book as an **ordered numeric feature**
where the phase file says dummies, because dummies discard the ordering a tree
needs. Both deviations are stated in the module docstring and raised as findings.

### The two Phase 4 packages

`ews/` is WS-4.A and `reco/` is WS-4.B, and the split between them is the split
between detecting and acting. WS-4.A runs `signals` → `velocity` → `bocpd` →
`agri_triggers` → `routing` → `backtest`, with `experiment` as the Track P
runner. WS-4.B runs in the phase file's own shipping order: `feasible` (ship
first, useful alone) → `pricing` → `bandit` → `suitability`.

**The refusals here are about actions rather than numbers.** An `Alert` cannot be
constructed without an owner, an SLA and a recommended action, because an alert
missing any of the three is a notification and the difference stops being visible
once it is in a queue. A `BanditDecision` cannot be constructed without a
propensity, which makes Phase 4 §8's "completeness = 100%" the one exit criterion
this repository fully satisfies — it is a property of the type, not a
measurement. `Reward.blended()` refuses without a ratified weight, because a
bandit rewarded on take-up alone learns to offer the largest permitted loan to
whoever is likeliest to accept it. And no signal in the catalogue ships, because
precision needs a collections desk that does not exist.

**Two corrections came out of building it**, both recorded in
[Phase_4_FINDINGS](Lending_Hub_Phase_Docs/Phase_4_FINDINGS.md). The phase file's
BOCPD instruction names a quantity that is identically the hazard and detects
nothing (P4-F1). And my own first Track P capture number scored defaults the
detector could not have reached, measuring the train/test split rather than the
detector (P4-F11) — the same failure as P3's in-sample comparison, pointing the
other way.

### Start here

| You want to | Read |
|---|---|
| Know what is done and what is blocked | [P4 STATUS](docs/phase4/STATUS.md) · [P2](docs/phase2/STATUS.md) · [P3](docs/phase3/STATUS.md) · [P1](docs/phase1/STATUS.md) · [P0](docs/phase0/STATUS.md) |
| Pick up a task | [CONTRIBUTING.md](CONTRIBUTING.md), then STATUS |
| Know what data is fake, what is real, and what neither proves | [docs/phase0/DATA_SOURCING.md](docs/phase0/DATA_SOURCING.md) · [ADR-0012](docs/adr/0012-phase3-panel-source.md) |
| Know why the phase docs were not followed literally | [P0](Lending_Hub_Phase_Docs/Phase_0_FINDINGS.md) · [P1](Lending_Hub_Phase_Docs/Phase_1_FINDINGS.md) · [P2](Lending_Hub_Phase_Docs/Phase_2_FINDINGS.md) · [P3](Lending_Hub_Phase_Docs/Phase_3_FINDINGS.md) · [P4](Lending_Hub_Phase_Docs/Phase_4_FINDINGS.md) |
| Know what is waiting on a committee | [P0](docs/phase0/blocking_tickets.md) · [P1](docs/phase1/blocking_tickets.md) · [P2](docs/phase2/blocking_tickets.md) · [P3](docs/phase3/blocking_tickets.md) · [P4](docs/phase4/blocking_tickets.md) |
| Know what a model may and may not be used for | [P1 cards](docs/phase1/model_cards/) · [P2 cards](docs/phase2/model_cards/) · [P3 cards](docs/phase3/model_cards/) · [P4 cards](docs/phase4/model_cards/) |
| See real numbers from the whole P1 pipeline | `make trackp-p1` → `reports/trackP_p1_home_credit.json` |
| See real numbers from the whole P3 pipeline | `make trackp-p3` → `reports/trackP_p3_fannie_mae.json` |
| See whether deterioration precedes default, and by how long | `make trackp-p4` → `reports/trackP_p4_fannie_mae.json` |

---

## 5. How to run things

No install step is needed for the core checks.

```bash
make help          # list every target
make check         # grounding + registry + tests — run this before every commit
make test          # stdlib unittest suite (1,529 tests, ~27s)
make gate          # run every gate script and assemble all five gate packs
```

Individual gates: `make audit-joins` (WS-0.1.3), `make reconcile` (WS-0.1.5),
`make schemas` (WS-0.1.4), `make repro` (WS-0.2.3), `make loadtest` (WS-0.2.4),
`make parity` (WS-0.4), `make gate1` (Phase 1 §7 evidence pack),
`make gate2` (Phase 2 §7 evidence pack), `make gate3` (Phase 3 §7 evidence pack),
`make gate4` (Phase 4 §8 evidence pack).

`make trackp-p1` runs the whole of WS-1.1 against real applications and writes
`reports/trackP_p1_home_credit.json`. `make trackp-p3` runs WS-3.1 and WS-3.2
against a real 19-year mortgage panel and writes
`reports/trackP_p3_fannie_mae.json`. Both need `datasets/`, which is gitignored —
see [docs/phase0/DATA_SOURCING.md](docs/phase0/DATA_SOURCING.md) for how to obtain it.
Everything else runs on a clean clone with nothing downloaded.

Only `PyYAML` is required beyond the standard library (`pip install -r requirements-dev.txt`),
and only for the YAML config validators. If you find yourself adding a dependency to the
core packages, you are probably on Track B — put it behind a `ports.py` adapter instead.

---

## 6. Conventions

- **Definitions are imported, never retyped.** `from lending_hub.definitions import DEFAULT`
  — not a local copy of "DPD >= 90". Changing a definition needs Model Risk Committee
  approval and an impact analysis on every model importing it (Master Appendix A).
- **Every workstream artifact cites its clause.** A module docstring names its
  workstream (`WS-0.1.3`) and the SRS section it implements. `make grounding` checks this.
- **Every gate number is produced by a committed, rerunnable script**, never by hand.
  If a number appears in a report, `git grep` must find the script that computed it.
- **Commits:** `<area>: <what changed>` with the workstream in the body.
  One workstream deliverable per commit — the gate review reads the log.
  **Never add a `Co-Authored-By` trailer for an AI assistant** (or any other
  AI-attribution trailer) to a commit in this repo. The commit author is the
  engineer who owns the change; authorship of code the bank will be audited on
  is a human accountability record, not a tooling credit. This applies to every
  commit, including ones written end-to-end by an agent.
- Synthetic data lives in `tests/fixtures/` and nowhere else. A fixture that escapes into
  a training path is a build failure, not a code-review comment.
- **A missing `[POLICY]` value makes the code raise, not default.** From P1 the pattern
  is everywhere: `Scorecard.points()` raises without a score anchor,
  `FairnessReport.verdict()` raises without an action threshold, `build_graph()` has no
  default match threshold, `route()` has no default band set. A default in a signature
  is how an ungrounded number becomes the production one — nobody passes the argument,
  and by the time anyone asks it has been in a report for a year.
- **A model records its own governance state.** `GBM.promotable`, `FraudModel.promotable`
  and `BandConfig.effective` return why-not alongside the boolean, so an unratified
  constraint list or a missing second approver is a value a gate script reads rather
  than a footnote a reviewer notices.

---

## 7. What must never be invented here

Phase 0's do-not-invent list (Master Appendix B + Phase 0 §8), all `[POLICY]`:

> retention periods · consent wording · PII classifications · survivorship rule
> exceptions · GL mapping rules

**Phase 1's** (Phase 1 §8), all `[POLICY]` and all registered:

> approve/decline cutoffs · review-band edges · canary % (LH-204) · monotonicity
> direction list (LH-202) · reason-code wording (LH-203) · fairness action
> thresholds (LH-205) · fraud alert budget (LH-206) · step-up friction tolerance

Phase 1 implementation added four more that the phase file does not list, each raised
as a finding: the **score-scale anchor** (LH-208 — PDO fixes the slope, nothing fixes
the intercept), **bureau-retro availability** (LH-207), the **labelled duplicate-pair
set** the ER threshold needs (LH-209), and the **bank-branch directory** behind IFSC
existence (LH-210).

**Phase 3's** (Phase 3 §8), all `[POLICY]` and all registered:

> SICR thresholds (LH-301) · downturn LGD add-ons (LH-302) · CCF floors (LH-303) ·
> macro scenarios (LH-304) · discount-rate conventions (LH-305) · reporting segment
> definitions (LH-306)

Phase 3 implementation added five more the phase file does not list, each raised as
a finding: **CUSUM/ADWIN alarm parameters** (LH-307 — the methods are named, the
parameters that make them alarm are not), the **origination lifetime PD** SICR is
relative to (LH-308), the **cure definition** the LGD model's first stage needs
(LH-309 — Appendix A defines default but not cure), the **behavioural**
monotonicity list (LH-310, distinct from P1's application list), and the **LGD loss
basis** (LH-311 — whether credit enhancement is netted off, which flips the sign of
the LTV coefficient on real data).

**Phase 2's** (Phase 2 §8), all `[POLICY]` or `[DATA]` and all registered:

> crop calendars & sowing windows (LH-102, LH-402) · per-crop input costs (LH-401) ·
> disbursal-tranching rules (LH-403) · qualifying-crop lists (LH-404) ·
> natural-calamity relief treatment (LH-405) · **any plot polygon not observed or
> walked**

That last one is the only entry on any do-not-invent list an implementer can
violate *by accident* rather than by guessing a number, which is why it is a type
in `agri.registry` rather than a rule in a document.

Phase 2 implementation added five more the phase file does not list, each raised
as a finding: the **GPS-walk label set** Model A trains and gates on (LH-407 — an
input the plan never schedules), the **mandi price window** as distinct from the
feed (LH-408), where an **abstaining model's cases go** (LH-409), the **function
combining LandQualityIndex's six inputs** (LH-411 — six named inputs are not a
formula, and LQI is what exit criterion (a) tests), and **which crop season a
default belongs to** (LH-412 — the rule can pass or fail criterion (c) with no
change to the flag).

Later phases add: alert budgets, action SLAs, pricing (P4) · rates, fees,
adverse-action sentences (P5).

If a task seems to require one of these, the correct output is a **blocking ticket**, not
a best guess. Write `TBD[owner, ticket-id]`, add the row to your phase's register
([P0](docs/phase0/blocking_tickets.md), [P1](docs/phase1/blocking_tickets.md)), and keep
building everything the value does not block. Phase 1 is the proof that this works: ten
open tickets, and every workstream still built and exercised on real data.

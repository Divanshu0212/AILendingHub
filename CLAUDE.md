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

**Current phase: P3 — Portfolio Brain (behavioural PD, survival, LGD/EAD, staging,
dashboards).** Status: [docs/phase3/STATUS.md](docs/phase3/STATUS.md). P1 is complete
as far as it can be ([docs/phase1/STATUS.md](docs/phase1/STATUS.md)), as is P0
([docs/phase0/STATUS.md](docs/phase0/STATUS.md)); every phase's entry criteria trace
back to Phase 0's, which is why none is exitable. **P2 was skipped deliberately** —
its entry criteria are `[POLICY]`-blocked on crop calendars (LH-102) and the phase
file forbids guessing them, and its models cannot be honestly ported under ADR-0003.

Phase 1 was the first phase with **models**, so two rules that were abstract in
Phase 0 began to bite: every model ships with its card (Master §2 rule 5), and every
number is stamped with the track *and dataset* that produced it.

Phase 3 adds a third: **"not measured" and "not measurable" are different gate
states.** Some P3 criteria are unrun; others cannot be produced by any data
reachable from here, and no effort inside this repository changes that. The CCF
model is the clean case — there is no revolving product on any track, so the
denominator is identically zero. Reporting both the same way puts a scheduling
problem and a structural one in the same column, and the second never gets
escalated.

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

tools/                       CI gates: check_grounding, validate_source_registry,
                             check_schema_compatibility, gate_report,
                             phase1_gate_report, phase3_gate_report
config/sources/              one YAML per SRS §2.1 source
config/retention.yaml        per-table retention (every period pending on LH-111)
config/reason_codes.yaml     reason-code dictionary — DATA, editable by legal (LH-203)
config/policy_bands.yaml     cutoffs and canary bands — dual-control config (LH-204)
docs/adr/                    architecture decision records (0001-0004, 0010-0012)
docs/governance/             model card / validation / monitoring templates (WS-0.3.2)
docs/phase0/                 STATUS, DATA_SOURCING, TRACK_P_FINDINGS, blocking_tickets
docs/phase1/                 STATUS, blocking_tickets, model_cards/
docs/phase3/                 STATUS, blocking_tickets, model_cards/
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

### Start here

| You want to | Read |
|---|---|
| Know what is done and what is blocked | [P3 STATUS](docs/phase3/STATUS.md) · [P1](docs/phase1/STATUS.md) · [P0](docs/phase0/STATUS.md) |
| Pick up a task | [CONTRIBUTING.md](CONTRIBUTING.md), then STATUS |
| Know what data is fake, what is real, and what neither proves | [docs/phase0/DATA_SOURCING.md](docs/phase0/DATA_SOURCING.md) · [ADR-0012](docs/adr/0012-phase3-panel-source.md) |
| Know why the phase docs were not followed literally | [P0](Lending_Hub_Phase_Docs/Phase_0_FINDINGS.md) · [P1](Lending_Hub_Phase_Docs/Phase_1_FINDINGS.md) · [P3](Lending_Hub_Phase_Docs/Phase_3_FINDINGS.md) |
| Know what is waiting on a committee | [P0](docs/phase0/blocking_tickets.md) · [P1](docs/phase1/blocking_tickets.md) · [P3](docs/phase3/blocking_tickets.md) |
| Know what a model may and may not be used for | [P1 cards](docs/phase1/model_cards/) · [P3 cards](docs/phase3/model_cards/) |
| See real numbers from the whole P1 pipeline | `make trackp-p1` → `reports/trackP_p1_home_credit.json` |
| See real numbers from the whole P3 pipeline | `make trackp-p3` → `reports/trackP_p3_fannie_mae.json` |

---

## 5. How to run things

No install step is needed for the core checks.

```bash
make help          # list every target
make check         # grounding + registry + tests — run this before every commit
make test          # stdlib unittest suite (1,137 tests, ~23s)
make gate          # run every gate script and assemble all three gate packs
```

Individual gates: `make audit-joins` (WS-0.1.3), `make reconcile` (WS-0.1.5),
`make schemas` (WS-0.1.4), `make repro` (WS-0.2.3), `make loadtest` (WS-0.2.4),
`make parity` (WS-0.4), `make gate1` (Phase 1 §7 evidence pack),
`make gate3` (Phase 3 §7 evidence pack).

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

Later phases add: crop calendars, sowing windows (P2) · alert budgets, action SLAs,
pricing (P4) · rates, fees, adverse-action sentences (P5).

If a task seems to require one of these, the correct output is a **blocking ticket**, not
a best guess. Write `TBD[owner, ticket-id]`, add the row to your phase's register
([P0](docs/phase0/blocking_tickets.md), [P1](docs/phase1/blocking_tickets.md)), and keep
building everything the value does not block. Phase 1 is the proof that this works: ten
open tickets, and every workstream still built and exercised on real data.

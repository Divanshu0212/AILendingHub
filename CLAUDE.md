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

**Current phase: P0 — Foundations.** Status and traceability:
[docs/phase0/STATUS.md](docs/phase0/STATUS.md).

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
  Example: `MIN_JOIN_RATE = "TBD[Data Platform Lead, LH-104]"`.
- `make grounding` scans the tree and **fails the build** if a `TBD` reaches a release
  branch, or if a `TBD` is malformed (missing owner or ticket). This is
  [tools/check_grounding.py](tools/check_grounding.py) — it is the executable form of
  Master §2, and it is why the rule is real rather than aspirational.
- Every open placeholder is registered in
  [docs/phase0/blocking_tickets.md](docs/phase0/blocking_tickets.md).

The other five Master §2 rules, in short: one reference implementation per algorithm ·
synthetic data **only** under `tests/fixtures/`, never in a training table · every model
ships with its card · definitions imported from `lending_hub.definitions`, never retyped ·
LLM output is never a fact.

---

## 3. Two-track execution model (ADR-0003)

The phase docs describe a bank deployment. This repo has no bank attached, so every
Phase 0 deliverable is built on **two tracks against one interface**:

- **Track A — local reference implementation.** Runs on a laptop, stdlib-only, on
  synthetic fixtures in `tests/fixtures/`. Proves the *code paths*: joins,
  point-in-time correctness, serving path, reproducibility, audit arithmetic.
- **Track B — bank deployment.** Same interfaces, real backends (Delta/Iceberg, Kafka,
  Feast, MLflow, Airflow). Swapped in via the `ports.py` adapter in each package.

Track A results **never** substitute for a Track B gate number. A join rate computed on
fixtures is a test of the *audit script*, not evidence of a 99.5% join rate. The
[gate report](docs/phase0/STATUS.md) labels every number with the track that produced it.

Read [docs/adr/0003-two-track-execution-model.md](docs/adr/0003-two-track-execution-model.md)
before adding a dependency.

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
  serving/                   orchestrator stub, load test, parity harness (WS-0.2.4, WS-0.4)

tools/                       CI enforcement: grounding, registry, schema compatibility
config/sources/              one YAML per SRS §2.1 source
docs/adr/                    architecture decision records
docs/governance/             model card / validation / monitoring templates (WS-0.3.2)
docs/phase0/                 status, traceability, blocking-ticket register
tests/fixtures/              the ONLY place synthetic data may live (Master §2 rule 3)
```

---

## 5. How to run things

No install step is needed for the core checks.

```bash
make help          # list every target
make check         # grounding + registry + tests — run this before every commit
make test          # stdlib unittest suite
make gate          # full Phase 0 evidence pack into reports/
```

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

---

## 7. What must never be invented here

Phase 0's do-not-invent list (Master Appendix B + Phase 0 §8), all `[POLICY]`:

> retention periods · consent wording · PII classifications · survivorship rule
> exceptions · GL mapping rules

Later phases add: approve/decline cutoffs, monotonicity directions, reason-code wording,
fairness thresholds (P1) · crop calendars, sowing windows (P2) · SICR thresholds,
downturn LGD add-ons, macro scenarios (P3) · alert budgets, action SLAs, pricing (P4) ·
rates, fees, adverse-action sentences (P5).

If a task seems to require one of these, the correct output is a **blocking ticket**, not
a best guess. Write `TBD[owner, ticket-id]`, add the row to
[docs/phase0/blocking_tickets.md](docs/phase0/blocking_tickets.md), and keep building
everything the value does not block.

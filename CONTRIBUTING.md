# Contributing

Day-to-day workflow. The binding rules live in [CLAUDE.md](CLAUDE.md) — read that first.

## Getting started

```bash
git clone https://github.com/Divanshu0212/AILendingHub.git
cd AILendingHub
python3 -m pip install -r requirements-dev.txt   # PyYAML only
make check
```

`make check` must be green on a clean clone with nothing else installed. If it isn't,
that's a bug in the repo, not in your machine.

## Picking up work

1. Open [docs/phase1/STATUS.md](docs/phase1/STATUS.md) — the current phase. It maps every
   Phase 1 checklist item to the artifact that satisfies it, the track (A/P/B) it runs
   on, and its state. Phase 0's is [here](docs/phase0/STATUS.md).
2. Take an item that is `not started`, or unblock one in `blocked` by chasing its
   `[POLICY]` owner.
3. Load the Master guide + the one phase file you are working. Do not work from memory
   of the SRS — the numbers matter.

## Before every commit

```bash
make check
```

This runs three gates:

| Gate | What it enforces |
|---|---|
| `make grounding` | Master §2 — no ungrounded value, no malformed `TBD`, no unregistered ticket, no synthetic data outside `tests/fixtures/` |
| `make registry`  | Every `config/sources/*.yaml` validates against the source-registry schema |
| `make test`      | The unit suite — 793 tests, stdlib only, about 9 seconds |

Two more you will want when touching Phase 1:

| Command | What it does |
|---|---|
| `make gate1` | Assembles the Phase 1 §7 evidence pack into `reports/phase1_gate.md` |
| `make trackp-p1` | Runs the whole of WS-1.1 against real applications. Needs `datasets/` — see [DATA_SOURCING](docs/phase0/DATA_SOURCING.md). Everything else runs on a clean clone |

## Commit format

```
<area>: <imperative summary>

<why, and what it unblocks>

Workstream: WS-0.1.3
Deliverable: identity spine + join-rate audit report
```

`<area>` is the package or doc touched: `definitions`, `registry`, `identity`,
`featurestore`, `serving`, `docs`, `ci`, …

One deliverable per commit. The gate review reads `git log` as the build narrative, so a
commit that spans three workstreams is a commit nobody can review.

**No AI co-author trailers.** Do not add `Co-Authored-By: Claude ...` (or any other
AI-attribution trailer), even when an agent wrote the whole commit. The author field is
the engineer accountable for the change under model-risk review — keep it human.

## When you hit a missing value

Do **not** guess. Even once. The whole point of the grounding contract is that an invented
threshold looks exactly like a real one six months later.

1. Write `TBD[<owner role>, <ticket-id>]` at the point of use.
2. Add a row to **your phase's** register —
   [P0](docs/phase0/blocking_tickets.md), [P1](docs/phase1/blocking_tickets.md).
   `make grounding` reads every `docs/phase*/blocking_tickets.md` and fails on any
   `TBD` registered in none of them.
3. Make the code **raise** where the value would be read, rather than defaulting.
   `Scorecard.points()` raising `Ungrounded` is worth more than a plausible score,
   because a plausible score reaches a customer letter and nothing downstream can
   tell it apart from a real one.
4. Keep building everything the missing value does not block. A blocked number rarely
   blocks the code path around it — Phase 1 has ten open tickets and every workstream
   built.

## Adding a dependency

Default answer: don't. The core packages are stdlib-only on purpose (ADR-0003) so the
suite runs anywhere with no install. If you need a real backend (Delta Lake, Kafka, Feast,
MLflow), it goes behind the `ports.py` interface in that package and into the
`platform` extra in `pyproject.toml` — never imported at module top level in core code.

## Porting a library

The core packages are stdlib-only, so every algorithm the phase files name is a **port**
behind the interface the real library will occupy. Master §2 rule 2 allows this — "use
that library, or port it with unit tests reproducing the library's outputs on fixture
data" — and it comes with two obligations that are easy to skip:

1. **State what you did not port.** The GBM implements histogram splits and the
   regularised gain and has no GOSS or EFB; the binning is PAVA rather than OptBinning's
   MIP; SHAP is exact enumeration rather than TreeSHAP's polynomial algorithm. Each of
   those sentences is in the module docstring, because a port that claims to be the
   library is a port nobody re-checks.
2. **Test properties, not numbers.** Assert monotonicity, local accuracy, determinism
   from the seed, bin contiguity — the things a Track B swap must preserve. A test
   pinned to your port's exact cut points will fail on the library it is a port of, and
   the person who deletes it will not know which of the two was right.

## Definitions

Anything in Master Appendix A — DPD, default, outcome window, observation point,
indeterminate, confirmed fraud, agri season, alert precision — is imported from
`lending_hub.definitions`. Never retype a definition inline, not even in a comment that
"just explains" it. `make grounding` looks for the literal patterns and fails on them.

Changing a definition is a Model Risk Committee decision plus an impact analysis on every
model that imports it. It is not a refactor.

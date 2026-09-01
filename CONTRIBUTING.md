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

1. Open [docs/phase4/STATUS.md](docs/phase4/STATUS.md) — the current phase. It is
   the first phase that *acts*, so read
   [ADR-0014](docs/adr/0014-phase4-action-systems-track.md) before quoting
   anything from `ews/` or `reco/`: detection has Track P evidence, action has
   none, and nothing in the phase is simulated.
   Then [docs/phase2/STATUS.md](docs/phase2/STATUS.md) — the previous phase. It maps every
   Phase 2 checklist item to the artifact that satisfies it, the track it runs on, and
   its state. **Phase 2 has no Track P** ([ADR-0013](docs/adr/0013-phase2-agri-track.md)),
   which is unlike every phase before it — read that ADR before quoting anything from
   `agri/`. Other phases: [P3](docs/phase3/STATUS.md), [P1](docs/phase1/STATUS.md),
   [P0](docs/phase0/STATUS.md).
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
| `make test`      | The unit suite — 1,529 tests, stdlib only, about 27 seconds |

Two more you will want when touching Phase 1:

| Command | What it does |
|---|---|
| `make gate1` | Assembles the Phase 1 §7 evidence pack into `reports/phase1_gate.md` |
| `make trackp-p1` | Runs the whole of WS-1.1 against real applications. Needs `datasets/` — see [DATA_SOURCING](docs/phase0/DATA_SOURCING.md). Everything else runs on a clean clone |

And when touching Phase 3:

| Command | What it does |
|---|---|
| `make gate3` | Assembles the Phase 3 §7 evidence pack into `reports/phase3_gate.md` |
| `make trackp-p3` | Runs WS-3.1 and WS-3.2 against a real 19-year mortgage panel. Also needs `datasets/` |

Phase 4 has `make gate4` and `make trackp-p4`, which measures whether hazard
deterioration precedes default on the real panel. Phase 2 has `make gate2` and
**no `make trackp-p2`** — there is no imagery, no agri
book and no ratified crop calendar, and none of the three is approximable, so every
`agri/` module runs on Track A only. That is the whole content of ADR-0013, and it is
why the Phase 2 gate pack quotes no metrics rather than fixture ones.

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
   [P0](docs/phase0/blocking_tickets.md), [P1](docs/phase1/blocking_tickets.md),
   [P2](docs/phase2/blocking_tickets.md), [P3](docs/phase3/blocking_tickets.md),
   [P4](docs/phase4/blocking_tickets.md), [P7](docs/phase7/blocking_tickets.md).
   `make grounding` reads every `docs/phase*/blocking_tickets.md` and fails on any
   `TBD` registered in none of them.
3. Make the code **raise** where the value would be read, rather than defaulting.
   `Scorecard.points()` raising `Ungrounded` is worth more than a plausible score,
   because a plausible score reaches a customer letter and nothing downstream can
   tell it apart from a real one.
4. Keep building everything the missing value does not block. A blocked number rarely
   blocks the code path around it — Phase 1 has ten open tickets and Phase 3 eleven,
   and every workstream
   built.

## Working in `frontend/`

`make check` does **not** test the frontend, and cannot: `make test` runs the
Python suite, and there is no Node toolchain in this repository's baseline. Run
it anyway before committing — `make grounding` scans every text file including
`frontend/`'s `.md` and `.json`, so a malformed `TBD` or an unregistered ticket
there fails the same gate it fails anywhere else.

Then read [frontend/README.md](frontend/README.md) before touching anything. The
directory has **never been built or run**, so there is no green baseline to
regress from and no compiler catching your mistakes. Three rules bind harder
there than anywhere else in the repo:

1. **No arithmetic in the UI layer.** Not a helper, not a `.toFixed`, not an
   `index + 1`. Every number is a `{amount, display}` pair and components render
   `display`. `npm run check:no-client-math` is the gate; it is blunt on purpose
   and every false positive so far turned out to be a real finding.
2. **No English strings in components.** Copy comes from the document registry
   through `<Copy k="...">`, which has no `fallback` prop. If you need a
   sentence, you need a registry key and a row in the register — not a
   placeholder you mean to replace.
3. **No fixture data outside `tests/fixtures/`.** The adapter port has no mock
   implementation and is not to acquire one casually: a demo build showing a
   plausible score and EMI is indistinguishable from a real one in a screenshot.

Do not write a commit message claiming the app builds, runs or renders. Nobody
has evidence for any of that.

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
   MIP; SHAP is exact enumeration rather than TreeSHAP's polynomial algorithm; Cox has
   no penalised or stratified variant; S-H-ESD uses a seasonal median rather than STL.
   Each of those sentences is in the module docstring, because a port that claims to be
   the library is a port nobody re-checks.

   **And say where you deviate from the library's defaults, with the reason.** A port is
   not obliged to copy a default that is wrong for this data. `portfolio.cox` uses Efron
   tie handling where scikit-survival defaults to Breslow, because a month-end panel ties
   most of its events and Breslow biases coefficients toward zero at that density —
   measured at 0.740 against Efron's 0.758 on data generated with a true 0.800. A
   deviation nobody wrote down is indistinguishable from a mistake.
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

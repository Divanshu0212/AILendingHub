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

1. Open [docs/phase0/STATUS.md](docs/phase0/STATUS.md). It maps every Phase 0 checklist
   item to the artifact that satisfies it, the track (A/B) it runs on, and its state.
2. Take an item that is `not started`, or unblock one in `blocked` by chasing its
   `[POLICY]` owner.
3. Load the Master guide + `Phase_0_Foundations.md`. Do not work from memory of the SRS —
   the numbers matter.

## Before every commit

```bash
make check
```

This runs three gates:

| Gate | What it enforces |
|---|---|
| `make grounding` | Master §2 — no ungrounded value, no malformed `TBD`, no unregistered ticket, no synthetic data outside `tests/fixtures/` |
| `make registry`  | Every `config/sources/*.yaml` validates against the source-registry schema |
| `make test`      | The unit suite |

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
2. Add a row to [docs/phase0/blocking_tickets.md](docs/phase0/blocking_tickets.md) —
   `make grounding` fails on any `TBD` that isn't registered there.
3. Keep building everything the missing value does not block. A blocked number rarely
   blocks the code path around it.

## Adding a dependency

Default answer: don't. The core packages are stdlib-only on purpose (ADR-0003) so the
suite runs anywhere with no install. If you need a real backend (Delta Lake, Kafka, Feast,
MLflow), it goes behind the `ports.py` interface in that package and into the
`platform` extra in `pyproject.toml` — never imported at module top level in core code.

## Definitions

Anything in Master Appendix A — DPD, default, outcome window, observation point,
indeterminate, confirmed fraud, agri season, alert precision — is imported from
`lending_hub.definitions`. Never retype a definition inline, not even in a comment that
"just explains" it. `make grounding` looks for the literal patterns and fails on them.

Changing a definition is a Model Risk Committee decision plus an impact analysis on every
model that imports it. It is not a refactor.

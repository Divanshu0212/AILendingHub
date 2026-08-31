# ADR-0004 — Track P: public reference data

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-09-01 |
| Decider | Data Platform Lead |
| Workstream | WS-0 (all) |
| Amends | [ADR-0003](0003-two-track-execution-model.md) |

## Context

ADR-0003 defined two tracks: **A** (synthetic fixtures, stdlib, proves the code
paths) and **B** (the bank's data, the only thing that produces gate evidence).

Real public loan-performance data has now arrived in the repository — Fannie Mae
Single-Family Loan Performance (2007Q1 and 2019Q1) and Home Credit Default Risk.
This is neither track, and the gap matters:

- It is **not Track A.** These are real loans with real origination dates, real
  month-end delinquency histories and real credit losses. Nothing about them is
  generated. Master §2 rule 3 does not apply — this data does not belong in
  `tests/fixtures/`, and it is legitimate input to a Bronze layer.
- It is **not Track B.** A default rate computed from 2007 US conforming
  mortgages is a fact about the US housing market, not about this bank's
  portfolio. Reporting it against a Phase 0 gate would be a category error.

Left unnamed, the second point is exactly what erodes. A number computed from
real data *looks* like gate evidence, and six months on nobody remembers which
population produced it.

## Options considered

### A. Classify it as Track A

Wrong on the facts, and it would force real data into `tests/fixtures/`, breaking
Master §2 rule 3 in the other direction — the fixture guard exists to stop
synthetic data escaping, not to pull real data in.

### B. Classify it as Track B

Gets the "real data" half right and the "whose data" half catastrophically wrong.
Track B's entire purpose is that its numbers are evidence about the bank.

### C. Name a third track

One more concept to carry, and every report and stamp has to handle it.

## Decision

**Option C — Track P (public reference data).**

| Track | Data | Proves | Gate evidence |
|---|---|---|---|
| **A** | Synthetic fixtures under `tests/fixtures/` | Code paths, failure classification | No |
| **P** | Real, externally-sourced, not this bank's | The code survives real-world messiness: real key defects, real class imbalance, real missingness, real ingestion lag | **No** |
| **B** | The bank's own data | The portfolio | **Yes** |

Track P earns its place because it tests things Track A structurally cannot. A
fixture has the defects its author thought of. Fannie Mae's 2007Q1 file has 99
distinct delinquency-month values, an `XX` unknown status on 13,944 rows in the
first million, and seven zero-balance dispositions — none of which anyone would
have invented, and all of which the Appendix A label logic has to handle
correctly.

The rule carried over from ADR-0003 is unchanged and now has one more clause:
**only Track B produces gate evidence.** Track P numbers are stamped `P` and
carry the dataset identity, so a reader always knows which population a number
describes.

## Consequences

- Real datasets live in `datasets/` (gitignored — large, and not ours to
  redistribute), never in `tests/fixtures/`.
- Every Track P report names its dataset and vintage, not just its track.
- Adapters live in `lending_hub.sources.<dataset>` and map an external schema onto
  the platform's own definitions. The mapping is `[DATA]` — derived by a committed
  script from the data itself, not from memory of a file layout.
- Phase 0 still cannot be exited on Track P. Two of the four numeric gates (GL
  reconciliation, scorecard parity) have no public analogue at all.

## Revisit if

Bank data arrives, at which point Track P narrows to a regression corpus — a
large, messy, freely-redistributable dataset for testing the pipeline, which is a
genuinely useful thing to keep.

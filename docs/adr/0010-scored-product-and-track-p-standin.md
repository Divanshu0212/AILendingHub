# ADR-0010 — The product P1 scores, and its Track P stand-in

| Field | Value |
|---|---|
| Status | Accepted (Track P scope) · Blocked (Track B scope, LH-201) |
| Date | 2026-09-01 |
| Decider | Credit Risk Head (Track B) · Data Platform Lead (Track P) |
| Workstream | WS-1.1 |
| Consulted | Product Head, Model Risk, Fraud DS |
| Related | [ADR-0003](0003-two-track-execution-model.md), [ADR-0004](0004-public-reference-data-track.md) |

## Context

Phase 1 §1 scopes the phase to **one retail product** — "highest-volume unsecured
product; decision recorded as ADR-010". Everything downstream inherits from that
choice: the target table, the feature set, the bad rate, the ≥ 1,500-bads entry
test, the fairness segments, and the legacy scorecard the challenger must beat.

Two things about this decision are commonly conflated, and separating them is the
whole point of this ADR:

1. **Which product.** "Highest-volume unsecured" is a `[DATA]` claim about this
   bank's book. Nobody in this repository can compute it — origination volumes
   live behind LH-120, the data-sharing approvals that are still a Phase 0 *entry*
   criterion. Picking a plausible product here ("personal loans, obviously") would
   be precisely the invented-value failure Master §2 rule 1 exists to stop, and it
   would be invisible six months later.
2. **What we build against in the meantime.** ADR-0004 established Track P: real
   public data, exercised to prove the code survives real-world messiness, never
   quoted as gate evidence. Phase 1's modelling code needs a real portfolio with
   a real target to be worth anything, and Track P can supply one.

## Options considered

### A. Name a product now and proceed

Fast, and wrong in the specific way this program is built to prevent. The product
choice determines the bad rate, which determines whether the ≥ 1,500-bads entry
test passes, which determines whether the challenger is in scope at all. A guess
here propagates into a scope decision that reads as evidence-based.

### B. Block all of WS-1.1 until LH-201 resolves

Defensible, and it stalls three months of engineering behind an approval that is
not about engineering. Phase 0 already established the alternative: build the
interface, run it on Track P, label every number with the track that produced it.

### C. Split the decision — Track B product `[POLICY]`-blocked, Track P stand-in chosen now

Keeps the ungrounded half ungrounded and lets the buildable half proceed.

### D. Use one Track P dataset for everything

Simpler to explain, and neither candidate can carry the whole phase. See below.

## Decision

**Option C.** The Track B product slot stays `TBD[Product Head, LH-201]`. Track P
work proceeds against **two** datasets, each used only for what it can actually
support:

| Phase 1 need | Dataset | Why this one, and not the other |
|---|---|---|
| Application scorecard on an unsecured retail product | **Home Credit Default Risk** — cash and revolving consumer loans | The right *product shape*: unsecured, consumer, 307,511 applications, ~8% bad rate, one row per application. Fannie Mae is 30-year secured mortgages — a different risk process with a different feature set |
| Fairness testing (§4 Step 7) | **Home Credit** | It is the only source here carrying gender, age and region. Fannie Mae's public release strips every protected attribute, so a fairness harness run on it would test nothing and report clean |
| Out-of-time vintage discipline (§4 Step 1) | **Fannie Mae 2007Q1 / 2019Q1** | It is the only source with an absolute time axis. Two vintages either side of the worst mortgage credit event on record is a genuinely hostile out-of-time test, not a rehearsal |
| Reject inference (§4 Step 8) | **Neither** | Home Credit's `previous_application.csv` — the file carrying Approved/Refused/Canceled — was not supplied, and Fannie Mae contains only acquired loans. No declined applications exist in this repository, so reject inference is not exercisable. Recorded as a model-card limitation, never as a fabricated outcome |

Home Credit is `point_in_time_unsafe` in the source registry: every time column is
a relative day offset from an unstated per-application reference date. It
therefore **cannot** produce the vintage split Phase 1 §4 Step 1 mandates. The
splitter refuses rather than falling back to a random split, and any metric
produced from a non-temporal holdout is stamped `out_of_time=false` so it cannot
be quoted as an out-of-time number. That is why the split is two datasets rather
than one: the dataset with the right product has no clock, and the dataset with
the clock has the wrong product.

## Consequences

**Easy.** Every WS-1.1 step is exercisable on real loans today. The scorecard,
binning, calibration, fairness and validation code all run against a real target
with real missingness and real imbalance, which is what makes the reference
implementation worth anything when the Track B swap happens.

**Hard.** Two datasets means two adapters and two sets of caveats on every report.
The Phase 1 gate pack has to carry a per-number track *and dataset* label, not
just a track label.

**Locked in.** Nothing. Every model here records the dataset it trained against
alongside the Appendix A fingerprint, so re-fitting on the Track B product is a
data swap, not a rewrite. What is deliberately *not* locked in is the product
choice itself: no code branches on "personal loan".

**Not claimed.** Neither dataset's target is Appendix A. Home Credit's `TARGET` is
its own vendor definition of payment difficulty; Fannie Mae's labels are produced
by the Phase 0 adapter mapping delinquency months onto Appendix A, which holds for
that source and says nothing about a bank CBS. Every Track P metric is a statement
about US consumer credit or US conforming mortgages, and about nothing else.

## Revisit if

- LH-120 lands and real origination volumes make the "highest-volume unsecured"
  determination computable — at which point LH-201 resolves and this ADR is
  superseded for Track B.
- `previous_application.csv` is re-downloaded, which makes reject inference
  exercisable and reopens §4 Step 8.
- A Track P dataset arrives that has both an absolute time axis and protected
  attributes, which would collapse the two-dataset split back to one.

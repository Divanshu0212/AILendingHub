# ADR-0011 — Entity-resolution library

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-09-01 |
| Decider | Fraud DS Lead |
| Workstream | WS-1.2 Step 1 |
| Consulted | Data Platform, Model Risk, P6 graph squad |
| Related | [ADR-0003](0003-two-track-execution-model.md) |

## Context

Phase 1 §4 WS-1.2 Step 1 requires entity resolution across applications —
"blocking + fuzzy matching: name Jaro–Winkler with threshold tuned on labeled
duplicate pairs `[DATA]`; phone/account exact; address normalized + geohash" —
and names two candidate libraries, `splink` or `recordlinkage`, deferring the
choice to this ADR.

The choice is more consequential than it looks, because the output is not a
report. It is the **entity graph** that Phase 6 trains GraphSAGE and CARE-GNN on
(Phase 1 §2, "schema designed jointly with P6"). A resolution decision that
wrongly merges two applicants creates a graph edge that does not exist, and a GNN
trained on it learns a fraud ring that is a data-quality artifact. Under-merging
is the opposite failure and is the one fraudsters engineer for.

## Options considered

### A. `recordlinkage`

Pandas-native, easy to read, good comparison primitives. Two problems at bank
scale: it is single-machine, and its default scoring is a weighted sum of
similarity scores rather than a probabilistic model, so the output is a number
whose scale means nothing outside the run that produced it. A threshold tuned on
one month's data does not transfer.

### B. `splink`

Implements the Fellegi–Sunter probabilistic model with EM-estimated `m` and `u`
probabilities, and runs on DuckDB, Spark or Athena. Two properties matter here:

1. **The output is a match probability**, not a similarity score. It is
   comparable across runs and across attribute sets, and it can be thresholded
   against a stated tolerance for false merges rather than against a number
   someone tuned by eye.
2. **`u` probabilities are estimated from random pairs**, which means the model
   knows how discriminating each attribute actually is in *this* population.
   A shared surname in a population with few distinct surnames is weak evidence,
   and Fellegi–Sunter learns that rather than being told it.

Cost: heavier dependency, a real learning curve, and EM estimation that has to be
re-run and reviewed as the population changes.

### C. Build it

Rejected by Master §2 rule 2 as a production path. A hand-rolled matcher is
exactly the kind of component that accumulates undocumented special cases.

## Decision

**Option B — `splink` for Track B.** Track A ships a stdlib reference
implementation (`lending_hub.fraud.entity_resolution`) with the same interface:
blocking, deterministic exact-match rules, Jaro–Winkler on names, and normalised
address plus geohash. It exists to prove the code paths and the graph schema, and
its tests pin the properties the Track B swap must preserve.

The Track A matcher deliberately produces a **score with an explicit floor and no
probability interpretation**, and says so in its output. Presenting a weighted
similarity as though it were a match probability is the specific defect option A
was rejected for, and reproducing it on Track A would train everyone to read the
number wrongly before the real one arrives.

**The threshold is not decided here.** Phase 1 requires it "tuned on labeled
duplicate pairs `[DATA]`", and no labelled pairs exist — nothing in the programme
plan creates them. That is LH-209, and it is a scheduling gap rather than a
committee decision: someone has to clerically label a sample of candidate pairs
before any threshold means anything.

## Consequences

**Easy.** The graph schema is fixed now, so P6 can design against it, and the
match rule can be swapped underneath without moving the tables.

**Hard.** Two matchers to keep behaviourally aligned until Track B lands. The
mitigation is that the Track A tests assert properties (symmetry, blocking
completeness, transitivity handling) rather than scores.

**Locked in.** The node and edge schema, and the rule that a merge decision is
recorded with the evidence that produced it — every edge carries the attribute
and the score that created it, because "why are these two linked" is the first
question a fraud analyst asks and the first one a model-risk reviewer asks.

**Not locked in.** The scoring model. Fellegi–Sunter is the Track B choice; the
tables do not encode it.

## Revisit if

- A labelled duplicate-pair set arrives (LH-209) and shows the deterministic
  rules alone reach acceptable precision — in which case the probabilistic layer
  is unnecessary complexity for this product.
- Volumes stay small enough for one machine, which would make `recordlinkage`'s
  simplicity worth its weaker scoring.

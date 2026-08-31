# Phase 0 — implementation findings against the phase documents

Produced while building Phase 0. Master §1 is explicit that "conflicts are raised
as tickets, never resolved silently by an implementer", so nothing here has been
edited into `Phase_0_Foundations.md`; each finding is either a ticket or a
recommendation for the document owner.

**The documents held up well.** Almost everything in Phase 0 was buildable as
written, the grounding contract is the strongest part of the set, and the
workstream decomposition needed no rearranging. The findings below are the places
where implementation actually pushed back.

---

## A. Corrections — statements that are wrong as written

### A1. The join-rate gate measures the delinquency rate (ticket LH-122)

**WS-0.1.3:** *"≥ 99.5% of active loans join across the three systems on exact
keys."*

A healthy loan has no collections record. Requiring all three systems to match
for every active loan makes the measured join rate approximately
`1 − delinquency_rate`, so a bank with a clean book fails the gate and a
deteriorating book appears to improve. On any realistic portfolio the metric
would sit near 3–8% and the phase would stall on a number that was never about
data quality.

**Recommended replacement** — three separately mandatory directions:

| Check | Direction | Mandatory because |
|---|---|---|
| `loan_to_application` | CBS → LOS | Every active loan must trace to an originating application |
| `collections_to_loan` | collections → CBS | Referential integrity; an orphan case is a real break |
| `customer_consistency` | across all three | The same loan must not carry different customer keys |

Note the asymmetry: LOS legitimately holds applications that never became loans
(declines, withdrawals), so CBS → LOS is mandatory while LOS → CBS is not.
Implemented in [identity/spine.py](../src/lending_hub/identity/spine.py).

### A2. Appendix A's default definition is not computable as specified (ticket LH-103)

Appendix A defines default as *"max DPD ≥ 90 … OR write-off, OR fraud-confirmed,
OR restructure-due-to-distress"*. The DPD arm is `[SPEC]` and computable. The
other three are not: nothing states which CBS codes constitute a write-off, or
which restructure reason codes mean *distress* rather than a voluntary
restructure. Confirmed fraud is correctly marked `[POLICY]`; the other two are
not marked at all, which reads as though they were settled.

This matters more than a missing constant. A restructure code set that wrongly
includes voluntary restructures inflates the bad rate across scoring,
provisioning and EWS simultaneously — and because all three share one definition
by design, the error is perfectly correlated and invisible in cross-checks.

**Recommended:** mark both `[POLICY]` in Appendix A.

### A3. SRS §2.1 omits two sources the phase depends on (ticket LH-121)

SRS §2.1 lists eight sources; LOS and collections are not among them. Phase 0 §2
requires both as inputs and WS-0.1.3 builds the identity spine across
CBS↔LOS↔collections. Both are registered in `config/sources/`; the SRS needs the
two rows.

### A4. Duration inconsistency

The Phase 0 card says *Months 1–4*; the Master phase index says *3–4 mo*. Trivial,
but the phase card is what a squad plans against.

---

## B. Gaps — things that are missing rather than wrong

### B1. The point-in-time contract omits the timestamp that causes leakage

This is the most consequential finding in the set.

WS-0.2.1 requires training sets to be built "only via `get_historical_features`
point-in-time joins (kills future leakage and training/serving skew at the
platform level)". It never says what point-in-time correctness *means*, and the
usual reading — "latest value with `event_timestamp ≤ observation_point`" — is
insufficient.

A feature needs **two** timestamps: when the fact became true (`event_timestamp`)
and when the platform learned it (`created_timestamp`). A bureau refresh dated
3 March that landed in the warehouse on 20 March was not knowable on 10 March.
Joining on event time alone hands the model a value production could never have
had, and the resulting lift is leakage that evaporates in shadow — after months
of work.

Delegating this to Feast does not close the gap: Feast supports the two-timestamp
join, but only if the ingestion pipeline *carries* `created_timestamp`. That is
an extract requirement, and extract teams drop the field because it looks
redundant.

**Recommended:** state the two-timestamp rule in WS-0.2.1 and add
`created_timestamp` to the WS-0.1.1 source-registry required fields.
Implemented in [featurestore/pit.py](../src/lending_hub/featurestore/pit.py).

### B2. The reproducibility test as specified passes trivially

WS-0.2.3: *"retrain a toy model twice from the same triplet → assert identical
metrics."*

A constant function passes this. So does a pipeline that ignores its config
entirely. The assertion demonstrates determinism but says nothing about whether
the triplet *determines* the model — which is the property the whole
reproducibility story rests on.

**Recommended second half:** changing any one triplet element must change the
result. If it does not, the triplet is decoration on a model card. Implemented in
[mlops/reproducibility_test.py](../src/lending_hub/mlops/reproducibility_test.py).

### B3. Eight-year reproducibility and the erasure right collide, unaddressed

SRS CS-7 requires any decision reconstructable for ≥ 8 years. SRS §11.4 gives the
data principal an erasure right under DPDP. WS-0.1.2 mandates time travel on
every table, and a snapshot preserved for reproducibility contains rows an
erasure request covers.

Neither document acknowledges the conflict, and it cannot be resolved by
engineering — it is a written legal position, per table, about which duty
overrides. It needs to be settled *before* Silver is loaded, because retrofitting
row-level erasure into a tagged snapshot history is materially harder than
designing for it.

Surfaced in [ADR-0001](../docs/adr/0001-lakehouse-table-format.md), tracked as
LH-111.

### B4. Every gate is silent about the empty-denominator case

All four numeric gates are stated as thresholds with no floor on evidence. A join
audit over an empty extract, a freshness window with no events, a parity run over
an empty sample and a load test with zero requests all produce "no failures" —
and a naive implementation reports 100%, 0 s and PASS.

This is not hypothetical; it is the standard failure mode of a monitoring
pipeline whose upstream broke over a weekend.

**Recommended:** state that an unmeasurable gate is a fail. Implemented
throughout: every rate in this codebase returns `None` on an empty denominator,
and `None` never passes.

### B5. Master §2 rule 4 assumes a CI that no document defines

Rule 4 says "CI fails the build if a `TBD` reaches a release branch". No document
in the set defines that CI, and none of the seven rules had an enforcement
mechanism. A grounding contract that depends on everyone remembering it is a
statement of intent.

**Implemented:** [tools/check_grounding.py](../tools/check_grounding.py) enforces
four of the seven rules mechanically. It caught two defects in its own author's
work within an hour of existing — an unregistered ticket in `CLAUDE.md` and
another in the tokenization module.

### B6. No path exists if entry criteria do not land

Phase 0 §3 makes written data-sharing approvals an entry criterion. The document
has no branch for the (common, and currently actual) case where they do not
arrive on time — leaving a team to choose between idling and building against
invented data, which is exactly what Master §2 forbids.

**Implemented:** [ADR-0003](../docs/adr/0003-two-track-execution-model.md).

### B7. Monetary precision is unstated

The GL reconciliation is gated at 0.1%. Summing rupee amounts as floats across
millions of rows accumulates error at the same order of magnitude as the
tolerance, so the reconciliation can end up measuring its own arithmetic.

**Recommended:** require integer minor units in the WS-0.1.5 acceptance criteria.
Applied in the stream schemas and enforced in
[lakehouse/reconcile.py](../src/lending_hub/lakehouse/reconcile.py), which raises
on float input.

---

## C. Judgement calls, recorded rather than corrected

These are places where the document is defensible and this implementation chose
differently. Flagged so the document owner can overrule.

### C1. WS-0.4 without a legacy scorecard

WS-0.4 rebuilds the existing scorecard and compares at ≥ 99.9%. If a bank has no
scorecard — or no archived per-application decisions to compare against — the
exercise as written cannot run at all, and the phase loses its proof-of-platform.

The exercise's actual content is "two independently built score paths over one
frozen sample must agree; every discrepancy root-caused". Written that way it
survives a missing legacy system, with batch-path-versus-serving-path as the
substitute reference. That is what
[serving/parity.py](../src/lending_hub/serving/parity.py) implements. It is not a
replacement for the gate; it makes the gate a rerun rather than a rewrite.

### C2. Phase 0 ships an orchestrator with no cutoffs

WS-0.2.4 ships a serving skeleton, and all decision boundaries are `[POLICY]`
from P1. The implementation therefore refers every model-scored application to a
human, with reason code `P0_NO_CUTOFF_CONFIGURED`. An alternative reading is that
the stub should return the score and no outcome. Referring is chosen because it
keeps the decision-log path exercised end to end, which is what Phase 0 is
proving.

### C3. ADRs recorded as Proposed

WS-0.1.2 and WS-0.2.3 require ADR-001 and ADR-002 "merged". Both are merged with
Status: **Proposed**. Selecting an option and arguing it is the implementer's
job; ratifying it is the Data Platform Lead's, and marking them Accepted without
that signature would be the kind of quiet assumption the grounding contract
exists to prevent. ADR-0002 in particular turns on a fact about the bank nobody
has supplied — whether Airflow is already an operated platform service.

# Phase 6 — status

**Phase 6 is ongoing by definition.** Its card says *"Month 13 onward —
steady-state operating rhythm, not a fixed project"*, and §4's exit criterion is
**standing**: it applies to every promotion, forever, rather than once at a gate
review. So this document does not report a gate outcome in the sense the earlier
phases do — there is no single moment at which Phase 6 is finished.

What it reports instead is which parts of the phase can exist before its
feedback loops have run, and that division is
[ADR-0016](../adr/0016-phase6-learning-loops-track.md).

## The one-line summary

The **protocol layer is built and tested**; **no challenger model is fitted**,
and **no lift of any kind is measured**. That is the accurate summary of a phase
whose every challenger feeds on a loop that has never iterated.

## What is built

| Module | Workstream | State |
|---|---|---|
| `learning.promotion` | §4 | **Complete.** The standing criterion, composed onto Phase 0's artifact gate. Out-of-time is checked rather than asserted |
| `learning.challenger` | §2, §4 | **Complete.** The four conditions that make two evaluations comparable, plus WS-6.3's explainability clause |
| `learning.uplift` | WS-6.4 | **Guard and mechanics complete.** Qini curve and coefficient are exact; the identifiability guard refuses any effect estimate from an unrandomized log. No meta-learner, no causal forest |
| `learning.offpolicy` | WS-6.5 | **Estimator complete.** Doubly-robust value estimation with positivity as a refusal. Pinned against an independent hand computation. The log it would run on is empty |
| `learning.graph` | WS-6.1 | **Half complete, deliberately.** Louvain and modularity run on the real P1 entity graph today. `fraud_label_density` raises — it needs a disposition per node |
| `learning.cadence` | WS-6.7 | **Complete.** The rhythm as data, with overdue detection and the never-run / not-applicable distinctions |

90 tests. `make check` is green.

## What is not built, and why each is different

| Deliverable | Named feed | Why absent |
|---|---|---|
| GraphSAGE, CARE-GNN (WS-6.1) | ≥ 18 months of fraud-desk dispositions | The graph is real; the labels are not. LH-810, blocked on LH-206 |
| Noiseprint forensics (WS-6.2) | A labelled forged-document set | No document store on any track, and no investigation function to produce labels. LH-812 |
| DeepSurv (WS-6.3) | P3 hazard benchmark | The benchmark **exists** on Track P — this one is closest to buildable, and is deferred because its promotion gate is comparative against a champion this bank runs, which does not exist |
| Sequence models (WS-6.3) | Transaction event streams | No track carries per-account event data at transaction granularity. LH-813 |
| Uplift models (WS-6.4) | Randomized action holdouts | **Unidentifiable**, not merely unmeasured. LH-811 |
| Scoring maturation (WS-6.6) | Bureau-retro, consented alt-data | Already blocked from Phase 1 (LH-207) |

## The distinction this phase adds

Phase 3 established that **not measured** and **not measurable** are different
gate states. Phase 6 needs a third, and WS-6.4 is where it bites: **unidentifiable**.

Both earlier states are about missing *data* — given the right dataset, the
number appears. WS-6.4's uplift is missing **randomization**, and no quantity of
observational action logs supplies it. A collections desk that called every
borrower an officer judged likely to cure produces a log in which treatment and
cure are confounded by that judgement, and the difference computed on it is not
a noisy estimate of τ but a different quantity, biased toward flattering the
action.

The consequence is the part worth carrying forward: **more data makes it
tighter, not truer.** A confidence interval around a confounded estimate narrows
around the wrong number, converting a visible uncertainty into an invisible
bias. That is why `estimate_uplift()` raises rather than returning a flagged
number — and why LH-811 is the one ticket in the register where waiting makes
the answer worse.

## Tickets

11 open, in [blocking_tickets.md](blocking_tickets.md), and the register is
**shaped differently from every earlier phase's**. Elsewhere a blocking ticket
is a value a committee supplies. Here the rows split into:

* **Decisions** (LH-801, 802, 804–808) — a named owner can close them tomorrow.
  Five of the seven were **found by building**; LH-806 is a scope call and
  LH-808 restates a `[POLICY]` value the phase file already names.
* **Accruals** (LH-810 to LH-813) — records that only accumulate when a desk
  operates. No escalation closes them, and each traces back to a `[POLICY]`
  value that kept the desk from being staffed.

Reporting the two identically would make a scheduling problem look like a policy
one, which is the same error Phase 3's not-measured / not-measurable distinction
exists to prevent, one level up.

Two earlier tickets block Phase 6 directly and are not restated: **LH-503** (the
exploration percentage, which already names P6 off-policy evaluation among what
it blocks) and **LH-206** (the fraud alert budget, which is why LH-810 cannot
accrue).

## Findings

Seven, in
[Phase_6_FINDINGS.md](../../Lending_Hub_Phase_Docs/Phase_6_FINDINGS.md).

## Running it

```bash
make gate6      # assemble the Phase 6 evidence pack
make test       # the 90 Phase 6 tests run inside the full suite
```

There is no `make trackp-p6`, and that is a decision rather than an omission —
ADR-0016 records why Elliptic was examined and not adopted (LH-806).

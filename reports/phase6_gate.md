# Phase 6 — gate evidence pack

Generated 2026-09-02T06:37:22.187247+00:00 by `tools/phase6_gate_report.py`.

## Read this first

**Phase 6 does not end.** Its card says "steady-state operating rhythm,
not a fixed project", and §4's criterion is *standing* — it applies to
every promotion, forever, rather than once at a review. So this pack
reports **readiness to learn**, not learning having happened.

**No lift of any kind is measured here, and no challenger model is
fitted.** A reader skimming for numbers will find none. That is the
accurate summary of a phase whose every challenger feeds on a loop that
has never iterated.

The specific misreading this pack guards against is the inverse of
Phase 5's. Phase 5 risked a structural guarantee being read as a
measurement; Phase 6 risks a **protocol being read as a result**. "The
promotion gate is built and tested" is true, and says nothing about any
model having been promoted.

Per ADR-0003 and ADR-0004, **only Track B numbers are gate evidence.**
There is **no Track P**, and that is a decision: Elliptic was examined
and not adopted (LH-806), for the reasons in
[ADR-0016](../docs/adr/0016-phase6-learning-loops-track.md).

## The standing criterion (Phase 6 §4)

Five conditions. All five are **implemented and enforced**; none has
ever been *exercised on a real promotion*, because no model in this
repository has been promoted — every promotion path terminates at an
unratified `[POLICY]` value.

| Condition | Enforced by | State |
|---|---|---|
| Measured lift on out-of-time data | `learning.promotion` | **enforced**, never exercised |
| Model card | `mlops.promotion` | **enforced**, never exercised |
| Independent validation | `mlops.promotion` | **enforced**, never exercised |
| Rollback plan | `learning.promotion` | **enforced**, never exercised |
| Online A/B where feasible | `learning.promotion` | **enforced**, never exercised |

Two of the five are worth reading closely, because both are easy to
implement backwards:

* **Out-of-time is checked, not asserted.** It is the condition a
  submitter most often violates while believing they satisfied it — a
  random split of a multi-year panel is out-of-sample and in-time, which
  is exactly the optimistic number P4-F11 describes. `EvaluationWindow`
  compares the dates.
* **The A/B sentence is about admissible evidence, not about running an
  A/B.** §4 makes offline lift inadmissible *as the sole evidence* where
  an A/B was feasible and skipped, so the gate asks "was one available?"
  rather than "did you run one?" — and `INFEASIBLE` requires a stated
  reason against a named submitter. See P6-F3.

## Workstreams (Phase 6 §2)

| WS | Name | Named feed | Built | Why |
|---|---|---|---|---|
| WS-6.1 | Graph fraud — full Layer 3 | P1 entity graph + >= 18 months of fraud-desk dispositions | **partial** | Louvain runs on the real P1 graph today because community detection is unsupervised. GraphSAGE and CARE-GNN have no labels — LH-810, blocked on LH-206 |
| WS-6.2 | Document tamper CNNs | A labelled forged-document set [DATA] | **none** | No document store on any track and no investigation function to produce labels — LH-812. The precision floor is LH-808 |
| WS-6.3 | Survival & sequence challengers | P3 hazard benchmark + transaction streams | **none** | The survival benchmark **exists** on Track P, which makes DeepSurv the closest thing here to buildable. Deferred because its gate is comparative against a champion this bank runs. Sequence models have no event data at all — LH-813 |
| WS-6.4 | Collections & action uplift | P4 action-outcome logs + randomized holdouts | **guard only** | **Unidentifiable**, not merely unmeasured — LH-811. The Qini mechanics and the identifiability guard are built and tested |
| WS-6.5 | Off-policy improvement of offers | P4 propensity logs | **estimator only** | The DR estimator is complete and pinned against a hand computation. P4's `BanditDecision` guarantees the schema; the log has no rows (ADR-0014). Exploration cell is LH-503 |
| WS-6.6 | Scoring maturation | Bureau-retro program, consented alternative data | **none** | Both blocked from Phase 1 — LH-207 (bureau retro) and the DPDP clearances alternative data needs |
| WS-6.7 | Steady-state governance rhythm | None — it is a schedule | **done** | The table as data, with overdue detection. Tolerances are LH-807 |

## The distinction this phase adds: unidentifiable

Phase 3 established that *not measured* and *not measurable* are
different gate states. WS-6.4 needs a third.

Both earlier states are about missing **data** — given the right
dataset, the number appears. WS-6.4's uplift is missing
**randomization**, and no quantity of observational action logs supplies
it. A desk that called every borrower an officer judged likely to cure
produces a log where treatment and cure are confounded by that
judgement, and the difference computed on it is a *different quantity*,
biased toward flattering the action.

The operational consequence inverts the instinct every other blocked
ticket trains: **more data makes a confounded estimate tighter, not
truer.** The interval narrows around the wrong number, converting a
visible uncertainty into an invisible bias. LH-811 is the only row in
any register in this repository with that property.

So `uplift.estimate_uplift()` raises rather than returning a flagged
number, and `BalanceReport.proves_randomization` is always `False` — a
confounded log balances on the columns someone happened to record, while
the confounder (the officer's judgement) is recorded nowhere.

## What is exact, and is therefore built and tested in full

| Component | Status |
|---|---|
| Standing criterion (`learning.promotion`) | **done** — five conditions, every failing reason returned at once, composed onto Phase 0's gate |
| Comparison contract (`learning.challenger`) | **done** — same metric, population, window and operating point, or no comparison. Each mismatch produces a *positive* lift when violated, so all four are refusals |
| Doubly-robust OPE (`learning.offpolicy`) | **done** — Dudik et al., pinned against an independent hand computation. Refuses below propensity 0.001 or effective sample 30 |
| Uplift guard and Qini (`learning.uplift`) | **done** — curve and coefficient exact; arms below 30 refused; no estimate from an unrandomized log |
| Louvain (`learning.graph`) | **done** — runs on the real P1 entity graph; deterministic node order; communities below 3 unscored |
| Governance cadence (`learning.cadence`) | **done** — 16 activities across 5 cadences, with overdue detection |

## The cadence, and why nothing is overdue

16 activities are transcribed from the WS-6.7 table: 
3 nightly, 3 weekly, 3 monthly, 4 quarterly, 3 annual.

**0 are runnable today.** Every activity's
owning phase is pre-gate, so none is late — it is *not yet applicable*,
which is a different state and is reported as one. Collapsing the two
would make this section a wall of red, which is Phase 3's
not-measured / not-measurable error appearing in a monitoring dashboard.

One activity carries the phase file's own qualifier verbatim (*fraud/EWS retrains* — "as data warrants") rather than being resolved into a hard interval, because resolving it would invent a rule.

## What is NOT built, and the reason for each

Six challenger models are absent. Each is deferred for a stated reason
rather than for absence of effort, and each becomes buildable the moment
its named feed exists.

| Model | Reference | Blocked by |
|---|---|---|
| GraphSAGE | Hamilton et al., arXiv:1706.02216 | LH-810 (dispositions) |
| CARE-GNN | Dou et al., arXiv:2008.08692 | LH-810; and camouflage is a behaviour of an adversary responding to a deployed detector |
| Noiseprint | Cozzolino & Verdoliva, arXiv:1808.08396 | LH-812 (labelled forgeries) |
| DeepSurv | Katzman et al., arXiv:1606.00931 | No champion to beat — P6-F7 |
| E.T.-RNN class | Babaev et al., arXiv:1911.02496 | LH-813 (event streams) |
| Causal forest / meta-learners | Wager & Athey; Kunzel et al. | LH-811 (holdouts) — unidentifiable |

## Model cards

None. **This is the correct state**: Master §2 rule 5 requires a card
per *model*, and Phase 6 fits none. The two components that produce
numbers — the DR estimator and Louvain — are algorithms rather than
fitted models, and a card for an unfitted challenger would document
nothing.

## Open tickets

**11 open**, in `docs/phase6/blocking_tickets.md`. The
register is shaped differently from every earlier phase's, and the shape
is the finding: rows split into **decisions** a named owner can close
tomorrow, and **accruals** that only an operating bank closes. No
escalation closes an accrual, and reporting the two identically makes a
scheduling problem look like a policy one.

| Ticket | Owner |
|---|---|
| LH-801 | Model Risk |
| LH-802 | Model Risk + Collections Head |
| LH-804 | Model Risk |
| LH-805 | Fraud Head |
| LH-806 | GenAI/Fraud squad leads |
| LH-807 | Model Risk |
| LH-808 | Fraud Head |
| LH-810 | Fraud Head |
| LH-811 | Collections Head |
| LH-812 | Fraud Head |
| LH-813 | Data Engineering |

## Gate outcome

**Not applicable — and that is not a euphemism for fail.**

Phase 6 has no exit criteria to pass. §4 states a standing rule that
applies to every future promotion, and the honest report against it is:
the rule is implemented, enforced and tested, and it has judged nothing,
because nothing has been submitted to it.

What a reviewer should take from this pack:

1. The promotion protocol exists **before** the first promotion request,
   which is the point of building it now — a rule written under pressure
   by whoever ships the first challenger is a rule shaped by that
   challenger.
2. Two guards are track-independent and hold unchanged in a real
   deployment: the identifiability refusal and the positivity refusal.
   Both are statements about what a log can support.
3. Everything else waits on a feedback loop, and four of those loops
   trace back to a `[POLICY]` value that kept a desk from being staffed.

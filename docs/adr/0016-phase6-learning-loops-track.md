# ADR-0016 — Phase 6 as a protocol, not a model shelf

| Field | Value |
|---|---|
| Status | Accepted (Track A scope) · Blocked (Track P and Track B scope) |
| Date | 2026-09-02 |
| Decider | Model Risk (A on every promotion) · DS squad leads |
| Workstream | WS-6.1 … WS-6.7 |
| Consulted | Fraud Head, Collections Head, Compliance, DPO |
| Related | [ADR-0003](0003-two-track-execution-model.md), [ADR-0013](0013-phase2-agri-track.md), [ADR-0014](0014-phase4-action-systems-track.md), [ADR-0015](0015-phase5-assistant-track.md) |

## Context

Phase 6 is the first phase in the programme that is **not a deliverable**. Its
own card says so: *"Month 13 onward — steady-state operating rhythm, not a fixed
project."* Its exit criterion in §4 is **standing** — it applies forever, to
every promotion, rather than once at a gate review.

That inverts the usual question. For P1–P5 the question was "which of this
phase's outputs can be produced here?" For P6 it is "which of this phase's
outputs is a *thing* at all?" — and the answer is that most of §2 is a shelf of
challenger models, while §4 is a rule that governs them.

### Every challenger's feed is a feedback loop that has never run

Phase 6's subtitle is *the compounding phase*: it activates loops that earlier
phases were built to feed. Each workstream names its feed, and every one of them
is an artifact produced by **an operating bank over time**, not a dataset:

| Workstream | Named feed | Why it is absent |
|---|---|---|
| WS-6.1 graph fraud | P1 entity graph + **≥ 18 months of fraud-desk dispositions** | The graph is real (`fraud.entity_resolution` builds one). The dispositions require a fraud desk that has been operating for 18 months. LH-206's alert budget is still unratified, so the desk has not been staffed, so no alert has ever been dispositioned |
| WS-6.2 document tamper | **A labelled forged-document set** `[DATA]` | Forgeries labelled by an investigator who established that they were forgeries. There is no document store here and no investigation function |
| WS-6.3 survival challengers | P3 hazard benchmark + transaction streams | The benchmark exists on Track P (Fannie Mae). The **transaction streams** do not — no track carries time-stamped per-account event data |
| WS-6.4 action uplift | P4 action-outcome logs + **randomized holdouts** | ADR-0014 already established there are no actions. A holdout is a *decision to withhold treatment from a randomly chosen customer*, which is a policy act |
| WS-6.5 off-policy offers | P4 propensity logs | `BanditDecision` guarantees a propensity is present, so the *schema* is real. No decision has been logged, because no offer has been made |
| WS-6.6 scoring maturation | Bureau-retro program (LH-207), consented alternative data | Both already blocked from Phase 1 |

This is a sharper version of ADR-0014's finding. P4 could not evaluate actions
because none had been taken; P6 cannot evaluate *improvements to* those actions,
which is one further step removed. **A learning loop with no prior iteration has
nothing to learn from**, and no amount of work inside this repository changes
that.

### But the standing rule is pure logic

§4 is one sentence and it is the most reusable artifact in the phase:

> Measured lift on out-of-time data · model card · independent validation ·
> rollback plan · online A/B where feasible. **Offline lift alone never promotes
> a model that could have been A/B tested.**

None of that needs a feedback loop. It is a set of conditions over a promotion
request, and Phase 0 already built two thirds of it — `mlops.promotion.can_promote`
checks the model card, the independent validation report, the shadow duration,
the warm fallback and the definitions fingerprint, and returns every failing
reason at once.

What §4 adds is three conditions Phase 0 had no reason to know about, and the
third is the interesting one because **it is a rule about what evidence is
admissible, not about whether a number is large enough.**

## Decision

**Build Phase 6 as the protocol layer and the identifiability guards. Fit no
challenger model, and simulate no feedback loop.**

Concretely: `lending_hub.learning` implements the standing criterion, the causal
identifiability rules, the doubly-robust off-policy estimator, the champion /
challenger comparison contract, the Louvain community scorer, and the governance
cadence. It fits no GNN, no DeepSurv, no sequence model and no forgery CNN, and
it manufactures no disposition, outcome or holdout.

### What is exact, and is therefore built and tested in full

| Component | Why it is exact |
|---|---|
| **The standing promotion criterion** (`learning.promotion`) | Five conditions over a promotion request. Whether a rollback plan is attached, whether lift was measured out-of-time, and whether an A/B was feasible-but-skipped are decidable given the request. This is §4 in executable form and it is the phase's most valuable artifact |
| **Out-of-time window validation** (`learning.promotion`) | Whether an evaluation window post-dates a training window is a date comparison. "Out-of-time" being *checked* rather than *asserted by the submitter* is what makes the rule real |
| **Doubly-robust off-policy estimation** (`learning.offpolicy`) | Dudík, Langford & Li's estimator is a closed-form expression over logged (action, propensity, reward) triples and a reward model. Given the inputs, the estimate and its variance are arithmetic, and can be pinned against hand-computed values |
| **Propensity hygiene** (`learning.offpolicy`) | Positivity, support overlap, and the effective sample size that decides whether an estimate means anything are all computable from a log. Refusing an estimate on a log with a zero propensity is a mathematical necessity, not a policy |
| **Uplift identifiability** (`learning.uplift`) | Whether a treatment assignment was randomized is a property of the log, and it is the *only* thing separating a causal claim from a correlation. Decidable, and the phase file makes it standing policy |
| **Qini / uplift curve mechanics** (`learning.uplift`) | Given treatment, control and outcome columns, the curve and its coefficient are arithmetic |
| **Louvain modularity optimisation** (`learning.graph`) | Blondel et al.'s algorithm is deterministic given a node ordering. It runs on the P1 `EntityGraph` today, because community detection is **unsupervised** — it is the one WS-6.1 component whose feed is not a disposition log |
| **The champion/challenger contract** (`learning.challenger`) | What a challenger must produce to be *comparable* to a champion — same out-of-time window, same population, same metric, same decision threshold — is a specification, and violating it is detectable |
| **The governance cadence** (`learning.cadence`) | §2 WS-6.7's table of nightly/weekly/monthly/quarterly/annual activities, with each item's owning phase. A schedule with overdue detection is exact |

### What is structurally unmeasurable here

| Standing criterion component | Why no data reachable from here produces it |
|---|---|
| Measured lift on out-of-time data | Requires a champion in production and a challenger evaluated against it. No model in this repository has ever been promoted, because every promotion path terminates at an unratified `[POLICY]` value |
| Online A/B | Requires live traffic |
| Qini coefficient (WS-6.4) | Requires randomized action holdouts. **Unidentifiable in principle** from what exists, not merely unmeasured — see below |
| DR estimate on real logs (WS-6.5) | The estimator is implemented and tested; the log it would run on is empty |
| +recall at fixed alert budget (WS-6.1) | Requires the alert budget (LH-206) and 18 months of dispositions |
| Forgery precision (WS-6.2) | Requires a labelled forged-document set and a `[POLICY: Fraud Head]` floor |

### The distinction this phase adds: unmeasured versus unidentifiable

Phase 3 established that *not measured* and *not measurable* are different gate
states. Phase 6 needs a third, and WS-6.4 is where it bites.

The phase file states it plainly — *"without them, uplift is unidentifiable"* —
and this is a stronger claim than anything in P2, P3 or P4. Those phases lacked
**data**: given the right dataset, the number appears. WS-6.4 lacks
**randomization**, and no quantity of observational action logs supplies it. A
collections desk that called every borrower it judged likely to cure produces a
log in which treatment and cure are confounded by the officer's judgement, and:

* the uplift estimate from that log is not a noisy version of the causal effect;
* it is a different quantity, and it is biased in the direction that flatters
  the action — because the officer selected the cases most likely to cure.

So `learning.uplift` refuses to return an effect estimate from a log it cannot
verify was randomized, and the refusal is a type-level one rather than a warning.
The phase file makes this standing policy and adds the sentence that explains
why it is in a do-not-invent list: *"an AI assistant must never estimate uplift
from purely observational action logs and present it as causal."*

That sentence is addressed to an implementer in exactly this position.

### Why the Elliptic dataset is not a Track P for WS-6.1

Checked rather than assumed, following the ADR-0013 correction.

The phase file names Elliptic (arXiv:1908.02591) as a *public money-flow
benchmark*, and it is real and downloadable — over 200K Bitcoin transaction
nodes, 234K directed payment-flow edges and 166 node features, with a
licit/illicit label on a minority of nodes. It would run.

It tests the wrong property, in a way that matters more here than the usual
Track P caveat:

1. **The graph is a different object.** Elliptic's nodes are *transactions* in a
   payment network; the P1 entity graph's nodes are applicants, devices, phones,
   bank accounts and addresses, joined by shared-attribute edges from
   `fraud.entity_resolution`. A GNN's inductive bias is a claim about the
   neighbourhood structure, so a result on one says nothing about the other.
2. **CARE-GNN's whole subject is absent.** Dou et al.'s contribution is
   reinforcement-learned neighbour filtering *against camouflage* — fraudsters
   padding their neighbourhoods with legitimate links. Camouflage is a behaviour
   of an adversary responding to a deployed detector. Elliptic's labels come
   from a licit/illicit classification of entities, not from an adversary
   evading this bank's fraud desk.
3. **The gate is comparative and there is no champion.** WS-6.1's promotion gate
   is *+recall at the fixed alert budget vs. the P1 stack*. The P1 stack has
   never run against Elliptic and could not — it consumes application records,
   not Bitcoin transactions — so the comparison has no left-hand side.

A Gini on Elliptic would be a real number about Bitcoin, reported in a Phase 6
column. Registered as **LH-806** so the decision is revisitable, not asserted as
impossible.

## Consequences

**Positive.** The standing criterion becomes executable, and it is the one P6
artifact that Track B needs *unchanged* — a bank with all six feedback loops
running still needs a promotion rule, and this one refuses the promotions §4
says to refuse. The identifiability guard in `learning.uplift` is likewise
track-independent: it is a statement about what a log can support, and it holds
in a real deployment exactly as it holds here.

**Negative.** Phase 6 reports **no measured lift of any kind**, which is the
whole point of the phase as written. The gate pack must therefore be read as a
statement about readiness to learn, not about learning having happened. A reader
skimming for numbers will find none, and that is the accurate summary.

**Deferred.** Six challenger models are not fitted (CARE-GNN, GraphSAGE,
Noiseprint, DeepSurv, an E.T.-RNN-class sequence model, and a causal forest).
Each is deferred for a *stated* reason in the table above rather than for
absence of effort, and each becomes buildable the moment its named feed exists.

## Alternatives considered

**Fit the challengers on Track P data and report the lift.** Rejected on the
same grounds as ADR-0014's simulated collections desk, with one addition
specific to this phase. A challenger's promotion gate is *comparative*: lift
against the champion, on the same out-of-time window and population. Reporting
"DeepSurv beat the P3 GBM on Fannie Mae" would be a true sentence that answers a
question nobody asked — the champion it must beat is the model this bank runs,
on this bank's book. The comparison would look exactly like the gate evidence
and would not be it.

**Simulate a disposition log to exercise WS-6.1.** Rejected. The simulator would
encode a theory of which alerts are true, and the graph model would score well
to the extent it shared that theory — ADR-0014's argument, one loop further out
and therefore harder to spot in a report.

**Skip Phase 6 as unbuildable.** Rejected, and this is ADR-0013's lesson applied
forward. The standing criterion, the identifiability guard and the DR estimator
are the parts of P6 that *govern* the challengers, and they are groundable
today. Building them now means the promotion rule exists before the first
promotion request rather than being written under pressure by whoever is
shipping the first challenger.

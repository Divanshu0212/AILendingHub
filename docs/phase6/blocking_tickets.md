# Phase 6 — Blocking ticket register

Every `TBD[owner, ticket-id]` placeholder raised by Phase 6 work appears here.
`make grounding` reads every `docs/phase*/blocking_tickets.md` and fails on any
placeholder that appears in none of them.

Earlier registers: [Phase 0](../phase0/blocking_tickets.md) ·
[Phase 1](../phase1/blocking_tickets.md) · [Phase 2](../phase2/blocking_tickets.md) ·
[Phase 3](../phase3/blocking_tickets.md) · [Phase 4](../phase4/blocking_tickets.md) ·
[Phase 5](../phase5/blocking_tickets.md) · [Phase 7](../phase7/blocking_tickets.md).

**Phase 6's register is shaped differently from every earlier one, and the
difference is the phase.** Elsewhere a blocking ticket is a value a committee
must supply. Here most rows are *feedback loops that have not run yet* — the
fraud desk's dispositions, the collections desk's action outcomes, the
randomized holdouts. No committee can ratify those into existence; they accrue
by an operating bank doing the thing for months. So the rows below separate
**decisions** (a committee can close them tomorrow) from **accruals** (only time
and operation close them), because reporting the two identically makes a
schedule look like a policy problem.

**Two earlier tickets block Phase 6 directly and are not restated here.**
**LH-503** (the exploration percentage) already names "P6 off-policy evaluation"
among what it blocks, and it is what *guarantees* the positivity
`learning.offpolicy.evaluate_policy` requires rather than leaving it to whether
the logging policy happened to be diverse. **LH-206** (the fraud alert budget)
is why no alert was ever dispositioned, which is why LH-810 cannot accrue.

Phase 6 §5 puts these on the do-not-invent list: causal claims from
observational data (holdouts required) · alert budgets, floors, exploration %
(all `[POLICY]`) · any "improvement" not evidenced on out-of-time or online data
· training on undispositioned alerts.

## Decisions — a named owner can close these

| Ticket | Owner | Blocks | What is needed | Status |
|---|---|---|---|---|
| LH-801 | Model Risk | `learning.promotion`; `learning.challenger.assess`; every §2 promotion gate | The **minimum lift** each workstream's comparative gate requires. Phase 6 §4 says "measured lift", not "sufficient lift", and every workstream states its gate without a number: WS-6.1 "+recall at the fixed alert budget", WS-6.3 "C-index / capture-rate lift", WS-6.4 "Qini coefficient + online cure-rate lift". A default in `assess()` would silently become the bar every challenger in the programme was judged against, chosen by whoever typed it. Found by building. | open |
| LH-802 | Model Risk + Collections Head | `learning.uplift.qini_coefficient`; WS-6.4's promotion gate | The **Qini threshold** and the online cure-rate lift that accompanies it. Distinct from LH-801: a Qini coefficient is not on the same scale as a recall difference, so one number cannot serve both. Found by building. | open |
| LH-804 | Model Risk | `learning.offpolicy`; the canary decision | The **canary threshold and confidence requirement** for a DR estimate. WS-6.5 says "only positive-DR-estimate policies proceed to canary", which is a sign test on a point estimate; a value marginally above zero with an interval spanning it is not evidence. The estimator reports its standard error and applies no threshold. Found by building. | open |
| LH-805 | Fraud Head | `learning.graph`; ring alerting | The **community size and score at which a ring is alerted on**. Distinct from `MIN_COMMUNITY_SIZE`, which is an arithmetic floor below which entropy is not a meaningful quantity. This is the alerting decision, and it consumes the same fraud alert budget as LH-206 — which is itself unratified, so this ticket is downstream of that one. Found by building. | open |
| LH-806 | GenAI/Fraud squad leads | A Phase 6 Track P for WS-6.1, if one is wanted | Whether to stand up **Elliptic** (arXiv:1908.02591) as a graph-fraud reference dataset. It is real and would run. [ADR-0016](../adr/0016-phase6-learning-loops-track.md) records why it was not: its nodes are Bitcoin transactions rather than applicants, CARE-GNN's entire subject (camouflage against a deployed detector) is absent from it, and WS-6.1's gate is comparative against a P1 stack that cannot consume it. Raised rather than decided — a scope call, and the gate does not move either way. | open |
| LH-807 | Model Risk | `learning.cadence.overdue`; the monitoring dashboard | The **overdue tolerance per cadence item**. WS-6.7's table gives intervals and no grace periods, and the two are different questions: a weekly PSI check one day late is noise, a quarterly reject-inference cycle one day late may already have missed its retrain. `overdue()` takes grace as a required argument with no default. Found by building. | open |
| LH-808 | Fraud Head | WS-6.2 document tamper detection | The **forgery precision floor** `[POLICY: Fraud Head]` that WS-6.2's gate is stated against. Named in the phase file as a policy value and left unquantified. Downstream of LH-812, which is the labelled set the precision would be measured on. | open |

## Accruals — only an operating bank closes these

These are not scheduling problems that escalation fixes. Each is a record that
accumulates when a desk operates, and every one of them traces back to a
`[POLICY]` value that has kept the desk from being staffed.

| Ticket | Owner | Blocks | What is needed | Status |
|---|---|---|---|---|
| LH-810 | Fraud Head | WS-6.1 (GraphSAGE, CARE-GNN); `learning.graph.CommunityScore.fraud_label_density` | **≥ 18 months of fraud-desk dispositions.** The phase file names this as WS-6.1's feed alongside the P1 entity graph, and the graph is real. Phase 1 enforced disposition capture from day one precisely so this would exist by now; no alert has been dispositioned because the alert budget (LH-206) is unratified, so the desk was never staffed. Supervised graph learning has no labels until this accrues. | blocked on LH-206 |
| LH-811 | Collections Head | WS-6.4; `learning.uplift.estimate_uplift` | **Randomized action holdouts.** Not a dataset but a standing policy decision to withhold treatment from a randomly selected share of eligible accounts. Without it uplift is *unidentifiable* rather than merely unmeasured — no quantity of observational action logs recovers τ, because the officer's selection is the confounder and it is recorded nowhere. This is the sharpest row in the register: it is the one where waiting for more data makes the estimate worse rather than better, by narrowing the interval around a biased quantity. | blocked on LH-502 |
| LH-812 | Fraud Head | WS-6.2 | A **labelled forged-document set** `[DATA]` — documents an investigator established were forged, not documents that looked suspicious. There is no document store on any track here and no investigation function to produce the labels. | open |
| LH-813 | Data Engineering | WS-6.3 sequence challengers | **Time-stamped per-account transaction event streams.** P3's hazard benchmark exists on Track P (Fannie Mae, 338,210 account-months), so the survival half of WS-6.3 has a champion to challenge. The sequence half does not: no track carries per-account event data at transaction granularity, and Fannie Mae's monthly performance rows are not a substitute — a GRU over 12 monthly aggregates is a different model from one over a customer's transaction stream. | open |

## What is not blocked

The protocol layer. `learning.promotion`, `learning.challenger`,
`learning.cadence`, `learning.offpolicy`'s estimator and `learning.graph`'s
Louvain implementation are complete and tested, and none of them waits on a row
above. That is the point of [ADR-0016](../adr/0016-phase6-learning-loops-track.md):
the rule that governs the challengers is groundable today, and it is better
written before the first promotion request than under pressure by whoever is
shipping it.

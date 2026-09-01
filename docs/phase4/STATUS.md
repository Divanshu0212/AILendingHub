# Phase 4 — status and traceability

Maps every item on the Phase 4 §7 deliverables checklist to the artifact that
satisfies it, the track it runs on, and its honest state.

**Phase 4 is the first phase to use all three gate columns.** P1 and P3 reported
Track P numbers and blockers. P2 reported nothing measurable at all. P4 splits:
its **detection** layer has real Track P evidence on the Fannie panel, and its
**action** layer has none and cannot have any, because evaluating an action
requires having taken one. See [ADR-0014](../adr/0014-phase4-action-systems-track.md).

Last updated: 2026-09-01.

## The headline

The split is the thing to understand before reading anything else:

| Layer | Question it answers | Evidence available |
|---|---|---|
| **Detection** — PD velocity, BOCPD, agri triggers | Does deterioration precede default, and by how long? | **Yes, Track P.** The P3 hazard model is fitted on 338,210 real account-months with real defaults and real preceding trajectories |
| **Disposition** — signal precision, tier precision, SLA compliance | Was the alert *right*, and did anyone act on it? | **None, and none possible.** Precision is defined against confirmed-relevant dispositions from a collections desk (LH-510) |
| **Action** — offers, take-up, bandit reward | Did the customer accept, and was it good for them? | **None.** No offer logs, no customers, and the reward itself is undefined (LH-509) |

**Nothing here simulates a disposition, an offer or a take-up.** That is the
phase's central refusal and it is argued in ADR-0014: a simulated collections
desk authored by the same person as the detector would make every signal score
well exactly to the extent that the simulator shared the detector's theory of
default.

Ten Phase 4 tickets are open ([register](blocking_tickets.md)), LH-501 to
LH-510. Six are the Phase 4 §9 do-not-invent values. **Four were found by
building** — LH-507 (the per-officer alert cap, which is not derivable from the
portfolio alert budget), LH-508 (the three unquantified conditions inside the
two-key rule), LH-509 (the bandit reward blend), LH-510 (the disposition and
offer logs, listed as an entry criterion but never as a deliverable of any
phase).

**LH-509 is the one to read.** Phase 4 §5 Step 4 defines the bandit's reward as
"take-up blended with a seasoning risk-adjusted value proxy" and gives neither
the blend weight nor the horizon. A bandit rewarded on take-up alone learns to
offer the largest permitted loan to the customers most likely to accept — a
mis-selling engine with excellent metrics.

## Deliverables checklist (Phase 4 §7)

| # | Item | Artifact | Track | State |
|---|---|---|---|---|
| 1 | Signal catalog v1 with per-signal backtested precision | — | — | **not started** |
| 2 | PD-velocity trigger; BOCPD service with well-log unit test green | — | — | **not started** |
| 3 | Agri trigger rules wired from P2 monitoring | — | — | **not started** |
| 4 | Case-management routing; disposition/outcome capture enforced | — | — | **not started** |
| 5 | Fatigue guardrails (caps, auto-retirement) configured | — | — | **not started** |
| 6 | EWS backtest report + silent-run review memo | — | — | **not started** |
| 7 | Feasible-set library + golden-file tests; pricing on ALM config | — | — | **not started** |
| 8 | Take-up model + card; LinUCB with propensity logging verified | — | — | **not started** |
| 9 | Exploration-cell approval record; suitability audit process live | — | — | **not started** |
| 10 | Independent validation for EWS ranking model and bandit design | — | — | **not started** |

## Exit criteria (Phase 4 §8)

| # | Criterion | State |
|---|---|---|
| 1 | EWS backtest + silent-run meet targets (capture ≥ 55% at ≥ 60-day lead; Red precision ≥ 25%) | **split** — capture and lead time are measurable on Track P; **Red precision is not measurable** without dispositions (LH-510) |
| 2 | Alert SLA compliance ≥ 90% in first live month | **not measurable** — no live month, no case-management system, and the SLAs themselves are LH-502 |
| 3 | Recommendation A/B (bandit vs static) shows take-up lift with no vintage-risk deterioration at 3 months | **not measurable** — needs live traffic and a 3-month observation window |
| 4 | Suitability audit clean | **not measurable** — audits recommendations actually made; none are |
| 5 | Propensity logging completeness = 100% | **provable on Track A** — a structural property of the decision type rather than a measurement, and the one criterion this repository can fully satisfy |

**Track B evidence: 0 of 5.**

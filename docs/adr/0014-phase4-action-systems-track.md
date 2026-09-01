# ADR-0014 — Phase 4 on Track P: what an action system can prove without acting

| Field | Value |
|---|---|
| Status | Accepted (Track A + Track P scope) · Blocked (Track B scope, LH-120) |
| Date | 2026-09-01 |
| Decider | Credit DS Lead (Track P) · Model Risk (Track B) |
| Workstream | WS-4.A (EWS), WS-4.B (Recommendation engine) |
| Consulted | Collections (action owner), ALCO, Credit Policy, Model Risk |
| Related | [ADR-0003](0003-two-track-execution-model.md), [ADR-0004](0004-public-reference-data-track.md), [ADR-0012](0012-phase3-panel-source.md), [ADR-0013](0013-phase2-agri-track.md) |

## Context

Phase 4 is the first phase in this programme that **acts**. Every phase before it
produced a number: a score, a stage, a provision, an index. Phase 4 produces an
*alert routed to a human with an SLA* and an *offer made to a customer*. Phase 4
§1 is explicit — "Both are action systems — every automated action has an owner,
an SLA, and a captured outcome."

That changes what a track means, and the change runs in both directions.

**The inputs are in better shape than any previous phase.** Phase 4 §2 lists its
inputs as the P3 hazard model, P1 PDs, the P2 plot stream and cash-flow features.
The P3 hazard model *exists and is fitted on a real 19-year panel of 338,210
account-months* (ADR-0012). So unlike Phase 2, which had no substrate at all,
Phase 4's central mechanism — deterioration in a fitted hazard, measured over
time — has real data underneath it.

**The outputs are in worse shape than any previous phase.** A score can be
evaluated against an outcome that already happened. An *action* can only be
evaluated against what happened when it was taken, and nothing here takes any
action. There is no case-management system, no collections officer, no customer
to make an offer to. Phase 4 §3 requires 24 months of alert dispositions and
offer logs (LH-510) precisely because the phase cannot be evaluated on anything
else.

This produces a split that no earlier ADR had to draw.

## Decision

**Build every Phase 4 component on Track A, and take the EWS *detection* layer to
Track P on the Fannie Mae panel. Do not simulate a single disposition, offer,
take-up or reward.**

Concretely:

1. **Detection is measurable and goes to Track P.** Whether a hazard model's
   30-day velocity identifies accounts that later default, at what lead time and
   with what precision, is a question the Fannie panel answers. `make trackp-p4`
   runs the PD-velocity trigger and the §4 Step 6 backtest against it and reports
   capture rate and lead-time distribution as Track P numbers.

2. **Disposition is not measurable and is not simulated.** Signal *precision* per
   Phase 4 §4 Step 1 is defined against confirmed-relevant dispositions — a human
   judgement recorded by a collections desk. There is no desk. So
   `SignalDefinition.shippable` returns False with a reason for every signal, and
   the ship gate is reported as blocked rather than passed with an invented
   precision. This is the phase's central refusal.

3. **The recommendation engine is Track A only, and the bandit does not run.**
   `LinUCB` is implemented and unit-tested on its mathematical properties. It is
   never fitted on a reward, because the reward is undefined (LH-509) and every
   input it would need — offer logs, take-up outcomes, seasoning — is LH-510. A
   bandit trained on synthetic rewards is not a demonstration of a bandit; it is
   a demonstration of the synthetic reward.

4. **Propensity logging is built as a hard requirement, not a feature.**
   Phase 4 §5 Step 4 and §8 both require 100% propensity logging because P6's
   off-policy evaluation is impossible without it. So the bandit *cannot return a
   decision without a propensity* — it is a constructor invariant, not a logging
   call somebody remembers to make. This is the one part of the phase that can be
   fully proven without any data at all.

## Why simulating the missing half would be worse than absent

This deserves stating because Phase 4 is unusually easy to fake convincingly. A
simulated collections desk with a plausible disposition rate produces a signal
catalogue with precisions, a passing ship gate, a populated alert stream and a
bandit that visibly learns. Every number would be a property of the simulator.

Phase 3 established the discipline that catches this: an in-sample comparison
measures capacity rather than skill (finding P3-F14). Phase 4's version is worse,
because the simulator would be *authored by the same person as the detector*, so
the alerts and the ground truth would share their assumptions. A signal would
score well precisely to the extent that the simulator implemented the same theory
of default.

The correct output is a signal catalogue where every entry says "precision not
measured — LH-510", which is a true statement a Track B team can act on.

## What this genuinely establishes

* **PD-velocity is measurable, and the lead-time question is answerable.** On the
  Fannie panel there are real defaults with real preceding trajectories, so
  "does hazard deterioration precede default, and by how long" is a real
  question with a real answer. That is the core EWS claim.
* **The feasible-set library is fully provable.** EMI, FOIR and DSCR are
  arithmetic on policy caps. Phase 4 §5 Step 1 asks for golden-file tests against
  hand-computed examples, and those need no data — only the caps, which are
  LH-504 and are therefore required arguments rather than defaults.
* **Propensity completeness is provable at 100%** without a single real decision,
  because it is a structural property of the decision type.
* **The two-key rule's under-specification is demonstrable.** Implementing "change-point
  + negative direction + PD-velocity confirmation" requires three thresholds the
  phase file does not give, which is LH-508 and was found by building.

## Consequences

* Phase 4's gate pack will report a **mix** of not-measured, not-measurable and
  Track-P-measured, which is the first phase to use all three columns. That is
  the honest shape: detection has evidence, action has none, and the two are not
  interchangeable.
* The P3 staging engine's `ews_enabled` flag can now be exercised end to end —
  `portfolio.staging` has carried "EWS red flags are not wired (P4 not shipped)"
  since Phase 3, and the wiring exists after this phase even though no live flag
  flows through it.
* A Track B team receives a complete detection layer with measured lead times on
  real data, a complete rules-and-pricing layer awaiting its config, and a bandit
  that will refuse to make a decision it cannot log a propensity for.

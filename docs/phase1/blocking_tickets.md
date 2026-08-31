# Phase 1 — Blocking ticket register

Every `TBD[owner, ticket-id]` placeholder raised by Phase 1 work appears here.
`make grounding` reads every `docs/phase*/blocking_tickets.md` and fails on any
placeholder that appears in none of them.

Phase 0's register is [docs/phase0/blocking_tickets.md](../phase0/blocking_tickets.md);
several of its tickets (LH-101 confirmed-fraud taxonomy, LH-103 default-code sets,
LH-120 data-sharing approvals) block Phase 1 as hard as they block Phase 0, and
are not repeated here.

Phase 1 §8 puts these on the do-not-invent list: approve/decline cutoffs ·
review-band edges · canary % · monotonicity direction list · reason-code wording ·
fairness action thresholds · fraud alert budget · step-up friction tolerance.
Each one below is a stop, not a gap in the engineering.

| Ticket | Owner | Blocks | What is needed | Status |
|---|---|---|---|---|
| LH-201 | Product Head + Credit Risk Head | ADR-0010; every WS-1.1 step on Track B | Which retail product P1 scores. Phase 1 §1 says "highest-volume unsecured", which is a `[DATA]` fact about this bank's book and is not computable until LH-120 lands. The choice sets the bad rate, and therefore whether the ≥ 1,500-bads entry test passes and whether the challenger is in scope at all. | open |
| LH-202 | Credit Risk Head | WS-1.1 Step 4 (challenger `monotone_constraints`); every feature in the catalogue | The ratified monotonicity direction list: for each feature, whether PD must be non-increasing or non-decreasing in it. Phase 1 §8 do-not-invent. A direction read off the training fit is not a constraint — it is a restatement of the fit, and it removes the only thing the constraint was there to provide. | open |

## Why this register starts empty

It does not stay empty. It is committed ahead of the placeholders it will hold so
that the first Phase 1 `TBD` has somewhere to land — `make grounding` fails a
placeholder that cites an unregistered ticket, and the fix for that failure must
never be "delete the placeholder".

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
| LH-203 | Compliance | WS-1.1 Step 6 reason-code service; every adverse-action letter | The approved reason-code dictionary and its customer-facing wording. Phase 1 §8 do-not-invent. The mapping table is *data* editable by legal, not code — so the code ships with codes and no sentences, and a decision record stores the code rather than rendered text. | open |
| LH-204 | Credit Risk Committee | Orchestrator band config; Phase 1 §5 canary | Approve/decline cutoffs, review-band edges, and the canary traffic percentage. All three are Phase 1 §8 do-not-invent. They live in `config/policy_bands.yaml` as registered placeholders under dual-control approval, never as code constants — Phase 1 §5.2 is explicit that a cutoff in code cannot be changed under dual control, because changing it is a deployment. | open |
| LH-205 | Fair-Lending Committee | WS-1.1 Step 7 fairness verdicts; model-card sign-off | The disparity level at which a model requires mitigation, and which metric it is measured on. Phase 1 §8 do-not-invent. The four-fifths rule is a US employment-law convention, not a ratified Indian lending policy; `FairnessReport.verdict()` raises rather than adopting it, because an unratified bar written into a model card is quoted for years as though it had been agreed. | open |
| LH-207 | Credit Risk Head + Procurement | WS-1.1 Step 8 reject inference | Whether bureau retro data on this bank's declined applicants is purchasable, at what match rate, and under what consent basis. Phase 1 §4 Step 8 makes the first release's method conditional on it: with retro data the selection bias is corrected from evidence, without it the bias is only documented. Track P cannot substitute — Home Credit's `previous_application.csv`, the file carrying declined applications, was not supplied (ADR-0010). | open |
| LH-209 | Fraud Head + Fraud Operations | WS-1.2 Step 1 match threshold; ADR-0011 | A labelled set of duplicate/non-duplicate application pairs. Phase 1 §4 WS-1.2 Step 1 requires the Jaro-Winkler threshold "tuned on labeled duplicate pairs `[DATA]`" — but no workstream in the programme plan produces that set. This is a **scheduling gap, not a committee decision**: someone has to clerically label a stratified sample of candidate pairs before any threshold, or any precision claim about entity resolution, means anything. Raised as a Phase 1 finding. | open |
| LH-210 | Payments Operations | WS-1.2 Step 5 IFSC validity check | The authoritative bank-branch directory (or the NPCI/RBI lookup) that says whether a format-valid IFSC names a branch that exists. Format validity is a regex and is `[SPEC]` from the public RBI format; existence is a lookup. A forger who knows the format passes the regex every time, so a green "IFSC valid" from the format check alone is close to worthless as a control while reading exactly like a meaningful one on a checklist. | open |
| LH-206 | Fraud Head | WS-1.2 Step 6 routing; Phase 1 §7 fraud precision criterion | The operating alert budget — what fraction of applications the fraud desk can review, given its capacity and the bank's risk appetite. Phase 1 §8 do-not-invent. Distinct from the 0.5% rate Phase 1 names for *evaluating* recall, which is `[SPEC]`: same units, different number, and using the evaluation rate as an operating budget because it happens to be written down is an easy and expensive mistake. | open |
| LH-208 | Credit Risk Head | `Scorecard.points`; every score band, cutoff and customer-facing score | The score-scale anchor: the reference score and the good:bad odds at it. Phase 1 fixes PDO = 20 `[SPEC]`, which fixes the slope of `points = offset + factor·ln(odds)`; nothing in the SRS or the phase file fixes the intercept, and SRS CS-2's "e.g., 300–900" is an illustration. Two of the three scaling constants are ungrounded, so no points value is computable. Raised as a Phase 1 finding — see [Phase_1_FINDINGS.md](../../Lending_Hub_Phase_Docs/Phase_1_FINDINGS.md). | open |

## Why this register starts empty

It does not stay empty. It is committed ahead of the placeholders it will hold so
that the first Phase 1 `TBD` has somewhere to land — `make grounding` fails a
placeholder that cites an unregistered ticket, and the fix for that failure must
never be "delete the placeholder".

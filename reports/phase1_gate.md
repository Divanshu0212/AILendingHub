# Phase 1 — gate evidence pack

Generated 2026-08-31T21:13:44.089306+00:00 by `tools/phase1_gate_report.py`.

Per ADR-0003 and ADR-0004, **only Track B numbers are gate evidence.**
Track P results below prove the code paths against real applications and
say nothing about this bank's portfolio.

## Exit criteria (Phase 1 §7)

| # | Criterion | Workstream | Track | Measured | State |
|---|---|---|---|---|---|
| 1 | Challenger ≥ +3 Gini over rebuilt legacy, out-of-time | WS-1.1 Step 9 | P | -0.07 pts | not evaluable — measured on a test set that is NOT out of time; this number cannot satisfy the criterion as written |
| 2 | Brier ≤ legacy | WS-1.1 Step 9 | P | 0.06961 vs 0.06906 | fail (Track P) |
| 3 | Swap set shows no adverse-segment concentration | WS-1.1 Step 9 | P | worst segment 60-69 at 1.86x | not evaluable — no bar (LH-205) |
| 4 | Fraud precision at operating alert budget ≥ incumbent rules | WS-1.2 Step 3 | — | — | **not measured** |
| 5 | Step-up friction on eventual-good customers < 3% | WS-1.2 Step 6 | — | — | **not measured** |
| 6 | Decision-log spot audit: 100 re-scored decisions identical | Master §3.3 | — | — | **not measured** |
| 7 | Model cards + independent validation signed for every shipped model | Master §2 rule 5 | — | — | **not measured** |

Criteria with **Track B evidence: 0 of 7.** Phase 1 is not exitable, and the
reason is upstream: Phase 0 has not started (LH-120, written data-sharing
approvals) so no bank data exists to measure against.

## Fraud criteria

Criteria 4 and 5 are not merely unmeasured — they are **not evaluable at all**.
Master Appendix A defines confirmed fraud as a disposition code in the approved
taxonomy; the taxonomy is `[POLICY: Fraud Head]` and does not exist (LH-101).
Until it does, any count of confirmed frauds is a count of whichever codes
someone chose, and both the alert-precision criterion and the Phase 1 §4
WS-1.2 Step 3 scope test rest on that count. See
[Phase_1_FINDINGS.md](../Lending_Hub_Phase_Docs/Phase_1_FINDINGS.md) finding P1-F5.

## Decision-log spot audit

`lending_hub.decisionlog.spot_audit` is built and tested at zero score
tolerance (Master §3.3). It needs logged production decisions, and the
orchestrator has decided nothing: every band edge in `config/policy_bands.yaml`
is a registered placeholder (LH-204), so every scored application is referred.

## Model cards (Master §2 rule 5)

| Card | Signed |
|---|---|
| `application_pd_challenger.md` | **no** |
| `application_pd_champion.md` | **no** |

An unsigned card is not a completed card. Master §3.1 requires an
independent validator who is not the developer; none exists on Track P,
and `lending_hub.mlops.promotion` refuses the transition on that basis.

## Open Phase 1 blockers

| Ticket | Owner |
|---|---|
| LH-201 | Product Head + Credit Risk Head |
| LH-202 | Credit Risk Head |
| LH-203 | Compliance |
| LH-204 | Credit Risk Committee |
| LH-205 | Fair-Lending Committee |
| LH-207 | Credit Risk Head + Procurement |
| LH-209 | Fraud Head + Fraud Operations |
| LH-210 | Payments Operations |
| LH-206 | Fraud Head |
| LH-208 | Credit Risk Head |

Phase 0 tickets that also block Phase 1: **LH-101** (fraud taxonomy),
**LH-103** (default code sets), **LH-120** (data-sharing approvals).
Full register: [docs/phase1/blocking_tickets.md](../docs/phase1/blocking_tickets.md).

## Track P run (not gate evidence)

Dataset `home_credit_default_risk`, seed 20260901, 43.8s.

| Model | Test Gini | Brier | ECE | Score PSI |
|---|---|---|---|---|
| Champion (WOE scorecard) | 47.66 | 0.06906 | 0.00537 | 0.0017 |
| Challenger (monotone GBM) | 47.60 | 0.06961 | 0.00785 | 0.0013 |

Reproduce with `make trackp-p1`. Every limitation is listed in the run
report's `limitations` block — the split is not out of time, the label is
the vendor's, and the challenger carries no ratified monotone constraints.

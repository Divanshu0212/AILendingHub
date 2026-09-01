# Phase 4 — gate evidence pack

Generated 2026-09-01T19:45:57.752732+00:00 by `tools/phase4_gate_report.py`.

**Phase 4 is the first phase to use all three columns.** Its detection
layer has real Track P evidence; its action layer has none and can have
none, because evaluating an action requires having taken one; and one
criterion is provable on Track A because it is a structural property of a
type rather than a measurement. See
[ADR-0014](../docs/adr/0014-phase4-action-systems-track.md).

Per ADR-0003 and ADR-0004, **only Track B numbers are gate evidence.**

## Exit criteria (Phase 4 §8)

| # | Criterion | Workstream | Track | Measured | State |
|---|---|---|---|---|---|
| 1 | EWS backtest + silent-run meet targets | WS-4.A Step 6 | P | capture 0.911 at p90, median lead 562.5d (Track P) | **split**: capture and lead time are measured out of time on a real mortgage panel; **tier-Red precision is not measurable**, because it needs collections dispositions (LH-510) and the default outcome is not a substitute — it would score an alert that found distress the bank cured as a false positive. Not gate evidence: US conforming mortgages, not this bank's book (ADR-0012, ADR-0014) |
| 2 | Alert SLA compliance >= 90% in first live month | WS-4.A Step 5 | — | — | **not measurable** — there is no live month, no case-management system (Phase 4 §3 entry criterion, LH-120), and the SLAs themselves are unratified (LH-502) |
| 3 | Recommendation A/B (bandit vs static) shows take-up lift with no vintage-risk deterioration at 3 months | WS-4.B Step 4 | — | — | **not measurable** — needs live traffic through two policies and a 3-month observation window. The bandit is built and refuses to learn, because its reward is undefined (LH-509) and there are no offer logs (LH-510) |
| 4 | Suitability audit clean | WS-4.B Step 5 | — | — | **not measurable** — an audit reviews recommendations actually made; none are (LH-510). The two checks §5 Step 5 names are implemented and the audit refuses to sign itself off — §5 Step 5 specifies a *human* monthly audit, and an automated control clearing its own subject would make this criterion a claim the code makes about itself |
| 5 | Propensity logging completeness = 100% | WS-4.B Step 4 | A | 100% by construction | **provable on Track A** — `BanditDecision` cannot be constructed without a propensity, so completeness is a property of the type rather than a measurement. The only Phase 4 criterion this repository fully satisfies; still not gate evidence, because no decision has been made against a customer |

**Track B evidence: 0 of 5.**

## Nothing here is simulated

Phase 4 is unusually easy to fake convincingly. A simulated collections
desk with a plausible disposition rate produces a signal catalogue with
precisions, a passing ship gate, a populated alert stream and a bandit
that visibly learns — and every number would be a property of the
simulator.

It would also be worse than Phase 3's in-sample error (P3-F14), because
the simulator would be authored by the same person as the detector: a
signal would score well exactly to the extent that the simulator shared
the detector's theory of default.

So no disposition, offer, take-up or reward is generated anywhere in this
phase. The signal catalogue reports every signal as unshippable with its
reason, which is a true statement a Track B team can act on.

## What the Track P run established

The alert percentile is unratified (LH-501), so the run sweeps bands
rather than choosing one. This table is what a Collections Head needs
to set the budget: it maps alert volume onto capture rate on a real
book.

| Band | Alerts | Accounts | Capture | Median lead | Meets 55% target |
|---|---|---|---|---|---|
| p90 | 6,404 | 917 | 0.911 | 562.5d | yes |
| p95 | 3,526 | 641 | 0.861 | 365d | yes |
| p98 | 1,420 | 433 | 0.822 | 183d | yes |
| p99 | 687 | 330 | 0.564 | 153d | yes |

Panel: 5,081 loans, 338,210 account-months.

**Denominator:** 101 reachable defaults of 827 in the panel. The other 726 fall before the first held-out snapshot (2013-02-28) and could not have been alerted on by construction, so counting them would measure the train/test split rather than the detector. The 2007Q1 vintage front-loads its defaults into the 2008-11 credit event, which sits entirely inside the training window — see finding P4-F11.

## Model cards (Master §2 rule 5)

| Card | Signed |
|---|---|
| linucb_offer_bandit.md | **no** |
| pd_velocity_ews.md | **no** |

None signed: Master §3.1 requires an independent validator who is not
the developer, and there is none.

## Open blocking tickets

| Ticket | Owner |
|---|---|
| LH-501 | Collections Head |
| LH-502 | Collections Head |
| LH-503 | Credit Risk Committee |
| LH-504 | Credit Policy |
| LH-505 | ALCO |
| LH-506 | Credit Policy + Compliance |
| LH-507 | Collections Head + Operations |
| LH-508 | Credit Risk Committee + Collections Head |
| LH-509 | Model Risk + Credit Risk Committee |
| LH-511 | Credit Risk Head + Collections Head |
| LH-512 | Credit Risk Head + Collections Head |
| LH-513 | ALCO + Data Platform |
| LH-510 | Collections Head + Data Platform |

13 open. Six are Phase 4 §9 do-not-invent values.
**Seven were found by building** — LH-507 (a per-officer cap is not a
portfolio budget), LH-508 (the two-key rule quantifies none of its
three conditions), LH-509 (the bandit reward blend), LH-511 (absolute
or relative velocity), LH-512 (BOCPD confidence depends on the
preceding regime), LH-513 (ALM table staleness), and LH-510 (the
disposition and offer logs, listed as an entry criterion but produced
by no phase).

**LH-509 is the one to read.** Phase 4 §5 Step 4 defines the bandit's
reward as "take-up blended with a seasoning risk-adjusted value
proxy" and gives neither the weight nor the horizon. A bandit rewarded
on take-up alone learns to offer the largest permitted loan to whoever
is likeliest to accept it — a mis-selling engine whose own reward
curve looks like success.

## Gate outcome

**Fail.** No criterion has Track B evidence and three cannot have any
without a deployed case-management system and live traffic.

What a Track B team receives: a detection layer with measured lead times
on real data, a complete rules-and-pricing layer awaiting its config, and
a bandit that will refuse to make a decision it cannot log a propensity
for or to learn from a reward nobody has defined.

# Phase 3 — gate evidence pack

Generated 2026-09-01T17:42:01.181025+00:00 by `tools/phase3_gate_report.py`.

Per ADR-0003 and ADR-0004, **only Track B numbers are gate evidence.**
Track P results below prove the code paths against real mortgage
performance data and say nothing about this bank's portfolio.

## Exit criteria (Phase 3 §7)

| # | Criterion | Workstream | Track | Measured | State |
|---|---|---|---|---|---|
| 1 | Hazard GBM C-index ≥ Cox + 0.02 and ≥ 0.75 absolute | WS-3.1 Step 3 | P | C 0.5285 vs Cox 0.6967, uplift -0.1682 (Track P) | measured **out of sample** on accounts held out of both fits (Phase 3 finding D6 — an in-sample version of this comparison favoured the ensemble by its own memorisation and flipped sign with sample size). Not gate evidence: Track P is US conforming mortgages, not this bank's book (ADR-0012). Also: 88% of subjects are censored; Harrell's C is biased upward at this level (Uno et al. 2011). Read it as an upper bound and compare only against other Harrell's C values on the same censoring pattern. |
| 2 | PD calibration by grade within ±15% relative on backtest years | WS-3.1 Step 1 | P | out-of-time Gini 91.89 (Track P) | not evaluable — the criterion is calibration by *grade*, and grades need the score bands that LH-204 has not ratified |
| 3 | LGD MAE ≤ incumbent | WS-3.1 Step 5 | — | — | **not measurable** — there is no incumbent LGD model to compare against, and the comparison is against this bank's provisioning model (LH-120) |
| 4 | Dashboard freshness SLO met over 30 consecutive days | WS-3.2 Step 1 | P | no meaningful figure — batch pass over a static extract | not evaluable — the criterion is 30 *consecutive days* of a live streaming surface. The freshness *machinery* is built and tested (`Aggregate` cannot be constructed without a timezone-aware `as_of`, and every serialisation carries the SLO comparison); what is missing is a stream to measure |
| 5 | ECL parallel-run memo signed | Phase 3 §5 | — | — | **not measurable** — a parallel run needs a live provisioning process and a Finance signatory; neither exists outside a bank deployment |
| 6 | Staging provenance audit clean | WS-3.1 Step 7 | P | 4,253 of 5,081 undeterminable (84%) | not evaluable — provenance is logged on every decision, but Stage 1 cannot be assigned at all without LH-301 and LH-308, so most accounts have no stage to audit |

Criteria with **Track B evidence: 0 of 6.** Phase 3 is not exitable, and
the reason is upstream of Phase 3: Phase 0 has not started (LH-120, written
data-sharing approvals), so no bank panel exists; and Phase 1 has logged no
decisions (LH-204), so there are no origination PDs for a SICR baseline.

## Not measured versus not measurable

Two criteria are **not measurable** rather than not measured, and the
distinction is not pedantry — one is a scheduling item and the other is a
structural fact that no effort inside this repository changes.

* **LGD MAE ≤ incumbent** — there is no incumbent LGD model to compare against, and the comparison is against this bank's provisioning model (LH-120).
* **ECL parallel-run memo signed** — a parallel run needs a live provisioning process and a Finance signatory; neither exists outside a bank deployment.

The clearest case sits below the criteria: **no CCF model is estimable at
all.** No revolving product exists on Track A or Track P — Fannie Mae is
amortising term debt where `L == B₀` makes the CCF denominator identically
zero, and Home Credit's revolving slice carries no limit history — and the
regulatory floor is `[POLICY]` (LH-303). `portfolio.ead.fit_ccf()` refuses
with both reasons rather than fitting the degenerate case.

## What Track P did establish

Dataset `fannie_mae_sf_loan_performance` vintage `2007Q1`, 5,081 loans and 338,210 account-months over 2007-01-01 to 2026-03-01.

**Competing risks are not optional on a mortgage book.** Treating
prepayment as censoring overstates lifetime default:

| Quantity | Value |
|---|---|
| Cumulative incidence of default at 48m | 0.1018 |
| Cumulative incidence of prepayment | 0.4171 |
| Naive figure ignoring competition | 0.1355 |
| Overstatement | 0.0338 |
| Relative overstatement | 33.2% |

**The LGD loss basis decides the sign of the LTV effect (LH-311).**

| Original LTV | Workouts | With enhancement | LGD net | LGD gross |
|---|---|---|---|---|
| 1_le_80 | 15,683 | 7.3% | 0.4285 | 0.4714 |
| 2_81_to_90 | 3,138 | 92.3% | 0.3102 | 0.5524 |
| 3_gt_90 | 1,586 | 96.0% | 0.2115 | 0.5195 |

**Covariate admissibility in the Cox reference was tested, not**
**asserted** — and one hypothesis was overturned by the test:

| Covariate | Outcome | What happened |
|---|---|---|
| `dpd_now` | rejected | the fit separated on ['max_dpd_12m', 'dpd_now'] at iteration 3: their standardised coefficients passed 20 and the information matrix then collapsed, because at that magnitude the weights inside each risk set concentrate  |
| `months_observed` | admissible | the covariate fitted; the hypothesis above does not hold here |

## Model cards (Master §2 rule 5)

| Card | Signed |
|---|---|
| `behavioural_pd.md` | **no** |
| `discrete_time_hazard.md` | **no** |
| `lgd_recovery.md` | **no** |

An unsigned card is not a completed card. Master §3.1 requires an
independent validator who is not the developer; none exists on
Track P, and `lending_hub.mlops.promotion` refuses the transition on
that basis.

## Open Phase 3 blockers

| Ticket | Owner |
|---|---|
| LH-301 | Finance + Risk |
| LH-302 | Risk Committee |
| LH-303 | Risk Committee + Regulatory Reporting |
| LH-304 | ICAAP / ALCO |
| LH-305 | Finance Controller |
| LH-306 | Risk Reporting + Finance |
| LH-307 | Risk Reporting |
| LH-308 | Credit Risk Head |
| LH-309 | Credit Policy |
| LH-310 | Model Risk + Credit Risk Head |
| LH-311 | Risk Committee + Finance Controller |

Earlier-phase tickets that also block Phase 3: **LH-103** (default code
sets — they decide the hazard model's numerator), **LH-120** (data-sharing
approvals), **LH-204** (no logged decisions, so no SICR baseline).
Full register: [docs/phase3/blocking_tickets.md](../docs/phase3/blocking_tickets.md).

## Track P run (not gate evidence)

Seeded run, 445.1s. Reproduce with `make trackp-p3`.
Every limitation is listed in the run report's `panel.limitations`
block — Fannie's zero-balance code conflates prepayment with maturity,
there is no revolving product, and these are US conforming mortgages
rather than this bank's book.

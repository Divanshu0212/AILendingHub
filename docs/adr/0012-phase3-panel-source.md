# ADR-0012 — The Phase 3 panel, and what a mortgage book cannot stand in for

| Field | Value |
|---|---|
| Status | Accepted (Track P scope) · Blocked (Track B scope, LH-120) |
| Date | 2026-09-01 |
| Decider | Credit DS Lead (Track P) · Model Risk (Track B) |
| Workstream | WS-3.1, WS-3.2 |
| Consulted | Finance (ECL), Risk Reporting, Platform |
| Related | [ADR-0003](0003-two-track-execution-model.md), [ADR-0004](0004-public-reference-data-track.md), [ADR-0010](0010-scored-product-and-track-p-standin.md) |

## Context

Phase 3 §3 states an entry criterion that is unlike Phase 1's: **`[DATA]` ≥ 5
years of monthly account snapshots in Silver, with collections/recovery
cashflows reconciled to GL.** Phase 1 needed a *sample*; Phase 3 needs a
*panel*, and a panel with depth — behavioural PD, survival, competing risks and
transition matrices are all statements about what happens between one month and
the next, over years.

No such panel exists here. LH-120 (written data-sharing approvals) is still a
Phase 0 entry criterion, so there is no bank data at all, and the P1 orchestrator
has logged no decisions (LH-204), so there is no origination-PD history either.

Track P was established by ADR-0004 for exactly this situation. The question this
ADR settles is narrower and sharper than Phase 1's: **which dataset, and what
does building on it actually establish?**

## Decision

Build every Phase 3 model on the **Fannie Mae Single-Family Loan Performance**
extract, read as an account-month panel by
`lending_hub.sources.fanniemae_panel`. Label every number Track P. Record the
structural gaps — the things this data *cannot* establish — as **not
measurable** in the gate pack rather than as "not measured".

It is the only real panel available to this repository with the required depth.
The supplied 2007Q1 vintage runs January 2007 to March 2026: nineteen years of
month-end delinquency status per loan, with the 2008-11 credit event and the
2020-21 refinance wave both inside it.

## What this genuinely establishes

These are not simulations. Each was found by running against this data, and
several corrected code that looked right:

* **Censoring handled correctly under heavy competing risk.** At 2% sampling the
  panel is 5,081 loans and 338,210 account-months: 827 defaults, **4,169
  prepayments**, 85 administratively censored. A book that is 82% prepaid is the
  strongest possible test of whether prepayment is treated as a competing risk
  or quietly as censoring, and the difference is large — see
  `reports/trackP_p3_fannie_mae.json`.
* **LGD from real workout cashflows.** Foreclosure costs, property preservation,
  taxes, net sale proceeds and credit-enhancement proceeds are all present per
  disposed loan. Mean realised severity on the 2007 vintage is in the range
  published for it. Fitting against them produced **LH-311** — the finding that
  the loss basis decides the sign of the LTV coefficient.
* **Real feed defects.** Holding expenses post *net of credits* and proceeds can
  post as reversals; both broke validation that a fixture would have satisfied.
* **Specification failures that only appear on real covariates.** `months_observed`
  is unidentified in Cox (no within-risk-set variation) and `dpd_now` *separates*
  (reaching 90 DPD means passing through 60 first). Both now produce named
  errors rather than a singular matrix five iterations later.

## What it cannot establish, and why saying so matters

| Gap | Consequence |
|---|---|
| **No revolving product.** Fannie is amortising term debt: `L == B₀`, so the CCF denominator is identically zero. Home Credit's revolving slice carries no limit history. | No CCF model is estimable **at all**. `portfolio.ead.fit_ccf()` refuses. This is *not measurable*, not *not measured*. |
| **Prepayment and maturity share one code.** Fannie's zero-balance `01` is "Prepaid *or* Matured". | `Event.MATURED` is never emitted. Nearly harmless on a 2007 vintage of 30-year loans; a prepayment model on the 15-year slice would be measuring the amortisation schedule. |
| **No origination lifetime PD.** | SICR is defined relative to origination, so Stage 1 is unassignable (LH-301, LH-308). This is a *finding*, not a workaround: see `portfolio.staging`. |
| **US conforming mortgages.** Secured, prime, one country, one product, one regulatory regime. | Nothing about severity, seasoning shape, prepayment behaviour or macro sensitivity transfers to an Indian retail or agri book. A Gini computed here is a fact about US mortgage lending. |
| **No GL to reconcile to.** | The second half of the Phase 3 §3 entry criterion is untouched. |

## Why not the alternatives

* **Home Credit** (used for P1) has no monthly panel of sufficient depth per
  account and no workout cashflows. It answers application questions, not
  portfolio ones.
* **PKDD'99** has a genuine transaction panel but 682 loans — enough to exercise
  a code path, far too few for survival estimation with competing risks.
* **Simulating a panel** would make every Phase 3 number a restatement of the
  simulation's own parameters. Master §2 rule 3 confines synthetic data to
  `tests/fixtures/`, and the reason is visible here: none of the five findings
  above could have come from a generator, because a generator produces the
  defects its author thought of.

## Consequences

* Every Phase 3 report carries `"gate_evidence": false` and the dataset that
  produced it, as Phase 1's do.
* The gate pack distinguishes **not measured** from **not measurable**. Two of
  the six Phase 3 exit criteria, plus the whole CCF workstream, are structurally
  unreachable from here; reporting them alongside genuinely unrun work would
  put a scheduling problem and a structural one in the same column.
* When LH-120 lands, `fanniemae_panel` is replaced by a bank panel adapter behind
  the same `Panel` interface. Nothing in `lending_hub.portfolio` imports it.

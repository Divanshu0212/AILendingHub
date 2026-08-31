# Track P — what real data did to the platform

Findings from running Phase 0 against 28.5M rows of Fannie Mae Single-Family
Loan Performance data (2007Q1 and 2019Q1). Track P per
[ADR-0004](../adr/0004-public-reference-data-track.md): real loans, real
month-end delinquency histories — **not this bank's portfolio, so none of these
numbers is Phase 0 gate evidence.**

Reproduce with `python -m lending_hub.sources.profile`. Reports in
`reports/trackP_*.json`.

## Results

| Vintage | Window | Loans | Bad rate | Indeterminate | Censored |
|---|---|---|---|---|---|
| 2019Q1 | 12 months | 341,865 | 0.239% | 2.825% | 344 |
| 2007Q1 | 12 months | 253,279 | 0.452% | 5.270% | 908 |
| 2007Q1 | 48 months | 253,279 | **11.751%** | 11.687% | 210 |

Appendix A's label logic ran unmodified on all three passes.

## F1. The 12-month outcome window understates mortgage risk by ~26×

The same 2007Q1 loans give a 0.452% bad rate at 12 months and 11.751% at 48. The
12-month window captures under 4% of the four-year default experience.

Appendix A is not wrong — a 12-month window is right for the unsecured retail
origination scoring the SRS targets, where the outcome matures fast. It is simply
mismatched to 30-year mortgages, whose defaults peak in years 3-5. A 2007 vintage
scored on a 12-month window would look almost clean going into the worst mortgage
credit event on record.

**Not a change request.** Appendix A is `[SPEC]` and correct for its purpose.
It is a limitation to record on the model card of anything trained on this
dataset, and evidence that `outcome_window` needs to stay a parameter rather than
harden into a constant.

## F2. Delinquency status aligns with Appendix A without tuning

Fannie reports whole *months* delinquent in 30-day steps. Status `03` lands
exactly on `DEFAULT_DPD_THRESHOLD_DAYS`; `01` and `02` land exactly inside the
indeterminate band. No fitting, no fudge factor, no "close enough" — the
definitions were written independently and the boundaries coincide. That is what
makes this dataset a genuine test of the label logic rather than a rehearsal.

## F3. Prepayment is not censoring, and conflating them poisons the sample

First pass excluded any loan whose 12-month window was short — 233,476 of
341,865 loans in 2019Q1, 85% of the vintage.

Almost all of them had **prepaid**, not gone unobserved. The 2019 vintage
refinanced en masse through the 2020-21 rate collapse. A prepaid loan's outcome
is determined: it left the book performing.

Dropping them would have left a sample of borrowers who *could not* refinance —
systematically worse credit, higher rates, lower equity. The model would have
been fitted to a population defined by its inability to escape, and every offline
metric would have looked fine.

Now separated explicitly: terminated-inside-window (determined) versus
extract-ends-first (censored, excluded). Censored fell from 233,476 to 344.

## F4. A quarterly extract's first months are missing, and that is not censoring either

Reporting periods begin at the *acquisition quarter*, so a loan originated a
month or two earlier has no rows for those months. Counting rows and requiring
twelve discarded most of the vintage.

That gap cannot hide a 90-DPD event — the first payment is not yet due, so the
loan cannot be three payments down. The test is now whether the extract covers
the window's *end*, not how many rows were counted.

## F5. 908 real loans were being labelled GOOD with no observed month

A six-row fixture written to cover every label path caught it: a loan whose every
in-window status is `XX` has no observed performance at all, and `max_dpd == 0`
there means "nothing seen", not "nothing happened".

2007Q1 had 908 such loans and 2019Q1 had 344 — small, but they were silently
inflating the good count in the population with the *worst* data quality, which
is precisely where a bias does damage. Now censored.

This is the same None-versus-False distinction the definitions package draws for
unobserved outcome flags. It had to be re-derived here because the external
schema encodes "unknown" as a string rather than as an absence.

## F6. Neither Track P dataset can support point-in-time correctness

Both are declared `point_in_time_unsafe` in the source registry.

Fannie Mae carries `ACT_PERIOD` — event time — and no ingestion timestamp.
Knowability would have to be reconstructed from which quarterly release first
contained each row. That reconstruction is defensible, but it is *derived*, and a
derived knowability presented as native is exactly the leakage finding B1 exists
to prevent. Home Credit is worse: every time column is a relative day offset from
an unstated reference date, so there is no absolute timeline at all.

Correcting an earlier claim of mine: I said the monthly publication date gives a
real `created_timestamp`. It gives a *reconstructable* one. The registry now says
so, and any model trained on either source records the limitation.

## What this does not unblock

Still Track B only: GL reconciliation (no public dataset ships an independent
ledger) and scorecard parity (no legacy scorecard exists to rebuild). Two of the
four numeric gates remain blocked on a real bank.

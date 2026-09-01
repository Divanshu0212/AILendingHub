# Phase 3 — implementation findings against the phase documents

Produced while building Phase 3. Master §1: "conflicts are raised as tickets,
never resolved silently by an implementer." Every finding below is **raised and
unapplied** — the SRS, the Master and the Phase 3 file are unchanged pending the
document owner's decision, exactly as the Phase 1 findings were before they were
accepted.

**The Phase 3 document is the strongest of the three phase files built so far.**
Its workstream ordering is right — behavioural PD first because it powers the
dashboards, Cox before the challenger because auditors read it first — and two of
its instructions are unusually well judged: "every panel shows a data-as-of
timestamp" and "drill-through is what makes a dashboard a tool rather than a
poster". Both are the kind of requirement that only survives contact with a real
risk function.

Most of what follows is not "this is wrong". It is "this becomes a decision
somebody makes silently", and three of the items are things the phase file could
not have known because they only appear once code has to produce a number.

## Status of each finding

| # | Finding | Kind | Ticket |
|---|---|---|---|
| P3-F1 | **Stage 1 is not assignable**, and defaulting to it is the least conservative choice available | Correction | LH-301, LH-308 |
| P3-F2 | The **LGD loss basis decides the sign of the LTV effect** — and nothing specifies the basis | Gap found by building | **LH-311 (new)** |
| P3-F3 | Competing risks are not a refinement: prepayment-as-censoring overstates lifetime default by **47% relative** on real data | Evidence for an existing instruction | — |
| P3-F4 | Cox tie handling changes the coefficients on a monthly panel; the named library's default is the wrong one here | Under-specification | — |
| P3-F5 | "Month-on-book dummies" is right for the logistic form and wrong for the tree form the same step mandates | Correction | — |
| P3-F6 | CUSUM and ADWIN are named without the parameters that make them alarm | Gap found by building | **LH-307 (new)** |
| P3-F7 | **No CCF is estimable on any track** — "not measurable" is a different gate state from "not measured" | Structural | LH-303 |
| P3-F8 | Appendix A defines default but not **cure**, and the LGD model's first stage needs it | Gap found by building | **LH-309 (new)** |
| P3-F9 | SRS §9.3.2's DPD buckets put 90 in two of them | Correction (minor) | — |
| P3-F10 | A behavioural Gini is not comparable with an application Gini, and the exit criteria invite the comparison | Under-specification | — |
| P3-F11 | Current DPD **separates** in a Cox model at monthly granularity | Specification, found by building | — |
| P3-F12 | **A hypothesis of mine was wrong**, and the demonstration caught it | Method note | — |
| P3-F13 | A behavioural hazard model scored at origination returns an **exactly constant** risk, which reads as a broken model | Method note | — |
| P3-F14 | The §7 comparison was **in-sample**, which measures capacity rather than skill — a 200-tree ensemble against a four-parameter model | Correction to my own work | — |

---

## A. Corrections — statements that mislead as written

### A1 (P3-F1). Stage 1 is the stage you cannot assign

**§4 WS-3.1 Step 7:** *"Stage 2 = lifetime-PD ratio vs. origination > threshold
`[POLICY: Finance + Risk]` OR 30-DPD backstop OR P4 red flag … Stage 3 =
credit-impaired per definitions package."*

Read as a decision procedure this is complete: three arms for Stage 2, one for
Stage 3, and Stage 1 by elimination. But **Stage 1 means "not Stage 2"**, and
establishing that requires evaluating *every* Stage 2 arm. One of them cannot be
evaluated:

* the SICR threshold is `[POLICY]` and does not exist (LH-301); and
* the lifetime PD *at origination* does not exist either for anything already on
  the book (LH-308) — P1 produces one only for applications it scores from now
  on, and the industry workaround (re-score today's loans on origination-dated
  features with today's model) has an error correlated with vintage.

So for an account with no arrears and no flag, the honest output is not Stage 1.
It is **undeterminable**, and the difference is expensive: Stage 1 carries
12-month ECL where Stage 2 carries lifetime ECL. An engine that quietly assigns
Stage 1 understates the provision by exactly the amount the SICR rule was written
to capture, silently, on the majority of the book.

`portfolio.staging.classify()` returns an `Undeterminable` that is deliberately
**not** a `Stage` — it cannot be summed into a provision and will not compare
equal to `Stage.ONE` in a reporting query that forgot to check — and `stage()`
raises. On the Track P panel this is not a corner case: **84% of accounts are
undeterminable** (4,253 of 5,081), 0 are Stage 1, 1 is Stage 2, and 827 are
Stage 3.

**Proposed wording.** Add to Step 7: *"Stage 1 is assigned only when every
Stage 2 arm has been evaluated and none fired. Where an arm is unevaluable the
account is reported as unstaged, with the unevaluable rule named. Unstaged
accounts are never defaulted to Stage 1."*

### A2 (P3-F5). Month-on-book dummies are right for the model the step does not use

**§4 WS-3.1 Step 3:** *"month-on-book dummies for the baseline hazard,
monotone-constrained LightGBM."*

Dummies are the correct baseline for the canonical *logistic* discrete-time
hazard model, where the baseline must be free-form because the link is linear.
They are the wrong encoding for a tree ensemble, and in the same sentence: a
one-hot expansion discards the ordering of months, so the model cannot pool
information between month 13 and month 14 and must relearn each one from its own
rows. That costs precision exactly where the risk set is thinnest — long
durations.

`portfolio.hazard` passes `months_on_book` as an ordered numeric feature and the
tree recovers the baseline shape itself; `baseline_hazard()` reads it back out
for the diagnostic the dummies existed to provide.

**Proposed wording.** *"…month-on-book as the baseline hazard's time axis —
dummies for a logistic formulation, an ordered numeric feature for a tree
ensemble, which must not be one-hot encoded."*

### A3 (P3-F9). The DPD buckets overlap

**SRS §9.3.2:** *"Markov transition matrix across DPD buckets {current, 1–30,
31–60, 61–90, 90+, closed}"*

90 appears in both "61–90" and "90+". Every implementer resolves it the same way
and no harm follows, but the resolution is silent, and the top edge is not free:
the "90+" bucket **is** Appendix A's credit-impaired definition, so it must move
if the definition moves or the dashboard and the provision disagree.
`portfolio.transitions` imports `DEFAULT_DPD_THRESHOLD_DAYS` for the top edge and
labels the band below it `61-89`.

**Proposed wording.** *"{current, 1–30, 31–60, 61 to (default threshold − 1),
default threshold and above, closed}, with the top edge imported from Appendix A
rather than restated."*

---

## B. Under-specification — decisions an implementer would otherwise make silently

### B1 (P3-F4). Cox tie handling is not a detail on a monthly panel

**§4 WS-3.1 Step 2:** *"Cox proportional hazards with time-varying covariates
(`lifelines` / scikit-survival)."*

Cox's partial likelihood was derived for continuous time, where exact ties have
probability zero. A month-end panel ties **every** event time. On the Track P
run the tie fraction is 0.66; on simulated data with a known generating hazard it
reaches 0.96.

At those levels the tie approximation changes the coefficients rather than the
sixth decimal. Measured against a known truth of β = 0.800: **Efron recovers
0.758, Breslow 0.740.** Breslow biases toward zero, and Breslow is
scikit-survival's default — so following the phase file's own library reference
without thinking produces the worse estimate.

`portfolio.cox` defaults to Efron, records which approximation produced the fit,
and `promotable` refuses a heavily-tied Breslow fit rather than letting the
hazard ratios be quoted.

**Proposed wording.** Add: *"Tie handling is Efron; Breslow's approximation
biases coefficients toward zero at the tie densities a month-end panel produces.
The fit records which was used."*

### B2 (P3-F6). "CUSUM alarms" and "ADWIN" name methods, not alarms (ticket LH-307)

**§4 WS-3.2 Step 2:** *"CUSUM alarms on the 30→60 and 60→90 cells."*
**§4 WS-3.2 Step 3:** *"**ADWIN** streaming change detection on score
distributions."*

A CUSUM is not a statistic until a reference shift `k` and a decision interval
`h` are chosen; ADWIN is not a detector until a confidence `δ` is chosen. All
three set the false-alarm rate on a surface risk officers are expected to act on,
and none is in the SRS, the Master or the phase file. The failure mode is not a
wrong number — it is an alarm that fires at a rate nobody chose, which is worse
than no alarm because it trains people to ignore the panel.

`transitions.cusum`, `health.Adwin` and `health.calibration_drift` take them as
required arguments with no defaults. The ADWIN paper's own experimental δ is
available as `ADWIN_PAPER_DELTA` — a citation a caller may pass deliberately,
which is a different thing from a default nobody chose.

### B3 (P3-F8). Appendix A defines default but not cure (ticket LH-309)

**SRS §7.3.3:** *"two-stage model — (1) cure probability … (2) recovery rate on
non-cured."*

The first stage needs a cure definition: what counts as a defaulted account
returning to performing, and over what window. Master Appendix A defines
*default* and freezes it; nothing defines *cure*. The choice decides which
defaults enter the recovery model at all, so it moves LGD directly — and a cure
rule looser than the default rule produces accounts oscillating between states
every month.

`portfolio.lgd.TwoStageLGD.expected_lgd()` raises; `loss_given_no_cure()` is
computable and is labelled as the different quantity it is.

### B4 (P3-F10). A behavioural Gini is not an application Gini

**§7:** *"Hazard GBM C-index ≥ Cox + 0.02 and ≥ 0.75 absolute."*

The exit criteria mix discrimination measures taken at different observation
points without saying so. Measured on the Track P panel:

| Model | Observation point | Discrimination |
|---|---|---|
| Behavioural PD | mid-life, arrears history available | Gini 90.3 |
| Behavioural PD, arrears features removed | mid-life | Gini 78.6 |
| Survival, from origination | month 0, origination attributes only | C-index ≈ 0.58 |

These are not three qualities of model. They are three different questions, and
the easiest of them ("will this delinquency continue") looks the most impressive.
A gate that reads 90 beside 0.58 without the observation point attached will
conclude the survival model is broken.

The runner reports the arrears ablation and stamps `observation_point` on the
survival metrics for this reason. **Note the numbers above are Track P** and say
nothing about this bank's book (ADR-0012).

**Proposed wording.** Add to §7: *"Every discrimination figure is reported with
its observation point. Behavioural and origination-time metrics are not
comparable and neither may be substituted for the other."*

---

## C. Structural — things no amount of work inside this repository fixes

### C1 (P3-F7). No CCF is estimable, on any track (ticket LH-303)

**§4 WS-3.1 Step 6:** *"`CCF = (EAD − B₀)/(L − B₀)`; GBM/tobit on limit,
utilization, behavior."*

Two independent blockers, and reporting them together matters because either one
alone reads as a scheduling problem:

1. **No revolving product exists on any available track.** Fannie Mae is
   amortising term debt, where `L == B₀` makes the denominator *identically
   zero* — the formula is not hard to estimate on that data, it is undefined.
   Home Credit's revolving slice carries no limit history, so `L` is unknown at
   the reference date.
2. **Regulatory CCF floors are `[POLICY]`** (§8), and a CCF is one of the few
   model outputs routinely floored rather than used raw.

`portfolio.ead.fit_ccf()` refuses with both reasons rather than fitting the
degenerate case — a CCF regression that silently drops every zero denominator
returns a confident number computed from whichever rows had a data error.

This produces a gate-reporting consequence worth adopting programme-wide: the
Phase 3 pack distinguishes **not measurable** from **not measured**. Two of the
six exit criteria and the whole CCF workstream are structurally unreachable from
here. Reporting them alongside genuinely unrun work puts a scheduling problem and
a structural one in the same column, and the second never gets escalated.

---

## D. Found by building — values and effects the documents could not have known

### D1 (P3-F2). The LGD loss basis decides the sign of the LTV effect (ticket LH-311)

Not on the §8 do-not-invent list, and not a presentation choice. Measured on
20,407 real Fannie Mae workouts, where private mortgage insurance is required
above 80% original LTV and paid on ~90% of the losses carrying it:

| Original LTV | Workouts | MI paid | LGD **net** of MI | LGD **gross** of MI |
|---|---|---|---|---|
| ≤ 80 | 15,712 | 0.0% | 0.4285 | 0.4285 |
| 81–90 | 3,147 | 89.9% | 0.3102 | **0.4925** |
| > 90 | 1,600 | 94.6% | 0.2120 | **0.4767** |

Net of enhancement, LGD *falls* as LTV rises. Gross of it, LGD *rises*. Fitting
the recovery model on each basis:

| Basis | `oltv` | `credit_score` | E[LGD] for a high-risk borrower |
|---|---|---|---|
| Net of enhancement | −0.76 | +0.11 | 0.331 |
| Gross of enhancement | **+2.55** | **−0.44** | 0.625 |

On the net basis the model says less equity means smaller losses and a high-risk
borrower is cheaper than a low-risk one. That is a true statement about *the
insurance structure* and a false one about the collateral. Neither basis is
wrong; fitting on one and reading the other's interpretation is, and nothing in
the SRS or the phase file says which applies.

`realised_lgd()` takes the basis as a **required argument with no default**, and
`aggregates.Exposure` refuses an LGD that arrives without one, so a cell that
summed both reports `mixed_lgd_bases` rather than a number with no
interpretation.

### D2 (P3-F3). Evidence for the competing-risks instruction

§4 Step 4 already requires competing risks. This is the number that shows why it
is not a refinement. On the Track P panel — 5,081 loans, 82% of which prepaid:

| Quantity at 60 months | Value |
|---|---|
| Cumulative incidence of default | 0.1148 |
| Cumulative incidence of prepayment | 0.5191 |
| Naive figure, prepayment treated as censoring | 0.1687 |
| Overstatement | 0.0540 (**47% relative**) |

The naive curve assumes a prepaid loan would have defaulted at the same rate as
one that stayed. On a mortgage book that is close to backwards — the borrowers
who can refinance are the ones whose credit improved — and the error is largest
exactly where prepayment is heaviest, which is where pricing decisions are made.
`incidence()` returns both figures so the gap is a number in the report rather
than a caveat nobody quantified.

### D3 (P3-F11). Current DPD separates a Cox model at monthly granularity

Putting `dpd_now` into the Cox reference produces **complete separation**: the
coefficient diverges, the information matrix collapses, and the fit dies. This
is not a data problem. Reaching 90 DPD requires passing through 60 the month
before, so at month granularity the current reading nearly determines next
month's event *among those at risk together* — which is precisely the comparison
Cox's partial likelihood is built on.

The fix is specification, not more data: lag the covariate, coarsen it, or model
the roll directly. `fit_cox` now detects the condition and says so, rather than
reporting "the information matrix is singular", which reads as a data problem and
sends the reader to the wrong place.

### D4 (P3-F12). A hypothesis of mine was wrong, and the demonstration caught it

Worth recording as a method note rather than a document finding.

I expected `months_observed` to be **unidentified** in a Cox model — it looks
like a deterministic function of months on book, so it should be constant within
every risk set and contribute nothing to any comparison. I wrote that as a
comment, then wrote it as a demonstration instead: `_cox_exclusions` refits with
each such covariate added and records what actually happens.

It fits. On this panel loans enter at *different* ages, because a quarterly
acquisition file's reporting periods begin at the acquisition quarter, so months
observed genuinely varies among loans at risk together. The hypothesis was right
about the general case and wrong about this data.

The general check is worth keeping regardless: `fit_cox` now detects covariates
with no within-risk-set variation and names them, because the symptom otherwise
is a singular matrix several iterations later — which reads as a data problem
rather than a specification one.

### D5 (P3-F13). Scoring a behavioural model at origination produces a constant

Also a method note, and the more instructive of the two because the symptom
looked like a bug in the metric.

The first Track P run reported Harrell's C of **exactly 0.5** and a
time-dependent AUC of **exactly 0.5** at every horizon. Exactly 0.5 from
`harrell_c` means every comparable pair is tied — the risk score is constant.

It was. Survival metrics were being taken at month 0, where *every* behavioural
feature is zero for *every* loan: no arrears, no trend, no balance history. The
challenger's trees split first on the arrears features, so at month 0 every loan
falls into the same leaf and the origination attributes never get consulted. The
model was not broken; it was being asked a question none of its features can
answer.

The fix is the same one Phase 3 §7 implicitly requires: score both models on the
**same subjects, at the same month on book, over the same forward time axis**.
Anything else compares two populations. The runner now observes at month 12 and
measures time forward from there, which is what makes the §7 comparison
"C-index ≥ Cox + 0.02" formable at all.

The general lesson is worth more than the fix: **a metric that comes out at
exactly its null value is usually reporting a degenerate input, not a weak
model** — and an implementation that returns `None` where a quantity is
undefined (as `time_dependent_auc` does for an empty case or control set) makes
that visible, where returning 0.5 would have hidden it.

### D6 (P3-F14). The §7 comparison was in-sample, and that is not a comparison

This finding changed twice. The route matters more than the destination,
because each wrong version looked like a result.

**What the model does** (this part held throughout). A discrete-time hazard
model is asked "does this account default *this month*", and the most
informative answer is nearly always the most recent arrears reading. Left
unconstrained the trees spend themselves on `dpd_now` and `max_dpd_3m` — 61 of
the first 100 splits on a fitted model, while `months_on_book`, the feature I
expected to dominate, takes none of the top eight. Those are zero for about 99%
of accounts at any snapshot, because delinquency is rare, so the model
discriminates well inside the delinquent tail and barely at all across the
population. Ranking a book needs the second. That is why `feature_fraction` is
set.

**First wrong version: "column subsampling fixes it."** A configuration grid at
0.8% sampling gave the subsampled challenger a +0.075 uplift over Cox. I applied
it and wrote it into the module and the model card as a result.

**Second wrong version: "the comparison is unstable."** It did not replicate. At
2% the identical configuration gave −0.119. I concluded the measurement was
noise-dominated and rewrote the finding to say so — and that was wrong too,
because I had not checked whether it was *noise*. A seed sweep settles it:

| Sample | Subject events | Cox C | Challenger C by seed | Uplift by seed |
|---|---|---|---|---|
| 0.8% | 204 | 0.5675 | 0.6423 / 0.6726 / 0.6314 | **+0.075 / +0.105 / +0.064** |
| 2.0% | 600 | 0.6500 | 0.5517 / 0.5510 / 0.5685 | **−0.098 / −0.099 / −0.082** |

Within a sample size the result is tight — a spread of 0.04 and 0.02. Between
sample sizes it flips sign, consistently, every seed. That is not noise. It is a
*systematic* effect of sample size, and a systematic effect has a cause.

**The cause: the comparison had no held-out set.** Both models were being scored
on the accounts they were fitted on. A four-parameter Cox model can barely
overfit 200 events; a 200-tree depth-4 ensemble memorises them. So at 0.8% the
challenger's apparent advantage was its own training data being read back to it,
and as events accumulated the memorisation advantage shrank and the true (worse)
ranking emerged. Cox's C rising with more data and the challenger's falling is
the signature.

**The fix.** `HOLDOUT_FRACTION` splits the panel **by account** — never by
account-month, because the same loan on both sides of a panel split is the same
loan and the model has effectively seen the test row already. Both models are
fitted on the fit set and scored on the held-out accounts, and the run report
carries `out_of_sample: true`.

**The result, once it is a comparison.** On 1,400 held-out accounts at 2%
sampling: challenger C **0.5285**, Cox C **0.6967**, uplift **−0.168**. The gap
is *wider* out of sample than the −0.098 measured in-sample, which is what
removing a memorisation advantage should do and is the last piece of evidence
that the diagnosis is right.

So the honest Track P answer to §7 criterion 1 is that **the challenger does not
beat the reference** — it loses by 0.17 against a bar of +0.02, and it misses
the 0.75 absolute bar as well. That is not a failure of the phase file's
instruction to build a challenger; it is the instruction working. A
discrete-time hazard GBM whose signal concentrates in features that are zero for
99% of the population is the wrong shape for ranking a book, and an
interpretable four-parameter model that the phase file required be built *first*
is what revealed it.

**What this says about §7.** The criterion "hazard GBM C-index ≥ Cox + 0.02" is
silent on the split, and an implementer following it literally will do what I
did — because comparing two models on the data you have is the obvious reading,
and it systematically favours whichever model has more capacity. That is
precisely the wrong bias for a criterion whose job is to justify replacing an
interpretable model with a complex one.

**Proposed wording** for §7: *"the C-index comparison is made on accounts held
out of both fits, at a stated observation month, over a common forward time
axis, with subjects censored at the horizon the challenger was fitted to. An
in-sample comparison between models of different capacity does not satisfy this
criterion."*

One result held at every sample size and every seed: **`scale_pos_weight` makes
this model worse than random.** At a 0.3% event rate, upweighting the positives
buys fit on the delinquent tail at the cost of the ordering everywhere else. It
is deliberately absent, with the measurement recorded beside it, because "we
tried the obvious thing and it was actively harmful" is exactly the result that
gets rediscovered every two years.

---

## E. Two smaller things the tests found

**The trend detector inflated its own yardstick.** `opsanomaly`'s warning for
"this series is trending, so the seasonal-median decomposition will over-flag"
first compared the half-medians against the raw MAD, then against the residual
MAD. It was silent both times, because a trend inflates *both* of those scales.
It now uses the MAD of successive differences, which differencing makes
trend-insensitive. The general lesson — a scale estimated on the data you are
testing for a shift absorbs the shift — applies to more than this detector.

**PSI over self-computed bins is zero by construction.** `health.drift` takes
bin edges from the *reference* sample and never recomputes them. Re-binning both
sides on their own quantiles makes PSI approximately zero however far the
distribution has moved, and it is the commonest way a drift monitor reports
stability through a shift.

# Model Card — discrete_time_hazard (survival challenger) v0.1.0-trackP

> **This is a Track P model card** (ADR-0004, ADR-0012). Not a candidate for
> shadow, canary or production; none of its numbers is Phase 3 gate evidence.

## 1. Identification

| Field | Value |
|---|---|
| Model name / version | `discrete_time_hazard` v0.1.0-trackP |
| Registry stage | None — not registered; not promotable (see §11) |
| Owner (accountable) | Credit DS squad lead |
| Developer (R) | Credit DS |
| Independent validator | **Not assigned** (Master §3.1) |
| Reference model | `cox_reference` — the interpretable baseline this must beat (Phase 3 §7) |

## 2. Reproducibility triplet

| Field | Value |
|---|---|
| Code commit SHA | The commit that produced `reports/trackP_p3_fannie_mae.json` |
| Data snapshot | Fannie Mae 2007Q1, whole-loan sample per the run report |
| Config hash | `CHALLENGER_PARAMS` in `portfolio.experiment` — `n_trees=200`, `max_depth=4`, `learning_rate=0.05`, **`feature_fraction=0.5`**; risk set truncated at 60 months on book |
| Definitions fingerprint | Run report `definitions_fingerprint` (Appendix A v1.1) |

## 3. Purpose and scope

Estimates `h(m | x)` — the probability an account defaults in month `m` given it
was alive at the start of it — and rebuilds `S(t) = Π(1 − h_k)` from it
(SRS §7.3.2c). Provides PD(12m), lifetime PD and time-to-default.

**Must not be used for**: any population but this one; lifetime ECL (LH-301);
any survival curve past the last observed month without the extrapolation
caveat in §8.

## 4. Method

One row per account-month at risk; target "the event happened this month".
Censoring is handled by construction — a censored account simply stops
contributing rows. Boosting is `lending_hub.scoring.gbm` (Master §2 rule 2: one
reference implementation per algorithm); this module contains none of its own.

**Deviation from the phase file**, raised as finding P3-F5: Step 3 specifies
month-on-book *dummies*, which is right for the canonical logistic form and
wrong for a tree ensemble — dummies discard the ordering, so the model cannot
pool month 13 with month 14. `months_on_book` enters as an ordered numeric
feature and `baseline_hazard()` reads the shape back out.

## 5. Why `feature_fraction` is here

Left unconstrained, this model's trees spend themselves on `dpd_now` and
`max_dpd_3m` — 61 of the first 100 splits on a fitted model. Those are the most
informative answer to "does this account default *this month*", and they are
zero for about 99% of accounts at any snapshot, because delinquency is rare. The
result discriminates well inside the delinquent tail and barely at all across
the population, which is what a portfolio ranking needs. Column subsampling
forces each split to consider features with broader coverage.

**These are not tuned values, and the card will not present them as such.** A
configuration grid at one sample size preferred this setting by a wide margin
and the preference did not survive a larger sample. The measured uplift is in
the run report; the stability behind it is Phase 3 finding D6, and it is the
reason no single comparison here should be read as a result.

`scale_pos_weight` — the standard handling for class imbalance, and the first
thing anyone reaches for at a 0.3% event rate — made the model **worse than
random** at every sample size tried. It is deliberately absent.

## 6. Performance

Track P, from the run report's `survival_metrics`. **Observation point:
origination** — risk scores are taken from each loan's first month, so these
measure discrimination on origination-time information only. They are **not**
comparable with the behavioural Gini (finding B4).

| Metric | Where |
|---|---|
| Harrell's C-index | `survival_metrics.concordance` |
| Time-dependent AUC (12/24/36/60m) | `survival_metrics.time_dependent_auc` |
| Integrated Brier score | `survival_metrics.integrated_brier` |
| S(12m) calibration by decile | `survival_metrics.survival_calibration_at_12m` |

Harrell's C reports its own censoring rate and states when it is optimistic
(Uno et al. 2011). On this panel censoring is heavy and the caveat fires.

## 7. Competing risks

Prepayment is modelled as a competing cause, not censoring
(`portfolio.competing`). On this panel that is decisive: 82% of loans prepaid,
and the naive single-risk curve overstates 60-month lifetime default by 47%
relative. The cumulative incidence function is the quantity to use; the naive
figure is reported beside it so the gap is visible.

## 8. Fairness

**Not assessed** — no protected attributes in the extract.

## 9. Limitations

* **Extrapolation.** `S(t)` past the last observed month holds covariates at
  their last values while `months_on_book` advances. `SurvivalCurve.extrapolated_from`
  reports where measurement stops and projection starts. A 60-month curve on a
  12-month-old account is mostly assumption.
* Fannie's zero-balance code conflates prepayment with maturity, so the
  prepayment cause is really "left without a credit loss".
* No ratified monotone constraints (LH-310), so the shape is whatever the data
  gave.

## 10. Monitoring

As `behavioural_pd` §9. No alarm thresholds set (LH-307).

## 11. Decision provenance

Not decisioning.

## 12. Promotion status

**Not promotable.** `HazardModel.promotable` returns false on LH-310 — the
behavioural monotone direction list is not ratified.

On §7's numeric bar: the C-index comparison against Cox *is* now formable, and
the run report carries it — but it is **not decidable at this event count**. The
same configuration produced an uplift of +0.075 at one sample size and −0.119 at
another, a sign change of 0.19 against a criterion stated at +0.02 (finding D6).
The absolute 0.75 bar is not met at either. Both figures describe US conforming
mortgages rather than this bank's book (ADR-0012), so neither is gate evidence.
No independent validator exists either (§1).

## 13. Sign-off

| Role | Name | Date |
|---|---|---|
| Developer | — | — |
| Independent validator | — | — |
| Model Risk | — | — |

**Unsigned.**

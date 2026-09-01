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
| Config hash | `n_trees=60`, `max_depth=4`, `learning_rate=0.1`, risk set truncated at 60 months on book |
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

## 5. Performance

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

## 6. Competing risks

Prepayment is modelled as a competing cause, not censoring
(`portfolio.competing`). On this panel that is decisive: 82% of loans prepaid,
and the naive single-risk curve overstates 60-month lifetime default by 47%
relative. The cumulative incidence function is the quantity to use; the naive
figure is reported beside it so the gap is visible.

## 7. Fairness

**Not assessed** — no protected attributes in the extract.

## 8. Limitations

* **Extrapolation.** `S(t)` past the last observed month holds covariates at
  their last values while `months_on_book` advances. `SurvivalCurve.extrapolated_from`
  reports where measurement stops and projection starts. A 60-month curve on a
  12-month-old account is mostly assumption.
* Fannie's zero-balance code conflates prepayment with maturity, so the
  prepayment cause is really "left without a credit loss".
* No ratified monotone constraints (LH-310), so the shape is whatever the data
  gave.

## 9. Monitoring

As `behavioural_pd` §9. No alarm thresholds set (LH-307).

## 10. Decision provenance

Not decisioning.

## 11. Promotion status

**Not promotable.** `HazardModel.promotable` returns false on LH-310. Also: no
independent validator, and Phase 3 §7 requires C-index ≥ Cox + 0.02 and ≥ 0.75
absolute — a comparison the gate pack reports as **not evaluable**, because the
Cox reference and this model are not scored on a common out-of-time sample.

## 12. Sign-off

| Role | Name | Date |
|---|---|---|
| Developer | — | — |
| Independent validator | — | — |
| Model Risk | — | — |

**Unsigned.**

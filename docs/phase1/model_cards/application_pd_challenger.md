# Model Card — application_pd_challenger (monotone GBM) v0.1.0-trackP

> **Track P model card** (ADR-0004). Fitted on public reference data to prove the
> WS-1.1 code paths; not a candidate for shadow, canary or production, and no
> number here is Phase 1 gate evidence. Completed in full anyway — see the
> champion card's note.

## 1. Identification

| Field | Value |
|---|---|
| Model name / version | `application_pd_challenger` v0.1.0-trackP |
| Registry stage | None — `GBM.promotable` returns **False** (see §5) |
| Model tier | Tier 1 if ever customer-affecting; currently non-decisioning |
| Owner (accountable) | Credit DS squad lead |
| Developer (R) | Credit DS |
| Independent validator | Not assigned (Master §3.1) |
| Date registered | Not registered |

## 2. Reproducibility triplet

| Field | Value |
|---|---|
| Code commit SHA | The commit that produced `reports/trackP_p1_home_credit.json` |
| Data snapshot | Home Credit `application_train.csv`, first 60,000 rows, `--seed 20260901` |
| Config hash | `n_trees=120, max_depth=3, max_bins=32, l2=1.0, gamma=0.0, min_child_weight=1.0, early_stopping_rounds=15, scale_pos_weight=1.0, seed=20260901` |
| Definitions fingerprint | `run.definitions_fingerprint` in the report (Appendix A v1.1) |

91 trees grown; **best iteration 76** by validation log-loss. Scoring truncates
at the best iteration.

## 3. Purpose and scope

Challenger to the WOE scorecard for application PD (SRS §4.3.2). Same population,
same target, same split, deliberately — a challenger evaluated on a different
sample measures the sample.

**Must not be used for**: any decision (no cutoffs, LH-204); any population
outside the fitted one; any Appendix A default estimate.

## 4. Data

Identical to the champion card §4: the same 60,000-row target table, the same
random holdout (42,000 / 9,000 / 9,000), the same vendor label, the same three
unenforceable exclusions. Base rates 8.02% / 7.96% / 8.08% across train,
validation and test.

The challenger uses **all 17 IV-screened features**; the champion keeps the top
15. That asymmetry is deliberate — a scorecard is a document a credit officer
reads and a tree ensemble is not — and it is a difference between the models that
the swap-set analysis in §6 partly reflects.

## 5. Methodology

- **Algorithm**: histogram gradient boosting with the regularised second-order
  gain of SRS §4.3.2, depth-limited, early-stopped on the validation split.
- **Reference**: LightGBM (Ke et al., NeurIPS 2017) for the histogram split
  structure; XGBoost (Chen & Guestrin) for the gain and the monotone-constraint
  enforcement. `lending_hub.scoring.gbm` is a **documented port**: it implements
  histogram split finding and the regularised gain, and does **not** implement
  GOSS or EFB, which are LightGBM's speed optimisations at a scale this reference
  implementation does not target.
- **Alternatives**: the champion scorecard. On this dataset the scorecard wins
  (§6), which is itself the result worth recording.
- **Hyperparameters**: not searched. Fixed at the values above for a
  reproducibility-first run; Phase 1 §4 Step 4 requires any search to run on
  validation vintages only, and this source has no vintages.
- **Monotonicity constraints**: **none applied.** The ratified direction list is
  `[POLICY: Credit Risk Head]` and does not exist (LH-202), so the model was
  fitted through `MonotoneConstraints.for_experiment` with a written reason, and
  `promotable` returns `(False, "monotone directions are not ratified (LH-202)")`.
  The consequences are visible in §6 and are the point of recording them.

## 6. Performance

Test split, 9,000 applications, 727 bads.

| Metric | Champion | Challenger |
|---|---|---|
| AUC | 0.7383 | **0.7380** |
| Gini (points) | 47.66 | **47.60** |
| KS | 0.3548 | 0.3497 |
| Brier | 0.06906 | **0.06961** |
| ECE | 0.00537 | 0.00785 |
| Score PSI (train → test) | 0.0017 | 0.0013 |
| Train Gini | 44.69 | 50.64 |

**The challenger's uplift is −0.07 Gini points.** SRS §4.3.2 cites the Lessmann
et al. benchmark for "typically +2–6 Gini points" over logistic scorecards, and
on this dataset that did not reproduce. Recorded as Track P finding P1-F8 with
what does and does not follow from it.

Train Gini 50.64 against test 47.60 is a 3-point in-sample gap the champion does
not have, which is the expected shape: the ensemble has the capacity to fit noise
the linear model cannot, and early stopping bounded but did not remove it.

**Exit criteria** (`ValidationReport.exit_criteria`):

| Criterion | Evaluated | Met |
|---|---|---|
| Challenger ≥ +3 Gini over legacy, out-of-time | **No** — split is not out of time, and the comparator is the champion, not a rebuilt legacy scorecard | — |
| Brier ≤ legacy | Yes | **No** (0.06961 > 0.06906) |
| Monotonicity holds | Yes | **No** — see below |
| Score stability | Yes | Yes |
| Swap set: no adverse-segment concentration | **No** — the criterion has no numeric bar (LH-205) | — |

**Monotonicity spot checks fail, as designed.** Walking each of the top five
characteristics across its bin edges with the rest held fixed:

| Feature | Violations |
|---|---|
| EXT_SOURCE_3 | 0 |
| EXT_SOURCE_2 | **2** |
| EXT_SOURCE_1 | **1** |
| DAYS_EMPLOYED | 0 |
| credit_to_goods | 0 |

The ±10% sensitivity sweep says the same thing from another direction: 9 of 400
test rows move the same way under both a +10% and a −10% perturbation of
`EXT_SOURCE_3`, and 11 under `EXT_SOURCE_2` — locally non-monotone responses.

This is the concrete cost of LH-202. An unconstrained challenger *is*
non-monotone in features whose binned relationship is monotone, and the
regulator's "counter-intuitive behaviour" objection SRS §4.3.2.1 describes is
live rather than hypothetical.

**Swap-set analysis** against the champion at a common approval rate:

| Cell | Count | Bad rate |
|---|---|---|
| Both approve | 4,009 | — |
| Both decline | 3,525 | — |
| Swap in (champion declines, challenger approves) | 961 | 6.97% |
| Swap out (champion approves, challenger declines) | 505 | 6.53% |

The swap-out set's bad rate is *lower* than the swap-in set's — the challenger is
declining slightly better credits than it is accepting, which is consistent with
its not beating the champion.

Segment concentration in the swap-out set (share of swap-outs ÷ share of
population):

| Age band | Concentration |
|---|---|
| 60–69 | **1.86** |
| 50–59 | 1.02 |
| 30–39 | 1.01 |
| 20–29 | 0.86 |
| 40–49 | 0.66 |

The 60–69 band takes 1.86× its population share of the challenger's new declines.
Whether that fails Phase 1 §7 is not computable — the bar is LH-205 — but the
measurement is exactly what that criterion needs, and it is not zero.

## 7. Fairness

Measured on the challenger's approvals (test split):

| Attribute | Demographic parity difference | Parity ratio | Equalized-odds difference |
|---|---|---|---|
| Age band | 0.4046 | 0.4293 | 0.3954 |
| Gender | 0.1030 | 0.8248 | 0.0990 |
| Region rating (pincode proxy) | 0.2620 | 0.6195 | 0.2442 |

No verdict — LH-205. The age-band mechanism is analysed in the champion card §7
and applies identically here: elapsed-time features act as age proxies.

## 8. Explainability

Exact Shapley values, not a TreeSHAP port — depth-3 trees touch few enough
distinct features that exact enumeration over coalitions is cheap, and exactness
is worth more than speed when a wrong attribution looks entirely reasonable.
Local accuracy is asserted per explanation (`Explanation.reconciles`).

Global mean |SHAP| on a 200-row sample of the test split:

| Feature | Mean abs SHAP (log-odds) |
|---|---|
| EXT_SOURCE_3 | 0.403 |
| EXT_SOURCE_2 | 0.309 |
| EXT_SOURCE_1 | 0.190 |
| DAYS_EMPLOYED | 0.170 |
| AMT_GOODS_PRICE | 0.118 |

Three externally-supplied credit scores dominate. That is a limitation of the
dataset, not of the model, and it is why the uplift result in §6 should not be
generalised (see P1-F8).

Reason codes map through `config/reason_codes.yaml`; every sentence is
`TBD[Compliance, LH-203]`, so no adverse-action letter can be produced.

## 9. Limitations

Everything in the champion card §9, plus:

1. **Not promotable by construction.** No ratified monotone directions (LH-202).
2. **Its calibration is optimistic.** Early stopping ran on the validation split
   and the calibrator was then fitted on the same rows — Phase 1 §4 Steps 4 and 5
   use one set. `CalibrationReport.optimism_risk` is True on this run. The effect
   here is small (Brier 0.0690 → 0.0684) because `scale_pos_weight` was 1.0, but
   it would not be small at a production imbalance weighting. Finding P1-F2.
3. **No hyperparameter search.** The comparison against the champion is therefore
   between a tuned-by-construction scorecard and an untuned ensemble, which is a
   reason to treat the −0.07 uplift as weak evidence in either direction.
4. Feature-set asymmetry with the champion (17 vs 15) confounds the comparison
   slightly.

## 10. Monitoring and fallback

As the champion card §10. Additionally, an unconstrained ensemble needs
monotonicity re-checked at every retrain, not only at first validation: the
violations in §6 are a property of the fit, and a refit on new data will have
different ones.

## 11. Sign-off

**Unsigned and unsignable** — no independent validator, no ratified constraints,
no model-risk review. The promotion gate refuses on all three.

| Role | Name | Date |
|---|---|---|
| Developer | — | — |
| Independent validator | — | — |
| Model Risk Committee | — | — |

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

95 trees grown; **best iteration 80** by validation log-loss. Scoring truncates
at the best iteration.

## 3. Purpose and scope

Challenger to the WOE scorecard for application PD (SRS §4.3.2). Same population,
same target, same split, deliberately — a challenger evaluated on a different
sample measures the sample.

**Must not be used for**: any decision (no cutoffs, LH-204); any population
outside the fitted one; any Appendix A default estimate.

## 4. Data

Identical to the champion card §4: the same 60,000-row target table, the same
random holdout (train 35,700 / calibration 6,300 / validation 9,000 / test 9,000),
the same vendor label, the same three unenforceable exclusions. Training bads
2,884; test bads 727.

The challenger uses **all 16 IV-screened features**; the champion keeps the top
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

Discrimination on the raw score, calibration on the calibrated PD (SRS §4.3.4 v1.2).

| Metric | Champion | Challenger |
|---|---|---|
| AUC | 0.7222 | **0.7387** |
| Gini (points) | 44.45 | **47.73** |
| KS | 0.3247 | 0.3608 |
| Brier (calibrated PD) | 0.06996 | **0.06954** |
| ECE | 0.00935 | 0.00600 |
| PSI (train → test) | 0.0005 | 0.0018 |
| Train Gini | 42.95 | 51.43 |

**The challenger's uplift is +3.28 Gini points**, inside the +2–6 range SRS §4.3.2
cites from the Lessmann benchmark — but the figure is not stable and must not be
quoted alone. On a 42,000-row training set the same pair scores 47.77 / 47.78, an
uplift of **+0.01**. The whole difference is the champion's degradation on 15%
less data; the challenger moves 47.78 → 47.73, i.e. not at all. Finding P1-F8
gives the numbers and what follows from them.

Train Gini 51.43 against test 47.73 is a 3.7-point in-sample gap the champion does
not have, which is the expected shape: the ensemble has capacity to fit noise the
linear model cannot, and early stopping bounded but did not remove it.

**Exit criteria** (`ValidationReport.exit_criteria`):

| Criterion | Evaluated | Met |
|---|---|---|
| Challenger ≥ +3 Gini over legacy, out-of-time | **No** — split is not out of time, and the comparator is the champion, not a rebuilt legacy scorecard | — |
| Brier ≤ legacy | Yes | Yes (0.06954 ≤ 0.06996) |
| Monotonicity holds | Yes | **No** — see below |
| Score stability | Yes | Yes |
| Swap set: no adverse-segment concentration | **No** — the criterion has no numeric bar (LH-205) | — |

**Monotonicity spot checks fail, as designed.** Walking each of the top five
characteristics across its bin edges with the rest held fixed:

| Feature | Violations |
|---|---|
| EXT_SOURCE_3 | 0 |
| EXT_SOURCE_2 | 0 |
| EXT_SOURCE_1 | **1** |
| DAYS_EMPLOYED | 0 |
| credit_to_goods | 0 |

The ±10% sensitivity sweep says the same thing from another direction, and says
it louder: out of 400 test rows, a +10% and a −10% perturbation move the score the
*same* way for 10 rows on `EXT_SOURCE_3`, 14 on `EXT_SOURCE_2` and 17 on
`credit_to_goods` — locally non-monotone responses on characteristics whose grid
spot-check passed. A spot check walks one slice; the sweep walks 400, and the
disagreement between them is the reason both are run.

This is the concrete cost of LH-202. An unconstrained challenger *is*
non-monotone in features whose binned relationship is monotone, and the
regulator's "counter-intuitive behaviour" objection SRS §4.3.2.1 describes is
live rather than hypothetical.

**Swap-set analysis** against the champion at a common approval rate:

| Cell | Count | Bad rate |
|---|---|---|
| Both approve | 4,157 | — |
| Both decline | 3,097 | — |
| Swap in (champion declines, challenger approves) | 493 | **4.26%** |
| Swap out (champion approves, challenger declines) | 1,253 | **8.46%** |

The swap sets are the clearest evidence in this card. The challenger accepts 493
applicants the champion declined and they default at 4.26%; it declines 1,253 the
champion approved and they default at 8.46% — twice the rate. Both moves are in
the profitable direction, which is what a genuine +3.28 uplift should look like
from the business side rather than only in a Gini.

Segment concentration in the swap-out set (share of swap-outs ÷ share of
population):

| Age band | Concentration |
|---|---|
| 20–29 | **1.32** |
| 40–49 | 1.07 |
| 30–39 | 1.01 |
| 50–59 | 0.88 |
| 60–69 | 0.65 |

The 20–29 band takes 1.32× its population share of the challenger's new declines.
Whether that fails Phase 1 §7 is not computable — the bar is LH-205 — but the
measurement is exactly what that criterion needs, and it is not zero. Note that
this concentration was on a *different* band (60–69, at 1.86×) before the
calibration fix changed which applicants sit either side of the approval line:
swap-set concentration is a property of the operating point as much as of the
model, and a single measurement of it is a snapshot.

## 7. Fairness

Measured on the challenger's approvals (test split):

| Attribute | Demographic parity difference | Parity ratio | Equalized-odds difference |
|---|---|---|---|
| Age band | 0.4166 | 0.3974 | 0.4059 |
| Gender | 0.1035 | 0.8127 | 0.0985 |
| Region rating (pincode proxy) | 0.2667 | 0.5930 | 0.2521 |

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
| EXT_SOURCE_3 | 0.393 |
| EXT_SOURCE_2 | 0.315 |
| EXT_SOURCE_1 | 0.190 |
| DAYS_EMPLOYED | 0.177 |
| credit_to_goods | 0.117 |

Three externally-supplied credit scores dominate. That is a limitation of the
dataset, not of the model, and it is why the uplift result in §6 should not be
generalised (see P1-F8).

Reason codes map through `config/reason_codes.yaml`; every sentence is
`TBD[Compliance, LH-203]`, so no adverse-action letter can be produced.

## 9. Limitations

Everything in the champion card §9, plus:

1. **Not promotable by construction.** No ratified monotone directions (LH-202).
2. **The uplift figure is unstable** and swings from +0.01 to +3.28 on a 15%
   change in training-set size — a change that was about calibration hygiene, not
   about either model. Quote it only with the split protocol and training-set size
   attached. Finding P1-F8.
3. **No hyperparameter search.** The comparison is between a scorecard whose
   binning is optimal by construction and an untuned ensemble, which is a reason
   to treat the uplift as weak evidence in either direction.
4. Feature-set asymmetry with the champion (16 vs 15) confounds the comparison
   slightly.
5. Its calibration is **not** optimistic on this run — the calibrator was fitted
   on a dedicated 6,300-row block neither model saw (Phase 1 §4 Step 5 v1.1), and
   `optimism_risk` is False. That block is small enough that the isotonic fit
   expresses only ~50 distinct PDs, which is why discrimination is reported on the
   raw score (finding P1-F13).

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

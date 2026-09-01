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
| Data snapshot | Home Credit `application_train.csv` (first 150,000 rows) + `bureau.csv` + `POS_CASH_balance.csv`, `--seed 20260901` |
| Config hash | `n_trees=400, max_depth=3, learning_rate=0.1, max_bins=32, l2=1.0, gamma=0.0, min_child_weight=1.0, feature_fraction=1.0, early_stopping_rounds=15, scale_pos_weight=1.0, seed=20260901` — depth, rate, `min_child_weight` and `l2` **selected by the §4 Step 4 search**, not chosen |
| Definitions fingerprint | `run.definitions_fingerprint` in the report (Appendix A v1.1) |

255 trees grown; **best iteration 240** by validation log-loss. Scoring truncates
at the best iteration.

## 3. Purpose and scope

Challenger to the WOE scorecard for application PD (SRS §4.3.2). Same population,
same target, same split, deliberately — a challenger evaluated on a different
sample measures the sample.

**Must not be used for**: any decision (no cutoffs, LH-204); any population
outside the fitted one; any Appendix A default estimate.

## 4. Data

Identical to the champion card §4: the same 150,000-row target table across three
Home Credit tables, the same random holdout (train 89,250 / calibration 15,750 /
validation 22,500 / test 22,500), the same vendor label, the same three
unenforceable exclusions.

The challenger uses **all 77 binnable features**; the champion uses 12. That
asymmetry is deliberate and it changed in this release. The IV floor had been
applied to both, which is a misreading of both documents — SRS §4.3.1 states the
screen inside the *champion's* method and Step 4 says nothing about IV — and it was
discarding 51 of 77 features before the challenger saw them. A scorecard needs each
characteristic to carry standalone signal because each contributes independently; a
tree ensemble's advantage *is* the interaction between features that are
individually weak. The leakage *ceiling* still applies to both. Finding D4.

## 5. Methodology

- **Algorithm**: histogram gradient boosting with the regularised second-order
  gain of SRS §4.3.2, depth-limited, early-stopped on the validation split.
- **Reference**: LightGBM (Ke et al., NeurIPS 2017) for the histogram split
  structure; XGBoost (Chen & Guestrin) for the gain and the monotone-constraint
  enforcement. `lending_hub.scoring.gbm` is a **documented port**: it implements
  histogram split finding and the regularised gain, and does **not** implement
  GOSS or EFB, which are LightGBM's speed optimisations at a scale this reference
  implementation does not target.
- **Alternatives**: the champion scorecard, fitted in the same run on the same
  split — see §6 for what each buys.
- **Hyperparameters**: **searched**, as Phase 1 §4 Step 4 requires. Six named
  configurations bracketing LightGBM's documented defaults, fitted on a seeded
  30,000-row subsample of train, selected by **validation log-loss** — not
  validation AUC, because a search that optimises ranking says nothing about
  whether the probabilities mean anything, and calibration happens afterwards on
  rows neither the fit nor the search has seen. The test set was not read.

  | Configuration | depth | rate | validation log-loss |
  |---|---|---|---|
  | **library-default** | 3 | 0.10 | **0.255699** |
  | deeper-regularised | 4 | 0.05 | 0.256207 |
  | deepest-regularised | 5 | 0.05 | 0.256430 |
  | deeper | 4 | 0.10 | 0.256825 |
  | shallow-slow | 3 | 0.05 | 0.256856 |
  | shallow-heavy-leaf | 3 | 0.05 | 0.256952 |

  The spread is 0.0013 in log-loss. The search's honest conclusion is that on this
  feature set the configuration barely matters and the library default wins — a
  useful thing to have measured rather than assumed, and it means the earlier
  card's "the challenger was not tuned" confound was smaller than it looked.
- **Monotonicity constraints**: **none applied.** The ratified direction list is
  `[POLICY: Credit Risk Head]` and does not exist (LH-202), so the model was
  fitted through `MonotoneConstraints.for_experiment` with a written reason, and
  `promotable` returns `(False, "monotone directions are not ratified (LH-202)")`.
  The consequences are visible in §6 and are the point of recording them.

## 6. Performance

Test split, 22,500 applications. Discrimination on the raw score, calibration on
the calibrated PD (SRS §4.3.4 v1.2).

| Metric | Champion | Challenger |
|---|---|---|
| AUC | 0.7343 | **0.7597** |
| Gini (points) | 46.86 | **51.94** |
| KS | 0.3585 | 0.3899 |
| Brier (calibrated PD) | 0.06894 | **0.06739** |
| Brier skill vs base-rate null | +0.0810 | **+0.1017** |
| ECE | 0.00708 | 0.00740 |
| PSI (train → test) | 0.0006 | 0.0018 |
| Train Gini | 46.35 | 57.79 |

**The challenger's uplift is +5.08 Gini points**, inside the +2–6 range SRS §4.3.2
cites from the Lessmann benchmark. The figure has been unstable across this
model's history — an earlier configuration produced +0.01 — so it is quoted with
the training-set size and feature set that produced it, and finding P1-F8 records
why a single-run uplift is not evidence.

Read the Brier alongside its skill score: predicting the 8.17% base rate for
everyone scores 0.07501, so the whole usable range of that metric is about 0.006
(finding P1-F14).

Train Gini 57.79 against test 51.94 is a 5.9-point in-sample gap the champion does
not have, and it widened as the feature set grew from 16 to 77. That is the
expected shape — the ensemble has capacity to fit noise the linear model cannot,
and early stopping bounded it rather than removing it — but it is the number to
watch if the feature set grows further.

**Exit criteria** (`ValidationReport.exit_criteria`):

| Criterion | Evaluated | Met |
|---|---|---|
| Challenger ≥ +3 Gini over legacy, out-of-time | **No** — split is not out of time, and the comparator is the champion, not a rebuilt legacy scorecard | — |
| Brier ≤ legacy | Yes | Yes (0.06739 ≤ 0.06894) |
| Monotonicity holds | Yes | **No** — see below |
| Score stability | Yes | Yes |
| Swap set: no adverse-segment concentration | **No** — the criterion has no numeric bar (LH-205) | — |

**Monotonicity spot checks fail, as designed.** Walking each of the top five
characteristics across its bin edges with the rest held fixed:

| Feature | Violations |
|---|---|
| EXT_SOURCE_3 | 0 |
| EXT_SOURCE_2 | 0 |
| EXT_SOURCE_1 | 0 |
| DAYS_EMPLOYED | **1** |
| bureau_days_since_last | **1** |

The ±10% sensitivity sweep says the same thing from another direction, and says
it louder: out of 400 test rows a +10% and a −10% perturbation move the score the
*same* way for a double-digit count on the strongest features — locally
non-monotone responses on characteristics whose grid spot-check passed. A spot check walks one slice; the sweep walks 400, and the
disagreement between them is the reason both are run.

This is the concrete cost of LH-202. An unconstrained challenger *is*
non-monotone in features whose binned relationship is monotone, and the
regulator's "counter-intuitive behaviour" objection SRS §4.3.2.1 describes is
live rather than hypothetical.

**Swap-set analysis** against the champion at a common approval rate:

| Cell | Count | Bad rate |
|---|---|---|
| Swap in (champion declines, challenger approves) | 2,712 | **5.24%** |
| Swap out (champion approves, challenger declines) | 1,215 | **9.05%** |

The swap sets are the clearest evidence in this card. The challenger accepts 2,712
applicants the champion declined and they default at 5.24% — below the 8.17%
portfolio rate — and declines 1,215 the champion approved that default at 9.05%.
Both moves are in the profitable direction, which is what a genuine uplift looks
like from the business side rather than only in a Gini.

Segment concentration in the swap-out set (share of swap-outs ÷ share of
population):

| Age band | Concentration |
|---|---|
| 50–59 | **1.23** |
| 40–49 | 1.15 |
| 30–39 | 0.93 |

The 50–59 band takes 1.23× its population share of the challenger's new declines.
Whether that fails Phase 1 §7 is not computable — the bar is LH-205 — but the
measurement is exactly what that criterion needs, and it is not zero. Note that
this concentration has landed on a *different* band in each configuration (60–69 at 1.86×, then 20–29 at 1.32×) as the
calibration fix changed which applicants sit either side of the approval line:
swap-set concentration is a property of the operating point as much as of the
model, and a single measurement of it is a snapshot.

## 7. Fairness

Measured on the challenger's approvals (test split):

| Attribute | Demographic parity difference | Parity ratio | Equalized-odds difference |
|---|---|---|---|
| Age band | 0.4250 | 0.4451 | — |
| Gender | 0.0778 | 0.8716 | — |
| Region rating (pincode proxy) | 0.2653 | 0.6347 | — |

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
| EXT_SOURCE_3 | 0.391 |
| EXT_SOURCE_2 | 0.358 |
| EXT_SOURCE_1 | 0.195 |
| DAYS_EMPLOYED | 0.152 |
| credit_to_goods | 0.136 |
| AMT_GOODS_PRICE | 0.125 |

Three externally-supplied credit scores dominate. That is a limitation of the
dataset, not of the model, and it is why the uplift result in §6 should not be
generalised (see P1-F8).

Reason codes map through `config/reason_codes.yaml`; every sentence is
`TBD[Compliance, LH-203]`, so no adverse-action letter can be produced.

## 9. Limitations

Everything in the champion card §9, plus:

1. **Not promotable by construction.** No ratified monotone directions (LH-202).
2. **The uplift figure has been unstable** across configurations of this model,
   from +0.01 to +5.08. Quote it only with the split protocol, training-set size
   and feature set attached. Finding P1-F8.
3. **Feature-set asymmetry with the champion** (77 vs 12) is now large and
   deliberate. It is the correct asymmetry — see §4 — but it means the comparison
   is between two differently-scoped models, not between two algorithms.
4. **The in-sample gap widened** with the feature set (5.9 Gini points against the
   champion's 0.5). Early stopping bounds it; more features would widen it further.
5. Its calibration is **not** optimistic — the calibrator was fitted on a dedicated
   15,750-row block neither model saw (Phase 1 §4 Step 5 v1.1) and `optimism_risk`
   is False. Discrimination is still reported on the raw score, because an isotonic
   step function quantises the PD (finding P1-F13).
6. **The history features carry the source's point-in-time limitation.** "Strictly
   before the application" is the strongest claim available, and it is a claim
   about the publisher's relative month index rather than about knowability in a
   production pipeline.

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

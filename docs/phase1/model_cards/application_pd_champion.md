# Model Card — application_pd_champion (WOE scorecard) v0.1.0-trackP

> **This is a Track P model card.** It documents a model fitted on public
> reference data (ADR-0004) to prove the WS-1.1 code paths. It is **not** a
> candidate for shadow, canary or production on this bank's portfolio, and none
> of its numbers is Phase 1 gate evidence. The card is completed in full anyway —
> a card written for the first time under gate pressure is a card nobody has
> tested.

## 1. Identification

| Field | Value |
|---|---|
| Model name / version | `application_pd_champion` v0.1.0-trackP |
| Registry stage | None — not registered; not promotable (see §11) |
| Model tier | Tier 1 if ever customer-affecting (WS-0.3.1); currently non-decisioning |
| Owner (accountable) | Credit DS squad lead |
| Developer (R) | Credit DS |
| Independent validator | **Not assigned.** Master §3.1 requires a validator who is not the developer; on Track P none exists, and the model is unpromotable for this reason alone |
| Date registered | Not registered |

## 2. Reproducibility triplet

| Field | Value |
|---|---|
| Code commit SHA | The commit that produced `reports/trackP_p1_home_credit.json` |
| Data snapshot | Home Credit `application_train.csv` (first 150,000 rows) + `bureau.csv` + `POS_CASH_balance.csv`, `--seed 20260901` |
| Config hash | `--limit 150000 --seed 20260901 --trees 400`; scorecard `epochs=15`, stepwise sign elimination, 15% calibration block carved from train |
| Definitions fingerprint | Recorded in the run report under `run.definitions_fingerprint` (Appendix A v1.1) |

Regenerate with `make trackp-p1`. The fit is deterministic given the seed.

## 3. Purpose and scope

Estimates a calibrated probability of default at application time for a single
unsecured consumer-credit product, as the **champion** in the Phase 1
champion/challenger pair (SRS §4.3.1).

**It must not be used for**: any population other than the Home Credit consumer
book it was fitted on; any decision at all — no approve/decline cutoffs exist
(LH-204); any statement about this bank's portfolio; any Appendix A default
estimate, because it was not fitted to an Appendix A target (§4).

## 4. Data

- **Sources**: [`config/sources/home_credit_default_risk.yaml`](../../../config/sources/home_credit_default_risk.yaml). Track P, `point_in_time_unsafe: true`. Three tables:
  `application_train.csv` (150,000 rows read), `bureau.csv` (1,716,428 credit records
  aggregated to 128,682 of those applicants) and `POS_CASH_balance.csv` (10,001,358
  monthly balances aggregated to 141,073). The last carries `SK_DPD` — observed days
  past due on prior loans, not a proxy for it.
- **History point-in-time rule**: only months strictly before the application are
  aggregated. The publisher documents `MONTHS_BALANCE = 0` as "the information at
  application", which is probably knowable at decision time and not certainly so;
  the cost of excluding it is one month of history and the cost of including it
  wrongly is a leak in the strongest feature in the set.
- **Observation point / outcome window**: not Appendix A's. The source publishes
  a ready-made label and no DPD history, so neither the observation point nor the
  window is under this project's control. See the target definition below.
- **Target definition**: `LabelProvenance.VENDOR`. Home Credit's `TARGET` — the
  publisher's own payment-difficulty flag, with the publisher's window and
  thresholds. **Not** `lending_hub.definitions.label`, and the target table
  reports `appendix_a_aligned: false`.
- **Population**: 150,000 applications read, all labelled and kept; 0 undetermined;
  0 excluded. Bad rate **8.17%**.
- **Split** (random holdout, seed 20260901): train 89,250 · calibration 15,750 ·
  validation 22,500 · test 22,500. The calibration block is carved out of train per
  Phase 1 §4 Step 5 (v1.1) so that no row is used for both fitting and
  calibrating.
- **Exclusions**: all three Phase 1 exclusions (fraud-tagged, staff loan,
  restructure) are **unenforceable** on this source — a public extract carries
  none of the flags. Accepted deliberately via `require_enforceable=False` and
  recorded in the target ledger, which reconciles exactly (150,000 in = 150,000
  kept + 0 + 0).
- **Indeterminates**: none. A vendor label is binary by construction, so no
  indeterminate band exists to preserve. This is a **loss** relative to an
  Appendix A target, not a simplification.
- **Point-in-time correctness**: not demonstrated and not demonstrable. The
  source has no absolute timeline (Track P finding F6).

## 5. Methodology

- **Algorithm**: monotone optimal binning → WOE transform → regularised logistic
  regression on WOE, per SRS §4.3.1.
- **Reference**: OptBinning (Navas-Palencia) for the binning; Siddiqi / Hand &
  Henley for the scorecard form. `lending_hub.scoring.binning` is a **documented
  port**, not the library: it takes the L2-optimal monotone fit of the event rate
  (PAVA) and adopts its pooled blocks as bins, where OptBinning solves an
  IV-maximising MIP. The difference is stated in the module docstring.
- **Alternatives considered**: the challenger (§ challenger card). The scorecard
  is champion because its per-characteristic contributions *are* the reason codes
  rather than an attribution method's estimate of them.
- **Feature selection**: 77 candidates — application, derived affordability
  ratios, bureau aggregates and prior-repayment aggregates — screened by
  information value against the SRS §4.3.1 window [0.02, 0.5]. 26 passed; none
  tripped the leakage ceiling. The card is then built by **stepwise sign
  elimination**: fit, drop the most negative coefficient, backfill from the
  IV-ranked pool, refit. Fourteen characteristics were dropped this way and the
  procedure converged — no wrong signs remain (`signs_converged: true`), which is
  reported explicitly because the procedure can exhaust its budget without getting
  there.
- **Final card (12 characteristics)**: `EXT_SOURCE_3`, `EXT_SOURCE_2`,
  `EXT_SOURCE_1`, `DAYS_EMPLOYED`, `bureau_days_since_last`, `credit_to_goods`,
  `NAME_INCOME_TYPE=Working`, `AMT_GOODS_PRICE`, `NAME_INCOME_TYPE=Pensioner`,
  `AMT_CREDIT`, `bureau_max_amount_overdue`, `pos_completed_count`. Two of the
  twelve come from the history tables the earlier version of this model ignored.
- **Hyperparameters**: 15 SGD epochs, learning rate 0.1, L2 1e-3, seed 20260901,
  inverse-base-rate class weighting.
- **Monotonicity**: every binning direction was **inferred from the data**
  (`direction_source: "data"`), because the ratified direction list is `[POLICY]`
  and does not exist (LH-202). An inferred direction is a restatement of the fit,
  not a constraint.

## 6. Performance

Test split, 22,500 applications. Discrimination on the raw score, calibration on
the calibrated PD (SRS §4.3.4 v1.2).

| Metric | Train | Test |
|---|---|---|
| AUC | — | **0.7343** |
| Gini (points) | 46.35 | **46.86** |
| KS | — | 0.3585 |
| Brier (calibrated PD) | — | **0.06894** |
| Brier skill vs base-rate null | — | **+0.0810** |
| ECE | — | 0.00708 |
| PSI, train → test (calibrated PD) | — | 0.0006 |

**Read the Brier with its skill score.** Predicting the 8.17% base rate for every
applicant scores 0.07501, so the whole usable range of the metric is about 0.006.
Brier alone makes a good model and a useless one look almost identical at this
base rate — finding P1-F14.

**The test split is not out of time.** The source has no clock, so the holdout is
random and stamped `out_of_time: false`. These numbers say nothing about how the
model travels across a macro regime, which is the question an out-of-time test
exists to answer. The §7 champion criterion is therefore unevaluated — as is the
Brier comparison, since there is no rebuilt legacy scorecard on Track P.

**This model is sensitive to training-set size**, more so than the challenger —
a 12-characteristic scorecard rests on bin-level event rates, and a bin holding 5%
of the sample has a noisier WOE the smaller the sample gets. An earlier run on
35,700 training rows scored 44.45 against 47.77 on 42,000. Do not compare it to a
challenger fitted on a different number of rows. Finding P1-F8.

Train Gini 46.35 against test 46.86 is the expected shape for a heavily
regularised linear model on twelve characteristics: no capacity to overfit 89,250
rows.

**Calibration is not optional for this model.** Raw Brier 0.1654 → calibrated
0.0696, a factor of two. Inverse-base-rate class weighting makes the raw output a
ranking, not a probability. SRS §4.3.2.2 makes this point about GBMs; it applies
more strongly to a class-weighted scorecard, and a pipeline that calibrated only
the challenger would ship an uncalibrated champion.

The calibrator was fitted on the dedicated 15,750-row block, which neither model
saw — so `optimism_risk` is False, and the reliability diagram describes the model
rather than the selection.

## 7. Fairness

Measured on the test split (`assess`, protected attributes read only through
`ProtectedAttributeAccess`):

| Attribute | Demographic parity difference | Parity ratio |
|---|---|---|
| Age band | 0.4250 | 0.4451 |
| Gender | 0.0778 | 0.8716 |
| Region rating (pincode proxy) | 0.2653 | 0.6347 |

No group was flagged as statistically indistinguishable from noise. The gender
disparity narrowed from 0.1035 to 0.0778 as the history features entered — real
repayment behaviour displacing proxies is the direction one would hope for, and it
is one run, not a trend.

**No verdict is recorded, and none can be.** The disparity level requiring action
is `[POLICY: Fair-Lending Committee]` (LH-205); `FairnessReport.verdict()` raises.

The age-band disparity is the finding that matters and it has an identifiable
cause: `DAYS_EMPLOYED`, `DAYS_REGISTRATION` and `DAYS_ID_PUBLISH` are all
elapsed-time columns that correlate strongly with age. Age is excluded as a
feature and re-enters through three proxies — the exact mechanism SRS §4.3.3's
proxy probe exists to detect, observed live rather than hypothesised.

## 8. Explainability

Per-characteristic point contributions, exact by construction for a linear model
on binned inputs. Reason codes default to **points-below-max** — the distance
from the applicant's bin to the best attainable bin on that characteristic —
rather than the largest raw negative contribution; the divergence from Phase 1
§4 Step 3's literal wording is Finding P1-F3.

Codes map to wording through [`config/reason_codes.yaml`](../../../config/reason_codes.yaml).
Every sentence there is `TBD[Compliance, LH-203]` and `render()` raises on one.
**No adverse-action letter can be produced from this model.**

## 9. Limitations

1. Track P: real applications, not this bank's portfolio.
2. The target is the vendor's, not Appendix A. Every comparison against a bank
   model is apples to oranges.
3. No out-of-time evidence exists or can exist for this source.
4. Reject inference not performed — no declined applications are published
   (ADR-0010). The model estimates default risk *conditional on having been
   approved*, not through-the-door risk. Full memo in the run report.
5. No indeterminate band, so the sharpness of the good/bad boundary is the
   vendor's choice, not a modelled one.
6. **Resolved.** An earlier version of this card listed five characteristics with
   negative fitted coefficients as a known limitation. Stepwise sign elimination
   now removes them: fourteen were dropped and backfilled, and the card converged
   with none remaining. That the procedure needed fourteen rounds is itself a
   finding about the feature set — bureau aggregates are heavily collinear with
   one another, so most of them cannot sit on the same card.
7. **Its Track P numbers depend on the training-set size** (see §6). Any
   comparison against the challenger must hold that constant.
8. **The history aggregates inherit the source's point-in-time limitation.** They
   are built from a source declared `point_in_time_unsafe`: there is no absolute
   timeline and no ingestion timestamp, so "strictly before the application" is
   the strongest claim available and it is a claim about the publisher's own
   relative month index, not about knowability in a production pipeline.
9. Thin-file and new-to-credit populations are not separately validated (SRS
   CS-3 requires segment models; out of scope for P1's single product).

## 10. Monitoring and fallback

Monitoring plan: not written — this model is not deployed. Were it deployed, the
triggers would be the SRS §4.3.4 ones the code already computes: score PSI alert
> 0.1 and act > 0.25 (`screen_psi`), plus calibration drift on the reliability
diagram. The warm fallback path is the legacy decisioning route (SRS §12), which
does not exist on Track P.

## 11. Sign-off

**Unsigned, and it cannot be signed.** Master §3.1 requires an independent
validator who is not the developer; Master §2 rule 5 requires a completed card
reviewed by model risk before shadow. Neither has happened, and the promotion
gate (`lending_hub.mlops.promotion`) refuses the transition on that basis.

| Role | Name | Date |
|---|---|---|
| Developer | — | — |
| Independent validator | — | — |
| Model Risk Committee | — | — |

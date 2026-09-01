# Model Card — behavioural_pd (discrete-time GBM) v0.1.0-trackP

> **This is a Track P model card.** It documents a model fitted on public
> reference data (ADR-0004, ADR-0012) to prove the WS-3.1 code paths. It is
> **not** a candidate for shadow, canary or production on this bank's portfolio,
> and none of its numbers is Phase 3 gate evidence. The card is completed in
> full anyway — a card written for the first time under gate pressure is a card
> nobody has tested.

## 1. Identification

| Field | Value |
|---|---|
| Model name / version | `behavioural_pd` v0.1.0-trackP |
| Registry stage | None — not registered; not promotable (see §11) |
| Model tier | Tier 1 if ever customer-affecting (WS-0.3.1); currently non-decisioning |
| Owner (accountable) | Credit DS squad lead |
| Developer (R) | Credit DS |
| Independent validator | **Not assigned.** Master §3.1 requires a validator who is not the developer; on Track P none exists, and the model is unpromotable for this reason alone |
| Date registered | Not registered |

## 2. Reproducibility triplet

| Field | Value |
|---|---|
| Code commit SHA | The commit that produced `reports/trackP_p3_fannie_mae.json` |
| Data snapshot | Fannie Mae Single-Family Loan Performance, 2007Q1 vintage, whole-loan sample at the rate recorded in the run report's `panel.sample_rate` |
| Config hash | `n_trees=60`, `max_depth=4`, `learning_rate=0.1`, `min_months_on_book=3`, out-of-time split at 2012-12-31 |
| Definitions fingerprint | Recorded in the run report under `definitions_fingerprint` (Appendix A v1.1) |

Regenerate with `make trackp-p3`. Sampling is a stable hash of the loan id, so
the same loans are drawn on every run.

## 3. Purpose and scope

Estimates the probability that a live account reaches Appendix A default within
the next 12 months, refreshed monthly (SRS §7.3.1, DP-1). This is the model
Phase 3 ships first because it powers the dashboards immediately.

**It must not be used for**: any population other than the US conforming
mortgages it was fitted on; any decision at all — no score bands exist (LH-204);
any statement about this bank's portfolio; lifetime ECL, which needs the
survival model and a ratified SICR threshold (LH-301).

## 4. Data

One row per account-month, built by `lending_hub.portfolio.panel` and featurised
by `lending_hub.portfolio.behavioural`. Target: Appendix A default in months
`(t, t+12]`.

Rows excluded from training, counted separately in the run report:

* **INDETERMINATE** — the 30-to-89 arrears band Appendix A excludes from training
  targets. Substantial on a behavioural panel.
* **Undetermined** — the 12-month window runs past the extract end. Distinct from
  the above, and only this one shrinks as data arrives.

## 5. Features

Trailing-window behavioural features (max DPD over 3/6/12 months, times in
arrears, DPD trend, balance ratios, observed/unobserved month counts) plus
origination attributes.

**Point-in-time guarantee.** Every feature at month `t` is computed from
`months[:t+1]` in a single slice, and
`behavioural.assert_point_in_time()` proves the property directly by rewriting
every later month and re-deriving. A test drives a deliberate leak through the
check to confirm it bites.

**Absent by design**: the agri NDVI/SPEI features SRS §7.3.1 lists come from
Phase 2, which does not exist. They are absent rather than zero-filled — a zero
NDVI is a real value meaning bare ground.

## 6. Performance

All figures **Track P**, out of time (split 2012-12-31), from the run report.

| Metric | Value |
|---|---|
| Out-of-time Gini | See `behavioural_pd.test_gini` |
| Out-of-time Gini, arrears features removed | See `behavioural_pd.ablation_without_arrears_features.test_gini` |

**Read these together.** The headline figure is dominated by current and recent
arrears, which is the expected behaviour of a behavioural scorecard (SRS §7.3.1)
and not a leak. It does mean the number answers "will this delinquency continue",
which is a much easier question than an application scorecard's — the two are not
comparable, and the ablation is reported so that nobody compares them. See
Phase 3 findings B4.

## 7. Fairness

**Not assessed.** The Fannie Mae extract carries no protected attributes, by
design of the public release. No fairness claim can be made about this model in
either direction, and its absence here is not evidence of absence of disparity.

## 8. Limitations

* US conforming mortgages: secured, prime, one country, one product. Nothing
  about the seasoning shape or arrears dynamics transfers to an Indian retail or
  agri book.
* The vendor's delinquency status is the label source; Appendix A's non-DPD arms
  (write-off, distress restructure, fraud) are unavailable (LH-103).
* Servicer reporting gaps are carried as unobserved, never as current.

## 9. Monitoring

`portfolio.health` provides PSI over reference bin edges, ADWIN on the score
stream, and a two-sided calibration CUSUM. **No alarm thresholds are set**: the
CUSUM `k`/`h` and the ADWIN `δ` are LH-307 and the functions require them.

## 10. Decision provenance

Not decisioning. Were it wired to the orchestrator, every band edge is a
registered placeholder (LH-204) and every application would be referred.

## 11. Promotion status

**Not promotable.** `BehaviouralModel.promotable` returns false with:

> monotone directions for the behavioural feature set are not ratified (LH-310).
> LH-202 covers application features only.

Independently: no independent validator (§1), and Track P results are not gate
evidence (ADR-0012).

## 12. Sign-off

| Role | Name | Date |
|---|---|---|
| Developer | — | — |
| Independent validator | — | — |
| Model Risk | — | — |

**Unsigned.** An unsigned card is not a completed card.

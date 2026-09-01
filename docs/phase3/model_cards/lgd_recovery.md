# Model Card — lgd_recovery (beta regression, stage 2 only) v0.1.0-trackP

> **This is a Track P model card** (ADR-0004, ADR-0012). Not a candidate for
> shadow, canary or production; none of its numbers is Phase 3 gate evidence.
>
> **It is also only half a model.** SRS §7.3.3 specifies two stages; stage 1
> (cure) cannot be built because Appendix A defines default but not cure
> (LH-309). This card documents stage 2 alone, and the distinction is load-bearing
> — see §3.

## 1. Identification

| Field | Value |
|---|---|
| Model name / version | `lgd_recovery` v0.1.0-trackP |
| Registry stage | None — not registered; not promotable (see §11) |
| Owner (accountable) | Credit DS squad lead, with Finance (C) for the loss basis |
| Developer (R) | Credit DS |
| Independent validator | **Not assigned** (Master §3.1) |

## 2. Reproducibility triplet

| Field | Value |
|---|---|
| Code commit SHA | The commit that produced `reports/trackP_p3_fannie_mae.json` |
| Data snapshot | Fannie Mae 2007Q1, all loss dispositions (zero-balance codes 02, 03, 09) with positive exposure |
| Config hash | Beta regression, logit link, joint Fisher scoring on (β, φ); Smithson-Verkuilen squeeze applied |
| Definitions fingerprint | Run report `definitions_fingerprint` |

## 3. Purpose and scope

Estimates **E[LGD | not cured]** — the recovery-rate stage of the two-stage LGD
model (SRS §7.3.3), on real workout cashflows.

**This is not LGD.** Using it as LGD assumes no account ever cures, which
overstates the loss on every secured product. `TwoStageLGD.expected_lgd()` raises
until LH-309 supplies a cure definition; `loss_given_no_cure()` returns this
quantity under its own name.

**Also not usable for ECL**: the discounting convention is LH-305 and
`discounted_lgd()` raises. This model is fitted on the **undiscounted** realised
loss, which is a different quantity.

## 4. The loss basis — read this before quoting any coefficient

`realised_lgd()` requires a `LossBasis` and has no default, because the basis
decides the **sign** of the LTV effect (finding P3-F2, ticket LH-311). Measured
on this data:

| Basis | `oltv` coefficient | `credit_score` coefficient |
|---|---|---|
| Net of credit enhancement | −0.76 | +0.11 |
| Gross of credit enhancement | **+2.55** | **−0.44** |

Private mortgage insurance is required above 80% LTV and paid on ~90% of the
losses carrying it, so *net of it* less equity means smaller losses — true of
the insurance structure, false of the collateral. The run report fits both and
the gate pack tabulates them. **Neither is the model** until LH-311 says which
basis the bank uses.

## 5. Method

Beta regression with a logit link and constant precision (Ferrari &
Cribari-Neto 2004), fitted by joint Fisher scoring on (β, φ) with stdlib
digamma/trigamma. Recovers known generating parameters (−1.0, 2.0, 8.0) as
(−1.09, 2.13, 7.75) on simulated data.

Drivers: original LTV, DTI, credit score, original UPB. SRS §7.3.3 also lists
collateral type, legal-recovery route and (agri) land quality; none is present
in this extract.

## 6. The boundary problem

Realised LGD is **not** beta-distributed. It has point masses at 0 (collateral
covered everything) and at 1 (it did not), with a spread between.
`LGDDistribution` counts them separately and raises a caveat when the boundary
share is material. The Smithson-Verkuilen squeeze moves them inside the open
interval before fitting — this **changes every observation**, and it is applied
in `fit_beta_regression` rather than by the caller so that a fit on boundary
data cannot happen by forgetting it.

The fitted model therefore describes the interior. A zero-and-one-inflated model
would represent the masses; Phase 3 names beta regression and that is what is
here, with the limitation stated rather than modelled away.

## 7. Data quality

Two real feed behaviours, both kept rather than filtered, both counted:

* Holding expenses post **net of credits** (Fannie's own field is "miscellaneous
  holding expenses *and credits*"), so costs can be negative.
* Proceeds can post as **reversals** — 2 rows in 20,459 on this vintage.

Rejecting either as malformed would drop real workouts and bias the sample
toward expensive ones. `LGDDistribution.reversals` reports the count.

## 8. Limitations

* Undiscounted (LH-305). Not an ECL input.
* No downturn add-on (LH-302). The 2007 vintage *is* a downturn cohort, which
  makes the arithmetic demonstrable and the number inapplicable elsewhere.
* Stage 1 absent (LH-309).
* US mortgage severity. Collateral, legal-recovery route and timelines are
  nothing like an Indian secured book's.

## 9. Fairness

**Not assessed** — no protected attributes in the extract.

## 10. Decision provenance

Not decisioning.

## 11. Promotion status

**Not promotable.** `TwoStageLGD.promotable` returns false with:

> stage 1 (cure) is not buildable: TBD[Credit Policy, LH-309]. SRS §7.3.3 makes
> cure probability the first stage, and Appendix A defines default but not cure.

Plus: no ratified loss basis (LH-311), no discounting convention (LH-305), no
independent validator.

## 12. Sign-off

| Role | Name | Date |
|---|---|---|
| Developer | — | — |
| Independent validator | — | — |
| Model Risk | — | — |

**Unsigned.**

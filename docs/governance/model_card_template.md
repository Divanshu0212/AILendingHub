# Model Card — <model name> v<version>

> Template for Master §2 rule 5: **no model passes shadow without a completed model
> card reviewed by the model-risk team.** Based on Mitchell et al.,
> [arXiv:1810.03993](https://arxiv.org/abs/1810.03993), extended to the
> bank-validation depth SRS §11.2 requires.
>
> Delete this quote block when filling it in. Do not delete a section — write
> "not applicable" and say why. A silently missing section is the one a validator
> asks about first.

## 1. Identification

| Field | Value |
|---|---|
| Model name / version | |
| Registry stage | None / Staging / Production / Archived |
| Model tier | Tier 1 if customer-affecting (WS-0.3.1) |
| Owner (accountable) | |
| Developer (R) | |
| Independent validator | Must not be the developer (Master §3.1) |
| Date registered | |

## 2. Reproducibility triplet

| Field | Value |
|---|---|
| Code commit SHA | |
| Data snapshot (Iceberg tag) | |
| Config hash | |
| Definitions fingerprint | `lending_hub.definitions.fingerprint()` at training time |

If Appendix A has changed since training, the Master §4 impact analysis is
**required before promotion** — the promotion gate refuses without it.

## 3. Purpose and scope

What decision it informs, for which product and population, and — as importantly
— what it must **not** be used for. A model reused outside its documented
population is the most common way a validated model becomes an unvalidated one.

## 4. Data

- Sources (cite `config/sources/<id>.yaml` for each).
- Observation point and outcome window (cite Appendix A; do not restate them).
- Target definition — must be `lending_hub.definitions.label`, not a local variant.
- Population: inclusions, exclusions, and the count at each filtering step.
- Indeterminates: how many, and confirmation they were excluded from training and
  retained in reporting.
- Point-in-time correctness: how the training set was built, and evidence that
  `created_timestamp` was respected, not just `event_timestamp`.

## 5. Methodology

- Algorithm, and the single reference paper and library (Master §2 rule 2).
- Alternatives considered and why they were rejected. "We tried the simple one
  first" is a real answer and validators prefer it to silence.
- Hyperparameters and how they were selected.
- Monotonicity constraints and their directions — `[POLICY]` from P1.

## 6. Performance

- Discrimination and calibration, in-time and **out-of-time**. Out-of-time is the
  number that matters; in-time alone is a description of the training set.
- Performance by segment, including the segments the business cares about and the
  ones it does not.
- Stability (PSI) against the development sample.

## 7. Fairness

Metrics and mitigations per SRS §4.3.3 and §11.3. Where geospatial features are
used, the explicit geographic disparate-impact test SRS §11.3 requires, plus the
documented business necessity.

## 8. Explainability

Reason-code derivation, and how reason codes map to customer-facing wording.
Wording is `[POLICY]` — the card records the mapping, never invents the sentence.

## 9. Limitations

Where the model is known to be weak: thin-file populations, new products,
post-shock regimes, segments with little data. A card with no limitations section
has not been reviewed.

## 10. Monitoring and fallback

Link the monitoring plan. State the automatic rollback triggers (PSI /
calibration breach per SRS §11.1) and the fallback path that stays warm.

## 11. Sign-off

| Role | Name | Date |
|---|---|---|
| Developer | | |
| Independent validator | | |
| Model Risk Committee | | |

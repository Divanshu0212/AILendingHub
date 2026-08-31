# Independent Validation Report — <model name> v<version>

> Master §3.1: the evidence pack presented at each gate includes an **independent**
> validation report. Independent means the validator did not build the model
> (Master §3.1, SR 11-7). If that is not true of you, stop and escalate — a
> validation report written by the developer is not a weaker control, it is not a
> control.

## 1. Scope and conclusion

State the conclusion first: **fit for purpose / fit with conditions / not fit**.
Conditions are dated and owned, or they are wishes.

## 2. Conceptual soundness

Is the method appropriate for this decision and population? Are the assumptions
stated, and do they hold in the data? Would a simpler model do as well — and if
the answer is unknown, that is a finding.

## 3. Data and definition review

- Target reproduces `lending_hub.definitions.label` exactly (re-derived
  independently, not inspected).
- Point-in-time correctness independently tested — construct at least one row by
  hand and confirm no feature used information that post-dates the observation
  point in either timestamp.
- Reject/indeterminate treatment.
- Sample representativeness against the current book.

## 4. Outcomes analysis

Independently recomputed performance — recomputed, not copied from the model
card. Out-of-time and out-of-sample. Segment-level. Calibration.

## 5. Fairness and customer impact

Independent replication of the fairness testing, including the geographic
disparate-impact test where geospatial features are used (SRS §11.3).

## 6. Implementation testing

- Scores from the registered artifact match scores from the training pipeline on
  a shared sample (the parity harness).
- Training/serving skew report.
- Decision-log replay: re-score logged decisions from stored features and confirm
  identical outputs (Master §3.3).

## 7. Findings

| # | Severity | Finding | Owner | Due |
|---|---|---|---|---|

Severity: **blocking** (no promotion), **conditional** (promotion with a dated
remediation), **observation**.

## 8. Validator statement

Name, role, date, and an explicit statement of independence from development.

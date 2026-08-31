# Monitoring Plan — <model name> v<version>

> SRS §11.1 and §11.2. Every model ships with one; a model in production without a
> monitoring plan is unmonitored regardless of how many dashboards exist.

## 1. What is monitored

| Signal | Metric | Cadence | Threshold | Owner |
|---|---|---|---|---|
| Input drift | PSI per feature vs. development sample | | `[POLICY]` | |
| Score drift | PSI on the score distribution | | `[POLICY]` | |
| Calibration | Observed vs. expected default rate by band | | `[POLICY]` | |
| Discrimination | AUC / KS on matured cohorts | | `[POLICY]` | |
| Fairness | Metrics per SRS §4.3.3 by protected segment | | `[POLICY]` | |
| Feature freshness | Staleness per feature vs. its TTL | | | |
| Feature coverage | Null / missing rate per feature | | | |
| Latency | p99 feature fetch, p99 score | | 100 ms / 500 ms | |
| Decision-log integrity | Hash-chain verification | | must verify | |

Every threshold above is `[POLICY]`. A monitoring plan with invented thresholds
alerts on nothing meaningful and trains its audience to ignore it.

## 2. Outcome lag

State when performance is actually measurable. With a 12-month outcome window,
discrimination on a fresh cohort is not observable for a year — so the plan must
name the **leading** indicators watched meanwhile, and be explicit that they are
proxies.

## 3. Automatic actions

| Trigger | Action |
|---|---|
| PSI / calibration breach | Automatic rollback to the previous champion (SRS §11.1) |
| Feature source unavailable | Degrade to policy-rule decisioning, queue for re-score (SRS §12) |
| Decision-log chain fails verification | Halt automated decisioning; escalate immediately |

## 4. Human review

Cadence, forum, and who is accountable for acting — not merely for receiving the
report.

## 5. Retirement

The condition under which this model is retired rather than retrained. A model
with no retirement condition is retrained forever, including past the point where
it should have been replaced.

# Model Card — PD-velocity early-warning trigger (SRS §10)

> **Track P card.** This documents a detector exercised on public reference data
> (ADR-0004, ADR-0012, ADR-0014) to establish whether hazard deterioration
> precedes default and by how long. It is **not** a candidate for shadow or
> production on this bank's book, and none of its numbers is Phase 4 gate
> evidence. The card is completed in full anyway — a card written for the first
> time under gate pressure is a card nobody has tested.

## 1. Identification

| Field | Value |
|---|---|
| Name / version | `pd_velocity_ews` v0.1.0-trackP |
| Components | `ews.velocity` (trigger) over `portfolio.behavioural` (the fitted hazard) |
| Registry stage | None — not registered |
| Model tier | Tier 1 if it ever routes to a customer contact |
| Owner (accountable) | Credit DS squad lead |
| Independent validator | **Not assigned.** Master §3.1 requires a validator who is not the developer; none exists on Track P |

## 2. Reproducibility

| Field | Value |
|---|---|
| Code commit | The commit producing `reports/trackP_p4_fannie_mae.json` |
| Data | Fannie Mae Single-Family Loan Performance, 2007Q1 vintage, whole-loan sample at the run report's `panel.sample_rate` |
| Config | `n_trees=40`, `max_depth=4`, `learning_rate=0.1`, `min_months_on_book=3`, out-of-time split at 2012-12-31 — the same split Phase 3 uses, so the two runs are readable side by side |
| Definitions fingerprint | Recorded in the run report (Appendix A v1.1) |

Regenerate with `make trackp-p4`.

## 3. Purpose and scope

Flags accounts whose 12-month PD has deteriorated fastest over the last 30 days,
expressed as a percentile of the portfolio's velocity distribution on that
snapshot.

**Velocity, not level.** Phase 4 §4 Step 2 states the reason and it is the
design's whole basis: a thin-file borrower can sit permanently at "medium risk",
and re-alerting them monthly is both useless and the fastest route to alert
fatigue. An account at 8% hazard for two years is not news; one that moved from
1.1% to 2.4% in a month is, even though it remains the safer of the two.

**It must not be used for**: any population other than US conforming mortgages;
any automated action, since no action library exists (LH-502); any statement
about this bank's book; and — most importantly — any claim about *precision*,
which this model has never had measured.

## 4. Why a percentile rather than a threshold

Capacity. A fixed Δ-hazard threshold makes alert volume swing with the macro
cycle: in a downturn every account deteriorates at once and the queue explodes on
the week the collections desk can least absorb it. A percentile pins the volume
and lets the severity float, which is the correct way round when the binding
constraint is human hours.

The cost, stated rather than hidden: in a genuinely benign quarter the top band
still alerts, so some alerts land on accounts nobody would worry about. That is
the price of a bounded queue, and it makes measured precision look *worse* in
good times through no fault of the signal. Any precision figure this model ever
carries must be read against the regime it was measured in.

## 5. Known limitations

**The basis is unresolved (LH-511).** Phase 4 §4 Step 2 says "Δ(30-day) hazard"
without saying absolute or relative, and the two rank the book differently:
absolute concentrates alerts on already-risky accounts, quietly reintroducing
the level trigger the step exists to avoid; relative surfaces early deterioration
but is unstable at small PDs and undefined at zero. The runner uses absolute —
the reading needing no extra assumption — and records it on every ranking.

**The alert percentile is unratified (LH-501).** `trigger()` raises rather than
defaulting. The Track P run sweeps bands instead of choosing one, which is the
table a Collections Head needs anyway: it maps alert volume onto capture rate on
a real book.

**Small portfolios cannot supply a percentile.** Below 200 concurrent accounts
the "95th percentile" is the second-worst account — a fixed count dressed as a
rate, which stops behaving like a budget the moment the book grows. Enforced.

**Tie grouping is by exact float equality.** Two arithmetically-equivalent paths
to the same PD can yield slightly different alert counts. The direction is safe
(more granular, never fewer alerts than the budget), and it is pinned by test
rather than left to be discovered.

**The underlying hazard model carries its own limitations**, including LH-310
(behavioural monotonicity directions never ratified), which is why the Track P
run passes `MonotoneConstraints.for_experiment`.

## 6. Metrics

Capture rate at ≥ 60-day lead and the lead-time distribution, out of time, from
`reports/trackP_p4_fannie_mae.json`.

**Read the denominator before the ratio.** Capture is scored against *reachable*
defaults — those occurring after the first held-out snapshot. A default before
that point could not have been alerted on, so including it measures the
train/test split rather than the detector. On this vintage the distinction is
large: the 2007Q1 book front-loads its defaults into the 2008-11 credit event,
which sits entirely inside the training window, so most panel defaults are
unreachable. The run report carries `in_panel`, `reachable` and
`before_first_alertable_snapshot` separately. See finding P4-F11 — the first
version of this run reported a capture rate about a seventh of the real one for
exactly this reason. The distribution is reported rather than the
mean, because a 70-day average built from half at 130 days and half at 10 is a
different system from one where every alert lands at 70 — and only the second
delivers Phase 4 §1's "30-120 days ahead".

**No precision figure appears anywhere.** Precision is defined against
confirmed-relevant dispositions from a collections desk (LH-510). The available
substitute — scoring against whether the account later defaulted — penalises the
system for working: an alert that correctly found distress the bank then cured
counts as a false positive, so a better collections operation scores a worse EWS.

## 7. Fairness

Not assessed. The relevant risk here is that velocity-based alerting fires more
often on borrowers with volatile income, which correlates with informal
employment — so the alert stream could be demographically skewed even where the
underlying hazard model is not. Measuring it needs the alert dispositions of
LH-510.

## 8. Monitoring, promotion, rollback

None. `lending_hub.mlops.promotion` would refuse the transition on the
absent-validator basis alone.

## 9. Open tickets

**LH-501** (alert budget and trigger percentile) · **LH-502** (action library and
SLAs) · **LH-510** (dispositions) · **LH-511** (velocity basis) · **LH-310**
(behavioural monotonicity) · **LH-120** (bank data).

## 10. Sign-off

| Role | Name | Date |
|---|---|---|
| Developer | — | — |
| Independent validator | — | — |
| Model Risk | — | — |

**Unsigned.** No validator exists, and the model has never been evaluated on
this bank's portfolio.

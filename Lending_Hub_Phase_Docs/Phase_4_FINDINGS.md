# Phase 4 — implementation findings against the phase documents

Produced while building Phase 4. Master §1: "conflicts are raised as tickets,
never resolved silently by an implementer." Every finding below is **raised and
unapplied** — the SRS, the Master and the Phase 4 file are unchanged pending the
document owner's decision, as with the Phase 1, 2 and 3 findings.

**Phase 4 is the first phase that acts**, and that changes the character of its
findings. Phases 1-3 produced numbers that could be checked against outcomes
that had already happened. Phase 4 produces an alert routed to a human with an
SLA, and an offer made to a customer. Several findings below are about values
that only become necessary at the moment something is *done* rather than
computed.

## Status of each finding

| # | Finding | Kind | Ticket |
|---|---|---|---|
| P4-F1 | **"Spike in P(r_t = 0) = regime change" is wrong** — that quantity is identically the hazard and carries no evidence | **Correction (material)** | — |
| P4-F2 | The **bandit reward is named and not defined**, and take-up alone makes a mis-selling engine | Gap found by building | **LH-509 (new)** |
| P4-F3 | **"Δ(30-day) hazard as a percentile" does not say absolute or relative**, and they disagree about who is alerted | Under-specification | **LH-511 (new)** |
| P4-F4 | **The two-key rule names three conditions and quantifies none** | Under-specification | **LH-508 (new)** |
| P4-F5 | **BOCPD confidence depends on the preceding regime's stability**, so a global threshold has no constant false-negative rate | Gap found by measurement | **LH-512 (new)** |
| P4-F6 | **A per-officer alert cap is not derivable from a portfolio alert budget** | Gap found by building | **LH-507 (new)** |
| P4-F7 | **Signal precision is unmeasurable for every signal**, so §4 Step 1's ship gate blocks the entire catalogue | Structural | LH-510 |
| P4-F8 | **"Never hard-coded" is about time, and the phase file omits the freshness that follows from it** | Gap found by building | **LH-513 (new)** |
| P4-F9 | **Velocity confirmation without a change-point is not an alert**, which the two-key rule implies and does not say | Under-specification | LH-508 |
| P4-F10 | Scoring alert precision against the **default outcome measures the opposite of its name** | Method note | LH-510 |
| P4-F11 | **A correction to my own work**: the first Track P capture number scored unreachable defaults and measured the train/test split | Correction to my own work | — |

---

## A. Corrections — statements that mislead as written

### A1 (P4-F1). The change-point signal is not where the phase file says it is

**§4 WS-A Step 3:** *"Mechanics: posterior over run length r_t; **spike in
P(r_t = 0) = regime change** (salary loss, business interruption) — visible
months before a missed EMI."*

The mechanism is right, the reference is right, and the named quantity is wrong.
Under a **constant** hazard `h` — which is what Adams & MacKay use and what the
phase file implies — the normalised `P(r_t = 0)` is *identically* `h` at every
step, on every series, whatever the data does.

The algebra is two lines. Writing `w_r = posterior[r] + predictive[r]` in log
space:

* the change-point row is `logsumexp_r(w_r) + log(h)`;
* the growth rows sum to `logsumexp_r(w_r) + log(1 - h)`;
* so the evidence is `logsumexp_r(w_r) + log(h + (1-h))` = `logsumexp_r(w_r)`;
* and `P(r_t = 0) = exp(change - evidence) = h`. Exactly, always.

The change-point row sums the *same* predictive mass the growth rows do, so it
cannot carry information about whether a change occurred. A detector built
literally to this instruction reports a flat 0.004 forever and never fires.

**Where the evidence actually is: `P(r_t = 1)`**, one step later — "the current
regime began with the previous observation" — because that is the first point at
which the new regime has an observation to discriminate on. On a clean level
shift this reaches 0.71 at the shifted index while `P(r_t = 0)` reads 0.004.

`ews.bocpd.RunLengthPosterior.changepoint_probability` reports `P(r_t = 1)`;
`prior_reset_mass` keeps the phase file's quantity as a diagnostic, and a test
pins that it equals the hazard. **How this was caught matters**: the run-length
*mode* was resetting correctly at the change while the reported probability sat
pinned, which is the signature of reading the right posterior at the wrong lag.
A test that only asserted "a change is detected somewhere" would have passed.

**Recommended edit to the phase file:** replace "spike in P(r_t = 0)" with
"spike in P(r_t = 1), the run length having reset at the previous observation;
note that P(r_t = 0) is identically the hazard under a constant hazard function
and is not a detection statistic."

### A2. A boundary artefact the phase file does not mention

The first observation of any series necessarily begins a regime, so it scores
~1.0 on every series ever passed in. Left in, it puts a change-point on every
customer on the day their account is opened — a whole-book alert storm at
onboarding. `changepoints()` and `peak` exclude index 0 at the source rather
than leaving it to callers, because a caller who forgets is not making a subtle
error.

---

## B. Gaps found by building — values the phase file does not know it needs

### B1 (P4-F2). The bandit reward is named, not defined

**§5 WS-B Step 4:** *"Reward = take-up blended with a seasoning risk-adjusted
value proxy (delayed-reward correction)."*

Two components, and neither the blend weight nor the seasoning horizon. This is
the most consequential unspecified value in the phase, and it is not a tuning
knob — it is what the system optimises.

A bandit rewarded on take-up alone learns, correctly and quickly, to offer **the
largest loan the feasible set permits to the customers most likely to accept
it**. That is a mis-selling engine with excellent metrics: take-up rises, the
bandit's own reward curve looks like a success, and the losses arrive two years
later in a different report. The feasible set bounds it — exploration cannot
breach affordability, per §5 Step 4 — but the feasible set is a *floor*, not a
suitability judgement, and the difference between the largest permissible loan
and the right one is exactly where consumer harm lives.

The seasoning horizon is the other half and is nearly as sharp: too short and
the risk-adjustment sees no defaults, which reduces the blend to take-up again
with extra steps.

Registered as **LH-509**. `reco.bandit` will refuse to fit without it.

### B2 (P4-F3). "Δ(30-day) hazard as a percentile" — absolute or relative?

**§4 WS-A Step 2:** *"Δ(30-day) hazard, expressed as a percentile of the
portfolio distribution."*

Δ of what, exactly. Absolute change and relative change rank the book
differently, and the difference decides who is alerted:

* **Absolute** concentrates alerts on already-risky accounts — 8% → 10% is two
  points, while 0.4% → 1.2% is under one — which quietly reintroduces the
  *level* trigger the same step was written to avoid.
* **Relative** surfaces the early deterioration the workstream is named for, but
  is unstable at small PDs and undefined at zero.

`portfolio_percentiles()` takes the basis as an argument, defaults to absolute
(the reading that needs no extra assumption), and records the choice on the
result. Registered as **LH-511**.

### B3 (P4-F4). The two-key rule names three conditions and quantifies none

**§4 WS-A Step 3:** *"change-point alone → Amber; change-point + negative
direction + PD-velocity confirmation → Red. This keeps Red precision high."*

The design is good — requiring two independent mechanisms to agree is exactly
how you keep a high-severity tier's precision up. But as a decision procedure it
is incomplete in three places: what posterior probability counts as a
change-point (LH-512), how negative a direction must be to count, and what
PD-velocity percentile constitutes "confirmation" (LH-501). Registered as
**LH-508**.

### B4 (P4-F6). A per-officer cap is not a portfolio budget

**§4 WS-A Step 5** requires "per-officer daily alert cap" as a fatigue guardrail
without stating one, and it is not derivable from the alert budget in Step 2.
The budget is a portfolio-level *rate*; the cap is a per-person *workload*. A
book comfortably inside its budget can still bury the one officer covering a
district in drought, because alerts are spatially and temporally correlated
exactly when they matter. Registered as **LH-507**.

### B5 (P4-F8). "Never hard-coded" is a statement about time

**§5 WS-B Step 2:** *"Funds cost, opex, hurdle from ALM tables `[POLICY: ALCO]`
— **never hard-coded**."*

The emphasis is doing real work and it is worth spelling out why. ALM components
are not constants that happen to be unknown; they **move**. A cost of funds
tracks the policy rate, an opex allocation moves with cost-to-income, a hurdle is
reset by ALCO. So a pricing service reading a constant is not merely ungrounded —
it is *wrong within a quarter even if the constant was right on the day*.

Which is exactly why the omission matters: the phase file requires the components
come from tables and says nothing about **how current the table must be**. A
table that stopped updating produces plausible rates indefinitely from a funding
environment that no longer exists, and nothing in the output says so. That is the
failure that actually happens — "never hard-coded" is satisfied, and the service
is still wrong.

`price()` refuses a table older than an engineering default of 92 days and
refuses a future-dated one. The real tolerance is a treasury decision.
Registered as **LH-513**.

### B6 (P4-F9). Velocity without a change-point is not an alert

**§4 WS-A Step 3** defines Amber as "change-point alone" and Red as
"change-point + negative direction + PD-velocity confirmation". Read as a
complete decision procedure, that leaves a case unnamed: **PD velocity firing
with no cash-flow change-point.**

Implementing `tier()` forced the question. The answer that follows from the
rule's own logic is Tier.NONE — a PD move with no corresponding regime change in
cash flow is the ordinary month-to-month drift of a hazard model, and routing it
as Amber would flood the queue with model noise, which is the fatigue failure the
two-key rule exists to prevent. But the phase file does not say so, and the
opposite reading ("any signal fires → at least Amber") is equally available to an
implementer. Added to **LH-508**.

---

## C. Measured findings

### C1 (P4-F5). BOCPD is least confident where the customer is most stable

Measured while building. Two equally obvious level shifts in one series scored
**0.04** and **0.92**. The cause is not the size of the shift: it is that a
tight variance posterior, built from a long quiet run, makes the model reluctant
to concede a change, and it concedes a step late.

The operational consequence inverts the intuition. A single global declaration
threshold does **not** have a constant false-negative rate across the book — a
customer with a long, very stable salary history needs a *lower* threshold than
one whose inflows already wobble. The stable customers are the harder ones to
monitor, not the easier ones, and they are also the ones whose deterioration is
most informative.

Registered as **LH-512**, and pinned by test rather than tuned away, because
tuning it needs the disposition data of LH-510.

---

## D. Structural

### D1 (P4-F7). §4 Step 1's ship gate blocks the entire catalogue, correctly

**§4 WS-A Step 1:** *"a signal ships only with a backtested precision estimate
attached. Signals without measurable precision do not ship — this is the
anti-alert-fatigue contract."*

This is the best rule in the phase and it currently blocks every signal in the
catalogue, which is the right outcome rather than a failure of the
implementation. Appendix A defines alert precision against **confirmed-relevant
dispositions** — human judgements recorded by a collections desk. There is no
desk (LH-510), so no signal has a precision, so none ships.

`SignalDefinition.shippable` returns `(False, reason)` for all eight v1 signals,
each naming its ticket. The alternative — shipping with a plausible precision —
is precisely the failure the rule was written to prevent, and it would be
invisible: an invented 0.31 looks exactly like a measured one.

### C2 (P4-F10). The available precision proxy measures the opposite of its name

Not a gap in the phase file — §4 Step 6 correctly asks for precision per tier,
and Appendix A correctly defines it against confirmed-relevant dispositions. The
finding is about what happens when those dispositions do not exist, because the
substitution is obvious and available: score each alert against whether the
account later defaulted.

**That metric is inversely related to the thing it is named for.** An alert that
correctly identified distress, which the collections team then successfully
cured, becomes a false positive. So the better the collections operation, the
worse its EWS appears — and a bank that improved its cure rate would see its
early-warning precision fall and might well "fix" the detector.

It is the same class of error as Phase 3's in-sample comparison (P3-F14): a
number that looks like the right metric and measures something else.
`ews.backtest.tier_precision()` requires dispositions and refuses an empty set
with this reason attached, and the Track P run reports precision as **not
measurable** rather than substituting.

### C3 (P4-F11). A correction to my own work: capture measured the split, not the detector

The first Track P run reported **capture 0.111 at p90** against a 0.55 target,
with `never_alerted: 728 of 827`. Read straight, that says the detector missed
88% of defaulters and the criterion fails badly.

It was wrong, and the shape of the error is worth recording because it is the
same one Phase 3 caught in itself (P3-F14) pointing the other way.

The detector alerts only on **held-out** snapshots — everything after the
out-of-time split at 2012-12-31. But the denominator was every default in the
panel. A default that happened before the first held-out snapshot **could not
have been alerted on by construction**, so including it does not measure a worse
detector; it measures the split.

On this panel that is not a small correction. Measured directly: **151 of 179
defaults in a 0.5% sample (84%) occur before the split**, because the Fannie Mae
2007Q1 vintage front-loads its defaults into the 2008-11 credit event, which
sits entirely inside the training window. So roughly six sevenths of the
denominator was unreachable, and the reported capture was about a seventh of the
detector's real rate.

`ews.experiment` now scores against **reachable** defaults only — those after
the first alertable snapshot — and the run report carries `in_panel`,
`reachable` and `before_first_alertable_snapshot` so the distinction is visible
rather than buried in a single ratio.

**Why this belongs in the findings rather than a silent fix.** Phase 3's finding
was an in-sample comparison that flattered a model; this is an out-of-sample
denominator that maligned one. Both are the same underlying failure — a metric
whose population was chosen by the mechanics of the experiment rather than by
the question — and both are invisible in the output, because 0.111 looks exactly
like a real capture rate. The only thing that surfaced it was asking why the
number was so far from plausible and checking the denominator against the split
before publishing it.

---

## E. What the phase file gets right

* **"Velocity, not level, is the trigger."** §4 Step 2 states the mechanism
  *and* the reason — "a thin-file borrower can be permanently medium risk". An
  EWS built on level re-alerts the same names monthly and teaches officers to
  stop reading the queue. Rare to see the failure mode named in the
  specification.
* **"A signal ships only with a backtested precision estimate."** The
  anti-alert-fatigue contract, and the only defence against a catalogue that
  grows until nothing in it is believed.
* **Percentile rather than threshold**, which pins alert *volume* against the
  macro cycle. A fixed Δ threshold explodes the queue in a downturn — on the
  week the desk can least absorb it.
* **"Exploration can never breach affordability or policy."** §5 Step 4 puts the
  bandit inside the feasible set rather than beside it, which is the difference
  between a learning system and an uncontrolled one.
* **Arms as offer *templates***, not free parameters. A small, auditable arm
  space is what makes a bandit explainable to a regulator at all.
* **Two-key rule for Red.** Requiring two independent mechanisms to agree is the
  correct way to protect a high-severity tier's precision, even though the
  thresholds are missing (B3).

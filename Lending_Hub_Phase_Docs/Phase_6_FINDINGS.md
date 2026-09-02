# Phase 6 — implementation findings against the phase documents

Produced while building Phase 6. Master §1: "conflicts are raised as tickets,
never resolved silently by an implementer." Every finding below is **raised and
unapplied** — the SRS, the Master and the Phase 6 file are unchanged pending the
document owner's decision, as with the Phase 1, 2, 3, 4, 5 and 7 findings.

**Phase 6's findings have a different shape because Phase 6 is not a
deliverable.** Its card says so, and §4's exit criterion is *standing* rather
than one-time. Most findings below are therefore not "this value is missing" but
"this rule is stated and the thing that makes it act is not" — and the sharpest
one is about a quantity that cannot be computed at all, however much data
arrives.

## Status of each finding

| # | Finding | Kind | Ticket |
|---|---|---|---|
| P6-F1 | **Uplift is unidentifiable, not unmeasured**, and the difference decides whether waiting helps | **Method note (material)** | LH-811 |
| P6-F2 | **"Measured lift" is not "sufficient lift"**, and no workstream quantifies its gate | Under-specification | **LH-801 (new)** |
| P6-F3 | **"Offline lift alone never promotes" is a rule about admissible evidence**, and is easy to implement backwards | Method note | — |
| P6-F4 | **WS-6.1's community scorer names two inputs and only one is computable** | Gap found by building | **LH-810 (new)** |
| P6-F5 | **"Only positive-DR-estimate policies proceed" is a sign test on a point estimate** | Under-specification | **LH-804 (new)** |
| P6-F6 | **The WS-6.7 cadence table gives intervals and no tolerances** | Gap found by building | **LH-807 (new)** |
| P6-F7 | **A challenger's promotion gate is comparative, and P6 has no champion to compare against** | Structural | LH-801 |

---

## A. The method note that governs the phase

### A1 (P6-F1). Unidentifiable is a third gate state, and it inverts the usual advice

**§2 WS-6.4:** *"Randomized action holdouts are **standing policy** (without
them, uplift is unidentifiable — an AI assistant must never estimate uplift from
purely observational action logs and present it as causal)."*

The phase file is right, and the parenthesis deserves to be a rule in the Master
rather than an aside in one workstream, because it changes what "blocked" means.

Phase 3 established two gate states. **Not measured**: the job has not run.
**Not measurable**: no data reachable from here produces the number. Both are
statements about *data*, and both are fixed by data arriving.

WS-6.4 is neither. A collections desk that called every borrower an officer
judged likely to cure produces a log in which treatment and cure are confounded
by that judgement. The naive difference on that log is not a noisy estimate of
τ — it is a **different quantity**, and it is biased in the direction that
flatters the action, because the officer selected the cases most likely to cure
anyway.

The consequence is the part that matters operationally, and it inverts the
instinct every other blocked ticket in this repository trains:

> **More data makes a confounded estimate tighter, not truer.**

A confidence interval around a biased quantity narrows around the wrong number.
So the usual remedy for a weak number — wait, accumulate, re-run — actively
makes this one *more* dangerous, by converting a visible uncertainty into an
invisible bias. LH-811 is the only row in any register with that property.

Implemented as a structural refusal rather than a warning:
`uplift.estimate_uplift()` and `uplift.qini_curve()` raise on a log whose
assignment is not `RANDOMIZED`, and `RANDOMIZED` requires a named asserter
because no code can verify randomization from a log alone.

**Recommended Master edit:** add *unidentifiable* alongside *not measured* and
*not measurable* in the gate-state vocabulary, with WS-6.4 as the worked example.

---

## B. Gaps found by building

### B1 (P6-F2). "Measured" is not "sufficient", and nothing says how much

**§4:** *"Measured lift on out-of-time data · model card · independent
validation · rollback plan · online A/B where feasible."*

Every workstream's gate is comparative and none is quantified:

| Workstream | Gate as written |
|---|---|
| WS-6.1 | "+recall at the fixed alert budget vs. the P1 stack" |
| WS-6.2 | "precision ≥ agreed floor `[POLICY: Fraud Head]`" |
| WS-6.3 | "C-index / capture-rate lift **and** an explainability review" |
| WS-6.4 | "Qini coefficient + online cure-rate lift" |
| WS-6.5 | "only positive-DR-estimate policies proceed to canary" |

WS-6.2 at least names its floor as a policy value. The rest read as thresholds
and are not: "+recall" is a sign, and a challenger beating a champion by 0.0001
recall satisfies it literally.

`challenger.assess()` therefore applies the sign test and no minimum, and the
absence is deliberate — a default here would silently become the bar every
challenger in the programme was judged against, chosen by whoever typed it.
LH-801, with LH-802 separately for Qini because a Qini coefficient is not on the
same scale as a recall difference.

### B2 (P6-F4). The community scorer names two inputs; one of them is a disposition

**§2 WS-6.1 step 1:** *"dense clusters scored by **fraud-label density and
shared-attribute entropy**; cheap and explainable — deploy first."*

*Deploy first* is right and is why this is the one Phase 6 component running on
real data: Louvain is unsupervised, so it needs the P1 entity graph and not the
dispositions. But the *scorer* the step describes needs both inputs, and only
one survives:

* **shared-attribute entropy** — computable from the graph's edge types;
* **fraud-label density** — needs a fraud label per node, which is a fraud-desk
  disposition. WS-6.1's own feed line says so: *"P1 entity graph + ≥ 18 months
  of fraud-desk dispositions"*.

So `CommunityScore.fraud_label_density` raises rather than returning a
structural proxy. The temptation to substitute is real, because dense
single-attribute clusters *are* suspicious and an entropy-only score would rank
communities plausibly — and it would be presented as WS-6.1's scorer while
measuring something else. LH-810 registers the feed, blocked on LH-206.

### B3 (P6-F5). A sign test on a point estimate is not a canary decision

**§2 WS-6.5:** *"only positive-DR-estimate policies proceed to canary."*

Implementable exactly as written, and insufficient as written. A DR estimate
carries a standard error; a point estimate marginally above zero whose interval
spans it is not evidence that the policy is better, and "positive" does not
distinguish the two.

The phase file is unusually careful elsewhere about evidence quality — §4's
whole subject is what evidence admits a promotion — which is what makes this
one read as an omission rather than a simplification.
`DoublyRobustEstimate.positive` implements the stated sign test and
`confidence_interval()` is available beside it; no threshold is applied. LH-804.

Related and not raised as a separate finding: the module refuses a log whose
**effective sample size** is below 30, which is not in the phase file at all. A
log of 10,000 rows whose importance weights concentrate on three of them has an
ESS in single digits, and reporting *n* = 10,000 beside that estimate is the
misleading part.

### B4 (P6-F6). Intervals without tolerances cannot detect lateness

**§2 WS-6.7** is a table of five cadences, and it is the phase's steady-state
rhythm. It gives each activity an interval and no grace period — which is
enough to schedule and not enough to *alert*, because "overdue" needs both.

The two are different questions with different consequences: a weekly PSI check
one day late is noise; a quarterly reject-inference cycle one day late may
already have missed the retrain it feeds. So `cadence.overdue()` takes `grace`
as a **required argument with no default**, and LH-807 registers the tolerance
set.

The module also separates two states the table cannot express — an activity that
has **never run** (usually never set up) from one that ran and **stopped**, and
an activity whose **owning phase has not shipped** from one that is late. The
last is Phase 3's not-measured / not-measurable distinction appearing in a
monitoring dashboard, where collapsing it makes a cadence report a wall of red
that nobody reads.

---

## C. Method and structural notes

### C1 (P6-F3). The A/B sentence is a rule about evidence, and inverts easily

**§4:** *"**Offline lift alone never promotes a model that could have been A/B
tested.**"*

Worth stating separately because the natural implementation is the wrong one. It
is tempting to read this as "an A/B is required" and gate on `ab_test_ran`. It
does not say that. It says offline lift is **inadmissible as the sole evidence**
where an A/B was *feasible* and was not run — so the question the gate asks is
"was one available to you?", not "did you run one?".

That distinction is what makes the rule enforceable at all. A model that
genuinely cannot be A/B tested must still be promotable, or the rule blocks the
safest models along with the lazy evaluations.

`AbTestFeasibility` therefore has three states rather than two, and `INFEASIBLE`
requires a stated reason recorded against a named submitter — because "we could
not A/B test this" with nothing attached is precisely how a standing rule
becomes a checkbox.

### C2 (P6-F7). Every gate is comparative, and there is no champion

Not a defect in the phase file — a structural consequence of where this
repository is, recorded so the gate pack is read correctly.

Each promotion gate in §2 is a *difference*: the challenger against the champion
this bank runs. No model in this repository has ever been promoted, because
every promotion path terminates at an unratified `[POLICY]` value. So every
comparative gate has no left-hand side.

This is why ADR-0016 rejects fitting the challengers on Track P and reporting
the result. "DeepSurv beat the P3 GBM on Fannie Mae" would be a true sentence
answering a question nobody asked — and it would look exactly like the gate
evidence while not being it, which is the failure mode ADR-0014 named for the
simulated collections desk and ADR-0015 for the fabricated corpus.

`challenger.compare()` is the guard that makes the requirement explicit: same
metric, same population, same window, same operating point, or no comparison at
all. Each of those four mismatches produces a *positive* lift when violated,
which is why they are refusals rather than warnings.

# Model Card — LinUCB offer bandit (SRS §6)

> **This card documents a bandit that has never learned anything**, and that is
> the correct state rather than an incomplete one. Its reward is undefined
> (LH-509) and every input it would need is unavailable (LH-510), so `update()`
> raises. Master §2 rule 5 requires a card regardless, and the card is where the
> reason belongs.

## 1. Identification

| Field | Value |
|---|---|
| Name / version | `linucb_offer_bandit` v0.1.0 — **never fitted** |
| Reference | Li, Chu, Langford & Schapire, WWW 2010 ([arXiv:1003.0146](https://arxiv.org/abs/1003.0146)) |
| Registry stage | None |
| Model tier | Tier 1 — it selects what is offered to a customer |
| Owner (accountable) | Credit DS squad lead |
| Independent validator | **Not assigned** (Master §3.1) |

## 2. Purpose and scope

Selects an offer *template* for a customer from the arms that map to a feasible
offer, using LinUCB's ``x^T θ̂_a + α √(x^T A_a^{-1} x)``.

**Arms are templates, not free parameters.** Phase 4 §5 Step 4 specifies this
and it is what makes the model explainable: "the bandit chose template
`top_up_12m_standard`" is reviewable by a regulator; "the bandit chose ₹347,912
at 14.7% over 41 months" is not, and no volume of logging makes it so.

**It must not be used for**: any decision at all, since it has never been fitted;
selecting outside the feasible set, which the code prevents; or learning from
take-up alone, which the code refuses — see §4.

## 3. The safety property that does hold

**Propensity logging is complete by construction.** `BanditDecision` cannot be
constructed without a propensity in (0, 1], and `select()` returns a decision
rather than an arm. There is no code path producing an action without the
probability it was taken with.

This matters because Phase 4 §8 makes 100% completeness an exit criterion, and
P6's off-policy evaluation depends on it: a logged decision with no propensity
cannot be reweighted, so it does not merely drop out of the analysis — it biases
whatever remains toward the decisions that happened to be logged. It is the one
Phase 4 criterion this repository fully satisfies, because it is a property of a
type rather than a measurement.

The greedy propensity is 1.0 and is logged honestly. LinUCB is deterministic
given its state; P6's importance weighting handles a deterministic logging
policy, but not a determinism smoothed into a plausible-looking distribution.

**Exploration is inside the feasible set, not beside it.** Arms are filtered to
feasible offers *before* scoring. A learner that chose first and checked
afterwards would need a fallback, and every fallback is a hole in the propensity:
the logged probability would be for an action other than the one taken. An empty
intersection raises rather than relaxing the set.

## 4. Why it does not learn, and why that is deliberate

Phase 4 §5 Step 4 defines the reward as *"take-up blended with a seasoning
risk-adjusted value proxy (delayed-reward correction)"* — naming two components
and specifying neither the blend weight nor the seasoning horizon.

This is the most consequential unspecified value in the phase, and it is not a
tuning knob: it is what the system optimises. **A bandit rewarded on take-up
alone learns, correctly and quickly, to offer the largest loan the feasible set
permits to the customers most likeliest to accept it.** That is a mis-selling
engine with excellent metrics — take-up rises, the reward curve looks like a
success, and the losses arrive two years later in a different report.

The feasible set bounds it, per §5 Step 4, but a feasible set is a **floor**
rather than a suitability judgement. The gap between the largest permissible loan
and the right one is exactly where consumer harm lives.

The seasoning horizon is nearly as sharp: too short and the risk-adjustment
observes no defaults, which reduces the blend to take-up again with extra steps.

`Reward.blended()` and `LinUCB.update()` both raise without a ratified weight
(**LH-509**). `FeasibleSet.largest_feasible` is exposed under a deliberately
obvious name so that this convergence is visible in review rather than emergent.

## 5. Known limitations

**Never fitted, so no metrics of any kind.** No regret curve, no take-up lift,
no calibration. Phase 4 §8's A/B criterion needs live traffic through two
policies and a three-month vintage-risk window.

**The exploration cell size is unratified (LH-503).** §5 Step 4 illustrates 1-2%,
which is an illustration. It decides how many customers receive a deliberately
sub-optimal offer, making it a customer-impact decision rather than a parameter.

**`alpha` has a default and the cell size does not.** That asymmetry is
intentional: `alpha` is a statistical parameter with a principled value from the
paper's regret bound; the cell size is a decision about customers.

**The take-up model has selection bias** — Phase 4 §5 Step 3 names it: the model
only ever sees offers previously made. The mitigation is the exploration cell,
which is unratified, so the bias is currently documented rather than corrected.

## 6. Fairness

Not assessed — nothing has been decided. The structural risk worth recording:
a bandit optimising take-up will learn demographic proxies if they predict
acceptance, and the feasible set does not prevent this because it constrains
affordability rather than which affordable offer is chosen. Any live deployment
needs the disparity monitoring LH-205 governs, applied to *offers made* rather
than to decisions.

## 7. Open tickets

**LH-509** (reward blend and horizon) · **LH-503** (exploration cell) ·
**LH-510** (offer logs and take-up outcomes) · **LH-504** (feasibility caps) ·
**LH-505** (pricing components) · **LH-205** (disparity thresholds).

## 8. Sign-off

| Role | Name | Date |
|---|---|---|
| Developer | — | — |
| Independent validator | — | — |
| Model Risk | — | — |

**Unsigned.** The model has never been fitted, and its objective function has
never been defined.

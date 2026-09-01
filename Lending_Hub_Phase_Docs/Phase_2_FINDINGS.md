# Phase 2 — implementation findings against the phase documents

Produced while building Phase 2. Master §1: "conflicts are raised as tickets,
never resolved silently by an implementer." Every finding below is **raised and
unapplied** — the SRS, the Master and the Phase 2 file are unchanged pending the
document owner's decision, exactly as the Phase 1 and Phase 3 findings were.

**Phase 2 is the best-written phase file in the set, and the least buildable.**
Those are unrelated facts and both are worth stating. Its instructions are
unusually well judged — "never geocode a village centroid and store it as a
plot", "build the auditable fallback first", "Presto ships only if ≥ +5 macro-F1
over the baseline (complexity must be earned)", "a failed test triggers feature
redesign — never threshold relaxation" — and each of those is a sentence written
by someone who has watched the alternative happen. But its entry criteria are
categorically unsatisfiable here (ADR-0013), so unlike Phase 1 and Phase 3 it has
**no Track P**: no imagery, no agri book, no ratified calendar, and none of the
three approximable.

That changes what this document can be. The Phase 3 findings were largely
evidence — 47% relative overstatement here, a sign flip there, measured on a real
panel. Phase 2's are structural: things that become a decision somebody makes
silently, found by writing code against the specification until it had to produce
a value.

## Status of each finding

| # | Finding | Kind | Ticket |
|---|---|---|---|
| P2-F1 | **Six named inputs are not a formula** — LandQualityIndex has no combining function, and it is the feature exit criterion (a) tests | Gap found by building | **LH-411 (new)** |
| P2-F2 | **"Season-linked default" is not a defined population**, and the attribution rule can pass or fail criterion (c) with no change to the flag | Gap found by building | **LH-412 (new)** |
| P2-F3 | The **GPS-walk label set is treated as an input and scheduled by nobody** | Scheduling gap | **LH-407 (new)** |
| P2-F4 | **"Price_P50" names a statistic without a window**, and the window moves it more than the model does | Under-specification | **LH-408 (new)** |
| P2-F5 | Both models are told to **abstain, and neither is told where the abstention goes** | Gap found by building | **LH-409 (new)** |
| P2-F6 | A **median IoU gate with no sample size** reads identically at n=12 and n=1,200 | Under-specification | — |
| P2-F7 | The **IoU gate is measured on IoU and enforced through confidence**, and nothing requires the two to be related | Correction | — |
| P2-F8 | A passing median IoU **fails hardest on the smallest borrowers**, and §7 asks only for the median | Correction | — |
| P2-F9 | **"Snap to cadastral where available" has no threshold**, and parcels tile — so there is always a nearest one | Under-specification | LH-407 |
| P2-F10 | The **fallback cannot ship P50 alone**: StressedIncome is *defined* on P25, so a missing quantile deletes a feature rather than degrading it | Specification, found by building | — |
| P2-F11 | **Point-in-time for imagery is a publication-date problem**, not an acquisition-date one, and §4 says "point-in-time imagery only" without saying which | Correction | — |
| P2-F12 | The **agronomic signal and the geographic disparity are the same measurement** — SRS §11.3's analysis cannot separate them, and should not pretend to | Structural | LH-410 |
| P2-F13 | **The whole phase is not measurable**, and that is a different gate state from "not measured" for all six criteria at once | Structural | LH-406, LH-102 |

---

## A. Gaps found by building — values the phase file does not know it needs

### A1 (P2-F1). Six named inputs are not a formula

**§4 WS-2.3:** *"LandQualityIndex = f(soil organic carbon, slope, irrigation
proxy, 5-yr mean peak-NDVI percentile vs agro-zone, yield volatility, drought
frequency)"*.

The `f` is never given. Not the weights, not the direction of each term, not the
normalisation, not the range. Six named inputs read as a specification right up
until code has to return a number — and then it turns out that every choice
about how they combine is a choice about what "land quality" means at this bank.

What makes it worse than an ordinary missing parameter: **LandQualityIndex is
exactly what exit criterion (a) tests.** "LQI quartiles order historical agri NPA
rates monotonically" is not a test of anything if whoever runs the backtest also
chose the weights — a monotone ordering can be produced by fitting the weights to
the outcome, and nothing in the criterion forbids it.

`land_quality_index()` requires a `LandQualityFormula` carrying a policy
reference and raises without one. `land_quality_components()` returns the six
normalised inputs, which are all `[DATA]` and individually useful — drought
frequency and irrigation proxy tell an underwriter something with no weighting at
all. Registered as **LH-411**.

### A2 (P2-F2). "Season-linked default" is not a defined population

**§4 WS-2.4(c):** *"the non-sowing flag would have fired on ≥ 60% of
season-linked defaults with ≥ 45 days lead"*.

Appendix A defines default. Nothing defines the season linkage. A farmer holding
a Kharif loan and a Rabi loan who defaults in March has defaulted on one of them,
and the attribution changes both halves of the criterion:

* the **numerator and denominator**, since a default attributed to a season the
  flag never watched is an automatic miss; and
* **every lead time in it**, because attributing a default to the *later* season
  gives it a short lead by construction.

So the linkage rule can make the 45-day criterion pass or fail without any change
to the flag being tested. `non_sowing_backtest()` requires the linkage as an
input rather than inferring one. Registered as **LH-412**.

### A3 (P2-F3). The GPS-walk label set is scheduled by nobody

**§4 WS-2.2 Model A** fine-tunes on "officer GPS-walk labels" and gates on
"held-out GPS-walk polygons". **§8** forbids storing "any plot polygon not
observed or walked", which makes the walk set the only admissible label source
for the model *and* the only admissible ground truth for its gate.

No workstream in the programme plan produces it. §4 WS-2.1 Step 2 mentions the
officer mobile app as "the ground-truth channel", which is an interface, not a
collection programme: someone has to walk a stratified sample of plots across the
operating districts, and that is field work with a season's lead time and a
budget.

This is the same shape as Phase 1's LH-209 (the labelled duplicate-pair set an ER
threshold is tuned on): **a scheduling gap, not a committee decision**. It is
registered as **LH-407** because it blocks Model A entirely, and because a phase
plan that treats a season of field work as an input will discover it in month
four.

### A4 (P2-F4). "Price_P50" names a statistic without a window

**§4 WS-2.3:** *"mandi price distributions from Agmarknet feeds `[DATA]`"*, feeding
`Price_P50` and `Price_P25`.

Agmarknet is a real feed and naming it settles the source. It does not settle
what the distribution is *over*. Price at harvest? Across the marketing season?
A forward? Over how many years of history, and at which mandi — the nearest, or
the one the farmer actually sells at?

For a crop whose price swings 30% between harvest and the lean season, that
choice moves `ExpectedIncome` further than any modelling decision in this phase.
Registered as **LH-408**.

### A5 (P2-F5). Both models abstain, and neither abstention has a destination

Two of the phase file's better instructions are abstention rules:

* Model A: below the IoU gate, *"plots require a manual walk"*;
* Model B: *"predictions < 0.6 confidence surface as 'unsure', never forced"*.

Both are right. Neither says who acts, within what SLA, or what happens to the
application in the meantime. An abstention with no destination is not a safe
default — it is an application sitting in a queue nobody owns, and the pressure
that resolves it will be a deadline rather than a walk.

Registered as **LH-409**. It matters more here than it would elsewhere because
abstention rates in this phase are driven by *cloud*, so they arrive seasonally
and in bulk: a monsoon fortnight can push a district's plots into "unsure" all at
once.

---

## B. Corrections — statements that mislead as written

### B1 (P2-F6, P2-F7, P2-F8). Three things about one gate

**§4 WS-2.2 Model A:** *"Gate: median IoU vs. held-out GPS-walk polygons ≥ 0.75
before auto-delineations are shown; below it, plots require a manual walk."*

Three separate problems, all in one sentence.

**No sample size (P2-F6).** "Median IoU ≥ 0.75" reads identically whether it came
from 12 held-out plots or 1,200. At n=12 the confidence interval on a median IoU
spans the gate in both directions, so the gate is decided by which plots happened
to be walked. `MIN_GATE_SAMPLE = 100` is imposed here and reported in
`GateResult.why_not`; the number is an engineering floor and the *need* for one
is the finding.

**The gate is measured on one quantity and enforced through another (P2-F7).**
IoU needs a walked polygon. At inference there is no walked polygon — that is the
entire reason the model exists. So the gate is established on held-out walked
plots and then applied per-plot through the model's **confidence score**, which
is a different quantity. That substitution is only valid while confidence is
calibrated against IoU, and nothing in the phase file requires it. An
uncalibrated confidence makes the per-plot rule a filter on an arbitrary number
that happens to lie in [0, 1]. Recorded as a validation obligation on the Model A
card.

**A median hides the borrowers it fails (P2-F8).** A median of 0.80 is compatible
with a quarter of plots below 0.5, and those plots are not random: delineation
fails on small, irregular and intercropped fields. So a gate that passes on the
median systematically routes the *smallest* borrowers to a manual walk — which is
the correct engineering outcome and an access-to-credit problem at the same time,
since a manual walk is slower and rationed. `GateResult` carries p25, p10 and the
below-gate share for this reason. §7 asks only for the median.

### B2 (P2-F9). "Snap to cadastral where available" has no threshold, and always finds something

**§4 WS-2.2 Model A:** *"snap to digitized cadastral layers where available"*.

Cadastral parcels **tile the landscape**. There is always a nearest parcel, so
"snap to the best match" with no floor always snaps — and when the delineation was
poor, it snaps the plot onto the neighbour's field. The failure is silent and it
is worse than no snapping at all, because a cadastral parcel boundary *looks*
more authoritative than a model output: the precision goes up while the accuracy
goes down.

`snap_to_cadastral()` takes `min_iou` with no default and returns the delineation
unchanged when nothing clears it. The threshold itself belongs with LH-407.

### B3 (P2-F11). Point-in-time for imagery is about publication, not acquisition

**§4 WS-2.4:** *"computing everything as-of historical decision dates
(point-in-time imagery only)"*.

"Point-in-time imagery" is ambiguous in the one way that matters. Imagery has two
timestamps — when the scene was acquired and when the product was published — and
they differ by hours to days for Sentinel-2 L2A and by **weeks to months** for
ERA5 reanalysis, which is revised after first publication.

A backtest that filters on acquisition date is using scenes that existed
physically but were not available to anyone at the decision point. The result
looks *better* than the live system could ever achieve, which is precisely what
an unnoticed leak looks like.

Phase 0 caught half of this already — `config/sources/weather.yaml` records the
reanalysis vintage requirement, and `satellite.yaml` notes that publication lags
acquisition. The phase file's own §4 does not carry it through to WS-2.4.
`assert_point_in_time()` checks publication dates and `IngestRecord` refuses a
reanalysis record with no vintage.

---

## C. Specification observations — right as written, worth recording

### C1 (P2-F10). The fallback cannot ship P50 alone

**§4 WS-2.2 Model C** is emphatic: *"Output contract: P50 / P25 / P10 yield (the
GP uncertainty is part of the contract, not optional)."* The emphasis is
justified and worth spelling out, because the natural implementation defeats it.

Build the fallback first, as instructed, and you have an OLS fit with a point
prediction and no quantiles. The obvious move is to ship P50 and mark P25/P10
pending the GP. But **`StressedIncome` is defined on `Yield_P25`** — so a missing
P25 does not degrade the stressed-income feature, it deletes it, and the deletion
propagates to every affordability cap built on it.

`YieldModel` therefore produces its interval from the fit's own residual
distribution, and every prediction carries `interval_basis` saying it is a
homoscedastic residual band and **not** a GP posterior. A wrong-but-stated
interval is auditable; a missing one silently becomes a point estimate somewhere
downstream.

### C2. The joint stress in StressedIncome is deliberate and unusual

**§4 WS-2.3** moves *both* yield and price to their P25 in the same formula. That
implicitly assumes yield and price shortfalls coincide.

For a single farmer facing a local crop failure, that is right — their crop failed
and the market price is set elsewhere. Across a district it is conservative in an
unusual direction, because a *regional* yield failure typically raises local
prices, so the two stresses partly offset. The formula is `[SPEC]` and is
implemented exactly as written; the observation is recorded because a reviewer
comparing `StressedIncome` against a district-level stress test will find them
inconsistent and should know why.

---

## D. Structural — the phase's position, not its specification

### D1 (P2-F12). The agronomic signal and the geographic disparity are one number

**§6 deliverable 9 / SRS §11.3** require a geographic disparate-impact analysis of
the agri features. Phase 1's fairness analysis has protected attributes that are
*given*. This one does not, and there is a deeper problem beneath the missing
comparison units (LH-410).

**The agri features are derived from land.** A district on thin soil in a
rain-shadow genuinely has lower expected yields, so its `LandQualityIndex` is
genuinely lower, so its approval rate will be lower — and that is simultaneously
a correct risk assessment and a geographic disparity of exactly the kind SRS
§11.3 exists to surface. No statistical technique separates them, because they
are not two effects; they are one measurement viewed through two questions.

`agri.disparate` therefore reports the disparity **and the land-quality gap
beside it**, so a reviewer can see how much of one tracks the other, and
`GeographicReport.verdict()` raises. Deciding whether agronomically-justified
geographic disparity is acceptable lending is a redlining question with a policy
answer, and it is the question the memo exists to answer rather than one the
memo's code should pre-empt.

### D2 (P2-F13). Every criterion is not measurable, and that is itself the finding

Phase 3 introduced the distinction between **not measured** (nothing has been
run) and **not measurable** (no data reachable from here can produce the number),
and reported two of six criteria in the second column.

Phase 2 reports **six of six**. The aggregate says something the individual rows
do not: *this phase's gate is not blocked on effort anywhere.* There is no task
in this repository whose completion moves any of the six, and three of them are
blocked on the single thing Phase 2 §3 lists as its own entry criterion —
LH-406, the historical agri portfolio.

The right conclusion is not that Phase 2 was a poor investment. Every
deterministic computation in the phase is built and tested, the boundary of what
is groundable is now explicit and reviewable, and five values nobody had noticed
were missing are registered with owners. The right conclusion is narrower:
**Phase 2 should not be taken to a Gate Review until LH-406 and LH-102 land**, and
saying so once at the top of the pack is more useful than discovering it six rows
down.

---

## E. What the phase file gets right

Worth recording, because a findings document that lists only problems misleads
about the source.

* **"Never geocode a village centroid and store it as a plot."** The single best
  sentence in the phase set. It names a specific failure, explains the correct
  alternative (village-level features, flagged as such), and is enforceable — it
  is now a type in `agri.registry` rather than a convention. A geocoded centroid
  is not imprecise; it acquires an income, an NDVI series and a quality index for
  whatever sits at the village centre, all well-formed and all about the wrong
  land.
* **"Build the auditable fallback first."** Correct ordering, correct reason, and
  it survived contact: the fallback is the only part of Model C that exists, and
  it is the part that would still be trustworthy during an imagery outage.
* **"Presto ships only if ≥ +5 macro-F1 points over the baseline (complexity must
  be earned)."** A quantified, pre-registered ship/no-ship rule stated *before*
  the challenger is built. Rare, and the reason Phase 2 has a defensible
  deployment decision for a model it has not built.
* **"A failed test triggers feature redesign — never threshold relaxation."**
  Aimed exactly at the moment someone is looking at a near miss. It is why
  `run_backtest()` accepts no threshold arguments at all.
* **Fallow as a first-class label.** A small decision with large consequences —
  "not sown" and "could not tell" are opposite claims, and the entire non-sowing
  early-warning flag rests on keeping them apart.

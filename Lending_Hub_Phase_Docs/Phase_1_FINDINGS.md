# Phase 1 — implementation findings against the phase documents

Produced while building Phase 1. Master §1: "conflicts are raised as tickets,
never resolved silently by an implementer." Every finding below was first raised
and left unapplied. **The document owner has since accepted them and they are now
applied** — to SRS **v1.2**, Master **v1.2** and Phase 1 **v1.1** — which is the
route Master §1 reserves the change for.

The narrative is kept in the tense it was written in, because *why* each finding
exists is the part that survives longer than the edit. One of them (P1-F8) was
wrong on its own headline number and is corrected in place; the correction is
worth more than the original.

**The documents held up well.** The Phase 1 document is good. Its workstream decomposition is right, its
do-not-invent list is unusually complete, and the fraud section's insistence that
the anomaly layer feeds the supervised layer rather than alerting separately is
the kind of detail that only comes from having run a fraud desk. Most of what
follows is not "this is wrong" but "this is under-specified in a way that becomes
a decision somebody makes silently".

## Status of each finding

| # | Finding | Applied in |
|---|---|---|
| P1-F1 | The score scale is not computable — PDO fixes the slope, nothing fixes the intercept | SRS **v1.2** §4.3.1.4 and CS-2; Phase 1 §4 Step 3 and §8; Master Appendix B. Ticket LH-208 stays open on the committee for the value |
| P1-F2 | Calibration is fitted on the set the model was selected on | SRS §4.3.2.2 and Phase 1 §4 Step 5 now forbid it; `Part.CALIBRATION` + `carve_calibration()` implement the fourth block |
| P1-F3 | "Largest negative point contribution" is the wrong reason-code rule | SRS §4.3.1 and Phase 1 §4 Step 3 corrected to points-below-max |
| P1-F4 | Reject inference: the same paragraph schedules parcelling and forbids it | SRS §4.3.2.4 and Phase 1 §4 Step 8 separate evidence from belief |
| P1-F5 | The fraud scope test cannot be evaluated at all | Phase 1 §4 WS-1.2 Step 3 is now a two-part, three-valued test; LH-101 open |
| P1-F6 | Monotonicity is imposed on the challenger and inferred for the champion | Phase 1 §4 Step 3 — the ratified list governs the binning direction too; LH-202 open |
| P1-F7 | ER threshold requires labelled pairs no workstream produces | Phase 1 §4 WS-1.2 Step 1 makes it a scheduled task and permits a deterministic-only v1; LH-209 open |
| P1-F8 | **Corrected.** The challenger's uplift is unstable, not absent — and the champion's data sensitivity is why | Phase 1 §7 now requires recording what the challenger bought. See C1 |
| P1-F9 | The champion has no acceptance bar of its own | Phase 1 §7 gives it one; `ValidationReport.role` applies it |
| P1-F10 | Where protected attributes live is unstated | SRS §4.3.3 and Phase 1 §4 Step 7 state the separation, the proxy rule and the ladder's order |
| P1-F11 | Isotonic is mandated where the cited paper advises against it | SRS §4.3.2.2 and Phase 1 §4 Step 5 — chosen by event count and recorded |
| P1-F12 | "IFSC validity" is two different checks | Phase 1 §4 WS-1.2 Step 5 splits them; LH-210 open |
| P1-F13 | Which score each metric class is computed on was unstated | SRS **v1.2** §4.3.4; `validate()` takes score and PD separately. See C2 |
| P1-F14 | "Brier ≤ legacy" barely discriminates at an 8% base rate — the between-model gap is a tenth of the distance to a model that has learned nothing | **Not applied.** Moving a gate threshold is the owner's call with Model Risk. See B7 |

Every `[POLICY]` ticket remains **open** — the documents now say the value is
required and who owns it, which is not the same as having it.

---

## A. Corrections — statements that are wrong or self-contradictory as written

### A1 (P1-F1). The scorecard emits a score that cannot be computed (ticket LH-208)

**§4 WS-1.1 Step 3:** *"… → PDO-20 score scaling (SRS §4.3.1)."*
**SRS §4.3.1:** *"points = offset − factor·log-odds, e.g. 20 points to double the odds."*
**SRS CS-2:** *"score (e.g., 300–900 scale)."*

Points scaling has three constants: PDO, an anchor score, and the odds at that
anchor. PDO = 20 is `[SPEC]` and fixes the *slope*. Nothing anywhere fixes the
intercept, and both places the SRS mentions a scale say "e.g.".

This is worse than an ordinary missing value because the output looks fine. A
score of 612 computed against an invented anchor is indistinguishable from a real
one, and it travels: into a cutoff, into a letter, into a customer conversation,
into a regulator's file. There is no downstream check that could catch it,
because internally consistent nonsense is consistent.

**Implemented:** `Scorecard.points()` raises `Ungrounded` citing LH-208.
`Scorecard.predict()` — the calibrated PD, which is what pricing and IFRS-9
actually consume — works today. The scorecard is fully usable without a score
scale; only the customer-facing number is blocked.

**Recommended:** Phase 1 §8's do-not-invent list should name *the score-scale
anchor*, not just cutoffs. A reader who sees "PDO-20" reasonably concludes the
scale is specified.

### A2 (P1-F2). The calibrator is fitted on the set the model was selected on

**§4 WS-1.1 Step 4:** *"Hyperparameter search on validation vintages only; early stopping."*
**§4 WS-1.1 Step 5:** *"Isotonic regression on the validation set."*

The same rows do both jobs. The challenger stops where validation loss is
lowest, and the calibrator is then fitted where the model was chosen to look
good. The resulting reliability diagram and Brier score are optimistic, and it is
the *calibration* half that matters, because SRS §4.3.2.2 routes PDs into pricing
and IFRS-9 ECL — an optimistic calibration is a systematic mispricing, not a
cosmetic overstatement.

The magnitude depends on how hard early stopping worked. On the Track P run it is
small (Brier 0.0690 → 0.0684 in-sample) because `scale_pos_weight` was 1.0. At a
production imbalance weighting it would not be small.

**Implemented:** `CalibrationReport.optimism_risk` is set whenever the caller
declares the rows were used for model selection, and the note travels into the
validation pack. The module does **not** refuse the phase file's path — an
implementer does not overrule a phase file. `CalibrationSource.CROSS_FITTED_TRAIN`
and `cross_fitted_scores()` are built and tested for the day this is accepted.

**Recommended:** either a four-way split (train / validation / calibration /
out-of-time test), or cross-fitted calibration on the training set. The second is
better on a thin-bad portfolio because it uses the largest sample available,
which is exactly the constraint that binds when defaults are rare.

### A3 (P1-F3). "Largest negative point contribution" is the wrong reason-code rule

**§4 WS-1.1 Step 3:** *"Reason codes = largest negative point contributions."*

Taken literally this ranks characteristics by the *width of their weight range*
rather than by this applicant's shortfall. A heavily-weighted characteristic on
which the applicant is merely average outranks a lightly-weighted one on which
they are in the worst bin. The customer is then told the principal reason for
their decline is something they are unremarkable at.

The scorecard convention — and what an adverse-action duty to state "the
principal reasons why" actually asks for — is **points below max**: the distance
from the applicant's assigned points to the best attainable points on that
characteristic. It answers "why *you*" rather than "what does this model weigh".

**Implemented:** both. `Scorecard.reasons(method="points_below_max")` is the
default; `method="largest_negative"` implements the phase file's literal wording.
The divergence is not silent — it is this finding.

### A4 (P1-F4). Reject inference: the paragraph forbids the method it schedules

**§4 WS-1.1 Step 8:** *"… otherwise document the selection-bias limitation in the
model card and schedule parceling/fuzzy augmentation for the first retrain.
**Never fabricate outcomes for rejects.**"*

Parcelling assigns outcomes to rejected applicants — weighting each as part-good
and part-bad according to the current model's prediction. That is the model's own
belief fed back as data. Read plainly, the last sentence forbids the method the
previous sentence schedules.

There is a coherent reading, and it is worth writing down rather than leaving to
each implementer:

- **Bureau retro is inference from evidence.** Someone else lent to the applicant
  and observed the outcome. It belongs in the target table, flagged as externally
  observed.
- **Parcelling is inference from belief.** Presented as a correction it is
  circular — the model's belief becomes the model's evidence and the resulting
  confidence is manufactured. It belongs in a *sensitivity analysis*: "the
  coefficients move this much if rejects behave as the model already expects".

**Implemented:** `Parcelled` is deliberately not a `TargetRow`, and
`assert_not_in_target()` raises at the point the boundary would be crossed.
`selection_gap()` measures the size of the bias using no reject outcomes at all,
which is the honest thing to report when nothing can correct it.

### A5 (P1-F11). Isotonic is mandated where the cited paper advises against it

**§4 WS-1.1 Step 5** mandates isotonic regression and cites Niculescu-Mizil &
Caruana (ICML 2005). That paper is also the source of the caveat: isotonic needs
more data than Platt scaling and overfits below roughly a thousand examples,
where its step function chases noise.

On a rare-default portfolio the binding constraint is not rows but *events*. A
15% validation slice of a book with a 1% bad rate has a few hundred bads, and an
isotonic fit resting on a few hundred events produces a reliability diagram that
looks precise and is not.

**Implemented:** `recommend_calibrator(n, positives)` returns a recommendation
with its citation, and `CalibrationReport` records both the recommendation and
whether the caller followed it — so a calibrator swapped between retrains is
visible rather than buried.

**Recommended:** Step 5 should read "isotonic where the calibration sample
supports it, Platt otherwise, with the choice recorded", and name the event count
as the test.

---

## B. Gaps — things missing rather than wrong

### B1 (P1-F5). The fraud scope test cannot be evaluated (ticket LH-101)

**§4 WS-1.2 Step 3:** *"If `[DATA]` confirmed frauds < 200 → ship rules + anomaly
layer only."*

This reads as a countable question. It is not. Master Appendix A defines
confirmed fraud as *"a fraud-desk disposition code in the approved taxonomy"*,
and the taxonomy is `[POLICY: Fraud Head]` and does not exist. Until it does,
every count is a count of some code set someone chose — which is precisely the
decision the taxonomy is.

The failure mode is specific: a team counts "cases the desk marked suspicious",
gets 150, reports "below the floor, anomaly layer only", and the number reads as
a data limitation when the truth is that nobody has said what a fraud is. Those
two states need different escalations.

**Implemented:** `Scope` is three-valued — `TAXONOMY_BLOCKED`, `BELOW_MINIMUM`,
`IN_SCOPE` — and the blocked note says explicitly that it is *not* the same as
having too few.

### B2 (P1-F6). Monotonicity is imposed on the challenger and inferred for the champion

**§4 WS-1.1 Step 3** specifies "monotonic optimal binning" for the champion and
says nothing about direction. **Step 4** requires `monotone_constraints` on the
challenger "on the ratified direction list `[POLICY: Credit Risk Head]`".

OptBinning's default picks the direction from the data. So as written, the
champion may encode a data-chosen direction for a feature while the challenger
encodes the committee's — and where those disagree, the two models represent
opposite risk relationships for the same characteristic. The swap-set analysis
Step 9 requires would then be comparing models that disagree about the direction
of risk, and nothing in the process surfaces that.

**Implemented:** every `Binning` records `direction_source` (`"policy"` or
`"data"`), `Scorecard.unresolved_directions()` lists the characteristics fitted
without a ratified direction, and the Track P run reports all 15 as data-chosen.

**Recommended:** Step 3 should state that the ratified direction list governs the
binning direction too, once it exists.

**What Track P showed this costs.** The challenger was fitted unconstrained
(LH-202 is open). Its monotonicity spot checks fail on 2 of 5 characteristics —
two violations on `EXT_SOURCE_2`, one on `EXT_SOURCE_1` — and the ±10%
sensitivity sweep finds 9–11 rows per feature out of 400 where a +10% and a −10%
perturbation move the score the *same* way. The regulator's "counter-intuitive
behaviour" objection SRS §4.3.2.1 describes is not hypothetical; it is what an
unconstrained fit does on real data.

### B3 (P1-F7). The ER threshold needs labelled pairs nothing produces (ticket LH-209)

**§4 WS-1.2 Step 1:** *"name Jaro–Winkler with threshold tuned on labeled duplicate
pairs `[DATA]`."*

No workstream in the programme plan produces a labelled duplicate-pair set. It is
not a committee decision waiting on a meeting — it is clerical work that has to
be scheduled, resourced and sampled properly, and until it happens every
precision claim about entity resolution rests on a number somebody picked.

The consequence is not confined to Phase 1. The entity graph is what Phase 6
trains GraphSAGE and CARE-GNN on; a threshold set by eye determines which edges
exist, and a GNN trained on wrong edges learns rings that are data-quality
artifacts.

**Implemented:** `build_graph()` has **no default threshold** — a default is how
an untuned value becomes the production one — and every graph is stamped with
whether its threshold was ratified.

**Recommended:** add a labelling task to WS-1.2 with an owner and a sample design,
or state that v1 ships deterministic rules only and fuzzy matching is deferred.

### B4 (P1-F9). The champion has no acceptance bar of its own

**§7:** *"Challenger ≥ +3 Gini over rebuilt legacy scorecard on out-of-time test;
Brier ≤ legacy."*

Every numeric exit criterion is about the challenger. The champion is the model
§4 Step 3 names as champion, and on the shipping ladder it is the model that
decides the traffic the challenger is not canarying — yet nothing requires it to
beat the legacy scorecard, or to beat anything.

This is probably an oversight from the ladder's shape (the challenger is the
thing being promoted), but the effect is that the model deciding most
applications passes the gate on the strength of a different model's numbers.

**Recommended:** state a bar for the champion. "No worse than the rebuilt legacy
scorecard on out-of-time Gini and Brier" would be the minimum defensible one.

### B5 (P1-F10). Where protected attributes live is unstated

**§4 WS-1.1 Step 7** requires fairness metrics on gender, age band and geography,
and SRS §4.3.3 says caste and religion are never features and pincode is tested
as a proxy. Neither says where these attributes are *stored*, who can read them,
or what stops one appearing in a feature table.

"Gender is not a feature" enforced by a review checklist survives exactly as long
as the reviewer who remembers it. And the attributes have to be readable — you
cannot measure a disparity you cannot see — so the answer cannot be "we do not
collect them".

**Implemented:** protected attributes are a separate registry;
`FeatureCatalogue.register()` refuses them outright; fairness code reads them
through `ProtectedAttributeAccess`, which no training path is handed; and
`assess()` has no parameter that accepts them inline. The Home Credit adapter
returns them as a separate value, so using gender as a feature would require code
that visibly merges two dictionaries.

**Recommended:** WS-1.1 Step 7 should state the separation and the DPDP purpose
limitation that goes with it — an attribute collected for fairness monitoring is
not thereby available for scoring.

### B6 (P1-F12). "IFSC validity" is two checks with very different value

**§4 WS-1.2 Step 5:** *"deterministic cross-field arithmetic: salary-slip totals,
bank-statement balance continuity across months, IFSC validity."*

Format validity is a regex against a public RBI format. Branch existence is a
lookup against a directory. A forger who knows the format passes the regex every
time, so the first check is close to worthless as a fraud control while reading
exactly like a meaningful one on a deliverables checklist.

**Implemented:** `check_ifsc()` validates format, states in its own result that
existence was not checked, and cites LH-210 for the directory.

### B7 (P1-F14). "Brier ≤ legacy" barely discriminates on a rare event

**§7:** *"Brier ≤ legacy."*

Brier score on a rare event is dominated by the base rate, and at an 8% default
rate almost all of it is the base rate. Predicting 8.02% for every applicant —
a model that has learned nothing — scores **0.0738**. The two Phase 1 models score
0.06996 and 0.06954.

So the whole usable range of the criterion is about 0.004, and the gap it is being
asked to adjudicate between two models is 0.0004 — **a tenth of the distance to a
model with no information in it.** A challenger that is genuinely much better and
one that is marginally worse both land in the third decimal place. On a 1% fraud
base rate, which is where P1's own WS-1.2 evaluation lives, it would be the fourth.

ECE over the same pair is 0.00935 against 0.00600 — a 36% difference where Brier
shows 0.6%. The calibration signal is there; Brier is the wrong instrument for
reading it.

**Recommended.** State the criterion as a **skill score** against the base-rate
null — `1 − Brier / (p(1−p))`, which is 0.0517 and 0.0575 for these two models and
puts the models on a scale where the difference is visible — or state it on ECE,
which §4.3.4 already lists. Keep Brier as a reported number; it is a proper
scoring rule and it belongs in the pack. Just do not ask a comparison to turn on
it. **Not applied**: this one changes a gate threshold rather than clarifying an
instruction, and a gate threshold is the document owner's to move with Model Risk
rather than mine to propose into the file.

---

## C. Track P observations — evidence, not document changes

### C1 (P1-F8). The challenger's uplift is not stable, and the champion is why

**An earlier version of this finding reported an uplift of −0.07 Gini points and
concluded the benchmark had not reproduced. That number was measured wrongly and
the conclusion did not survive the correction.** What replaced it is more useful.

Two defects in the harness produced it: discrimination was computed on the
calibrated PD rather than the raw score (finding P1-F13), and the calibrator was
fitted on the validation rows the challenger had been early-stopped on (P1-F2).
Fixing both changes the measurement, and fixing the *second* changes the answer —
because carving a dedicated calibration block takes 15% of the rows out of
training, and the two models do not react to that equally:

| Configuration | Champion | Challenger | Uplift |
|---|---|---|---|
| 42,000 train, 16 features, calibrated on validation | 47.77 | 47.78 | **+0.01** |
| 35,700 train, 16 features, dedicated calibration block | 44.45 | 47.73 | **+3.28** |
| 89,250 train, 77 features, bureau + repayment history, tuned | 46.86 | **51.94** | **+5.08** |

The challenger is essentially unmoved by losing 15% of its training data
(47.78 → 47.73). The champion loses **3.3 Gini points**. The uplift is not a
property of the challenger at all on this dataset; it is a property of how much
data the champion has.

That is the opposite of the usual intuition, which expects the high-capacity model
to be the data-hungry one. The mechanism is visible in the method: a 15-
characteristic WOE scorecard rests on bin-level event rates, and a bin holding 5%
of a 35,700-row sample has a noisier WOE than the same bin at 42,000 — whereas a
depth-3 ensemble is averaging over 76 trees and absorbs it.

The third row is the current state and it settles the original question: with the
bureau and repayment-history tables loaded, the feature screen corrected (D4) and
the §4 Step 4 search actually run, the challenger clears +3 Gini comfortably and
lands inside the +2–6 the benchmark cites. The benchmark reproduces. What did not
reproduce, in the first two rows, was a pipeline using a fifth of the available
data and a sixth of the available features.

**What follows.**

1. **A single-run uplift figure is not evidence.** It has moved from +0.01 to
   +5.08 across three configurations, none of which changed the *algorithms*. Any
   gate that turns on "+3 Gini" needs the figure computed under a fixed, stated
   split protocol, and reported with the training-set size and feature set that
   produced it.
2. **Two of the four confounds have since been removed.** The challenger *is* now
   tuned — and the search found a 0.0013 log-loss spread across six
   configurations, so that confound was smaller than it looked — and the feature
   screen no longer starves it. The two that remain: three of the features are
   `EXT_SOURCE_1/2/3`, externally-supplied credit scores that already aggregate
   the non-linear structure a GBM would otherwise find (global SHAP 0.391, 0.358,
   0.195 against 0.152 for the next feature), and the split is still not out of
   time.
3. **§7 should record what the challenger bought, not only whether it cleared the
   bar** — applied in Phase 1 v1.1.
4. **The champion's data sensitivity is a scorecard-design finding in its own
   right.** It argues for fewer, better-populated bins, and for checking bin
   stability across resamples before a scorecard is called stable. Not raised as a
   document change, because it is a modelling practice rather than a specification
   gap — but it is the reason the champion's Track P numbers should not be read as
   its ceiling.
5. **Collinearity is the champion's real constraint, not feature availability.**
   With 26 IV-passing candidates, stepwise sign elimination had to drop *fourteen*
   before the signs came out clean, and the card settled at twelve
   characteristics. The bureau aggregates are heavily collinear with one another,
   so most of them cannot sit on the same card however predictive each is alone.

### C2 (P1-F13). Discrimination measured on a calibrated PD understates it

Isotonic regression is monotone, so it cannot reorder a score — but it is a
*step* function, so it collapses distinct scores into ties. On the Track P run it
took **8,969 distinct scores down to 31**, and Gini fell 0.9 points as a result.
Nothing about the model changed; only the number of distinct values it could
express.

The size of the loss depends on how many rows the calibrator saw — 42 distinct PDs
from a 9,000-row calibration sample, 31 from 6,300 — so a model reported this way
appears to get worse when its calibration sample shrinks. That is a reporting
artifact wearing the shape of a model property, and it would be read as evidence
about the model in any review that did not know to look.

Neither SRS §4.3.4 nor Phase 1 §4 Step 9 said which score each metric class is
computed on. **Applied in SRS v1.2**: discrimination on the raw score, calibration
and PSI on the deployed PD, and explicit tie handling required in every rank-based
metric.

### C3. Swap-set concentration is measurable and non-trivial

At a common approval rate the challenger swapped out 505 applicants the champion
approved. The 60–69 age band took **1.86×** its population share of those new
declines. Whether that fails §7's "no adverse-segment concentration" is not
computable — the criterion has no number (LH-205) — but the measurement is real
and the criterion is the only one of the five with no bar.

### C4. Age re-enters through elapsed-time proxies

Age is excluded as a feature. The fitted models nonetheless show an age-band
demographic parity difference of **0.40** (parity ratio 0.43), because
`DAYS_EMPLOYED`, `DAYS_REGISTRATION` and `DAYS_ID_PUBLISH` are all elapsed-time
columns correlated with age. This is the mechanism SRS §4.3.3's proxy probe
exists to detect, observed rather than hypothesised, and it argues for running
the proxy test on *every* feature group rather than only on geography.

---

## D. Judgement calls, recorded rather than corrected

### D1. Two Track P datasets rather than one

ADR-0010's reasoning in full. Home Credit has the right product shape and the
protected attributes; Fannie Mae has the only absolute time axis. Neither carries
the phase alone, and the alternative — picking one and quietly relaxing what the
other was needed for — is how a limitation stops being visible.

### D2. Reference implementations rather than the named libraries

Master §2 rule 2 permits "use that library, or port it with unit tests
reproducing the library's outputs on fixture data". Every algorithm here is a
port behind the interface the library will occupy: OptBinning, LightGBM, SHAP,
Fairlearn, scikit-learn's IsolationForest, splink. Each module states what it
ports and what it does **not** — the GBM has no GOSS or EFB; the binning is PAVA
rather than a MIP; SHAP is exact enumeration rather than TreeSHAP's polynomial
algorithm, which is viable only because the trees are depth-limited.

The tests assert the *properties* a Track B swap must preserve rather than pinned
numbers, because a test pinned to this port's exact cut points would fail on the
library it is a port of.

### D3. The orchestrator still refers everything

Phase 1 §5.2 requires cutoffs to be config under dual control. They are — and
every edge in `config/policy_bands.yaml` is a registered placeholder, so the
orchestrator refers every scored application to a human. That is not a stub: it
is the correct behaviour for a platform with no approved decision boundary, and
making it the default is what stops a missing config from being filled in with
something plausible.

The orchestrator now distinguishes *two* reasons for referring —
`P1_CUTOFFS_NOT_RATIFIED` (the numbers are `[POLICY]`) and
`P1_BANDS_NOT_DUAL_APPROVED` (a control failed) — because those go to different
people.

### D4. The IV floor was applied to the challenger, and the documents never said to

An implementation defect of mine, recorded here because it is the kind that hides
successfully: the run screened its **challenger's** feature set through the
information-value floor and kept only what passed.

Both documents scope that screen to the champion. SRS §4.3.1 states the IV window
inside the scorecard's method, and Phase 1 §4 Step 3 restates it in the champion
step; Step 4, the challenger, says nothing about IV. Nothing asked for the screen
to be shared, and there is a reason it should not be: a scorecard needs each
characteristic to carry standalone signal because each contributes independently,
whereas a tree ensemble's advantage *is* the interaction between features that are
individually weak. Screening on standalone IV removes exactly the features a GBM
is there to exploit.

The cost was large. With the bureau and repayment-history tables loaded, 74 of the
candidates bin successfully and 31 clear the IV floor — so the screen was
discarding **43 features** before the challenger ever saw them. The challenger now
takes everything that bins, minus anything the leakage *ceiling* flagged, which is
the one half of the screen that protects it rather than starving it.

Worth noting what this did to finding P1-F8's territory: two of the reasons the
uplift looked weak — "the challenger was not tuned" and "only 17 of 56 candidates
survived the screen" — were partly this defect rather than properties of the data.

### D5. A defect the Track P run found in the harness

The first run reported a train-to-test score PSI of **4.69** on a *random* split
of a single population, which is impossible. The cause was comparing raw training
scores against calibrated test scores: PSI does not know it has been handed two
scales, it just returns a large number. Corrected (both sides calibrated; PSI is
now 0.0017), and recorded here because the failure shape generalises — a
stability metric fed two different score definitions produces a frightening
number that reads as a finding about the population.

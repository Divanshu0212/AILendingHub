# Phase 1 — implementation findings against the phase documents

Produced while building Phase 1. Master §1: "conflicts are raised as tickets,
never resolved silently by an implementer." So every finding below is **raised
and unapplied** — the code implements what the documents say, and where it does
something else it says so at the point of use and stamps the difference into its
own output. Applying any of these is the document owner's call, not the
implementer's.

The Phase 1 document is good. Its workstream decomposition is right, its
do-not-invent list is unusually complete, and the fraud section's insistence that
the anomaly layer feeds the supervised layer rather than alerting separately is
the kind of detail that only comes from having run a fraud desk. Most of what
follows is not "this is wrong" but "this is under-specified in a way that becomes
a decision somebody makes silently".

## Status

| # | Finding | Kind | Raised as |
|---|---|---|---|
| P1-F1 | The score scale is not computable — PDO fixes the slope, nothing fixes the intercept | Gap | LH-208 |
| P1-F2 | Calibration is fitted on the set the model was selected on | Correction | Recorded on every `CalibrationReport` |
| P1-F3 | "Largest negative point contribution" is the wrong reason-code rule | Correction | Both implemented; points-below-max is the default |
| P1-F4 | Reject inference: the same paragraph schedules parcelling and forbids it | Correction | `Parcelled` is not a `TargetRow` |
| P1-F5 | The fraud scope test cannot be evaluated at all | Gap | Three-valued `Scope`; LH-101 |
| P1-F6 | Monotonicity is imposed on the challenger and inferred for the champion | Gap | `direction_source` on every binning; LH-202 |
| P1-F7 | ER threshold requires labelled pairs no workstream produces | Gap | LH-209 |
| P1-F8 | The challenger's expected Gini uplift did not reproduce | Track P observation | Recorded, not a doc change |
| P1-F9 | The champion has no acceptance bar of its own | Gap | Recorded below |
| P1-F10 | Where protected attributes live is unstated | Gap | `ProtectedAttributeAccess` |
| P1-F11 | Isotonic is mandated where the cited paper advises against it | Correction | `recommend_calibrator` |
| P1-F12 | "IFSC validity" is two different checks | Gap | LH-210 |

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

---

## C. Track P observations — evidence, not document changes

### C1 (P1-F8). The challenger's expected Gini uplift did not reproduce

SRS §4.3.2 cites Lessmann et al. (EJOR 2015) for GBMs delivering "typically +2–6
Gini points over logistic scorecards". On the Track P run (Home Credit, 60,000
applications, 8.0% bad rate, 17 IV-screened features) the challenger scored
**47.60 Gini against the champion's 47.66** — an uplift of −0.07 points — with a
worse Brier (0.06961 vs 0.06906).

**What this is not.** It is not evidence that the SRS is wrong, and it must not
be quoted as a reason to drop the challenger. Four confounds, any of which could
account for it:

1. The challenger was **not tuned**. Fixed hyperparameters against a scorecard
   whose binning is optimal by construction is not a fair fight.
2. Three of the seventeen features are `EXT_SOURCE_1/2/3` — externally supplied
   credit scores that already aggregate the non-linear structure a GBM would
   otherwise discover. Global SHAP confirms they dominate (0.403, 0.309, 0.190
   mean |SHAP| against 0.170 for the next feature).
3. The split is **not out of time**, and the benchmark's uplift is largest
   exactly where relationships shift.
4. Only 17 features survived the IV screen out of 56 candidates. A GBM's
   advantage is interactions, and there are fewer interactions available.

**What it is.** A reason to treat "+2–6 Gini" as a hypothesis this bank tests on
its own data rather than a result it can assume. Phase 1 §3 already reduces scope
to scorecard-only below 1,500 bads; this suggests the gate should also record
what the challenger actually bought, because on a bureau-score-dominated feature
set the answer may be "very little, at the cost of monotonicity and
explainability".

### C2. Swap-set concentration is measurable and non-trivial

At a common approval rate the challenger swapped out 505 applicants the champion
approved. The 60–69 age band took **1.86×** its population share of those new
declines. Whether that fails §7's "no adverse-segment concentration" is not
computable — the criterion has no number (LH-205) — but the measurement is real
and the criterion is the only one of the five with no bar.

### C3. Age re-enters through elapsed-time proxies

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

### D4. A defect the Track P run found in the harness

The first run reported a train-to-test score PSI of **4.69** on a *random* split
of a single population, which is impossible. The cause was comparing raw training
scores against calibrated test scores: PSI does not know it has been handed two
scales, it just returns a large number. Corrected (both sides calibrated; PSI is
now 0.0017), and recorded here because the failure shape generalises — a
stability metric fed two different score definitions produces a frightening
number that reads as a finding about the population.

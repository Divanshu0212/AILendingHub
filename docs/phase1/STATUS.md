# Phase 1 — status and traceability

Maps every item on the Phase 1 §6 deliverables checklist to the artifact that
satisfies it, the track it runs on, and its honest state.

**Read the track column before quoting any number.** Track A is evidence about
the code, Track P is evidence that the code survives real data
([ADR-0004](../adr/0004-public-reference-data-track.md)); only **Track B** counts
as gate evidence, and there is none.

Last updated: 2026-09-01 (findings accepted and applied; SRS v1.2, Master v1.2, Phase 1 v1.1).

## The headline

Every Phase 1 workstream is **built and exercised on real applications**. No
Phase 1 exit criterion has Track B evidence, and none can until Phase 0's entry
criteria land ([LH-120](../phase0/blocking_tickets.md)). Phase 1's own entry
criterion — "P0 gate passed" — is therefore unmet, and what exists is everything
buildable before it is.

Track P run: **150,000** Home Credit applications across all three usable tables
(1.72M bureau records, 10.0M monthly balances carrying observed DPD), 8.17% bad
rate, 77 candidate features, both models fitted, tuned, calibrated, explained,
fairness-tested and validated in about 17 minutes.

| | Champion | Challenger |
|---|---|---|
| AUC | 0.7343 | **0.7597** |
| Gini | 46.86 | **51.94** |
| KS | 0.3585 | 0.3899 |
| Brier skill vs base-rate null | +0.0810 | **+0.1017** |
| ECE | 0.00708 | 0.00740 |

The split is not out of time and the comparator is the champion rather than a
rebuilt legacy scorecard, so **this satisfies no §7 criterion**. `make trackp-p1`
reproduces it; `make gate1` assembles the pack.

## Deliverables checklist (Phase 1 §6)

| # | Item | Artifact | Track | State |
|---|---|---|---|---|
| 1 | ADR-010 (product), ADR-011 (ER library) | [ADR-0010](../adr/0010-scored-product-and-track-p-standin.md) · [ADR-0011](../adr/0011-entity-resolution-library.md) | — | **partial** — both merged; the Track B product choice is `[POLICY]` (LH-201) |
| 2 | Target script + split manifest (versioned) | [target.py](../../src/lending_hub/scoring/target.py) · [splits.py](../../src/lending_hub/scoring/splits.py) | A+P | **done** — ledger reconciles; manifest hashed and stamped `out_of_time` |
| 3 | Feast feature definitions + metadata screens | [features.py](../../src/lending_hub/scoring/features.py) · [homecredit_history.py](../../src/lending_hub/sources/homecredit_history.py) | A+P | **partial** — 10 bank definitions with source/PIT/null/IV/PSI metadata, and the bureau + repayment-history groups now exercised on 1.72M real credit records and 10.0M monthly balances; Feast deployment is LH-120 |
| 4 | Champion scorecard + challenger in MLflow (calibrated) | [scorecard.py](../../src/lending_hub/scoring/scorecard.py) · [gbm.py](../../src/lending_hub/scoring/gbm.py) · [calibration.py](../../src/lending_hub/scoring/calibration.py) | A+P | **partial** — both fitted, tuned (§4 Step 4 search) and calibrated on a dedicated block; the champion's signs converge with no wrong-signed characteristics; MLflow server is LH-120; the challenger is **not promotable** (LH-202) |
| 5 | SHAP reason-code service + editable mapping table | [explain.py](../../src/lending_hub/scoring/explain.py) · [reasons.py](../../src/lending_hub/scoring/reasons.py) · [config/reason_codes.yaml](../../config/reason_codes.yaml) | A+P | **partial** — exact Shapley values with local accuracy asserted; every sentence is `TBD` (LH-203), so no letter can be rendered |
| 6 | Fairness report; reject-inference memo | [fairness.py](../../src/lending_hub/scoring/fairness.py) · [rejects.py](../../src/lending_hub/scoring/rejects.py) | A+P | **partial** — disparities measured on Track P; no verdict is computable (LH-205); reject inference is **not exercisable** (no declined applications, ADR-0010) |
| 7 | Independent validation report (both models) | [validation.py](../../src/lending_hub/scoring/validation.py) | A+P | **partial** — the harness runs and produces both reports; *independent* validation needs a validator who is not the developer (Master §3.1) and none exists |
| 8 | Entity graph tables + ER tuning report | [entity_resolution.py](../../src/lending_hub/fraud/entity_resolution.py) | A | **partial** — nodes/edges schema fixed for P6, every edge carries its evidence; tuning needs labelled pairs (LH-209) |
| 9 | Flink velocity jobs; fraud GBM + IsolationForest registered | [velocity.py](../../src/lending_hub/fraud/velocity.py) · [supervised.py](../../src/lending_hub/fraud/supervised.py) · [anomaly.py](../../src/lending_hub/fraud/anomaly.py) | A | **partial** — all three built with the two-timestamp discipline and a skew check; no Flink cluster (LH-120); the supervised layer is **taxonomy-blocked** (LH-101) |
| 10 | Document-check service v1; AA-first rule wired | [documents.py](../../src/lending_hub/fraud/documents.py) | A | **partial** — arithmetic checks and AA-first done; OCR is a port; IFSC existence needs a directory (LH-210) |
| 11 | Case-management routing with mandatory dispositions | [routing.py](../../src/lending_hub/fraud/routing.py) | A | **partial** — completeness enforced from day one; the taxonomy itself is `[POLICY]` (LH-101), so `training_labels()` refuses |
| 12 | Shadow/canary comparison dashboards | [shadow.py](../../src/lending_hub/serving/shadow.py) · [bands.py](../../src/lending_hub/serving/bands.py) | A | **partial** — comparison and ladder-status logic built; nothing to compare until a model scores live traffic |

## Exit criteria (Phase 1 §7)

Generated by `make gate1` into `reports/phase1_gate.md`. Eight criteria since
Phase 1 v1.1 gave the champion a bar of its own. Summary:

| # | Criterion | Track B evidence | Why not |
|---|---|---|---|
| 1 | Champion ≥ rebuilt legacy, out-of-time | No | No rebuilt legacy scorecard exists on Track P |
| 2 | Challenger ≥ +3 Gini over rebuilt legacy, out-of-time | No | No legacy model, and no source with a usable time axis and the right product |
| 3 | Brier ≤ legacy | No | Same |
| 4 | Swap set: no adverse-segment concentration | No | The criterion has **no numeric bar** (LH-205); the measurement exists |
| 5 | Fraud precision at operating alert budget ≥ incumbent | No | **Not evaluable** — no confirmed-fraud taxonomy (LH-101) |
| 6 | Step-up friction < 3% | No | Same |
| 7 | Decision-log spot audit: 100 re-scored decisions identical | No | The orchestrator has decided nothing — every band edge is a placeholder (LH-204) |
| 8 | Model cards + independent validation signed | No | Cards written for both models; neither is signed, and no independent validator exists |

## What is actually finished

Engineering that does not depend on bank access, and is done:

- Target engineering whose ledger **reconciles** and whose exclusions refuse to
  report success when the flag they read is absent.
- A splitter that refuses a random split unless the *source registry* declares the
  dataset clockless, and stamps `out_of_time=false` on everything it then produces.
- Monotone optimal binning, WOE and IV with a leakage-alarm ceiling that survives
  a perfectly-separating feature.
- A WOE scorecard whose points method **raises** rather than emitting a score on an
  invented scale.
- A monotone-constrained histogram GBM that will not fit without a direction for
  every feature, and reports itself unpromotable without a ratified list.
- Isotonic and Platt calibration, with the optimism of the phase file's own path
  recorded rather than hidden.
- **Exact** Shapley attribution with local accuracy asserted per explanation.
- Fairness measurement that returns numbers and refuses to return a verdict.
- Reject inference that cannot fabricate an outcome, enforced by the type system.
- Entity resolution producing the graph schema P6 will train on, with evidence on
  every edge.
- Event-time velocity counters that measure their own training/serving skew.
- Document checks in integer minor units, with AA-first as a rule and not a
  preference.
- A case queue that will not close a case without a validated disposition.
- Policy bands as dual-control config, with the band version on every decision.

**793 tests, stdlib only, green on a clean clone in about 9 seconds.**

## What is blocked, and on whom

See [blocking_tickets.md](blocking_tickets.md) — ten Phase 1 tickets. The three
Phase 0 tickets that block Phase 1 as hard as they block Phase 0 are **LH-101**
(fraud disposition taxonomy), **LH-103** (default code sets) and **LH-120**
(data-sharing approvals).

The critical path is LH-120, exactly as it was for Phase 0.

## Findings raised against the docs

Thirteen, in [Phase_1_FINDINGS.md](../../Lending_Hub_Phase_Docs/Phase_1_FINDINGS.md).
Raised first and left unapplied per Master §1; **the document owner has accepted
them and they are now applied** — SRS **v1.2**, Master **v1.2**, Phase 1 **v1.1**.
The code has followed the corrected documents, which is where the calibration
block, the champion exit criterion and the score-versus-PD separation came from.

Accepting them changed the documents, not the tickets: every `[POLICY]` value is
still outstanding. The documents now say what is required and who owns it, which
is not the same as having it.

| # | Finding | Applied in |
|---|---|---|
| P1-F1 | The score scale is not computable: PDO fixes the slope, nothing fixes the intercept | SRS §4.3.1.4, CS-2, Phase 1 §4 Step 3 and §8 |
| P1-F3 | "Largest negative point contribution" ranks by a characteristic's weight range, not the applicant's shortfall | SRS §4.3.1, Phase 1 §4 Step 3 |
| P1-F4 | Step 8 schedules parcelling in the paragraph that forbids fabricating reject outcomes | SRS §4.3.2.4, Phase 1 §4 Step 8 |
| P1-F9 | The champion decides most traffic and had no bar at all | Phase 1 §7; `ValidationReport.role` |
| P1-F13 | Discrimination measured on a calibrated PD understates it — 8,969 distinct scores collapsed to 31 | SRS §4.3.4; `validate()` takes both series |

**One finding was itself wrong.** P1-F8 originally reported that the challenger's
Gini uplift did not reproduce (−0.07 points). That number came from measuring
discrimination on calibrated PDs and calibrating on the selection set; corrected,
the uplift is **+3.28**. The replacement finding is more useful than the original:
the uplift swings from +0.01 to +3.28 on a 15% change in training-set size, and
the whole swing is the *champion's* degradation — the challenger is unmoved. A
single-run uplift figure is not evidence, and the model that turned out to be
data-hungry was the scorecard, not the ensemble.

## Performance work, and what it did not change

The models improved substantially inside this phase — challenger Gini 47.73 →
51.94, Brier skill +0.058 → +0.102, and the champion's five wrong-signed
characteristics eliminated. The causes, in order of size: the bureau and
repayment-history tables (previously unread), the corrected feature screen
(finding D4), four times the training data, the §4 Step 4 hyperparameter search,
and stepwise sign elimination.

**None of it moves a single exit criterion.** The split is still not out of time,
the label is still the vendor's, there is still no rebuilt legacy scorecard, and
no independent validator exists. A better Track P model is a better demonstration
that the code paths work; it is not evidence, and the gate pack still reads 0 of 8.

On speed: a fit uses one core for the phase that dominates it, because boosting is
sequential across trees. Binning and the hyperparameter search are parallelised
(`scoring/parallel.py`); the rest is a consequence of ADR-0003's stdlib-only rule,
which trades throughput for a suite that runs anywhere with no install.

## Where to start reading

| You want to | Read |
|---|---|
| Run the whole thing on real data | `make trackp-p1`, then `reports/trackP_p1_home_credit.json` |
| See the gate position | `make gate1`, then [reports/phase1_gate.md](../../reports/phase1_gate.md) |
| Understand what the models are and are not | [model_cards/](model_cards/) |
| Know where the docs and the build disagree | [Phase_1_FINDINGS.md](../../Lending_Hub_Phase_Docs/Phase_1_FINDINGS.md) |
| Know what is waiting on a committee | [blocking_tickets.md](blocking_tickets.md) |

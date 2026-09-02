# Phase 5 — gate evidence pack

Generated 2026-09-02T06:02:48.984790+00:00 by `tools/phase5_gate_report.py`.

**Phase 5 is the first phase whose central guarantee is structural**
rather than measured. Phase 4 introduced one such column (propensity
completeness); Phase 5 has several, and the risk that a structural
guarantee is read as a measurement is correspondingly larger. So every
structural claim below names the **code path it guards**, because that
is exactly what a guarantee does not cover.

There is **no Track P** for this phase, and that is a decision rather
than an unrun job: public RAG benchmarks exist and test the wrong
property. See [ADR-0015](../docs/adr/0015-phase5-assistant-track.md).

Per ADR-0003 and ADR-0004, **only Track B numbers are gate evidence.**

## Exit criteria (Phase 5 §7)

| # | Criterion | Workstream | Track | Measured | State |
|---|---|---|---|---|---|
| 1 | Retrieval hit-rate@5 >= 95% on the golden set | WS-5.2 | — | — | **not measurable** — hit-rate is defined *on the golden set, against the corpus*, and neither exists (LH-602, LH-601). The metric and its admission gate are implemented and tested; the number they would compute has no inputs. No public benchmark substitutes — see ADR-0015: the stale-rate failure this phase is built around happens when retrieval *succeeds*, and no public corpus has documents that supersede each other |
| 2 | Answer faithfulness >= 97% | WS-5.4 | — | — | **not measurable** — requires generated answers, which requires a bound model (LH-604). The RAGAS decomposition and aggregation are implemented; the entailment judgement is a port, and the obvious fallback is worse than nothing — a lexical-overlap groundedness score is highest exactly where a negation has been flipped |
| 3 | Uncited-numeric leak rate = 0 in weekly audits (hard gate) | WS-5.3.1 | A | leak rate 0.0, basis **structural** | **structurally guaranteed on Track A** — `ValidatedAnswer` cannot be constructed holding a kept sentence with an uncited numeric claim, so the rate cannot be non-zero along this path. Stronger than the criterion asks (a weekly audit samples, and a sample can show a rate is low but never that it is zero) and narrower than it sounds — see below |
| 4 | Containment >= [POLICY: target] with correct-escalation >= 95% | WS-5.4 | — | — | **not measurable** — no sessions, and the target itself is unratified (LH-605). Containment is also the one metric in this phase that improves when the assistant gets more reckless, so a target set without correct-escalation beside it rewards answering questions the assistant should refuse |
| 5 | Red-team sign-off current | WS-5.4 | — | — | **not measurable** — the three suites (injection, jailbreak, PII-leak) run in CI as required by §5 step 2, and a green suite is **not** the sign-off. They exercise the deterministic defences against the attacks we wrote down; there is no model (LH-604), so nothing tests whether a model resists a jailbreak. The sign-off is a human act by a security function that does not exist here |
| 6 | Compliance sign-off on KFS/disclosure behavior | WS-5.3.3 | — | — | **not measurable** — a human act by a function that does not exist here. Its inputs are LH-606 (conversational PII classes) and LH-111 (log retention), neither of which is supplied |

**Track B evidence: 0 of 6.**

## Criterion 3 — what the guarantee covers, and what it does not

Phase 5 §7 makes the uncited-numeric leak rate a hard gate measured in
weekly audits. This repository takes the other route, the same one
Phase 4 took for propensity completeness: the validator strips an
uncited numeric sentence before the answer object exists, and an answer
stripped of all its numeric content becomes a handoff rather than a
thinner answer.

Two limits travel with that and are not optional reading:

* **It guards a code path, not a product.** A generation service that
  renders model output without calling `validate()` is outside the
  guarantee. The validator returns a new object rather than mutating a
  string precisely so that skipping it leaves nothing to render.
* **It is about citation, not truth.** A cited number can still be
  wrong — if the citation is to a partially superseded circular
  (LH-608), or the retrieval was poisoned. Effective-date filtering and
  the faithfulness scorer address that, and neither is measurable here.

## What is exact, and is therefore built and tested in full

This is the column that makes Phase 5 unlike Phase 2. Most of what the
phase file specifies is deterministic and needs no corpus, no golden
set and no model.

| Component | Status |
|---|---|
| Effective-date filtering (`assistant.registry`) | **done** — undated ingestion refused by constructor; `effective()` requires an as-of date with no default |
| Structure-aware chunking (`assistant.chunking`) | **done** — tables atomic over the token ceiling; metadata inherited |
| BM25 (`assistant.retrieval`) | **done** — full Robertson & Zaragoza port, pinned against hand-computed scores |
| Reciprocal-rank fusion (`assistant.retrieval`) | **done** — Cormack et al., k=60, needs no score normalisation |
| Numeric-claim validator (`assistant.answer`) | **done** — adversarially tested; the phase's central control |
| Tool schema validation and allow-list (`assistant.tools`) | **done** — closed schema subset that raises on an unimplemented keyword |
| Guardrail patterns (`assistant.guardrails`) | **done** — fences, refusal ids, injection scan, PII redaction |
| Faithfulness decomposition + suppression (`assistant.faithfulness`) | **done** — the entailment judgement is a port |
| Golden-set admission gate (`assistant.goldenset`) | **done** — refuses to score an inadmissible set |

## Deliverables (Phase 5 §6)

| # | Item | State |
|---|---|---|
| 1 | Document registry + dated ingestion | **done**; corpus empty (0 documents registered) — LH-601 |
| 2 | Chunking; golden set v1 (>= 500 triples) | chunking **done**; golden set **absent** — LH-602, which depends on LH-601 |
| 3 | Hybrid retrieval + reranker; hit-rate@5 report | BM25/RRF/metric **done**; dense leg and reranker unbound (LH-604); no hit-rate |
| 4 | Generation service + citation contract + numeric validator | validator **done**; no generation service (LH-604) |
| 5 | Tool layer (4 launch tools) + schema validation + rate limits | **done** — book_branch_slot, compute_emi, get_application_status, get_document_checklist. `compute_emi` delegates to `reco.feasible.emi`; the other three refuse without their backends. Rate ceiling unratified (LH-612) |
| 6 | Adverse-action template library | selection and ordering **done**; 10 templates over 10 codes, **none ratified** — LH-603, LH-203, LH-610 |
| 7 | Guardrails; injection/jailbreak/PII red-team suites in CI | **done** — the three suites are `tests/test_assistant_redteam.py` and run on every commit, which is the cadence §5 step 2 asks for |
| 8 | Faithfulness scorer + suppression + weekly audit | scorer and suppression **done**; entailment is a port (LH-604). Audit sample rate 2% is [SPEC]; no sessions to sample |
| 9 | Officer beta report; escalation flow | **not done** — 50 officers for 6 weeks (§5 step 1). The escalation *contract* exists in `answer.py` |
| 10 | DPDP/RBI-KFS compliance review memo | **not done** — inputs are LH-606 and LH-111 |

## Nothing here is fabricated

No corpus document, no golden-set triple, no adverse-action sentence
and no generated answer exists in this repository, and no LLM is called
anywhere. The argument is ADR-0015's and it is worth restating, because
Phase 5 is the easiest phase in the programme to demo convincingly:

A faithfulness number computed over a fabricated corpus measures the
fabricator. Worse than Phase 4's simulated collections desk, because
the corpus author, the golden-set author and the retrieval author would
be the same person — so the assistant would score well exactly to the
extent that the questions were written against documents written to
answer them.

And a fabricated rate circular is the *specific* failure this phase
exists to prevent. Stale-rate poisoning is named as the #1 RAG failure
in banks; a synthetic rate sheet sitting in a repository whose grounding
checker exists to stop invented numbers is a contradiction a future
reader resolves in the wrong direction.

Test fixtures are a different matter and are used freely — Master §2
rule 3 puts synthetic data in `tests/fixtures/`. No fixture document is
servable outside a test, and no number computed on one is reported here.

## Model cards (Master §2 rule 5)

| Card | Signed |
|---|---|
| hybrid_retriever.md | **no** |
| numeric_claim_validator.md | **no** |

None signed: Master §3.1 requires an independent validator who is not
the developer, and there is none. Two of these document components
that are not statistical models — a retriever and a validator — and
that is deliberate: a retrieval configuration decides which document
a customer is answered from, which is a model-risk surface whatever
it is called.

## Open blocking tickets

| Ticket | Owner |
|---|---|
| LH-601 | Product SMEs + Compliance |
| LH-602 | Product SMEs |
| LH-603 | Compliance |
| LH-604 | GenAI squad + Model Risk |
| LH-605 | Product + Compliance |
| LH-606 | DPO |
| LH-607 | Security + GenAI squad |
| LH-608 | Compliance + Product |
| LH-609 | GenAI squad |
| LH-610 | Compliance + Product SMEs |
| LH-611 | Compliance |
| LH-612 | Security + Product |

12 open. Six are Phase 5 §8 do-not-invent values.
**Six were found by building** — LH-606 (conversational PII is not
schema PII), LH-607 (an injection defence with no stated response),
LH-608 (partial supersession, which effective dates cannot express),
LH-610 (a language slice with no minimum size), LH-611 (tool-sourced
numbers versus document-sourced ones), LH-612 (the per-session tool
ceiling).

**LH-601 and LH-602 are the pair to read.** The corpus and the golden
set block four of the six exit criteria between them, and the second
depends on the first: a triple's answer is only correct relative to
documents that exist, so the set cannot be curated before the corpus
is. That changes the scheduling question from "when will SMEs write
it" to "when will there be something to write it against".

**LH-608 is the one that will surprise people.** Two circulars
effective at once, the later amending the earlier in part. Retrieval
returning both lets the model pick between two live rates; superseding
the earlier drops its unamended clauses. Effective dates cannot
express it, and the phase file names neither case.

## Gate outcome

**Fail.** No criterion has Track B evidence. Four cannot have any
without a corpus, a golden set, a bound model and a deployed service;
two require human sign-offs by functions that do not exist here.

One criterion — the uncited-numeric leak rate — is satisfied more
strongly than it is stated, as a property of a type rather than a
sampled measurement, over the code path `validate()` guards.

What a Track B team receives: a complete deterministic spine — dated
corpus governance, structure-aware chunking, an exact BM25, rank fusion,
an adversarially tested numeric-claim validator, an allow-listed tool
layer whose EMI is the bank's one reference implementation, and
guardrails that treat retrieved documents as untrusted — with the LLM,
the embedder, the vector store, the reranker and the entailment model as
five unbound ports, and a validator that will strip its model's output
without asking.

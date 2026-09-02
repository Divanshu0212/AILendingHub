# Phase 5 — status and traceability

Maps every item on the Phase 5 §6 deliverables checklist to the artifact that
satisfies it, the track it runs on, and its honest state.

**Phase 5 is the first phase whose central guarantee is structural rather than
measured.** See [ADR-0015](../adr/0015-phase5-assistant-track.md).

Last updated: 2026-09-02.

## The headline

Phase 5 has no corpus, no golden set, no LLM and no approved templates — and
**most of what the phase specifies needs none of them.** That combination is new
here, and it is why this phase is not a second Phase 2.

| Layer | Question it answers | Evidence available |
|---|---|---|
| **Deterministic spine** — registry, chunking, BM25, RRF, the numeric-claim validator, tool schemas, guardrail patterns | Does the code do the exact thing the phase file specifies? | **Yes, Track A, in full.** These are closed-form functions with right answers on every input, tested against hand-computed cases |
| **Structural guarantees** — uncited-numeric leak, undated ingestion, LLM arithmetic, composed adverse-action prose | Can the failure happen at all? | **Proven by type.** Not a measurement and not a sample — a property of the constructors |
| **Retrieval and answer quality** — hit-rate@5, faithfulness, containment | Is the assistant any good? | **None, and none possible.** Both metrics are defined *on the golden set against the corpus*, and neither exists (LH-601, LH-602) |

**Nothing here fabricates a corpus document, a golden-set triple, an
adverse-action sentence or a generated answer**, and no LLM is called anywhere.
That is the phase's central refusal, argued in ADR-0015: a faithfulness number
computed over a corpus written by the same person who wrote the questions
measures the author, not the assistant.

## Deliverables checklist (Phase 5 §6)

| # | Item | Artifact | Track | State |
|---|---|---|---|---|
| 1 | Document registry + dated-corpus ingestion with effective-date filtering | [registry.py](../../src/lending_hub/assistant/registry.py) | A | **done** — ingestion refuses an undated document by constructor invariant; retrieval filters to currently-effective documents by default. No corpus to load (LH-601) |
| 2 | Chunking pipeline; golden set v1 (≥ 500 triples, per-language slices) | [chunking.py](../../src/lending_hub/assistant/chunking.py) · [goldenset.py](../../src/lending_hub/assistant/goldenset.py) | A | **split** — chunking **done**; the golden set is **not started and has no author** (LH-602). The harness that measures against it ships ahead of it, and refuses to report a metric on a set that fails its own admission gate |
| 3 | Hybrid retrieval + reranker; hit-rate@5 report | [retrieval.py](../../src/lending_hub/assistant/retrieval.py) | A | **partial** — BM25, RRF and the hit-rate metric are built and tested; the dense retriever and cross-encoder are unbound ports (LH-604). No hit-rate number: no corpus, no questions |
| 4 | Generation service with citation contract + deterministic numeric-claim validator | [answer.py](../../src/lending_hub/assistant/answer.py) | A | **done for the part that matters** — the validator is exact and adversarially tested; an uncited numeric claim cannot exist inside a `ValidatedAnswer`. No generation service: no model (LH-604) |
| 5 | Tool layer (4 launch tools) with schema validation + rate limits | [tools.py](../../src/lending_hub/assistant/tools.py) | A | **partial** — all four launch tools registered, schema-validated and rate-limited. `compute_emi` delegates to `reco.feasible.emi`; the other three are ports onto P1/P4 systems that are not deployed |
| 6 | Adverse-action template library (per language) wired to P1 reason codes | [templates.py](../../src/lending_hub/assistant/templates.py) | A | **partial** — selection, ordering and the no-composition guarantee are built; **every template raises**, because the sentences are LH-603 and the reason-code wording under them is LH-203 |
| 7 | Guardrails layer; injection/jailbreak/PII red-team suites in CI | [guardrails.py](../../src/lending_hub/assistant/guardrails.py) · [tests/test_assistant_redteam.py](../../tests/test_assistant_redteam.py) | A | **partial** — topic fences, refusal library, indirect-injection scanning and PII redaction built; the three red-team suites run in CI as tests. Coverage of the pattern sets is an open empirical question, and the quarantine threshold is LH-607 |
| 8 | Faithfulness scorer + suppression path + weekly audit process | [faithfulness.py](../../src/lending_hub/assistant/faithfulness.py) | A | **partial** — decomposition, support-checking mechanics and the suppression path are built and tested; the entailment judgement is a port (LH-604). No audit process: no sessions |
| 9 | Officer beta report; escalation flow to human channels | — | — | **not done** — 50 officers for 6 weeks (Phase 5 §5). The escalation *contract* is in `answer.py` as the handoff path |
| 10 | DPDP/RBI-KFS compliance review memo | — | — | **not done** — a memo by a function that does not exist here. LH-606 (conversational PII classes) and LH-111 (log retention) are its inputs |

## Exit criteria (Phase 5 §7)

| # | Criterion | State |
|---|---|---|
| 1 | Retrieval hit-rate@5 ≥ 95% on the golden set | **not measurable** — the metric is implemented and tested; its two inputs are LH-601 and LH-602 |
| 2 | Answer faithfulness ≥ 97% | **not measurable** — needs generated answers, which needs a model (LH-604) |
| 3 | Uncited-numeric leak rate = 0 (hard gate) | **structurally guaranteed on Track A** — the only criterion this repository can satisfy, and it satisfies it more strongly than the criterion asks. See below |
| 4 | Containment ≥ `[POLICY: target]`, correct-escalation ≥ 95% | **not measurable** — no sessions, and the target itself is unratified (LH-605) |
| 5 | Red-team sign-off current | **not measurable** — the suites run in CI; the sign-off is a human act by a function that does not exist |
| 6 | Compliance sign-off on KFS/disclosure behavior | **not measurable** — same |

**Track B evidence: 0 of 6.**

### On criterion 3, which is the interesting one

Phase 5 §7 makes uncited-numeric leak rate = 0 a hard gate **measured in weekly
audits**. An audit samples; a sample can establish that a rate is low and never
that it is zero.

This repository takes the other route, the same one Phase 4 took for propensity
completeness. `ValidatedAnswer` cannot be constructed holding an uncited numeric
claim: the validator strips those sentences before the object exists, and an
answer stripped of all its numeric content becomes a handoff rather than a
thinner answer. The leak rate is not measured at zero — it is unable to be
non-zero along this path.

Two honest limits travel with that:

* **It guards a code path, not a product.** Track B's generation service must
  route through `validate()`. A model whose output reaches a UI without passing
  it is outside the guarantee, which is why the validator returns a
  `ValidatedAnswer` rather than mutating a string in place — a caller cannot
  accidentally skip it and still have something to render.
* **It is a claim about citations, not about truth.** A cited number can still
  be wrong, if the citation is to a superseded circular (LH-608) or the
  retrieval was poisoned. That is what the faithfulness scorer and effective-date
  filtering are for, and neither is measurable here.

## Findings

Nine findings were raised while building, in
[Phase_5_FINDINGS.md](../../Lending_Hub_Phase_Docs/Phase_5_FINDINGS.md). Six
carry a new ticket; the other three carry none because there is nothing for a
committee to rule on — a deliberate deviation on table chunking (P5-F1), a scope
note that ratifying LH-203 does not unblock LH-603 (P5-F8), and the boundary
that has to travel with the leak-rate guarantee (P5-F9).

Six of the twelve open tickets were **found by building** — LH-606
(conversational PII is not schema PII), LH-607 (an injection defence with no
stated response), LH-608 (partial supersession, which effective dates cannot
express), LH-610 (a language slice with no minimum size), LH-611 (tool-sourced
numbers versus document-sourced numbers), and LH-609 (whether a Track P is
wanted at all).

`make gate5` assembles the pack.

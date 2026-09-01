# ADR-0015 — Phase 5 without a corpus, a golden set, or a model

| Field | Value |
|---|---|
| Status | Accepted (Track A scope) · Blocked (Track P and Track B scope) |
| Date | 2026-09-02 |
| Decider | GenAI Lead (Track A) · Model Risk (Track B) |
| Workstream | WS-5.1, WS-5.2, WS-5.3, WS-5.4 |
| Consulted | Compliance (A on language), Product SMEs (corpus owners), Security (red team), DPO |
| Related | [ADR-0003](0003-two-track-execution-model.md), [ADR-0004](0004-public-reference-data-track.md), [ADR-0013](0013-phase2-agri-track.md), [ADR-0014](0014-phase4-action-systems-track.md) |

## Context

Phase 5 ships a retrieval-augmented assistant. Its governing contract is Master
§2 rule 7 — *LLM outputs are never facts* — and the phase file makes that the
design centre rather than a caveat.

Four things Phase 5 needs are absent from this repository, and they are absent
for four *different* reasons. Collapsing them into one word ("blocked") is what
ADR-0013 did for Phase 2, and it had to be amended (see
[phase2/DATA_SOURCING](../phase2/DATA_SOURCING.md)) because one of its three
"categorically unsatisfiable" blockers turned out to have a licensed public
dataset behind it. So each is separated here.

1. **No corpus.** WS-5.1 wants the bank's policy circulars, rate sheets, KFS
   templates and product FAQs, each with an owner and an effective date. None
   exists here, and unlike Phase 2's imagery there is no useful substitute:
   another bank's circular is not a noisy version of this bank's, it is a
   different policy that produces a confidently wrong answer with a citation
   attached. The citation is what makes the substitution dangerous — a wrong
   number sourced to a real-looking document is harder to catch than a wrong
   number with no source at all.
2. **No golden set.** WS-5.1.3 wants ≥ 500 question → answer → source-passage
   triples curated by product SMEs. This is `[DATA]` produced by people, not
   found in a dataset. It is derivative of (1): a triple's *answer* is only
   correct relative to a corpus, so a golden set cannot precede the corpus it
   measures retrieval against.
3. **No LLM.** ADR-0003 makes the core packages stdlib-only, and no model
   weights or API credentials are present. This one is a *deliberate* absence
   rather than a missing input — see the Decision below.
4. **No approved templates.** WS-5.3.3 requires legal-approved adverse-action
   sentences per language, `[POLICY: Compliance]`. These are the same sentences
   Phase 1 has been waiting on since LH-203; Phase 5 is where the absence stops
   being a rendering problem and becomes a product one.

But — and this is where Phase 5 differs sharply from Phase 2 — **most of what
this phase actually specifies is deterministic code that needs none of the
four.**

## Decision

**Build Phase 5 on Track A. Call no LLM anywhere, generate no corpus document,
and author no golden-set triple. Report the deterministic layer as tested and
the generative layer as structurally unmeasurable, and keep the two apart in
every report.**

### What is exact, and is therefore built and tested in full

These are not approximations of a Phase 5 component; they are the component.

| Component | Why it is exact |
|---|---|
| **Effective-date filtering** (`assistant.registry`) | A date comparison against a document's `effective_from`/`effective_to`. Given a corpus and an as-of date, the set of servable documents is determined. Ingestion refusing an undated document is a type invariant, not a heuristic |
| **BM25** (`assistant.retrieval`) | Robertson & Zaragoza's saturating term-frequency score is a closed-form function of the index. Its ranking on a given corpus is reproducible to the last digit, and a test can pin it against hand-computed values |
| **Reciprocal-rank fusion** (`assistant.retrieval`) | `Σ 1/(k + rank)` over input rankings. Arithmetic |
| **The numeric-claim validator** (`assistant.answer`) | The phase file is explicit that this is deterministic code and **not** another LLM. Whether a sentence contains a numeric claim and whether that claim carries a resolvable citation is a parsing question with a right answer on every input. This is the single most testable thing in the phase and the single most important |
| **Structure-aware chunking** (`assistant.chunking`) | Given a document and a token budget, the chunk boundaries are determined by the document's own structure |
| **Tool schema validation** (`assistant.tools`) | JSON-schema validation and allow-list membership are decidable |
| **Topic fences, refusal library, injection scanning, PII redaction** (`assistant.guardrails`) | Pattern and policy evaluation over text. The *coverage* of the patterns is an open empirical question; whether a given pattern fires is not |
| **Faithfulness decomposition and the suppression path** (`assistant.faithfulness`) | The claim-extraction and support-checking *mechanics*, and the rule that a below-threshold answer is suppressed rather than shown, are exact. The **threshold** is `[SPEC]` at 97% from Phase 5 §7; the *entailment judgement* inside is not, and is a port boundary |

That list covers seven of the ten Phase 5 §6 deliverables at least in part. It
is a materially larger fraction of the phase than Phase 2's equivalent, and
saying so is the point of this ADR: Phase 5 is *not* a second Phase 2.

### What is structurally unmeasurable here

| Exit criterion (Phase 5 §7) | Why no data reachable from here produces it |
|---|---|
| Retrieval hit-rate@5 ≥ 95% | Hit-rate is defined *on the golden set*, against *the corpus*. Neither exists (LH-601, LH-602). The metric function is implemented and tested against hand-built cases; the number it would compute has no inputs |
| Answer faithfulness ≥ 97% | Requires generated answers, which requires a model (LH-604) and a corpus |
| Uncited-numeric leak rate = 0 | Requires a weekly audit of real sessions. **But see below** — the property the audit measures is enforced structurally, which is a stronger statement than a measured zero, and a different one |
| Containment ≥ `[POLICY: target]`, correct-escalation ≥ 95% | The target itself is unratified (LH-605) and containment is measured on live sessions |
| Red-team sign-off current | Requires a security function and a deployed system. The three suites are built as executable tests; the sign-off is a human act |
| Compliance sign-off on KFS/disclosure behavior | A human act by a function that does not exist here |

### The one criterion that is stronger than "not measurable"

Phase 5 §7 makes **uncited-numeric leak rate = 0** a hard gate, measured in
weekly audits. An audit is a sampling procedure: it can establish that the rate
is low, never that it is zero.

This repository takes the other route. `ValidatedAnswer` cannot be constructed
holding an uncited numeric claim — the validator strips such sentences before
the answer object exists, and an answer whose numeric content was entirely
stripped becomes a handoff rather than a thinner answer. So the leak rate is
zero **by construction of the type**, in the same way Phase 4's propensity
completeness is 100% by construction of `BanditDecision`.

That is not gate evidence and this ADR does not claim it is: a structural
guarantee holds only over the code path it guards, and Track B's real generation
service must route through it. What it *is* is the correct shape for this
property. A leak rate measured at zero over a sample is a claim about last week;
a leak rate that cannot be non-zero is a claim about the program.

### Why no LLM is called, even though one could be

This is the decision most likely to be second-guessed, so it is argued rather
than asserted. A model could be bound behind `assistant.ports` and prompted with
a fabricated corpus, and the result would demo well.

It would establish nothing, and it would establish nothing in a way that *looks*
like evidence:

* **A faithfulness number over a fabricated corpus measures the fabricator.**
  The same failure ADR-0014 refused for Phase 4's collections desk, and worse
  here: the corpus author, the golden-set author and the retrieval author would
  be the same person, so the assistant would score well exactly to the extent
  that the questions were written against documents written to answer them.
* **A generated adverse-action sentence is a compliance artifact.** Phase 5 §8
  puts adverse-action sentences on the do-not-invent list and SRS GA-3 forbids
  the assistant composing them at all. A sample sentence produced "just for a
  test" has the same shape as an approved one and outlives the test.
* **A fabricated rate sheet is the exact failure the phase is built to prevent.**
  Stale-rate poisoning is named as the #1 RAG failure in banks. A synthetic rate
  circular sitting in a repository whose grounding checker exists to stop
  invented numbers is a contradiction that a future reader resolves in the wrong
  direction.

Test fixtures are a different matter and are used freely: `tests/fixtures/` is
where Master §2 rule 3 puts synthetic data, and a fixture corpus of obviously
fictional documents with obviously fictional numbers is how the deterministic
layer is exercised. The line is that no fixture document is ever servable
outside a test, and no metric computed on one is ever reported as a Phase 5
number.

## Why there is no Track P

Unlike Phase 2, this was checked rather than assumed, and the answer is that the
substitutes that exist test the *wrong property*.

Public RAG benchmarks exist in quantity — BEIR, MS MARCO, Natural Questions,
FiQA for finance, and RBI's own circulars and FAQs are public documents. Any of
them could be indexed and a hit-rate@5 computed. That number would be a fact
about BM25 on English open-domain text, and Phase 5's retrieval gate is not
about BM25's general quality:

* **The gate is corpus-specific by construction.** Hit-rate@5 ≥ 95% is a
  statement about *this bank's* documents answering *this bank's* customers'
  questions. A 95% on FiQA and an 80% on the bank's KFS templates are both
  possible simultaneously, and only the second decides whether the assistant
  ships.
* **The failure mode the phase names is not a retrieval-quality failure.**
  Stale-rate poisoning happens when retrieval succeeds — it returns exactly the
  right passage from last quarter's circular. No public benchmark has an
  effective-date structure to reproduce that, because no public benchmark's
  documents supersede each other.
* **The exact-token argument cuts the same way.** Hybrid retrieval is mandatory
  because "KCC" and "MCLR" are tokens dense retrieval fumbles. Demonstrating
  that on a corpus containing neither token demonstrates nothing.

So BM25 is tested the way a port is tested (ADR-0003, CONTRIBUTING "Porting a
library"): against hand-computed scores and against the ranking properties a
Track B swap to Elasticsearch or Vespa must preserve. That is a stronger
guarantee for this repository's purpose than a benchmark number, because it is
the property Track B inherits.

**If a Track P is ever wanted**, the cheapest honest one is RBI's own published
Master Directions and FAQs: real financial-regulatory prose, real supersession
chains with effective dates, real exact tokens. It would exercise chunking and
effective-date filtering on documents with genuine structure. It would still
produce no hit-rate number, because there is no question set. Raised as LH-609
rather than done, because sourcing it is a decision about scope rather than an
afternoon's work, and because the phase's gate does not move either way.

## What this genuinely establishes

* **An uncited numeric claim cannot reach a user through this code.** The
  validator is exact, adversarially tested, and sits inside the type rather than
  beside it.
* **An undated document cannot enter the index**, and an expired one cannot be
  retrieved by default. Both are constructor and query invariants.
* **LLM arithmetic is structurally impossible** for EMI: `compute_emi` delegates
  to `lending_hub.reco.feasible.emi`, the one reference implementation (Master
  §2 rule 2), and the tool layer is the only path to a number.
* **The assistant cannot compose an adverse-action sentence**, because there is
  no code path that produces decision-explanation prose — only template
  selection, and every template renders from `config/reason_codes.yaml`, which
  is unratified and therefore raises.
* **Retrieved chunks are untrusted input** by type, not by convention.
* **The golden-set harness exists ahead of the golden set**, so the set arrives
  into a measuring instrument rather than the other way round.

## Consequences

* Phase 5's gate pack reports **six exit criteria, none with Track B evidence**,
  and — like Phase 4 — uses more than one "unmeasured" column. Unlike Phase 4 it
  has no Track P column at all, and unlike Phase 2 it has a substantial
  **structurally-guaranteed** column, which is new.
* `docs/phase5/model_cards/` contains cards for components that are not
  statistical models (a retriever, a validator). Master §2 rule 5 says every
  model ships with its card; a retrieval configuration decides which document a
  customer is answered from, which is a model-risk surface whatever it is called.
* A Track B team receives a complete, tested deterministic spine with the LLM,
  the embedder, the vector store and the reranker as four unbound ports — and a
  numeric-claim validator that will strip its model's output without asking.

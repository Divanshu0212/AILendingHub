"""GenAI loan assistant — corpus, retrieval, constrained generation, guardrails.

Phase 5 Workstream 5.1-5.4 (SRS §8). The assistant answers customer and officer
questions about loans, and its governing contract is Master §2 rule 7: **LLM
outputs are never facts.**

That rule is the whole design here, not a caveat attached to it. Every phase
before this one built systems whose outputs were wrong in *measurable* ways — a
miscalibrated PD, a signal with poor precision. A language model is wrong in a
different way: fluently, with the same surface form as being right, and in a
customer's own language. So the defences cannot be quality thresholds on the
output. They have to be structural.

Three of them are, and they are the package's reason for existing.

**A numeric claim without a resolvable citation cannot reach a user.**
:class:`~lending_hub.assistant.answer.ValidatedAnswer` cannot be constructed
holding one; the validator strips the sentence before the object exists, and an
answer stripped of all its numeric content becomes a handoff rather than a
thinner answer. Phase 5 §7 makes the leak rate a hard gate measured by weekly
audit — a sample can show a rate is low, never that it is zero. This shows it
cannot be non-zero along this path, which is the same shape as Phase 4's
propensity completeness.

**An undated document cannot be indexed, and an expired one cannot be
retrieved.** Stale-rate poisoning is the failure mode the SRS names first, and
it is nastier than a retrieval miss because retrieval *succeeded* — it returned
exactly the right passage from last quarter's circular. So the effective-date
filter is the default rather than an option, and turning it off is an explicit,
recorded act.

**The assistant cannot compose a decision-explanation sentence.** SRS GA-3 and
Phase 5 §4 allow selecting and ordering pre-approved templates and nothing else.
There is no code path in this package that produces adverse-action prose.

**No LLM is called anywhere in this package.** Every model seam — generation,
embedding, vector search, reranking — is a protocol in
:mod:`~lending_hub.assistant.ports` that Track B binds. Nothing here fabricates
a corpus document, a golden-set triple or a generated answer either; the reasons
are argued in [ADR-0015](../../../docs/adr/0015-phase5-assistant-track.md), and
the short version is that a faithfulness number computed over a corpus written
by the same person who wrote the questions measures the author.

Workstream: WS-5.1-5.4 (SRS §8)
"""

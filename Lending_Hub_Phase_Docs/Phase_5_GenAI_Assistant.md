# Phase 5 — GenAI Loan Assistant (RAG)

| Phase card | |
|---|---|
| Duration | Months 8–11 (parallel track from P3) |
| SRS modules | §8 (GenAI loan assistant) |
| Depends on | Phase 0 (platform); Phase 1 (status APIs, reason codes) |
| Unblocks | P6 continuous-improvement loop on assistant quality |
| Squads | GenAI (R), Compliance (A on language/disclosures), Product SMEs (corpus owners), Security (red team) |
| Governing contract | `00_MASTER_Implementation_Guide.md` §2–§4 — binding; rule 7 (LLM outputs are never facts) is the design center of this phase |

**Objective.** Ship the retrieval-augmented loan assistant — officer-facing first, then customer-facing — engineered so it **cannot state an ungrounded banking fact**: every number comes from a retrieved, currently-effective document or a tool computation; adverse-action language comes only from legal-approved templates; everything else is refused or escalated to a human.

**Architecture note (common confusion, settled here):** RAG involves two data footprints. The base LLM's pretraining corpus gives it language ability and is *not* retrained by the bank. What the assistant *answers from* is the **retrieval index the bank builds** — its own policies, rate circulars, KFS templates, FAQs. Documents are indexed (embedded), not trained into weights, so the corpus can change daily with no retraining. Reference: [Lewis et al., NeurIPS 2020, arXiv:2005.11401](https://arxiv.org/abs/2005.11401).

---

## 2. Position in the program

**Inputs:** P0 platform; P1 orchestrator APIs (`application status`, reason codes); document corpus from product/compliance owners; legal-approved explanation templates `[POLICY: Compliance]`.

**Outputs:** customer/officer assistant; conversation logs (PII-redacted) for quality loops; escalation stream into human channels.

---

## 3. Entry criteria

- Corpus owners named per document family; legal templates for decision explanations approved.
- Status/EMI/checklist APIs available from the P1 orchestrator.
- Red-team plan approved by Security; hallucination-audit staffing committed (2% of sessions weekly).

---

## 4. Workstreams

### WS-5.1 Corpus before model

1. **Corpus governance first.** Document registry: every policy circular, rate sheet, KFS template, FAQ gets `{owner, effective-from, effective-to, version, product tags}`. **Ingestion refuses undated documents.** Retrieval filters to currently-effective documents by default — stale-rate poisoning is the #1 RAG failure in banks (SRS §8.3.1).
2. **Chunking.** Structure-aware: headings respected, tables kept intact; 300–800 tokens per chunk; chunk metadata inherits registry fields.
3. **Golden set before pipeline.** ≥ 500 question → answer → source-passage triples curated by product SMEs, covering each product, each language, and known tricky cases (fee edge cases, eligibility boundaries). This set is the phase's measuring stick; it is versioned and refreshed quarterly.

### WS-5.2 Retrieval

Hybrid retrieval (SRS §8.3.1): **BM25** ([Robertson & Zaragoza, 2009](https://www.staff.city.ac.uk/~sbrp622/papers/foundations_bm25_review.pdf)) + dense embeddings, merged with reciprocal-rank fusion, then a cross-encoder reranker. Hybrid is mandatory: banking queries carry exact tokens (product codes, "KCC", "MCLR") that dense retrieval alone fumbles.
**Gate before generation work is graded:** hit-rate@5 ≥ 95% on the golden set.

### WS-5.3 Constrained generation

1. **Answer contract.** Output schema: every factual sentence carries a citation id resolving to a retrieved chunk; numeric values must come from a citation or a tool call. A **post-generation validator** parses each answer and **drops any uncited numeric claim** — the user then sees a handoff message, never an uncited answer. This validator is deterministic code, not another LLM.
2. **Tools, not arithmetic.** Allow-listed, JSON-schema-validated functions only (ReAct-style loop, [Yao et al., arXiv:2210.03629](https://arxiv.org/abs/2210.03629)): `compute_emi(p,r,n)`, `get_application_status(id)`, `get_document_checklist(product)`, `book_branch_slot(...)`. All read-only or workflow-safe. **LLM arithmetic is forbidden** — EMIs and eligibility amounts always come from tools.
3. **Templated adverse-action language.** The assistant explains decisions only by selecting and ordering pre-approved templates keyed to P1 reason codes `[POLICY: Compliance]`, per language. It never composes new decision-explanation sentences (SRS GA-3).
4. **Multilingual.** Language detection → per-language prompt + template set. Each language has its own golden-set slice; a language ships only when its slice passes the same gates as English.

### WS-5.4 Guardrails & safety

- Policy-rails layer (NeMo Guardrails-class, [arXiv:2310.10501](https://arxiv.org/abs/2310.10501)): topic fences (no investment/tax advice, no rate negotiation), refusal library, human-handoff intent detection.
- **Injection defense:** user input *and retrieved chunks* are untrusted data ([Greshake et al., arXiv:2302.12173](https://arxiv.org/abs/2302.12173)); instruction/data separation in prompts; tool calls outside the allow-list denied; per-session rate limits.
- **PII redaction before logging**; conversation logs retained per DPDP config `[POLICY: DPO]`.
- **Faithfulness scoring** on every answer (RAGAS-style groundedness, [arXiv:2309.15217](https://arxiv.org/abs/2309.15217)); below-threshold answers suppressed automatically; 2% weekly human hallucination audit feeding fixes to prompts/retrieval/corpus.

---

## 5. Shipping ladder

1. **Officer-facing beta** — 50 users, 6 weeks. Officers can spot wrong policy answers; customers cannot. Their corrections are triaged into corpus fixes vs. retrieval fixes vs. prompt fixes.
2. **Red-team pass** — injection suite, jailbreak suite, PII-leak suite. **Rerun on every model or prompt change** (a standing CI job, not a one-time event).
3. **Customer-facing** — 2 products, 2 languages first; expand product-by-product, language-by-language, each behind its golden-set gate.
4. **Steady state** — weekly hallucination audits; quarterly golden-set refresh; corpus registry compliance monitored (no undated/expired documents servable).

## 6. Deliverables checklist

- [ ] Document registry + dated-corpus ingestion with effective-date filtering
- [ ] Chunking pipeline; golden set v1 (≥ 500 triples, per-language slices)
- [ ] Hybrid retrieval + reranker; hit-rate@5 report
- [ ] Generation service with citation contract + deterministic numeric-claim validator
- [ ] Tool layer (4 launch tools) with schema validation + rate limits
- [ ] Adverse-action template library (per language) wired to P1 reason codes
- [ ] Guardrails layer; injection/jailbreak/PII red-team suites in CI
- [ ] Faithfulness scorer + suppression path + weekly audit process
- [ ] Officer beta report; escalation flow to human channels
- [ ] DPDP/RBI-KFS compliance review memo

## 7. Exit criteria (gate review)

Golden set: retrieval hit-rate@5 ≥ 95% · answer faithfulness ≥ 97% · **uncited-numeric leak rate = 0** in weekly audits (hard gate) · containment ≥ `[POLICY: target]` with correct-escalation ≥ 95% · red-team sign-off current · Compliance sign-off on KFS/disclosure behavior.

## 8. Do-not-invent list (P5)

Rates, fees, charges (retrieval/tool-only — never generated) · adverse-action sentences (templates-only) · eligibility rules (retrieval-only) · containment targets · retention periods for logs · any answer where retrieval returned nothing (refuse + escalate, never improvise). All `[POLICY]` or grounded.

## 9. References for this phase

- Lewis et al. — *Retrieval-Augmented Generation* — [arXiv:2005.11401](https://arxiv.org/abs/2005.11401)
- Yao et al. — *ReAct* — [arXiv:2210.03629](https://arxiv.org/abs/2210.03629)
- Rebedea et al. — *NeMo Guardrails* — [arXiv:2310.10501](https://arxiv.org/abs/2310.10501)
- Es et al. — *RAGAS* — [arXiv:2309.15217](https://arxiv.org/abs/2309.15217)
- Greshake et al. — indirect prompt injection — [arXiv:2302.12173](https://arxiv.org/abs/2302.12173)
- Robertson & Zaragoza — *BM25* — [PDF](https://www.staff.city.ac.uk/~sbrp622/papers/foundations_bm25_review.pdf)
- RBI Digital Lending Directions 2025 (KFS/disclosure duties) — [overview](https://www.argus-p.com/updates/updates/rbi-digital-lending-directions-2025-an-overview/)

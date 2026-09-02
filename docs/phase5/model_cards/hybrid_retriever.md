# Model Card — Hybrid retriever (SRS §8.3.1)

> **This card documents a retriever that has never been evaluated**, and that is
> the correct state rather than an incomplete one. Its gate metric —
> hit-rate@5 ≥ 95% — is defined on a golden set (LH-602) against a corpus
> (LH-601), and neither exists. Master §2 rule 5 requires a card regardless, and
> the card is where the reason belongs.
>
> It is also a card for something not usually called a model. A retrieval
> configuration decides **which document a customer is answered from**, which is
> a model-risk surface whatever it is named — and unlike a scorecard, it has no
> AUC that would make its absence obvious.

## 1. Identification

| Field | Value |
|---|---|
| Name / version | `assistant.retrieval.HybridRetriever` v0.1.0 — **never evaluated** |
| Components | `BM25Index` (lexical) · `DenseRetriever` (unbound) · `fuse` (RRF) · `Reranker` (unbound) |
| References | Robertson & Zaragoza 2009 (BM25) · Cormack, Clarke & Buettcher, SIGIR 2009 (RRF) · Lewis et al., NeurIPS 2020 (RAG) |
| Registry stage | None |
| Model tier | Tier 1 — it decides the evidence every answer is grounded in |
| Owner (accountable) | GenAI squad lead |
| Independent validator | **Not assigned** (Master §3.1) |

## 2. Reproducibility

| Field | Value |
|---|---|
| Lexical leg | Fully deterministic. `k1=1.2`, `b=0.75` — the paper's recommended values and every mainstream implementation's default. Ties broken by chunk id, so the top-5 is stable and a hit-rate over it is reproducible |
| Fusion | Deterministic. `RRF_K=60`, Cormack et al.'s published value, not tuned here |
| Dense leg | **Unbound** (LH-604). Reproducibility depends on the bound model's version pinning |
| Reranker | **Unbound** (LH-604) |
| Corpus | **Absent** (LH-601) |

## 3. Purpose and scope

Returns the top-k currently-effective chunks for a query, fusing a lexical and a
dense ranking and optionally reranking with a cross-encoder.

**Hybrid is mandatory, and the reason is specific.** Phase 5 §4 WS-5.2: banking
queries carry exact tokens — "KCC", "MCLR", product codes — that dense retrieval
fumbles. The failure is not a miss. An embedding model places "KCC" near
"agricultural credit" and "farm loan", which is *correct semantics and the wrong
document*: the customer gets the general agri circular and a fluent, cited answer
about a different product. BM25 cannot make that error, because a rare term has
a high IDF and the document containing it wins on the term itself.

So the lexical leg is not the fallback. It carries the query shape a bank gets
most of, and `fuse()` requires it while treating the dense leg as optional —
the reverse of the usual framing.

**It must not be used for**: any claim about retrieval quality, since none has
been measured; or with the effective-date filter disabled, which is what
`BM25Index.search`'s permissive `as_of` default allows and
`HybridRetriever.retrieve`'s required argument prevents.

## 4. The port, and where it deviates

`BM25Index` is a full port of Okapi BM25 and is pinned against hand-computed
scores — CONTRIBUTING's "test properties, not numbers" does not apply to an
algorithm whose value a paper defines.

**Not ported:** inverted-index compression, skip lists, WAND or block-max
pruning, positional indexing and therefore phrase queries. Scoring is a linear
pass over the query terms' postings — fine at the thousands of chunks a bank's
policy library reaches, and not at web scale.

**One deviation from a library default, stated per CONTRIBUTING.** The older
Robertson-Zaragoza IDF form goes negative for a term appearing in more than half
the corpus. On a policy corpus "loan" is in every document, so that form would
*subtract* score from every document containing the word — ranking documents
about loans below documents that never mention them. This port uses the `+1`
form (which Lucene also adopted), keeping IDF non-negative. The deviation
inverts the ranking for the commonest query shape a bank receives, which is why
it is a correctness fix rather than a preference.

**Two tokenizer choices** that a default tokenizer gets wrong here, both found
by testing rather than by reading:

* A slash splits and a hyphen does not. "KCC/MCLR" must be two terms or neither
  is findable; "non-agri" must be one, because splitting yields "agri" and
  inverts the query's meaning.
* Combining marks are part of a word. Devanagari matras are Unicode `Mn`/`Mc`
  and not word characters, so the obvious pattern shreds "किसान" into five
  one-character terms. The failure is **silent** — every query shreds the same
  way, so Hindi retrieval is merely bad and reads as a weak embedding model. SRS
  GA-4 requires Hindi plus two regional languages.

## 5. The stale-rate defence

SRS §8.3.1 names stale-rate poisoning as the #1 RAG failure in banks, and it is
this component's most important behaviour because it is a failure of *success*:
retrieval returns exactly the right passage from last quarter's circular.

* `HybridRetriever.retrieve` takes a required `as_of` with no default. A default
  of "today" would make every replay of a stored conversation a re-answer
  against a corpus that has moved (Master §3.3 requires eight years of them).
* Chunks answer `is_effective_on` themselves rather than consulting a registry,
  so a chunk cannot be served because the registry was unavailable — which is
  exactly when nobody is watching.
* Effective-date bounds are inclusive at both ends. The half-open convention
  correct for timestamps loses or duplicates one day at every rate change: the
  day two rates are simultaneously quotable.

**What it cannot defend against is LH-608.** Two circulars effective at once,
the later amending the earlier in part. Both pass the date filter, correctly —
the earlier one's unamended clauses are still policy — and nothing in
`{effective_from, effective_to}` says which passage won.
`DocumentRegistry.conflicts()` surfaces the pairs and refuses to rule on them.

## 6. Known limitations

* **No evaluation of any kind.** No hit-rate, no MRR, no nDCG. The metric and
  its admission gate are implemented and tested; the number has no inputs.
* **Degradation is reported, not prevented.** With no dense leg bound, every
  result carries `degraded=True` and the reason. A silent degradation would make
  "hybrid is mandatory" satisfiable by omission.
* **No stemming or per-language analysis.** On a policy corpus stemming merges
  "waived"/"waiver" helpfully and "secured"/"security" harmfully — and the
  second moves a collateral question onto an information-security circular. A
  Track B swap to Elasticsearch brings real per-language analyzers; this does
  not pretend to have them.
* **`candidate_k` defaults to 4×k** and is untuned, because tuning it needs the
  golden set.

## 7. Monitoring

| Signal | Why |
|---|---|
| Share of results that are `degraded` | Should be zero once a dense leg is bound; anything else is a silent halving of the retriever |
| Queries returning nothing | Feeds the refusal path (Phase 5 §8). A rise is a corpus-coverage problem, not a retrieval one |
| `DocumentRegistry.conflicts()` count | The LH-608 surface. A rise means live policy ambiguity, and it is a Compliance queue rather than an engineering one |
| Expired-document retrieval attempts | Must be zero. Any non-zero is a filter bypass, and stale-rate poisoning is the outcome |
| Per-language hit-rate, once measurable | The Hindi tokenizer gap above surfaces here first |

## 8. Sign-off

| Field | Value |
|---|---|
| Developer | GenAI squad |
| Independent validation | **Not performed** — no validator assigned (Master §3.1) |
| Model Risk decision | **Not sought** — there is nothing to review; no metric exists |
| Compliance | **Not sought** |

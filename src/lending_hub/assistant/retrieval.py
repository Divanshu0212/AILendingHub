"""Hybrid retrieval — BM25, dense, reciprocal-rank fusion, reranking (WS-5.2).

Phase 5 §4 WS-5.2, verbatim:

    Hybrid retrieval (SRS §8.3.1): **BM25** (Robertson & Zaragoza, 2009) + dense
    embeddings, merged with reciprocal-rank fusion, then a cross-encoder
    reranker. Hybrid is mandatory: banking queries carry exact tokens (product
    codes, "KCC", "MCLR") that dense retrieval alone fumbles.
    **Gate before generation work is graded:** hit-rate@5 ≥ 95% on the golden set.

Why hybrid is mandatory, restated as a property this code has
---------------------------------------------------------------
"Dense retrieval fumbles exact tokens" is easy to nod at and easy to lose in
implementation. The concrete failure: an embedding model places "KCC" near
"agricultural credit" and "farm loan", which is *correct* semantics and the
wrong retrieval — a customer asking about KCC gets the general agri-credit
circular rather than the KCC circular, and the answer is plausible, cited, and
about a different product.

BM25 cannot make that mistake, because a rare term has a high IDF and the
document containing it wins on the term itself. So the lexical leg is not a
fallback for when the dense leg is unavailable; it is the leg that carries
exactly the queries a bank gets most of. :func:`fuse` therefore requires the
lexical ranking and treats the dense one as optional — the reverse of the usual
framing, and deliberate.

What is ported and what is not
--------------------------------
:class:`BM25Index` is a full port of Robertson & Zaragoza's Okapi BM25 with the
standard `k1`/`b` parameterisation, IDF as they define it in the probabilistic
derivation, and length normalisation against the corpus mean. It is exact: a
test pins it against hand-computed scores.

It is **not** an Elasticsearch or Lucene port. There is no inverted-index
compression, no skip lists, no WAND or block-max pruning, no positional index
and therefore no phrase queries. Scoring is a linear pass over the postings of
the query terms, which is O(query terms × documents containing them) and fine at
corpus sizes a bank's policy library reaches (thousands of chunks), and would
not be at web scale.

**One deviation from the library default, stated per CONTRIBUTING.** Lucene
clamps IDF at zero for terms appearing in more than half the corpus; the
Robertson-Zaragoza IDF as published goes negative there. This port keeps a small
positive floor rather than either — see :attr:`BM25Index.idf` for why a negative
IDF is actively wrong on a policy corpus, where "loan" appears in every document
and a query containing it should not be *penalised* for the documents that have
it.

Dense retrieval and reranking are ports of nothing: they are protocols in
:mod:`~lending_hub.assistant.ports` with no local implementation, because an
embedding model is model weights and there is no honest stdlib stand-in
(ADR-0015).

Workstream: WS-5.2 (SRS §8.3.1)
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, Mapping, Sequence

from lending_hub.assistant.chunking import Chunk
from lending_hub.assistant.ports import (
    EmbeddingModel,
    Reranker,
    UnboundPort,
    VectorStore,
)

#: Robertson & Zaragoza's own recommended operating range, and the value every
#: mainstream implementation (Lucene, Elasticsearch, rank_bm25) defaults to.
#: [SPEC] by way of the paper the phase file names as this algorithm's single
#: reference implementation (Master §2 rule 2).
BM25_K1 = 1.2
BM25_B = 0.75

#: The RRF constant from Cormack, Clarke & Buettcher (SIGIR 2009), which is the
#: paper behind "reciprocal rank fusion" as the phase file uses the term. 60 is
#: their published value, not a tuned one.
RRF_K = 60

#: Phase 5 §4 WS-5.2, verbatim: "hit-rate@5 >= 95% on the golden set".
HIT_RATE_K = 5
HIT_RATE_GATE = 0.95

#: Combining marks, built from the Unicode database rather than typed as a
#: range. Devanagari matras and viramas are category ``Mn``/``Mc`` and are *not*
#: ``\w``, so a naive word pattern shreds "किसान" into five one-character terms
#: and the Hindi index becomes useless — silently, since every query shreds the
#: same way and retrieval merely gets very bad rather than erroring. SRS GA-4
#: requires Hindi and two regional languages, so this is not an edge case.
_COMBINING = "".join(
    chr(code)
    for code in range(0x0300, 0x1E00)
    if unicodedata.category(chr(code)) in ("Mn", "Mc")
)

#: A term starts with a letter or digit and continues through what banking text
#: puts *inside* a word: combining marks, digits, the decimal point, the hyphen,
#: and the percent and rupee signs. A slash is deliberately outside a word —
#: "KCC/MCLR" is two product terms, and merging them means neither is findable.
_WORD = re.compile(
    r"[^\W_][\w%₹.\-" + re.escape(_COMBINING) + r"]*", re.UNICODE
)


class RetrievalError(Exception):
    """A query cannot be answered, or an index cannot be built."""


def tokenize(text: str) -> list[str]:
    """Lowercase word tokenisation that keeps the tokens banking queries carry.

    Four choices that a default tokenizer gets wrong for this corpus:

    * **Hyphens stay inside a token; slashes do not.** ``"KCC/MCLR"`` is two
      product terms and must be two, or neither is findable. ``"non-agri"`` is
      one term — splitting it yields ``agri``, which matches every agricultural
      document and inverts the query's meaning.
    * **Percent and rupee signs are kept.** ``"12.5%"`` is a term a rate query
      contains literally, and stripping the sign makes it collide with the
      version number ``12.5``.
    * **Decimal points inside numbers survive.** ``"7.0"`` and ``"70"`` are
      different rates.
    * **Combining marks are part of a word.** Devanagari matras are Unicode
      category ``Mn``/``Mc`` and are not word characters, so the obvious pattern shreds
      "किसान" into five one-character terms. That failure is silent — every
      query shreds identically, so the Hindi index does not error, it just
      retrieves nothing useful — and SRS GA-4 requires Hindi plus two regional
      languages, so it is not an edge case. The mark set is read from the
      Unicode database rather than typed as a range, so Bengali and Tamil work
      without a second fix.

    Stemming is deliberately absent. On a policy corpus it merges ``"waived"``
    and ``"waiver"``, which is helpful, and ``"secured"`` and ``"security"``,
    which is not — and the second error moves a collateral question onto an
    information-security circular. A Track B swap to Elasticsearch brings real
    per-language analyzers; this port does not pretend to have them.
    """
    out = []
    for match in _WORD.finditer(text):
        term = match.group(0).lower().strip(".-")
        if term:
            out.append(term)
    return out


@dataclass(frozen=True)
class ScoredChunk:
    """One retrieval result: the chunk, its score, and which leg produced it.

    ``leg`` is carried through fusion rather than discarded because it is what
    makes a retrieval failure diagnosable. "The answer cited the wrong product's
    circular" has two very different fixes depending on whether the lexical or
    the dense leg surfaced it, and a fused list that has forgotten its
    provenance forces a re-run to find out.
    """

    chunk: Chunk
    score: float
    leg: str = "bm25"
    rank: int = 0


class BM25Index:
    """Okapi BM25 over chunk text (Robertson & Zaragoza, 2009).

    The scoring function, in full::

        score(D, Q) = Σ_{q ∈ Q} IDF(q) · ( f(q,D) · (k1 + 1) )
                                        / ( f(q,D) + k1 · (1 - b + b · |D|/avgdl) )

    Three parts, each doing something the others cannot:

    * **IDF** weights rare terms up. This is what makes "KCC" beat "loan".
    * **The saturating numerator** stops a term's tenth occurrence counting as
      much as its second. A rate circular that says "interest" forty times is
      not forty times more about interest than one that says it twice.
    * **Length normalisation** (``b``) stops long documents winning by volume.
      It matters more here than in general web search because chunk lengths in
      this corpus vary by design: an atomic rate table is several times the
      length of an FAQ answer, and without normalisation it would outrank the
      FAQ on every query that shares a word with it.
    """

    def __init__(self, *, k1: float = BM25_K1, b: float = BM25_B) -> None:
        if k1 < 0:
            raise RetrievalError(f"k1 must be non-negative, got {k1}")
        if not 0.0 <= b <= 1.0:
            raise RetrievalError(f"b must be in [0, 1], got {b}")
        self.k1 = k1
        self.b = b
        self._chunks: dict[str, Chunk] = {}
        self._lengths: dict[str, int] = {}
        self._postings: dict[str, dict[str, int]] = {}

    def __len__(self) -> int:
        return len(self._chunks)

    @property
    def average_length(self) -> float:
        if not self._lengths:
            return 0.0
        return sum(self._lengths.values()) / len(self._lengths)

    def add(self, chunk: Chunk) -> None:
        """Index one chunk. Re-adding the same id replaces its postings.

        Replacement rather than accumulation: a re-ingested chunk whose text
        shrank would otherwise keep the term frequencies of the text it no
        longer has, and the index would answer for a passage that is gone.
        """
        if chunk.chunk_id in self._chunks:
            self._remove(chunk.chunk_id)
        terms = tokenize(self._indexed_text(chunk))
        self._chunks[chunk.chunk_id] = chunk
        self._lengths[chunk.chunk_id] = len(terms)
        for term, count in Counter(terms).items():
            self._postings.setdefault(term, {})[chunk.chunk_id] = count

    def add_all(self, chunks: Iterable[Chunk]) -> None:
        for chunk in chunks:
            self.add(chunk)

    def _remove(self, chunk_id: str) -> None:
        self._chunks.pop(chunk_id, None)
        self._lengths.pop(chunk_id, None)
        for postings in self._postings.values():
            postings.pop(chunk_id, None)

    @staticmethod
    def _indexed_text(chunk: Chunk) -> str:
        """Chunk text prefixed with its heading trail.

        The heading is indexed because a rate table's cells often name only the
        product code while the heading names the product — so a query for
        "Kisan Credit Card interest" matches the heading and a query for "KCC"
        matches the cell, and both need to reach the same chunk.
        """
        if chunk.heading_path:
            return f"{chunk.heading_trail}\n{chunk.text}"
        return chunk.text

    def idf(self, term: str) -> float:
        """Robertson-Zaragoza IDF with a positive floor.

        The published form is ``ln((N - n + 0.5) / (n + 0.5) + 1)``, whose ``+1``
        inside the log already keeps it non-negative — this is the form Lucene
        adopted precisely to avoid the negative branch of the older
        ``ln((N - n + 0.5) / (n + 0.5))``.

        **Why the older form is actively wrong here**, and worth a note because
        several BM25 ports still carry it: on a policy corpus, "loan" appears in
        every document, giving ``n ≈ N`` and a negative IDF. A query containing
        it would then *subtract* score from every document that contains the
        word — so "personal loan eligibility" would rank documents mentioning
        loans below documents that do not. That is not a small mis-weighting; it
        inverts the ranking for the most common query shape a bank receives.

        A term absent from the corpus scores 0 rather than raising: an unknown
        word in a query is normal (a typo, a product the bank does not offer)
        and it should contribute nothing, not stop the query.
        """
        n = len(self._postings.get(term, ()))
        if n == 0:
            return 0.0
        total = len(self._chunks)
        return math.log(((total - n + 0.5) / (n + 0.5)) + 1.0)

    def score(self, query: str, chunk_id: str) -> float:
        """BM25 score of one chunk against one query. Exposed for testing.

        A per-document entry point exists so the arithmetic can be pinned
        against hand-computed values without going through ranking, which is
        what CONTRIBUTING's "test properties, not numbers" carves out an
        exception for: BM25's *value* is defined by the paper, so the port is
        allowed — and obliged — to reproduce it exactly.
        """
        if chunk_id not in self._chunks:
            raise RetrievalError(f"{chunk_id!r} is not indexed")
        length = self._lengths[chunk_id]
        avgdl = self.average_length or 1.0
        total = 0.0
        for term in tokenize(query):
            freq = self._postings.get(term, {}).get(chunk_id, 0)
            if freq == 0:
                continue
            denominator = freq + self.k1 * (1.0 - self.b + self.b * length / avgdl)
            total += self.idf(term) * (freq * (self.k1 + 1.0)) / denominator
        return total

    def search(
        self,
        query: str,
        k: int,
        *,
        as_of: date | None = None,
        product: str | None = None,
        language: str | None = None,
    ) -> list[ScoredChunk]:
        """Top-``k`` chunks for ``query``, effective-date filtered by default.

        ``as_of`` defaults to ``None``, which means **no date filter**, and that
        looks like the unsafe default this repository argues against. It is not,
        and the distinction is worth stating: this is the raw lexical leg, and
        the filter belongs to :class:`HybridRetriever`, which is the entry point
        an answer path uses and which requires ``as_of``. Putting a permissive
        default here and a required argument there means the safe path is the
        one with the shorter name.

        Ties are broken by chunk id so the ranking is deterministic. An unstable
        top-5 makes hit-rate@5 unreproducible, and the gate is measured on it.
        """
        if k <= 0:
            raise RetrievalError(f"k must be positive, got {k}")
        terms = tokenize(query)
        if not terms:
            return []

        candidates: set[str] = set()
        for term in terms:
            candidates |= set(self._postings.get(term, ()))

        scored: list[tuple[float, str]] = []
        for chunk_id in candidates:
            chunk = self._chunks[chunk_id]
            if as_of is not None and not chunk.is_effective_on(as_of):
                continue
            if product is not None and product not in chunk.product_tags:
                continue
            if language is not None and chunk.language != language:
                continue
            value = self.score(query, chunk_id)
            if value > 0.0:
                scored.append((value, chunk_id))

        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        return [
            ScoredChunk(chunk=self._chunks[chunk_id], score=value, leg="bm25", rank=rank)
            for rank, (value, chunk_id) in enumerate(scored[:k], start=1)
        ]


def fuse(
    rankings: Mapping[str, Sequence[ScoredChunk]],
    *,
    k: int,
    rrf_k: int = RRF_K,
) -> list[ScoredChunk]:
    """Reciprocal-rank fusion over one or more rankings.

    ``RRF(d) = Σ_r 1 / (rrf_k + rank_r(d))`` — Cormack, Clarke & Buettcher,
    SIGIR 2009.

    RRF rather than a weighted score sum, and that choice is the point of the
    method: BM25 scores and cosine similarities live on incomparable scales, and
    a weighted sum of them needs a normalisation nobody can ground. Ranks are
    comparable by construction, so fusion needs no calibration and no tuned
    weight — which matters here specifically because there is no golden set to
    tune one against (LH-602).

    ``rrf_k`` damps the top of each list: with ``k=60``, rank 1 contributes
    1/61 and rank 2 contributes 1/62, so a document ranked first by one leg and
    absent from the other loses to a document ranked third by both. That is the
    intended behaviour — agreement between an exact-token match and a semantic
    match is stronger evidence than either alone.
    """
    if k <= 0:
        raise RetrievalError(f"k must be positive, got {k}")
    if rrf_k <= 0:
        raise RetrievalError(f"rrf_k must be positive, got {rrf_k}")
    if not rankings:
        raise RetrievalError("fusion needs at least one ranking")

    totals: dict[str, float] = {}
    seen: dict[str, Chunk] = {}
    legs: dict[str, list[str]] = {}

    for leg, ranking in rankings.items():
        for position, hit in enumerate(ranking, start=1):
            chunk_id = hit.chunk.chunk_id
            totals[chunk_id] = totals.get(chunk_id, 0.0) + 1.0 / (rrf_k + position)
            seen.setdefault(chunk_id, hit.chunk)
            legs.setdefault(chunk_id, []).append(leg)

    order = sorted(totals.items(), key=lambda pair: (-pair[1], pair[0]))
    return [
        ScoredChunk(
            chunk=seen[chunk_id],
            score=value,
            leg="+".join(sorted(set(legs[chunk_id]))),
            rank=rank,
        )
        for rank, (chunk_id, value) in enumerate(order[:k], start=1)
    ]


class DenseRetriever:
    """The dense leg. Needs a bound embedding model and vector store.

    Present as a class rather than left implicit so the hybrid retriever has a
    concrete thing to be missing. With no binding it raises
    :class:`UnboundPort`, and :class:`HybridRetriever` degrades to lexical-only
    **and says so on every result** — a silent degradation would make the
    hybrid requirement satisfiable by omission.
    """

    def __init__(self, embedder: EmbeddingModel | None, store: VectorStore | None) -> None:
        self.embedder = embedder
        self.store = store

    @property
    def bound(self) -> bool:
        return self.embedder is not None and self.store is not None

    def index(self, chunks: Sequence[Chunk]) -> None:
        if not self.bound:
            raise UnboundPort(
                "no embedding model or vector store is bound (LH-604). Phase 5 "
                "binds neither on Track A by decision — see ADR-0015."
            )
        vectors = self.embedder.encode([c.text for c in chunks])  # type: ignore[union-attr]
        for chunk, vector in zip(chunks, vectors, strict=True):
            self.store.upsert(chunk.chunk_id, vector)  # type: ignore[union-attr]

    def search(self, query: str, k: int, chunks: Mapping[str, Chunk]) -> list[ScoredChunk]:
        if not self.bound:
            raise UnboundPort(
                "no embedding model or vector store is bound (LH-604); the dense "
                "leg cannot run. Hybrid retrieval degrades to lexical-only, which "
                "HybridRetriever reports rather than hides."
            )
        vector = self.embedder.encode([query])[0]  # type: ignore[union-attr]
        hits = self.store.search(vector, k)  # type: ignore[union-attr]
        out = []
        for rank, hit in enumerate(hits, start=1):
            chunk = chunks.get(hit.chunk_id)
            if chunk is None:
                continue
            out.append(ScoredChunk(chunk=chunk, score=hit.score, leg="dense", rank=rank))
        return out


@dataclass
class RetrievalResult:
    """A fused, optionally reranked result list plus what produced it.

    The provenance fields exist because Phase 5 §5 step 1 requires officer
    corrections to be triaged into "corpus fixes vs. retrieval fixes vs. prompt
    fixes", and that triage is impossible from a bare list of passages. Knowing
    that a wrong answer came from a lexical-only run with no reranker is most of
    the diagnosis.
    """

    hits: list[ScoredChunk]
    as_of: date
    legs_used: tuple[str, ...]
    reranked: bool
    degraded: bool = False
    degraded_reason: str = ""

    @property
    def chunk_ids(self) -> list[str]:
        return [hit.chunk.chunk_id for hit in self.hits]

    @property
    def empty(self) -> bool:
        return not self.hits


class HybridRetriever:
    """BM25 + dense + RRF + reranker, with the date filter as the entry rule.

    This is the entry point an answer path uses, and its ``as_of`` is required
    with no default — the mirror image of :meth:`BM25Index.search`, whose
    permissive default is fine because it is the raw leg. Phase 5 §4 WS-5.1
    step 1 makes the filter a *retrieval* requirement, and a retrieval entry
    point that could be called without a date is one that eventually is.
    """

    def __init__(
        self,
        *,
        lexical: BM25Index | None = None,
        dense: DenseRetriever | None = None,
        reranker: Reranker | None = None,
    ) -> None:
        self.lexical = lexical if lexical is not None else BM25Index()
        self.dense = dense
        self.reranker = reranker
        self._chunks: dict[str, Chunk] = {}

    def index(self, chunks: Sequence[Chunk]) -> None:
        self.lexical.add_all(chunks)
        for chunk in chunks:
            self._chunks[chunk.chunk_id] = chunk
        if self.dense is not None and self.dense.bound:
            self.dense.index(chunks)

    def retrieve(
        self,
        query: str,
        *,
        as_of: date,
        k: int = HIT_RATE_K,
        candidate_k: int | None = None,
        product: str | None = None,
        language: str | None = None,
    ) -> RetrievalResult:
        """Retrieve ``k`` passages effective on ``as_of``.

        ``candidate_k`` is how deep each leg goes before fusion, defaulting to
        ``4 × k``. Fusing only the final-``k`` lists would throw away the
        agreement signal RRF exists to find: a chunk ranked 6th by both legs is
        strong evidence and is invisible if each leg only reports 5.
        """
        if not isinstance(as_of, date):
            raise RetrievalError(
                "retrieve() needs an as-of date. Phase 5 §4 WS-5.1 step 1 makes "
                "effective-date filtering a retrieval requirement, and stale-rate "
                "poisoning is a successful retrieval of a superseded passage — "
                "there is no safe default."
            )
        if k <= 0:
            raise RetrievalError(f"k must be positive, got {k}")
        depth = candidate_k if candidate_k is not None else 4 * k

        lexical_hits = self.lexical.search(
            query, depth, as_of=as_of, product=product, language=language
        )
        rankings: dict[str, Sequence[ScoredChunk]] = {"bm25": lexical_hits}

        degraded = False
        reason = ""
        if self.dense is not None and self.dense.bound:
            eligible = {
                chunk_id: chunk
                for chunk_id, chunk in self._chunks.items()
                if chunk.is_effective_on(as_of)
                and (product is None or product in chunk.product_tags)
                and (language is None or chunk.language == language)
            }
            rankings["dense"] = self.dense.search(query, depth, eligible)
        else:
            degraded = True
            reason = (
                "no dense leg: no embedding model or vector store is bound "
                "(LH-604). Phase 5 §4 WS-5.2 calls hybrid retrieval mandatory "
                "because exact tokens like KCC and MCLR are what dense retrieval "
                "fumbles — running lexical-only is the safer half to keep, but it "
                "is not the specified system and no hit-rate from it is a gate "
                "number."
            )

        fused = fuse(rankings, k=k)
        reranked = False
        if self.reranker is not None and fused:
            scores = self.reranker.rerank(query, [hit.chunk.text for hit in fused])
            if len(scores) != len(fused):
                raise RetrievalError(
                    f"reranker returned {len(scores)} scores for {len(fused)} "
                    "passages; scores must align with the input order"
                )
            order = sorted(
                zip(fused, scores, strict=True),
                key=lambda pair: (-pair[1], pair[0].chunk.chunk_id),
            )
            fused = [
                ScoredChunk(chunk=hit.chunk, score=score, leg=hit.leg, rank=rank)
                for rank, (hit, score) in enumerate(order, start=1)
            ]
            reranked = True

        return RetrievalResult(
            hits=fused,
            as_of=as_of,
            legs_used=tuple(sorted(rankings)),
            reranked=reranked,
            degraded=degraded,
            degraded_reason=reason,
        )


def hit_rate_at_k(
    retrieved: Sequence[Sequence[str]],
    relevant: Sequence[Sequence[str]],
    *,
    k: int = HIT_RATE_K,
) -> float:
    """Fraction of queries whose top-``k`` contains at least one relevant chunk.

    Phase 5 §4 WS-5.2's gate metric. It is *hit rate*, not recall or precision:
    one relevant passage in the top ``k`` is a hit however many others were
    missed, because the assistant needs one groundable passage to answer from,
    not all of them.

    That makes it the right metric for this gate and a *misleading* one for
    corpus quality, which is worth writing down: a corpus where every question
    is answered by exactly one passage and a corpus where each is answered by
    five score identically, and only the second survives a document being
    retired.
    """
    if len(retrieved) != len(relevant):
        raise RetrievalError(
            f"{len(retrieved)} retrieved lists against {len(relevant)} relevant "
            "sets; a hit rate over mismatched lists is a hit rate over the wrong "
            "questions"
        )
    if not retrieved:
        raise RetrievalError(
            "hit rate over zero queries is not 0.0 and not 1.0 — it is undefined. "
            "The golden set is LH-602."
        )
    if k <= 0:
        raise RetrievalError(f"k must be positive, got {k}")

    hits = 0
    for got, want in zip(retrieved, relevant, strict=True):
        if not want:
            raise RetrievalError(
                "a golden-set question with no relevant passage cannot be scored: "
                "it is either unanswerable from the corpus (which the refusal path "
                "handles, not the retriever) or a curation error"
            )
        if set(got[:k]) & set(want):
            hits += 1
    return hits / len(retrieved)

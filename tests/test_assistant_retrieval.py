"""Hybrid retrieval — BM25, RRF, reranking, hit-rate@5 — WS-5.2.

Phase 5 §4 WS-5.2 calls hybrid retrieval mandatory, and gives the reason in one
sentence: banking queries carry exact tokens ("KCC", "MCLR", product codes) that
dense retrieval fumbles. The concrete failure is not a miss — an embedding model
places "KCC" near "agricultural credit", which is correct semantics and the
wrong document, so the customer gets the general agri circular and a plausible,
cited answer about a different product.

BM25 is a port of a published algorithm rather than a heuristic, so CONTRIBUTING's
"test properties, not numbers" carves out an exception here: the *value* is
defined by Robertson & Zaragoza, and the port is obliged to reproduce it. The
hand-computed test below is that obligation. Everything downstream of BM25 —
fusion order, degradation reporting, the gate metric — is tested on properties.
"""

from __future__ import annotations

import math
import unittest
from datetime import date

from lending_hub.assistant.chunking import chunk_document
from lending_hub.assistant.ports import UnboundPort, VectorHit
from lending_hub.assistant.registry import Document, DocumentKind
from lending_hub.assistant.retrieval import (
    BM25_B,
    BM25_K1,
    HIT_RATE_GATE,
    HIT_RATE_K,
    RRF_K,
    BM25Index,
    DenseRetriever,
    HybridRetriever,
    RetrievalError,
    ScoredChunk,
    fuse,
    hit_rate_at_k,
    tokenize,
)

AS_OF = date(2026, 6, 1)


def _doc(text, *, doc_id="D1", tags=("personal_loan",), language="en",
         effective_from=date(2026, 1, 1), effective_to=None) -> Document:
    return Document(
        doc_id=doc_id,
        title=doc_id,
        kind=DocumentKind.POLICY_CIRCULAR,
        owner="Product Head",
        effective_from=effective_from,
        effective_to=effective_to,
        text=text,
        version="v1",
        language=language,
        product_tags=tags,
    )


def _chunks(*docs):
    out = []
    for doc in docs:
        out.extend(chunk_document(doc))
    return out


class Tokenisation(unittest.TestCase):
    def test_slashes_split_but_hyphens_do_not(self):
        """"KCC/MCLR" is two terms; "non-agri" is one, and the difference matters.

        Splitting "non-agri" yields "agri", which then matches every
        agricultural document — so a query about non-agricultural lending
        retrieves the agricultural corpus and inverts its own meaning.
        """
        self.assertEqual(tokenize("KCC/MCLR"), ["kcc", "mclr"])
        self.assertIn("non-agri", tokenize("non-agri exposure"))

    def test_percent_and_decimal_survive(self):
        """"12.5%" is a term a rate query contains literally.

        Stripping the sign collides the rate with a version number; dropping the
        decimal point makes 7.0 and 70 the same term.
        """
        self.assertIn("12.5%", tokenize("the rate is 12.5%"))
        self.assertNotIn("70", tokenize("7.0 per cent"))

    def test_case_is_folded(self):
        self.assertEqual(tokenize("KCC kcc Kcc"), ["kcc", "kcc", "kcc"])

    def test_devanagari_words_survive_as_words(self):
        """The silent failure that would make the Hindi index useless.

        Matras are Unicode category Mn/Mc and are not word characters, so the obvious
        word pattern shreds "किसान" into five single-character terms. Nothing
        errors — every query shreds the same way — so the symptom is only that
        Hindi retrieval is bad, which reads as "the embedding model is weak on
        Hindi" and gets fixed in the wrong place. SRS GA-4 requires Hindi plus
        two regional languages.
        """
        self.assertEqual(tokenize("किसान क्रेडिट कार्ड"), ["किसान", "क्रेडिट", "कार्ड"])

    def test_other_indic_scripts_work_without_a_second_fix(self):
        """The mark set comes from the Unicode database, not a typed range.

        A Devanagari-shaped fix that had to be repeated per script is a fix that
        will not be repeated for the third language.
        """
        self.assertEqual(tokenize("ব্যাঙ্ক ঋণ"), ["ব্যাঙ্ক", "ঋণ"])
        self.assertEqual(tokenize("கடன் வட்டி"), ["கடன்", "வட்டி"])


class BM25Arithmetic(unittest.TestCase):
    """BM25's value is defined by the paper. The port must reproduce it exactly."""

    def test_score_matches_a_hand_computed_value(self):
        """The obligation Master §2 rule 2 places on a port, discharged.

        Two documents, one term. Everything in the formula is small enough to
        compute by hand, so a drift in k1, b, the IDF form or the length
        normalisation shows up here rather than as a subtly worse ranking
        nobody can attribute.
        """
        index = BM25Index()
        index.add_all(
            _chunks(
                _doc("kcc kcc alpha beta", doc_id="A"),
                _doc("gamma delta epsilon zeta", doc_id="B"),
            )
        )
        chunk_a = next(c for c in index.search("kcc", 5) if c.chunk.doc_id == "A").chunk

        # N=2, n=1 for "kcc": idf = ln((2 - 1 + 0.5)/(1 + 0.5) + 1) = ln 2
        expected_idf = math.log(2.0)
        self.assertAlmostEqual(index.idf("kcc"), expected_idf, places=12)

        # Both chunks are 4 terms, so |D| = avgdl = 4 and the length factor is 1.
        freq = 2.0
        expected = expected_idf * (freq * (BM25_K1 + 1.0)) / (
            freq + BM25_K1 * (1.0 - BM25_B + BM25_B * 1.0)
        )
        self.assertAlmostEqual(index.score("kcc", chunk_a.chunk_id), expected, places=12)

    def test_idf_never_goes_negative_on_a_universal_term(self):
        """The deviation CONTRIBUTING requires stating, and why it is not optional.

        The older Robertson-Zaragoza IDF form goes negative when a term appears
        in more than half the corpus. On a policy corpus "loan" is in every
        document, so a query containing it would *subtract* score from every
        document that has the word — ranking documents about loans below
        documents that never mention them. That inverts the ranking for the most
        common query shape a bank receives.
        """
        index = BM25Index()
        index.add_all(
            _chunks(
                _doc("loan terms alpha", doc_id="A"),
                _doc("loan terms beta", doc_id="B"),
                _doc("loan terms gamma", doc_id="C"),
            )
        )
        self.assertGreater(index.idf("loan"), 0.0)

    def test_a_rare_term_outranks_a_common_one(self):
        """This is the whole reason the lexical leg exists.

        "KCC" is rare and decisive; "loan" is everywhere and nearly free. A
        retriever that weighted them alike would answer a KCC question from
        whichever loan document happened to be longest.
        """
        index = BM25Index()
        index.add_all(
            _chunks(
                _doc("loan loan loan loan terms and conditions apply", doc_id="COMMON"),
                _doc("kcc loan limits for farmers", doc_id="KCC"),
            )
        )
        hits = index.search("kcc loan", 5)
        self.assertEqual(hits[0].chunk.doc_id, "KCC")

    def test_term_frequency_saturates(self):
        """A circular saying "interest" forty times is not forty times as relevant.

        Without saturation, keyword-stuffed or simply repetitive documents win
        every query that shares a word with them — and a rate table repeats its
        column headings by construction.
        """
        index = BM25Index()
        index.add_all(
            _chunks(
                _doc(" ".join(["interest"] * 2 + ["filler"] * 20), doc_id="TWICE"),
                _doc(" ".join(["interest"] * 40 + ["filler"] * 20), doc_id="FORTY"),
            )
        )
        twice = index.search("interest", 5)
        by_doc = {h.chunk.doc_id: h.score for h in twice}
        self.assertLess(by_doc["FORTY"] / by_doc["TWICE"], 3.0)

    def test_length_normalisation_stops_a_long_chunk_winning_on_volume(self):
        """Chunk lengths vary by design here — an atomic rate table is long.

        Without ``b``, that table outranks a short FAQ on every query sharing a
        word with it, purely because it contains more words.
        """
        index = BM25Index()
        index.add_all(
            _chunks(
                _doc("waiver", doc_id="SHORT"),
                _doc("waiver " + " ".join(["padding"] * 200), doc_id="LONG"),
            )
        )
        hits = index.search("waiver", 5)
        self.assertEqual(hits[0].chunk.doc_id, "SHORT")

    def test_an_unknown_query_term_contributes_nothing_rather_than_raising(self):
        """A typo or an unoffered product is a normal query, not an error."""
        index = BM25Index()
        index.add_all(_chunks(_doc("kcc limits", doc_id="A")))
        self.assertEqual(index.idf("zzzznotaword"), 0.0)
        self.assertEqual(index.search("zzzznotaword", 5), [])

    def test_ranking_is_deterministic_under_ties(self):
        """An unstable top-5 makes hit-rate@5 unreproducible, and it is the gate."""
        index = BM25Index()
        index.add_all(_chunks(*[_doc("kcc terms", doc_id=f"D{i}") for i in range(6)]))
        first = [h.chunk.chunk_id for h in index.search("kcc", 5)]
        second = [h.chunk.chunk_id for h in index.search("kcc", 5)]
        self.assertEqual(first, second)

    def test_reindexing_replaces_postings_rather_than_accumulating(self):
        """A shrunk chunk must not keep the frequencies of text it no longer has.

        Otherwise the index answers for a passage that is gone, and the citation
        resolves to text that does not contain the matched term.
        """
        index = BM25Index()
        chunk = _chunks(_doc("kcc kcc kcc alpha", doc_id="A"))[0]
        index.add(chunk)
        shrunk = type(chunk)(**{**chunk.__dict__, "text": "alpha"})
        index.add(shrunk)
        self.assertEqual(index.score("kcc", shrunk.chunk_id), 0.0)

    def test_the_heading_trail_is_indexed_with_the_body(self):
        """A cell says "KCC"; the heading says "Kisan Credit Card".

        Both queries must reach the same chunk, and only indexing the heading
        makes the long-form query work.
        """
        index = BM25Index()
        index.add_all(
            _chunks(_doc("# Kisan Credit Card\n\n| Code | Rate |\n| - | - |\n| KCC | 7.0% |", doc_id="A"))
        )
        self.assertTrue(index.search("kisan credit card", 5))
        self.assertTrue(index.search("kcc", 5))

    def test_invalid_parameters_raise(self):
        with self.assertRaises(RetrievalError):
            BM25Index(b=1.5)
        with self.assertRaises(RetrievalError):
            BM25Index(k1=-1)


class Fusion(unittest.TestCase):
    def test_rrf_weights_agreement_above_a_single_first_place(self):
        """The intended behaviour, and the reason RRF is used instead of a sum.

        A chunk ranked 3rd by both legs beats a chunk ranked 1st by one and
        absent from the other, because agreement between an exact-token match
        and a semantic match is stronger evidence than either alone.
        """
        chunks = _chunks(*[_doc(f"text {i}", doc_id=f"D{i}") for i in range(4)])
        both, lexical_only, dense_only, filler = chunks
        lexical = [
            ScoredChunk(chunk=lexical_only, score=9.0, rank=1),
            ScoredChunk(chunk=filler, score=8.0, rank=2),
            ScoredChunk(chunk=both, score=7.0, rank=3),
        ]
        dense = [
            ScoredChunk(chunk=dense_only, score=0.9, leg="dense", rank=1),
            ScoredChunk(chunk=both, score=0.7, leg="dense", rank=3),
        ]
        fused = fuse({"bm25": lexical, "dense": dense}, k=4)
        self.assertEqual(fused[0].chunk.chunk_id, both.chunk_id)
        order = [h.chunk.chunk_id for h in fused]
        self.assertLess(order.index(both.chunk_id), order.index(lexical_only.chunk_id))
        self.assertLess(order.index(both.chunk_id), order.index(dense_only.chunk_id))

    def test_fusion_needs_no_score_normalisation(self):
        """BM25 scores and cosine similarities are on incomparable scales.

        RRF uses ranks, so it needs no calibration and no tuned weight — which
        matters here specifically, because there is no golden set to tune one
        against (LH-602).
        """
        chunks = _chunks(*[_doc("t", doc_id=f"D{i}") for i in range(2)])
        huge = [ScoredChunk(chunk=chunks[0], score=1e9, rank=1)]
        tiny = [ScoredChunk(chunk=chunks[1], score=1e-9, leg="dense", rank=1)]
        fused = fuse({"bm25": huge, "dense": tiny}, k=2)
        self.assertAlmostEqual(fused[0].score, fused[1].score, places=12)

    def test_the_fused_leg_records_which_legs_found_it(self):
        """Phase 5 §5 step 1 triages corrections into corpus vs retrieval vs prompt.

        That triage is impossible from a bare passage list: "the wrong circular
        was cited" has different fixes depending on which leg surfaced it.
        """
        chunks = _chunks(*[_doc("t", doc_id=f"D{i}") for i in range(1)])
        fused = fuse(
            {
                "bm25": [ScoredChunk(chunk=chunks[0], score=1.0, rank=1)],
                "dense": [ScoredChunk(chunk=chunks[0], score=1.0, leg="dense", rank=1)],
            },
            k=1,
        )
        self.assertEqual(fused[0].leg, "bm25+dense")

    def test_rrf_k_is_the_published_constant(self):
        """60 from Cormack, Clarke & Buettcher — not a value tuned here."""
        self.assertEqual(RRF_K, 60)

    def test_no_rankings_raises(self):
        with self.assertRaises(RetrievalError):
            fuse({}, k=5)


class EffectiveDateAtRetrieval(unittest.TestCase):
    """Stale-rate poisoning is a *successful* retrieval of a superseded passage."""

    def setUp(self):
        self.retriever = HybridRetriever()
        self.retriever.index(
            _chunks(
                _doc(
                    "The personal loan rate is 11.0% per annum.",
                    doc_id="OLD",
                    effective_from=date(2026, 1, 1),
                    effective_to=date(2026, 3, 31),
                ),
                _doc(
                    "The personal loan rate is 12.5% per annum.",
                    doc_id="NEW",
                    effective_from=date(2026, 4, 1),
                ),
            )
        )

    def test_the_superseded_rate_is_not_retrieved(self):
        result = self.retriever.retrieve("personal loan rate", as_of=AS_OF)
        self.assertEqual([h.chunk.doc_id for h in result.hits], ["NEW"])

    def test_a_past_as_of_retrieves_what_was_live_then(self):
        """Replay must resolve against the corpus in force at the time.

        Master §3.3 requires a decision to be reproducible for eight years, and
        a replay that silently used today's corpus would report a disagreement
        that is a fact about the intervening years rather than about the answer.
        """
        result = self.retriever.retrieve("personal loan rate", as_of=date(2026, 2, 1))
        self.assertEqual([h.chunk.doc_id for h in result.hits], ["OLD"])

    def test_retrieve_has_no_default_as_of(self):
        """The safe path is the one with the shorter name.

        BM25Index.search may be called without a date because it is the raw leg;
        HybridRetriever.retrieve is what an answer path calls, and a retrieval
        entry point that *can* be called without a date eventually is.
        """
        with self.assertRaises(TypeError):
            self.retriever.retrieve("rate")  # type: ignore[call-arg]
        with self.assertRaises(RetrievalError):
            self.retriever.retrieve("rate", as_of="2026-06-01")  # type: ignore[arg-type]


class Degradation(unittest.TestCase):
    def test_lexical_only_is_reported_not_hidden(self):
        """A silent degradation makes the hybrid requirement satisfiable by omission.

        Phase 5 §4 WS-5.2 calls hybrid mandatory. Running lexical-only is the
        safer half to keep — it is the half that handles KCC and MCLR — but it
        is not the specified system, and a hit-rate computed from it is not the
        gate's number.
        """
        result = HybridRetriever().retrieve("anything", as_of=AS_OF)
        self.assertTrue(result.degraded)
        self.assertIn("LH-604", result.degraded_reason)
        self.assertEqual(result.legs_used, ("bm25",))

    def test_an_unbound_dense_leg_raises_rather_than_returning_nothing(self):
        """An empty dense ranking and an unbound model must not look alike.

        The first is "the index has nothing relevant"; the second is a
        deployment error. Fusing an empty list for the second silently halves
        the retriever and reports full health.
        """
        with self.assertRaises(UnboundPort):
            DenseRetriever(None, None).search("q", 5, {})


class _StubEmbedder:
    """A one-dimensional 'embedding': the count of a marker token.

    Not a model and not pretending to be one. It exists only to prove the fusion
    plumbing carries a second leg's ranking — the dense leg's *quality* is not
    testable here and no number from it is reported anywhere.
    """

    dimension = 1

    def encode(self, texts):
        return [[float(t.lower().count("solar"))] for t in texts]


class _StubStore:
    def __init__(self):
        self.vectors = {}

    def upsert(self, chunk_id, vector):
        self.vectors[chunk_id] = list(vector)

    def search(self, vector, k):
        ranked = sorted(
            self.vectors.items(), key=lambda kv: (-kv[1][0], kv[0])
        )
        return [VectorHit(chunk_id=cid, score=vec[0]) for cid, vec in ranked[:k] if vec[0] > 0]


class _ReverseReranker:
    """Scores passages in reverse input order, so reranking is observable."""

    def rerank(self, query, passages):
        return [float(len(passages) - i) for i in range(len(passages))]


class HybridPlumbing(unittest.TestCase):
    def test_a_bound_dense_leg_contributes_to_the_fusion(self):
        retriever = HybridRetriever(dense=DenseRetriever(_StubEmbedder(), _StubStore()))
        retriever.index(
            _chunks(
                _doc("solar solar rooftop financing", doc_id="SOLAR"),
                _doc("kcc limits for farmers", doc_id="KCC"),
            )
        )
        result = retriever.retrieve("solar", as_of=AS_OF)
        self.assertFalse(result.degraded)
        self.assertEqual(result.legs_used, ("bm25", "dense"))

    def test_a_reranker_reorders_and_is_recorded(self):
        retriever = HybridRetriever(reranker=_ReverseReranker())
        retriever.index(
            _chunks(*[_doc(f"kcc terms {i}", doc_id=f"D{i}") for i in range(3)])
        )
        result = retriever.retrieve("kcc", as_of=AS_OF, k=3)
        self.assertTrue(result.reranked)
        self.assertEqual(len(result.hits), 3)

    def test_a_misaligned_reranker_raises(self):
        """Scores must align with input order, and a length mismatch proves they don't.

        Silently zipping the short list would attach one passage's score to
        another passage, which reorders the answer's evidence without any
        symptom.
        """

        class _Short:
            def rerank(self, query, passages):
                return [1.0]

        retriever = HybridRetriever(reranker=_Short())
        retriever.index(_chunks(*[_doc(f"kcc {i}", doc_id=f"D{i}") for i in range(3)]))
        with self.assertRaises(RetrievalError):
            retriever.retrieve("kcc", as_of=AS_OF, k=3)

    def test_candidate_depth_exceeds_k_before_fusion(self):
        """Fusing only the final-k lists throws away the agreement RRF looks for.

        A chunk ranked 6th by both legs is strong evidence and is invisible if
        each leg reports only 5.
        """
        retriever = HybridRetriever()
        retriever.index(_chunks(*[_doc(f"kcc term {i}", doc_id=f"D{i}") for i in range(20)]))
        result = retriever.retrieve("kcc", as_of=AS_OF, k=5)
        self.assertEqual(len(result.hits), 5)

    def test_product_and_language_narrow_the_candidate_set(self):
        retriever = HybridRetriever()
        retriever.index(
            _chunks(
                _doc("kcc rate", doc_id="KCC-EN", tags=("kcc",), language="en"),
                _doc("kcc rate", doc_id="KCC-HI", tags=("kcc",), language="hi"),
                _doc("kcc rate", doc_id="PL", tags=("personal_loan",)),
            )
        )
        result = retriever.retrieve("kcc rate", as_of=AS_OF, product="kcc", language="en")
        self.assertEqual([h.chunk.doc_id for h in result.hits], ["KCC-EN"])


class HitRate(unittest.TestCase):
    def test_the_gate_constants_are_spec(self):
        """hit-rate@5 >= 95% is Phase 5 §4 WS-5.2 verbatim, not a chosen bar."""
        self.assertEqual((HIT_RATE_K, HIT_RATE_GATE), (5, 0.95))

    def test_one_relevant_passage_in_the_top_k_is_a_hit(self):
        """Hit rate, not recall: the assistant needs one groundable passage.

        Worth pinning because the two are easy to conflate, and because the
        difference is what makes hit rate the right *gate* metric and a
        misleading *corpus-quality* metric — a corpus with one answer per
        question and one with five score identically, and only the second
        survives a document being retired.
        """
        self.assertEqual(
            hit_rate_at_k([["a", "b", "c", "d", "e"]], [["e", "z"]], k=5), 1.0
        )
        self.assertEqual(
            hit_rate_at_k([["a", "b", "c", "d", "e", "f"]], [["f"]], k=5), 0.0
        )

    def test_zero_queries_is_undefined_rather_than_perfect(self):
        """An empty golden set must not report 1.0, or the gate passes on nothing.

        This is the specific way a missing measuring stick becomes a passing
        gate: no questions, no misses, 100%.
        """
        with self.assertRaises(RetrievalError):
            hit_rate_at_k([], [])

    def test_a_question_with_no_relevant_passage_is_refused(self):
        """It is a curation error or a refusal case, and neither is a retrieval score.

        An unanswerable question belongs to the refusal path (Phase 5 §8: "any
        answer where retrieval returned nothing — refuse + escalate"), so
        scoring it as a retrieval miss blames the retriever for correct
        behaviour.
        """
        with self.assertRaises(RetrievalError):
            hit_rate_at_k([["a"]], [[]])

    def test_mismatched_lengths_raise(self):
        with self.assertRaises(RetrievalError):
            hit_rate_at_k([["a"], ["b"]], [["a"]])


if __name__ == "__main__":
    unittest.main()

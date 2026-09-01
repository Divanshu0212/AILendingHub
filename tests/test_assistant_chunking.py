"""Structure-aware chunking — WS-5.1.2.

Phase 5 §4 WS-5.1 step 2 gives three instructions and one of them is
load-bearing: "tables kept intact". The other two are hygiene.

A split rate table does not fail loudly. Both halves retrieve — one for the
heading, one for the numbers — and each is a fluent passage that has lost the
association that gave it meaning. The model then answers with one product's rate
under another product's heading, which is a wrong number carrying a real
citation to a real document. That is the hardest error in this phase to catch
afterwards, so the tests below are weighted towards it.
"""

from __future__ import annotations

import unittest
from datetime import date

from lending_hub.assistant.chunking import (
    MAX_CHUNK_TOKENS,
    MIN_CHUNK_TOKENS,
    BlockKind,
    ChunkingError,
    budget_report,
    chunk_corpus,
    chunk_document,
    parse_blocks,
)
from lending_hub.assistant.registry import Document, DocumentKind

TABLE = """| Product | Rate |
| --- | --- |
| Personal Loan | 12.5% |
| Kisan Credit Card | 7.0% |
| Gold Loan | 9.25% |"""


def _doc(text: str, *, doc_id="CIRC-1", version="v1", language="en") -> Document:
    return Document(
        doc_id=doc_id,
        title="Rate circular",
        kind=DocumentKind.RATE_SHEET,
        owner="Product Head",
        effective_from=date(2026, 1, 1),
        effective_to=date(2026, 12, 31),
        text=text,
        version=version,
        language=language,
        product_tags=("personal_loan", "kcc"),
    )


def _words(n: int, word="policy") -> str:
    return " ".join([word] * n)


def _sentences(n: int) -> str:
    """``n`` short well-formed sentences — the shape ordinary policy prose has.

    Distinct from :func:`_words`, which produces one un-terminated run and
    therefore exercises the deliberately different single-sentence path.
    """
    return " ".join(f"Clause {i} of the policy applies to eligible accounts." for i in range(n))


class BlockParsing(unittest.TestCase):
    def test_headings_build_a_nested_trail(self):
        """A rate under 'KCC › Interest' and one under 'Personal Loan › Interest'
        are different facts.

        A chunk that dropped its heading path would make them indistinguishable
        to the retriever and to the human reading the cited passage — the two
        readers who most need to tell them apart.
        """
        blocks = parse_blocks("# Products\n\n## KCC\n\nRate text.\n\n## Personal Loan\n\nOther text.")
        paragraphs = [b for b in blocks if b.kind is BlockKind.PARAGRAPH]
        self.assertEqual(paragraphs[0].heading_path, ("Products", "KCC"))
        self.assertEqual(paragraphs[1].heading_path, ("Products", "Personal Loan"))

    def test_a_deeper_heading_does_not_pop_a_shallower_one(self):
        blocks = parse_blocks("# A\n\n### C\n\nbody")
        body = [b for b in blocks if b.kind is BlockKind.PARAGRAPH][0]
        self.assertEqual(body.heading_path[0], "A")
        self.assertIn("C", body.heading_path)

    def test_a_pipe_table_is_one_atomic_block(self):
        blocks = parse_blocks(TABLE)
        tables = [b for b in blocks if b.kind is BlockKind.TABLE]
        self.assertEqual(len(tables), 1)
        self.assertTrue(tables[0].atomic)
        self.assertIn("Kisan Credit Card", tables[0].text)

    def test_a_paragraph_after_a_table_is_not_absorbed_into_it(self):
        """Otherwise the atomic block grows without limit down the document.

        Every following paragraph would inherit the table's un-splittability,
        and one table near the top of a circular would make the whole circular a
        single chunk.
        """
        blocks = parse_blocks(TABLE + "\nConditions apply.")
        kinds = [b.kind for b in blocks]
        self.assertIn(BlockKind.TABLE, kinds)
        self.assertIn(BlockKind.PARAGRAPH, kinds)

    def test_lists_are_their_own_block_kind(self):
        blocks = parse_blocks("Intro.\n\n- one\n- two\n- three")
        self.assertIn(BlockKind.LIST, [b.kind for b in blocks])


class TablesAreNeverSplit(unittest.TestCase):
    """The requirement the whole module exists for."""

    def test_a_table_larger_than_the_ceiling_stays_whole(self):
        """Intactness beats the ceiling when they conflict, and this pins it.

        Phase 5 §4 states both requirements and does not say which wins. The
        chunker chooses intactness because the failure mode of the other choice
        is a wrong rate with a valid citation, which nothing downstream detects.
        Raised as finding P5-F1 rather than resolved silently.
        """
        rows = "\n".join(f"| Product {i} | {i}.5% |" for i in range(300))
        text = f"# Rates\n\n| Product | Rate |\n| --- | --- |\n{rows}"
        chunks = chunk_document(_doc(text))
        table_chunks = [c for c in chunks if c.contains_table]
        self.assertEqual(len(table_chunks), 1)
        self.assertGreater(table_chunks[0].token_count, MAX_CHUNK_TOKENS)
        self.assertTrue(table_chunks[0].oversize)
        self.assertIn("Product 0", table_chunks[0].text)
        self.assertIn("Product 299", table_chunks[0].text)

    def test_a_header_row_never_lands_in_a_different_chunk_from_its_data(self):
        """The specific failure, asserted directly rather than via a proxy.

        If the header and the rows separate, one chunk answers "what are the
        rates" with column names and the other answers "12.5" with no product
        attached — and both look like good retrievals.
        """
        text = f"# Intro\n\n{_words(700)}\n\n## Rates\n\n{TABLE}"
        chunks = chunk_document(_doc(text))
        holding_header = [c for c in chunks if "| Product | Rate |" in c.text]
        self.assertEqual(len(holding_header), 1)
        self.assertIn("12.5%", holding_header[0].text)
        self.assertIn("7.0%", holding_header[0].text)

    def test_oversize_chunks_are_reported_and_attributed(self):
        """An oversize chunk with no table in it is a packing bug, not a table.

        The report distinguishes the two so that "3 oversize" reads as "3 rate
        tables kept whole" rather than "the budget stopped working".
        """
        rows = "\n".join(f"| P{i} | {i}% |" for i in range(300))
        chunks = chunk_document(_doc(f"| P | R |\n| - | - |\n{rows}"))
        report = budget_report(chunks)
        self.assertGreaterEqual(report["oversize"], 1)
        self.assertTrue(report["oversize_all_contain_tables"])


class Budget(unittest.TestCase):
    def test_prose_chunks_respect_the_spec_ceiling(self):
        """Ordinary prose packs inside the ceiling; only atomic blocks exceed it."""
        chunks = chunk_document(_doc(_sentences(400)))
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(c.token_count <= MAX_CHUNK_TOKENS for c in chunks))
        self.assertFalse(any(c.oversize for c in chunks))

    def test_the_band_is_spec_and_the_module_does_not_move_it(self):
        """300-800 is [SPEC] from Phase 5 §4 and SRS §8.3.1, not a tuned value."""
        self.assertEqual((MIN_CHUNK_TOKENS, MAX_CHUNK_TOKENS), (300, 800))

    def test_an_invalid_budget_raises_rather_than_being_clamped(self):
        with self.assertRaises(ChunkingError):
            chunk_document(_doc("body"), min_tokens=900, max_tokens=100)

    def test_a_short_document_is_one_undersize_chunk_not_a_padded_one(self):
        """A two-sentence FAQ is a two-sentence chunk.

        Padding it to the floor would mean joining it to unrelated text, which
        is how a chunk comes to retrieve for a question its own document does
        not answer.
        """
        chunks = chunk_document(_doc("The fee is waived for KCC accounts."))
        self.assertEqual(len(chunks), 1)
        self.assertTrue(chunks[0].undersize)
        self.assertLess(chunks[0].token_count, MIN_CHUNK_TOKENS)

    def test_a_heading_below_the_floor_does_not_force_a_new_chunk(self):
        """Three-line sections would otherwise become index entries of their own.

        A very short chunk loses every retrieval to a longer neighbour that
        mentions the same terms, so forcing one is not neutral — it removes that
        section from the index in practice.
        """
        text = "# A\n\nshort.\n\n# B\n\nalso short.\n\n# C\n\nstill short."
        self.assertEqual(len(chunk_document(_doc(text))), 1)

    def test_a_single_sentence_longer_than_the_budget_is_not_split(self):
        """The table failure in miniature.

        "the fee is waived" and "for accounts under six months" are each fluent
        and together mean something neither says alone.
        """
        sentence = "The fee is waived " + _words(1200) + " for eligible accounts."
        chunks = chunk_document(_doc(sentence))
        self.assertEqual(len(chunks), 1)


class MetadataInheritance(unittest.TestCase):
    """WS-5.1.2: "chunk metadata inherits registry fields"."""

    def setUp(self):
        self.document = _doc(_words(900))
        self.chunks = chunk_document(self.document)

    def test_every_registry_field_travels_onto_every_chunk(self):
        for chunk in self.chunks:
            self.assertEqual(chunk.doc_id, "CIRC-1")
            self.assertEqual(chunk.version, "v1")
            self.assertEqual(chunk.citation_key, "CIRC-1@v1")
            self.assertEqual(chunk.owner, "Product Head")
            self.assertEqual(chunk.kind, DocumentKind.RATE_SHEET)
            self.assertEqual(chunk.effective_from, date(2026, 1, 1))
            self.assertEqual(chunk.effective_to, date(2026, 12, 31))
            self.assertEqual(chunk.product_tags, ("personal_loan", "kcc"))
            self.assertEqual(chunk.doc_content_hash, self.document.content_hash())

    def test_a_chunk_answers_the_effective_question_without_the_registry(self):
        """Retrieval filters on chunks, and a registry lookup is a dependency.

        A chunk that has to ask a registry whether it is current is a chunk that
        gets served when the registry is unavailable — which is exactly when
        nobody is watching.
        """
        chunk = self.chunks[0]
        self.assertTrue(chunk.is_effective_on(date(2026, 6, 1)))
        self.assertFalse(chunk.is_effective_on(date(2027, 1, 1)))
        self.assertFalse(chunk.is_effective_on(date(2025, 12, 31)))


class ChunkIdentity(unittest.TestCase):
    def test_chunk_ids_are_stable_across_identical_runs(self):
        """Re-ingesting an unchanged document must not churn the index."""
        first = chunk_document(_doc(_words(900)))
        second = chunk_document(_doc(_words(900)))
        self.assertEqual([c.chunk_id for c in first], [c.chunk_id for c in second])

    def test_changed_text_changes_the_id_at_the_same_position(self):
        """A stale vector must not be able to answer under a new text's identity.

        With a positional-only id, an edited paragraph 3 keeps chunk id 3 and
        the vector store happily serves the old embedding for the new text. The
        citation then resolves to a passage that is not what was retrieved, and
        nothing surfaces it until a human reads both.
        """
        a = chunk_document(_doc("# H\n\nThe fee is 1.5%."))
        b = chunk_document(_doc("# H\n\nThe fee is 2.0%."))
        self.assertNotEqual(a[0].chunk_id, b[0].chunk_id)

    def test_the_citation_key_is_embedded_in_the_chunk_id(self):
        """A chunk id found in a log must name its document without a lookup."""
        chunk = chunk_document(_doc(_words(400)))[0]
        self.assertTrue(chunk.chunk_id.startswith("CIRC-1@v1#"))


class Corpus(unittest.TestCase):
    def test_chunk_corpus_preserves_document_order(self):
        docs = [_doc(_words(400), doc_id=f"D{i}") for i in range(3)]
        chunks = chunk_corpus(docs)
        self.assertEqual([c.doc_id for c in chunks], ["D0", "D1", "D2"])

    def test_empty_document_raises_at_the_registry_not_here(self):
        """The registry already refuses empty text; chunking need not repeat it."""
        with self.assertRaises(Exception):
            _doc("")

    def test_a_document_that_is_only_a_heading_produces_no_body_chunk(self):
        """A heading with nothing under it is not a passage, and must not index.

        Chunking it anyway puts a title into the index with no content behind
        it, and a title matches a query about its own subject better than the
        paragraph that actually answers it — so the empty chunk wins the
        retrieval and the answer has nothing to cite.
        """
        with self.assertRaises(ChunkingError):
            chunk_document(_doc("# Rates only, no body"))


class BudgetReport(unittest.TestCase):
    def test_report_names_the_counter_as_approximate(self):
        """A median token count read as exact is a median from the wrong tokenizer.

        The undercount is worst for Devanagari, which is one of the languages
        SRS GA-4 requires, so the caveat must travel with the number.
        """
        report = budget_report(chunk_document(_doc(_words(900))))
        self.assertIn("approximate", report["token_counter"])

    def test_empty_input_reports_zero_rather_than_raising(self):
        self.assertEqual(budget_report([]), {"chunks": 0})


if __name__ == "__main__":
    unittest.main()

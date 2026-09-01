"""Structure-aware chunking (WS-5.1.2).

Phase 5 §4 WS-5.1 step 2, verbatim:

    Chunking. Structure-aware: headings respected, tables kept intact; 300-800
    tokens per chunk; chunk metadata inherits registry fields.

Three instructions, and the middle one is load-bearing
-------------------------------------------------------
"Headings respected" and "metadata inherits" are hygiene. **"Tables kept
intact" is the requirement that decides whether the assistant can answer a rate
question at all**, and it is the one a naive chunker silently violates.

A rate table split across two chunks does not fail loudly. It retrieves. The
half holding the header row retrieves for "what are the rates", the half holding
the numbers retrieves for "12.5", and each half is a fluent, well-formed passage
that has lost the association between the two. The model then answers with a
rate from one product's row under another product's heading — a wrong number
with a real citation to a real document, which is the single hardest error in
this phase to detect after the fact.

So :func:`chunk_document` treats a table as atomic and will emit a chunk **over
the 800-token ceiling** rather than split one, recording the overflow. That is a
deliberate choice against the spec's letter in favour of its purpose, and it is
raised as a finding rather than done quietly.

What "structure-aware" means without a parser
-----------------------------------------------
This module reads Markdown-ish structure: ATX headings (``#``), pipe tables,
and blank-line-delimited paragraphs. Real bank circulars arrive as PDF and DOCX
and their structure is recovered by an extraction stage upstream of here
(Track B). That stage is not in this repository and this module does not pretend
to replace it: it consumes text that has *already* been given structure, which
is why :class:`Document.text` is the input rather than a file path.

What this does not port
-----------------------
No semantic or embedding-based chunking, no sliding-window overlap tuning
against a retrieval metric, no layout analysis. Overlap here is a fixed count of
carried sentences rather than a tuned parameter, because tuning it needs the
golden set (LH-602) and a chunker tuned against no metric is a chunker tuned
against its author's intuition.

Workstream: WS-5.1.2 (SRS §8.3.1)
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Callable, Sequence

from lending_hub.assistant.ports import count_tokens
from lending_hub.assistant.registry import Document, DocumentKind

#: Phase 5 §4 WS-5.1 step 2 and SRS §8.3.1 both write the budget as 300-800
#: tokens. [SPEC] — not a tuned value, and not this module's to move.
MIN_CHUNK_TOKENS = 300
MAX_CHUNK_TOKENS = 800

_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_RULE = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Zऀ-ॿ])")


class ChunkingError(Exception):
    """A document cannot be chunked."""


class BlockKind(str, Enum):
    """What a structural block is, which decides whether it may be split."""

    HEADING = "heading"
    PARAGRAPH = "paragraph"
    TABLE = "table"
    LIST = "list"


@dataclass(frozen=True)
class Block:
    """One structural unit of a document, before any budgeting.

    Separating parsing from packing is what makes "tables kept intact"
    enforceable: the packer never sees a table's rows, only a block it may take
    or leave whole.
    """

    kind: BlockKind
    text: str
    heading_path: tuple[str, ...] = ()
    """The heading trail above this block, outermost first."""

    @property
    def atomic(self) -> bool:
        """Whether this block must survive into exactly one chunk.

        Tables only. A long paragraph split mid-argument costs some coherence;
        a table split between its header and its numbers produces two passages
        that each retrieve confidently and have lost the association that gave
        them meaning.
        """
        return self.kind is BlockKind.TABLE


@dataclass(frozen=True)
class Chunk:
    """One indexable passage, carrying the governance record of its document.

    Every registry field is copied rather than referenced. A chunk sitting in a
    vector store years from now must be able to answer "was this servable on the
    day it was retrieved?" without a join back to a registry that may have been
    migrated — and the effective dates are what makes the answer possible.
    """

    chunk_id: str
    doc_id: str
    version: str
    citation_key: str
    text: str
    token_count: int
    heading_path: tuple[str, ...]

    ordinal: int
    """Position in the document's block groups. **Not** a dense index.

    Gaps are normal — a heading with no body under it is dropped rather than
    indexed, and its ordinal goes with it. Renumbering to close the gap would
    make every later chunk's id move whenever an empty section is added or
    removed, which churns the vector store for an edit that changed no text.
    """

    # Inherited registry fields (WS-5.1.2: "chunk metadata inherits registry fields")
    kind: DocumentKind = DocumentKind.FAQ
    owner: str = ""
    effective_from: date | None = None
    effective_to: date | None = None
    language: str = "en"
    product_tags: tuple[str, ...] = ()
    doc_content_hash: str = ""

    contains_table: bool = False
    oversize: bool = False
    """True when an atomic block pushed this chunk past the ceiling."""

    undersize: bool = False
    """True when the document simply had less text than the floor."""

    def is_effective_on(self, as_of: date) -> bool:
        """The same window test as the document, answerable without the registry.

        Retrieval filters on chunks, not documents, and a chunk that has to ask
        a registry whether it is current is a chunk that gets served when the
        registry is unavailable.
        """
        if self.effective_from is None:
            return False
        if as_of < self.effective_from:
            return False
        if self.effective_to is not None and as_of > self.effective_to:
            return False
        return True

    @property
    def heading_trail(self) -> str:
        return " › ".join(self.heading_path)


def parse_blocks(text: str) -> list[Block]:
    """Split document text into structural blocks, tracking the heading trail.

    The heading trail travels with each block because a rate figure under
    "Kisan Credit Card › Interest" and the same figure under "Personal Loan ›
    Interest" are different facts, and a chunk that dropped its heading path
    would make them indistinguishable to both the retriever and the reader.
    """
    blocks: list[Block] = []
    path: list[str] = []
    buffer: list[str] = []
    buffer_kind = BlockKind.PARAGRAPH

    def flush() -> None:
        nonlocal buffer, buffer_kind
        body = "\n".join(buffer).strip()
        if body:
            blocks.append(Block(kind=buffer_kind, text=body, heading_path=tuple(path)))
        buffer = []
        buffer_kind = BlockKind.PARAGRAPH

    for raw in text.splitlines():
        line = raw.rstrip()
        heading = _HEADING.match(line)

        if heading is not None:
            flush()
            level = len(heading.group(1))
            title = heading.group(2)
            del path[level - 1 :]
            path.append(title)
            blocks.append(Block(kind=BlockKind.HEADING, text=line.strip(), heading_path=tuple(path)))
            continue

        if _TABLE_ROW.match(line):
            if buffer_kind is not BlockKind.TABLE:
                flush()
                buffer_kind = BlockKind.TABLE
            buffer.append(line)
            continue

        if buffer_kind is BlockKind.TABLE:
            # A table ends at the first non-row line. Flush before deciding what
            # the new line is, so a paragraph immediately after a table does not
            # get absorbed into the atomic block.
            flush()

        if not line.strip():
            flush()
            continue

        if re.match(r"^\s*(?:[-*+]|\d+[.)])\s+", line):
            if buffer_kind is not BlockKind.LIST:
                flush()
                buffer_kind = BlockKind.LIST
            buffer.append(line)
            continue

        if buffer_kind is BlockKind.LIST:
            flush()

        buffer.append(line)

    flush()
    return blocks


def _split_paragraph(text: str, budget: int, counter: Callable[[str], int]) -> list[str]:
    """Break an over-long paragraph at sentence boundaries.

    Sentence boundaries rather than a fixed token stride: a stride cuts mid-
    clause, and the half-sentence that lands at the top of the next chunk reads
    as a fragment to a reranker and as a non-sequitur to a reader who is shown
    the passage as a citation.

    A single sentence longer than the budget is emitted whole. Splitting inside
    one is the same failure as splitting a table, in miniature — "the fee is
    waived" and "for accounts under six months" are each fluent and together
    mean something neither says alone.
    """
    sentences = [s for s in _SENTENCE_END.split(text) if s.strip()] or [text]
    out: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for sentence in sentences:
        tokens = counter(sentence)
        if current and current_tokens + tokens > budget:
            out.append(" ".join(current))
            current, current_tokens = [], 0
        current.append(sentence.strip())
        current_tokens += tokens
    if current:
        out.append(" ".join(current))
    return out


def chunk_document(
    document: Document,
    *,
    min_tokens: int = MIN_CHUNK_TOKENS,
    max_tokens: int = MAX_CHUNK_TOKENS,
    counter: Callable[[str], int] = count_tokens,
) -> list[Chunk]:
    """Chunk one document into indexable passages.

    ``counter`` is an argument so a Track B team binding a real tokenizer
    changes one call rather than searching for the approximation
    (:func:`lending_hub.assistant.ports.count_tokens` explains why an
    approximation is admissible for a budget and would not be for a threshold).

    The packing rule, in order of precedence:

    1. **A table is never split.** If it alone exceeds ``max_tokens`` it becomes
       its own chunk, flagged ``oversize``. Phase 5 §4 states both the ceiling
       and the intactness requirement and does not say which wins when they
       conflict; this module chooses intactness and raises the conflict as a
       finding, because the failure mode of a split rate table is a wrong number
       with a valid citation.
    2. **A heading starts a new chunk** when the current one has already reached
       the floor. Below the floor the heading joins the running chunk — a
       three-line section under its own heading is not worth an index entry of
       its own, and forcing one produces chunks that lose every retrieval to
       longer neighbours.
    3. **Everything else packs** until the ceiling.
    """
    if min_tokens <= 0 or max_tokens < min_tokens:
        raise ChunkingError(
            f"invalid budget: min={min_tokens}, max={max_tokens}. The [SPEC] band "
            f"is {MIN_CHUNK_TOKENS}-{MAX_CHUNK_TOKENS} (Phase 5 §4 WS-5.1 step 2)."
        )

    blocks = parse_blocks(document.text)
    if not blocks:
        raise ChunkingError(f"{document.doc_id}: no content to chunk")

    # Expand over-long non-atomic blocks first, so packing only ever sees units
    # that either fit or are deliberately atomic.
    units: list[Block] = []
    for block in blocks:
        if block.atomic or counter(block.text) <= max_tokens:
            units.append(block)
            continue
        for piece in _split_paragraph(block.text, max_tokens, counter):
            units.append(Block(kind=block.kind, text=piece, heading_path=block.heading_path))

    groups: list[list[Block]] = []
    current: list[Block] = []
    current_tokens = 0

    for unit in units:
        tokens = counter(unit.text)
        starts_section = unit.kind is BlockKind.HEADING and current_tokens >= min_tokens
        overflows = current and current_tokens + tokens > max_tokens
        if starts_section or overflows:
            groups.append(current)
            current, current_tokens = [], 0
        current.append(unit)
        current_tokens += tokens

    if current:
        groups.append(current)

    chunks: list[Chunk] = []
    for ordinal, group in enumerate(groups):
        body = "\n\n".join(block.text for block in group).strip()
        if not body:
            continue
        if all(block.kind is BlockKind.HEADING for block in group):
            # A heading with no body under it is not a passage. Indexing it
            # anyway is worse than dropping it: a title matches a query about
            # its own subject better than the paragraph that actually answers
            # it, so the empty chunk wins the retrieval and the answer has
            # nothing to cite.
            continue
        tokens = counter(body)
        heading_path = next(
            (b.heading_path for b in reversed(group) if b.heading_path), ()
        )
        contains_table = any(b.kind is BlockKind.TABLE for b in group)
        chunk_id = _chunk_id(document, ordinal, body)
        chunks.append(
            Chunk(
                chunk_id=chunk_id,
                doc_id=document.doc_id,
                version=document.version,
                citation_key=document.citation_key,
                text=body,
                token_count=tokens,
                heading_path=heading_path,
                ordinal=ordinal,
                kind=document.kind,
                owner=document.owner,
                effective_from=document.effective_from,
                effective_to=document.effective_to,
                language=document.language,
                product_tags=tuple(document.product_tags),
                doc_content_hash=document.content_hash(),
                contains_table=contains_table,
                oversize=tokens > max_tokens,
                undersize=tokens < min_tokens and len(groups) == 1,
            )
        )

    if not chunks:
        raise ChunkingError(f"{document.doc_id}: chunking produced nothing")
    return chunks


def _chunk_id(document: Document, ordinal: int, body: str) -> str:
    """A chunk id that changes when the text does.

    Deriving it from the content rather than only the position means a
    re-ingested document whose paragraph moved gets a new id, so a stale vector
    for the old text cannot answer under the new one's identity. That failure —
    an index holding a vector for text that no longer exists — is invisible
    until someone reads a citation and finds a passage that is not there.
    """
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:8]
    return f"{document.citation_key}#{ordinal:03d}-{digest}"


def chunk_corpus(
    documents: Sequence[Document],
    **kwargs,
) -> list[Chunk]:
    """Chunk many documents, preserving their order."""
    out: list[Chunk] = []
    for document in documents:
        out.extend(chunk_document(document, **kwargs))
    return out


def budget_report(chunks: Sequence[Chunk]) -> dict:
    """How well a chunking run held the [SPEC] budget, and where it did not.

    Reported rather than asserted. A run with three oversize chunks is not a
    failure — it is three rate tables that were kept intact, which is the
    correct outcome — but it is a number a reviewer should see, because the
    other reading is a chunker that has quietly stopped budgeting.
    """
    if not chunks:
        return {"chunks": 0}
    counts = sorted(c.token_count for c in chunks)
    oversize = [c for c in chunks if c.oversize]
    return {
        "chunks": len(chunks),
        "min_tokens": counts[0],
        "median_tokens": counts[len(counts) // 2],
        "max_tokens": counts[-1],
        "within_spec_band": sum(
            1 for c in chunks if MIN_CHUNK_TOKENS <= c.token_count <= MAX_CHUNK_TOKENS
        ),
        "oversize": len(oversize),
        "oversize_all_contain_tables": all(c.contains_table for c in oversize),
        "oversize_note": (
            "an oversize chunk is admissible only because it holds an atomic "
            "table (Phase 5 §4 WS-5.1 step 2 'tables kept intact'). An oversize "
            "chunk without a table is a packing bug — see finding P5-F1"
        ),
        "with_tables": sum(1 for c in chunks if c.contains_table),
        "token_counter": (
            "approximate (lending_hub.assistant.ports.count_tokens); a Track B "
            "tokenizer will report higher counts, especially for Devanagari"
        ),
    }

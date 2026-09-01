"""Document registry and dated-corpus ingestion (WS-5.1.1).

Phase 5 §4 WS-5.1 step 1, verbatim:

    Corpus governance first. Document registry: every policy circular, rate
    sheet, KFS template, FAQ gets {owner, effective-from, effective-to, version,
    product tags}. **Ingestion refuses undated documents.** Retrieval filters to
    currently-effective documents by default — stale-rate poisoning is the #1
    RAG failure in banks (SRS §8.3.1).

"Corpus before model" is the ordering, and it is right
------------------------------------------------------
The phase file puts corpus governance ahead of retrieval and generation, which
reads like project sequencing and is actually a correctness argument. A
retrieval system's quality ceiling is its corpus: no reranker recovers from an
index that holds last quarter's rate circular alongside this quarter's, because
both are *relevant*. The stale one is not a retrieval miss to be tuned away — it
is a correct answer to the wrong question, and it arrives with a citation.

So the two hard rules here are constructor and query invariants rather than
validation steps somebody calls:

* :class:`Document` cannot be constructed without ``effective_from``. Not
  "should not" — the constructor raises. An undated document has no defined
  answer to "is this current?", and the only safe treatment of an unanswerable
  question at query time is to have made it unaskable at ingest.
* :meth:`DocumentRegistry.effective` filters by default and
  :meth:`DocumentRegistry.all_versions` is the explicit opt-out. The default is
  the safe direction because the unsafe direction has to be typed out, and
  because a reviewer reading a call site can see which one was chosen.

What an effective date cannot express
--------------------------------------
Two circulars are simultaneously effective and the later one amends the earlier
*in part*. Both pass the date filter, which is correct — the unamended clauses
of the earlier one are still policy. But retrieval then returns both and the
model picks, and there is nothing in ``{effective_from, effective_to}`` that
says which passage won. Superseding the earlier document wholesale drops its
unamended clauses; leaving it drops nothing and asserts two rates.

Neither is safe, the phase file names neither, and this module therefore models
supersession as a *declared relation* (:attr:`Document.supersedes`) that is
recorded and reported but not automatically acted on. :meth:`conflicts` surfaces
the pairs a human must rule on. Raised as LH-608.

What this does not port
-----------------------
No document store, no OCR, no PDF or DOCX parsing, no ingestion scheduler. Text
extraction is upstream of this module by design: a registry that also parsed
files would couple the governance rules — which are policy and change rarely —
to format handling, which is engineering and changes constantly.

Workstream: WS-5.1.1 (SRS §8.3.1)
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Iterable, Iterator, Mapping, Sequence


class RegistryError(Exception):
    """A document cannot be registered, or a query cannot be answered."""


class UndatedDocument(RegistryError):
    """Ingestion refused a document with no effective-from date.

    Its own exception type rather than a generic validation error because it is
    the phase file's one explicitly named refusal, and because the operational
    response is specific: the fix is to go back to the document owner for the
    date, never to pick one from the file's modification time. A modification
    date is when someone saved a file; an effective date is when a policy began
    binding customers, and the gap between them is where a rate change lives.
    """


class DocumentKind(str, Enum):
    """The document families Phase 5 §4 WS-5.1 step 1 names.

    An enum rather than a free string because the family decides the governance
    treatment — a rate sheet's staleness is a customer-facing error, an FAQ's is
    a nuisance — and a free string lets ``"rate_sheet"`` and ``"rate sheet"``
    become two families that are governed differently by accident.
    """

    POLICY_CIRCULAR = "policy_circular"
    RATE_SHEET = "rate_sheet"
    KFS_TEMPLATE = "kfs_template"
    FAQ = "faq"
    REGULATION = "regulation"
    PRODUCT_SHEET = "product_sheet"


@dataclass(frozen=True)
class Document:
    """One registered document with its full governance record.

    Every field in Phase 5 §4 WS-5.1 step 1's ``{owner, effective-from,
    effective-to, version, product tags}`` is required except ``effective_to``,
    which is genuinely optional: an open-ended circular is the normal case and
    forcing a far-future sentinel date would make "no end date" and "ends in
    2099" indistinguishable in every downstream filter.

    ``owner`` is required and validated non-empty. Phase 5 §3 makes "corpus
    owners named per document family" an entry criterion, and an unowned
    document is one nobody will retire — which is how a corpus accumulates the
    stale documents this whole module exists to keep out of answers.
    """

    doc_id: str
    title: str
    kind: DocumentKind
    owner: str
    effective_from: date
    text: str
    version: str
    language: str = "en"
    effective_to: date | None = None
    product_tags: tuple[str, ...] = ()
    supersedes: tuple[str, ...] = ()
    """Documents this one replaces, declared by the owner. Never inferred."""

    source_uri: str = ""

    def __post_init__(self) -> None:
        if not self.doc_id:
            raise RegistryError("a document needs an id")
        if not self.title.strip():
            raise RegistryError(f"{self.doc_id}: a document needs a title")
        if not str(self.owner).strip():
            raise RegistryError(
                f"{self.doc_id}: a document needs a named owner. Phase 5 §3 makes "
                "corpus owners per document family an entry criterion — an unowned "
                "document is one nobody retires."
            )
        if self.effective_from is None:
            raise UndatedDocument(
                f"{self.doc_id}: ingestion refuses an undated document "
                "(Phase 5 §4 WS-5.1 step 1). Ask the owner for the effective "
                "date; a file modification time is not one."
            )
        if not isinstance(self.effective_from, date):
            raise UndatedDocument(
                f"{self.doc_id}: effective_from must be a date, got "
                f"{type(self.effective_from).__name__}"
            )
        if self.effective_to is not None:
            if not isinstance(self.effective_to, date):
                raise RegistryError(f"{self.doc_id}: effective_to must be a date")
            if self.effective_to < self.effective_from:
                raise RegistryError(
                    f"{self.doc_id}: effective_to {self.effective_to} precedes "
                    f"effective_from {self.effective_from}. A document that expired "
                    "before it began is never servable, and silently registering it "
                    "hides a data-entry error behind an empty result set."
                )
        if not str(self.version).strip():
            raise RegistryError(
                f"{self.doc_id}: a document needs a version. Two texts under one "
                "id with no version cannot be told apart in a citation, and a "
                "citation nobody can resolve to an exact text is not an audit trail."
            )
        if not self.text.strip():
            raise RegistryError(f"{self.doc_id}: a document with no text is not a document")

    def is_effective_on(self, as_of: date) -> bool:
        """Whether this document is in force on ``as_of``.

        Inclusive at both ends. A circular effective from the 1st binds on the
        1st, and one effective to the 31st binds on the 31st — the half-open
        convention that is right for timestamps is wrong for policy dates, and
        getting it wrong loses or duplicates exactly one day of coverage at
        every rate change.
        """
        if as_of < self.effective_from:
            return False
        if self.effective_to is not None and as_of > self.effective_to:
            return False
        return True

    @property
    def citation_key(self) -> str:
        """The stable handle a citation resolves to: id plus version.

        Version is part of the key rather than metadata beside it. A citation to
        ``CIRC-2026-04`` is ambiguous once that circular is amended; a citation
        to ``CIRC-2026-04@v2`` names one text forever, which is what
        reproducing an eight-year-old answer (Master §3.3) requires.
        """
        return f"{self.doc_id}@{self.version}"

    def content_hash(self) -> str:
        """Content hash over the text and the governance fields that bind it.

        Recorded on every chunk so a chunk found in an index years later can be
        proven to have come from this exact text under these exact dates. The
        dates are inside the hash because the same words under different
        effective dates are a different fact.
        """
        payload = json.dumps(
            {
                "doc_id": self.doc_id,
                "version": self.version,
                "effective_from": self.effective_from.isoformat(),
                "effective_to": self.effective_to.isoformat() if self.effective_to else None,
                "text": self.text,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Conflict:
    """Two documents that a human must rule between (LH-608).

    Not an error. A conflict is the normal state of a policy corpus mid-amendment
    and the registry's job is to make it visible, not to resolve it — resolving
    it means choosing which of two effective policies a customer is told about,
    which is a Compliance decision wearing a data-engineering costume.
    """

    earlier: str
    later: str
    kind: DocumentKind
    product_tag: str
    reason: str


class DocumentRegistry:
    """The corpus, with its governance rules attached.

    Deliberately not a dict. Every read path here is a policy decision —
    "currently effective", "as of a past date", "every version" — and a mapping
    would let a caller iterate the raw values and skip all three.
    """

    def __init__(self) -> None:
        self._by_key: dict[str, Document] = {}

    def __len__(self) -> int:
        return len(self._by_key)

    def __iter__(self) -> Iterator[Document]:
        return iter(sorted(self._by_key.values(), key=lambda d: d.citation_key))

    def ingest(self, document: Document) -> Document:
        """Register one document. Raises on a duplicate citation key.

        The duplicate check is on ``id@version``, not on id: re-registering the
        same version with different text is the failure worth catching, because
        it means two different texts are both answering to one citation and no
        stored answer can be reproduced.
        """
        key = document.citation_key
        existing = self._by_key.get(key)
        if existing is not None:
            if existing.content_hash() == document.content_hash():
                return existing
            raise RegistryError(
                f"{key} is already registered with different content. Bump the "
                "version — two texts under one citation key make every stored "
                "answer citing it unreproducible."
            )
        self._by_key[key] = document
        return document

    def ingest_all(self, documents: Iterable[Document]) -> list[Document]:
        return [self.ingest(document) for document in documents]

    def get(self, citation_key: str) -> Document:
        """Resolve a citation key to its exact text.

        Raises rather than returning ``None``: a citation that does not resolve
        is not a missing document, it is an answer claiming a source that does
        not exist, and the caller
        (:func:`lending_hub.assistant.answer.validate`) must treat it as an
        uncited claim rather than a soft warning.
        """
        try:
            return self._by_key[citation_key]
        except KeyError:
            raise RegistryError(
                f"citation {citation_key!r} resolves to no registered document"
            ) from None

    def all_versions(self) -> list[Document]:
        """Every registered document, effective or not. The explicit opt-out.

        Named to be conspicuous at the call site. Audit, migration and
        supersession review need the whole corpus; retrieval never does, and a
        retrieval path calling this is a bug a reviewer can see by the method
        name alone.
        """
        return list(self)

    def effective(
        self,
        as_of: date,
        *,
        kind: DocumentKind | None = None,
        product: str | None = None,
        language: str | None = None,
    ) -> list[Document]:
        """Documents in force on ``as_of``, optionally narrowed.

        ``as_of`` is a required argument with no default, and that is the
        module's second-most important line after the undated refusal. A default
        of "today" would make the answer to a question depend on when it was
        asked rather than on when it was *about* — and every replay of a stored
        conversation (Master §3.3 requires eight years of them) would silently
        re-answer against today's corpus and call it a reproduction.
        """
        if not isinstance(as_of, date):
            raise RegistryError(
                "effective() needs an as-of date. There is no default: a "
                "replayed conversation must resolve against the corpus that was "
                "in force when it happened, not the one in force when it is replayed."
            )
        out = []
        for document in self:
            if not document.is_effective_on(as_of):
                continue
            if kind is not None and document.kind is not kind:
                continue
            if product is not None and product not in document.product_tags:
                continue
            if language is not None and document.language != language:
                continue
            out.append(document)
        return out

    def expired(self, as_of: date) -> list[Document]:
        """Documents whose effective window has closed.

        Kept rather than deleted. Phase 5 §5 step 4 requires monitoring that no
        expired document is *servable*, which is a different requirement from
        not being *stored* — an answer given in 2026 and audited in 2031 has to
        resolve its citations against the text that was live in 2026.
        """
        return [
            document
            for document in self
            if document.effective_to is not None and as_of > document.effective_to
        ]

    def not_yet_effective(self, as_of: date) -> list[Document]:
        """Documents dated into the future.

        A real state, not a data error: a rate circular is published before it
        binds. It is separated from ``expired`` because the two need opposite
        operational responses — a future document is waiting and correct, an
        expired one is finished and dangerous.
        """
        return [document for document in self if as_of < document.effective_from]

    def superseded(self) -> dict[str, list[str]]:
        """Declared supersession, as ``{superseded_id: [superseding ids]}``.

        Built only from owner declarations. Nothing here infers supersession
        from dates or titles: two circulars with adjacent dates on the same
        product are the *usual* case and are usually not supersession, and an
        inference that is right nine times in ten produces a corpus where nobody
        knows which tenth is wrong.
        """
        out: dict[str, list[str]] = {}
        for document in self:
            for target in document.supersedes:
                out.setdefault(target, []).append(document.doc_id)
        for key in out:
            out[key] = sorted(set(out[key]))
        return out

    def conflicts(self, as_of: date) -> list[Conflict]:
        """Pairs of simultaneously-effective documents a human must rule on.

        The LH-608 surface. Two documents conflict here when they are both in
        force, share a kind and a product tag, and neither declares supersession
        of the other. That is deliberately a *wide* net — it will flag pairs
        that turn out to be complementary — because the cost of a false flag is
        a Compliance review and the cost of a miss is two live rates.

        It is not a semantic comparison and does not pretend to be. Whether the
        later circular amends the earlier in part is a reading question, and
        this module's whole position on LH-608 is that the reading belongs to a
        human.
        """
        live = self.effective(as_of)
        declared = self.superseded()
        out: list[Conflict] = []
        for index, earlier in enumerate(live):
            for later in live[index + 1 :]:
                if earlier.kind is not later.kind:
                    continue
                shared = sorted(set(earlier.product_tags) & set(later.product_tags))
                if not shared:
                    continue
                if later.doc_id in declared.get(earlier.doc_id, []):
                    continue
                if earlier.doc_id in declared.get(later.doc_id, []):
                    continue
                if earlier.doc_id == later.doc_id:
                    continue
                first, second = sorted((earlier, later), key=lambda d: d.effective_from)
                out.append(
                    Conflict(
                        earlier=first.citation_key,
                        later=second.citation_key,
                        kind=first.kind,
                        product_tag=shared[0],
                        reason=(
                            "both effective, same kind and product, and neither "
                            "declares supersession of the other. A partial "
                            "amendment cannot be expressed in effective dates "
                            "alone — LH-608."
                        ),
                    )
                )
        return out

    def governance_report(self, as_of: date) -> dict:
        """The WS-5.1.1 compliance view: what is servable and what is not.

        Phase 5 §5 step 4 makes "corpus registry compliance monitored (no
        undated/expired documents servable)" a steady-state duty. Undated
        documents cannot be counted here because they were never admitted —
        which is the point, and is stated in the output so a reader does not
        take a zero for a measurement.
        """
        live = self.effective(as_of)
        expired = self.expired(as_of)
        future = self.not_yet_effective(as_of)
        conflicts = self.conflicts(as_of)
        return {
            "as_of": as_of.isoformat(),
            "registered": len(self),
            "effective": len(live),
            "expired_retained": len(expired),
            "not_yet_effective": len(future),
            "undated": 0,
            "undated_note": (
                "structurally zero: Document.__post_init__ refuses an undated "
                "document, so an undated one cannot be registered to be counted "
                "(Phase 5 §4 WS-5.1 step 1)"
            ),
            "unowned": 0,
            "unowned_note": "structurally zero: a document without an owner does not construct",
            "kinds": {
                kind.value: sum(1 for d in live if d.kind is kind) for kind in DocumentKind
            },
            "languages": sorted({d.language for d in live}),
            "conflicts": [
                {
                    "earlier": c.earlier,
                    "later": c.later,
                    "kind": c.kind.value,
                    "product": c.product_tag,
                }
                for c in conflicts
            ],
            "conflict_count": len(conflicts),
            "corpus_present": len(self) > 0,
            "corpus_note": (
                "" if len(self) else
                "no corpus is loaded. The bank's policy circulars, rate sheets, "
                "KFS templates and FAQs are LH-601, and nothing substitutes: "
                "another institution's circular is a different policy, not a "
                "noisy copy of this one."
            ),
        }

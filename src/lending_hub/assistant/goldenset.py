"""The golden set as a typed, versioned artifact (WS-5.1.3).

Phase 5 §4 WS-5.1 step 3, verbatim:

    Golden set before pipeline. ≥ 500 question → answer → source-passage triples
    curated by product SMEs, covering each product, each language, and known
    tricky cases (fee edge cases, eligibility boundaries). This set is the
    phase's measuring stick; it is versioned and refreshed quarterly.

The harness ships before the set, and that ordering is the point
------------------------------------------------------------------
There is no golden set here (LH-602) and there cannot be one: ≥ 500 triples
curated by product SMEs is `[DATA]` produced by people, and it is derivative of
the corpus (LH-601), because a triple's *answer* is only correct relative to
documents that exist.

So what this module contains is the measuring instrument. That is worth doing
ahead of the thing it measures, for a reason that is not obvious: **a measuring
stick built after the thing being measured is built to fit it.** A golden set
authored while a retrieval pipeline is being tuned drifts towards questions the
pipeline answers well, and nobody involved intends it or notices. The harness
existing first means the set arrives into a fixed definition of admissible
rather than the other way round.

"The phase's measuring stick" makes admission a gate of its own
-----------------------------------------------------------------
If the set defines whether the phase passes, then the set itself needs a
standard, and the phase file gives four fragments of one: at least 500 triples,
coverage of each product, coverage of each language, and the tricky cases. Three
of those are checkable here; the fourth is not, because "known tricky cases" is
a judgement about a corpus nobody has written.

:meth:`GoldenSet.admission` therefore reports each criterion separately and
refuses to reduce them to a boolean, and :func:`evaluate` refuses to compute a
hit-rate on a set that fails admission. That refusal is the module's central
one: a hit-rate of 0.97 measured on 40 questions is not a worse version of the
gate number, it is a different quantity with the same name.

What the phase file leaves unspecified, found by building
-----------------------------------------------------------
**The per-language slice size.** §4 WS-5.3.4 says a language ships only when its
slice passes the same gates as English, and SRS GA-4 requires Hindi plus two
regional languages. Neither says how large a slice must be for a 95% hit-rate to
mean anything. A 20-triple Hindi slice passing at 95% is four misses and a coin
flip — and it would be reported in the same column as English's 500. LH-610.

What this does not port
-----------------------
No annotation tooling, no inter-annotator agreement, no active-learning loop for
selecting questions. The quarterly refresh is a process, not a function: this
module versions a set and reports what changed between versions, and who decides
what goes in is the SMEs' job by design.

Workstream: WS-5.1.3 (SRS §8.3.4)
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from lending_hub.assistant.retrieval import HIT_RATE_GATE, HIT_RATE_K, hit_rate_at_k
from lending_hub.definitions.provenance import Pending

#: Phase 5 §4 WS-5.1 step 3, verbatim: "≥ 500 question → answer → source-passage
#: triples". [SPEC] — the floor for the set as a whole.
MIN_TRIPLES = 500

#: The per-language minimum. **Not specified anywhere** — §4 WS-5.3.4 requires a
#: language to pass "the same gates as English" and never says how many triples
#: that needs. Found by building.
MIN_TRIPLES_PER_LANGUAGE = Pending(
    owner="Compliance + Product SMEs",
    ticket="LH-610",
    note="the launch language list, and the minimum slice size a per-language hit-rate needs to mean anything",
)

#: The set itself.
GOLDEN_SET = Pending(
    owner="Product SMEs",
    ticket="LH-602",
    note="≥ 500 question → answer → source-passage triples, per product and per language",
)


class GoldenSetError(Exception):
    """A triple or a set is malformed, or a metric cannot be computed on it."""


@dataclass(frozen=True)
class Triple:
    """One question → answer → source-passage triple.

    ``source_chunks`` is required and non-empty, and that is the constraint
    doing the work. A triple whose answer has no source passage is not a
    harder question — it is an *unanswerable* one, and unanswerable questions
    belong to the refusal path (Phase 5 §8: "any answer where retrieval returned
    nothing — refuse + escalate"). Scoring one as a retrieval miss blames the
    retriever for behaving correctly, and a set containing them makes the gate
    unreachable for reasons that have nothing to do with retrieval.
    """

    triple_id: str
    question: str
    answer: str
    source_chunks: tuple[str, ...]
    product: str
    language: str = "en"
    tricky: bool = False
    """Marked by the SME as a fee edge case, eligibility boundary or similar."""

    notes: str = ""

    def __post_init__(self) -> None:
        if not self.triple_id:
            raise GoldenSetError("a triple needs an id")
        if not self.question.strip():
            raise GoldenSetError(f"{self.triple_id}: a triple needs a question")
        if not self.answer.strip():
            raise GoldenSetError(
                f"{self.triple_id}: a triple needs a reference answer. A question "
                "with no answer measures retrieval and nothing else, and the set "
                "is the measuring stick for faithfulness too."
            )
        if not self.source_chunks:
            raise GoldenSetError(
                f"{self.triple_id}: a triple needs at least one source passage. A "
                "question with no source is unanswerable from the corpus, which "
                "belongs to the refusal path — scoring it as a retrieval miss "
                "blames the retriever for correct behaviour."
            )
        if not self.product.strip():
            raise GoldenSetError(
                f"{self.triple_id}: a triple needs a product. Coverage per product "
                "is a §4 WS-5.1 admission criterion and cannot be checked without it."
            )
        if not self.language.strip():
            raise GoldenSetError(f"{self.triple_id}: a triple needs a language")


@dataclass(frozen=True)
class SliceReport:
    """One language or product slice, and whether it can carry a gate number."""

    name: str
    triples: int
    minimum: int | None
    """``None`` while the per-slice minimum is unratified (LH-610)."""

    @property
    def sufficient(self) -> bool | None:
        """Whether the slice is large enough. ``None`` means unknown, not False.

        Three states rather than two, and the third is the honest one: a slice
        of 40 is not "failing", it is *unassessable*, because nobody has said
        what a slice needs. Collapsing that into False would make LH-610 look
        like a failing slice that more curation fixes, and collapsing it into
        True would let a 20-triple Hindi slice report a 95% next to English's.
        """
        if self.minimum is None:
            return None
        return self.triples >= self.minimum


@dataclass(frozen=True)
class Admission:
    """Whether a set may be used as the phase's measuring stick.

    Reports each criterion separately and offers no single boolean. The
    criteria fail for different reasons and are fixed by different people — a
    small set needs more SME time, a missing language needs a launch decision
    (LH-610), and missing tricky cases needs someone who knows where the fee
    edge cases are.
    """

    total: int
    meets_minimum: bool
    products: tuple[str, ...]
    languages: tuple[str, ...]
    per_language: tuple[SliceReport, ...]
    per_product: tuple[SliceReport, ...]
    tricky_cases: int
    has_tricky_cases: bool

    @property
    def admissible(self) -> bool:
        """Whether the checkable criteria pass.

        Deliberately does **not** cover per-language sufficiency, because that
        criterion has no ratified standard (LH-610). A property that silently
        skipped an unratified criterion while looking like a full check is how
        an unmeasured thing becomes a passed thing.
        """
        return self.meets_minimum and self.has_tricky_cases and bool(self.products)

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "minimum": MIN_TRIPLES,
            "meets_minimum": self.meets_minimum,
            "products": list(self.products),
            "languages": list(self.languages),
            "tricky_cases": self.tricky_cases,
            "has_tricky_cases": self.has_tricky_cases,
            "admissible": self.admissible,
            "per_language": [
                {"name": s.name, "triples": s.triples, "sufficient": s.sufficient}
                for s in self.per_language
            ],
            "per_language_note": (
                "'sufficient': null means unassessable, not failing. §4 WS-5.3.4 "
                "requires a language to pass the same gates as English and never "
                "says how many triples that needs — a 20-triple slice passing at "
                "95% is four misses and a coin flip, reported in the same column "
                "as English's 500. LH-610"
            ),
            "unmeasured_criterion": (
                "'covering known tricky cases' is checked here only as a count of "
                "SME-marked triples. Whether the marked cases are the *right* "
                "tricky cases is a judgement about a corpus nobody has written "
                "(LH-601)"
            ),
        }


class GoldenSet:
    """A versioned set of triples, with its admission criteria attached."""

    def __init__(self, triples: Sequence[Triple] = (), *, version: str = "unversioned") -> None:
        self._triples: dict[str, Triple] = {}
        self.version = version
        for triple in triples:
            self.add(triple)

    def __len__(self) -> int:
        return len(self._triples)

    def __iter__(self):
        return iter(sorted(self._triples.values(), key=lambda t: t.triple_id))

    @property
    def empty(self) -> bool:
        return not self._triples

    def add(self, triple: Triple) -> None:
        if triple.triple_id in self._triples:
            raise GoldenSetError(
                f"{triple.triple_id} is already in the set. A duplicate id means "
                "one question is scored twice, which weights it twice in the "
                "hit rate without anybody choosing to."
            )
        self._triples[triple.triple_id] = triple

    def slice(self, *, language: str | None = None, product: str | None = None) -> list[Triple]:
        return [
            triple
            for triple in self
            if (language is None or triple.language == language)
            and (product is None or triple.product == product)
        ]

    def content_hash(self) -> str:
        """Content hash over every triple.

        Recorded beside any metric computed from this set. Quarterly refresh
        (§4 WS-5.1 step 3) means the measuring stick changes, and a hit-rate
        that moved between quarters could be the retriever or the set — the
        hash is what makes the two distinguishable after the fact.
        """
        payload = [
            {
                "id": t.triple_id,
                "question": t.question,
                "answer": t.answer,
                "sources": list(t.source_chunks),
                "product": t.product,
                "language": t.language,
            }
            for t in self
        ]
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    def admission(self) -> Admission:
        """Whether this set may serve as the phase's measuring stick."""
        languages = Counter(t.language for t in self)
        products = Counter(t.product for t in self)

        minimum = None
        if not isinstance(MIN_TRIPLES_PER_LANGUAGE, Pending):  # pragma: no cover - LH-610
            minimum = MIN_TRIPLES_PER_LANGUAGE

        tricky = sum(1 for t in self if t.tricky)
        return Admission(
            total=len(self),
            meets_minimum=len(self) >= MIN_TRIPLES,
            products=tuple(sorted(products)),
            languages=tuple(sorted(languages)),
            per_language=tuple(
                SliceReport(name=name, triples=count, minimum=minimum)
                for name, count in sorted(languages.items())
            ),
            per_product=tuple(
                SliceReport(name=name, triples=count, minimum=None)
                for name, count in sorted(products.items())
            ),
            tricky_cases=tricky,
            has_tricky_cases=tricky > 0,
        )

    def diff(self, other: "GoldenSet") -> dict:
        """What changed between two versions. The quarterly-refresh audit view."""
        mine = {t.triple_id for t in self}
        theirs = {t.triple_id for t in other}
        changed = [
            triple_id
            for triple_id in sorted(mine & theirs)
            if self._triples[triple_id] != other._triples[triple_id]
        ]
        return {
            "from_version": other.version,
            "to_version": self.version,
            "added": sorted(mine - theirs),
            "removed": sorted(theirs - mine),
            "changed": changed,
            "from_hash": other.content_hash(),
            "to_hash": self.content_hash(),
            "note": (
                "a metric that moved between refreshes could be the retriever or "
                "the set. Report both hashes with any number computed from either"
            ),
        }


@dataclass(frozen=True)
class Evaluation:
    """A hit-rate measured on a golden set, with the set's identity attached."""

    hit_rate: float
    k: int
    gate: float
    triples_scored: int
    set_version: str
    set_hash: str
    language: str | None = None

    @property
    def passes(self) -> bool:
        return self.hit_rate >= self.gate

    def to_dict(self) -> dict:
        return {
            "hit_rate_at_k": self.hit_rate,
            "k": self.k,
            "gate": self.gate,
            "passes": self.passes,
            "triples_scored": self.triples_scored,
            "golden_set_version": self.set_version,
            "golden_set_hash": self.set_hash,
            "language": self.language,
        }


def evaluate(
    golden: GoldenSet,
    retrieved: Mapping[str, Sequence[str]],
    *,
    k: int = HIT_RATE_K,
    language: str | None = None,
    require_admission: bool = True,
) -> Evaluation:
    """Hit-rate@k of ``retrieved`` against ``golden``.

    ``retrieved`` maps triple id to the ranked chunk ids the retriever returned.

    **Refuses on a set that fails admission**, and that refusal is the module's
    central one. A hit-rate of 0.97 measured on 40 questions is not a rougher
    version of the gate number — it is a different quantity carrying the same
    name, and once it is in a report nothing distinguishes them. ``require_admission``
    exists so a *development* run can measure a partial set, and the resulting
    :class:`Evaluation` still carries the set's hash and size, so a number
    produced that way is identifiable later.

    A triple with no retrieval result scores as a miss rather than being skipped.
    Skipping is the failure that inflates: a retriever that errored on the
    hardest 10% would report a hit-rate over the easy 90% and look better for
    having failed.
    """
    triples = golden.slice(language=language) if language else list(golden)
    if not triples:
        raise GoldenSetError(
            "there are no triples to score"
            + (f" for language {language!r}" if language else "")
            + ". The golden set is LH-602; the harness exists ahead of it so that "
            "the set arrives into a fixed definition of admissible."
        )

    if require_admission:
        admission = golden.admission()
        if not admission.admissible:
            raise GoldenSetError(
                f"this set is not admissible as a measuring stick: {admission.total} "
                f"triples against a minimum of {MIN_TRIPLES}, tricky cases "
                f"{'present' if admission.has_tricky_cases else 'absent'}. A "
                "hit-rate computed here is a different quantity with the same "
                "name — pass require_admission=False for a development run, and "
                "the result will carry the set's size and hash."
            )

    got = [list(retrieved.get(t.triple_id, ())) for t in triples]
    want = [list(t.source_chunks) for t in triples]
    return Evaluation(
        hit_rate=hit_rate_at_k(got, want, k=k),
        k=k,
        gate=HIT_RATE_GATE,
        triples_scored=len(triples),
        set_version=golden.version,
        set_hash=golden.content_hash(),
        language=language,
    )


def harness_report(golden: GoldenSet | None = None) -> dict:
    """The WS-5.1.3 deliverable's state, for the gate pack."""
    if golden is None or golden.empty:
        return {
            "present": False,
            "triples": 0,
            "minimum": MIN_TRIPLES,
            "blocking_ticket": "LH-602",
            "depends_on": "LH-601",
            "note": (
                "the harness ships and the set does not. ≥ 500 triples curated by "
                "product SMEs is [DATA] produced by people, and it is derivative "
                "of the corpus: a triple's answer is only correct relative to "
                "documents that exist. The ordering is deliberate — a measuring "
                "stick built after the thing it measures is built to fit it"
            ),
            "per_language_minimum": str(MIN_TRIPLES_PER_LANGUAGE),
        }
    admission = golden.admission()
    return {
        "present": True,
        "version": golden.version,
        "hash": golden.content_hash(),
        "admission": admission.to_dict(),
        "per_language_minimum": str(MIN_TRIPLES_PER_LANGUAGE),
    }

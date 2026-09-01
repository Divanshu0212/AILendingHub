"""The Track B seam for every model and store Phase 5 needs and this repo has none of.

ADR-0003 keeps the core packages stdlib-only, so the four components Phase 5
cannot implement locally appear here as protocols: a generation model, an
embedding model, a vector store, and a cross-encoder reranker. Track A satisfies
them in memory or not at all; Track B binds a real model
(:doc:`LH-604 </docs/phase5/blocking_tickets>`).

Why these are protocols and not stubs
-------------------------------------
The same reason :mod:`lending_hub.agri.ports` gives, sharpened by what a
language model is. A stubbed :class:`SceneSource` returns a plausible NDVI and
somebody notices when the crop is wrong. A stubbed
:class:`GenerationModel` returns plausible *prose*, and plausible prose about a
loan is indistinguishable from correct prose about a loan until a regulator
reads it.

So :class:`UnboundPort` is raised rather than a canned answer being returned. A
pipeline that ran end to end against a stub would produce a faithfulness score,
a hit-rate and a containment rate — every one of them a property of the stub —
and those numbers would be in a report before anyone asked where they came from.

What this does not port
-----------------------
No model weights, no tokenizer, no HTTP client, no vector index. There is no
approximate-nearest-neighbour search here and no attention implementation;
:class:`VectorStore` and :class:`GenerationModel` are where those live on
Track B (FAISS/pgvector/Vespa; a hosted or self-hosted LLM).

One thing is deliberately *not* behind a port: **token counting**.
:func:`count_tokens` is a whitespace-and-punctuation approximation that the
chunker uses to hold Phase 5 §4's 300-800 token budget, and it is here rather
than in :mod:`~lending_hub.assistant.chunking` so that a Track B team binding a
real tokenizer changes one function. See its docstring for why an approximation
is admissible where a threshold would not be.

Workstream: WS-5.1, WS-5.2, WS-5.3 (SRS §8.3.1, §8.3.2)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, Sequence, runtime_checkable


class UnboundPort(Exception):
    """A Track B model or store was called and no adapter is bound.

    Deliberately an exception rather than a fallback. Every fallback available
    here is worse than stopping: a canned answer is ungrounded prose, an empty
    retrieval silently turns a grounded question into a refusal, and a zero
    embedding makes every document equidistant from every query, which looks
    like poor relevance rather than an unbound model.
    """


class ModelUnavailable(Exception):
    """A bound model exists but could not answer this call.

    Distinct from :class:`UnboundPort` because the operational response differs:
    an unbound port is a deployment error, a timeout or a rate limit is a
    runtime condition the assistant handles by escalating to a human. Merging
    them means a misconfigured environment looks like a busy one and never gets
    fixed.
    """


@dataclass(frozen=True)
class GenerationRequest:
    """One call to a generation model.

    ``system`` and ``context`` are separate fields rather than one concatenated
    prompt, and that is the WS-5.4 instruction/data separation requirement
    expressed as a type. Greshake et al.'s indirect-injection attack works
    because retrieved text and operator instructions arrive at the model as one
    undifferentiated string; a caller that has to put them in different fields
    cannot merge them by accident, and a Track B adapter that concatenates them
    anyway is doing so visibly at one reviewable place.
    """

    system: str
    """Operator instructions. Trusted."""

    context: Sequence[str]
    """Retrieved passages. **Untrusted** — see :mod:`lending_hub.assistant.guardrails`."""

    question: str
    """The user's turn. **Untrusted.**"""

    language: str = "en"
    max_tokens: int | None = None


@dataclass(frozen=True)
class GenerationResult:
    """What a generation model returned, before any validation.

    ``text`` has been through nothing at this point. It is not an answer until
    :func:`lending_hub.assistant.answer.validate` has run over it, which is why
    this type is deliberately not called ``Answer``.
    """

    text: str
    model_id: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


@runtime_checkable
class GenerationModel(Protocol):
    """The LLM. Track B binds one; nothing in this repository does.

    An implementation must not add retrieval of its own. The assistant's
    guarantee is that every servable number traces to a retrieved chunk or a
    tool result, and a model that fetched its own context would put passages
    into the answer that the validator's citation resolver has never seen — so
    every claim from them reads as uncited and the whole answer collapses to a
    handoff. That failure is at least loud; the quiet version is an adapter that
    also registers those passages, which breaks the guarantee outright.
    """

    def generate(self, request: GenerationRequest) -> GenerationResult: ...


@runtime_checkable
class EmbeddingModel(Protocol):
    """Dense vector encoder for the hybrid retriever's second leg.

    Track B: any strong open embedding model (SRS §8.3.1). Vectors must be
    returned in a fixed dimension for the whole index — a store holding two
    dimensionalities has no defined similarity, and the failure surfaces as
    nonsense rankings rather than an exception.
    """

    def encode(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...

    @property
    def dimension(self) -> int: ...


@dataclass(frozen=True)
class VectorHit:
    """One dense-retrieval result."""

    chunk_id: str
    score: float


@runtime_checkable
class VectorStore(Protocol):
    """Approximate-nearest-neighbour index over chunk embeddings.

    Track B: FAISS, pgvector, Vespa, or the platform's managed equivalent.
    """

    def upsert(self, chunk_id: str, vector: Sequence[float]) -> None: ...

    def search(self, vector: Sequence[float], k: int) -> Sequence[VectorHit]: ...


@runtime_checkable
class Reranker(Protocol):
    """Cross-encoder reranking a fused candidate list (SRS §8.3.1 step 2).

    Separate from :class:`EmbeddingModel` because it is a different kind of
    model with different economics: a bi-encoder embeds documents once at index
    time, a cross-encoder scores every (query, document) pair at query time. A
    port that merged them would hide the fact that raising ``k`` into the
    reranker raises per-query cost linearly, which is the parameter Track B will
    actually tune.
    """

    def rerank(self, query: str, passages: Sequence[str]) -> Sequence[float]:
        """Relevance scores for each passage, aligned to the input order.

        Returning scores rather than a reordered list is deliberate: the caller
        fuses them with lexical evidence, and a port that had already sorted
        would have discarded the margins that fusion needs.
        """
        ...


@runtime_checkable
class EntailmentModel(Protocol):
    """Does this passage support this claim? — the faithfulness scorer's core.

    RAGAS (arXiv:2309.15217) decomposes an answer into claims and asks, per
    claim, whether the retrieved context entails it. The decomposition and the
    aggregation are deterministic and live in
    :mod:`lending_hub.assistant.faithfulness`; **this judgement is not**, and
    pretending otherwise is the trap. Lexical overlap between a claim and a
    passage is not entailment: "the fee is waived for accounts under six months"
    and "the fee applies to accounts under six months" overlap almost entirely
    and mean opposite things.

    So there is no local implementation, and :func:`score_faithfulness` refuses
    without a bound model rather than falling back to overlap. A groundedness
    score computed from word overlap would be highest exactly where a negation
    was flipped.
    """

    def entails(self, premise: str, claim: str) -> float:
        """Probability in [0, 1] that ``premise`` supports ``claim``."""
        ...


#: Words are split on whitespace, then on the punctuation that carries meaning
#: in banking text. ``12.5%`` is two tokens to a real tokenizer and one word to
#: ``str.split``; ``KCC/MCLR`` is two terms and one whitespace token.
_TOKEN_SPLIT = re.compile(r"[^\w%₹.]+|(?<=\d)(?=%)|(?<=[a-zA-Z])(?=\d)")


def count_tokens(text: str) -> int:
    """Approximate token count for the WS-5.1.2 chunk budget.

    **This is an approximation and it is admissible, which needs justifying**,
    because the rest of this repository refuses approximations of exactly this
    shape.

    The grounding contract forbids inventing a *threshold* — a number that
    decides an outcome nobody can later re-derive. 300-800 tokens is not that.
    It is `[SPEC]` from Phase 5 §4 WS-5.1.2, and it is a budget with two
    tolerant ends: chunks a little small cost recall, chunks a little large cost
    context window. Neither end produces a wrong answer that looks right, which
    is the property that makes a number dangerous here.

    What *would* be wrong is pretending this equals a model's tokenizer. It does
    not — it has no vocabulary, no byte-pair merges and no language-specific
    behaviour, and it will undercount Devanagari substantially because it counts
    whitespace-delimited words where a BPE tokenizer emits several subwords per
    word. So a Track B team binding a real tokenizer replaces this function, and
    :func:`lending_hub.assistant.chunking.chunk_document` takes the counter as
    an argument so that replacing it is one line rather than a search.

    The undercount matters most for the languages SRS GA-4 requires and is
    recorded on the chunker's output, not left to be discovered.
    """
    if not text:
        return 0
    parts = [part for part in _TOKEN_SPLIT.split(text) if part]
    return len(parts)


class NullGenerationModel:
    """A generation model that refuses. The default binding, and the honest one.

    Present so that a pipeline assembled without a model fails at the model
    boundary with a message naming the ticket, rather than failing three layers
    later with an empty string that reads like a model declining to answer.
    """

    model_id = "unbound"

    def generate(self, request: GenerationRequest) -> GenerationResult:
        raise UnboundPort(
            "no generation model is bound (LH-604). Phase 5 calls no LLM on "
            "Track A by decision, not by omission — see ADR-0015. Bind one "
            "through this port on Track B; do not add a fallback that answers."
        )

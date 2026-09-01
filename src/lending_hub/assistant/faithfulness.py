"""Groundedness scoring and the suppression path (WS-5.4).

Phase 5 §4 WS-5.4:

    **Faithfulness scoring** on every answer (RAGAS-style groundedness,
    arXiv:2309.15217); below-threshold answers suppressed automatically; 2%
    weekly human hallucination audit feeding fixes to prompts/retrieval/corpus.

Phase 5 §7 sets the bar: answer faithfulness ≥ 97%.

What is exact here, and what is a model
-----------------------------------------
RAGAS decomposes an answer into atomic claims and asks, per claim, whether the
retrieved context entails it. Two of those three steps are deterministic and
live here in full: **decomposition** into claims, and **aggregation** into a
score with the suppression rule attached.

The middle step is not, and this module refuses to pretend otherwise.
:class:`~lending_hub.assistant.ports.EntailmentModel` is a port with no local
implementation, and :func:`score_faithfulness` raises without one.

**The tempting fallback is lexical overlap, and it is worse than nothing.**
"The fee is waived for accounts under six months" and "the fee applies to
accounts under six months" share every content word and mean opposite things —
so an overlap-based groundedness score is *highest* exactly where a negation has
been flipped, which is the failure mode that matters most. A scorer that is
confidently wrong on the dangerous cases and right on the easy ones is not a
degraded scorer; it is an inverted one, and it would be reported as a 0.97.

Distinct from the numeric-claim validator, and both are needed
----------------------------------------------------------------
:func:`lending_hub.assistant.answer.validate` decides whether a numeric claim
*carries* a citation. This module decides whether the cited passage *supports*
the claim. The first is a parsing question with a right answer on every input;
the second is entailment. An answer can pass the validator perfectly and be
unfaithful — every sentence cited, every citation resolving, and the cited
passage saying something else — which is precisely why the phase file asks for
both and why neither subsumes the other.

Suppression is not refusal
----------------------------
A suppressed answer becomes a handoff, and §4 is explicit that the fallback is
"let me connect you to an officer". It is *not* a hedged answer, a partial
answer, or the same answer with a confidence caveat. A caveat on an unfaithful
answer is an unfaithful answer that has been made harder to challenge.

What this does not port
-----------------------
No RAGAS library, no NLI model, no LLM-as-judge. No answer-relevance or
context-precision metrics — RAGAS defines several and only groundedness is what
§4 names, and implementing the others without the model that powers them would
produce four numbers of which none is computable.

Workstream: WS-5.4 (SRS §8.3.1 step 4, §8.3.4)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from lending_hub.assistant.answer import ValidatedAnswer, split_sentences
from lending_hub.assistant.ports import EntailmentModel, UnboundPort
from lending_hub.definitions.provenance import Pending

#: Phase 5 §7, verbatim: "answer faithfulness ≥ 97%". [SPEC].
FAITHFULNESS_GATE = 0.97

#: SRS GA-6 and Phase 5 §4 WS-5.4: "2% weekly human hallucination audit".
#: [SPEC] — a sampling rate, not a threshold.
WEEKLY_AUDIT_SAMPLE_RATE = 0.02

#: The containment target. Phase 5 §7 writes it as `[POLICY: target]` — the one
#: exit criterion in the programme that ships with its own placeholder visible
#: in the criterion text — and §8 puts containment targets on the do-not-invent
#: list.
CONTAINMENT_TARGET = Pending(
    owner="Product + Compliance",
    ticket="LH-605",
    note="the share of sessions that must be resolved without a human",
)


class FaithfulnessError(Exception):
    """A faithfulness score cannot be computed."""


@dataclass(frozen=True)
class Claim:
    """One atomic claim extracted from an answer.

    ``sentence_index`` is kept so an unsupported claim can be traced back to the
    sentence a human auditor will read. The weekly audit's whole job is turning
    a low score into a fix — prompt, retrieval or corpus — and "claim 7 was
    unsupported" points at none of the three without the sentence behind it.
    """

    text: str
    sentence_index: int


def extract_claims(text: str) -> list[Claim]:
    """Decompose an answer into atomic claims. Deterministic.

    One claim per sentence. RAGAS splits further — a sentence asserting two
    things is two claims — and doing that properly needs the parsing this module
    does not have. Sentence granularity is the **conservative** direction: a
    two-claim sentence with one unsupported half scores as one unsupported
    claim rather than half of one, so the score is lower than a finer
    decomposition would give, never higher.

    Stating that is necessary because it means this module's score is not
    directly comparable with a published RAGAS number, and a comparison would be
    made otherwise.
    """
    return [Claim(text=sentence, sentence_index=index)
            for index, sentence in enumerate(split_sentences(text))]


@dataclass(frozen=True)
class ClaimVerdict:
    """One claim, its best supporting passage, and the entailment score."""

    claim: Claim
    supported: bool
    score: float
    best_passage_index: int | None = None


@dataclass(frozen=True)
class FaithfulnessScore:
    """A groundedness score with its suppression decision attached.

    The two travel together because separating them is how a suppression gets
    skipped: a score returned alone is a number a caller may render beside the
    answer, and the answer is the thing that was supposed to be withheld.
    """

    verdicts: tuple[ClaimVerdict, ...]
    gate: float
    model_id: str

    @property
    def score(self) -> float:
        """Supported claims ÷ total claims — RAGAS groundedness.

        An answer with no claims scores 1.0 by the formula and that is refused
        in :func:`score_faithfulness` rather than returned: an empty answer is
        perfectly faithful and perfectly useless, and a 1.0 from it would lift
        the weekly average exactly when the assistant was answering nothing.
        """
        if not self.verdicts:
            return 1.0
        return sum(1 for v in self.verdicts if v.supported) / len(self.verdicts)

    @property
    def suppress(self) -> bool:
        return self.score < self.gate

    @property
    def unsupported(self) -> tuple[ClaimVerdict, ...]:
        return tuple(v for v in self.verdicts if not v.supported)

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "gate": self.gate,
            "suppress": self.suppress,
            "claims": len(self.verdicts),
            "unsupported": [
                {
                    "text": v.claim.text,
                    "sentence_index": v.claim.sentence_index,
                    "entailment": v.score,
                }
                for v in self.unsupported
            ],
            "entailment_model": self.model_id,
            "granularity_note": (
                "one claim per sentence. RAGAS splits a multi-claim sentence "
                "further; this does not, so a two-claim sentence with one "
                "unsupported half scores as one unsupported claim. The direction "
                "is conservative — lower than a finer decomposition, never higher "
                "— and the number is therefore not directly comparable with a "
                "published RAGAS score"
            ),
        }


def score_faithfulness(
    answer: str,
    context: Sequence[str],
    *,
    model: EntailmentModel | None,
    support_threshold: float,
    gate: float = FAITHFULNESS_GATE,
    model_id: str = "unbound",
) -> FaithfulnessScore:
    """Score an answer's groundedness against its retrieved context.

    ``model`` is required and may not be ``None``. The fallback nobody should
    reach for is lexical overlap, and it is worse than no score at all: "the fee
    is waived for accounts under six months" and "the fee applies to accounts
    under six months" share every content word and mean opposite things, so an
    overlap score peaks exactly where a negation was flipped. That is not a
    degraded scorer, it is an inverted one, and it reports 0.97.

    ``support_threshold`` — the entailment probability above which a claim
    counts as supported — is a required argument with no default. It is a
    property of the bound model rather than of this code: a threshold calibrated
    for one NLI model means something different on another, so a default here
    would be a number carried over from a model nobody is using.
    """
    if model is None:
        raise UnboundPort(
            "no entailment model is bound (LH-604). Faithfulness is not computed "
            "from lexical overlap: 'the fee is waived for accounts under six "
            "months' and 'the fee applies to accounts under six months' overlap "
            "almost entirely and mean opposite things, so an overlap score is "
            "highest exactly where a negation was flipped."
        )
    if not 0.0 <= support_threshold <= 1.0:
        raise FaithfulnessError(
            f"support_threshold must be in [0, 1], got {support_threshold}"
        )
    if not context:
        raise FaithfulnessError(
            "an answer with no retrieved context is not unfaithful, it is "
            "ungrounded — Phase 5 §8 refuses and escalates rather than scoring it"
        )

    claims = extract_claims(answer)
    if not claims:
        raise FaithfulnessError(
            "an answer with no claims scores 1.0 by the RAGAS formula, which "
            "would lift the weekly average exactly when the assistant answered "
            "nothing. An empty answer is a handoff, not a faithful answer."
        )

    verdicts: list[ClaimVerdict] = []
    for claim in claims:
        best_score = 0.0
        best_index: int | None = None
        for index, passage in enumerate(context):
            value = float(model.entails(passage, claim.text))
            if value > best_score:
                best_score, best_index = value, index
        verdicts.append(
            ClaimVerdict(
                claim=claim,
                supported=best_score >= support_threshold,
                score=best_score,
                best_passage_index=best_index,
            )
        )

    return FaithfulnessScore(verdicts=tuple(verdicts), gate=gate, model_id=model_id)


@dataclass(frozen=True)
class Disposition:
    """What the customer receives: the answer, or a handoff.

    Named for the decision rather than the score, because the decision is the
    deliverable. §4 requires below-threshold answers to be "suppressed
    automatically", and a scorer that returned a number and left the suppression
    to a caller has implemented the measurement and not the control.
    """

    served: bool
    text: str
    handoff_reason: str = ""

    def __post_init__(self) -> None:
        if not self.served and not self.handoff_reason:
            raise FaithfulnessError("a suppressed answer must say why it was suppressed")
        if not self.served and self.text:
            raise FaithfulnessError(
                "a suppressed answer must not carry its text. A hedged or "
                "caveated version of an unfaithful answer is an unfaithful "
                "answer that has been made harder to challenge."
            )


def suppress_if_unfaithful(
    answer: ValidatedAnswer,
    score: FaithfulnessScore,
) -> Disposition:
    """Apply the suppression rule. The §4 "automatically" made structural.

    Suppression drops the text entirely. Not a hedge, not a partial answer, not
    the same answer with a confidence caveat — §4 names the fallback as "let me
    connect you to an officer", and :class:`Disposition` refuses to be
    constructed as unserved while still holding text.
    """
    if answer.handoff:
        return Disposition(
            served=False,
            text="",
            handoff_reason=answer.handoff_reason,
        )
    if score.suppress:
        unsupported = len(score.unsupported)
        return Disposition(
            served=False,
            text="",
            handoff_reason=(
                f"faithfulness {score.score:.3f} is below the gate {score.gate:.2f}: "
                f"{unsupported} of {len(score.verdicts)} claims are not supported by "
                "the retrieved context. The answer is withheld rather than hedged."
            ),
        )
    return Disposition(served=True, text=answer.text)


def audit_sample_size(sessions: int, rate: float = WEEKLY_AUDIT_SAMPLE_RATE) -> int:
    """How many sessions the weekly hallucination audit must review.

    SRS GA-6 and §4 WS-5.4 both write it as ≥ 2% of sessions weekly, so this
    rounds **up**: 2% of 1,050 sessions is 21 sessions, and reviewing 21 rather
    than 20 is the difference between meeting a floor and nearly meeting it.

    Returns at least 1 for any non-zero session count. A week with 30 sessions
    has a mathematical sample of 0.6, and an audit that reviewed nothing that
    week would report full compliance with a 2% rate.
    """
    if sessions < 0:
        raise FaithfulnessError(f"sessions cannot be negative, got {sessions}")
    if not 0.0 < rate <= 1.0:
        raise FaithfulnessError(f"rate must be in (0, 1], got {rate}")
    if sessions == 0:
        return 0
    import math

    return max(1, math.ceil(sessions * rate))


def containment(sessions: int, handoffs: int) -> dict:
    """Sessions resolved without a human, and why the number has no verdict.

    Phase 5 §7 requires containment ≥ `[POLICY: target]` and the target is
    unratified (LH-605), so this reports the *rate* and refuses a pass/fail. The
    refusal matters more than usual here because containment is the one metric
    in this phase that gets better when the assistant gets more reckless: every
    handoff lowers it, so a target set without the correct-escalation rate
    beside it is a target that rewards answering questions the assistant should
    refuse.
    """
    if sessions < 0 or handoffs < 0:
        raise FaithfulnessError("session and handoff counts cannot be negative")
    if handoffs > sessions:
        raise FaithfulnessError(
            f"{handoffs} handoffs in {sessions} sessions is not possible"
        )
    return {
        "sessions": sessions,
        "handoffs": handoffs,
        "containment_rate": (sessions - handoffs) / sessions if sessions else None,
        "target": str(CONTAINMENT_TARGET),
        "verdict": None,
        "verdict_note": (
            "no verdict: the target is unratified (LH-605). Containment is the "
            "one metric here that improves when the assistant gets more "
            "reckless — every handoff lowers it — so a target set without the "
            "correct-escalation rate beside it rewards answering questions the "
            "assistant should refuse"
        ),
    }

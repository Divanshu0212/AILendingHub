"""The answer contract and the deterministic numeric-claim validator (WS-5.3.1).

Phase 5 §4 WS-5.3 step 1, verbatim:

    Answer contract. Output schema: every factual sentence carries a citation id
    resolving to a retrieved chunk; numeric values must come from a citation or
    a tool call. A **post-generation validator** parses each answer and **drops
    any uncited numeric claim** — the user then sees a handoff message, never an
    uncited answer. **This validator is deterministic code, not another LLM.**

Why the last sentence is the whole phase
------------------------------------------
An LLM checking an LLM's citations has the failure mode of the thing it is
checking. It is fluent about its own judgements, it can be argued out of them by
text in the answer it is reading, and — the part that matters for a bank — its
verdict cannot be reproduced eight years later for an auditor. A regex either
matched or it did not, on a string that is stored.

So this module is a parser, and its tests are adversarial rather than
illustrative. The interesting inputs are not "the fee is 1.5%" — they are the
ones where a number is present and does not look like one, or looks like one and
is not:

* **numbers written as words** — "twelve point five percent" carries the same
  claim as "12.5%" and no digit;
* **numbers inside the citation marker itself** — ``[CIRC-2026-04@v2]`` contains
  2026, 04 and 2, and a naive scan reports the citation as an uncited claim;
* **ranges and spans** — "between 8% and 12%" is two numbers and one claim;
* **currency in Indian grouping** — "₹1,50,000" is not "₹150,000" to a regex
  written for thousands separators;
* **ordinals and dates** — "the 15th of every month" is a number that is not a
  banking quantity, and refusing it makes the assistant unable to say when an
  EMI is due;
* **numbers inside a product name** — "Scheme 2020" is not a claim.

Each is a test below, and each shaped the parser.

What the validator does and does not decide
---------------------------------------------
It decides **whether a numeric claim carries a resolvable citation.** It does
not decide whether the cited passage *supports* the number — that is entailment,
it is not decidable by parsing, and it lives in
:mod:`~lending_hub.assistant.faithfulness` behind a model port. Conflating the
two would be the worse error, because a citation-checker that claimed to verify
support would make the faithfulness scorer look redundant.

The conservative direction is fixed and is not a tuning choice
---------------------------------------------------------------
Where the parser is unsure whether something is a numeric claim, it treats it as
one — which drops a sentence that might have been fine. The asymmetry is
deliberate: a dropped good sentence costs a customer a handoff to a human, and
an admitted bad one puts an ungrounded rate in front of them. Phase 5 §7 makes
the leak rate a *hard* gate and sets no target for over-refusal.

What this does not port
-----------------------
No natural-language parsing, no dependency tree, no coreference. Sentence
splitting is punctuation-based and will mis-split an abbreviation; that failure
is safe in this direction (a mis-split sentence is *more* likely to be flagged
as uncited, not less). No LLM, by explicit instruction of the phase file.

Workstream: WS-5.3.1 (SRS §8.3.1, GA-6)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Mapping, Sequence

#: Citation markers the contract recognises: ``[DOC-ID@version]`` or
#: ``[DOC-ID@version#chunk]``. Square brackets because they are the one
#: delimiter that does not occur in ordinary Indian banking prose, where
#: parentheses carry clause references and braces appear in templates.
CITATION = re.compile(r"\[([A-Za-z0-9][A-Za-z0-9._\-]*@[A-Za-z0-9._\-]+(?:#[A-Za-z0-9._\-]+)?)\]")

#: A tool-result marker: ``[tool:compute_emi]``. Distinct from a document
#: citation because Phase 5 §4 permits a number to come from "a citation **or a
#: tool call**", and the two need different downstream treatment — a document
#: citation resolves to stored text, a tool citation resolves to a logged call.
TOOL_CITATION = re.compile(r"\[tool:([a-z_][a-z0-9_]*)\]")

#: Digits in any of the shapes a rate, an amount or a tenor takes. The Indian
#: grouping (1,50,000) is matched by the same alternation as the international
#: one because ``[\d,]`` after the first digit accepts both — writing two
#: patterns is how one of them ends up maintained and the other does not.
_NUMERIC = re.compile(
    r"""
    (?<![\w@#.\-])            # not mid-identifier and not after a version dot
    (?:₹|rs\.?\s*|inr\s*)?    # optional currency prefix
    \d[\d,]*                  # integer part, any grouping
    (?:\.\d+)?                # optional decimal
    \s*(?:%|per\s*cent|percent|lakh|crore|bps|basis\s*points)?
    """,
    re.IGNORECASE | re.VERBOSE,
)

#: Number words. Present because "twelve point five percent" is the same claim
#: as "12.5%" with no digit in it, and a validator that only reads digits is
#: defeated by a model that was asked to write naturally. Bounded at the
#: magnitudes banking prose uses — beyond "crore" a model writing out digits is
#: the overwhelmingly likelier case.
_NUMBER_WORDS = frozenset(
    """
    zero one two three four five six seven eight nine ten eleven twelve
    thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty
    thirty forty fifty sixty seventy eighty ninety hundred thousand lakh
    lakhs crore crores million billion half quarter third
    """.split()
)

#: Words that turn a bare number into a *quantity claim* rather than an
#: incidental number. "twelve" alone in "twelve documents" is not a rate; "twelve
#: percent" is. Keeping this list short and specific is what stops the
#: word-number path from flagging every sentence containing "one".
_NUMBER_WORD_UNITS = frozenset(
    """
    percent per cent point rupees rupee lakh lakhs crore crores
    months month years year days day
    """.split()
)

#: Contexts in which a digit is not a banking quantity. Each is here because
#: refusing it would break a sentence the assistant must be able to say.
_NON_CLAIM_CONTEXTS = (
    # An ordinal date: "the 15th of every month" — when the EMI is due.
    re.compile(r"\b\d{1,2}(?:st|nd|rd|th)\b", re.IGNORECASE),
    # A bare four-digit year in a name or reference: "Scheme 2020", "RBI 2025".
    re.compile(r"(?<![\d.,₹])\b(?:19|20)\d{2}\b(?![\d.,%])"),
)

#: Abbreviations that end in a period and are never a sentence end. Kept
#: deliberately short — every entry is a place the splitter is now *less*
#: conservative, and the safe failure direction is over-splitting. "Rs." earns
#: its place because splitting there strands the amount in a fragment and leaves
#: "The fee is Rs." as a kept sentence, which is a mangled sentence shown to a
#: customer rather than an unsafe one.
_ABBREVIATIONS = ("rs.", "no.", "vs.", "sr.", "smt.", "shri.", "dr.", "mr.", "mrs.", "ms.")

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?।])\s+")

#: One or more citation markers with surrounding punctuation. Used two ways:
#: a fragment that is *only* this is the tail of the sentence before it, and a
#: fragment that *starts* with this carries the previous sentence's citation.
_CITATION_RUN = r"(?:\s*(?:" + CITATION.pattern + r"|" + TOOL_CITATION.pattern + r")\s*[.,;]?)+"
_ONLY_CITATIONS = re.compile(_CITATION_RUN, re.IGNORECASE)
_LEADING_CITATIONS = re.compile(_CITATION_RUN, re.IGNORECASE)


class AnswerError(Exception):
    """An answer cannot be constructed or validated."""


class ClaimKind(str, Enum):
    """Why a span was treated as a numeric claim.

    Recorded per claim so a suppression can be explained to the officer whose
    correction Phase 5 §5 step 1 triages. "Dropped because it contained a
    number" is unactionable; "dropped because 'twelve percent' is a spelled
    quantity with no citation" tells them whether the fix is the prompt, the
    corpus or the parser.
    """

    DIGITS = "digits"
    SPELLED = "spelled"


@dataclass(frozen=True)
class NumericClaim:
    """One numeric span found in a sentence."""

    text: str
    kind: ClaimKind


@dataclass(frozen=True)
class Sentence:
    """One sentence of a generated answer, with what the parser found in it."""

    text: str
    citations: tuple[str, ...]
    tool_citations: tuple[str, ...]
    numeric_claims: tuple[NumericClaim, ...]

    @property
    def has_numeric_claim(self) -> bool:
        return bool(self.numeric_claims)

    @property
    def cited(self) -> bool:
        return bool(self.citations or self.tool_citations)


class Verdict(str, Enum):
    """What happened to a sentence."""

    KEPT = "kept"
    DROPPED_UNCITED_NUMERIC = "dropped_uncited_numeric"
    DROPPED_UNRESOLVABLE_CITATION = "dropped_unresolvable_citation"


@dataclass(frozen=True)
class SentenceVerdict:
    sentence: Sentence
    verdict: Verdict
    reason: str = ""


@dataclass(frozen=True)
class ValidatedAnswer:
    """An answer that has been through the validator. **The only servable type.**

    The guarantee is a constructor invariant, not a convention: an instance
    holding a sentence with an uncited numeric claim cannot exist. That makes
    Phase 5 §7's "uncited-numeric leak rate = 0" a property of the type rather
    than a measurement over a weekly sample — a sample can show a rate is low
    and never that it is zero.

    Two honest limits on that, stated here because this docstring is where
    someone quoting the guarantee will look:

    * **It guards a code path.** A generation service that renders
      :class:`~lending_hub.assistant.ports.GenerationResult.text` directly is
      outside it. The validator returns a new object rather than mutating a
      string precisely so that skipping it leaves the caller with nothing to
      render.
    * **It is about citation, not truth.** A cited number can still be wrong if
      the citation is to a superseded circular (LH-608) or the retrieval was
      poisoned. Effective-date filtering and the faithfulness scorer are what
      address that, and neither is this.
    """

    text: str
    """The servable answer: kept sentences only, joined."""

    verdicts: tuple[SentenceVerdict, ...]
    handoff: bool
    handoff_reason: str = ""
    language: str = "en"

    def __post_init__(self) -> None:
        for item in self.verdicts:
            if item.verdict is not Verdict.KEPT:
                continue
            sentence = item.sentence
            if sentence.has_numeric_claim and not sentence.cited:
                raise AnswerError(
                    "a kept sentence carries an uncited numeric claim: "
                    f"{sentence.text!r}. This is Phase 5 §7's hard gate and it "
                    "is enforced here rather than sampled — construct "
                    "ValidatedAnswer through validate(), never directly."
                )
        if self.handoff and not self.handoff_reason:
            raise AnswerError("a handoff must say why; an unexplained handoff is a dead end")

    @property
    def dropped(self) -> tuple[SentenceVerdict, ...]:
        return tuple(v for v in self.verdicts if v.verdict is not Verdict.KEPT)

    @property
    def kept(self) -> tuple[SentenceVerdict, ...]:
        return tuple(v for v in self.verdicts if v.verdict is Verdict.KEPT)

    @property
    def citations(self) -> tuple[str, ...]:
        out: list[str] = []
        for item in self.kept:
            for citation in item.sentence.citations:
                if citation not in out:
                    out.append(citation)
        return tuple(out)

    def to_dict(self) -> dict:
        """The audit record. Every dropped sentence and why, kept verbatim.

        The dropped text is retained rather than discarded because the weekly
        hallucination audit (SRS GA-6, Phase 5 §4 WS-5.4) is looking for exactly
        this: a model that keeps producing uncited numbers is a prompt or
        retrieval problem, and the evidence is the sentences that were removed,
        not the ones that survived.
        """
        return {
            "text": self.text,
            "language": self.language,
            "handoff": self.handoff,
            "handoff_reason": self.handoff_reason,
            "citations": list(self.citations),
            "sentences_kept": len(self.kept),
            "sentences_dropped": len(self.dropped),
            "dropped": [
                {
                    "text": item.sentence.text,
                    "verdict": item.verdict.value,
                    "reason": item.reason,
                    "numeric_claims": [
                        {"text": claim.text, "kind": claim.kind.value}
                        for claim in item.sentence.numeric_claims
                    ],
                }
                for item in self.dropped
            ],
            "leak_rate_note": (
                "uncited-numeric leak rate is zero by construction of "
                "ValidatedAnswer, not by measurement over this answer "
                "(Phase 5 §7; ADR-0015)"
            ),
        }


def split_sentences(text: str) -> list[str]:
    """Split on terminal punctuation, including the Devanagari danda (।).

    **A trailing citation belongs to the sentence it follows.** Models place the
    marker after the full stop — "The fee is 1.5%. [CIRC@v2]" — and splitting
    naively makes the marker its own sentence. The consequences are not cosmetic
    and both directions are wrong: the claim sentence loses its citation and is
    dropped, and the orphaned marker has no numeric claim so it *survives*,
    leaving an answer whose entire visible content is "[CIRC@v2]". Found by
    testing rather than by reading; raised as finding P5-F2.

    Naive in the other direction, by design. The failure it keeps — splitting
    "Rs. 5,000" at the abbreviation — is safe: the fragment "5,000 in total."
    has no citation and is dropped, which errs towards refusal. A cleverer
    splitter would have to be right about which periods are terminal, and being
    wrong the other way admits an uncited claim.
    """
    parts = [part.strip() for part in _SENTENCE_SPLIT.split(text.strip()) if part.strip()]

    merged: list[str] = []
    for part in parts:
        if merged and _ONLY_CITATIONS.fullmatch(part):
            merged[-1] = f"{merged[-1]} {part}"
            continue
        if merged and merged[-1].lower().endswith(_ABBREVIATIONS):
            merged[-1] = f"{merged[-1]} {part}"
            continue

        leading = _LEADING_CITATIONS.match(part)
        if merged and leading is not None and leading.end() < len(part):
            # A marker at the *start* of a fragment is the previous sentence's
            # citation, not this one's — the sentence split fell after the full
            # stop and before the marker. Left attached here it grounds the
            # wrong claim: "The fee is 1.5%." silently loses its source while
            # the next sentence's number silently gains one.
            merged[-1] = f"{merged[-1]} {part[: leading.end()].strip()}"
            part = part[leading.end() :].strip()
            if not part:
                continue

        merged.append(part)
    return merged


def _strip_citations(text: str) -> str:
    """Remove citation markers before scanning for numbers.

    The single most important line in the module. ``[CIRC-2026-04@v2]`` contains
    2026, 04 and 2, so a validator that scanned the raw sentence would find
    "numeric claims" inside every citation and drop every properly cited
    sentence — a validator that fails closed on correct input, which gets
    switched off within a week of launch.
    """
    return TOOL_CITATION.sub(" ", CITATION.sub(" ", text))


def find_numeric_claims(text: str) -> list[NumericClaim]:
    """Every numeric claim in a sentence, citation markers excluded.

    Two passes, because the two evasions are different in kind. Digits are found
    by pattern; spelled quantities are found by looking for a number word next
    to a unit word, which is what separates "twelve percent" (a claim) from
    "one of the documents" (not one).
    """
    body = _strip_citations(text)
    claims: list[NumericClaim] = []

    masked = body
    for pattern in _NON_CLAIM_CONTEXTS:
        masked = pattern.sub(" ", masked)

    for match in _NUMERIC.finditer(masked):
        span = match.group(0).strip()
        if not any(character.isdigit() for character in span):
            continue
        claims.append(NumericClaim(text=span, kind=ClaimKind.DIGITS))

    words = re.findall(r"[a-z]+", body.lower())
    for index, word in enumerate(words):
        if word not in _NUMBER_WORDS:
            continue
        window = words[max(0, index - 1) : index + 4]
        if any(neighbour in _NUMBER_WORD_UNITS for neighbour in window if neighbour != word):
            phrase = " ".join(words[index : index + 3])
            claims.append(NumericClaim(text=phrase, kind=ClaimKind.SPELLED))
            break

    return claims


def parse_sentence(text: str) -> Sentence:
    """Parse one sentence into citations, tool citations and numeric claims."""
    return Sentence(
        text=text,
        citations=tuple(CITATION.findall(text)),
        tool_citations=tuple(TOOL_CITATION.findall(text)),
        numeric_claims=tuple(find_numeric_claims(text)),
    )


#: What the user sees when nothing survives validation. Deliberately not a
#: sentence about loans: Phase 5 §8 forbids improvising an answer where
#: retrieval returned nothing, and a handoff that hedges ("the rate is roughly
#: …") is an improvisation with a disclaimer.
HANDOFF_MARKER = "handoff"


def validate(
    text: str,
    *,
    resolvable: Callable[[str], bool] | Sequence[str] | None = None,
    allowed_tools: Sequence[str] | None = None,
    language: str = "en",
) -> ValidatedAnswer:
    """Drop every uncited numeric claim, and hand off if nothing survives.

    ``resolvable`` decides whether a citation id points at a real retrieved
    chunk. Passing ``None`` means **no citation resolves** — the strict reading,
    and the right default, because the alternative default (trust every marker)
    makes a model that invents plausible citation ids fully unvalidated. A
    caller with a retrieval result passes its chunk ids or the registry's
    membership test.

    ``allowed_tools`` is the same for tool markers: unknown by default, because
    ``[tool:compute_apr]`` naming a tool that does not exist is exactly what an
    injected instruction produces.

    The handoff condition is *nothing kept*, not *anything dropped*. An answer
    that explained the documents needed and lost one sentence quoting a fee is
    still a useful answer, and forcing a human handoff for it would push
    containment down for no safety gain. An answer whose every sentence was
    numeric and uncited has nothing left to say.
    """
    if resolvable is None:
        resolves: Callable[[str], bool] = lambda _: False
    elif callable(resolvable):
        resolves = resolvable
    else:
        known = set(resolvable)
        resolves = lambda citation: citation in known

    tools = set(allowed_tools or ())

    sentences = split_sentences(text)
    verdicts: list[SentenceVerdict] = []

    for raw in sentences:
        sentence = parse_sentence(raw)

        unresolved = [c for c in sentence.citations if not resolves(c)]
        bad_tools = [t for t in sentence.tool_citations if t not in tools]

        if sentence.has_numeric_claim:
            good_citations = [c for c in sentence.citations if resolves(c)]
            good_tools = [t for t in sentence.tool_citations if t in tools]
            if not good_citations and not good_tools:
                claims = ", ".join(repr(c.text) for c in sentence.numeric_claims)
                if sentence.citations or sentence.tool_citations:
                    reason = (
                        f"numeric claim(s) {claims} carry only unresolvable "
                        f"citations {unresolved + bad_tools}. An id that resolves "
                        "to nothing is a claimed source that does not exist, "
                        "which is weaker evidence than no claim at all."
                    )
                    verdict = Verdict.DROPPED_UNRESOLVABLE_CITATION
                else:
                    reason = f"numeric claim(s) {claims} with no citation"
                    verdict = Verdict.DROPPED_UNCITED_NUMERIC
                verdicts.append(SentenceVerdict(sentence=sentence, verdict=verdict, reason=reason))
                continue

        verdicts.append(SentenceVerdict(sentence=sentence, verdict=Verdict.KEPT))

    kept = [v for v in verdicts if v.verdict is Verdict.KEPT]
    if not kept:
        return ValidatedAnswer(
            text="",
            verdicts=tuple(verdicts),
            handoff=True,
            handoff_reason=(
                "every sentence was dropped as an uncited numeric claim. Phase 5 "
                "§8: an answer where retrieval returned nothing is refused and "
                "escalated, never improvised."
                if verdicts
                else "the model returned no sentences"
            ),
            language=language,
        )

    return ValidatedAnswer(
        text=" ".join(v.sentence.text for v in kept),
        verdicts=tuple(verdicts),
        handoff=False,
        language=language,
    )


def leak_audit(answers: Sequence[ValidatedAnswer]) -> dict:
    """The weekly-audit view of Phase 5 §7's hard gate.

    Reports zero and says why it is zero. A bare "leak rate: 0.0" in a gate pack
    reads as a measurement that could have come out otherwise; this one cannot,
    and the difference is what a Model Risk reviewer needs in order to decide
    whether the number means anything about the deployed system.
    """
    total_sentences = sum(len(a.verdicts) for a in answers)
    dropped = sum(len(a.dropped) for a in answers)
    return {
        "answers": len(answers),
        "sentences": total_sentences,
        "sentences_dropped": dropped,
        "handoffs": sum(1 for a in answers if a.handoff),
        "uncited_numeric_leaks": 0,
        "leak_rate": 0.0,
        "basis": "structural",
        "basis_note": (
            "not a measurement. ValidatedAnswer refuses construction with an "
            "uncited numeric claim in a kept sentence, so the rate cannot be "
            "non-zero along this path. Phase 5 §7 asks for a weekly audit, which "
            "samples; this is stronger for the path it guards and says nothing "
            "about a generation service that bypasses validate()"
        ),
    }

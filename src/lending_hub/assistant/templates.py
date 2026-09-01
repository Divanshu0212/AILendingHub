"""Adverse-action templates keyed to P1 reason codes (WS-5.3.3).

Phase 5 §4 WS-5.3 step 3, verbatim:

    Templated adverse-action language. The assistant explains decisions only by
    **selecting and ordering** pre-approved templates keyed to P1 reason codes
    `[POLICY: Compliance]`, per language. It **never composes new
    decision-explanation sentences** (SRS GA-3).

The module is defined by what it does not contain
---------------------------------------------------
There is no code path here that produces a decision-explanation sentence.
:func:`explain_decision` selects template ids and orders them; the rendering
call raises while the sentences are unratified; and no branch of it falls back
to composing prose. That is unusual even for this repository — most modules
refuse a *number* — and it is what "never composes" has to mean if it is going
to be true of the deployed system rather than of the prompt.

The reason the rule is absolute rather than a quality bar is regulatory. An
adverse-action statement is a legal communication in a specific form; a model
that paraphrased an approved sentence into something clearer would produce a
sentence Compliance never approved, and it would be *better written*, which
makes it more likely to survive review and reach a customer.

Two tickets, and they are not the same ticket
-----------------------------------------------
LH-203 is Phase 1's **reason-code wording**: one sentence per code in
``config/reason_codes.yaml``, for an adverse-action letter. LH-603 is this
phase's **conversational template set**: per-language variants, ordering rules,
and the disclosures that must accompany an explanation given in a chat.
Ratifying LH-203 does not produce LH-603 — a sentence written for a letter that
a customer reads once, with the letter's headers and footers around it, is not
the same artifact as a turn in a conversation the customer can reply to.

This module reads the LH-203 table because that is where the code→feature
mapping lives and it must not be duplicated (Master §2 rule 2 applies to
mappings as much as algorithms). It renders nothing from it.

Ordering is a compliance decision, not a ranking
--------------------------------------------------
Adverse-action rules require the *principal* reasons. P1's
:func:`lending_hub.scoring.reasons.map_reasons` already orders codes by SHAP
contribution and that ordering is preserved here rather than re-derived —
re-sorting on any other basis (severity, brevity, what reads best) would state
reasons that are not the principal ones, which is the specific thing the rules
exist to prevent.

What this does not port
-----------------------
No template engine, no localisation framework, no ICU message formatting. Slot
substitution is a plain named-field format over a validated slot set, and it
raises on an unfilled slot rather than emitting a template with a hole in it.
No translation: a Hindi template is authored in Hindi by Compliance, never
machine-translated from English, because a translated adverse-action sentence is
a new sentence in a language Compliance cannot read.

Workstream: WS-5.3.3 (SRS §8.3.3, GA-3)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from lending_hub.definitions.provenance import Pending, Ungrounded
from lending_hub.scoring.reasons import (
    ReasonCodeTable,
    ReasonTableError,
    load_table,
)

#: The approved conversational template set. Phase 5 §8 do-not-invent:
#: "adverse-action sentences (templates-only)".
TEMPLATE_LIBRARY = Pending(
    owner="Compliance",
    ticket="LH-603",
    note=(
        "per-language adverse-action templates, their ordering rules and the "
        "disclosures that must accompany an explanation given in conversation"
    ),
)

#: The launch language list and per-language slice sizes. SRS GA-4 requires
#: "≥ Hindi + English + 2 regional" and names none of them.
LAUNCH_LANGUAGES = Pending(
    owner="Compliance + Product SMEs",
    ticket="LH-610",
    note="which languages ship, and the minimum golden-set slice each needs",
)

_SLOT = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


class TemplateError(Exception):
    """A template cannot be selected, filled or rendered."""


class UnmappedCode(TemplateError):
    """A reason code has no template in this language.

    Its own type because the operational response is specific and urgent: a
    decision was made, the customer is entitled to its principal reasons, and
    one of them cannot be stated. The assistant must escalate rather than
    explain the decision partially — a partial explanation is an explanation
    that omits a principal reason, which is worse than none.
    """


@dataclass(frozen=True)
class Template:
    """One approved sentence for one reason code in one language.

    ``body`` is a :class:`Pending` while unratified, and the type is what stops
    a draft sentence being rendered. A string field holding "TBD" would render
    the literal placeholder into a customer's chat window; a ``Pending`` raises
    at the point of use, which is the whole difference between the two.
    """

    code: str
    language: str
    body: Pending | str
    slots: tuple[str, ...] = ()
    disclosure: Pending | str | None = None
    """Any statement that must accompany this template. Separate from ``body``
    because the disclosure is often mandated by a different rule than the
    reason itself, and joining them makes a change to one a change to both."""

    def __post_init__(self) -> None:
        if not self.code:
            raise TemplateError("a template needs a reason code")
        if not self.language:
            raise TemplateError(f"{self.code}: a template needs a language")

    @property
    def ratified(self) -> bool:
        return not isinstance(self.body, Pending)

    def render(self, slots: Mapping[str, object] | None = None) -> str:
        """Fill and return the approved sentence. Raises while unratified.

        Raising is the point. Phase 5 §8 puts adverse-action sentences on the
        do-not-invent list, and a plausible draft rendered "just for the demo"
        is indistinguishable from an approved one six months later — the
        failure Master §2 rule 1 exists to prevent, in the one place where the
        artifact is a legal communication.
        """
        if isinstance(self.body, Pending):
            raise Ungrounded(
                f"{self.body} — the adverse-action template for {self.code!r} in "
                f"{self.language!r} is not ratified. A decision explanation cannot "
                "be rendered from a draft sentence: SRS GA-3 permits selecting and "
                "ordering approved templates and nothing else."
            )
        values = dict(slots or {})
        required = set(self.slots)
        missing = required - set(values)
        if missing:
            raise TemplateError(
                f"{self.code}: unfilled slot(s) {sorted(missing)}. A template with "
                "a hole in it is not a shorter sentence, it is a different one."
            )
        extra = set(values) - required
        if extra:
            raise TemplateError(
                f"{self.code}: slot(s) {sorted(extra)} are not declared by this "
                "template. Substituting an undeclared value is composition."
            )
        return self.body.format(**values)


@dataclass(frozen=True)
class SelectedTemplate:
    """One template chosen for one decision, in the order it must be stated."""

    code: str
    language: str
    position: int
    contribution: float
    template: Template

    @property
    def renderable(self) -> bool:
        return self.template.ratified


@dataclass(frozen=True)
class Explanation:
    """A decision explanation: an ordered selection, and nothing composed.

    Deliberately holds *templates*, not text. The rendering step is separate and
    can fail, and keeping them apart means the selection — which is auditable
    and correct — survives the fact that the sentences do not exist yet. An
    explanation type that held strings could not be constructed at all here, and
    the ordering logic would have gone untested until Compliance delivered.
    """

    language: str
    selected: tuple[SelectedTemplate, ...]
    escalate: bool = False
    escalation_reason: str = ""

    def __post_init__(self) -> None:
        if self.escalate and not self.escalation_reason:
            raise TemplateError("an escalation must say why")
        if not self.escalate and not self.selected:
            raise TemplateError(
                "an explanation with no reasons and no escalation is a decision "
                "communicated without its principal reasons"
            )

    @property
    def renderable(self) -> bool:
        """Whether every selected template is ratified.

        All-or-nothing on purpose. Rendering the ratified subset would state
        some of the principal reasons and silently drop the others, which is
        precisely the adverse-action failure — and it would look like a working
        feature.
        """
        return bool(self.selected) and all(s.renderable for s in self.selected)

    def render(self, slots: Mapping[str, Mapping[str, object]] | None = None) -> str:
        """Render the full explanation. Raises unless every template is ratified."""
        if self.escalate:
            raise TemplateError(
                f"this explanation escalates rather than explaining: {self.escalation_reason}"
            )
        if not self.renderable:
            unratified = [s.code for s in self.selected if not s.renderable]
            raise Ungrounded(
                f"templates {unratified} are not ratified (LH-603). The ratified "
                "subset is not rendered either: stating some principal reasons and "
                "dropping the rest is the adverse-action failure itself, and it "
                "would look like a working feature."
            )
        per_code = dict(slots or {})
        return " ".join(
            item.template.render(per_code.get(item.code)) for item in self.selected
        )

    def to_dict(self) -> dict:
        return {
            "language": self.language,
            "escalate": self.escalate,
            "escalation_reason": self.escalation_reason,
            "renderable": self.renderable,
            "codes": [
                {
                    "code": item.code,
                    "position": item.position,
                    "contribution": item.contribution,
                    "ratified": item.renderable,
                }
                for item in self.selected
            ],
            "composition_note": (
                "no sentence in this object was composed. Every entry names an "
                "approved template id; the assistant selects and orders, and "
                "SRS GA-3 permits nothing else"
            ),
        }


class TemplateLibrary:
    """Approved templates, addressed by (code, language).

    Not a nested dict, for the reason the other registries in this package are
    not: the lookup that matters — "is there an approved sentence for this code
    in this customer's language?" — has a specific failure that must not be a
    ``KeyError`` swallowed by a ``.get``.
    """

    def __init__(self, templates: Sequence[Template] = ()) -> None:
        self._by_key: dict[tuple[str, str], Template] = {}
        for template in templates:
            self.add(template)

    def __len__(self) -> int:
        return len(self._by_key)

    @property
    def languages(self) -> tuple[str, ...]:
        return tuple(sorted({language for _, language in self._by_key}))

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(sorted({code for code, _ in self._by_key}))

    def add(self, template: Template) -> None:
        key = (template.code, template.language)
        if key in self._by_key:
            raise TemplateError(
                f"{template.code} already has a template in {template.language!r}. "
                "Two approved sentences for one code means the choice between them "
                "is made in code, which is the thing this library exists to prevent."
            )
        self._by_key[key] = template

    def get(self, code: str, language: str) -> Template:
        try:
            return self._by_key[(code, language)]
        except KeyError:
            raise UnmappedCode(
                f"no approved template for {code!r} in {language!r}. The decision "
                "cannot be explained in this language and must be escalated — a "
                "partial explanation omits a principal reason, which is worse than "
                "none."
            ) from None

    def coverage(self, codes: Sequence[str], language: str) -> dict:
        """Which codes can be explained in this language, and which cannot.

        The pre-flight check §4 WS-5.3.4 implies but does not state: a language
        ships only when its slice passes the same gates as English, and a
        language whose template set has holes cannot pass anything. Running this
        before launch is cheaper than discovering the hole in a live
        conversation with a declined applicant.
        """
        present, missing, unratified = [], [], []
        for code in codes:
            try:
                template = self.get(code, language)
            except UnmappedCode:
                missing.append(code)
                continue
            present.append(code)
            if not template.ratified:
                unratified.append(code)
        return {
            "language": language,
            "codes": len(codes),
            "with_template": sorted(present),
            "missing_template": sorted(missing),
            "template_unratified": sorted(unratified),
            "complete": not missing and not unratified,
        }


def from_reason_table(
    table: ReasonCodeTable,
    language: str = "en",
) -> TemplateLibrary:
    """Build an unratified library covering every code in the P1 dictionary.

    Every body is a :class:`Pending` on LH-603. This is not a stub of a library
    — it is the library's *shape*, which is the useful artifact right now:
    Compliance receives an exact list of the sentences they owe, per code and
    per language, rather than a request to "write the templates".

    The codes come from the P1 table rather than being listed here because the
    mapping from feature to code is P1's and must have one home. A second list
    would drift the moment a reason code is added, and the drift would surface
    as an unexplainable decline.
    """
    return TemplateLibrary(
        [
            Template(
                code=entry.code,
                language=language,
                body=Pending(
                    owner="Compliance",
                    ticket="LH-603",
                    note=f"conversational adverse-action sentence for {entry.code} in {language}",
                ),
            )
            for entry in table.entries
        ]
    )


def explain_decision(
    reason_codes: Sequence[tuple[str, float]],
    library: TemplateLibrary,
    *,
    language: str,
    max_reasons: int | None = None,
) -> Explanation:
    """Select and order templates for a decision. **Composes nothing.**

    ``reason_codes`` arrives as ``(code, contribution)`` pairs from
    :func:`lending_hub.scoring.reasons.map_reasons`, already ordered by
    contribution. **That order is preserved, not re-derived.** Adverse-action
    rules require the *principal* reasons, and re-sorting on severity, brevity
    or readability would state reasons that are not the principal ones — the
    specific failure those rules exist to prevent.

    ``max_reasons`` truncates from the *front* of the existing order when a
    channel imposes a limit. Truncating is safe only because the order is by
    contribution: dropping the least influential reasons keeps the principal
    ones, and dropping from any other order would not.

    A missing template escalates the whole explanation rather than omitting one
    reason. There is no partial mode, and adding one would be the single easiest
    way to reintroduce the failure.
    """
    if not reason_codes:
        return Explanation(
            language=language,
            selected=(),
            escalate=True,
            escalation_reason=(
                "the decision carried no reason codes. A decision explained with "
                "no reasons is not an explanation, and the assistant does not "
                "improvise one (Phase 5 §8)."
            ),
        )
    if max_reasons is not None and max_reasons <= 0:
        raise TemplateError(f"max_reasons must be positive, got {max_reasons}")

    ordered = list(reason_codes)
    if max_reasons is not None:
        ordered = ordered[:max_reasons]

    selected: list[SelectedTemplate] = []
    for position, (code, contribution) in enumerate(ordered, start=1):
        try:
            template = library.get(code, language)
        except UnmappedCode as exc:
            return Explanation(
                language=language,
                selected=(),
                escalate=True,
                escalation_reason=(
                    f"{exc} The assistant cannot state a subset of the principal "
                    "reasons, so the conversation is handed to a human."
                ),
            )
        selected.append(
            SelectedTemplate(
                code=code,
                language=language,
                position=position,
                contribution=contribution,
                template=template,
            )
        )

    return Explanation(language=language, selected=tuple(selected))


def library_report(library: TemplateLibrary, table: ReasonCodeTable | None = None) -> dict:
    """The WS-5.3.3 deliverable's state, for the gate pack."""
    codes = list(library.codes)
    per_language = {
        language: library.coverage(codes, language) for language in library.languages
    }
    return {
        "templates": len(library),
        "codes": len(codes),
        "languages": list(library.languages),
        "coverage": per_language,
        "any_ratified": any(
            library.get(code, language).ratified
            for code in codes
            for language in library.languages
        ),
        "blocking_tickets": ["LH-603", "LH-203", "LH-610"],
        "note": (
            "no template is ratified. Phase 5 §8 puts adverse-action sentences on "
            "the do-not-invent list, and this library holds the exact set "
            "Compliance owes — per code, per language — rather than drafts of it. "
            "Nothing in this module composes a decision-explanation sentence "
            "(SRS GA-3)"
        ),
        "reason_table_version": table.version() if table is not None else None,
    }


def load_default_library(language: str = "en", path: str | None = None) -> TemplateLibrary:
    """Build the library shape from the committed P1 reason-code dictionary."""
    try:
        table = load_table(path) if path else load_table()
    except ReasonTableError as exc:
        raise TemplateError(f"cannot read the P1 reason-code dictionary: {exc}") from exc
    return from_reason_table(table, language=language)

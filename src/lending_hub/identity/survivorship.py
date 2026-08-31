"""Survivorship rules: which system wins when sources disagree on an attribute.

Phase 0 WS-0.1.3 requires survivorship rules to be *documented*. Phase 0 §8 puts
"survivorship rule exceptions" on the do-not-invent list, so the shape here is
deliberate: the default rule is engineering (the declared system of record for an
entity wins), and every exception to it is `[POLICY]` and must arrive in writing.

Workstream: WS-0.1.3
"""

from __future__ import annotations

from dataclasses import dataclass

from lending_hub.definitions.provenance import Pending

from .keys import Entity

#: Default precedence: the system of record for an entity wins conflicts about
#: that entity's attributes. Derived from the `description` of each registered
#: source (config/sources/*.yaml), not invented here.
SYSTEM_OF_RECORD: dict[Entity, str] = {
    Entity.CUSTOMER: "cbs",
    Entity.ACCOUNT: "cbs",
    Entity.LOAN: "cbs",
    Entity.APPLICATION: "los",
    Entity.CASE: "collections",
}

#: Attribute-level exceptions to the default rule — cases where a non-SoR system
#: legitimately holds the better value (a collections address updated during
#: field visits, say). Every such rule is a governance decision.
SURVIVORSHIP_EXCEPTIONS = Pending(
    owner="Data Governance Council",
    ticket="LH-130",
    note=(
        "attribute-level exceptions to system-of-record precedence, e.g. whether a "
        "collections-updated contact address supersedes the CBS address"
    ),
)


@dataclass(frozen=True)
class Conflict:
    """One attribute on which two sources disagree for the same entity."""

    entity: Entity
    key: str
    attribute: str
    values: dict[str, object]
    """source_id -> value"""

    @property
    def sources(self) -> tuple[str, ...]:
        return tuple(sorted(self.values))


@dataclass(frozen=True)
class Resolution:
    """The surviving value and why it survived."""

    conflict: Conflict
    winner: str | None
    value: object
    rule: str

    @property
    def resolved(self) -> bool:
        return self.winner is not None


def resolve(conflict: Conflict) -> Resolution:
    """Apply the default system-of-record rule.

    Returns an unresolved :class:`Resolution` when the SoR did not supply a value.
    That case is *not* filled by falling back to whichever other source has one —
    a silent fallback is precisely the undocumented exception the phase doc puts on
    the do-not-invent list. It surfaces for LH-130 instead.
    """
    sor = SYSTEM_OF_RECORD.get(conflict.entity)
    if sor is not None and sor in conflict.values:
        return Resolution(
            conflict=conflict,
            winner=sor,
            value=conflict.values[sor],
            rule=f"system_of_record[{conflict.entity.value}] = {sor}",
        )
    return Resolution(
        conflict=conflict,
        winner=None,
        value=None,
        rule=(
            f"unresolved: system of record {sor!r} supplied no value; an exception "
            f"rule is required — {SURVIVORSHIP_EXCEPTIONS}"
        ),
    )


def resolve_all(conflicts: list[Conflict]) -> tuple[list[Resolution], list[Resolution]]:
    """Split conflicts into resolved and unresolved. Unresolved ones block the gate."""
    resolutions = [resolve(c) for c in conflicts]
    return (
        [r for r in resolutions if r.resolved],
        [r for r in resolutions if not r.resolved],
    )

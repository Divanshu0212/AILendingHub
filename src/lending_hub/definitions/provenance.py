"""Provenance typing for every grounded value in the platform.

Implements Master §2 rule 1: every number, threshold, rate, or business rule comes
from exactly one of three sources, and which one is recorded in the code rather
than remembered by a person.

Workstream: WS-0.3.4
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

TBD_PATTERN = re.compile(r"TBD\[(?P<owner>[^,\]]+),\s*(?P<ticket>[A-Z]{2,}-\d+)\]")


class Source(str, Enum):
    """The three — and only three — sources of truth (Master §2 rule 1)."""

    SPEC = "SPEC"
    """Written explicitly in the SRS, the Master guide, or a phase file."""

    DATA = "DATA"
    """Computed from the bank's actual data by a versioned, committed script."""

    POLICY = "POLICY"
    """Supplied in writing by the named owning committee."""


class Ungrounded(Exception):
    """Raised when code reads a value that no source of truth has supplied yet.

    This is deliberately an exception and not a default. A missing threshold must
    stop the caller, because a plausible fallback is indistinguishable from a real
    value once it is six months old.
    """


@dataclass(frozen=True)
class Pending:
    """A typed placeholder for a value that is not yet grounded.

    Rendered as ``TBD[owner, ticket-id]`` per Master §2 rule 4. Reading ``.value``
    raises :class:`Ungrounded` — the placeholder cannot be silently used in
    arithmetic or comparison.
    """

    owner: str
    ticket: str
    note: str = ""

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"TBD[{self.owner}, {self.ticket}]"

    @property
    def value(self):
        raise Ungrounded(
            f"{self} is not grounded yet"
            + (f" ({self.note})" if self.note else "")
            + ". Chase the owner or raise the ticket; do not substitute a default."
        )

    @classmethod
    def parse(cls, text: str) -> Pending | None:
        """Parse a ``TBD[owner, TICKET-1]`` string, or return None if malformed."""
        match = TBD_PATTERN.fullmatch(text.strip())
        if match is None:
            return None
        return cls(owner=match.group("owner").strip(), ticket=match.group("ticket"))


@dataclass(frozen=True)
class Grounded:
    """A value together with the source of truth that supplied it."""

    value: object
    source: Source
    citation: str
    """Where the value came from: an SRS/Master clause, a script path, or a
    committee decision reference."""

    owner: str | None = None
    """Required for POLICY values — the committee that owns the number."""

    def __post_init__(self) -> None:
        if self.source is Source.POLICY and not self.owner:
            raise ValueError("a POLICY value must name its owning committee")
        if not self.citation:
            raise ValueError("every grounded value must carry a citation")

    def __str__(self) -> str:  # pragma: no cover - trivial
        tag = f"{self.source.value}: {self.owner}" if self.owner else self.source.value
        return f"{self.value!r} [{tag}] ({self.citation})"


def resolve(item: Grounded | Pending):
    """Read a value, raising :class:`Ungrounded` if it is still a placeholder."""
    return item.value

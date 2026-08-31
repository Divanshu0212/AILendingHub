"""Deterministic key normalisation for the identity spine.

Phase 0 WS-0.1.3 is explicit that fuzzy matching is **out of scope** — it belongs to
P1 fraud entity resolution. Everything here is exact-match after a documented,
reversible normalisation, and any rule that would merge two records on a similarity
judgement belongs in P1, not here.

The distinction matters more than it looks. A spine that quietly fuzzy-matches
inflates its own join rate, and the 99.5% gate then measures the matcher's
optimism rather than the data's quality.

Workstream: WS-0.1.3
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

_WHITESPACE = re.compile(r"\s+")


class Entity(str, Enum):
    """Entities the spine keys on. One per join axis in WS-0.1.3."""

    CUSTOMER = "customer_id"
    ACCOUNT = "account_id"
    LOAN = "loan_id"
    APPLICATION = "application_id"
    CASE = "case_id"


class KeyProblem(str, Enum):
    """Why a raw key could not become a spine key.

    These are the root-cause categories the WS-0.1.3 audit report is required to
    break failures down by. A join-rate number without them tells an engineer
    nothing about what to fix.
    """

    NULL = "null_key"
    """Absent, empty, or whitespace-only."""

    PLACEHOLDER = "placeholder_key"
    """A sentinel that a source system uses to mean "unknown" — 'NA', '0',
    '999999', 'UNKNOWN'. These join to each other and create phantom matches,
    which is worse than not joining at all."""

    CHARSET = "charset_key"
    """Contains characters the key grammar does not allow, usually a sign of a
    free-text field being used as an identifier."""

    TOO_SHORT = "too_short_key"
    """Shorter than any real identifier from this source; usually truncation in an
    extract."""


#: Sentinels observed as "unknown" markers in source systems. Extending this list
#: is a [DATA] activity: add a value only after a committed profiling script shows
#: it occurring as a non-identifier, never on the strength of it looking suspicious.
PLACEHOLDER_KEYS = frozenset(
    {"", "0", "-", "NA", "N/A", "NULL", "NONE", "UNKNOWN", "NOT AVAILABLE", "XXX"}
)

MIN_KEY_LENGTH = 3
_ALLOWED = re.compile(r"^[A-Z0-9][A-Z0-9_-]*$")


@dataclass(frozen=True)
class SpineKey:
    """A normalised, join-safe identifier."""

    entity: Entity
    value: str

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.entity.value}={self.value}"


@dataclass(frozen=True)
class RejectedKey:
    """A raw key that cannot enter the spine, with its root cause."""

    entity: Entity
    raw: str | None
    problem: KeyProblem


def normalise(entity: Entity, raw: object) -> SpineKey | RejectedKey:
    """Normalise one raw source key into a spine key, or reject it with a cause.

    Normalisation is deliberately shallow: strip, collapse internal whitespace,
    uppercase. It never removes characters. A rule that deleted punctuation would
    make ``LN-001`` and ``LN001`` join, which is a similarity judgement wearing a
    normalisation costume — and that belongs to P1.
    """
    if raw is None:
        return RejectedKey(entity, None, KeyProblem.NULL)

    text = _WHITESPACE.sub(" ", str(raw).strip()).upper()

    if not text:
        return RejectedKey(entity, str(raw), KeyProblem.NULL)
    if text in PLACEHOLDER_KEYS:
        return RejectedKey(entity, text, KeyProblem.PLACEHOLDER)
    if not _ALLOWED.match(text):
        return RejectedKey(entity, text, KeyProblem.CHARSET)
    if len(text) < MIN_KEY_LENGTH:
        return RejectedKey(entity, text, KeyProblem.TOO_SHORT)

    return SpineKey(entity, text)


def normalise_strict(entity: Entity, raw: object) -> SpineKey:
    """Normalise, raising on rejection. For paths where a bad key is a bug."""
    result = normalise(entity, raw)
    if isinstance(result, RejectedKey):
        raise ValueError(f"cannot use {raw!r} as {entity.value}: {result.problem.value}")
    return result

"""Schema-registry backward-compatibility checking.

Phase 0 WS-0.1.4 requires a schema registry with "backward-compatible evolution
enforced in CI". This is that enforcement. The rules follow Avro's resolution
semantics, which is what a Confluent-style registry applies at Track B — checking
them here means a breaking change fails in the pull request rather than at 3am
when a consumer starts throwing.

*Backward compatible* means: a consumer built against the **new** schema can read
data written with the **old** one. That is the direction that matters for a
platform where readers (feature pipelines, Flink jobs, the EWS) are upgraded
before every producer can be.

Workstream: WS-0.1.4
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass
from enum import Enum

#: Avro type promotions a reader can perform without data loss.
PROMOTIONS: dict[str, frozenset[str]] = {
    "int": frozenset({"long", "float", "double"}),
    "long": frozenset({"float", "double"}),
    "float": frozenset({"double"}),
    "string": frozenset({"bytes"}),
    "bytes": frozenset({"string"}),
}


class Severity(str, Enum):
    BREAKING = "breaking"
    WARNING = "warning"


@dataclass(frozen=True)
class CompatIssue:
    severity: Severity
    field: str
    message: str

    def __str__(self) -> str:
        return f"[{self.severity.value}] {self.field}: {self.message}"


@dataclass(frozen=True)
class Schema:
    """A subset of Avro record schema, enough for the two Phase 0 streams."""

    name: str
    version: int
    fields: dict[str, dict]
    raw: dict

    @classmethod
    def from_dict(cls, doc: dict) -> Schema:
        fields = {}
        for field in doc.get("fields", []):
            if "name" not in field or "type" not in field:
                raise ValueError(f"{doc.get('name')}: every field needs a name and a type")
            fields[field["name"]] = field
        return cls(
            name=doc["name"],
            version=int(doc.get("version", 1)),
            fields=fields,
            raw=doc,
        )

    @classmethod
    def load(cls, path: pathlib.Path | str) -> Schema:
        path = pathlib.Path(path)
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _has_default(field: dict) -> bool:
    # `null` is a legitimate default, so membership is the test, not truthiness.
    return "default" in field


def _type_names(field: dict) -> list[str]:
    field_type = field["type"]
    if isinstance(field_type, list):
        return [t if isinstance(t, str) else t.get("type", "record") for t in field_type]
    if isinstance(field_type, dict):
        return [field_type.get("type", "record")]
    return [field_type]


def _promotable(old_types: list[str], new_types: list[str]) -> bool:
    """Can a reader on the new schema read every value the old schema allowed?"""
    for old in old_types:
        if old in new_types:
            continue
        if not any(new in PROMOTIONS.get(old, frozenset()) for new in new_types):
            return False
    return True


def check_backward(old: Schema, new: Schema) -> list[CompatIssue]:
    """Issues preventing a new-schema consumer from reading old-schema data."""
    issues: list[CompatIssue] = []

    if old.name != new.name:
        issues.append(
            CompatIssue(Severity.BREAKING, "<record>",
                        f"record renamed {old.name!r} -> {new.name!r}; a rename is a new "
                        "topic, not an evolution")
        )

    for name, new_field in new.fields.items():
        if name in old.fields:
            continue
        # A field the old data does not carry: the reader must have a default,
        # or every historical message becomes unreadable.
        if not _has_default(new_field):
            issues.append(
                CompatIssue(Severity.BREAKING, name,
                            "field added without a default; a consumer on the new schema "
                            "cannot read any message written before it existed")
            )

    for name, old_field in old.fields.items():
        if name not in new.fields:
            # Dropping a field is backward compatible for the reader, but it
            # silently blinds every downstream feature built on it.
            issues.append(
                CompatIssue(Severity.WARNING, name,
                            "field removed; readers tolerate it, but any feature derived "
                            "from it stops updating without failing — check the feature "
                            "store before merging")
            )
            continue

        old_types, new_types = _type_names(old_field), _type_names(new.fields[name])
        if not _promotable(old_types, new_types):
            issues.append(
                CompatIssue(Severity.BREAKING, name,
                            f"type changed {old_types} -> {new_types} with no safe promotion")
            )

        if _has_default(old_field) and not _has_default(new.fields[name]):
            issues.append(
                CompatIssue(Severity.BREAKING, name,
                            "default removed; messages that relied on it become unreadable")
            )

    return issues


def is_backward_compatible(old: Schema, new: Schema) -> bool:
    return not any(i.severity is Severity.BREAKING for i in check_backward(old, new))

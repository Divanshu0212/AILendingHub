"""Source-registry schema and validator.

Phase 0 WS-0.1.1 requires "a machine-readable source registry (one YAML per source,
schema-validated in CI)". This module is that schema, expressed as code rather than a
JSON-Schema document so it can enforce the rules a JSON Schema cannot: that a
`[POLICY]`-owned field is either a real value or a well-formed ``TBD[owner, ticket]``
placeholder, and never a plausible-looking guess.

Workstream: WS-0.1.1 · SRS §2.1
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from lending_hub.definitions.provenance import Pending

SCHEMA_VERSION = "1.0"


class ExtractMechanism(str, Enum):
    """How data physically leaves the source system (Phase 0 WS-0.1.1)."""

    CDC = "cdc"
    API = "api"
    SFTP_BATCH = "sftp_batch"
    OBJECT_STORE = "object_store"
    STREAM = "stream"


class SourceKind(str, Enum):
    INTERNAL = "internal"
    """Bank system of record — CBS, LOS, collections, KYC."""

    BUREAU = "bureau"
    """Licensed third-party credit data."""

    CONSENTED = "consented"
    """Customer data obtained under an explicit consent artifact (AA, telco)."""

    PUBLIC = "public"
    """Open geospatial/environmental data."""


class Status(str, Enum):
    NOT_STARTED = "not_started"
    PENDING_APPROVAL = "pending_approval"
    """Phase 0 entry criterion: written data-sharing approval not yet received."""

    CONTRACTED = "contracted"
    ONBOARDED = "onboarded"


#: Fields the Phase 0 do-not-invent list marks `[POLICY]`. Each must hold either a
#: value supplied in writing by the named owner, or a well-formed TBD placeholder.
POLICY_FIELDS = ("classification.pii", "retention.period")

REQUIRED_TOP_LEVEL = (
    "id",
    "name",
    "kind",
    "srs_ref",
    "owner",
    "extract",
    "classification",
    "retention",
    "entities",
    "status",
)


@dataclass
class ValidationError:
    """One schema violation, addressed to the file that caused it."""

    source_file: str
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.source_file}: {self.path}: {self.message}"


@dataclass
class SourceRecord:
    """A validated registry entry."""

    id: str
    name: str
    kind: SourceKind
    raw: dict
    path: str
    unresolved: tuple[str, ...] = field(default_factory=tuple)
    """Dotted paths whose value is still a TBD placeholder."""

    @property
    def mechanism(self) -> ExtractMechanism:
        return ExtractMechanism(self.raw["extract"]["mechanism"])

    @property
    def status(self) -> Status:
        return Status(self.raw["status"])

    @property
    def entities(self) -> list[str]:
        return list(self.raw.get("entities", []))


def _get(doc: dict, dotted: str):
    node = doc
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def validate_document(doc: object, source_file: str) -> tuple[SourceRecord | None, list[ValidationError]]:
    """Validate one parsed registry YAML document."""
    errors: list[ValidationError] = []

    def err(path: str, message: str) -> None:
        errors.append(ValidationError(source_file, path, message))

    if not isinstance(doc, dict):
        err("<root>", "registry entry must be a YAML mapping")
        return None, errors

    if doc.get("schema_version") != SCHEMA_VERSION:
        err("schema_version", f"must be {SCHEMA_VERSION!r}, got {doc.get('schema_version')!r}")

    for key in REQUIRED_TOP_LEVEL:
        if key not in doc:
            err(key, "required field is missing")

    source_id = doc.get("id")
    if isinstance(source_id, str):
        if not source_id.islower() or " " in source_id:
            err("id", "must be a lowercase, space-free identifier")
    elif "id" in doc:
        err("id", "must be a string")

    kind = None
    if "kind" in doc:
        try:
            kind = SourceKind(doc["kind"])
        except ValueError:
            err("kind", f"must be one of {[k.value for k in SourceKind]}")

    if "extract" in doc:
        extract = doc["extract"]
        if not isinstance(extract, dict):
            err("extract", "must be a mapping")
        else:
            try:
                ExtractMechanism(extract.get("mechanism"))
            except ValueError:
                err(
                    "extract.mechanism",
                    f"must be one of {[m.value for m in ExtractMechanism]}, "
                    f"got {extract.get('mechanism')!r}",
                )
            if not extract.get("cadence"):
                err("extract.cadence", "refresh cadence is required (WS-0.1.1)")

    if "status" in doc:
        try:
            Status(doc["status"])
        except ValueError:
            err("status", f"must be one of {[s.value for s in Status]}")

    for owner_field in ("owner.business", "owner.technical"):
        if _get(doc, owner_field) in (None, ""):
            err(owner_field, "every source names an owner (WS-0.1.1)")

    entities = doc.get("entities")
    if entities is not None and (
        not isinstance(entities, list) or not all(isinstance(e, str) for e in entities)
    ):
        err("entities", "must be a list of identity-spine entity names")

    if not doc.get("srs_ref"):
        err("srs_ref", "cite the SRS clause this source is drawn from")

    # Residency is not [POLICY]: SRS §12 states it ("all personal data within India;
    # satellite/weather public data exempt"), so it is [SPEC] and must be filled in
    # from the SRS rather than left as a placeholder.
    if _get(doc, "classification.residency") in (None, ""):
        err("classification.residency", "required; grounded in SRS §12 data residency")

    # `[POLICY]` fields: a real value, or a well-formed placeholder. Never blank,
    # never a guess. This is the check that makes the do-not-invent list operational.
    unresolved: list[str] = []
    for policy_field in POLICY_FIELDS:
        value = _get(doc, policy_field)
        if value in (None, ""):
            err(policy_field, "is [POLICY]-owned: give a value or a TBD[owner, ticket]")
            continue
        if not isinstance(value, str):
            continue
        if value.startswith("TBD"):
            if Pending.parse(value) is None:
                err(
                    policy_field,
                    f"malformed placeholder {value!r}; expected TBD[<owner>, <TICKET-N>]",
                )
            else:
                unresolved.append(policy_field)

    if errors:
        return None, errors

    return (
        SourceRecord(
            id=doc["id"],
            name=doc["name"],
            kind=kind,
            raw=doc,
            path=source_file,
            unresolved=tuple(unresolved),
        ),
        [],
    )

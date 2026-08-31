"""Source registry — the machine-readable inventory of every SRS §2.1 source.

Workstream: WS-0.1.1
"""

from .loader import RegistryUnavailable, load_registry, unresolved_policy_fields
from .schema import (
    SCHEMA_VERSION,
    ExtractMechanism,
    SourceKind,
    SourceRecord,
    Status,
    ValidationError,
    validate_document,
)

__all__ = [
    "SCHEMA_VERSION",
    "ExtractMechanism",
    "RegistryUnavailable",
    "SourceKind",
    "SourceRecord",
    "Status",
    "ValidationError",
    "load_registry",
    "unresolved_policy_fields",
    "validate_document",
]

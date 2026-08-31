"""Identity spine — deterministic customer/account/loan keys across CBS, LOS and
collections.

Workstream: WS-0.1.3
"""

from .keys import Entity, KeyProblem, RejectedKey, SpineKey, normalise, normalise_strict
from .spine import FailureCause, SpineAudit, SpineRecord, build_spine
from .survivorship import SYSTEM_OF_RECORD, Conflict, Resolution, resolve, resolve_all

__all__ = [
    "SYSTEM_OF_RECORD",
    "Conflict",
    "Entity",
    "FailureCause",
    "KeyProblem",
    "RejectedKey",
    "Resolution",
    "SpineAudit",
    "SpineKey",
    "SpineRecord",
    "build_spine",
    "normalise",
    "normalise_strict",
    "resolve",
    "resolve_all",
]

"""Streaming backbone — event schemas, compatibility rules, freshness.

Workstream: WS-0.1.4
"""

from .compat import (
    CompatIssue,
    Schema,
    Severity,
    check_backward,
    is_backward_compatible,
)
from .freshness import FRESHNESS_GATE, FreshnessReport

__all__ = [
    "FRESHNESS_GATE",
    "CompatIssue",
    "FreshnessReport",
    "Schema",
    "Severity",
    "check_backward",
    "is_backward_compatible",
]

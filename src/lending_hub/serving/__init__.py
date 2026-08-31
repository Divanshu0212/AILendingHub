"""Serving — decision orchestrator, load test, parity harness.

The orchestrator API is re-exported here. The two CLI modules
(:mod:`lending_hub.serving.loadtest` and :mod:`lending_hub.serving.parity`) are
deliberately *not*: importing a module here that is also run with ``python -m``
makes Python import it twice and emit a RuntimeWarning on every run, and output
noise on a routine command is how people learn to stop reading output. Import
those two directly.

Workstream: WS-0.2.4, WS-0.4, Phase 1 §5
"""

from .bands import (
    REQUIRED_APPROVERS,
    Approval,
    BandConfig,
    BandConfigError,
    canary_assignment,
    load_bands,
)
from .orchestrator import (
    DecisionResponse,
    ModelUnavailable,
    Orchestrator,
    PolicyRule,
    Timings,
)
from .shadow import (
    MINIMUM_CANARY,
    MINIMUM_SHADOW,
    DailyComparison,
    LadderStatus,
    ShadowError,
    ShadowReport,
    canary_status,
    compare_day,
    shadow_status,
)

__all__ = [
    "MINIMUM_CANARY",
    "MINIMUM_SHADOW",
    "REQUIRED_APPROVERS",
    "Approval",
    "BandConfig",
    "BandConfigError",
    "DailyComparison",
    "DecisionResponse",
    "LadderStatus",
    "ModelUnavailable",
    "Orchestrator",
    "PolicyRule",
    "ShadowError",
    "ShadowReport",
    "Timings",
    "canary_assignment",
    "canary_status",
    "compare_day",
    "load_bands",
    "shadow_status",
]

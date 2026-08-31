"""Serving — decision orchestrator, load test, parity harness.

The orchestrator API is re-exported here. The two CLI modules
(:mod:`lending_hub.serving.loadtest` and :mod:`lending_hub.serving.parity`) are
deliberately *not*: importing a module here that is also run with ``python -m``
makes Python import it twice and emit a RuntimeWarning on every run, and output
noise on a routine command is how people learn to stop reading output. Import
those two directly.

Workstream: WS-0.2.4, WS-0.4
"""

from .orchestrator import (
    DecisionResponse,
    ModelUnavailable,
    Orchestrator,
    PolicyRule,
    Timings,
)

__all__ = [
    "DecisionResponse",
    "ModelUnavailable",
    "Orchestrator",
    "PolicyRule",
    "Timings",
]

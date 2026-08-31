"""Decision logging — the 8-year audit spine.

Workstream: Master §3.3
"""

from .record import Actor, DecisionRecord, ModelRef, Outcome, ReasonCode
from .replay import SCORE_TOLERANCE, ReplayMismatch, ReplayReport, spot_audit
from .store import ChainStatus, DecisionLog, TamperDetected

__all__ = [
    "SCORE_TOLERANCE",
    "Actor",
    "ChainStatus",
    "DecisionLog",
    "DecisionRecord",
    "ModelRef",
    "Outcome",
    "ReasonCode",
    "ReplayMismatch",
    "ReplayReport",
    "TamperDetected",
    "spot_audit",
]

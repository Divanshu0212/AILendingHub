"""MLOps — artifacts, the reproducibility triplet, and the promotion gate.

Workstream: WS-0.2.2, WS-0.2.3
"""

from .artifact import ModelArtifact, Stage, Triplet, config_hash
from .ports import InMemoryRegistry, MlflowRegistry, ModelRegistry
from .promotion import (
    LEGAL_TRANSITIONS,
    MINIMUM_SHADOW,
    PromotionDecision,
    can_promote,
)

__all__ = [
    "LEGAL_TRANSITIONS",
    "MINIMUM_SHADOW",
    "InMemoryRegistry",
    "MlflowRegistry",
    "ModelArtifact",
    "ModelRegistry",
    "PromotionDecision",
    "Stage",
    "Triplet",
    "can_promote",
    "config_hash",
]

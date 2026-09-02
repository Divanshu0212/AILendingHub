"""Phase 6 — learning loops and advanced challengers (SRS §5, §6, §7, §10, §11).

Built module by module; see :mod:`lending_hub.learning.promotion` first — Phase 6
§4's standing criterion is the phase's central artifact and the only one Track B
needs unchanged.

Workstream: WS-6.1 … WS-6.7
"""

from .promotion import (
    AbTestFeasibility,
    EvaluationWindow,
    LiftMeasurement,
    PromotionError,
    PromotionRequest,
    RollbackPlan,
    StandingDecision,
    evaluate_promotion,
)

__all__ = [
    "AbTestFeasibility",
    "EvaluationWindow",
    "LiftMeasurement",
    "PromotionError",
    "PromotionRequest",
    "RollbackPlan",
    "StandingDecision",
    "evaluate_promotion",
]

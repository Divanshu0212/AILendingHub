"""Phase 6 — learning loops and advanced challengers (SRS §5, §6, §7, §10, §11).

Built module by module; see :mod:`lending_hub.learning.promotion` first — Phase 6
§4's standing criterion is the phase's central artifact and the only one Track B
needs unchanged.

Workstream: WS-6.1 … WS-6.7
"""

from .uplift import (
    ActionLog,
    ActionRecord,
    Assignment,
    BalanceReport,
    UpliftError,
    check_randomization,
    estimate_uplift,
    qini_coefficient,
    qini_curve,
)
from .graph import (
    CommunityError,
    CommunityScore,
    Partition,
    louvain,
    modularity,
    score_communities,
)
from .offpolicy import (
    DoublyRobustEstimate,
    LoggedDecision,
    OffPolicyError,
    PositivityReport,
    check_positivity,
    evaluate_policy,
    from_bandit_decisions,
)
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
    "ActionLog",
    "ActionRecord",
    "Assignment",
    "BalanceReport",
    "CommunityError",
    "CommunityScore",
    "DoublyRobustEstimate",
    "LoggedDecision",
    "OffPolicyError",
    "Partition",
    "PositivityReport",
    "EvaluationWindow",
    "LiftMeasurement",
    "PromotionError",
    "PromotionRequest",
    "RollbackPlan",
    "StandingDecision",
    "UpliftError",
    "check_positivity",
    "check_randomization",
    "evaluate_policy",
    "from_bandit_decisions",
    "estimate_uplift",
    "louvain",
    "modularity",
    "score_communities",
    "evaluate_promotion",
    "qini_coefficient",
    "qini_curve",
]

"""Phase 6 — learning loops and advanced challengers (SRS §5, §6, §7, §10, §11).

Phase 6 is the first phase in the programme that is not a deliverable. Its card
says so — *"steady-state operating rhythm, not a fixed project"* — and its exit
criterion in §4 is **standing**: it applies to every promotion, forever, rather
than once at a gate review.

That inverts what is buildable here. Every challenger in §2 (CARE-GNN,
GraphSAGE, Noiseprint, DeepSurv, a sequence model, a causal forest) feeds on a
loop that has never run: fraud-desk dispositions, action-outcome logs,
randomized holdouts, a labelled forgery set. **A learning loop with no prior
iteration has nothing to learn from.** But the rule that governs those
challengers is pure logic, and it is better written before the first promotion
request than under pressure by whoever is shipping it.

So what is built is the protocol layer and the identifiability guards
([ADR-0016](../../../docs/adr/0016-phase6-learning-loops-track.md)):

* :mod:`~lending_hub.learning.promotion` — §4's standing criterion, composed
  onto Phase 0's artifact gate. Out-of-time is *checked*, not asserted.
* :mod:`~lending_hub.learning.uplift` — WS-6.4's causal guard. Refuses an effect
  estimate from a log it cannot verify was randomized.
* :mod:`~lending_hub.learning.offpolicy` — WS-6.5's doubly-robust estimator,
  with positivity as a refusal rather than a diagnostic.
* :mod:`~lending_hub.learning.graph` — WS-6.1's Louvain scorer, the one
  component here that runs on real data today, because it is unsupervised.
* :mod:`~lending_hub.learning.challenger` — what makes two evaluations
  comparable at all.
* :mod:`~lending_hub.learning.cadence` — WS-6.7's rhythm, as data with overdue
  detection.

**The distinction this phase adds** is a third gate state beyond Phase 3's *not
measured* / *not measurable*: **unidentifiable**. Those two are both about
missing data — given the right dataset, the number appears. WS-6.4's uplift is
missing *randomization*, and no quantity of observational action logs supplies
it. More rows narrow the interval around a confounded quantity instead of
converging on the causal one, which turns a visible uncertainty into an
invisible bias.

Workstream: WS-6.1 … WS-6.7
"""

from .cadence import CADENCE, Activity, CadenceError, Frequency, overdue, runnable
from .challenger import ChallengerEntry, ChallengerVerdict, ComparisonError, assess, compare
from .graph import CommunityError, CommunityScore, Partition, louvain, modularity, score_communities
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

__all__ = [
    "CADENCE",
    "AbTestFeasibility",
    "ActionLog",
    "ActionRecord",
    "Activity",
    "Assignment",
    "BalanceReport",
    "CadenceError",
    "ChallengerEntry",
    "ChallengerVerdict",
    "CommunityError",
    "CommunityScore",
    "ComparisonError",
    "DoublyRobustEstimate",
    "EvaluationWindow",
    "Frequency",
    "LiftMeasurement",
    "LoggedDecision",
    "OffPolicyError",
    "Partition",
    "PositivityReport",
    "PromotionError",
    "PromotionRequest",
    "RollbackPlan",
    "StandingDecision",
    "UpliftError",
    "assess",
    "check_positivity",
    "check_randomization",
    "compare",
    "estimate_uplift",
    "evaluate_policy",
    "evaluate_promotion",
    "from_bandit_decisions",
    "louvain",
    "modularity",
    "overdue",
    "qini_coefficient",
    "qini_curve",
    "runnable",
    "score_communities",
]

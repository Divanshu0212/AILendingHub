"""The handlers that return a number something actually computed.

This module is deliberately short, and its length is the honest measure of how
much of the Phase 7 surface this repository can serve today. Everything not here
is in :mod:`lending_hub.gateway.blocked`, with a ticket.

THE RULE EVERY HANDLER HERE FOLLOWS
-------------------------------------
A handler may call an existing module and format what comes back. It may not
compute. Master §2 rule 2 gives one reference implementation per algorithm, and
an EMI recomputed here — even correctly, even identically — is a second
implementation that will drift from `reco.feasible.emi` the first time a
day-count convention lands in one of them. So :func:`quote_instalment` calls
`emi()` and `total_interest()` and does arithmetic on neither.

WHY THESE FOUR AND NOT OTHERS
-------------------------------
The test each one passes: *is there an input the caller can legitimately supply,
and a committed implementation that turns it into an answer, with no unratified
policy value in between?*

* **Instalment quote** — `emi(a, r, n)` is pure arithmetic on three caller-given
  numbers. The caps that decide whether that instalment is *permissible* are
  LH-504 and unratified, which is why this endpoint returns an instalment and
  emphatically not an eligibility: `/v1/applications/{id}/offers` is blocked, and
  a quote is not a feasible set. The distinction is the whole reason this
  endpoint is safe to ship — see the docstring on :func:`quote_instalment`.
* **Fraud subgraph / community structure** — Louvain is unsupervised, so it is
  the one component in `learning/` with real input (ADR-0016). It partitions the
  graph the caller posts. `fraud_label_density` raises, and this handler lets it.
* **Off-policy evaluation** — a doubly-robust estimate over decisions the caller
  supplies, refusing a log that violates positivity rather than widening an
  interval.
* **Learning cadence** — the WS-6.7 table is `[SPEC]`, transcribed, and `overdue`
  computes against a caller-supplied grace with no default.

WHAT NONE OF THEM CARRY
-------------------------
An attribution triplet. Not one of these four came from a fitted model: Louvain
is an algorithm run on a posted graph, the DR estimator is an estimator, the
cadence table is a transcription, and `emi` is a formula. The client marks none
of the routes they serve `modelDerived`, so no triplet is required — and
attaching one would name a model that did not exist. The endpoints that *are*
marked `modelDerived` are exactly the ones in :mod:`~lending_hub.gateway.blocked`,
which is not a coincidence: a model-derived value needs a model, and none is
fitted here.

Workstream: WS-7.1.1 (SRS §11.6a)
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Mapping

from lending_hub.fraud.entity_resolution import (
    Edge,
    EdgeType,
    EntityGraph,
    Node,
    NodeType,
)
from lending_hub.gateway.contract import FormattedNumber, Unavailable
from lending_hub.learning.cadence import CADENCE, CadenceError, overdue, runnable
from lending_hub.learning.graph import CommunityError, louvain, modularity, score_communities
from lending_hub.learning.offpolicy import (
    LoggedDecision,
    OffPolicyError,
    check_positivity,
    evaluate_policy,
)
from lending_hub.reco.feasible import FeasibilityError, emi, total_interest


class BadRequest(Exception):
    """The caller's input is malformed. Rendered as a 400."""


def _number(body: Mapping[str, Any], key: str) -> float:
    if key not in body:
        raise BadRequest(f"missing required field {key!r}")
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BadRequest(f"field {key!r} must be a number, got {type(value).__name__}")
    return float(value)


def _integer(body: Mapping[str, Any], key: str) -> int:
    value = _number(body, key)
    if value != int(value):
        raise BadRequest(f"field {key!r} must be a whole number, got {value}")
    return int(value)


# --------------------------------------------------------------- instalment


def _rupees(amount: float) -> FormattedNumber:
    """Render a rupee figure to two decimals.

    Two decimals is a *rendering* of a number this gateway did not invent, and
    the boundary matters: Phase 7 §8 forbids the frontend choosing a rounding
    for a repayment figure precisely because that choice is a disclosure
    decision, and moving it here does not make it a ratified one. The real
    convention belongs to the loan management system alongside fees and the odd
    first period, which `reco.feasible` says explicitly it does not model.

    So this is an ungrounded choice, registered as LH-713 rather than left as a
    comment. It does not *raise* — unlike a missing FOIR cap, an absent rounding
    convention does not change which side of a limit a number falls on, and
    refusing to render a computed EMI at all would hide the one real
    computation this gateway performs. But it bounds what the string may be used
    for: a display of a computed number, never a quoted instalment on a sanction
    letter or a Key Fact Statement.
    """
    return FormattedNumber(amount=amount, display=f"₹{amount:,.2f}", currency="INR")


def quote_instalment(body: Mapping[str, Any]) -> dict[str, Any]:
    """``POST /v1/quotes/instalment`` — a real EMI from `reco.feasible.emi`.

    THIS IS NOT AN ELIGIBILITY, AND THE DIFFERENCE IS THE POINT
    ------------------------------------------------------------
    It answers "what is the instalment on this principal, at this rate, over
    this tenor" — arithmetic, fully determined by the three inputs, with no
    policy in it. It does not answer "may this borrower have this loan", which
    needs FOIR/DSCR/LTV caps that are LH-504 and unratified, and it does not
    answer "what rate applies", which is LH-505.

    So the caller supplies the rate. That is a deliberate shape: a gateway that
    looked up a rate would be serving a price nobody ratified, and a gateway
    that defaulted one would be worse. `/v1/applications/{id}/offers` — the
    endpoint that would decide both — returns unavailable.

    The response carries no attribution and the client does not ask for one:
    `emi` is a formula in a phase file, not a model, and `modelDerived` is false
    on every route this serves.
    """
    principal = _number(body, "amount")
    annual_rate = _number(body, "annualRate")
    tenor = _integer(body, "tenorMonths")

    # `emi` takes a DECIMAL annual rate (0.125 for 12.5%), and the field name
    # `annualRate` invites the percentage. Sending 12.5 does not fail — it
    # returns an instalment of 520,833 on a principal of 500,000, which is
    # arithmetically correct for a 1250% rate and nonsense as an answer.
    #
    # A wrong unit that raises is a bug; a wrong unit that returns a
    # confident number is the failure this repository exists to prevent, so the
    # ambiguous range is refused rather than guessed. No consumer lending rate
    # is 100% or above as a decimal, and none is below 0.01 as a percentage, so
    # a value >= 1.0 is unambiguously a percentage sent as if it were a decimal.
    if annual_rate >= 1.0:
        raise BadRequest(
            f"annualRate {annual_rate} must be a decimal fraction, not a "
            f"percentage: send {annual_rate / 100:g} for {annual_rate:g}%. "
            "Passed as-is this returns a real EMI for a rate of "
            f"{annual_rate * 100:g}%, which is arithmetically correct and "
            "useless — so it is refused rather than answered."
        )

    try:
        instalment = emi(principal, annual_rate, tenor)
        interest = total_interest(principal, annual_rate, tenor)
    except FeasibilityError as error:
        raise BadRequest(str(error)) from error

    return {
        "amount": _rupees(principal).to_json(),
        "tenorMonths": tenor,
        # The rate is echoed as the caller sent it. It is an input, not a price
        # this gateway holds a view on.
        "annualRate": FormattedNumber(
            amount=annual_rate, display=f"{annual_rate * 100:.4g}%"
        ).to_json(),
        "emi": _rupees(instalment).to_json(),
        "totalInterest": _rupees(interest).to_json(),
        "computedBy": "lending_hub.reco.feasible.emi",
        "feasibilityAssessed": False,
        "feasibilityNote": (
            "This is arithmetic on the inputs supplied, not an eligibility "
            "decision. Whether this instalment is permissible needs the ratified "
            "FOIR/DSCR/LTV caps (LH-504); whether this rate applies needs ALM "
            "pricing (LH-505). Neither is available, so no offer is implied."
        ),
    }


# ------------------------------------------------------------------- graph


def _graph_from(body: Mapping[str, Any]) -> EntityGraph:
    nodes = body.get("nodes")
    edges = body.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise BadRequest("body needs 'nodes' and 'edges' arrays")

    graph = EntityGraph()
    for raw in nodes:
        if not isinstance(raw, dict):
            raise BadRequest("each node must be an object")
        node_id = raw.get("nodeId")
        kind = raw.get("kind")
        if not isinstance(node_id, str) or not node_id:
            raise BadRequest("each node needs a non-empty 'nodeId'")
        try:
            node_type = NodeType(kind)
        except ValueError as error:
            raise BadRequest(
                f"unknown node kind {kind!r}; expected one of "
                f"{sorted(t.value for t in NodeType)}"
            ) from error
        graph.add_node(Node(node_id, node_type))

    for raw in edges:
        if not isinstance(raw, dict):
            raise BadRequest("each edge must be an object")
        source, target, kind = raw.get("from"), raw.get("to"), raw.get("kind")
        if not isinstance(source, str) or not isinstance(target, str):
            raise BadRequest("each edge needs string 'from' and 'to'")
        if source not in graph.nodes or target not in graph.nodes:
            raise BadRequest(f"edge {source}->{target} references an undeclared node")
        try:
            edge_type = EdgeType(kind)
        except ValueError as error:
            raise BadRequest(
                f"unknown edge kind {kind!r}; expected one of "
                f"{sorted(t.value for t in EdgeType)}"
            ) from error
        graph.add_edge(Edge(source, target, edge_type))

    if not graph.nodes:
        raise BadRequest("an empty graph has no communities to detect")
    return graph


def detect_communities(body: Mapping[str, Any]) -> dict[str, Any]:
    """``POST /v1/graph/communities`` — real Louvain on the posted graph.

    WS-6.1's community detection is unsupervised, which is why it runs here when
    nothing else in `learning/` does: it needs a graph and no labels. The graph
    comes from the caller — the gateway holds no application table.

    `fraud_label_density` is the half of WS-6.1's scorer that needs fraud-desk
    dispositions (LH-810), and this handler does not catch its refusal into a
    number. It reports it as a per-community unavailable, because a scorer
    presenting entropy alone would rank communities plausibly and would not be
    the scorer the workstream specifies.
    """
    graph = _graph_from(body)
    try:
        partition = louvain(graph)
        scores = score_communities(graph, partition)
    except CommunityError as error:
        raise BadRequest(str(error)) from error

    label_density_block: dict[str, Any] | None = None
    if scores:
        try:
            scores[0].fraud_label_density
        except CommunityError as error:
            label_density_block = {
                "status": "unavailable",
                "capability": "fraud-label density per community",
                "ticket": "LH-810",
                "owner": "Fraud Head",
                "reason": str(error),
            }

    return {
        "nodeCount": len(graph.nodes),
        "edgeCount": len(graph.edges),
        "communityCount": len(partition.communities),
        "modularity": partition.modularity,
        # Display string beside the raw value, so the render layer chooses
        # no rounding for a figure a reviewer will quote (Phase 7 §8).
        "modularityDisplay": f"{partition.modularity:.3f}",
        "modularityIfSingleCommunity": modularity(graph, [frozenset(graph.nodes)]),
        "passes": partition.passes,
        "communities": [
            {
                "communityId": s.community_id,
                "size": s.size,
                "sharedAttributeEntropy": s.shared_attribute_entropy,
                "internalDensity": s.internal_density,
                # Display string alongside the raw fraction, per Phase 7 §8:
                # choosing a rounding is a decision about what the number
                # means, and the render layer is forbidden from making it.
                "internalDensityDisplay": f"{s.internal_density * 100:.0f}%",
                "dominantEdgeType": s.dominant_edge_type,
                "nodeTypes": dict(s.node_types),
            }
            for s in scores
        ],
        "computedBy": "lending_hub.learning.graph.louvain",
        "fraudLabelDensity": label_density_block,
    }


# ------------------------------------------------------------- off-policy


def evaluate_offpolicy(body: Mapping[str, Any]) -> dict[str, Any]:
    """``POST /v1/learning/offpolicy`` — a real doubly-robust estimate.

    The refusal is as much of the endpoint as the estimate. `evaluate_policy`
    rejects a log that violates positivity rather than returning a wide
    interval, because an unsupported estimate is not an imprecise one — so a
    caller posting a log whose target policy takes actions the logging policy
    never took gets a 400 naming the violation, not a number with a caveat.
    """
    raw = body.get("decisions")
    if not isinstance(raw, list) or not raw:
        raise BadRequest("body needs a non-empty 'decisions' array")

    decisions: list[LoggedDecision] = []
    for item in raw:
        if not isinstance(item, dict):
            raise BadRequest("each decision must be an object")
        try:
            decisions.append(
                LoggedDecision(
                    context_id=str(item["contextId"]),
                    action=str(item["action"]),
                    propensity=float(item["propensity"]),
                    reward=float(item["reward"]),
                )
            )
        except KeyError as error:
            raise BadRequest(
                f"each decision needs contextId, action, propensity and reward; "
                f"missing {error}"
            ) from error
        except (TypeError, ValueError) as error:
            raise BadRequest(f"malformed decision: {error}") from error
        except OffPolicyError as error:
            raise BadRequest(str(error)) from error

    target = body.get("targetPolicy")
    if not isinstance(target, dict) or not target:
        raise BadRequest(
            "body needs a 'targetPolicy' object mapping contextId -> action. "
            "A policy that is not specified per context cannot be evaluated "
            "against a log."
        )
    policy_table = {str(k): str(v) for k, v in target.items()}

    def target_policy(context_id: str) -> str:
        if context_id not in policy_table:
            # Deliberately fatal rather than falling back to the logged action.
            # A target policy silently agreeing with the log wherever it was not
            # specified evaluates to the logged value and looks like a result.
            raise BadRequest(
                f"targetPolicy does not specify an action for context "
                f"{context_id!r}. An unspecified context cannot default to the "
                "logged action: a target policy that agrees with the log "
                "wherever it was not stated evaluates to the log's own value."
            )
        return policy_table[context_id]

    rewards = body.get("rewardModel")
    if not isinstance(rewards, dict) or not rewards:
        raise BadRequest(
            "body needs a 'rewardModel' object mapping 'contextId|action' -> "
            "expected reward. The doubly-robust estimator needs a direct-method "
            "component; supplying none is not a simpler call, it is the IPS "
            "estimator, which WS-6.5 deliberately does not name."
        )
    reward_table = {str(k): float(v) for k, v in rewards.items()}

    def reward_model(context_id: str, action: str) -> float:
        key = f"{context_id}|{action}"
        if key not in reward_table:
            raise BadRequest(
                f"rewardModel has no entry for {key!r}. A missing r-hat is not "
                "zero: zero is a prediction, and the DR correction term is "
                "computed against it."
            )
        return reward_table[key]

    try:
        positivity = check_positivity(decisions, target_policy)
        estimate = evaluate_policy(decisions, target_policy, reward_model)
    except OffPolicyError as error:
        raise BadRequest(str(error)) from error
    except (TypeError, ValueError) as error:
        raise BadRequest(str(error)) from error

    low, high = estimate.confidence_interval()
    return {
        "estimate": estimate.value,
        "standardError": estimate.standard_error,
        "loggedValue": estimate.logged_value,
        "lift": estimate.lift,
        "n": estimate.n,
        # The interval is returned WITH the point estimate precisely because
        # LH-804 is that a sign test on the point estimate is not a decision
        # rule. z=1.96 is the caller-facing default of `confidence_interval`,
        # which is a normal-approximation convention rather than a policy
        # threshold, and it is labelled as such.
        "confidenceInterval": {"low": low, "high": high, "z": 1.96},
        "positivity": {
            "supported": positivity.supported,
            "violations": [
                {"contextId": c, "action": a, "propensity": p}
                for c, a, p in positivity.violations
            ],
            "unsupportedActions": list(positivity.unsupported_actions),
            "effectiveSampleSize": positivity.effective_sample_size,
        },
        "computedBy": "lending_hub.learning.offpolicy.evaluate_policy",
        "verdict": None,
        "verdictNote": (
            "No promote/hold verdict is returned. The canary confidence "
            "requirement is LH-804: 'only positive-DR-estimate policies "
            "proceed' is a sign test on a point estimate whose interval may "
            "span zero, and this response reports both so the caller can see "
            "which it is."
        ),
    }


# ---------------------------------------------------------------- cadence


def _parse_date(value: Any, field_name: str) -> date:
    if not isinstance(value, str):
        raise BadRequest(f"{field_name} must be an ISO-8601 date string")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise BadRequest(f"{field_name}: {error}") from error


def learning_cadence(query: Mapping[str, str], body: Mapping[str, Any]) -> dict[str, Any]:
    """``POST /v1/learning/cadence`` — the WS-6.7 schedule, evaluated.

    `graceDays` is required and this handler supplies no default, mirroring
    `cadence.overdue`. LH-807 is precisely that the phase file states intervals
    and no tolerances, and a default here would silently become the tolerance
    for every activity in the programme.

    `shippedPhases` is likewise the caller's, because which phases have shipped
    is a deployment fact this process cannot observe — and defaulting it to "all"
    would report every activity runnable, while defaulting it to "none" would
    report an empty schedule. Both look like answers.
    """
    if "graceDays" not in body:
        raise BadRequest(
            "graceDays is required and has no default. The WS-6.7 table gives "
            "intervals and no grace, and the two are different questions "
            "(LH-807) — a default here would become the programme's tolerance "
            "without anyone ratifying it."
        )
    grace_days = _integer(body, "graceDays")
    if grace_days < 0:
        raise BadRequest("graceDays cannot be negative")

    as_of_raw = body.get("asOf")
    as_of = _parse_date(as_of_raw, "asOf") if as_of_raw is not None else date.today()

    shipped = body.get("shippedPhases")
    if not isinstance(shipped, list):
        raise BadRequest(
            "shippedPhases is required: which phases have shipped is a "
            "deployment fact this process cannot observe, and either default "
            "('all' or 'none') would look like an answer."
        )
    shipped_phases = [str(p) for p in shipped]

    last_run_raw = body.get("lastRun") or {}
    if not isinstance(last_run_raw, dict):
        raise BadRequest("'lastRun' must be an object mapping activity name -> ISO date")
    last_run = {
        str(k): _parse_date(v, f"lastRun[{k}]") for k, v in last_run_raw.items()
    }

    applicable = runnable(CADENCE, shipped_phases)
    try:
        items = overdue(applicable, last_run, as_of=as_of, grace=timedelta(days=grace_days))
    except CadenceError as error:
        raise BadRequest(str(error)) from error

    by_name = {i.activity.name: i for i in items}
    return {
        "asOf": as_of.isoformat(),
        "graceDays": grace_days,
        "activities": [
            {
                "name": a.name,
                "frequency": a.frequency.value,
                "owningPhase": a.owning_phase,
                "conditional": a.conditional or None,
                "runnable": a in applicable,
                # never-run and late are different states with different causes,
                # so they are different fields rather than one nullable number.
                "neverRun": by_name[a.name].never_run if a.name in by_name else False,
                "daysLate": by_name[a.name].days_late if a.name in by_name else None,
            }
            for a in CADENCE
        ],
        "runnableCount": len(applicable),
        "overdueCount": len(items),
        "computedBy": "lending_hub.learning.cadence.overdue",
    }


__all__ = [
    "BadRequest",
    "quote_instalment",
    "detect_communities",
    "evaluate_offpolicy",
    "learning_cadence",
]

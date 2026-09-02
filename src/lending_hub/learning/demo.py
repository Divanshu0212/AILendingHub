"""An interactive demonstration of the WS-6 computations — Phase 6.

What this is, and the line it does not cross
---------------------------------------------
Phase 6 fits **no models** (ADR-0016), so there is nothing here that takes an
applicant and returns a prediction, and this module does not pretend otherwise.
A demo that appeared to score a customer would be fabricating the very thing the
phase refused to fabricate.

What Phase 6 *does* have is six modules of deterministic computation, and those
take input and produce real output. Every number this module prints comes from
calling the actual implementation on the data you supply — nothing is canned,
and no branch prints a result it did not compute. Change an input and the output
changes, because it was computed.

That distinction is the whole design:

* **Demonstrable** — Louvain partitions the graph you enter. The doubly-robust
  estimator values the policy you describe. The promotion gate returns the
  refusal reasons your request actually earns.
* **Not demonstrable** — any challenger model's prediction, any measured lift,
  any fraud-label density. Those need feedback loops that have never run, and
  the demo *shows you the refusal* rather than skipping the topic.

The refusals are the point, not an apology
--------------------------------------------
Four of the seven scenarios below end in an exception, and they are the most
useful part of the demo. Watching :func:`~lending_hub.learning.uplift.estimate_uplift`
refuse an observational log — with the reason attached — teaches Phase 6's
central idea more directly than any number could: uplift from a confounded log
is not a worse estimate, it is a different quantity, and more data narrows the
interval around the wrong number.

So the demo prints refusals in the same visual weight as results. A demo that
only showed the happy paths would misrepresent a package whose main contribution
is knowing what it must not compute.

Synthetic data (Master §2 rule 3)
-----------------------------------
The inputs below are illustrative and obviously so — six applicants named
``a1``..``b3``, round-numbered rewards. They are *arguments to a function*, never
a training table, and nothing computed here is reported as a Phase 6 number or
reaches any gate pack. `make gate6` reads the code, not this module.

Workstream: WS-6.1 … WS-6.7
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta

from lending_hub.definitions import fingerprint
from lending_hub.fraud.entity_resolution import (
    Edge,
    EdgeType,
    EntityGraph,
    Node,
    NodeType,
)
from lending_hub.mlops.artifact import ModelArtifact, Stage, Triplet

from .cadence import CADENCE, Frequency, overdue, runnable
from .challenger import ChallengerEntry, ComparisonError, assess
from .graph import CommunityError, louvain, modularity, score_communities
from .offpolicy import LoggedDecision, OffPolicyError, evaluate_policy
from .promotion import (
    AbTestFeasibility,
    EvaluationWindow,
    LiftMeasurement,
    PromotionRequest,
    RollbackPlan,
    evaluate_promotion,
)
from .uplift import (
    ActionLog,
    ActionRecord,
    Assignment,
    UpliftError,
    estimate_uplift,
    qini_coefficient,
    qini_curve,
)

RULE = "=" * 72
THIN = "-" * 72


def _heading(number: int, title: str, module: str) -> None:
    print(f"\n{RULE}\n {number}. {title}\n    lending_hub.learning.{module}\n{RULE}")


def _refusal(error: Exception) -> None:
    """Print an exception as a first-class outcome rather than an error.

    Same visual weight as a result, because in this package a refusal *is* the
    result — and one that a reader should be able to quote.
    """
    print(f"\n  REFUSED — {type(error).__name__}")
    for line in str(error).split(". "):
        text = line.strip().rstrip(".")
        if text:
            print(f"    {text}.")


def demo_graph(size: int) -> None:
    """WS-6.1 — Louvain on an entity graph you can vary."""
    _heading(1, "Community detection on an entity graph", "graph")

    graph = EntityGraph()
    left = [f"a{i}" for i in range(1, size + 1)]
    right = [f"b{i}" for i in range(1, size + 1)]
    for name in left + right:
        graph.add_node(Node(name, NodeType.APPLICANT))

    # Two dense clusters sharing a device internally, joined by one weak link.
    for group in (left, right):
        for i, source in enumerate(group):
            for target in group[i + 1 :]:
                graph.add_edge(Edge(source, target, EdgeType.SHARES_DEVICE))
    graph.add_edge(Edge(left[0], right[0], EdgeType.SHARES_ADDRESS))

    print(f"\n  input: {len(graph.nodes)} applicants, {len(graph.edges)} shared-attribute edges")
    print(f"         two groups of {size}, joined by one shared address")

    partition = louvain(graph)
    print(f"\n  communities found: {len(partition.communities)}  sizes {list(partition.sizes)}")
    print(f"  modularity Q     : {partition.modularity:.6f}")
    print(f"  aggregation passes: {partition.passes}")

    everything = [frozenset(graph.nodes)]
    print(f"  Q if all one community: {modularity(graph, everything):.6f}  (the partition beats it)")

    print(f"\n  {THIN}")
    for score in score_communities(graph, partition):
        print(f"  community {score.community_id}: {score.size} members")
        print(f"    shared-attribute entropy : {score.shared_attribute_entropy:.4f}  (0 = one attribute = ring signature)")
        print(f"    internal density         : {score.internal_density:.4f}")
        print(f"    dominant edge type       : {score.dominant_edge_type}")

    print("\n  Now the half of WS-6.1's scorer that cannot be computed:")
    try:
        score_communities(graph, partition)[0].fraud_label_density
    except CommunityError as error:
        _refusal(error)


def demo_promotion() -> None:
    """§4 — the standing criterion, on a request with real defects."""
    _heading(2, "The standing promotion criterion", "promotion")

    now = datetime(2026, 9, 2)
    train_end = datetime(2026, 1, 1)

    artifact = ModelArtifact(
        name="ews-challenger",
        version="3",
        triplet=Triplet("a" * 40, "snap-2026-08", "c" * 12),
        definitions_fingerprint=fingerprint(),
        stage=Stage.STAGING,
        model_card_path="docs/phase6/model_cards/x.md",
        validation_report_path="docs/governance/validation/x.md",
        shadow_started_at=now - timedelta(weeks=6),
    )

    # An evaluation window that OVERLAPS training — the mistake a submitter
    # makes while believing they did out-of-time validation.
    leaky = EvaluationWindow(
        train_end=train_end,
        eval_start=train_end - timedelta(days=45),
        eval_end=datetime(2026, 6, 1),
    )

    request = PromotionRequest(
        artifact=artifact,
        target=Stage.PRODUCTION,
        lift=LiftMeasurement("recall@budget", 0.41, 0.47, leaky, "retail unsecured"),
        rollback=RollbackPlan(trigger="precision drop 3 days", owner="EWS on-call"),
        ab_test=AbTestFeasibility.FEASIBLE_NOT_RUN,
        submitted_by="ews-squad-lead",
    )

    print("\n  submitted: a challenger with a model card, a validation report,")
    print("             6 weeks of shadow, and +0.06 recall over the champion.")
    print("             Every Phase 0 artifact condition passes.")

    decision = evaluate_promotion(request, now=now, via_ci=True)
    print(f"\n  allowed: {decision.allowed}")
    print(f"\n  {THIN}\n  reasons ({len(decision.reasons)}), all returned at once:")
    for reason in decision.reasons:
        print(f"    · {reason}")

    print("\n  Note what caught it: the lift was real and the artifact was clean.")
    print("  The window overlapped training by "
          f"{leaky.overlap_days} days, and an A/B was available and skipped.")

    # The same request, corrected.
    fixed = PromotionRequest(
        artifact=artifact,
        target=Stage.PRODUCTION,
        lift=LiftMeasurement(
            "recall@budget",
            0.41,
            0.47,
            EvaluationWindow(train_end, train_end, datetime(2026, 6, 1)),
            "retail unsecured",
        ),
        rollback=RollbackPlan(
            trigger="precision drop 3 days",
            owner="EWS on-call",
            rehearsed_on=now - timedelta(days=20),
        ),
        ab_test=AbTestFeasibility.RAN,
        submitted_by="ews-squad-lead",
    )
    corrected = evaluate_promotion(fixed, now=now, via_ci=True)
    print(f"\n  after fixing all three: allowed = {corrected.allowed}")


def demo_challenger() -> None:
    """§2/§4 — why two numbers and a subtraction is not a lift."""
    _heading(3, "The champion/challenger comparison contract", "challenger")

    window = EvaluationWindow(
        datetime(2026, 1, 1), datetime(2026, 1, 1), datetime(2026, 6, 1)
    )
    later = EvaluationWindow(
        datetime(2026, 1, 1), datetime(2026, 3, 1), datetime(2026, 9, 1)
    )

    champion = ChallengerEntry("p3-gbm", "c_index", 0.71, window, "retail 2024", None, True)

    print("\n  champion: p3-gbm, c_index 0.7100 on 2026-01-01..2026-06-01")
    print("  challenger: deepsurv, c_index 0.7400 — a clear +0.03")
    print("  ...but measured on a LATER window (2026-03-01..2026-09-01).")

    try:
        assess(champion, ChallengerEntry("deepsurv", "c_index", 0.74, later, "retail 2024", None, True))
    except ComparisonError as error:
        _refusal(error)

    print("\n  Same window, but the challenger has had no explainability review:")
    verdict = assess(
        champion,
        ChallengerEntry("et-rnn", "c_index", 0.95, window, "retail 2024", None, False),
    )
    print(f"\n  lift          : {verdict.lift.lift:+.4f}  (large)")
    print(f"  may proceed   : {verdict.may_proceed}")
    for reason in verdict.blocking:
        print(f"    · {reason}")


def demo_uplift(randomized: bool) -> None:
    """WS-6.4 — the identifiability guard, both ways."""
    _heading(4, "Uplift: identifiable and unidentifiable", "uplift")

    # Half treated. Among the treated, the first half respond to the action;
    # controls cure at a lower base rate. Constructed so a targeting rule that
    # finds the responders is visibly better than random, which is the property
    # a Qini coefficient exists to express.
    records = []
    for i in range(200):
        treated = i % 2 == 0
        if treated:
            cured = 1.0 if i < 100 else 0.0  # responders concentrated
        else:
            cured = 1.0 if i % 10 == 1 else 0.0  # 20% base cure rate
        records.append(
            ActionRecord(f"acct{i}", treated, cured, {"balance": float(i % 7)})
        )

    if randomized:
        log = ActionLog(records, Assignment.RANDOMIZED, asserted_by="collections-ops")
        print("\n  log: 200 accounts, treatment assigned by RANDOMISED holdout")
        print("       (asserted by collections-ops — no code can verify this)")
        estimate = estimate_uplift(log)
        print(f"\n  treated cure rate : {estimate.treated_rate:.4f}  (n={estimate.treated_n})")
        print(f"  control cure rate : {estimate.control_rate:.4f}  (n={estimate.control_n})")
        print(f"  causal effect tau : {estimate.effect:+.4f}")
        print(f"\n  balance: {estimate.balance.summary()}")
        print(f"  proves randomization: {estimate.balance.proves_randomization}"
              "   <- always False, by design")

        # A targeting rule that ranks the responsive segment first, against a
        # flat rule that ranks nobody. The absolute value of a Qini coefficient
        # is scale-dependent and means little alone; the comparison is the
        # quantity WS-6.4's gate is stated on, so both are printed.
        informed = {r.account_id: (1.0 if int(r.account_id[4:]) < 100 else 0.0) for r in records}
        flat = {r.account_id: 0.5 for r in records}
        informed_q = qini_coefficient(qini_curve(log, informed))
        flat_q = qini_coefficient(qini_curve(log, flat))
        print(f"\n  Qini, targeting the responsive segment: {informed_q:>12.6f}")
        print(f"  Qini, no targeting (flat scores)      : {flat_q:>12.6f}")
        print(f"  the informed rule ranks higher        : {informed_q > flat_q}")
        print("    (the level is scale-dependent; the comparison is the gate — LH-802)")
    else:
        log = ActionLog(records, Assignment.OBSERVATIONAL)
        print("\n  log: the SAME 200 accounts, same outcomes — but treatment was")
        print("       assigned by officer judgement rather than randomised.")
        try:
            estimate_uplift(log)
        except UpliftError as error:
            _refusal(error)
        print("\n  This is not a missing-data problem. The rows are identical.")
        print("  What is missing is randomization, and no number of extra rows")
        print("  supplies it — the interval would narrow around the wrong value.")


def demo_offpolicy(bad_log: bool) -> None:
    """WS-6.5 — doubly-robust estimation, and positivity as a refusal."""
    _heading(5, "Doubly-robust off-policy evaluation", "offpolicy")

    def target(_context: str) -> str:
        return "A"

    def reward_model(_context: str, action: str) -> float:
        return 0.5 if action == "A" else 0.2

    if bad_log:
        log = [LoggedDecision(f"c{i}", "B", 0.5, 0.0) for i in range(200)]
        log[0] = LoggedDecision("c0", "A", 0.5, 1.0)
        print("\n  log: 200 logged decisions — but the target policy always picks A,")
        print("       and the logging policy took A exactly once.")
        try:
            evaluate_policy(log, target, reward_model)
        except OffPolicyError as error:
            _refusal(error)
        print("\n  200 rows, and the estimate would have described one of them.")
        return

    log = [
        LoggedDecision(f"c{i}", "A" if i % 2 == 0 else "B", 0.5, 1.0 if i % 4 == 0 else 0.0)
        for i in range(80)
    ]
    print("\n  log: 80 logged decisions at propensity 0.5, alternating A/B")
    print("       target policy: always offer A")
    print("       reward model : r(A)=0.5, r(B)=0.2")

    estimate = evaluate_policy(log, target, reward_model)
    low, high = estimate.confidence_interval()
    print(f"\n  DR value estimate : {estimate.value:.6f}")
    print(f"  logged policy value: {estimate.logged_value:.6f}")
    print(f"  lift               : {estimate.lift:+.6f}")
    print(f"  standard error     : {estimate.standard_error:.6f}")
    print(f"  95% interval       : [{low:.6f}, {high:.6f}]")
    print(f"\n  rows n             : {estimate.n}")
    print(f"  effective sample   : {estimate.positivity.effective_sample_size:.1f}"
          "   <- the honest denominator")
    print(f"  passes sign test   : {estimate.positive}   (LH-804: how positive is unratified)")


def demo_cadence() -> None:
    """WS-6.7 — the rhythm, and the two states a table cannot express."""
    _heading(6, "The governance cadence", "cadence")

    print(f"\n  {len(CADENCE)} activities transcribed from the WS-6.7 table:")
    for frequency in Frequency:
        items = [a.name for a in CADENCE if a.frequency is frequency]
        print(f"    {frequency.value:<10} ({frequency.interval.days:>3}d): {', '.join(items)}")

    as_of = datetime(2026, 9, 2).date()
    never = overdue(CADENCE, {}, as_of=as_of, grace=timedelta(days=2))
    print(f"\n  {THIN}")
    print(f"  with no run history: {len(never)} items, all reported NEVER RUN")
    print("    (never-run is not 'infinitely overdue' — different cause, different fix)")

    last_run = {a.name: as_of - timedelta(days=400) for a in CADENCE}
    late = overdue(CADENCE, last_run, as_of=as_of, grace=timedelta(days=2))
    print(f"\n  with everything last run 400 days ago: {len(late)} overdue")
    for item in late[:4]:
        print(f"    · {item.activity.name}: {item.days_late}d late")
    print(f"    ... and {max(len(late) - 4, 0)} more")

    print(f"\n  runnable with no phase shipped : {len(runnable(CADENCE, []))}")
    print(f"  runnable with P0+P1 shipped    : {len(runnable(CADENCE, ['P0', 'P1']))}")
    print("    (not-yet-applicable is not overdue — else the report is a wall of red)")


def demo_absent() -> None:
    """What no demo can show, said plainly."""
    _heading(7, "What this demo cannot show", "(ADR-0016)")
    print("""
  Six challenger models are NOT fitted, so nothing here takes an applicant
  and returns a prediction. Each is absent for a stated reason:

    GraphSAGE / CARE-GNN  need >= 18 months of fraud-desk dispositions
                          (LH-810, blocked on the alert budget LH-206)
    Noiseprint            needs a labelled forged-document set (LH-812)
    DeepSurv              has no champion to be compared against (P6-F7)
    Sequence models       need transaction event streams (LH-813)
    Causal forests        need randomized holdouts (LH-811) — unidentifiable

  A demo that scored a customer would be fabricating exactly what Phase 6
  refused to fabricate, and a fabricated score is indistinguishable from a
  real one once it is in a screenshot.

  Everything printed above was computed by the real module on the inputs
  shown. Change an input and the output changes, because nothing here is
  a canned string.""")


SCENARIOS = {
    "graph": "Louvain community detection on an entity graph",
    "promotion": "The standing promotion criterion (§4)",
    "challenger": "The champion/challenger comparison contract",
    "uplift": "Uplift, identifiable and unidentifiable",
    "offpolicy": "Doubly-robust off-policy evaluation",
    "cadence": "The governance cadence",
    "absent": "What cannot be demonstrated, and why",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Interactive demonstration of the Phase 6 computations.",
        epilog="Every number printed is computed by the real module. No model is fitted.",
    )
    parser.add_argument(
        "scenario",
        nargs="?",
        default="all",
        choices=["all", *SCENARIOS],
        help="which scenario to run (default: all)",
    )
    parser.add_argument(
        "--group-size",
        type=int,
        default=3,
        help="applicants per cluster in the graph scenario (default: 3)",
    )
    parser.add_argument(
        "--observational",
        action="store_true",
        help="uplift scenario: use an unrandomized log, which is refused",
    )
    parser.add_argument(
        "--broken-log",
        action="store_true",
        help="offpolicy scenario: use a log that violates positivity",
    )
    args = parser.parse_args(argv)

    if args.group_size < 2:
        parser.error("--group-size must be at least 2 to form a community")

    print(RULE)
    print(" Phase 6 — learning loops: a demonstration of the computations")
    print(" No model is fitted here. Every number below is computed on the")
    print(" inputs shown, by the module named in each heading.")
    print(RULE)

    run = SCENARIOS if args.scenario == "all" else {args.scenario: SCENARIOS[args.scenario]}
    if "graph" in run:
        demo_graph(args.group_size)
    if "promotion" in run:
        demo_promotion()
    if "challenger" in run:
        demo_challenger()
    if "uplift" in run:
        demo_uplift(randomized=not args.observational)
    if "offpolicy" in run:
        demo_offpolicy(bad_log=args.broken_log)
    if "cadence" in run:
        demo_cadence()
    if "absent" in run:
        demo_absent()

    print(f"\n{RULE}")
    print(" Nothing computed here is a Phase 6 gate number. `make gate6` reads")
    print(" the code, not this module.")
    print(RULE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

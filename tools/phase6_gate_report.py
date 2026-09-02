#!/usr/bin/env python3
"""Assemble the Phase 6 gate evidence pack.

Master §3.1: each phase ends with a Gate Review presenting an evidence pack.
**Phase 6 does not end**, which makes this pack a different object from the five
before it.

Phase 6's card says "steady-state operating rhythm, not a fixed project" and its
§4 criterion is *standing* — it applies to every promotion, forever, rather than
once at a review. So this pack reports **readiness to learn**, not learning
having happened, and it says so in its own first paragraph because a reader
skimming for numbers will find none and should know that is the accurate state.

The pack's specific risk is the opposite of Phase 5's. Phase 5 risked a
structural guarantee being read as a measurement. Phase 6 risks a *protocol*
being read as a *result*: "the promotion gate is built and tested" is true and
says nothing about any model having been promoted. Every row below therefore
separates the rule from the evidence the rule would judge.

Per ADR-0003, ADR-0004 and ADR-0016, only Track B numbers are gate evidence.
There is no Track P for this phase; Elliptic was examined and not adopted
(LH-806), which is a decision rather than an unrun job.

Exit code 0 whether or not the gate passes — a report that failed CI when the
gate failed would create pressure to stop generating it.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
from datetime import UTC, datetime

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from lending_hub.learning.cadence import CADENCE, Frequency, runnable  # noqa: E402
from lending_hub.learning.graph import MIN_COMMUNITY_SIZE  # noqa: E402
from lending_hub.learning.offpolicy import (  # noqa: E402
    MIN_EFFECTIVE_SAMPLE,
    MIN_PROPENSITY,
)
from lending_hub.learning.uplift import MIN_ARM_SIZE  # noqa: E402

REPORTS = REPO / "reports"
MODEL_CARDS = REPO / "docs/phase6/model_cards"
TICKETS = REPO / "docs/phase6/blocking_tickets.md"

#: Phase 6 §4's standing criterion, decomposed. Not "exit criteria" — the phase
#: file deliberately states one standing rule rather than a list that is
#: satisfied once.
STANDING = [
    ("Measured lift on out-of-time data", "learning.promotion", "checked"),
    ("Model card", "mlops.promotion", "checked"),
    ("Independent validation", "mlops.promotion", "checked"),
    ("Rollback plan", "learning.promotion", "checked"),
    ("Online A/B where feasible", "learning.promotion", "checked"),
]

#: The six workstreams and the feed each names. The feed is the reason a
#: workstream is or is not buildable, so it travels with every row.
WORKSTREAMS = [
    (
        "WS-6.1",
        "Graph fraud — full Layer 3",
        "P1 entity graph + >= 18 months of fraud-desk dispositions",
        "partial",
        "Louvain runs on the real P1 graph today because community detection is "
        "unsupervised. GraphSAGE and CARE-GNN have no labels — LH-810, blocked "
        "on LH-206",
    ),
    (
        "WS-6.2",
        "Document tamper CNNs",
        "A labelled forged-document set [DATA]",
        "none",
        "No document store on any track and no investigation function to "
        "produce labels — LH-812. The precision floor is LH-808",
    ),
    (
        "WS-6.3",
        "Survival & sequence challengers",
        "P3 hazard benchmark + transaction streams",
        "none",
        "The survival benchmark **exists** on Track P, which makes DeepSurv the "
        "closest thing here to buildable. Deferred because its gate is "
        "comparative against a champion this bank runs. Sequence models have no "
        "event data at all — LH-813",
    ),
    (
        "WS-6.4",
        "Collections & action uplift",
        "P4 action-outcome logs + randomized holdouts",
        "guard only",
        "**Unidentifiable**, not merely unmeasured — LH-811. The Qini mechanics "
        "and the identifiability guard are built and tested",
    ),
    (
        "WS-6.5",
        "Off-policy improvement of offers",
        "P4 propensity logs",
        "estimator only",
        "The DR estimator is complete and pinned against a hand computation. "
        "P4's `BanditDecision` guarantees the schema; the log has no rows "
        "(ADR-0014). Exploration cell is LH-503",
    ),
    (
        "WS-6.6",
        "Scoring maturation",
        "Bureau-retro program, consented alternative data",
        "none",
        "Both blocked from Phase 1 — LH-207 (bureau retro) and the DPDP "
        "clearances alternative data needs",
    ),
    (
        "WS-6.7",
        "Steady-state governance rhythm",
        "None — it is a schedule",
        "done",
        "The table as data, with overdue detection. Tolerances are LH-807",
    ),
]


def _open_tickets() -> list[tuple[str, str]]:
    """Read the register rather than restating it, so the pack cannot drift."""
    if not TICKETS.exists():
        return []
    rows: list[tuple[str, str]] = []
    for line in TICKETS.read_text(encoding="utf-8").splitlines():
        match = re.match(r"\|\s*(LH-\d+)\s*\|\s*([^|]+)\|", line)
        if match:
            rows.append((match.group(1), match.group(2).strip()))
    return rows


def _model_cards() -> list[tuple[str, bool]]:
    if not MODEL_CARDS.exists():
        return []
    cards: list[tuple[str, bool]] = []
    for path in sorted(MODEL_CARDS.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        signed = "**Not assigned**" not in text and "never evaluated" not in text
        cards.append((path.name, signed))
    return cards


def _cadence_state() -> dict:
    """Computed from the module, so a dropped row cannot survive in the pack."""
    shipped: list[str] = []  # No phase has passed its gate review.
    return {
        "total": len(CADENCE),
        "by_frequency": {
            f.value: sum(1 for a in CADENCE if a.frequency is f) for f in Frequency
        },
        "runnable_now": len(runnable(CADENCE, shipped)),
        "conditional": [a.name for a in CADENCE if a.is_conditional],
    }


def build() -> list[str]:
    lines: list[str] = []
    add = lines.append
    cadence = _cadence_state()
    tickets = _open_tickets()
    cards = _model_cards()

    add("# Phase 6 — gate evidence pack")
    add("")
    add(f"Generated {datetime.now(UTC).isoformat()} by `tools/phase6_gate_report.py`.")
    add("")
    add("## Read this first")
    add("")
    add("**Phase 6 does not end.** Its card says \"steady-state operating rhythm,")
    add("not a fixed project\", and §4's criterion is *standing* — it applies to")
    add("every promotion, forever, rather than once at a review. So this pack")
    add("reports **readiness to learn**, not learning having happened.")
    add("")
    add("**No lift of any kind is measured here, and no challenger model is")
    add("fitted.** A reader skimming for numbers will find none. That is the")
    add("accurate summary of a phase whose every challenger feeds on a loop that")
    add("has never iterated.")
    add("")
    add("The specific misreading this pack guards against is the inverse of")
    add("Phase 5's. Phase 5 risked a structural guarantee being read as a")
    add("measurement; Phase 6 risks a **protocol being read as a result**. \"The")
    add("promotion gate is built and tested\" is true, and says nothing about any")
    add("model having been promoted.")
    add("")
    add("Per ADR-0003 and ADR-0004, **only Track B numbers are gate evidence.**")
    add("There is **no Track P**, and that is a decision: Elliptic was examined")
    add("and not adopted (LH-806), for the reasons in")
    add("[ADR-0016](../docs/adr/0016-phase6-learning-loops-track.md).")
    add("")

    add("## The standing criterion (Phase 6 §4)")
    add("")
    add("Five conditions. All five are **implemented and enforced**; none has")
    add("ever been *exercised on a real promotion*, because no model in this")
    add("repository has been promoted — every promotion path terminates at an")
    add("unratified `[POLICY]` value.")
    add("")
    add("| Condition | Enforced by | State |")
    add("|---|---|---|")
    for name, module, _ in STANDING:
        add(f"| {name} | `{module}` | **enforced**, never exercised |")
    add("")
    add("Two of the five are worth reading closely, because both are easy to")
    add("implement backwards:")
    add("")
    add("* **Out-of-time is checked, not asserted.** It is the condition a")
    add("  submitter most often violates while believing they satisfied it — a")
    add("  random split of a multi-year panel is out-of-sample and in-time, which")
    add("  is exactly the optimistic number P4-F11 describes. `EvaluationWindow`")
    add("  compares the dates.")
    add("* **The A/B sentence is about admissible evidence, not about running an")
    add("  A/B.** §4 makes offline lift inadmissible *as the sole evidence* where")
    add("  an A/B was feasible and skipped, so the gate asks \"was one available?\"")
    add("  rather than \"did you run one?\" — and `INFEASIBLE` requires a stated")
    add("  reason against a named submitter. See P6-F3.")
    add("")

    add("## Workstreams (Phase 6 §2)")
    add("")
    add("| WS | Name | Named feed | Built | Why |")
    add("|---|---|---|---|---|")
    for code, name, feed, built, why in WORKSTREAMS:
        add(f"| {code} | {name} | {feed} | **{built}** | {why} |")
    add("")

    add("## The distinction this phase adds: unidentifiable")
    add("")
    add("Phase 3 established that *not measured* and *not measurable* are")
    add("different gate states. WS-6.4 needs a third.")
    add("")
    add("Both earlier states are about missing **data** — given the right")
    add("dataset, the number appears. WS-6.4's uplift is missing")
    add("**randomization**, and no quantity of observational action logs supplies")
    add("it. A desk that called every borrower an officer judged likely to cure")
    add("produces a log where treatment and cure are confounded by that")
    add("judgement, and the difference computed on it is a *different quantity*,")
    add("biased toward flattering the action.")
    add("")
    add("The operational consequence inverts the instinct every other blocked")
    add("ticket trains: **more data makes a confounded estimate tighter, not")
    add("truer.** The interval narrows around the wrong number, converting a")
    add("visible uncertainty into an invisible bias. LH-811 is the only row in")
    add("any register in this repository with that property.")
    add("")
    add("So `uplift.estimate_uplift()` raises rather than returning a flagged")
    add("number, and `BalanceReport.proves_randomization` is always `False` — a")
    add("confounded log balances on the columns someone happened to record, while")
    add("the confounder (the officer's judgement) is recorded nowhere.")
    add("")

    add("## What is exact, and is therefore built and tested in full")
    add("")
    add("| Component | Status |")
    add("|---|---|")
    add(
        "| Standing criterion (`learning.promotion`) | **done** — five conditions, "
        "every failing reason returned at once, composed onto Phase 0's gate |"
    )
    add(
        "| Comparison contract (`learning.challenger`) | **done** — same metric, "
        "population, window and operating point, or no comparison. Each mismatch "
        "produces a *positive* lift when violated, so all four are refusals |"
    )
    add(
        f"| Doubly-robust OPE (`learning.offpolicy`) | **done** — Dudik et al., "
        f"pinned against an independent hand computation. Refuses below "
        f"propensity {MIN_PROPENSITY} or effective sample {MIN_EFFECTIVE_SAMPLE} |"
    )
    add(
        f"| Uplift guard and Qini (`learning.uplift`) | **done** — curve and "
        f"coefficient exact; arms below {MIN_ARM_SIZE} refused; no estimate from "
        "an unrandomized log |"
    )
    add(
        f"| Louvain (`learning.graph`) | **done** — runs on the real P1 entity "
        f"graph; deterministic node order; communities below {MIN_COMMUNITY_SIZE} "
        "unscored |"
    )
    add(
        f"| Governance cadence (`learning.cadence`) | **done** — "
        f"{cadence['total']} activities across "
        f"{len(cadence['by_frequency'])} cadences, with overdue detection |"
    )
    add("")

    add("## The cadence, and why nothing is overdue")
    add("")
    add(f"{cadence['total']} activities are transcribed from the WS-6.7 table: ")
    add(
        ", ".join(
            f"{count} {freq}" for freq, count in cadence["by_frequency"].items()
        )
        + "."
    )
    add("")
    add(f"**{cadence['runnable_now']} are runnable today.** Every activity's")
    add("owning phase is pre-gate, so none is late — it is *not yet applicable*,")
    add("which is a different state and is reported as one. Collapsing the two")
    add("would make this section a wall of red, which is Phase 3's")
    add("not-measured / not-measurable error appearing in a monitoring dashboard.")
    add("")
    add(
        f"One activity carries the phase file's own qualifier verbatim "
        f"(*{cadence['conditional'][0]}* — \"as data warrants\") rather than being "
        "resolved into a hard interval, because resolving it would invent a rule."
    )
    add("")

    add("## What is NOT built, and the reason for each")
    add("")
    add("Six challenger models are absent. Each is deferred for a stated reason")
    add("rather than for absence of effort, and each becomes buildable the moment")
    add("its named feed exists.")
    add("")
    add("| Model | Reference | Blocked by |")
    add("|---|---|---|")
    add("| GraphSAGE | Hamilton et al., arXiv:1706.02216 | LH-810 (dispositions) |")
    add("| CARE-GNN | Dou et al., arXiv:2008.08692 | LH-810; and camouflage is a behaviour of an adversary responding to a deployed detector |")
    add("| Noiseprint | Cozzolino & Verdoliva, arXiv:1808.08396 | LH-812 (labelled forgeries) |")
    add("| DeepSurv | Katzman et al., arXiv:1606.00931 | No champion to beat — P6-F7 |")
    add("| E.T.-RNN class | Babaev et al., arXiv:1911.02496 | LH-813 (event streams) |")
    add("| Causal forest / meta-learners | Wager & Athey; Kunzel et al. | LH-811 (holdouts) — unidentifiable |")
    add("")

    add("## Model cards")
    add("")
    if not cards:
        add("None. **This is the correct state**: Master §2 rule 5 requires a card")
        add("per *model*, and Phase 6 fits none. The two components that produce")
        add("numbers — the DR estimator and Louvain — are algorithms rather than")
        add("fitted models, and a card for an unfitted challenger would document")
        add("nothing.")
    else:
        add("| Card | Signed |")
        add("|---|---|")
        for name, signed in cards:
            add(f"| {name} | {'yes' if signed else '**no**'} |")
    add("")

    add("## Open tickets")
    add("")
    add(f"**{len(tickets)} open**, in `docs/phase6/blocking_tickets.md`. The")
    add("register is shaped differently from every earlier phase's, and the shape")
    add("is the finding: rows split into **decisions** a named owner can close")
    add("tomorrow, and **accruals** that only an operating bank closes. No")
    add("escalation closes an accrual, and reporting the two identically makes a")
    add("scheduling problem look like a policy one.")
    add("")
    if tickets:
        add("| Ticket | Owner |")
        add("|---|---|")
        for ticket, owner in tickets:
            add(f"| {ticket} | {owner} |")
    add("")

    add("## Gate outcome")
    add("")
    add("**Not applicable — and that is not a euphemism for fail.**")
    add("")
    add("Phase 6 has no exit criteria to pass. §4 states a standing rule that")
    add("applies to every future promotion, and the honest report against it is:")
    add("the rule is implemented, enforced and tested, and it has judged nothing,")
    add("because nothing has been submitted to it.")
    add("")
    add("What a reviewer should take from this pack:")
    add("")
    add("1. The promotion protocol exists **before** the first promotion request,")
    add("   which is the point of building it now — a rule written under pressure")
    add("   by whoever ships the first challenger is a rule shaped by that")
    add("   challenger.")
    add("2. Two guards are track-independent and hold unchanged in a real")
    add("   deployment: the identifiability refusal and the positivity refusal.")
    add("   Both are statements about what a log can support.")
    add("3. Everything else waits on a feedback loop, and four of those loops")
    add("   trace back to a `[POLICY]` value that kept a desk from being staffed.")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(REPORTS / "phase6_gate.md"))
    args = parser.parse_args(argv)

    out = pathlib.Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(build()) + "\n", encoding="utf-8")

    print(f"phase 6 gate pack -> {out}")
    print(f"open tickets: {len(_open_tickets())}")
    print("track P run: none by decision (ADR-0016)")
    print("gate outcome: not applicable — Phase 6's criterion is standing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

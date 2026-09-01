#!/usr/bin/env python3
"""Assemble the Phase 1 gate evidence pack.

Master §3.1: each phase ends with a Gate Review presenting an evidence pack.
Phase 1 §7 states four exit criteria; this collects what exists against each and
states plainly what does not. An evidence pack that omits a criterion silently is
worse than one that says "not measured", because an omission reads as an
oversight while a stated blocker reads as a blocker.

Per ADR-0003 and ADR-0004, **only Track B numbers are gate evidence.** The Track P
run proves the code paths on real data; it is not evidence about this bank's
portfolio, and every row it contributes is labelled accordingly.

Exit code 0 whether or not the gate passes — a report that fails CI when the gate
fails would create pressure to stop generating it.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from datetime import UTC, datetime

REPO = pathlib.Path(__file__).resolve().parents[1]
REPORTS = REPO / "reports"
TRACK_P_RUN = "trackP_p1_home_credit.json"
MODEL_CARDS = REPO / "docs/phase1/model_cards"
TICKETS = REPO / "docs/phase1/blocking_tickets.md"

#: Phase 1 §7, verbatim, with the workstream each belongs to.
CRITERIA = [
    ("Champion ≥ rebuilt legacy on out-of-time Gini and Brier", "WS-1.1 Step 9"),
    ("Challenger ≥ +3 Gini over rebuilt legacy, out-of-time", "WS-1.1 Step 9"),
    ("Brier ≤ legacy", "WS-1.1 Step 9"),
    ("Swap set shows no adverse-segment concentration", "WS-1.1 Step 9"),
    ("Fraud precision at operating alert budget ≥ incumbent rules", "WS-1.2 Step 3"),
    ("Step-up friction on eventual-good customers < 3%", "WS-1.2 Step 6"),
    ("Decision-log spot audit: 100 re-scored decisions identical", "Master §3.3"),
    ("Model cards + independent validation signed for every shipped model", "Master §2 rule 5"),
]


def _load(name: str) -> dict | None:
    path = REPORTS / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"status": "unreadable"}


def _open_tickets() -> list[tuple[str, str]]:
    if not TICKETS.exists():
        return []
    rows = re.findall(
        r"^\|\s*([A-Z]{2,}-\d+)\s*\|\s*([^|]+)\|[^|]*\|[^|]*\|\s*([^|]+)\|",
        TICKETS.read_text(encoding="utf-8"),
        re.M,
    )
    return [(t, owner.strip()) for t, owner, status in rows if "open" in status.lower()]


def _model_cards() -> list[tuple[str, bool]]:
    """Each card, and whether it carries a signature.

    A card exists / a card is signed are different states, and the second is what
    Master §2 rule 5 requires. Detecting the difference mechanically is cheap and
    stops "the card is written" being reported as "the card is done".
    """
    if not MODEL_CARDS.is_dir():
        return []
    out = []
    for path in sorted(MODEL_CARDS.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        signed = "| Independent validator |" in text and not re.search(
            r"\|\s*Independent validator\s*\|\s*—?\s*\|", text
        )
        out.append((path.name, signed))
    return out


def build(run: dict | None) -> list[str]:
    now = datetime.now(UTC).isoformat()
    lines = [
        "# Phase 1 — gate evidence pack",
        "",
        f"Generated {now} by `tools/phase1_gate_report.py`.",
        "",
        "Per ADR-0003 and ADR-0004, **only Track B numbers are gate evidence.**",
        "Track P results below prove the code paths against real applications and",
        "say nothing about this bank's portfolio.",
        "",
        "## Exit criteria (Phase 1 §7)",
        "",
        "| # | Criterion | Workstream | Track | Measured | State |",
        "|---|---|---|---|---|---|",
    ]

    measured: dict[str, tuple[str, str, str]] = {}
    if run:
        champion = run.get("validation", {}).get("champion", {})
        champion_uplift = champion.get("exit_criteria", {}).get(
            "champion_gini_uplift", {}
        )
        measured[CRITERIA[0][0]] = (
            "P",
            "—"
            if champion_uplift.get("measured") is None
            else f"{champion_uplift['measured']:+.2f} pts",
            "not evaluable — " + str(champion_uplift.get("note", "no comparator")),
        )

        challenger = run.get("validation", {}).get("challenger", {})
        criteria = challenger.get("exit_criteria", {})

        uplift = criteria.get("challenger_gini_uplift", {})
        measured[CRITERIA[1][0]] = (
            "P",
            "—" if uplift.get("measured") is None else f"{uplift['measured']:+.2f} pts",
            "not evaluable — " + str(uplift.get("note", "")),
        )
        brier = criteria.get("brier_no_worse_than_legacy", {})
        measured[CRITERIA[2][0]] = (
            "P",
            f"{brier.get('measured', float('nan')):.5f} vs {brier.get('legacy'):.5f}"
            if brier.get("legacy") is not None
            else "—",
            "fail (Track P)" if brier.get("met") is False else "pass (Track P)",
        )
        swap = criteria.get("swap_set_no_adverse_concentration", {})
        worst = ""
        if isinstance(swap.get("measured"), dict) and swap["measured"]:
            segment, value = next(iter(swap["measured"].items()))
            worst = f"worst segment {segment} at {value:.2f}x"
        measured[CRITERIA[3][0]] = (
            "P", worst or "—", "not evaluable — no bar (LH-205)",
        )

    for index, (label, workstream) in enumerate(CRITERIA, start=1):
        track, value, state = measured.get(label, ("—", "—", "**not measured**"))
        lines.append(f"| {index} | {label} | {workstream} | {track} | {value} | {state} |")

    lines += [
        "",
        f"Criteria with **Track B evidence: 0 of {len(CRITERIA)}.** Phase 1 is not "
        "exitable, and the",
        "reason is upstream: Phase 0 has not started (LH-120, written data-sharing",
        "approvals) so no bank data exists to measure against.",
        "",
        "## Fraud criteria",
        "",
        "Criteria 4 and 5 are not merely unmeasured — they are **not evaluable at all**.",
        "Master Appendix A defines confirmed fraud as a disposition code in the approved",
        "taxonomy; the taxonomy is `[POLICY: Fraud Head]` and does not exist (LH-101).",
        "Until it does, any count of confirmed frauds is a count of whichever codes",
        "someone chose, and both the alert-precision criterion and the Phase 1 §4",
        "WS-1.2 Step 3 scope test rest on that count. See",
        "[Phase_1_FINDINGS.md](../Lending_Hub_Phase_Docs/Phase_1_FINDINGS.md) finding P1-F5.",
        "",
        "## Decision-log spot audit",
        "",
        "`lending_hub.decisionlog.spot_audit` is built and tested at zero score",
        "tolerance (Master §3.3). It needs logged production decisions, and the",
        "orchestrator has decided nothing: every band edge in `config/policy_bands.yaml`",
        "is a registered placeholder (LH-204), so every scored application is referred.",
        "",
        "## Model cards (Master §2 rule 5)",
        "",
    ]

    cards = _model_cards()
    if not cards:
        lines.append("No model cards found under `docs/phase1/model_cards/`.")
    else:
        lines += ["| Card | Signed |", "|---|---|"]
        for name, signed in cards:
            lines.append(f"| `{name}` | {'yes' if signed else '**no**'} |")
        lines += [
            "",
            "An unsigned card is not a completed card. Master §3.1 requires an",
            "independent validator who is not the developer; none exists on Track P,",
            "and `lending_hub.mlops.promotion` refuses the transition on that basis.",
        ]

    tickets = _open_tickets()
    lines += ["", "## Open Phase 1 blockers", ""]
    if not tickets:
        lines.append("None registered.")
    else:
        lines += ["| Ticket | Owner |", "|---|---|"]
        lines += [f"| {ticket} | {owner} |" for ticket, owner in tickets]
        lines += [
            "",
            "Phase 0 tickets that also block Phase 1: **LH-101** (fraud taxonomy),",
            "**LH-103** (default code sets), **LH-120** (data-sharing approvals).",
            "Full register: [docs/phase1/blocking_tickets.md](../docs/phase1/blocking_tickets.md).",
        ]

    if run:
        lines += [
            "",
            "## Track P run (not gate evidence)",
            "",
            f"Dataset `{run['run']['dataset']}`, seed {run['run']['seed']}, "
            f"{run['run']['seconds']}s.",
            "",
            "| Model | Test Gini | Brier | ECE | Score PSI |",
            "|---|---|---|---|---|",
        ]
        for name, key in (("Champion (WOE scorecard)", "champion"),
                          ("Challenger (monotone GBM)", "challenger")):
            report = run["validation"][key]
            lines.append(
                f"| {name} | {report['test']['gini_points']:.2f} | "
                f"{report['brier']:.5f} | {report['ece']:.5f} | "
                f"{report['score_psi']:.4f} |"
            )
        lines += [
            "",
            "Reproduce with `make trackp-p1`. Every limitation is listed in the run",
            "report's `limitations` block — the split is not out of time, the label is",
            "the vendor's, and the challenger carries no ratified monotone constraints.",
        ]

    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="reports/phase1_gate.md")
    args = parser.parse_args(argv)

    run = _load(TRACK_P_RUN)
    if run is None:
        print(
            f"note: {TRACK_P_RUN} not found — run `make trackp-p1` for the Track P "
            "section (needs datasets/, see docs/phase0/DATA_SOURCING.md)",
            file=sys.stderr,
        )

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(build(run)) + "\n", encoding="utf-8")

    print(f"Phase 1 gate evidence pack written to {out}")
    print(f"  0 of {len(CRITERIA)} exit criteria have Track B evidence")
    print("  Phase 1 is not exitable — see docs/phase1/STATUS.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Assemble the Phase 4 gate evidence pack.

Master §3.1: each phase ends with a Gate Review presenting an evidence pack.
Phase 4 §8 states five exit criteria.

**Phase 4 is the first phase to use all three columns**, and that is the pack's
main job to communicate. Phase 1 and Phase 3 reported Track P numbers against
blockers. Phase 2 reported nothing measurable at all. Phase 4 splits down the
middle: its detection layer has real Track P evidence on a mortgage panel, its
action layer has none and can have none, and one criterion is **provable on
Track A** because it is a structural property rather than a measurement.

Per ADR-0003, ADR-0004 and ADR-0014, only Track B numbers are gate evidence.

Exit code 0 whether or not the gate passes — a report that failed CI when the
gate failed would create pressure to stop generating it.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from datetime import UTC, datetime

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from lending_hub.definitions.provenance import TBD_PATTERN  # noqa: E402

REPORTS = REPO / "reports"
TRACK_P_RUN = "trackP_p4_fannie_mae.json"
MODEL_CARDS = REPO / "docs/phase4/model_cards"
TICKETS = REPO / "docs/phase4/blocking_tickets.md"

#: Phase 4 §8, verbatim, with the workstream each belongs to.
CRITERIA = [
    ("EWS backtest + silent-run meet targets", "WS-4.A Step 6"),
    ("Alert SLA compliance >= 90% in first live month", "WS-4.A Step 5"),
    (
        "Recommendation A/B (bandit vs static) shows take-up lift with no "
        "vintage-risk deterioration at 3 months",
        "WS-4.B Step 4",
    ),
    ("Suitability audit clean", "WS-4.B Step 5"),
    ("Propensity logging completeness = 100%", "WS-4.B Step 4"),
]

#: Criteria no data reachable from here can produce, with why.
NOT_MEASURABLE = {
    "Alert SLA compliance >= 90% in first live month": (
        "there is no live month, no case-management system (Phase 4 §3 entry "
        "criterion, LH-120), and the SLAs themselves are unratified (LH-502)"
    ),
    "Recommendation A/B (bandit vs static) shows take-up lift with no "
    "vintage-risk deterioration at 3 months": (
        "needs live traffic through two policies and a 3-month observation "
        "window. The bandit is built and refuses to learn, because its reward "
        "is undefined (LH-509) and there are no offer logs (LH-510)"
    ),
    "Suitability audit clean": (
        "an audit reviews recommendations actually made; none are (LH-510). The "
        "two checks §5 Step 5 names are implemented and the audit refuses to "
        "sign itself off — §5 Step 5 specifies a *human* monthly audit, and an "
        "automated control clearing its own subject would make this criterion a "
        "claim the code makes about itself"
    ),
}


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
    if not MODEL_CARDS.exists():
        return []
    out = []
    for path in sorted(MODEL_CARDS.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        signed = bool(
            re.search(r"^\|\s*(Signed|Signature|Validator)\b", text, re.M | re.I)
        ) and not TBD_PATTERN.search(text)
        out.append((path.name, signed))
    return out


def _best_band(run: dict | None) -> tuple[str, dict] | None:
    """The sweep band with the highest capture rate, if the run produced one."""
    if not run:
        return None
    sweep = run.get("capture_sweep") or {}
    bands = {
        name: payload
        for name, payload in sweep.items()
        if isinstance(payload, dict) and payload.get("capture_rate") is not None
    }
    if not bands:
        return None
    return max(bands.items(), key=lambda kv: kv[1]["capture_rate"])


def _criterion_state(name: str, run: dict | None) -> tuple[str, str, str]:
    """``(track, measured, state)`` for one criterion."""
    if name in NOT_MEASURABLE:
        return "—", "—", f"**not measurable** — {NOT_MEASURABLE[name]}"

    if name.startswith("Propensity logging"):
        return (
            "A",
            "100% by construction",
            "**provable on Track A** — `BanditDecision` cannot be constructed "
            "without a propensity, so completeness is a property of the type "
            "rather than a measurement. The only Phase 4 criterion this "
            "repository fully satisfies; still not gate evidence, because no "
            "decision has been made against a customer",
        )

    if name.startswith("EWS backtest"):
        if run is None:
            return "—", "—", "**not measured** — no Track P run present"
        best = _best_band(run)
        if best is None:
            sweep = run.get("capture_sweep") or {}
            reason = sweep.get("reason", "the run produced no rankable snapshots")
            return "—", "—", f"**not measured** — {reason}"
        band_name, payload = best
        measured = (
            f"capture {payload['capture_rate']:.3f} at {band_name}, "
            f"median lead {payload['median_lead_days']}d (Track P)"
        )
        return (
            "P",
            measured,
            "**split**: capture and lead time are measured out of time on a real "
            "mortgage panel; **tier-Red precision is not measurable**, because it "
            "needs collections dispositions (LH-510) and the default outcome is "
            "not a substitute — it would score an alert that found distress the "
            "bank cured as a false positive. Not gate evidence: US conforming "
            "mortgages, not this bank's book (ADR-0012, ADR-0014)",
        )

    return "—", "—", "**not measured**"


def build(run: dict | None) -> list[str]:
    lines: list[str] = []
    add = lines.append

    add("# Phase 4 — gate evidence pack")
    add("")
    add(f"Generated {datetime.now(UTC).isoformat()} by `tools/phase4_gate_report.py`.")
    add("")
    add("**Phase 4 is the first phase to use all three columns.** Its detection")
    add("layer has real Track P evidence; its action layer has none and can have")
    add("none, because evaluating an action requires having taken one; and one")
    add("criterion is provable on Track A because it is a structural property of a")
    add("type rather than a measurement. See")
    add("[ADR-0014](../docs/adr/0014-phase4-action-systems-track.md).")
    add("")
    add("Per ADR-0003 and ADR-0004, **only Track B numbers are gate evidence.**")
    add("")

    add("## Exit criteria (Phase 4 §8)")
    add("")
    add("| # | Criterion | Workstream | Track | Measured | State |")
    add("|---|---|---|---|---|---|")
    for index, (name, workstream) in enumerate(CRITERIA, start=1):
        track, measured, state = _criterion_state(name, run)
        add(f"| {index} | {name} | {workstream} | {track} | {measured} | {state} |")
    add("")
    add("**Track B evidence: 0 of 5.**")
    add("")

    add("## Nothing here is simulated")
    add("")
    add("Phase 4 is unusually easy to fake convincingly. A simulated collections")
    add("desk with a plausible disposition rate produces a signal catalogue with")
    add("precisions, a passing ship gate, a populated alert stream and a bandit")
    add("that visibly learns — and every number would be a property of the")
    add("simulator.")
    add("")
    add("It would also be worse than Phase 3's in-sample error (P3-F14), because")
    add("the simulator would be authored by the same person as the detector: a")
    add("signal would score well exactly to the extent that the simulator shared")
    add("the detector's theory of default.")
    add("")
    add("So no disposition, offer, take-up or reward is generated anywhere in this")
    add("phase. The signal catalogue reports every signal as unshippable with its")
    add("reason, which is a true statement a Track B team can act on.")
    add("")

    if run:
        add("## What the Track P run established")
        add("")
        sweep = run.get("capture_sweep") or {}
        bands = {
            name: payload
            for name, payload in sweep.items()
            if isinstance(payload, dict) and payload.get("capture_rate") is not None
        }
        if bands:
            add("The alert percentile is unratified (LH-501), so the run sweeps bands")
            add("rather than choosing one. This table is what a Collections Head needs")
            add("to set the budget: it maps alert volume onto capture rate on a real")
            add("book.")
            add("")
            add("| Band | Alerts | Accounts | Capture | Median lead | Meets 55% target |")
            add("|---|---|---|---|---|---|")
            for name in sorted(bands):
                p = bands[name]
                add(
                    f"| {name} | {p['alerts_raised']:,} | "
                    f"{p['accounts_alerted']:,} | {p['capture_rate']:.3f} | "
                    f"{p['median_lead_days']}d | "
                    f"{'yes' if p['meets_target'] else 'no'} |"
                )
            add("")
        panel = run.get("panel") or {}
        defaults = run.get("observed_defaults") or {}
        if panel:
            add(
                f"Panel: {panel.get('loans_sampled', 0):,} loans, "
                f"{panel.get('account_months', 0):,} account-months."
            )
            add("")
        if isinstance(defaults, dict) and defaults:
            add(
                f"**Denominator:** {defaults.get('reachable', 0):,} reachable "
                f"defaults of {defaults.get('in_panel', 0):,} in the panel. The "
                f"other {defaults.get('before_first_alertable_snapshot', 0):,} "
                f"fall before the first held-out snapshot "
                f"({defaults.get('first_alertable_snapshot', '—')}) and could "
                "not have been alerted on by construction, so counting them "
                "would measure the train/test split rather than the detector. "
                "The 2007Q1 vintage front-loads its defaults into the 2008-11 "
                "credit event, which sits entirely inside the training window — "
                "see finding P4-F11."
            )
            add("")
    else:
        add("## Track P run")
        add("")
        add("Not present. `make trackp-p4` needs `datasets/`, which is gitignored —")
        add("see [DATA_SOURCING](../docs/phase0/DATA_SOURCING.md).")
        add("")

    add("## Model cards (Master §2 rule 5)")
    add("")
    cards = _model_cards()
    if not cards:
        add("No model cards.")
    else:
        add("| Card | Signed |")
        add("|---|---|")
        for name, signed in cards:
            add(f"| {name} | {'yes' if signed else '**no**'} |")
        add("")
        add("None signed: Master §3.1 requires an independent validator who is not")
        add("the developer, and there is none.")
    add("")

    add("## Open blocking tickets")
    add("")
    tickets = _open_tickets()
    if not tickets:
        add("None registered.")
    else:
        add("| Ticket | Owner |")
        add("|---|---|")
        for ticket, owner in tickets:
            add(f"| {ticket} | {owner} |")
        add("")
        add(f"{len(tickets)} open. Six are Phase 4 §9 do-not-invent values.")
        add("**Seven were found by building** — LH-507 (a per-officer cap is not a")
        add("portfolio budget), LH-508 (the two-key rule quantifies none of its")
        add("three conditions), LH-509 (the bandit reward blend), LH-511 (absolute")
        add("or relative velocity), LH-512 (BOCPD confidence depends on the")
        add("preceding regime), LH-513 (ALM table staleness), and LH-510 (the")
        add("disposition and offer logs, listed as an entry criterion but produced")
        add("by no phase).")
        add("")
        add("**LH-509 is the one to read.** Phase 4 §5 Step 4 defines the bandit's")
        add("reward as \"take-up blended with a seasoning risk-adjusted value")
        add("proxy\" and gives neither the weight nor the horizon. A bandit rewarded")
        add("on take-up alone learns to offer the largest permitted loan to whoever")
        add("is likeliest to accept it — a mis-selling engine whose own reward")
        add("curve looks like success.")
    add("")

    add("## Gate outcome")
    add("")
    add("**Fail.** No criterion has Track B evidence and three cannot have any")
    add("without a deployed case-management system and live traffic.")
    add("")
    add("What a Track B team receives: a detection layer with measured lead times")
    add("on real data, a complete rules-and-pricing layer awaiting its config, and")
    add("a bandit that will refuse to make a decision it cannot log a propensity")
    add("for or to learn from a reward nobody has defined.")

    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 4 gate evidence pack")
    parser.add_argument("--output", default="reports/phase4_gate.md")
    args = parser.parse_args(argv)

    run = _load(TRACK_P_RUN)
    output = pathlib.Path(args.output)
    if not output.is_absolute():
        output = REPO / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(build(run)) + "\n", encoding="utf-8")

    print(f"phase 4 gate pack -> {output}")
    print(f"track P run: {'present' if run else 'absent'}")
    print(f"open tickets: {len(_open_tickets())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

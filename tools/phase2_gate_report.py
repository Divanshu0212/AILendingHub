#!/usr/bin/env python3
"""Assemble the Phase 2 gate evidence pack.

Master §3.1: each phase ends with a Gate Review presenting an evidence pack.
Phase 2 §7 states six exit criteria, and this collects what exists against each.

**All six are not measurable**, which is a first for this programme and is the
main thing the pack has to communicate. Phase 3 reported two of six that way and
treated it as notable; Phase 2 reports every one. That is a fact about Phase 2's
position, not about its engineering: there is no imagery in this repository, no
agri portfolio with outcomes, and no ratified crop calendar, and none of the
three is approximable — a crop calendar for the wrong agro-zone is a different
calendar, not a noisy version of the right one (ADR-0013).

Phase 1 and Phase 3 each had a Track P run behind their numbers. Phase 2 has
none, so this pack quotes **no metrics at all**. That is deliberate: a gate pack
that fills its Measured column with numbers computed on fixtures teaches the
reader that the column contains evidence.

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

from lending_hub.definitions.provenance import TBD_PATTERN  # noqa: E402

MODEL_CARDS = REPO / "docs/phase2/model_cards"
TICKETS = REPO / "docs/phase2/blocking_tickets.md"
STATUS = REPO / "docs/phase2/STATUS.md"

#: Phase 2 §7, verbatim, with the workstream each belongs to and why no data
#: reachable from this repository can produce it.
CRITERIA: list[tuple[str, str, str]] = [
    (
        "Backtests (a) LQI quartiles order agri NPA monotonically, "
        "(b) >= +4 Gini from agri features, "
        "(c) non-sowing flag on >= 60% of season-linked defaults at >= 45 days",
        "WS-2.4",
        "all three need this bank's historical agri portfolio with outcomes and "
        "location granularity over >= 3 seasons (LH-406). No public dataset "
        "substitutes: the criteria are statements about this bank's agri book. "
        "(c) additionally needs the season-attribution rule (LH-412)",
    ),
    (
        "Crop classifier macro-F1 >= 0.85 on the 5 majority crops per zone, "
        "on held-out ground truth",
        "WS-2.2 Model B",
        "needs ground-truth crop labels from crop-cutting experiments and "
        "officer visits (LH-406) and the ratified per-zone class set that "
        "defines what 'the 5 majority crops' means (LH-404). The RF baseline, "
        "macro-F1 and the +5-point earn-it rule are built and unit-tested",
    ),
    (
        "Boundary IoU gate met (median >= 0.75 vs held-out GPS-walk polygons)",
        "WS-2.2 Model A",
        "needs the officer GPS-walk polygon set (LH-407), which is field work "
        "with a season's lead time and which no workstream in the programme "
        "plan schedules. The IoU metric, the gate and its distribution "
        "reporting are built and unit-tested",
    ),
    (
        "Underwriter adoption >= 70% of agri files opened in the evidence UI",
        "Phase 2 §5 step 1",
        "there is no rendering surface of any kind in this repository — the same "
        "gap Phase 3 recorded for its dashboards — and no agri files to open. "
        "Adoption telemetry without a UI measures nothing",
    ),
    (
        "Model cards + independent validation for Models A/B/C",
        "Master §2 rule 5, §3.1",
        "none of the three models exists (ADR-0013), so there is nothing to "
        "validate. Master §3.1 separately requires a validator who is not the "
        "developer, and there is none",
    ),
    (
        "Geographic disparate-impact memo filed",
        "WS-2.4 / SRS §11.3",
        "needs both the agri features on a real book (LH-406) and the ratified "
        "geographic comparison units and disparity bar (LH-410). The measurement "
        "code is built and refuses to reach a verdict without them",
    ),
]

#: Phase 2 §6 deliverables, and what exists for each. The distinction this
#: column carries is between "not built because it is blocked on data or policy"
#: and "not built because it is a Track B backend".
DELIVERABLES: list[tuple[str, str]] = [
    (
        "Ingestion DAGs + completeness monitors",
        "**monitors built** (`agri.ingest`); DAGs are Airflow, i.e. Track B "
        "(ADR-0002). The three source contracts were registered in Phase 0 "
        "(`config/sources/satellite.yaml`, `weather.yaml`, `soil_geo.yaml`)",
    ),
    (
        "Plot registry (PostGIS) + officer GPS-walk capture",
        "**registry logic built** (`agri.registry`, `agri.geometry`) against the "
        "`agri.ports.PlotStore` seam; PostGIS is Track B. The field app is not "
        "in this repository, and the walk set it would produce is LH-407",
    ),
    (
        "Index pipelines with SPI unit test green",
        "**built, and the mandated test is green** (`agri.drought`, "
        "`agri.indices`). Phase 2 §4 names one explicit unit test in the whole "
        "phase and this is it",
    ),
    (
        "Models A/B/C registered in MLflow with model cards",
        "**not built** (ADR-0013). Each model's *contract* is built — the IoU "
        "gate, the calibration and abstention rules, the P50/P25/P10 output — "
        "and each has a card recording that the model behind it does not exist",
    ),
    (
        "RF baseline + fallback yield regression (kept, documented)",
        "**both built** (`agri.crop`, `agri.yield_model`). Phase 2 §4 orders the "
        "fallback built first and kept forever; it is, and it satisfies the "
        "P50/P25/P10 contract without the GP",
    ),
    (
        "Feature aggregation package with policy sign-off record",
        "**built** (`agri.features`); no sign-off record, because the two income "
        "formulas cannot be evaluated without input costs (LH-401) and "
        "LandQualityIndex has no ratified combining function at all (LH-411)",
    ),
    (
        "Backtest report (a)/(b)/(c) with scripts",
        "**harness built** (`agri.backtest`), including the point-in-time proof "
        "against publication dates. No report: LH-406 supplies no denominator",
    ),
    (
        "Underwriter evidence UI live; adoption telemetry",
        "**not built** — no rendering surface in this repository",
    ),
    (
        "Geographic disparate-impact analysis",
        "**measurement built** (`agri.disparate`); it refuses a verdict without "
        "LH-410, and reports the land-quality gap beside the disparity because "
        "in this phase the agronomic signal and the disparity are one number",
    ),
]


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

    Same detector as the Phase 1 and Phase 3 packs: a card existing and a card
    being signed are different states, and an open placeholder anywhere in it
    disqualifies it. The placeholder syntax comes from ``definitions.provenance``
    rather than being restated, so a change to it cannot leave this behind.
    """
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


def build() -> list[str]:
    lines: list[str] = []
    add = lines.append

    add("# Phase 2 — gate evidence pack")
    add("")
    add(f"Generated {datetime.now(UTC).isoformat()} by `tools/phase2_gate_report.py`.")
    add("")
    add("**Phase 2 has no Track P.** Phase 1 and Phase 3 each had real public")
    add("data standing in for the bank's, so their numbers — never gate evidence —")
    add("were at least facts about real lending. Phase 2 has no imagery, no agri")
    add("portfolio and no ratified crop calendar, and none is approximable: a crop")
    add("calendar for the wrong agro-zone is a different calendar, not a noisy")
    add("version of the right one. See [ADR-0013](../docs/adr/0013-phase2-agri-track.md).")
    add("")
    add("This pack therefore quotes **no metrics**. A Measured column filled with")
    add("figures computed on fixtures would teach the reader that the column")
    add("contains evidence.")
    add("")

    add("## Exit criteria (Phase 2 §7)")
    add("")
    add("| # | Criterion | Workstream | Track | State |")
    add("|---|---|---|---|---|")
    for index, (name, workstream, reason) in enumerate(CRITERIA, start=1):
        add(f"| {index} | {name} | {workstream} | — | **not measurable** — {reason} |")
    add("")
    add("**Track B evidence: 0 of 6. Not measurable: 6 of 6.**")
    add("")

    add("## Why every criterion, and not just some")
    add("")
    add("Phase 3 reported two of six as not measurable and treated the distinction")
    add("as worth carrying through the pack. Phase 2 reports all six, and the")
    add("aggregate says something the individual rows do not: **this phase's gate")
    add("is not blocked on effort anywhere.** There is no task in this repository")
    add("whose completion moves any of the six.")
    add("")
    add("Three of the six are blocked on one thing — LH-406, the historical agri")
    add("portfolio — which is Phase 2 §3's own entry criterion. A phase whose entry")
    add("criteria are unmet cannot have exit criteria met, and stating that once at")
    add("the top is more useful than discovering it six rows down.")
    add("")

    add("## Deliverables (Phase 2 §6)")
    add("")
    add("The distinction this column carries: *blocked on data or policy* against")
    add("*is a Track B backend*. They call for different responses.")
    add("")
    add("| # | Deliverable | State |")
    add("|---|---|---|")
    for index, (name, state) in enumerate(DELIVERABLES, start=1):
        add(f"| {index} | {name} | {state} |")
    add("")

    add("## Model cards (Master §2 rule 5)")
    add("")
    cards = _model_cards()
    if not cards:
        add("No model cards. Phase 2's three models are not built (ADR-0013).")
    else:
        add("| Card | Signed |")
        add("|---|---|")
        for name, signed in cards:
            add(f"| {name} | {'yes' if signed else '**no**'} |")
        add("")
        add("A card is written for each of Models A, B and C recording what the")
        add("contract requires and that the model behind it does not exist. None is")
        add("signed: Master §3.1 requires an independent validator, and a card for")
        add("an unbuilt model has nothing to validate.")
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
        add(f"{len(tickets)} open. Five are Phase 2 §8 do-not-invent values.")
        add("**Five were found by building** and are on no §8 list — LH-407 (the")
        add("GPS-walk label set nobody scheduled), LH-408 (the mandi price window,")
        add("as distinct from the feed), LH-409 (where an abstaining model's cases")
        add("go), LH-411 (the function combining LandQualityIndex's six named")
        add("inputs), LH-412 (which season a default belongs to).")
    add("")

    add("## Gate outcome")
    add("")
    add("**Fail — not presentable.** Master §3.1 offers pass / conditional pass /")
    add("fail, and none fits a phase with no measurable criterion. The honest")
    add("statement is that Phase 2 should not be taken to a Gate Review at all")
    add("until LH-406 and LH-102 land; a review with nothing to review consumes")
    add("committee time and produces a remediation list identical to the ticket")
    add("register above.")
    add("")
    add("What a Track B team receives instead: every deterministic computation in")
    add("the phase, built and tested against the interfaces their backends occupy,")
    add("and a ticketed list of exactly three models and one dataset they must")
    add("supply.")

    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 2 gate evidence pack")
    parser.add_argument("--output", default="reports/phase2_gate.md")
    args = parser.parse_args(argv)

    # Resolve relative paths against the repo root so `make gate2` works from
    # anywhere, while leaving an absolute path exactly where the caller asked.
    output = pathlib.Path(args.output)
    if not output.is_absolute():
        output = REPO / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(build()) + "\n", encoding="utf-8")

    print(f"phase 2 gate pack -> {output}")
    print("exit criteria: 0 of 6 measured, 6 of 6 not measurable")
    print(f"open tickets: {len(_open_tickets())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

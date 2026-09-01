#!/usr/bin/env python3
"""Assemble the Phase 3 gate evidence pack.

Master §3.1: each phase ends with a Gate Review presenting an evidence pack.
Phase 3 §7 states six exit criteria; this collects what exists against each and
states plainly what does not. An evidence pack that omits a criterion silently
is worse than one that says "not measured", because an omission reads as an
oversight while a stated blocker reads as a blocker.

Phase 3 adds a distinction Phase 1 did not need. Some criteria are **not
measured** — nothing has been run. Others are **not measurable**: no data on any
available track can produce the number, and no amount of effort inside this
repository changes that. The CCF model is the clean example. Reporting both as
"not measured" would put a scheduling problem and a structural one in the same
column.

Per ADR-0003 and ADR-0004, **only Track B numbers are gate evidence.** The
Track P run proves the code paths on real mortgage data; it is not evidence
about this bank's portfolio, and every row it contributes is labelled.

Exit code 0 whether or not the gate passes — a report that fails CI when the
gate fails would create pressure to stop generating it.
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
TRACK_P_RUN = "trackP_p3_fannie_mae.json"
MODEL_CARDS = REPO / "docs/phase3/model_cards"
TICKETS = REPO / "docs/phase3/blocking_tickets.md"

#: Phase 3 §7, verbatim, with the workstream each belongs to.
CRITERIA = [
    ("Hazard GBM C-index ≥ Cox + 0.02 and ≥ 0.75 absolute", "WS-3.1 Step 3"),
    ("PD calibration by grade within ±15% relative on backtest years", "WS-3.1 Step 1"),
    ("LGD MAE ≤ incumbent", "WS-3.1 Step 5"),
    ("Dashboard freshness SLO met over 30 consecutive days", "WS-3.2 Step 1"),
    ("ECL parallel-run memo signed", "Phase 3 §5"),
    ("Staging provenance audit clean", "WS-3.1 Step 7"),
]

#: Criteria that cannot be evaluated from any data reachable here, with why.
NOT_MEASURABLE = {
    "LGD MAE ≤ incumbent": (
        "there is no incumbent LGD model to compare against, and the comparison "
        "is against this bank's provisioning model (LH-120)"
    ),
    "ECL parallel-run memo signed": (
        "a parallel run needs a live provisioning process and a Finance "
        "signatory; neither exists outside a bank deployment"
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
    """Each card, and whether it carries a signature.

    A card exists / a card is signed are different states, and the second is
    what Master §2 rule 5 asks for. An open placeholder anywhere in the card
    also disqualifies it — the placeholder syntax comes from
    ``definitions.provenance`` rather than being restated here, so a change to
    what a placeholder looks like cannot leave this detector behind.
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


def _criterion_state(name: str, run: dict | None) -> tuple[str, str]:
    """``(measured, state)`` for one criterion."""
    if name in NOT_MEASURABLE:
        return "—", f"**not measurable** — {NOT_MEASURABLE[name]}"

    if run is None:
        return "—", "**not measured** — no Track P run present"

    if name.startswith("Hazard GBM C-index"):
        metrics = run.get("survival_metrics", {})
        challenger = metrics.get("concordance_challenger", {})
        reference = metrics.get("concordance_cox_reference", {})
        value = challenger.get("c_index")
        if value is None:
            return "—", "**not measured** — no concordance in the run"
        uplift = metrics.get("c_index_uplift_over_cox")
        measured = (
            f"C {value:.4f} vs Cox {reference.get('c_index', float('nan')):.4f}, "
            f"uplift {uplift:+.4f} (Track P)"
            if uplift is not None else f"{value:.4f} (Track P)"
        )
        detail = (
            "**not decidable at this event count** — the same configuration "
            "produced an uplift of +0.075 at one sample size and −0.119 at "
            "another, a sign change of 0.19 against a criterion stated at +0.02 "
            "(Phase 3 finding D6). Read the number above as one draw, not as a "
            "result. Not gate evidence either way: Track P is US conforming "
            "mortgages, not this bank's book (ADR-0012)"
        )
        caveat = challenger.get("caveat", "")
        if caveat:
            detail += f". Also: {caveat}"
        return measured, detail

    if name.startswith("PD calibration"):
        pd_section = run.get("behavioural_pd", {})
        gini = pd_section.get("test_gini")
        if gini is None:
            return "—", "**not measured**"
        return (
            f"out-of-time Gini {gini} (Track P)",
            "not evaluable — the criterion is calibration by *grade*, and grades "
            "need the score bands that LH-204 has not ratified",
        )

    if name.startswith("Dashboard freshness"):
        book = (run.get("aggregates") or {}).get("book") or {}
        if not book:
            return "—", "**not measured**"
        return (
            f"{book.get('freshness_seconds')}s on one batch pass",
            "not evaluable — the criterion is 30 *consecutive days* of a live "
            "streaming surface; a batch computation cannot produce it",
        )

    if name.startswith("Staging provenance"):
        staging = run.get("staging", {})
        counts = staging.get("counts", {})
        undeterminable = counts.get("undeterminable")
        if undeterminable is None:
            return "—", "**not measured**"
        fraction = staging.get("undeterminable_fraction")
        return (
            f"{undeterminable:,} of {staging.get('accounts', 0):,} undeterminable "
            f"({fraction:.0%})" if fraction is not None else f"{undeterminable:,}",
            "not evaluable — provenance is logged on every decision, but "
            "Stage 1 cannot be assigned at all without LH-301 and LH-308, so "
            "most accounts have no stage to audit",
        )

    return "—", "**not measured**"


def build(run: dict | None) -> list[str]:
    lines: list[str] = []
    add = lines.append

    add("# Phase 3 — gate evidence pack")
    add("")
    add(f"Generated {datetime.now(UTC).isoformat()} by `tools/phase3_gate_report.py`.")
    add("")
    add("Per ADR-0003 and ADR-0004, **only Track B numbers are gate evidence.**")
    add("Track P results below prove the code paths against real mortgage")
    add("performance data and say nothing about this bank's portfolio.")
    add("")
    add("## Exit criteria (Phase 3 §7)")
    add("")
    add("| # | Criterion | Workstream | Track | Measured | State |")
    add("|---|---|---|---|---|---|")
    for index, (name, workstream) in enumerate(CRITERIA, start=1):
        measured, state = _criterion_state(name, run)
        track = "—" if measured == "—" else "P"
        add(f"| {index} | {name} | {workstream} | {track} | {measured} | {state} |")
    add("")
    add("Criteria with **Track B evidence: 0 of 6.** Phase 3 is not exitable, and")
    add("the reason is upstream of Phase 3: Phase 0 has not started (LH-120, written")
    add("data-sharing approvals), so no bank panel exists; and Phase 1 has logged no")
    add("decisions (LH-204), so there are no origination PDs for a SICR baseline.")
    add("")

    add("## Not measured versus not measurable")
    add("")
    add("Two criteria are **not measurable** rather than not measured, and the")
    add("distinction is not pedantry — one is a scheduling item and the other is a")
    add("structural fact that no effort inside this repository changes.")
    add("")
    for name, why in NOT_MEASURABLE.items():
        add(f"* **{name}** — {why}.")
    add("")
    add("The clearest case sits below the criteria: **no CCF model is estimable at")
    add("all.** No revolving product exists on Track A or Track P — Fannie Mae is")
    add("amortising term debt where `L == B₀` makes the CCF denominator identically")
    add("zero, and Home Credit's revolving slice carries no limit history — and the")
    add("regulatory floor is `[POLICY]` (LH-303). `portfolio.ead.fit_ccf()` refuses")
    add("with both reasons rather than fitting the degenerate case.")
    add("")

    add("## What Track P did establish")
    add("")
    if run is None:
        add("No Track P run present. Generate one with `make trackp-p3`.")
    else:
        panel = run.get("panel", {})
        add(f"Dataset `{run.get('dataset')}` vintage `{run.get('vintage')}`, "
            f"{panel.get('loans_sampled', 0):,} loans and "
            f"{panel.get('account_months', 0):,} account-months over "
            f"{panel.get('first_period')} to {panel.get('last_period')}.")
        add("")
        incidence = run.get("observed_incidence")
        if incidence:
            add("**Competing risks are not optional on a mortgage book.** Treating")
            add("prepayment as censoring overstates lifetime default:")
            add("")
            add("| Quantity | Value |")
            add("|---|---|")
            add(f"| Cumulative incidence of default at "
                f"{incidence['horizon_months']}m | {incidence['cif_default']:.4f} |")
            add(f"| Cumulative incidence of prepayment | {incidence['cif_prepay']:.4f} |")
            add(f"| Naive figure ignoring competition | "
                f"{incidence['naive_default_ignoring_competition']:.4f} |")
            add(f"| Overstatement | {incidence['overstatement']:.4f} |")
            if incidence.get("relative_overstatement") is not None:
                add(f"| Relative overstatement | "
                    f"{incidence['relative_overstatement']:.1%} |")
            add("")
        lgd_section = run.get("lgd", {})
        finding = lgd_section.get("credit_enhancement_finding")
        if finding:
            add("**The LGD loss basis decides the sign of the LTV effect (LH-311).**")
            add("")
            add("| Original LTV | Workouts | With enhancement | LGD net | LGD gross |")
            add("|---|---|---|---|---|")
            for band, row in sorted(finding.get("by_ltv_band", {}).items()):
                add(f"| {band} | {row['workouts']:,} | "
                    f"{row['share_with_enhancement']:.1%} | "
                    f"{row['mean_lgd_net']:.4f} | {row['mean_lgd_gross']:.4f} |")
            add("")
        exclusions = run.get("cox_excluded_covariates")
        if exclusions:
            add("**Covariate admissibility in the Cox reference was tested, not**")
            add("**asserted** — and one hypothesis was overturned by the test:")
            add("")
            add("| Covariate | Outcome | What happened |")
            add("|---|---|---|")
            for name, detail in sorted(exclusions.items()):
                note = detail.get("note", "").replace("\n", " ")[:220]
                add(f"| `{name}` | {detail.get('outcome')} | {note} |")
            add("")

    add("## Model cards (Master §2 rule 5)")
    add("")
    cards = _model_cards()
    if not cards:
        add("No Phase 3 model cards present.")
    else:
        add("| Card | Signed |")
        add("|---|---|")
        for name, signed in cards:
            add(f"| `{name}` | {'yes' if signed else '**no**'} |")
        add("")
        add("An unsigned card is not a completed card. Master §3.1 requires an")
        add("independent validator who is not the developer; none exists on")
        add("Track P, and `lending_hub.mlops.promotion` refuses the transition on")
        add("that basis.")
    add("")

    add("## Open Phase 3 blockers")
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
    add("Earlier-phase tickets that also block Phase 3: **LH-103** (default code")
    add("sets — they decide the hazard model's numerator), **LH-120** (data-sharing")
    add("approvals), **LH-204** (no logged decisions, so no SICR baseline).")
    add("Full register: [docs/phase3/blocking_tickets.md](../docs/phase3/blocking_tickets.md).")
    add("")

    if run is not None:
        add("## Track P run (not gate evidence)")
        add("")
        add(f"Seeded run, {run.get('elapsed_seconds')}s. Reproduce with `make trackp-p3`.")
        add("Every limitation is listed in the run report's `panel.limitations`")
        add("block — Fannie's zero-balance code conflates prepayment with maturity,")
        add("there is no revolving product, and these are US conforming mortgages")
        add("rather than this bank's book.")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(REPORTS / "phase3_gate.md"))
    args = parser.parse_args(argv)

    run = _load(TRACK_P_RUN)
    lines = build(run)
    text = "\n".join(lines) + "\n"

    output = pathlib.Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

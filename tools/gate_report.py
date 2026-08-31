#!/usr/bin/env python3
"""Assemble the Phase 0 gate evidence pack from the reports/ directory.

Master §3.1: each phase ends with a Gate Review presenting an evidence pack. This
collects whatever the gate scripts have produced and states plainly what is
missing — an evidence pack that omits a gate silently is worse than one that says
"not measured", because the omission reads as an oversight rather than a blocker.

Every number is stamped with the track that produced it. Per ADR-0003, only
Track B output is gate evidence.

Exit codes: 0 written (whether or not gates pass), 2 nothing to report on.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import UTC, datetime

REPORTS = pathlib.Path("reports")

#: Phase 0 §7 numeric gates and the report each is expected to come from.
GATES = [
    ("Join rate ≥ 99.5%", "join_rate_audit.json", "WS-0.1.3"),
    ("GL delta ≤ 0.1%", "gl_reconciliation.json", "WS-0.1.5"),
    ("Stream freshness < 60 s", "freshness.json", "WS-0.1.4"),
    ("Scorecard parity ≥ 99.9%", "parity.json", "WS-0.4"),
    ("Serving latency p99", "loadtest.json", "WS-0.2.4"),
]


def _load(name: str) -> dict | None:
    path = REPORTS / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"status": "unreadable"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="reports/phase0_gate.md")
    args = parser.parse_args(argv)

    lines = [
        "# Phase 0 — gate evidence pack",
        "",
        f"Generated {datetime.now(UTC).isoformat()} by `tools/gate_report.py`.",
        "",
        "Per ADR-0003, **only Track B numbers are gate evidence.** A Track A result",
        "describes the code that computed it, not the portfolio.",
        "",
        "## Numeric gates (Phase 0 §7)",
        "",
        "| Gate | Workstream | Track | Result | State |",
        "|---|---|---|---|---|",
    ]

    ready = 0
    for label, filename, workstream in GATES:
        report = _load(filename)
        if report is None:
            lines.append(f"| {label} | {workstream} | — | — | **not run** |")
            continue
        if report.get("status") == "blocked":
            blockers = ", ".join(report.get("blocked_on", []))
            lines.append(f"| {label} | {workstream} | — | — | **blocked** on {blockers} |")
            continue

        track = report.get("track", "?")
        passed = report.get("passed")
        if passed is None and "gate" in report:
            checks = report["gate"].get("checks", [])
            passed = all(c["passed"] for c in checks) if checks else None
            result = ", ".join(
                f"{c['name']}={'n/a' if c['rate'] is None else format(c['rate'], '.4%')}"
                for c in checks
            )
        else:
            result = _headline(report)

        state = "pass" if passed else "fail"
        if track == "A":
            state += " (Track A — not gate evidence)"
        else:
            ready += 1
        lines.append(f"| {label} | {workstream} | {track} | {result} | **{state}** |")

    lines += [
        "",
        f"Gates with Track B evidence: **{ready} of {len(GATES)}**.",
        "",
        "## Outstanding blockers",
        "",
        "See [blocking_tickets.md](../docs/phase0/blocking_tickets.md). Phase 0 cannot",
        "be exited until the four numeric gates have Track B evidence — see",
        "[STATUS.md](../docs/phase0/STATUS.md).",
        "",
        "## Also required in the pack (Master §3.1)",
        "",
        "- Model cards for every model — none exist yet; Phase 0 ships no models by design.",
        "- Independent validation report — not applicable until a model exists.",
        "- Security and privacy sign-off — blocked on LH-110, LH-111, LH-140.",
        "- Decision-log spot-audit — `lending_hub.decisionlog.spot_audit`, needs logged decisions.",
        "",
    ]

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"gate evidence pack written to {out}")
    print(f"  {ready} of {len(GATES)} gates have Track B evidence")
    if ready < len(GATES):
        print("  Phase 0 is not exitable — see docs/phase0/STATUS.md")
    return 0


def _headline(report: dict) -> str:
    if "parity" in report:
        parity = report["parity"]
        return "n/a" if parity is None else f"{parity:.4%}"
    if "score" in report and isinstance(report["score"], dict):
        fetch = report.get("feature_fetch", {}).get("p99_ms")
        score = report.get("score", {}).get("p99_ms")
        return f"fetch p99={fetch}ms, score p99={score}ms"
    if "accounts" in report:
        return f"{len(report['accounts'])} account(s)"
    return "see report"


if __name__ == "__main__":
    raise SystemExit(main())

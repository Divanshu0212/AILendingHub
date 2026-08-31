"""Join-rate audit CLI — the WS-0.1.3 written report, generated not typed.

CLAUDE.md convention: every gate number is produced by a committed, rerunnable
script. This is that script for the identity spine.

    make audit-joins        # Track A, over tests/fixtures/
    python -m lending_hub.identity.audit --track B --config <bank config>

Exit codes: 0 gates met, 1 a gate missed, 2 the audit could not run.

Workstream: WS-0.1.3
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import UTC, datetime

from .ports import FixtureReader
from .spine import build_spine

#: Phase 0 WS-0.1.3 / §7 exit criteria: "join rate >= 99.5%". [SPEC]
JOIN_RATE_GATE = 0.995

FIXTURE_DIR = pathlib.Path("tests/fixtures/identity")


def run_track_a(fixture_dir: pathlib.Path):
    return build_spine(
        FixtureReader("cbs", fixture_dir / "cbs_loans.csv"),
        FixtureReader("los", fixture_dir / "los_applications.csv"),
        FixtureReader("collections", fixture_dir / "collections_cases.csv"),
    )


def evaluate(audit) -> list[tuple[str, float | None, bool]]:
    """Score each mandatory join direction against the gate.

    A ``None`` rate (empty denominator) is *not* a pass. An audit with nothing to
    measure has not demonstrated anything, and reporting it as 100% is how an
    empty extract gets signed off.
    """
    return [
        (name, rate, rate is not None and rate >= JOIN_RATE_GATE)
        for name, rate in (
            ("loan_to_application", audit.loan_to_application_rate),
            ("collections_to_loan", audit.collections_to_loan_rate),
            ("customer_consistency", audit.customer_consistency_rate),
        )
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--track", choices=["A", "B"], default="A")
    parser.add_argument("--fixtures", default=str(FIXTURE_DIR))
    parser.add_argument("--out", default="reports/join_rate_audit.json")
    parser.add_argument(
        "--enforce-gate",
        action="store_true",
        help="exit non-zero when a gate is missed. Implied on Track B; on Track A "
        "the fixtures deliberately contain every failure mode, so a Track A "
        "verdict is a property of the fixtures, not of a portfolio (ADR-0003).",
    )
    args = parser.parse_args(argv)

    if args.track == "B":
        print(
            "Track B join audit needs Silver tables (ADR-0001) and source access "
            "(LH-120). Neither is available; nothing was measured.",
            file=sys.stderr,
        )
        return 2

    fixture_dir = pathlib.Path(args.fixtures)
    if not fixture_dir.is_dir():
        print(f"error: fixture directory not found: {fixture_dir}", file=sys.stderr)
        return 2

    _, audit = run_track_a(fixture_dir)
    results = evaluate(audit)

    report = audit.to_dict()
    report["generated_at"] = datetime.now(UTC).isoformat()
    report["gate"] = {
        "threshold": JOIN_RATE_GATE,
        "source": "Phase 0 §7 exit criteria [SPEC]",
        "checks": [
            {"name": name, "rate": rate, "passed": passed} for name, rate, passed in results
        ],
    }

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"identity spine join audit — track {audit.track}")
    print(f"  active CBS loans          {audit.loans_in_cbs}")
    print(f"  collections cases         {audit.collections_cases}")
    for name, rate, passed in results:
        shown = "n/a (empty denominator)" if rate is None else f"{rate:.4%}"
        print(f"  {name:24} {shown:24} {'PASS' if passed else 'FAIL'}")
    if audit.causes():
        print("  root causes:")
        for cause, count in audit.causes().items():
            print(f"    {cause:28} {count}")
    if audit.rejected_keys:
        print("  rejected keys:")
        for problem, count in sorted(audit.rejected_keys.items()):
            print(f"    {problem:28} {count}")
    print(f"  report written to {out}")

    met = all(passed for _, _, passed in results)

    if audit.track == "A":
        print(
            "\n  NOTE Track A: this measures the audit script, not the portfolio.\n"
            "       The fixtures carry one instance of every failure cause on\n"
            "       purpose, so these rates are expected to sit below the gate.\n"
            "       Phase 0 gate evidence requires Track B (ADR-0003)."
        )
        if not args.enforce_gate:
            return 0

    return 0 if met else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Profile a Track P dataset against Master Appendix A.

Every number here is produced by this committed script, stamped Track P, and is
**not** Phase 0 gate evidence (ADR-0004). What it demonstrates is that the
Appendix A label logic in ``lending_hub.definitions`` survives real data — real
missingness, real class imbalance, real dispositions.

    python -m lending_hub.sources.profile --path "datasets/Fannie Mae/2019Q1.csv"

Exit codes: 0 profiled, 2 the file does not match the adapter's column map.

Workstream: WS-0.3.4 · ADR-0004
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from datetime import UTC, datetime

from .fanniemae import LayoutError, build_outcomes, verify_layout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", required=True, help="path to the extract")
    parser.add_argument("--vintage", default="", help="label for the report, e.g. 2007Q1")
    parser.add_argument("--limit", type=int, default=None, help="stop after N rows")
    parser.add_argument(
        "--outcome-months",
        type=int,
        default=None,
        help="outcome window length; defaults to Appendix A's OUTCOME_WINDOW_MONTHS",
    )
    parser.add_argument("--out", default=None, help="write the JSON report here")
    args = parser.parse_args(argv)

    path = pathlib.Path(args.path)
    if not path.exists():
        print(f"error: {path} not found", file=sys.stderr)
        return 2

    vintage = args.vintage or path.stem

    try:
        # Never trust a column map without re-checking it against the file.
        verify_layout(str(path))
    except LayoutError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    started = time.perf_counter()
    _, summary = build_outcomes(
        str(path), limit=args.limit, outcome_months=args.outcome_months
    )
    elapsed = time.perf_counter() - started

    summary.vintage = vintage
    report = summary.to_dict()
    report["generated_at"] = datetime.now(UTC).isoformat()
    report["elapsed_seconds"] = round(elapsed, 1)
    report["outcome_months"] = args.outcome_months
    report["source_file"] = str(path)

    if args.out:
        out = pathlib.Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"{summary.dataset} · {vintage} · track {summary.track}")
    print(f"  rows read            {summary.rows_read:,} in {elapsed:.0f}s")
    print(f"  loans                {summary.loans:,}")
    print(f"  outcome determined   {summary.fully_observed:,} "
          f"(of which {summary.terminated_in_window:,} terminated inside the window)")
    print(f"  censored, excluded   {summary.censored:,}  "
          f"(extract ends {summary.extract_end})")
    print("  Appendix A labels:")
    for name, count in sorted(summary.labels.items()):
        share = count / summary.fully_observed if summary.fully_observed else 0
        print(f"    {name:16} {count:>9,}  {share:7.3%}")
    bad = summary.bad_rate
    ind = summary.indeterminate_rate
    print(f"  bad rate             {'n/a' if bad is None else f'{bad:.3%}'}  (good+bad only)")
    print(f"  indeterminate rate   {'n/a' if ind is None else f'{ind:.3%}'}")
    print(f"  unknown DLQ rows     {summary.unknown_dlq_rows:,}")
    if summary.dispositions:
        print("  dispositions:")
        for code, count in sorted(summary.dispositions.items()):
            print(f"    {code:16} {count:>9,}")
    if args.out:
        print(f"  report written to {args.out}")
    print("\n  NOTE " + report["track_note"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

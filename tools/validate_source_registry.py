#!/usr/bin/env python3
"""CI gate: validate ``config/sources/*.yaml`` against the registry schema.

Phase 0 WS-0.1.1 — "one YAML per source, schema-validated in CI".

Exit codes: 0 valid, 1 schema violations, 2 registry unreadable.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from lending_hub.registry import (  # noqa: E402
    RegistryUnavailable,
    load_registry,
    unresolved_policy_fields,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default="config/sources", help="registry directory")
    parser.add_argument(
        "--strict-policy",
        action="store_true",
        help="also fail when any [POLICY] field is still a TBD placeholder "
        "(the Phase 0 gate condition; not the day-to-day build condition)",
    )
    args = parser.parse_args(argv)

    try:
        records, errors = load_registry(args.dir)
    except RegistryUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    for error in errors:
        print(f"FAIL {error}", file=sys.stderr)

    if errors:
        print(f"\n{len(errors)} schema violation(s) in {args.dir}", file=sys.stderr)
        return 1

    pending = unresolved_policy_fields(records)
    print(f"OK  {len(records)} source(s) valid against schema")
    for record in records:
        flag = f"  [{len(record.unresolved)} pending]" if record.unresolved else ""
        print(f"    {record.id:24} {record.kind.value:10} {record.status.value}{flag}")

    if pending:
        print(f"\n{len(pending)} [POLICY] field(s) awaiting an owner:")
        for source_id, field in pending:
            print(f"    {source_id}.{field}")
        print("  Registered in docs/phase0/blocking_tickets.md — these block the")
        print("  Phase 0 gate, not the build. Run with --strict-policy at gate time.")
        if args.strict_policy:
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

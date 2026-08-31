#!/usr/bin/env python3
"""CI gate: stream schemas evolve backward-compatibly (WS-0.1.4).

Compares each schema in ``src/lending_hub/streaming/schemas/`` against the
previous version of the same record, so a breaking change fails in review rather
than at 3am when a consumer starts throwing.

Versions are files named ``<record>_v<N>.json``. A new version is a new file; an
existing version file is immutable once merged, which is what makes the registry
a record rather than a mutable document.

Exit codes: 0 compatible, 1 breaking change, 2 could not run.
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from lending_hub.streaming import Schema, Severity, check_backward  # noqa: E402

SCHEMA_DIR = pathlib.Path("src/lending_hub/streaming/schemas")
VERSIONED = re.compile(r"^(?P<stem>.+)_v(?P<version>\d+)\.json$")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default=str(SCHEMA_DIR))
    args = parser.parse_args(argv)

    directory = pathlib.Path(args.dir)
    if not directory.is_dir():
        print(f"error: schema directory not found: {directory}", file=sys.stderr)
        return 2

    families: dict[str, list[tuple[int, pathlib.Path]]] = collections.defaultdict(list)
    for path in sorted(directory.glob("*.json")):
        match = VERSIONED.match(path.name)
        if match is None:
            print(
                f"error: {path.name} is not named <record>_v<N>.json, so its version "
                "cannot be ordered",
                file=sys.stderr,
            )
            return 2
        families[match.group("stem")].append((int(match.group("version")), path))

    if not families:
        print(f"error: no schemas found in {directory}", file=sys.stderr)
        return 2

    breaking = 0
    for stem, versions in sorted(families.items()):
        versions.sort()
        loaded = [(v, Schema.load(p), p) for v, p in versions]
        print(f"{stem}: {len(loaded)} version(s)")

        for (old_v, old, _), (new_v, new, new_path) in zip(loaded, loaded[1:]):
            issues = check_backward(old, new)
            label = f"  v{old_v} -> v{new_v}"
            if not issues:
                print(f"{label}  compatible")
                continue
            for issue in issues:
                print(f"{label}  {issue}")
                if issue.severity is Severity.BREAKING:
                    breaking += 1
        if len(loaded) == 1:
            print("  v1 only — nothing to compare yet")

    if breaking:
        print(f"\n{breaking} breaking change(s)", file=sys.stderr)
        return 1
    print("\nschema compatibility: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

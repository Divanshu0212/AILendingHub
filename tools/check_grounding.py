#!/usr/bin/env python3
"""CI gate: enforce the Master §2 grounding rules mechanically.

The Master guide states seven anti-hallucination rules and then relies on every
implementer — human or AI — remembering them. This script is their executable
form. A rule nobody checks is a rule that holds until the first deadline.

Checks
------
G1  Every ``TBD`` is well formed: ``TBD[<owner>, <TICKET-N>]``. A bare ``TBD`` reads as
    handled while belonging to nobody, which is worse than a missing value.
G2  Every ``TBD`` ticket id is registered in docs/phase0/blocking_tickets.md.
G3  On a release branch, no ``TBD`` survives at all (Master §2 rule 4).
G4  Appendix A definitions are not retyped outside the definitions package
    (Master §2 rule 6) — a second copy of "DPD >= 90" is a future divergence
    between scoring, provisioning and EWS.
G5  Synthetic data lives only under ``tests/fixtures/`` (Master §2 rule 3).
G6  Every platform module cites the workstream or contract clause it implements.

Exit codes: 0 clean, 1 violations found.
"""

from __future__ import annotations

import argparse
import ast
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]

SKIP_DIRS = {
    ".git", "__pycache__", ".venv", "venv", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", "node_modules", ".localstack", "reports",
}

TEXT_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".toml", ".json", ".cfg", ".sh", ".ini"}
TEXT_NAMES = {"Makefile", "Dockerfile"}

TICKET_REGISTER = REPO / "docs/phase0/blocking_tickets.md"

WELL_FORMED_TBD = re.compile(r"TBD\[[^,\]]+,\s*[A-Z]{2,}-\d+\]")
ANY_TBD = re.compile(r"TBD(?:\[[^\]]*\])?")
TICKET_IN_TBD = re.compile(r"TBD\[[^,\]]+,\s*([A-Z]{2,}-\d+)\]")

#: Files whose job is to *define or explain* the placeholder grammar. G1 (is this
#: placeholder well formed?) asks whether a TBD is being used as a value, and in
#: these files it never is — they contain the regex that parses it, the schema that
#: rejects it, the prose that teaches it, and the negative test fixtures. G2 and G3
#: still apply here, so a bad ticket reference is still caught.
G1_EXEMPT = {
    "tools/check_grounding.py",
    "tools/validate_source_registry.py",
    "src/lending_hub/definitions/provenance.py",
    "src/lending_hub/registry/schema.py",
}

#: The test suite is the one place malformed placeholders and fake ticket ids are
#: *supposed* to appear — they are the negative fixtures that prove G1 and G2 fire.
#: G1 and G2 are checks on what ships or instructs (code, config, docs), so they
#: skip tests entirely; G4 and G6 still apply.
PLACEHOLDER_CHECK_SKIP_PREFIXES = ("tests/",)

#: Prose describes placeholders; it does not hold them. G1 is a check on values.
G1_EXEMPT_SUFFIXES = {".md"}
G1_EXEMPT_NAMES = {"Makefile"}

#: Formats where a `#` starts a comment. Comments are prose for the same reason
#: docstrings are, so G1 reads only the value side of the line. G2 still reads the
#: whole line: a ticket cited in a comment is still a commitment to a real ticket.
HASH_COMMENT_SUFFIXES = {".yaml", ".yml", ".toml", ".sh", ".ini", ".cfg"}

#: Appendix A values, in the shapes they get accidentally retyped as.
DEFINITION_LEAKS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("default DPD threshold", re.compile(r"\bdpd\b[^\n]{0,24}?[<>!=]=?\s*90\b", re.I)),
    ("default DPD threshold", re.compile(r"\b90\s*(?:\+\s*)?(?:days?[ _]past[ _]due|dpd)\b", re.I)),
    ("indeterminate band", re.compile(r"\b30\s*[-–]\s*89\b")),
    ("outcome window", re.compile(r"\b12\s*months?\s+from\s+disbursal\b", re.I)),
    ("alert precision window", re.compile(r"\brolling\s+90\s*[- ]?days?\b", re.I)),
)

#: The one package allowed to state Appendix A, plus the tests that pin it.
DEFINITION_HOME = (
    "src/lending_hub/definitions/",
    "tests/test_definitions.py",
    "tools/check_grounding.py",
)

#: Where G4 applies. Documentation legitimately quotes the definitions; code and
#: config are where a second copy becomes a divergence.
DEFINITION_SCAN_ROOTS = ("src/", "tools/", "scripts/", "config/")

DATA_SUFFIXES = {".csv", ".parquet", ".jsonl", ".ndjson", ".tsv", ".avro"}
SYNTHETIC_HINT = re.compile(r"synthetic|fixture|sample|mock|dummy|fake|seed[_-]?data", re.I)

#: A module must say which part of the contract it implements. That is usually a
#: numbered workstream, but cross-cutting components (decision logging, the
#: shipping ladder) implement a Master or SRS clause instead and are no less
#: grounded for it.
WORKSTREAM_CITATION = re.compile(r"WS-\d|§\s?\d")
DOCSTRING_EXEMPT = {"src/lending_hub/__init__.py"}


class Finding:
    __slots__ = ("rule", "path", "line", "message")

    def __init__(self, rule: str, path: str, line: int | None, message: str):
        self.rule, self.path, self.line, self.message = rule, path, line, message

    def __str__(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else self.path
        return f"{self.rule} {where}: {self.message}"


def iter_files(root: pathlib.Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def is_text(path: pathlib.Path) -> bool:
    return path.suffix in TEXT_SUFFIXES or path.name in TEXT_NAMES


def read(path: pathlib.Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def registered_tickets() -> set[str]:
    if not TICKET_REGISTER.exists():
        return set()
    text = TICKET_REGISTER.read_text(encoding="utf-8")
    return set(re.findall(r"^\|\s*([A-Z]{2,}-\d+)\s*\|", text, re.M))


def _python_value_strings(text: str) -> list[tuple[int, str]]:
    """String literals a Python module *uses as a value*.

    Docstrings are excluded (they explain, they do not configure) and so are the
    constant fragments of f-strings, which build placeholders rather than declare
    them. What is left is the set of literals where a real "TBD" would hide.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []

    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    docstrings.add(id(body[0].value))

    interpolated: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            for part in ast.walk(node):
                interpolated.add(id(part))

    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in docstrings or id(node) in interpolated:
            continue
        found.append((node.lineno, node.value))
    return found


def _cited_tickets(text: str) -> set[str]:
    """Ticket ids referenced in code form, e.g. ``Pending(..., ticket="LH-101")``.

    Without this, the canonical way to raise a placeholder in Python looks to the
    checker like an unused ticket, and the register slowly fills with false
    "stale" notes until people stop reading them.
    """
    return set(re.findall(r'ticket\s*=\s*["\']([A-Z]{2,}-\d+)["\']', text))


def check_placeholders(files, tickets: set[str], release: bool) -> list[Finding]:
    findings: list[Finding] = []
    used: set[str] = set()

    for path, rel, text in files:
        used |= _cited_tickets(text)

        if rel.startswith(PLACEHOLDER_CHECK_SKIP_PREFIXES):
            continue

        # G2/G3 apply everywhere: a well-formed placeholder is a real commitment
        # wherever it appears, docs included.
        for lineno, line in enumerate(text.splitlines(), 1):
            for token in WELL_FORMED_TBD.findall(line):
                ticket = TICKET_IN_TBD.match(token).group(1)
                used.add(ticket)
                if ticket not in tickets:
                    findings.append(
                        Finding("G2", rel, lineno,
                                f"{token} cites {ticket}, which is not in "
                                "docs/phase0/blocking_tickets.md")
                    )
                if release:
                    findings.append(
                        Finding("G3", rel, lineno,
                                f"{token} on a release branch (Master §2 rule 4)")
                    )

        # G1 asks whether a placeholder used as a *value* is well formed.
        if rel in G1_EXEMPT or path.suffix in G1_EXEMPT_SUFFIXES or path.name in G1_EXEMPT_NAMES:
            continue

        if path.suffix == ".py":
            candidates = _python_value_strings(text)
        elif path.suffix in HASH_COMMENT_SUFFIXES:
            candidates = [
                (lineno, line.split("#", 1)[0])
                for lineno, line in enumerate(text.splitlines(), 1)
            ]
        else:
            candidates = list(enumerate(text.splitlines(), 1))

        for lineno, chunk in candidates:
            for match in ANY_TBD.finditer(chunk):
                token = match.group(0)
                if WELL_FORMED_TBD.fullmatch(token):
                    continue
                findings.append(
                    Finding("G1", rel, lineno,
                            f"malformed placeholder {token!r}; expected "
                            "TBD[<owner>, <TICKET-N>]")
                )

    for ticket in sorted(tickets - used):
        findings.append(
            Finding("G2-info", str(TICKET_REGISTER.relative_to(REPO)), None,
                    f"{ticket} is registered but nothing cites it "
                    "(expected for process tickets; stale otherwise)")
        )
    return findings


def check_definition_leaks(files) -> list[Finding]:
    findings: list[Finding] = []
    for path, rel, text in files:
        if not rel.startswith(DEFINITION_SCAN_ROOTS):
            continue
        if rel.startswith(DEFINITION_HOME):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for term, pattern in DEFINITION_LEAKS:
                if pattern.search(line):
                    findings.append(
                        Finding("G4", rel, lineno,
                                f"{term} appears to be retyped here; import it from "
                                "lending_hub.definitions (Master §2 rule 6)")
                    )
    return findings


def check_synthetic_data(root: pathlib.Path) -> list[Finding]:
    findings: list[Finding] = []
    for path in iter_files(root):
        rel = str(path.relative_to(root))
        if path.suffix not in DATA_SUFFIXES:
            continue
        if rel.startswith("tests/fixtures/"):
            continue
        if SYNTHETIC_HINT.search(rel):
            findings.append(
                Finding("G5", rel, None,
                        "synthetic-looking data file outside tests/fixtures/ "
                        "(Master §2 rule 3)")
            )
    return findings


def check_workstream_citations(files) -> list[Finding]:
    findings: list[Finding] = []
    for path, rel, text in files:
        if not rel.startswith("src/lending_hub/") or path.suffix != ".py":
            continue
        if rel in DOCSTRING_EXEMPT:
            continue
        try:
            doc = ast.get_docstring(ast.parse(text))
        except SyntaxError as exc:
            findings.append(Finding("G6", rel, exc.lineno, f"does not parse: {exc.msg}"))
            continue
        if not doc:
            findings.append(Finding("G6", rel, 1, "module has no docstring"))
        elif not WORKSTREAM_CITATION.search(doc):
            findings.append(
                Finding("G6", rel, 1,
                        "module docstring cites no workstream or contract clause "
                        "(e.g. 'WS-0.1.3' or 'Master §3.3')")
            )
    return findings


def current_branch() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=REPO, capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Master §2 grounding-rule enforcement")
    parser.add_argument(
        "--release", action="store_true",
        help="release-branch mode: any surviving TBD fails the build",
    )
    args = parser.parse_args(argv)

    release = args.release or current_branch().startswith(("release/", "gate/"))

    files = []
    for path in iter_files(REPO):
        if not is_text(path):
            continue
        text = read(path)
        if text is not None:
            files.append((path, str(path.relative_to(REPO)), text))

    tickets = registered_tickets()
    findings = (
        check_placeholders(files, tickets, release)
        + check_definition_leaks(files)
        + check_synthetic_data(REPO)
        + check_workstream_citations(files)
    )

    errors = [f for f in findings if not f.rule.endswith("-info")]
    infos = [f for f in findings if f.rule.endswith("-info")]

    for finding in errors:
        print(f"FAIL {finding}", file=sys.stderr)
    for finding in infos:
        print(f"note {finding}")

    open_placeholders = sum(
        len(WELL_FORMED_TBD.findall(text))
        for path, rel, text in files
        if path.suffix not in G1_EXEMPT_SUFFIXES
        and rel not in G1_EXEMPT
        and not rel.startswith(PLACEHOLDER_CHECK_SKIP_PREFIXES)
    )

    print(
        f"\ngrounding: {len(files)} files scanned · {len(tickets)} tickets registered · "
        f"{open_placeholders} open placeholder(s) · "
        f"{'RELEASE mode' if release else 'development mode'}"
    )

    if errors:
        print(f"grounding: {len(errors)} violation(s)", file=sys.stderr)
        return 1
    print("grounding: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

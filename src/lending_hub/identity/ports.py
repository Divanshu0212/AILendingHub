"""Source-reader port for the identity spine (ADR-0003).

Track A reads fixtures; Track B reads Bronze/Silver tables. Both satisfy this
interface, so the spine builder and the join audit are written once.

Workstream: WS-0.1.3
"""

from __future__ import annotations

import csv
import pathlib
from typing import Iterable, Iterator, Protocol

from .keys import Entity


class SourceReader(Protocol):
    """Yields records from one registered source (``config/sources/<id>.yaml``)."""

    source_id: str
    track: str

    def records(self) -> Iterator[dict]:
        """Yield one dict per row, keys as they appear in the source extract."""
        ...


class FixtureReader:
    """Track A reader over a CSV under ``tests/fixtures/`` (Master §2 rule 3).

    Refuses to read from anywhere else. The check is here rather than in a lint
    rule because this is the exact boundary synthetic data would cross to reach a
    training table, and a runtime refusal is harder to ignore than a warning.
    """

    track = "A"

    def __init__(self, source_id: str, path: pathlib.Path | str):
        self.source_id = source_id
        self.path = pathlib.Path(path)
        parts = self.path.as_posix()
        if "tests/fixtures/" not in parts:
            raise ValueError(
                f"synthetic data must live under tests/fixtures/ (Master §2 rule 3); "
                f"refusing to read {self.path}"
            )

    def records(self) -> Iterator[dict]:
        with self.path.open("r", encoding="utf-8", newline="") as handle:
            yield from csv.DictReader(handle)


class InMemoryReader:
    """Reader over an in-memory sequence — for unit tests of the audit itself."""

    track = "A"

    def __init__(self, source_id: str, rows: Iterable[dict]):
        self.source_id = source_id
        self._rows = list(rows)

    def records(self) -> Iterator[dict]:
        yield from self._rows


class LakehouseReader:
    """Track B reader over a Silver table. Implemented in WS-0.1.2 Track B work."""

    track = "B"

    def __init__(self, source_id: str, table: str, snapshot_tag: str | None = None):
        self.source_id = source_id
        self.table = table
        self.snapshot_tag = snapshot_tag

    def records(self) -> Iterator[dict]:
        raise NotImplementedError(
            "Track B lakehouse reader is not implemented: it needs the Iceberg "
            "catalog from ADR-0001 and source access from LH-120. Track A "
            "(FixtureReader) exercises the same interface meanwhile."
        )


#: Which entity key each spine source is expected to supply. Mirrors the
#: ``entities:`` block in config/sources/*.yaml — the registry is authoritative and
#: `_cross_validate` fails the build if a spine source stops declaring its keys.
SPINE_KEY_COLUMNS: dict[str, dict[Entity, str]] = {
    "cbs": {
        Entity.CUSTOMER: "customer_id",
        Entity.ACCOUNT: "account_id",
        Entity.LOAN: "loan_id",
    },
    "los": {
        Entity.CUSTOMER: "customer_id",
        Entity.APPLICATION: "application_id",
        Entity.LOAN: "loan_id",
    },
    "collections": {
        Entity.CUSTOMER: "customer_id",
        Entity.LOAN: "loan_id",
        Entity.CASE: "case_id",
    },
}

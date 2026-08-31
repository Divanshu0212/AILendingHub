"""Append-only decision log with a verifiable hash chain.

Workstream: Master §3.3
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass

from .record import DecisionRecord


class TamperDetected(Exception):
    """The stored chain does not verify. Never recoverable in place."""


@dataclass
class ChainStatus:
    records: int
    valid: bool
    broken_at: int | None = None
    detail: str = ""


class DecisionLog:
    """JSONL, append-only, hash-chained.

    Track A writes a file; Track B writes the same records to the bank's immutable
    store. The chain logic is identical either way, which is the point — the
    verification a gate spot-audit runs is not a property of the storage engine.
    """

    def __init__(self, path: pathlib.Path | str):
        self.path = pathlib.Path(path)
        self._last_hash: str | None = None
        if self.path.exists():
            self._last_hash = self._tail_hash()

    def _tail_hash(self) -> str | None:
        last = None
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    last = json.loads(line)
        return None if last is None else last.get("_hash")

    def append(self, record: DecisionRecord) -> str:
        """Append a record, chaining it to the previous one. Returns its hash."""
        if record.prev_hash != self._last_hash:
            record = _with_prev_hash(record, self._last_hash)
        digest = record.content_hash()
        payload = record.to_dict()
        payload["_hash"] = digest

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")
        self._last_hash = digest
        return digest

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def verify(self) -> ChainStatus:
        """Walk the chain and confirm nothing was edited or removed."""
        entries = self.read_all()
        prev: str | None = None

        for index, entry in enumerate(entries):
            stored_hash = entry.pop("_hash", None)
            if entry.get("prev_hash") != prev:
                return ChainStatus(
                    len(entries), False, index,
                    f"record {index} points at {entry.get('prev_hash')!r}, expected {prev!r} "
                    "— a record was removed, reordered, or inserted",
                )
            recomputed = _hash_dict(entry)
            if recomputed != stored_hash:
                return ChainStatus(
                    len(entries), False, index,
                    f"record {index} content does not match its stored hash — it was edited",
                )
            prev = stored_hash

        return ChainStatus(len(entries), True)


def _hash_dict(payload: dict) -> str:
    import hashlib

    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _with_prev_hash(record: DecisionRecord, prev_hash: str | None) -> DecisionRecord:
    import dataclasses

    return dataclasses.replace(record, prev_hash=prev_hash)

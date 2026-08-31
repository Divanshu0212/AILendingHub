"""Vintage splits for the application scorecard, and the refusal to fake one.

Phase 1 §4 WS-1.1 Step 1: "Split by vintage: train = oldest 70%, validation =
next 15%, test (out-of-time) = newest 15%. **Random splits are forbidden** —
macro leakage."

Why the prohibition needs teeth
-------------------------------
A random split over a lending portfolio puts loans from the same month, the same
rate cycle and the same policy regime on both sides of the wall. The model learns
the macro conditions of the test set from the training set, and the out-of-time
Gini that a gate review reads is an in-time Gini wearing the wrong name. It is
not a small effect on credit data: it is the difference between a 2007 vintage
looking benign and looking like 2007.

So this module makes the forbidden path *hard to take by accident*:

* :func:`split_by_vintage` is the only route to an out-of-time split, and it
  requires a real vintage key.
* Boundaries snap to whole vintages. Splitting inside a vintage — 70% of the rows
  in ``2019Q1`` to train, the rest to test — is a random split with a date column
  next to it, and it leaks exactly the macro conditions the rule is about.
* :func:`holdout_without_time_axis` exists for sources that genuinely have no
  clock, and it will only run for a source the **registry declares**
  ``point_in_time_unsafe``. A modeller cannot reach it by asserting at split time
  that dates are unavailable; someone had to write the reason down in
  ``config/sources/`` first. Everything it produces is stamped
  ``out_of_time=False``.

Workstream: WS-1.1 Step 1 · SRS §4.4 ("time-based (out-of-time) validation, never
random splits")
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Sequence

from lending_hub.definitions import DEFINITIONS_VERSION, Label, fingerprint

from .target import TargetRow, TargetTable

#: Phase 1 §4 WS-1.1 Step 1 [SPEC]. Fractions of *rows*, not of vintages: a
#: portfolio that tripled in size would otherwise put most of its history in a
#: train set holding a quarter of its loans.
TRAIN_FRACTION = 0.70
VALIDATION_FRACTION = 0.15
TEST_FRACTION = 0.15

#: Phase 1 §3 entry criterion [SPEC]: "≥ 1,500 *bads* for the chosen product per
#: Master Appendix A definition. If fewer → scope reduces to scorecard-only;
#: challenger deferred and the limitation recorded in the gate pack."
MINIMUM_BADS_FOR_CHALLENGER = 1_500


class SplitError(Exception):
    """The requested split cannot be built as specified."""


class RandomSplitForbidden(SplitError):
    """Phase 1 §4 WS-1.1 Step 1 forbids random splits."""


class Part(str, Enum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"


@dataclass
class Splits:
    """One partition of a target table, plus what may be claimed about it."""

    train: list[TargetRow] = field(default_factory=list)
    validation: list[TargetRow] = field(default_factory=list)
    test: list[TargetRow] = field(default_factory=list)

    out_of_time: bool = True
    """False when the test part is not later in time than the train part. Every
    metric computed from such a test set is stamped with this, so an in-time
    number cannot be quoted as an out-of-time one."""

    strategy: str = "vintage"
    boundaries: dict[str, list[str]] = field(default_factory=dict)
    limitation: str = ""

    def part(self, part: Part) -> list[TargetRow]:
        return {Part.TRAIN: self.train, Part.VALIDATION: self.validation, Part.TEST: self.test}[part]

    @property
    def sizes(self) -> dict[str, int]:
        return {p.value: len(self.part(p)) for p in Part}

    def trainable(self, part: Part) -> list[TargetRow]:
        return [row for row in self.part(part) if row.trainable]

    def bads(self, part: Part) -> int:
        return sum(1 for row in self.trainable(part) if row.label is Label.BAD)

    def base_rate(self, part: Part) -> float | None:
        rows = self.trainable(part)
        if not rows:
            return None
        return self.bads(part) / len(rows)

    def challenger_in_scope(self) -> tuple[bool, str]:
        """Phase 1 §3: below the bad floor the phase reduces to scorecard-only.

        Counted on the training part, which is what a challenger actually learns
        from. Counting the whole table would pass the test on bads the model never
        sees.
        """
        bads = self.bads(Part.TRAIN)
        if bads >= MINIMUM_BADS_FOR_CHALLENGER:
            return True, f"{bads} training bads meets the Phase 1 §3 floor"
        return False, (
            f"{bads} training bads is below the Phase 1 §3 floor of "
            f"{MINIMUM_BADS_FOR_CHALLENGER}: scope reduces to scorecard-only, the "
            "challenger is deferred, and the limitation goes in the gate pack"
        )


@dataclass
class SplitManifest:
    """The versioned split record. Phase 1 §6 deliverable: "split manifest"."""

    dataset: str
    strategy: str
    out_of_time: bool
    sizes: dict[str, int]
    bads: dict[str, int]
    base_rates: dict[str, float | None]
    boundaries: dict[str, list[str]]
    fractions: dict[str, float]
    challenger_in_scope: bool
    challenger_note: str
    limitation: str = ""
    definitions_version: str = DEFINITIONS_VERSION
    definitions_fingerprint: str = ""
    target_manifest_hash: str = ""

    def to_dict(self) -> dict:
        return {
            "dataset": self.dataset,
            "strategy": self.strategy,
            "out_of_time": self.out_of_time,
            "sizes": self.sizes,
            "bads": self.bads,
            "base_rates": self.base_rates,
            "boundaries": self.boundaries,
            "fractions": self.fractions,
            "challenger_in_scope": self.challenger_in_scope,
            "challenger_note": self.challenger_note,
            "limitation": self.limitation,
            "definitions_version": self.definitions_version,
            "definitions_fingerprint": self.definitions_fingerprint,
            "target_manifest_hash": self.target_manifest_hash,
        }

    def hash(self) -> str:
        blob = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def split_by_vintage(
    table: TargetTable,
    *,
    train_fraction: float = TRAIN_FRACTION,
    validation_fraction: float = VALIDATION_FRACTION,
) -> Splits:
    """Partition oldest-first by vintage, snapping boundaries to whole vintages.

    Vintages are ordered by their string key, which is why the key must sort
    chronologically — ``2019Q1`` does, ``Q1-2019`` does not. The check is explicit
    rather than trusting the caller, because a lexical order that happens to be
    wrong produces a split that looks temporal and is not.
    """
    rows = list(table.rows)
    if not rows:
        raise SplitError("cannot split an empty target table")

    by_vintage: dict[str, list[TargetRow]] = {}
    for row in rows:
        by_vintage.setdefault(row.vintage, []).append(row)

    vintages = sorted(by_vintage)
    _check_chronological(by_vintage, vintages)

    if len(vintages) < 3:
        raise SplitError(
            f"{len(vintages)} vintage(s) in the table: an out-of-time test needs at "
            "least three so that train, validation and test can each hold a whole "
            "one. Splitting inside a vintage is a random split with a date column "
            "beside it."
        )

    total = len(rows)
    train_cut = train_fraction * total
    validation_cut = (train_fraction + validation_fraction) * total

    splits = Splits(strategy="vintage", out_of_time=True)
    assigned: dict[str, list[str]] = {p.value: [] for p in Part}

    seen = 0
    for vintage in vintages:
        chunk = by_vintage[vintage]
        # The vintage is placed by where its *midpoint* falls, so a single large
        # vintage straddling a boundary lands on the side it mostly belongs to
        # instead of being torn in half.
        midpoint = seen + len(chunk) / 2
        if midpoint <= train_cut:
            part = Part.TRAIN
        elif midpoint <= validation_cut:
            part = Part.VALIDATION
        else:
            part = Part.TEST
        splits.part(part).extend(chunk)
        assigned[part.value].append(vintage)
        seen += len(chunk)

    empty = [name for name, vintages_in in assigned.items() if not vintages_in]
    if empty:
        raise SplitError(
            f"no vintage landed in {', '.join(sorted(empty))}. The vintages are too "
            "unevenly sized for these fractions; either regroup the cohorts or state "
            "different fractions deliberately — never fall back to a random split."
        )

    splits.boundaries = assigned
    return splits


def _check_chronological(by_vintage: dict[str, list[TargetRow]], ordered: list[str]) -> None:
    """Confirm the vintage keys sort in the same order as the decisions they hold."""
    latest = None
    for vintage in ordered:
        earliest_in_vintage = min(row.decided_at for row in by_vintage[vintage])
        if latest is not None and earliest_in_vintage < latest:
            raise SplitError(
                f"vintage {vintage!r} sorts after its predecessor but contains an "
                f"earlier decision ({earliest_in_vintage}). The vintage key does not "
                "sort chronologically, so an ordering by it is not an ordering in "
                "time."
            )
        latest = max(row.decided_at for row in by_vintage[vintage])


def _registry_says_unsafe(source_id: str) -> bool:
    from lending_hub.registry import load_registry

    records, _ = load_registry()
    for record in records:
        if record.id == source_id:
            return record.point_in_time_unsafe
    raise SplitError(
        f"{source_id!r} is not in the source registry. A dataset that is not "
        "registered cannot declare anything about its time axis (WS-0.1.1)."
    )


def holdout_without_time_axis(
    table: TargetTable,
    *,
    source_id: str,
    seed: int,
    train_fraction: float = TRAIN_FRACTION,
    validation_fraction: float = VALIDATION_FRACTION,
    registry_lookup: Callable[[str], bool] = _registry_says_unsafe,
) -> Splits:
    """A non-temporal holdout, available only to a declared clockless source.

    This is the forbidden split, permitted narrowly. It exists because Home Credit
    — the only Track P source with the right product shape — publishes every time
    column as a relative day offset from an unstated reference date, so there is
    no order to split on. Refusing to split at all would mean no reference
    implementation runs against real consumer-credit data.

    What keeps it honest is that the permission comes from the **registry**, not
    from the caller: ``point_in_time_unsafe: true`` with a written
    ``unsafe_reason`` had to be committed to ``config/sources/`` before this
    function will run. And everything it returns carries ``out_of_time=False``, so
    no metric derived from it can be presented as out-of-time evidence.
    """
    if not registry_lookup(source_id):
        raise RandomSplitForbidden(
            f"{source_id!r} is not declared point_in_time_unsafe in the source "
            "registry, so it has a usable time axis and must be split by vintage "
            "(Phase 1 §4 WS-1.1 Step 1). If its dates are genuinely unusable, say so "
            "in config/sources/ with a reason first — that statement is the thing a "
            "reviewer can check."
        )

    rows = list(table.rows)
    if not rows:
        raise SplitError("cannot split an empty target table")

    # Ordered by application id before shuffling, so the partition depends on the
    # seed and the data — not on the order the rows happened to arrive in.
    rows.sort(key=lambda row: row.application_id)
    random.Random(seed).shuffle(rows)

    train_end = int(train_fraction * len(rows))
    validation_end = int((train_fraction + validation_fraction) * len(rows))

    return Splits(
        train=rows[:train_end],
        validation=rows[train_end:validation_end],
        test=rows[validation_end:],
        out_of_time=False,
        strategy=f"random_holdout(seed={seed})",
        boundaries={p.value: [] for p in Part},
        limitation=(
            f"{source_id} is declared point_in_time_unsafe in the source registry: "
            "its time columns are relative offsets with no absolute reference, so no "
            "vintage ordering exists. This holdout is random. Nothing computed from "
            "it is out-of-time evidence, and every model fitted on it records the "
            "limitation on its card."
        ),
    )


def manifest(table: TargetTable, splits: Splits) -> SplitManifest:
    """Assemble the versioned split manifest (Phase 1 §6 deliverable)."""
    in_scope, note = splits.challenger_in_scope()
    return SplitManifest(
        dataset=table.dataset,
        strategy=splits.strategy,
        out_of_time=splits.out_of_time,
        sizes=splits.sizes,
        bads={p.value: splits.bads(p) for p in Part},
        base_rates={p.value: splits.base_rate(p) for p in Part},
        boundaries=splits.boundaries,
        fractions={
            "train": TRAIN_FRACTION,
            "validation": VALIDATION_FRACTION,
            "test": TEST_FRACTION,
        },
        challenger_in_scope=in_scope,
        challenger_note=note,
        limitation=splits.limitation,
        definitions_fingerprint=fingerprint(),
        target_manifest_hash=table.manifest_hash(),
    )


def forbid_random_split(rows: Sequence[TargetRow]) -> None:  # pragma: no cover - guard
    """Explicit tripwire for anyone reaching for a shuffle in a training path."""
    raise RandomSplitForbidden(
        "random splits are forbidden on lending data (Phase 1 §4 WS-1.1 Step 1): "
        "same-month loans on both sides of the wall leak the macro regime. Use "
        "split_by_vintage, or holdout_without_time_axis for a registry-declared "
        "clockless source."
    )

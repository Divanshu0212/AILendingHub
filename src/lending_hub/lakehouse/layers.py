"""Bronze / Silver / Gold layer contracts.

Phase 0 WS-0.1.2: "Bronze (raw immutable) -> Silver (cleaned, conformed) -> Gold
(feature-ready) on an ACID table format ... Time-travel/versioning enabled on
every table (this is what makes SRS CS-7 'reproducible for 8 years' physically
possible)."

The rules encoded here are the ones that get broken quietly under deadline
pressure: a "quick fix" applied to Bronze, a Gold table reading from Bronze
because Silver is not ready yet, an untagged table feeding a training run. Each
one is individually defensible in the moment and collectively destroys the
reproducibility the layering exists to provide.

Workstream: WS-0.1.2
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Layer(str, Enum):
    BRONZE = "bronze"
    """Raw, immutable, exactly as extracted. Never corrected in place — a
    correction is a new row, so the extract stays reproducible."""

    SILVER = "silver"
    """Cleaned and conformed to the identity spine. Where corrections live."""

    GOLD = "gold"
    """Feature-ready. The only layer the feature store reads."""


#: Which layer may read from which. Skipping a layer is the recurring shortcut:
#: it works, and it moves the cleaning logic somewhere nobody audits.
ALLOWED_SOURCES: dict[Layer, frozenset[Layer]] = {
    Layer.BRONZE: frozenset(),
    Layer.SILVER: frozenset({Layer.BRONZE, Layer.SILVER}),
    Layer.GOLD: frozenset({Layer.SILVER, Layer.GOLD}),
}


class LayerViolation(Exception):
    pass


@dataclass(frozen=True)
class TableSpec:
    """One lakehouse table and the guarantees it carries."""

    name: str
    layer: Layer
    source_id: str
    """The registered source in config/sources/ this table derives from."""

    reads_from: tuple[str, ...] = ()
    partition_by: tuple[str, ...] = ()
    time_travel: bool = True
    contains_pii: bool | None = None
    """None means the DPO has not classified it yet (LH-110) — distinct from
    False, which is a decision."""

    description: str = ""

    def __post_init__(self) -> None:
        if not self.time_travel:
            raise LayerViolation(
                f"{self.name}: time travel cannot be disabled. SRS CS-7 requires any "
                "decision to be reconstructable for 8 years, and a table without "
                "versioning makes that physically impossible (WS-0.1.2)."
            )
        if self.layer is Layer.BRONZE and self.reads_from:
            raise LayerViolation(
                f"{self.name}: Bronze is raw extract only; it cannot read another table"
            )


@dataclass
class Lakehouse:
    """The registered table set, with layering enforced at registration."""

    tables: dict[str, TableSpec] = field(default_factory=dict)

    def register(self, spec: TableSpec) -> None:
        if spec.name in self.tables:
            raise LayerViolation(f"{spec.name}: already registered")

        for upstream_name in spec.reads_from:
            upstream = self.tables.get(upstream_name)
            if upstream is None:
                raise LayerViolation(
                    f"{spec.name}: reads from {upstream_name!r}, which is not registered"
                )
            if upstream.layer not in ALLOWED_SOURCES[spec.layer]:
                raise LayerViolation(
                    f"{spec.name} ({spec.layer.value}) cannot read "
                    f"{upstream_name} ({upstream.layer.value}): allowed sources are "
                    f"{sorted(s.value for s in ALLOWED_SOURCES[spec.layer])}. "
                    "Skipping a layer moves cleaning logic somewhere nobody audits."
                )

        self.tables[spec.name] = spec

    def unclassified(self) -> list[str]:
        """Tables the DPO has not classified for PII (LH-110)."""
        return sorted(n for n, t in self.tables.items() if t.contains_pii is None)

    def lineage(self, name: str) -> list[str]:
        """Transitive upstream tables, nearest first."""
        seen: list[str] = []
        queue = list(self.tables[name].reads_from)
        while queue:
            current = queue.pop(0)
            if current in seen:
                continue
            seen.append(current)
            queue.extend(self.tables[current].reads_from)
        return seen

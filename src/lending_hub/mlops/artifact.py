"""Model artifacts and the reproducibility triplet.

Phase 0 WS-0.2.3: "A registered model artifact = {code commit SHA, data snapshot
version, config hash}." Everything about reproducibility hangs off that triplet
being complete and honest, so it is a type here rather than a convention: a
partially-specified triplet cannot be constructed.

Workstream: WS-0.2.3
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Stage(str, Enum):
    """MLflow registry stages (WS-0.2.2)."""

    NONE = "None"
    STAGING = "Staging"
    PRODUCTION = "Production"
    ARCHIVED = "Archived"


@dataclass(frozen=True)
class Triplet:
    """What a model was built from. All three parts are mandatory.

    A triplet with a missing part is not "mostly reproducible" — it is
    unreproducible, and recording it as if it were the former is how a model
    reaches validation with an untraceable lineage.
    """

    code_commit: str
    data_snapshot: str
    """Iceberg snapshot tag (ADR-0001), not a timestamp — a tag is durable and a
    timestamp is a lookup that ages out."""

    config_hash: str

    def __post_init__(self) -> None:
        for name in ("code_commit", "data_snapshot", "config_hash"):
            if not getattr(self, name):
                raise ValueError(
                    f"{name} is required: a partial triplet is not partially "
                    "reproducible, it is unreproducible"
                )

    def key(self) -> str:
        return f"{self.code_commit}|{self.data_snapshot}|{self.config_hash}"

    def digest(self) -> str:
        return hashlib.sha256(self.key().encode("utf-8")).hexdigest()[:16]


def config_hash(config: dict) -> str:
    """Stable hash of a training config. Key order and formatting must not matter."""
    blob = json.dumps(config, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


@dataclass
class ModelArtifact:
    """A registered model version."""

    name: str
    version: str
    triplet: Triplet
    definitions_fingerprint: str
    stage: Stage = Stage.NONE
    metrics: dict = field(default_factory=dict)
    model_card_path: str | None = None
    validation_report_path: str | None = None
    shadow_started_at: datetime | None = None
    registered_at: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "stage": self.stage.value,
            "triplet": {
                "code_commit": self.triplet.code_commit,
                "data_snapshot": self.triplet.data_snapshot,
                "config_hash": self.triplet.config_hash,
                "digest": self.triplet.digest(),
            },
            "definitions_fingerprint": self.definitions_fingerprint,
            "metrics": self.metrics,
            "model_card_path": self.model_card_path,
            "validation_report_path": self.validation_report_path,
            "shadow_started_at": (
                self.shadow_started_at.isoformat() if self.shadow_started_at else None
            ),
        }

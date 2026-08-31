"""Model registry port (ADR-0003).

Workstream: WS-0.2.2
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .artifact import ModelArtifact, Stage
from .promotion import PromotionDecision, can_promote


class ModelRegistry(Protocol):
    track: str

    def register(self, artifact: ModelArtifact) -> None: ...

    def get(self, name: str, version: str) -> ModelArtifact: ...

    def transition(self, name: str, version: str, target: Stage, *, via_ci: bool) -> None: ...


class InMemoryRegistry:
    """Track A registry. Enforces exactly the same promotion gate as Track B."""

    track = "A"

    def __init__(self):
        self._artifacts: dict[tuple[str, str], ModelArtifact] = {}

    def register(self, artifact: ModelArtifact) -> None:
        self._artifacts[(artifact.name, artifact.version)] = artifact

    def get(self, name: str, version: str) -> ModelArtifact:
        try:
            return self._artifacts[(name, version)]
        except KeyError as exc:
            raise LookupError(f"{name} v{version} is not in the registry") from exc

    def transition(
        self,
        name: str,
        version: str,
        target: Stage,
        *,
        via_ci: bool,
        now: datetime | None = None,
        fallback_path_warm: bool = True,
    ) -> PromotionDecision:
        from datetime import UTC

        artifact = self.get(name, version)
        decision = can_promote(
            artifact,
            target,
            now=now or datetime.now(UTC),
            via_ci=via_ci,
            fallback_path_warm=fallback_path_warm,
        )
        if decision.allowed:
            artifact.stage = target
        return decision


class MlflowRegistry:
    """Track B adapter over an MLflow registry (WS-0.2.2)."""

    track = "B"

    def __init__(self, tracking_uri: str):
        self.tracking_uri = tracking_uri

    def register(self, artifact: ModelArtifact) -> None:
        raise NotImplementedError(
            "Track B needs a deployed MLflow server (WS-0.2.2). It must apply "
            "lending_hub.mlops.promotion.can_promote before any transition — the "
            "gate is the contract, not the storage."
        )

    def get(self, name, version):
        raise NotImplementedError("Track B: see register")

    def transition(self, name, version, target, *, via_ci):
        raise NotImplementedError("Track B: see register")

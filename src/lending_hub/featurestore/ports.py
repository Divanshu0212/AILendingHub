"""Feature-store port (ADR-0003).

Track A is the reference implementation in :mod:`lending_hub.featurestore.pit`.
Track B delegates to Feast — Master §2 rule 2 allows exactly one reference
implementation per algorithm, and for point-in-time joins that is Feast's
``get_historical_features``, not a reimplementation of it.

Workstream: WS-0.2.1
"""

from __future__ import annotations

from typing import Protocol, Sequence

from .pit import EntityRow, FeatureSource, JoinResult, get_historical_features


class FeatureStore(Protocol):
    """The only sanctioned way a model reads features (WS-0.2.1 contract)."""

    track: str

    def get_historical_features(
        self, entity_rows: Sequence[EntityRow], features: Sequence[str]
    ) -> JoinResult:
        """Point-in-time correct training dataset."""
        ...

    def get_online_features(self, entity_key: str, features: Sequence[str]) -> dict:
        """Latest known values for serving."""
        ...


class LocalFeatureStore:
    """Track A store over in-memory sources. Used by tests and the parity harness."""

    track = "A"

    def __init__(self, sources: Sequence[FeatureSource]):
        self._sources = {s.spec.name: s for s in sources}

    def _resolve(self, features: Sequence[str]) -> list[FeatureSource]:
        missing = [f for f in features if f not in self._sources]
        if missing:
            raise KeyError(f"features not registered in the store: {missing}")
        return [self._sources[f] for f in features]

    def get_historical_features(
        self, entity_rows: Sequence[EntityRow], features: Sequence[str]
    ) -> JoinResult:
        return get_historical_features(entity_rows, self._resolve(features))

    def get_online_features(self, entity_key: str, features: Sequence[str]) -> dict:
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        out = {}
        for source in self._resolve(features):
            value = source.as_of(entity_key, now)
            out[source.spec.name] = None if value is None else value.value
        return out

    def as_of_lookup(self, entity_key: str, feature: str, observation_point):
        """Online-style lookup at a historical point — for the skew comparison."""
        value = self._sources[feature].as_of(entity_key, observation_point)
        return None if value is None else value.value


class FeastFeatureStore:
    """Track B adapter. Implemented when a Feast deployment exists (LH-120)."""

    track = "B"

    def __init__(self, repo_path: str):
        self.repo_path = repo_path

    def get_historical_features(self, entity_rows, features):
        raise NotImplementedError(
            "Track B needs a deployed Feast repo with the lakehouse as offline store "
            "(WS-0.2.1). It must delegate to feast.FeatureStore.get_historical_features "
            "rather than reimplement the join, and is contract-tested against "
            "lending_hub.featurestore.pit."
        )

    def get_online_features(self, entity_key, features):
        raise NotImplementedError("Track B: see get_historical_features")

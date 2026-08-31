"""Point-in-time correct feature joins.

Phase 0 WS-0.2.1 makes this the platform-level contract: "training datasets are
built *only* via ``get_historical_features`` point-in-time joins (kills future
leakage and training/serving skew at the platform level)". This module is the
Track A reference implementation of that join, and the definition of correct that
the Track B Feast adapter is tested against.

Two timestamps, not one
-----------------------
A point-in-time join is usually written as "take the latest feature value with
``event_timestamp <= observation_point``". That is not sufficient, and the
insufficiency is the single most expensive bug in credit modelling.

- ``event_timestamp`` — when the fact became true in the world.
- ``created_timestamp`` — when the platform actually learned it.

A bureau refresh dated 3 March that landed in the warehouse on 20 March was *not
knowable* on 10 March. Joining on ``event_timestamp`` alone hands the model a
value the production scorer could never have had, and the resulting AUC lift is
pure leakage that evaporates in shadow. So this join filters on both, and a
feature source that does not carry ``created_timestamp`` is rejected rather than
assumed to be simultaneous — see :class:`FeatureSource`.

Master §2 rule 2 names one reference implementation per algorithm: the semantics
here follow Feast's ``get_historical_features``, and the Track B adapter delegates
to Feast rather than reimplementing it.

Workstream: WS-0.2.1
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable, Sequence


class LeakageError(Exception):
    """Raised when a join would expose information from after the observation point.

    An exception rather than a filter: silently dropping the offending row would
    hide a broken upstream pipeline, and the value of this check is that it is
    loud.
    """


@dataclass(frozen=True, order=True)
class FeatureValue:
    """One observation of one feature for one entity.

    ``created_timestamp`` is mandatory. A source that cannot supply it cannot be
    joined point-in-time correctly, and defaulting it to ``event_timestamp``
    would silently assert zero ingestion lag — the exact assumption that produces
    leakage.
    """

    event_timestamp: datetime
    created_timestamp: datetime
    value: object = field(compare=False)

    def __post_init__(self) -> None:
        if self.created_timestamp < self.event_timestamp:
            raise ValueError(
                "created_timestamp precedes event_timestamp: the platform cannot "
                "have learned a fact before it was true. Check the source clock."
            )


@dataclass(frozen=True)
class FeatureSpec:
    """Declaration of one feature in the store.

    ``ttl`` is what stops a stale value being carried forward indefinitely. A
    bureau score from four years ago is not "the current bureau score", and a join
    that treats it as one produces a model that looks stable in backtest and
    degrades immediately in production.
    """

    name: str
    ttl: timedelta | None
    owner: str
    source_id: str
    description: str = ""

    def __post_init__(self) -> None:
        if self.ttl is not None and self.ttl <= timedelta(0):
            raise ValueError(f"{self.name}: ttl must be positive")


class FeatureSource:
    """Point-in-time queryable history for one feature, for one entity at a time.

    Values are held sorted by ``event_timestamp`` so the as-of lookup is a binary
    search rather than a scan — the same access pattern the offline store uses,
    kept here so the reference implementation stays honest about cost.
    """

    def __init__(self, spec: FeatureSpec):
        self.spec = spec
        self._by_entity: dict[str, list[FeatureValue]] = {}

    def add(self, entity_key: str, value: FeatureValue) -> None:
        bucket = self._by_entity.setdefault(entity_key, [])
        bucket.append(value)
        bucket.sort(key=lambda v: (v.event_timestamp, v.created_timestamp))

    def extend(self, entity_key: str, values: Iterable[FeatureValue]) -> None:
        for value in values:
            self.add(entity_key, value)

    def as_of(self, entity_key: str, observation_point: datetime) -> FeatureValue | None:
        """The value a production scorer would have seen at ``observation_point``.

        Selects the latest value that was both *true* and *known* by then, then
        applies the TTL. Ties on ``event_timestamp`` resolve to the latest
        ``created_timestamp`` — a correction that landed later is the better value.
        """
        history = self._by_entity.get(entity_key)
        if not history:
            return None

        cutoff = bisect_right(
            [v.event_timestamp for v in history], observation_point
        )
        candidate: FeatureValue | None = None
        for value in history[:cutoff]:
            # Knowability: the row must have existed in the warehouse by then.
            if value.created_timestamp > observation_point:
                continue
            if candidate is None or (
                value.event_timestamp,
                value.created_timestamp,
            ) >= (candidate.event_timestamp, candidate.created_timestamp):
                candidate = value

        if candidate is None:
            return None

        if self.spec.ttl is not None:
            if observation_point - candidate.event_timestamp > self.spec.ttl:
                return None

        return candidate


@dataclass(frozen=True)
class EntityRow:
    """One training/scoring row: an entity observed at a point in time.

    ``observation_point`` comes from ``lending_hub.definitions.observation_point``
    — the final-decision timestamp for application scoring, the snapshot month-end
    for behavioral. It is not a free parameter.
    """

    entity_key: str
    observation_point: datetime
    label: object = None


@dataclass
class JoinResult:
    """Joined rows plus the diagnostics that make the join reviewable."""

    rows: list[dict]
    missing: dict[str, int] = field(default_factory=dict)
    """feature name -> rows where no value was knowable at the observation point."""

    expired: dict[str, int] = field(default_factory=dict)
    """feature name -> rows where the only candidate value was past its TTL."""

    def coverage(self, feature: str, total: int | None = None) -> float | None:
        total = len(self.rows) if total is None else total
        if total == 0:
            return None
        return 1 - (self.missing.get(feature, 0) / total)


def get_historical_features(
    entity_rows: Sequence[EntityRow],
    sources: Sequence[FeatureSource],
    *,
    strict: bool = True,
) -> JoinResult:
    """Build a training dataset with point-in-time correct feature values.

    ``strict`` re-checks every returned value against the observation point and
    raises :class:`LeakageError` on a violation. It is on by default and costs
    almost nothing: the check exists because this is the one join in the platform
    whose failure mode is invisible in every offline metric.
    """
    result = JoinResult(rows=[])

    for entity_row in entity_rows:
        record: dict = {
            "entity_key": entity_row.entity_key,
            "observation_point": entity_row.observation_point,
        }
        if entity_row.label is not None:
            record["label"] = entity_row.label

        for source in sources:
            name = source.spec.name
            value = source.as_of(entity_row.entity_key, entity_row.observation_point)

            if value is None:
                record[name] = None
                latest_known = _latest_regardless_of_ttl(
                    source, entity_row.entity_key, entity_row.observation_point
                )
                bucket = result.expired if latest_known is not None else result.missing
                bucket[name] = bucket.get(name, 0) + 1
                continue

            if strict and (
                value.event_timestamp > entity_row.observation_point
                or value.created_timestamp > entity_row.observation_point
            ):
                raise LeakageError(
                    f"{name} for {entity_row.entity_key}: value "
                    f"(event={value.event_timestamp.isoformat()}, "
                    f"created={value.created_timestamp.isoformat()}) is not knowable at "
                    f"observation point {entity_row.observation_point.isoformat()}"
                )

            record[name] = value.value

        result.rows.append(record)

    return result


def _latest_regardless_of_ttl(
    source: FeatureSource, entity_key: str, observation_point: datetime
) -> FeatureValue | None:
    """Distinguish "never had a value" from "had one, but it went stale".

    The two need different fixes — a broken join versus a TTL that does not match
    the refresh cadence — and a single "missing" count conflates them.
    """
    history = source._by_entity.get(entity_key)  # noqa: SLF001 - same module contract
    if not history:
        return None
    knowable = [
        v
        for v in history
        if v.event_timestamp <= observation_point and v.created_timestamp <= observation_point
    ]
    return max(knowable, key=lambda v: (v.event_timestamp, v.created_timestamp), default=None)

"""Event-time velocity counters — the Flink reference implementation.

Phase 1 §4 WS-1.2 Step 2: "Applications per device / phone / address over
1h / 24h / 7d windows; event-time watermarks for late events; counters written to
the online feature store."

Why event time, and why it is not optional
------------------------------------------
Velocity is the highest-value cheap fraud signal there is: fifteen applications
from one device in an hour is not a coincidence. It is also the signal most
easily destroyed by using the wrong clock. A counter built on *processing* time
counts when the platform noticed, so a five-minute ingestion stall makes a burst
look like a trickle, and a replayed backlog makes an ordinary day look like an
attack. Both errors are invisible in the counter itself.

The two-timestamp rule applies here too
---------------------------------------
WS-0.2.1 established that a point-in-time join needs both when a fact became true
and when the platform learned it. A velocity counter is the same problem wearing
different clothes, and it is where training/serving skew is most often
manufactured: rebuilding history offline, every event is present, so the training
counter includes events that had not yet arrived when the decision was made. The
model learns from a counter production can never reproduce, and the lift
evaporates in shadow.

So :meth:`VelocityCounter.count` takes **both** cutoffs, and the ingestion cutoff
has no default. Passing only an event-time cutoff is the exact mistake, and a
default would make it the easy one.

Late events
-----------
An event arriving after the watermark has passed its window is *counted and
reported*, never silently dropped and never silently folded in. Dropping loses
fraud signal; folding it in changes a number a decision was already made on. The
counter keeps it and :attr:`VelocityCounter.late_events` says how much of the
history arrived too late to have influenced anything.

Workstream: WS-1.2 Step 2 · SRS §5.3.1, §9.3.1 · WS-0.2.1 (two-timestamp joins)
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Iterable, Sequence

#: Phase 1 §4 WS-1.2 Step 2 [SPEC]: "1h / 24h / 7d windows".
WINDOWS: dict[str, timedelta] = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
}

#: How far behind the newest event the watermark sits — the lateness the pipeline
#: tolerates before it declares a window complete. A *pipeline* parameter, not a
#: fraud threshold: it trades result latency against how many genuinely late
#: events still land inside their window, and the bank's own ingestion lag
#: distribution sets it. Stated as a default so it is visible and overridable.
DEFAULT_ALLOWED_LATENESS = timedelta(minutes=5)


class VelocityError(Exception):
    """The counter cannot answer as asked."""


class Dimension(str, Enum):
    """What the velocity is counted over. Phase 1 §4 WS-1.2 Step 2."""

    DEVICE = "device"
    PHONE = "phone"
    ADDRESS = "address"


@dataclass(frozen=True)
class ApplicationEvent:
    """One application arriving on the stream."""

    application_id: str
    key: str
    """The dimension value: a device id, normalised phone, or address geohash."""

    dimension: Dimension
    event_time: datetime
    """When the application was submitted — the fact's own clock."""

    ingest_time: datetime
    """When the platform received it. Never assumed equal to ``event_time``."""

    def __post_init__(self) -> None:
        if self.ingest_time < self.event_time:
            raise VelocityError(
                f"{self.application_id}: ingested at {self.ingest_time} before it "
                f"happened at {self.event_time}. This is a clock-skew defect, not a "
                "fast pipeline, and a negative lag corrupts every window it lands in."
            )

    @property
    def lag(self) -> timedelta:
        return self.ingest_time - self.event_time


@dataclass
class VelocityCounter:
    """Event-time windowed counts over one dimension.

    Holds ``(event_time, ingest_time)`` pairs per key, sorted by event time, so a
    count is two binary searches and a filter. The filter on ingestion is what
    keeps a rebuilt history honest — see the module docstring.
    """

    dimension: Dimension
    allowed_lateness: timedelta = DEFAULT_ALLOWED_LATENESS
    _events: dict[str, list[tuple[datetime, datetime]]] = field(default_factory=dict)
    watermark: datetime | None = None
    late_events: int = 0
    total_events: int = 0

    def ingest(self, event: ApplicationEvent) -> bool:
        """Add one event. Returns whether it arrived before its watermark.

        A False return is a signal, not an error: it means this event could not
        have influenced any decision made before now, so any counter that appeared
        to include it in a backtest was reading the future.
        """
        if event.dimension is not self.dimension:
            raise VelocityError(
                f"{event.dimension.value} event offered to a {self.dimension.value} counter"
            )

        self.total_events += 1
        on_time = self.watermark is None or event.event_time >= self.watermark
        if not on_time:
            self.late_events += 1

        bucket = self._events.setdefault(event.key, [])
        pair = (event.event_time, event.ingest_time)
        bucket.insert(bisect_right(bucket, pair), pair)

        candidate = event.event_time - self.allowed_lateness
        if self.watermark is None or candidate > self.watermark:
            # Watermarks only advance. A late event must not drag it backwards, or
            # windows already declared complete would reopen.
            self.watermark = candidate
        return on_time

    def ingest_all(self, events: Iterable[ApplicationEvent]) -> None:
        for event in events:
            self.ingest(event)

    def count(
        self,
        key: str,
        *,
        as_of_event_time: datetime,
        known_at: datetime,
        window: timedelta,
    ) -> int:
        """Events for ``key`` in ``[as_of − window, as_of]`` that had arrived by ``known_at``.

        ``known_at`` has no default. Omitting the ingestion filter is what makes a
        training counter unreproducible in production, and a default would make
        the wrong call the short one.
        """
        if window <= timedelta(0):
            raise VelocityError("a velocity window must be positive")
        if known_at < as_of_event_time:
            raise VelocityError(
                f"known_at {known_at} precedes the observation point "
                f"{as_of_event_time}: a decision cannot be made before its own "
                "observation point"
            )

        bucket = self._events.get(key)
        if not bucket:
            return 0

        # Bucket entries are (event_time, ingest_time) pairs sorted lexicographically,
        # so a sentinel ingest time of datetime.min/max brackets the whole event-time
        # range without materialising a parallel key list on every call.
        floor = datetime.min.replace(tzinfo=as_of_event_time.tzinfo)
        ceiling = datetime.max.replace(tzinfo=as_of_event_time.tzinfo)
        start = bisect_left(bucket, (as_of_event_time - window, floor))
        stop = bisect_right(bucket, (as_of_event_time, ceiling))
        return sum(
            1 for _, ingest_time in bucket[start:stop] if ingest_time <= known_at
        )

    def features(
        self, key: str, *, as_of_event_time: datetime, known_at: datetime
    ) -> dict[str, int]:
        """The online-feature-store row for one key: one count per named window."""
        return {
            f"velocity_{self.dimension.value}_{name}": self.count(
                key,
                as_of_event_time=as_of_event_time,
                known_at=known_at,
                window=window,
            )
            for name, window in WINDOWS.items()
        }

    def to_dict(self) -> dict:
        return {
            "dimension": self.dimension.value,
            "keys": len(self._events),
            "total_events": self.total_events,
            "late_events": self.late_events,
            "late_fraction": (
                self.late_events / self.total_events if self.total_events else None
            ),
            "watermark": self.watermark.isoformat() if self.watermark else None,
            "allowed_lateness_seconds": self.allowed_lateness.total_seconds(),
            "windows": sorted(WINDOWS),
        }


@dataclass
class VelocityFeatures:
    """All three dimensions together — what the scorer actually reads."""

    counters: dict[Dimension, VelocityCounter] = field(default_factory=dict)

    @classmethod
    def build(cls, allowed_lateness: timedelta = DEFAULT_ALLOWED_LATENESS):
        return cls(
            counters={
                dimension: VelocityCounter(dimension, allowed_lateness)
                for dimension in Dimension
            }
        )

    def ingest_all(self, events: Sequence[ApplicationEvent]) -> None:
        for event in events:
            self.counters[event.dimension].ingest(event)

    def for_application(
        self,
        keys: dict[Dimension, str],
        *,
        as_of_event_time: datetime,
        known_at: datetime,
    ) -> dict[str, int]:
        """Every velocity feature for one application.

        A dimension the application has no key for is *absent* from the result,
        not zero. "No device fingerprint captured" and "one application from this
        device" are different facts, and a zero merges the first into the second —
        which reads as the safest possible applicant.
        """
        out: dict[str, int] = {}
        for dimension, key in keys.items():
            if not key:
                continue
            out.update(
                self.counters[dimension].features(
                    key, as_of_event_time=as_of_event_time, known_at=known_at
                )
            )
        return out

    def to_dict(self) -> dict:
        return {
            dimension.value: counter.to_dict()
            for dimension, counter in sorted(
                self.counters.items(), key=lambda pair: pair[0].value
            )
        }


def skew_check(
    counter: VelocityCounter,
    key: str,
    *,
    as_of_event_time: datetime,
    known_at: datetime,
    window: timedelta,
) -> dict:
    """Compare the honest count with the one a single-timestamp pipeline produces.

    The offline number is what a training job computes when it has the whole
    history; the online number is what production could actually have seen. Their
    difference is training/serving skew measured directly rather than inferred
    from a metric drop weeks later — which is how it is usually found.
    """
    online = counter.count(
        key, as_of_event_time=as_of_event_time, known_at=known_at, window=window
    )
    offline = counter.count(
        key,
        as_of_event_time=as_of_event_time,
        known_at=datetime.max.replace(tzinfo=as_of_event_time.tzinfo),
        window=window,
    )
    return {
        "key": key,
        "online_count": online,
        "offline_count": offline,
        "skew": offline - online,
        "note": (
            "offline counts every event in the window; online counts only those "
            "that had arrived by the decision. A non-zero skew is the number of "
            "events a backtest would have used that production could not have."
        ),
    }

"""Stream freshness measurement.

Phase 0 WS-0.1.4 gate: source event to online feature in **< 60 s**, with a
dashboard. This computes the number the dashboard shows, from the two timestamps
every Phase 0 stream schema is required to carry.

Workstream: WS-0.1.4
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

#: Phase 0 WS-0.1.4 / §7 exit criteria: "stream freshness < 60 s". [SPEC]
FRESHNESS_GATE = timedelta(seconds=60)


@dataclass
class FreshnessReport:
    topic: str
    track: str
    lags_seconds: list[float] = field(default_factory=list)

    def observe(self, event_timestamp: datetime, materialised_at: datetime) -> None:
        """Record one event's source-to-online-feature lag."""
        if materialised_at < event_timestamp:
            raise ValueError(
                f"{self.topic}: materialised before the event occurred "
                f"({materialised_at.isoformat()} < {event_timestamp.isoformat()}); "
                "check producer and consumer clock sync before trusting freshness"
            )
        self.lags_seconds.append((materialised_at - event_timestamp).total_seconds())

    def percentile(self, p: float) -> float | None:
        """Nearest-rank percentile. None when nothing was observed."""
        if not self.lags_seconds:
            return None
        if not 0 < p <= 100:
            raise ValueError("percentile must be in (0, 100]")
        ordered = sorted(self.lags_seconds)
        rank = max(1, min(len(ordered), int(-(-p / 100 * len(ordered)) // 1)))
        return ordered[rank - 1]

    @property
    def p99(self) -> float | None:
        return self.percentile(99)

    @property
    def passed(self) -> bool:
        """A gate with nothing measured is not met.

        An empty window means the consumer is down or the topic is idle. Reporting
        that as "0 s lag, passing" is how a dead pipeline gets signed off.
        """
        p99 = self.p99
        return p99 is not None and p99 < FRESHNESS_GATE.total_seconds()

    def to_dict(self) -> dict:
        return {
            "topic": self.topic,
            "track": self.track,
            "observations": len(self.lags_seconds),
            "p50_seconds": self.percentile(50),
            "p95_seconds": self.percentile(95),
            "p99_seconds": self.p99,
            "max_seconds": max(self.lags_seconds) if self.lags_seconds else None,
            "gate_seconds": FRESHNESS_GATE.total_seconds(),
            "passed": self.passed,
        }

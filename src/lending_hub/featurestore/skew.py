"""Training/serving skew detection.

Phase 0 WS-0.2.1 makes Feast the single path to features precisely so that
training and serving cannot diverge. That contract still needs a test, because the
usual way skew appears is not two different feature stores — it is the same store
read two different ways, or an online value that was written late.

Workstream: WS-0.2.1
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SkewFinding:
    entity_key: str
    feature: str
    offline_value: object
    online_value: object
    observation_point: datetime

    def __str__(self) -> str:
        return (
            f"{self.feature}[{self.entity_key}] @ {self.observation_point.isoformat()}: "
            f"offline={self.offline_value!r} online={self.online_value!r}"
        )


@dataclass
class SkewReport:
    compared: int = 0
    findings: list[SkewFinding] = field(default_factory=list)
    missing_online: dict[str, int] = field(default_factory=dict)

    @property
    def skew_rate(self) -> float | None:
        """Fraction of comparisons that disagreed. None when nothing was compared."""
        if self.compared == 0:
            return None
        return len(self.findings) / self.compared

    def to_dict(self) -> dict:
        return {
            "compared": self.compared,
            "disagreements": len(self.findings),
            "skew_rate": self.skew_rate,
            "missing_online": dict(sorted(self.missing_online.items())),
            "sample": [str(f) for f in self.findings[:25]],
        }


def compare(
    offline_rows: list[dict],
    online_lookup,
    features: list[str],
) -> SkewReport:
    """Compare offline (training) values against the online store, row by row.

    ``online_lookup(entity_key, feature, observation_point)`` returns what the
    serving path would have returned. Any disagreement is a finding — including
    ``None`` on one side only, which is the most common real case and the easiest
    to wave away as "just missing data".
    """
    report = SkewReport()

    for row in offline_rows:
        entity_key = row["entity_key"]
        observation_point = row["observation_point"]
        for feature in features:
            offline_value = row.get(feature)
            online_value = online_lookup(entity_key, feature, observation_point)
            report.compared += 1

            if online_value is None and offline_value is not None:
                report.missing_online[feature] = report.missing_online.get(feature, 0) + 1

            if offline_value != online_value:
                report.findings.append(
                    SkewFinding(entity_key, feature, offline_value, online_value, observation_point)
                )

    return report

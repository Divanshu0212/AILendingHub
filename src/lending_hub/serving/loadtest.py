"""Serving-path load test.

Phase 0 WS-0.2.4 gates: p99 feature-fetch < 100 ms, p99 score < 500 ms, measured
with fixture keys only (Master §2 rule 3 — synthetic data in ``tests/fixtures/``).

Workstream: WS-0.2.4
"""

from __future__ import annotations

import argparse
import json
import pathlib
import statistics
from dataclasses import dataclass, field
from datetime import UTC, datetime

#: Phase 0 WS-0.2.4 gates [SPEC].
FEATURE_FETCH_P99_MS = 100.0
SCORE_P99_MS = 500.0


def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile; None on an empty sample."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, min(len(ordered), int(-(-p / 100 * len(ordered)) // 1)))
    return ordered[rank - 1]


@dataclass
class LoadTestResult:
    track: str
    requests: int = 0
    feature_fetch_ms: list[float] = field(default_factory=list)
    score_ms: list[float] = field(default_factory=list)
    total_ms: list[float] = field(default_factory=list)
    errors: int = 0

    def summary(self) -> dict:
        return {
            "track": self.track,
            "requests": self.requests,
            "errors": self.errors,
            "feature_fetch": _stats(self.feature_fetch_ms),
            "score": _stats(self.score_ms),
            "total": _stats(self.total_ms),
            "gates": {
                "feature_fetch_p99_ms": FEATURE_FETCH_P99_MS,
                "score_p99_ms": SCORE_P99_MS,
            },
            "passed": self.passed,
            "track_note": (
                "Track A measures an in-process path with no network, no online "
                "store and no serialisation. It bounds the platform's own overhead "
                "and is not evidence for the WS-0.2.4 gate (ADR-0003)."
                if self.track == "A"
                else "Track B: measured against the deployed serving path."
            ),
        }

    @property
    def passed(self) -> bool:
        """Nothing measured is not a pass, and any error fails outright."""
        fetch_p99 = percentile(self.feature_fetch_ms, 99)
        score_p99 = percentile(self.score_ms, 99)
        if fetch_p99 is None or score_p99 is None or self.errors:
            return False
        return fetch_p99 < FEATURE_FETCH_P99_MS and score_p99 < SCORE_P99_MS


def _stats(values: list[float]) -> dict:
    return {
        "n": len(values),
        "mean_ms": round(statistics.fmean(values), 4) if values else None,
        "p50_ms": percentile(values, 50),
        "p95_ms": percentile(values, 95),
        "p99_ms": percentile(values, 99),
        "max_ms": max(values) if values else None,
    }


def run(orchestrator, applications: list[dict]) -> LoadTestResult:
    result = LoadTestResult(track=getattr(orchestrator.feature_store, "track", "A"))
    for application in applications:
        try:
            response = orchestrator.decide(application)
        except Exception:  # noqa: BLE001 - a load test records failures, it does not raise
            result.errors += 1
            continue
        result.requests += 1
        result.feature_fetch_ms.append(response.timings.feature_fetch_ms)
        result.score_ms.append(response.timings.score_ms)
        result.total_ms.append(response.timings.total_ms)
    return result


def _fixture_harness(n: int):
    """Build a Track A orchestrator over fixture keys only (Master §2 rule 3)."""
    from datetime import timedelta

    from lending_hub.decisionlog import ModelRef
    from lending_hub.definitions import fingerprint
    from lending_hub.featurestore import FeatureSource, FeatureSpec, FeatureValue, LocalFeatureStore

    from .orchestrator import Orchestrator

    now = datetime.now(UTC)
    spec = FeatureSpec("repayments_30d", ttl=timedelta(days=30), owner="Credit DS", source_id="cbs")
    source = FeatureSource(spec)
    applications = []
    for i in range(n):
        token = f"tok-fixture-{i:05d}"
        source.add(token, FeatureValue(now - timedelta(days=1), now - timedelta(days=1), i % 7))
        applications.append(
            {"customer_token": token, "application_id": f"AP-FIXTURE-{i:05d}"}
        )

    store = LocalFeatureStore([source])
    model_ref = ModelRef(
        name="phase0_stub", version="0.0.0", registry_stage="None",
        code_commit="phase0", data_snapshot="fixtures", config_hash="none",
        definitions_fingerprint=fingerprint(),
    )
    orchestrator = Orchestrator(
        feature_store=store,
        scorer=lambda features: {"stub_score": 0.0},
        model_ref=model_ref,
        features=["repayments_30d"],
    )
    return orchestrator, applications


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=int, default=2000)
    parser.add_argument("--out", default="reports/loadtest.json")
    args = parser.parse_args(argv)

    orchestrator, applications = _fixture_harness(args.requests)
    result = run(orchestrator, applications)
    summary = result.summary()
    summary["generated_at"] = datetime.now(UTC).isoformat()

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(f"serving load test — track {result.track}, {result.requests} requests")
    for stage in ("feature_fetch", "score", "total"):
        s = summary[stage]
        print(f"  {stage:16} p50={s['p50_ms']:.4f}ms p95={s['p95_ms']:.4f}ms p99={s['p99_ms']:.4f}ms")
    print(f"  gates: feature p99 < {FEATURE_FETCH_P99_MS}ms, score p99 < {SCORE_P99_MS}ms")
    print(f"  {'PASS' if result.passed else 'FAIL'} · report written to {out}")
    print("\n  NOTE " + summary["track_note"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""WS-0.4 parity harness — proof-of-platform.

Phase 0 WS-0.4 rebuilds the bank's existing scorecard on-platform and requires
on-platform scores to match legacy decisioning for **>= 99.9%** of a frozen
12-month application sample, with every discrepancy root-caused in writing. The
phase doc is explicit that the exercise is "deliberately boring — it validates
joins, point-in-time logic, and the serving path before any new ML exists".

There is no legacy scorecard attached to this repository (LH-120), so the harness
is written around what the exercise actually tests rather than around the bank
system it happens to test it with: **two independently-built score paths over one
frozen sample must agree**.

* **Track B** — reference = legacy decisioning, candidate = on-platform rebuild.
  This is the WS-0.4 gate, and only this counts as gate evidence.
* **Track A** — reference = batch/training path (point-in-time join + model),
  candidate = online serving path. Same comparator, same discrepancy
  classification. It catches the specific defects WS-0.4 exists to catch —
  training/serving skew, a feature the online store lacks, a join that behaves
  differently under the two readers — before any bank data exists.

Track A parity is not a substitute for the WS-0.4 gate. It is the same test with
a different reference, and it makes the gate a rerun rather than a rewrite.

Workstream: WS-0.4
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Callable, Sequence

#: Phase 0 WS-0.4 / §7 exit criteria: ">= 99.9%" parity. [SPEC]
PARITY_GATE = 0.999


class Discrepancy(str, Enum):
    """Root-cause classes for a mismatch.

    WS-0.4 requires every discrepancy root-caused in writing. Classifying at
    comparison time is what makes that a report rather than a research project:
    a bare parity percentage tells nobody which of these is happening.
    """

    OUTCOME_DIFFERS = "outcome_differs"
    """Different decisions — the class that actually matters to a customer."""

    SCORE_DIFFERS = "score_differs"
    """Same outcome, different score. Usually rounding or feature drift; benign
    until the cutoff moves, then not."""

    MISSING_IN_CANDIDATE = "missing_in_candidate"
    """The platform produced nothing. Usually a join that dropped the row —
    exactly what this exercise is for."""

    MISSING_IN_REFERENCE = "missing_in_reference"
    """The reference produced nothing but the platform did. Often a sample
    definition mismatch rather than a defect, and worth separating for that
    reason."""

    ERROR = "error"
    """One path raised."""


@dataclass
class ParityCase:
    key: str
    kind: Discrepancy
    reference: object
    candidate: object
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "kind": self.kind.value,
            "reference": self.reference,
            "candidate": self.candidate,
            "detail": self.detail,
        }


@dataclass
class ParityReport:
    track: str
    reference_name: str
    candidate_name: str
    compared: int = 0
    agreed: int = 0
    cases: list[ParityCase] = field(default_factory=list)

    @property
    def parity(self) -> float | None:
        """None when nothing was compared — an empty sample proves nothing."""
        if self.compared == 0:
            return None
        return self.agreed / self.compared

    @property
    def passed(self) -> bool:
        parity = self.parity
        return parity is not None and parity >= PARITY_GATE

    def root_causes(self) -> dict[str, int]:
        return dict(sorted(Counter(c.kind.value for c in self.cases).items()))

    def to_dict(self) -> dict:
        return {
            "track": self.track,
            "reference": self.reference_name,
            "candidate": self.candidate_name,
            "compared": self.compared,
            "agreed": self.agreed,
            "parity": self.parity,
            "gate": PARITY_GATE,
            "passed": self.passed,
            "root_causes": self.root_causes(),
            "discrepancies": [c.to_dict() for c in self.cases[:100]],
            "discrepancies_total": len(self.cases),
            "track_note": (
                "Track A compares the batch path against the serving path. It is "
                "the same comparator as the WS-0.4 gate with a different reference, "
                "and is not gate evidence (ADR-0003)."
                if self.track == "A"
                else "Track B: on-platform rebuild versus legacy decisioning."
            ),
        }


def compare(
    sample: Sequence[dict],
    reference: Callable[[dict], dict | None],
    candidate: Callable[[dict], dict | None],
    *,
    track: str,
    reference_name: str,
    candidate_name: str,
    score_tolerance: float = 0.0,
) -> ParityReport:
    """Score one frozen sample through both paths and classify every difference.

    ``score_tolerance`` defaults to zero. WS-0.4 is a rebuild of the *same* logic,
    so a difference is a finding, not noise — a tolerance would absorb precisely
    the small feature-level divergence the exercise exists to surface.
    """
    report = ParityReport(track, reference_name, candidate_name)

    for row in sample:
        key = row.get("application_id") or row.get("key") or repr(row)
        report.compared += 1
        try:
            left = reference(row)
            right = candidate(row)
        except Exception as exc:  # noqa: BLE001 - a raising path is a finding
            report.cases.append(ParityCase(key, Discrepancy.ERROR, None, None, str(exc)))
            continue

        if right is None and left is not None:
            report.cases.append(
                ParityCase(key, Discrepancy.MISSING_IN_CANDIDATE, left, None,
                           "platform produced no result — check the join")
            )
            continue
        if left is None and right is not None:
            report.cases.append(
                ParityCase(key, Discrepancy.MISSING_IN_REFERENCE, None, right,
                           "reference produced no result — check the sample definition")
            )
            continue
        if left is None and right is None:
            report.agreed += 1
            continue

        if left.get("outcome") != right.get("outcome"):
            report.cases.append(
                ParityCase(key, Discrepancy.OUTCOME_DIFFERS,
                           left.get("outcome"), right.get("outcome"))
            )
            continue

        left_score, right_score = left.get("score"), right.get("score")
        if left_score is not None and right_score is not None:
            if abs(float(left_score) - float(right_score)) > score_tolerance:
                report.cases.append(
                    ParityCase(key, Discrepancy.SCORE_DIFFERS, left_score, right_score,
                               "same outcome, different score — benign until the cutoff moves")
                )
                continue

        report.agreed += 1

    return report


def _track_a_harness(n: int):
    """Batch path versus serving path over fixture keys."""
    from datetime import timedelta

    from lending_hub.featurestore import (
        EntityRow,
        FeatureSource,
        FeatureSpec,
        FeatureValue,
        LocalFeatureStore,
    )

    now = datetime.now(UTC)
    spec = FeatureSpec("repayments_30d", ttl=timedelta(days=90), owner="Credit DS", source_id="cbs")
    source = FeatureSource(spec)
    sample = []
    for i in range(n):
        token = f"tok-fixture-{i:05d}"
        source.add(token, FeatureValue(now - timedelta(days=2), now - timedelta(days=2), i % 7))
        sample.append({"application_id": f"AP-FIXTURE-{i:05d}", "customer_token": token})

    store = LocalFeatureStore([source])

    def score(value):
        return None if value is None else round(0.1 * float(value), 12)

    def batch_path(row):
        result = store.get_historical_features(
            [EntityRow(row["customer_token"], now)], ["repayments_30d"]
        )
        value = result.rows[0]["repayments_30d"]
        return {"outcome": "refer", "score": score(value)}

    def serving_path(row):
        value = store.get_online_features(row["customer_token"], ["repayments_30d"])[
            "repayments_30d"
        ]
        return {"outcome": "refer", "score": score(value)}

    return sample, batch_path, serving_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--track", choices=["A", "B"], default="A")
    parser.add_argument("--sample-size", type=int, default=1000)
    parser.add_argument("--out", default="reports/parity.json")
    args = parser.parse_args(argv)

    if args.track == "B":
        print(
            "Track B parity needs the frozen 12-month application sample and the "
            "legacy decisioning outputs (LH-120). Neither is available; nothing "
            "was compared.",
            file=sys.stderr,
        )
        return 2

    sample, reference, candidate = _track_a_harness(args.sample_size)
    report = compare(
        sample, reference, candidate,
        track="A", reference_name="batch_path", candidate_name="serving_path",
    )

    payload = report.to_dict()
    payload["generated_at"] = datetime.now(UTC).isoformat()
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    parity = report.parity
    print(f"parity harness — track {report.track}")
    print(f"  {report.reference_name} vs {report.candidate_name}")
    print(f"  compared {report.compared}, agreed {report.agreed}")
    print(f"  parity   {'n/a' if parity is None else f'{parity:.4%}'} (gate >= {PARITY_GATE:.1%})")
    if report.cases:
        print("  root causes:")
        for cause, count in report.root_causes().items():
            print(f"    {cause:24} {count}")
    print(f"  {'PASS' if report.passed else 'FAIL'} · report written to {out}")
    print("\n  NOTE " + payload["track_note"])
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

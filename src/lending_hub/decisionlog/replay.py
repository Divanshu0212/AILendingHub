"""Decision replay — the Master §3.3 gate spot-audit.

"Spot-audit at every gate: re-score a random sample of logged decisions from
stored features + registered model → identical outputs."

The audit is only meaningful if replay uses the *stored* feature values rather
than recomputing them. Recomputing would test whether the pipeline is
deterministic today; the duty is to show what the model did then, from what it saw
then. Those diverge the moment a feature definition changes, which is exactly when
an auditor asks.

Workstream: Master §3.3
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, Sequence

#: Tolerance for score comparison. Zero: a replay is a re-execution of the same
#: model on the same inputs, so anything other than an exact match means the
#: artifact, the features, or the log has changed. A tolerance here would hide
#: precisely the drift the audit exists to find.
SCORE_TOLERANCE = 0.0


@dataclass
class ReplayMismatch:
    decision_id: str
    field_name: str
    logged: object
    replayed: object

    def __str__(self) -> str:
        return (
            f"{self.decision_id}: {self.field_name} logged={self.logged!r} "
            f"replayed={self.replayed!r}"
        )


@dataclass
class ReplayReport:
    sampled: int = 0
    matched: int = 0
    mismatches: list[ReplayMismatch] = field(default_factory=list)
    unreplayable: list[str] = field(default_factory=list)
    """Decision ids whose model version is no longer resolvable in the registry —
    a distinct and more serious finding than a mismatch, because it means the
    8-year duty is already broken."""

    @property
    def match_rate(self) -> float | None:
        if self.sampled == 0:
            return None
        return self.matched / self.sampled

    @property
    def passed(self) -> bool:
        """A spot-audit with nothing sampled has demonstrated nothing."""
        return self.sampled > 0 and not self.mismatches and not self.unreplayable

    def to_dict(self) -> dict:
        return {
            "sampled": self.sampled,
            "matched": self.matched,
            "match_rate": self.match_rate,
            "mismatches": [str(m) for m in self.mismatches],
            "unreplayable": list(self.unreplayable),
            "passed": self.passed,
            "tolerance": SCORE_TOLERANCE,
        }


def spot_audit(
    entries: Sequence[dict],
    scorer: Callable[[dict, dict], dict],
    *,
    sample_size: int = 50,
    seed: int | None = None,
) -> ReplayReport:
    """Re-score a random sample of logged decisions and compare.

    ``scorer(model_ref, feature_values) -> {score_name: value}`` must load the
    exact registered model version named in the record. Raising
    :class:`LookupError` from it means that version can no longer be resolved,
    which is recorded as unreplayable rather than as a mismatch.
    """
    report = ReplayReport()
    if not entries:
        return report

    rng = random.Random(seed)
    sample = rng.sample(list(entries), min(sample_size, len(entries)))

    for entry in sample:
        report.sampled += 1
        decision_id = entry.get("decision_id", "<unknown>")
        models = entry.get("models") or []
        if not models:
            # A non-model decision (policy rule, fallback, human) has no score to
            # replay. It still has to be complete, which is checked elsewhere.
            report.matched += 1
            continue

        try:
            replayed = scorer(models[0], entry.get("feature_values", {}))
        except LookupError as exc:
            report.unreplayable.append(f"{decision_id}: {exc}")
            continue

        logged_scores = entry.get("scores", {})
        mismatched = False
        for name, logged_value in logged_scores.items():
            replayed_value = replayed.get(name)
            if not _equal(logged_value, replayed_value):
                report.mismatches.append(
                    ReplayMismatch(decision_id, f"scores.{name}", logged_value, replayed_value)
                )
                mismatched = True

        for name in set(replayed) - set(logged_scores):
            report.mismatches.append(
                ReplayMismatch(decision_id, f"scores.{name}", None, replayed[name])
            )
            mismatched = True

        if not mismatched:
            report.matched += 1

    return report


def _equal(logged: object, replayed: object) -> bool:
    if isinstance(logged, (int, float)) and isinstance(replayed, (int, float)):
        return abs(float(logged) - float(replayed)) <= SCORE_TOLERANCE
    return logged == replayed

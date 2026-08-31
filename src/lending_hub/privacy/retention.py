"""Per-table retention configuration.

Phase 0 WS-0.3.3 requires "per-table retention config [POLICY: DPO + Compliance]",
and Phase 0 §8 puts retention periods on the do-not-invent list. So this module
loads and validates a configuration it cannot supply: every period arrives as a
`[POLICY]` value or as a typed placeholder, and the loader refuses to default.

It does enforce one thing the bank cannot waive downwards — SRS CS-7 requires any
decision to be reconstructable for at least 8 years, so a retention period shorter
than that on a decision-carrying table is a configuration error, not a choice.

Workstream: WS-0.3.3
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass
from enum import Enum

from lending_hub.definitions.provenance import Pending

#: SRS §12 auditability / CS-7: "every decision reconstructable >= 8 years". [SPEC]
MINIMUM_DECISION_RETENTION_YEARS = 8


class Basis(str, Enum):
    """Why a table is retained for as long as it is."""

    REGULATORY = "regulatory"
    """An RBI/statutory duty. Overrides a DPDP erasure request (SRS §11.4)."""

    AUDIT = "audit"
    """SRS CS-7 decision reconstruction."""

    CONSENT = "consent"
    """Bounded by the consent artifact; erasure requests must be honoured."""

    OPERATIONAL = "operational"
    """Neither regulatory nor consent-bound; the shortest defensible period wins."""


@dataclass(frozen=True)
class RetentionRule:
    table: str
    period_years: int | Pending
    basis: Basis
    carries_decisions: bool = False
    erasable_on_request: bool = False
    note: str = ""

    @property
    def resolved(self) -> bool:
        return not isinstance(self.period_years, Pending)


class RetentionConfigError(Exception):
    pass


def validate(rules: list[RetentionRule]) -> list[str]:
    """Return configuration errors. Empty means the config is internally consistent.

    Note what this cannot check: whether a period is *correct*. That is a DPO and
    Compliance judgement (LH-111). What it checks is that the config does not
    contradict itself or the SRS.
    """
    errors: list[str] = []
    seen: set[str] = set()

    for rule in rules:
        if rule.table in seen:
            errors.append(f"{rule.table}: duplicate retention rule")
        seen.add(rule.table)

        if not rule.resolved:
            continue

        if rule.period_years <= 0:
            errors.append(f"{rule.table}: retention period must be positive")

        if rule.carries_decisions and rule.period_years < MINIMUM_DECISION_RETENTION_YEARS:
            errors.append(
                f"{rule.table}: {rule.period_years}y is below the SRS CS-7 floor of "
                f"{MINIMUM_DECISION_RETENTION_YEARS}y for a table carrying decisions"
            )

        if rule.basis is Basis.REGULATORY and rule.erasable_on_request:
            errors.append(
                f"{rule.table}: a regulatory retention duty cannot also be erasable "
                "on request; SRS §11.4 makes the duty the override, so the flags "
                "contradict each other"
            )

    return errors


def unresolved(rules: list[RetentionRule]) -> list[RetentionRule]:
    return [r for r in rules if not r.resolved]


def load(path: pathlib.Path | str) -> list[RetentionRule]:
    """Load ``config/retention.yaml``.

    A missing or unparseable period becomes a :class:`Pending` placeholder rather
    than a default. There is no safe default for a retention period: too short
    destroys audit evidence, too long is a DPDP violation.
    """
    try:
        import yaml
    except ModuleNotFoundError as exc:  # pragma: no cover - environment dependent
        raise RetentionConfigError(
            "PyYAML is needed to read the retention config: "
            "pip install -r requirements-dev.txt"
        ) from exc

    doc = yaml.safe_load(pathlib.Path(path).read_text(encoding="utf-8")) or {}
    rules: list[RetentionRule] = []

    for table, entry in (doc.get("tables") or {}).items():
        raw_period = entry.get("period_years")
        if isinstance(raw_period, int):
            period: int | Pending = raw_period
        else:
            parsed = Pending.parse(str(raw_period)) if raw_period else None
            if parsed is None:
                raise RetentionConfigError(
                    f"{table}: period_years must be an integer or a well-formed "
                    f"TBD[<owner>, <TICKET-N>], got {raw_period!r}"
                )
            period = parsed

        try:
            basis = Basis(entry["basis"])
        except (KeyError, ValueError) as exc:
            raise RetentionConfigError(
                f"{table}: basis must be one of {[b.value for b in Basis]}"
            ) from exc

        rules.append(
            RetentionRule(
                table=table,
                period_years=period,
                basis=basis,
                carries_decisions=bool(entry.get("carries_decisions", False)),
                erasable_on_request=bool(entry.get("erasable_on_request", False)),
                note=entry.get("note", ""),
            )
        )

    return rules

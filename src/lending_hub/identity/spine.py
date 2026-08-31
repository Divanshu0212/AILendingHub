"""The identity spine: deterministic keys joined across CBS, LOS and collections.

Phase 0 WS-0.1.3 states the audit target as ">= 99.5% of active loans join across
the three systems on exact keys". Taken literally that metric is wrong, and wrong
in a way that would quietly pass: **a healthy loan has no collections record**.
Requiring all three systems to match for every active loan makes the measured
"join rate" approximately the delinquency rate, so a portfolio in good health
would fail the gate and a deteriorating one would appear to improve.

The join is therefore decomposed into the three checks the target was reaching for,
each with a direction that is actually mandatory:

===============================  =========================================
``loan_to_application``          every active CBS loan traces to an
                                 originating LOS application  (mandatory)
``collections_to_loan``          every collections case resolves to a CBS
                                 loan  (mandatory, referential integrity)
``customer_consistency``         the customer key on a loan agrees across
                                 every system that carries it  (mandatory)
===============================  =========================================

Raised as **LH-122** against Phase 0 §WS-0.1.3 rather than reinterpreted silently
(Master §1: conflicts become tickets).

Workstream: WS-0.1.3
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import Enum

from .keys import Entity, KeyProblem, RejectedKey, SpineKey, normalise
from .ports import SPINE_KEY_COLUMNS, SourceReader


class FailureCause(str, Enum):
    """Root causes a join failure is attributed to.

    WS-0.1.3 requires failures to be "root-caused in a written report". A bare
    percentage tells an engineer nothing about what to fix, so the audit
    classifies every failing record as it counts it.
    """

    MISSING_APPLICATION = "missing_application"
    """Active loan with no LOS application. Usually a migrated legacy loan whose
    origination predates the LOS, or a manually booked account."""

    ORPHAN_COLLECTIONS_CASE = "orphan_collections_case"
    """Collections case whose loan key is absent from CBS — a genuine referential
    integrity break, or a case opened against a written-off loan CBS has purged."""

    CUSTOMER_DISAGREEMENT = "customer_disagreement"
    """Same loan, different customer key across systems. Either a key reuse bug or
    a real re-assignment; both need a decision before the spine is trusted."""

    UNUSABLE_KEY = "unusable_key"
    """The key itself could not be normalised — see :class:`KeyProblem` for which
    of null / placeholder / charset / truncation it was."""


@dataclass
class SpineRecord:
    """One loan's presence across the three spine systems."""

    loan: SpineKey
    customer_by_source: dict[str, str] = field(default_factory=dict)
    present_in: set[str] = field(default_factory=set)
    application: SpineKey | None = None
    cases: list[SpineKey] = field(default_factory=list)


@dataclass
class Failure:
    """One record that did not join, with its cause."""

    cause: FailureCause
    source_id: str
    key: str | None
    detail: str


@dataclass
class SpineAudit:
    """Result of building the spine — the WS-0.1.3 written report, as data."""

    track: str
    loans_in_cbs: int = 0
    loans_with_application: int = 0
    collections_cases: int = 0
    collections_cases_resolved: int = 0
    loans_with_consistent_customer: int = 0
    loans_with_customer_evidence: int = 0
    failures: list[Failure] = field(default_factory=list)
    rejected_keys: Counter = field(default_factory=Counter)

    @property
    def loan_to_application_rate(self) -> float | None:
        return _rate(self.loans_with_application, self.loans_in_cbs)

    @property
    def collections_to_loan_rate(self) -> float | None:
        return _rate(self.collections_cases_resolved, self.collections_cases)

    @property
    def customer_consistency_rate(self) -> float | None:
        return _rate(self.loans_with_consistent_customer, self.loans_with_customer_evidence)

    def causes(self) -> dict[str, int]:
        counts: Counter = Counter(f.cause.value for f in self.failures)
        return dict(sorted(counts.items()))

    def to_dict(self) -> dict:
        return {
            "track": self.track,
            "track_note": (
                "Track A numbers describe the audit script, not the portfolio. "
                "Only Track B output is Phase 0 gate evidence (ADR-0003)."
                if self.track == "A"
                else "Track B: computed from source data."
            ),
            "counts": {
                "loans_in_cbs": self.loans_in_cbs,
                "loans_with_application": self.loans_with_application,
                "collections_cases": self.collections_cases,
                "collections_cases_resolved": self.collections_cases_resolved,
                "loans_with_customer_evidence": self.loans_with_customer_evidence,
                "loans_with_consistent_customer": self.loans_with_consistent_customer,
            },
            "rates": {
                "loan_to_application": self.loan_to_application_rate,
                "collections_to_loan": self.collections_to_loan_rate,
                "customer_consistency": self.customer_consistency_rate,
            },
            "root_causes": self.causes(),
            "rejected_keys": dict(sorted(self.rejected_keys.items())),
            "failures_sample": [
                {
                    "cause": f.cause.value,
                    "source": f.source_id,
                    "key": f.key,
                    "detail": f.detail,
                }
                for f in self.failures[:50]
            ],
            "failures_total": len(self.failures),
        }


def _rate(numerator: int, denominator: int) -> float | None:
    """Return None on an empty denominator — an empty portfolio is not 100% joined."""
    if denominator == 0:
        return None
    return numerator / denominator


def _key(record: dict, source_id: str, entity: Entity):
    column = SPINE_KEY_COLUMNS[source_id].get(entity)
    if column is None:
        return None
    return normalise(entity, record.get(column))


def build_spine(
    cbs: SourceReader, los: SourceReader, collections: SourceReader
) -> tuple[dict[str, SpineRecord], SpineAudit]:
    """Join the three systems on exact normalised keys and audit the result.

    Only *active* CBS loans form the denominator, per WS-0.1.3. ``is_active`` is
    read from the CBS extract rather than derived here: deciding what counts as
    active is a portfolio definition, not a join concern.
    """
    tracks = {cbs.track, los.track, collections.track}
    audit = SpineAudit(track="/".join(sorted(tracks)) if len(tracks) > 1 else tracks.pop())

    spine: dict[str, SpineRecord] = {}

    for row in cbs.records():
        if str(row.get("is_active", "true")).strip().lower() not in ("true", "1", "y", "yes"):
            continue
        loan = _key(row, "cbs", Entity.LOAN)
        if isinstance(loan, RejectedKey):
            audit.rejected_keys[f"cbs.{loan.problem.value}"] += 1
            audit.failures.append(
                Failure(FailureCause.UNUSABLE_KEY, "cbs", loan.raw,
                        f"loan_id rejected: {loan.problem.value}")
            )
            continue

        audit.loans_in_cbs += 1
        record = spine.setdefault(loan.value, SpineRecord(loan=loan))
        record.present_in.add("cbs")
        customer = _key(row, "cbs", Entity.CUSTOMER)
        if isinstance(customer, SpineKey):
            record.customer_by_source["cbs"] = customer.value
        elif isinstance(customer, RejectedKey):
            audit.rejected_keys[f"cbs.customer.{customer.problem.value}"] += 1

    for row in los.records():
        loan = _key(row, "los", Entity.LOAN)
        if isinstance(loan, RejectedKey):
            audit.rejected_keys[f"los.{loan.problem.value}"] += 1
            continue
        record = spine.get(loan.value)
        if record is None:
            # An LOS application for a loan CBS does not carry as active: a
            # declined or not-yet-disbursed application. Not a failure — the
            # mandatory direction is CBS -> LOS, not the reverse.
            continue
        record.present_in.add("los")
        application = _key(row, "los", Entity.APPLICATION)
        if isinstance(application, SpineKey):
            record.application = application
        customer = _key(row, "los", Entity.CUSTOMER)
        if isinstance(customer, SpineKey):
            record.customer_by_source["los"] = customer.value

    for row in collections.records():
        audit.collections_cases += 1
        loan = _key(row, "collections", Entity.LOAN)
        if isinstance(loan, RejectedKey):
            audit.rejected_keys[f"collections.{loan.problem.value}"] += 1
            audit.failures.append(
                Failure(FailureCause.UNUSABLE_KEY, "collections", loan.raw,
                        f"loan_id rejected: {loan.problem.value}")
            )
            continue
        record = spine.get(loan.value)
        if record is None:
            audit.failures.append(
                Failure(FailureCause.ORPHAN_COLLECTIONS_CASE, "collections", loan.value,
                        "collections case does not resolve to an active CBS loan")
            )
            continue
        audit.collections_cases_resolved += 1
        record.present_in.add("collections")
        case = _key(row, "collections", Entity.CASE)
        if isinstance(case, SpineKey):
            record.cases.append(case)
        customer = _key(row, "collections", Entity.CUSTOMER)
        if isinstance(customer, SpineKey):
            record.customer_by_source["collections"] = customer.value

    for record in spine.values():
        if record.application is not None:
            audit.loans_with_application += 1
        else:
            audit.failures.append(
                Failure(FailureCause.MISSING_APPLICATION, "cbs", record.loan.value,
                        "active loan has no originating LOS application")
            )

        customers = set(record.customer_by_source.values())
        if len(record.customer_by_source) >= 2:
            audit.loans_with_customer_evidence += 1
            if len(customers) == 1:
                audit.loans_with_consistent_customer += 1
            else:
                audit.failures.append(
                    Failure(
                        FailureCause.CUSTOMER_DISAGREEMENT, "spine", record.loan.value,
                        "customer_id differs across systems: "
                        + ", ".join(f"{s}={v}" for s, v in sorted(record.customer_by_source.items())),
                    )
                )

    return spine, audit

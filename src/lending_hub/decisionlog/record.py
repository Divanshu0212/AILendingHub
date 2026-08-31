"""The decision record — what every automated decision stores.

Master §3.3: "Every automated decision stores: inputs, feature values, model
versions, scores, reason codes, rule/policy provenance, and any human override —
reproducible for >= 8 years (SRS CS-7)."

The design constraint that shapes this module is the eight years. A record has to
be replayable by someone who has none of today's context: not the code, not the
config, not the person who wrote it. So the record carries its own provenance —
model version, definitions fingerprint, feature-store dataset version, policy
version — rather than referring to "the current" anything.

Workstream: Master §3.3 · SRS §12 auditability
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Outcome(str, Enum):
    APPROVE = "approve"
    DECLINE = "decline"
    REFER = "refer"
    """Routed to a human underwriter with the full evidence pack (SRS §2.3 step 6)."""


class Actor(str, Enum):
    MODEL = "model"
    POLICY_RULE = "policy_rule"
    """The BRE overrode the model. SRS §2.2: policy rules always take precedence."""

    HUMAN = "human"
    FALLBACK = "fallback"
    """The AI path was unavailable and the previous decisioning path decided
    (SRS §12 availability)."""


@dataclass(frozen=True)
class ModelRef:
    """Exactly which model produced a score."""

    name: str
    version: str
    registry_stage: str
    code_commit: str
    data_snapshot: str
    config_hash: str
    definitions_fingerprint: str
    """Appendix A content hash at training time. When Appendix A changes, this is
    what identifies which decisions were made under the old definitions."""

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass(frozen=True)
class ReasonCode:
    """One adverse-action / explanation reason.

    ``wording`` is deliberately absent. Reason-code *wording* is `[POLICY]` in
    every phase from P1 onward, and a record that stores rendered text freezes a
    sentence nobody approved. The code is stored; the wording is looked up from
    the versioned template at render time.
    """

    code: str
    contribution: float | None = None
    source: str = "model"


@dataclass(frozen=True)
class DecisionRecord:
    """One immutable decision, reconstructable without any surrounding context."""

    decision_id: str
    decided_at: datetime
    subject_token: str
    """Tokenized customer identifier — the log never holds raw PII (SRS §11.4)."""

    application_id: str
    outcome: Outcome
    decided_by: Actor
    inputs: dict
    feature_values: dict
    models: list[ModelRef]
    scores: dict
    reason_codes: list[ReasonCode] = field(default_factory=list)
    policy_version: str = ""
    rules_fired: list[str] = field(default_factory=list)
    consent_ids: list[str] = field(default_factory=list)
    override: dict | None = None
    """Set when a human changed the automated outcome: who, when, why, and the
    outcome that was replaced."""

    feature_dataset_version: str = ""
    prev_hash: str | None = None

    def __post_init__(self) -> None:
        if not self.models and self.decided_by is Actor.MODEL:
            raise ValueError("a model decision must record which models produced it")
        if self.decided_by is Actor.HUMAN and not self.override:
            raise ValueError(
                "a human decision must record the override: who, when, why, and what "
                "outcome it replaced"
            )
        if not self.policy_version:
            raise ValueError(
                "policy_version is required: without it nobody can tell years later "
                "which rule set was in force"
            )

    def to_dict(self) -> dict:
        return {
            "decision_id": self.decision_id,
            "decided_at": self.decided_at.isoformat(),
            "subject_token": self.subject_token,
            "application_id": self.application_id,
            "outcome": self.outcome.value,
            "decided_by": self.decided_by.value,
            "inputs": self.inputs,
            "feature_values": self.feature_values,
            "models": [m.to_dict() for m in self.models],
            "scores": self.scores,
            "reason_codes": [
                {"code": r.code, "contribution": r.contribution, "source": r.source}
                for r in self.reason_codes
            ],
            "policy_version": self.policy_version,
            "rules_fired": list(self.rules_fired),
            "consent_ids": list(self.consent_ids),
            "override": self.override,
            "feature_dataset_version": self.feature_dataset_version,
            "prev_hash": self.prev_hash,
        }

    def content_hash(self) -> str:
        """Stable hash of the record's content, including ``prev_hash``.

        Chaining each record to its predecessor makes the log tamper-evident: an
        edited or removed record breaks every hash after it. Cheap to compute,
        and it turns "the log says so" into something a validator can verify
        rather than trust.
        """
        blob = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

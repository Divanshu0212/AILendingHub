"""DPDP consent artifacts.

SRS §11.4: "purpose-limited consent for alternative data (AA, telco, location);
consent artifacts stored with the decision record". Phase 0 WS-0.3.3 requires the
schema.

Purpose limitation is the whole point and the part most often lost in
implementation: consent collected to assess a loan application does not authorise
using the same data to train a model, market a product, or score a different
application two years later. So :meth:`ConsentArtifact.permits` takes a purpose
and a time, and there is no way to ask "is this consent valid?" without both.

Workstream: WS-0.3.3
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Purpose(str, Enum):
    """Purposes a consent artifact can grant.

    The list is deliberately narrow. Adding one is a Compliance decision
    (**LH-112**), because each entry is a statement about what the customer was
    told — and the wording they were shown is what the purpose actually means.
    """

    CREDIT_ASSESSMENT = "credit_assessment"
    FRAUD_PREVENTION = "fraud_prevention"
    MODEL_TRAINING = "model_training"
    PORTFOLIO_MONITORING = "portfolio_monitoring"


class DataCategory(str, Enum):
    BANK_STATEMENTS = "bank_statements"
    BUREAU = "bureau"
    TELCO = "telco"
    LOCATION = "location"
    DEVICE = "device"


class ConsentError(Exception):
    pass


@dataclass(frozen=True)
class ConsentArtifact:
    """One consent, as stored alongside the decision record.

    ``notice_version`` binds the artifact to the exact wording shown. Without it a
    consent record proves only that a box was ticked, not what it said — which is
    precisely what a regulator asks for.
    """

    consent_id: str
    customer_token: str
    purposes: frozenset[Purpose]
    categories: frozenset[DataCategory]
    granted_at: datetime
    expires_at: datetime | None
    notice_version: str
    revoked_at: datetime | None = None
    source_id: str = "account_aggregator"
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.purposes:
            raise ConsentError("a consent artifact with no purpose grants nothing")
        if not self.categories:
            raise ConsentError("a consent artifact must name the data categories it covers")
        if not self.notice_version:
            raise ConsentError(
                "notice_version is required: a consent record without the wording "
                "shown proves only that a box was ticked"
            )
        if self.expires_at is not None and self.expires_at <= self.granted_at:
            raise ConsentError("expires_at must be after granted_at")
        if self.revoked_at is not None and self.revoked_at < self.granted_at:
            raise ConsentError("revoked_at precedes granted_at")

    def permits(
        self, purpose: Purpose, category: DataCategory, at: datetime
    ) -> bool:
        """Whether this artifact authorises ``purpose`` on ``category`` at ``at``.

        Evaluated as of a time, not "now", so a decision replayed years later is
        judged against the consent that was in force when the decision was made —
        which is what Master §3.3 reproducibility requires.
        """
        if purpose not in self.purposes or category not in self.categories:
            return False
        if at < self.granted_at:
            return False
        if self.expires_at is not None and at >= self.expires_at:
            return False
        if self.revoked_at is not None and at >= self.revoked_at:
            return False
        return True

    def require(self, purpose: Purpose, category: DataCategory, at: datetime) -> None:
        """Raise unless permitted. For call sites where proceeding is not an option."""
        if not self.permits(purpose, category, at):
            raise ConsentError(
                f"consent {self.consent_id} does not permit {purpose.value} on "
                f"{category.value} at {at.isoformat()}"
            )

    def to_dict(self) -> dict:
        return {
            "consent_id": self.consent_id,
            "customer_token": self.customer_token,
            "purposes": sorted(p.value for p in self.purposes),
            "categories": sorted(c.value for c in self.categories),
            "granted_at": self.granted_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "notice_version": self.notice_version,
            "source_id": self.source_id,
            "metadata": self.metadata,
        }

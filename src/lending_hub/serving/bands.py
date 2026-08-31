"""Policy bands as dual-control config — cutoffs that are not code constants.

Phase 1 §5.2: "Cutoffs and review-band edges are orchestrator *config* with
dual-control change approval — never code constants."

That is a governance requirement with a technical consequence, and the
consequence is the whole reason for this module. **A cutoff in code cannot be
changed under dual control.** Changing it is a deployment, so the approval that
actually governs it is the one on the pull request — reviewed by whoever was
free, under a process designed for code quality rather than for credit risk. Two
committee members signing a config change is a different control from two
engineers approving a diff, and only one of them is what Phase 1 asks for.

So the bands live in ``config/policy_bands.yaml``, carry their own approvals,
hash to their own version, and that version goes into every decision record.

Everything here is a placeholder
--------------------------------
Approve/decline cutoffs, review-band edges and the canary percentage are all
`[POLICY: Credit Risk Committee]` (LH-204). :meth:`BandConfig.outcome_for` raises
until they exist, which leaves the orchestrator referring every scored
application to a human — the only honest behaviour for a platform with no
approved decision boundary.

Workstream: WS-1.1 / Phase 1 §5 · SRS §2.2 (policy precedence), §11.2
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Sequence

from lending_hub.decisionlog import Outcome
from lending_hub.definitions import Pending, Ungrounded

DEFAULT_BANDS = pathlib.Path("config/policy_bands.yaml")

#: Phase 1 §5.2 [SPEC]: dual control means two people, and they must be different
#: people. One person approving twice is not a second pair of eyes; it is the
#: same pair, and the control that catches a fat-fingered cutoff is the second
#: person, not the second signature.
REQUIRED_APPROVERS = 2


class BandConfigError(Exception):
    """The band configuration is not usable as written."""


@dataclass(frozen=True)
class Approval:
    approver: str
    role: str
    approved_at: datetime

    def to_dict(self) -> dict:
        return {
            "approver": self.approver,
            "role": self.role,
            "approved_at": self.approved_at.isoformat(),
        }


@dataclass
class BandConfig:
    """Loaded cutoffs, canary settings and approvals for one model."""

    model: str
    owner: str
    status: str
    approve_below: Pending | float
    decline_above: Pending | float
    canary_percentage: Pending | float
    canary_band_low: Pending | float
    canary_band_high: Pending | float
    approvals: list[Approval] = field(default_factory=list)
    source_path: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.approve_below, Pending) and not isinstance(
            self.decline_above, Pending
        ):
            if self.approve_below >= self.decline_above:
                raise BandConfigError(
                    f"approve_below ({self.approve_below}) must be strictly less than "
                    f"decline_above ({self.decline_above}); otherwise there is no "
                    "review band and the two cutoffs contradict each other"
                )

    @property
    def grounded(self) -> bool:
        return not any(
            isinstance(value, Pending)
            for value in (self.approve_below, self.decline_above)
        )

    @property
    def distinct_approvers(self) -> int:
        return len({approval.approver for approval in self.approvals})

    @property
    def dual_control_satisfied(self) -> bool:
        return self.distinct_approvers >= REQUIRED_APPROVERS

    @property
    def effective(self) -> bool:
        """Whether this config may decide anything."""
        return self.grounded and self.dual_control_satisfied

    def version(self) -> str:
        """Content hash over the values *and* the approvals.

        Approvals are inside the hash on purpose: a config re-approved by
        different people is a different governance object even when the numbers
        are identical, and a decision record naming only the numbers could not
        show who authorised them.
        """
        payload = {
            "model": self.model,
            "approve_below": str(self.approve_below),
            "decline_above": str(self.decline_above),
            "canary_percentage": str(self.canary_percentage),
            "canary_band_low": str(self.canary_band_low),
            "canary_band_high": str(self.canary_band_high),
            "approvals": [a.to_dict() for a in sorted(
                self.approvals, key=lambda a: (a.approver, a.approved_at)
            )],
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    def outcome_for(self, probability_of_default: float) -> Outcome:
        """Map a calibrated PD to an outcome. Raises while the cutoffs are `[POLICY]`."""
        if not self.grounded:
            raise Ungrounded(
                f"{self.approve_below} — no approve/decline cutoffs are configured. "
                "Phase 1 §8 puts them on the do-not-invent list; until the Credit "
                "Risk Committee supplies them every scored application is referred "
                "to a human."
            )
        if not self.dual_control_satisfied:
            raise BandConfigError(
                f"{self.model}: band config has {self.distinct_approvers} distinct "
                f"approver(s), needs {REQUIRED_APPROVERS}. Dual control is what "
                "catches a mistyped cutoff before it reaches traffic."
            )
        if not 0.0 <= probability_of_default <= 1.0:
            raise BandConfigError("probability of default must be in [0, 1]")

        if probability_of_default <= self.approve_below:
            return Outcome.APPROVE
        if probability_of_default >= self.decline_above:
            return Outcome.DECLINE
        return Outcome.REFER

    def in_canary_band(self, probability_of_default: float) -> bool:
        """Phase 1 §5.2: the challenger applies to mid-score bands only."""
        if isinstance(self.canary_band_low, Pending) or isinstance(
            self.canary_band_high, Pending
        ):
            return False
        return self.canary_band_low <= probability_of_default <= self.canary_band_high

    def unresolved(self) -> list[str]:
        return sorted(
            name
            for name, value in (
                ("approve_below", self.approve_below),
                ("decline_above", self.decline_above),
                ("canary_percentage", self.canary_percentage),
                ("canary_band_low", self.canary_band_low),
                ("canary_band_high", self.canary_band_high),
            )
            if isinstance(value, Pending)
        )

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "owner": self.owner,
            "status": self.status,
            "version": self.version(),
            "grounded": self.grounded,
            "dual_control_satisfied": self.dual_control_satisfied,
            "distinct_approvers": self.distinct_approvers,
            "effective": self.effective,
            "unresolved": self.unresolved(),
            "approvals": [a.to_dict() for a in self.approvals],
        }


def _value(raw) -> Pending | float:
    pending = Pending.parse(str(raw))
    if pending is not None:
        return pending
    try:
        return float(raw)
    except (TypeError, ValueError) as exc:
        raise BandConfigError(
            f"{raw!r} is neither a number nor a TBD[owner, ticket] placeholder. A "
            "band edge has to be one or the other — anything else is a value with "
            "no provenance."
        ) from exc


def load_bands(path: str | pathlib.Path = DEFAULT_BANDS) -> BandConfig:
    """Load and validate the band configuration."""
    path = pathlib.Path(path)
    if not path.exists():
        raise BandConfigError(f"band config not found: {path}")

    try:
        import yaml
    except ModuleNotFoundError as exc:  # pragma: no cover - environment dependent
        raise BandConfigError(
            "PyYAML is needed to read the band config: "
            "pip install -r requirements-dev.txt"
        ) from exc

    with path.open("r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle)

    if not isinstance(document, dict):
        raise BandConfigError(f"{path}: expected a mapping at the top level")

    cutoffs = document.get("cutoffs") or {}
    canary = document.get("canary") or {}
    for field_name in ("approve_below", "decline_above"):
        if field_name not in cutoffs:
            raise BandConfigError(f"{path}: cutoffs.{field_name} is missing")

    approvals = []
    for index, raw in enumerate(document.get("approvals") or []):
        if not isinstance(raw, dict):
            raise BandConfigError(f"{path}: approvals[{index}] is not a mapping")
        for required in ("approver", "role", "approved_at"):
            if not raw.get(required):
                raise BandConfigError(f"{path}: approvals[{index}] is missing {required!r}")
        approvals.append(
            Approval(
                approver=str(raw["approver"]),
                role=str(raw["role"]),
                approved_at=datetime.fromisoformat(str(raw["approved_at"])),
            )
        )

    return BandConfig(
        model=document.get("model", ""),
        owner=document.get("owner", ""),
        status=document.get("status", ""),
        approve_below=_value(cutoffs["approve_below"]),
        decline_above=_value(cutoffs["decline_above"]),
        canary_percentage=_value(canary.get("traffic_percentage", "TBD[Credit Risk Committee, LH-204]")),
        canary_band_low=_value(canary.get("score_band_low", "TBD[Credit Risk Committee, LH-204]")),
        canary_band_high=_value(canary.get("score_band_high", "TBD[Credit Risk Committee, LH-204]")),
        approvals=approvals,
        source_path=str(path),
    )


def canary_assignment(application_id: str, config: BandConfig) -> bool:
    """Whether this application is in the canary slice.

    Assignment is a stable hash of the application id, not a random draw. A
    coin flip would move an applicant between arms on a retry or a re-submission,
    which corrupts the comparison and — worse — can hand the same person two
    different decisions on the same day.
    """
    if isinstance(config.canary_percentage, Pending):
        return False
    if not 0.0 <= config.canary_percentage <= 100.0:
        raise BandConfigError("canary percentage must be between 0 and 100")
    digest = hashlib.sha256(application_id.encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) % 10_000
    return bucket < config.canary_percentage * 100

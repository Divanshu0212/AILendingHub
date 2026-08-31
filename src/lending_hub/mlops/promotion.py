"""Registry promotion gate.

Phase 0 WS-0.2.2: stage moves happen "only via CI pipelines — direct UI/manual
promotion disabled". Master §3.2 adds the fixed rules of the shipping ladder:
shadow >= 4 weeks, the previous path stays warm, promotion and rollback only via
CI against the registry.

This module is where those rules stop being prose. Every reason a promotion can
be refused is returned as a list rather than raised one at a time, so a team
learns everything blocking them in one run instead of one condition per attempt.

Workstream: WS-0.2.2 · Master §3.2
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from lending_hub.definitions import fingerprint

from .artifact import ModelArtifact, Stage

#: Master §3.2: "shadow >= 4 weeks". [SPEC]
MINIMUM_SHADOW = timedelta(weeks=4)

#: Legal stage transitions. Anything absent is refused — notably None ->
#: Production, which is the transition every incident report describes.
LEGAL_TRANSITIONS: dict[Stage, frozenset[Stage]] = {
    Stage.NONE: frozenset({Stage.STAGING, Stage.ARCHIVED}),
    Stage.STAGING: frozenset({Stage.PRODUCTION, Stage.ARCHIVED, Stage.NONE}),
    Stage.PRODUCTION: frozenset({Stage.ARCHIVED, Stage.STAGING}),
    Stage.ARCHIVED: frozenset({Stage.STAGING}),
}


@dataclass
class PromotionDecision:
    allowed: bool
    reasons: list[str]

    def __bool__(self) -> bool:
        return self.allowed


def can_promote(
    artifact: ModelArtifact,
    target: Stage,
    *,
    now: datetime,
    via_ci: bool,
    fallback_path_warm: bool = True,
) -> PromotionDecision:
    """Evaluate every gate condition for one stage transition."""
    reasons: list[str] = []

    if target not in LEGAL_TRANSITIONS.get(artifact.stage, frozenset()):
        reasons.append(
            f"{artifact.stage.value} -> {target.value} is not a legal transition"
        )

    if not via_ci:
        reasons.append(
            "promotion must run through a CI pipeline; manual registry moves are "
            "disabled (WS-0.2.2)"
        )

    if target is Stage.PRODUCTION:
        if not artifact.model_card_path:
            reasons.append(
                "no model card: Master §2 rule 5 blocks shadow, let alone production"
            )
        if not artifact.validation_report_path:
            reasons.append("no independent validation report (Master §3.1)")
        if artifact.shadow_started_at is None:
            reasons.append("never entered shadow; Master §3.2 requires >= 4 weeks")
        else:
            elapsed = now - artifact.shadow_started_at
            if elapsed < MINIMUM_SHADOW:
                reasons.append(
                    f"shadow ran {elapsed.days}d, short of the {MINIMUM_SHADOW.days}d "
                    "minimum (Master §3.2)"
                )
        if not fallback_path_warm:
            reasons.append(
                "previous decisioning path is not warm; Master §3.2 requires it as "
                "the automatic fallback (SRS §12 availability)"
            )
        if artifact.definitions_fingerprint != fingerprint():
            reasons.append(
                f"trained against definitions {artifact.definitions_fingerprint}, "
                f"current Appendix A is {fingerprint()} — Master §4 impact analysis "
                "is required before this reaches customers"
            )

    return PromotionDecision(allowed=not reasons, reasons=reasons)

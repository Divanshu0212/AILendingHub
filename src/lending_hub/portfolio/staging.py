"""IFRS-9 / Ind AS 109 staging engine (WS-3.1 Step 7).

A deterministic service, not a model: given a lifetime PD now, a lifetime PD at
origination, a DPD, and an early-warning flag, it assigns Stage 1, 2 or 3 and
logs which rule fired. Phase 3 requires the provenance on every decision, and
that requirement is why this is a service rather than a SQL case statement — a
staging feed that cannot say *why* an account moved cannot be audited, and the
staging audit is a Phase 3 exit criterion.

Stage 1 is the one you cannot assign
------------------------------------
Stage 3 is determinable from evidence: credit-impaired per Appendix A. Stage 2
is determinable when the DPD backstop trips or an EWS flag is raised. But
Stage 1 means *"not Stage 2"*, and one of Stage 2's arms — significant increase
in credit risk, measured as lifetime-PD deterioration against origination —
needs a threshold that does not exist (LH-301) and an origination lifetime PD
that mostly does not exist either (LH-308).

So the honest output for an account with no arrears and no flag is **not
Stage 1**. It is "undeterminable", and :meth:`StagingPolicy.stage` raises
rather than returning it. Defaulting those accounts to Stage 1 is not a
conservative simplification — it is the single least conservative choice
available, because Stage 1 carries 12-month ECL and Stage 2 carries lifetime
ECL. An engine that quietly assigns Stage 1 understates the provision by
exactly the amount the SICR rule was written to capture, and it does so
silently, on the majority of the book.

:meth:`StagingPolicy.classify` returns the undeterminable state as a value for
reporting flows that need to count it. Nothing here converts it to a stage.

Workstream: WS-3.1 Step 7 (SRS §7.3.4)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Sequence

from lending_hub.definitions import OutcomeObservation, is_default
from lending_hub.definitions.provenance import Grounded, Pending, Source, Ungrounded

#: The SICR threshold — how much lifetime PD must deteriorate against
#: origination before an account is Stage 2. Phase 3 §8 do-not-invent.
SICR_THRESHOLD = Pending(
    owner="Finance + Risk",
    ticket="LH-301",
    note="the lifetime-PD deterioration ratio that triggers Stage 2",
)

#: The DPD backstop. `[SPEC]` from SRS §7.3.4, which states the rule rather
#: than leaving it to policy — unlike the SICR ratio above.
#:
#: It coincides numerically with Appendix A's indeterminate lower bound and is
#: **not** the same rule: different owner, different purpose, and they will not
#: move together. Aliasing them would make an Appendix A change silently
#: restage the book.
DPD_BACKSTOP_DAYS = Grounded(
    value=30,
    source=Source.SPEC,
    citation="SRS §7.3.4 — Stage-2 rule: '... OR 30+ DPD backstop'",
)


class StagingError(Exception):
    """The staging decision cannot be formed as asked."""


class Stage(IntEnum):
    """IFRS-9 impairment stages."""

    ONE = 1
    """Performing — 12-month ECL."""

    TWO = 2
    """Significant increase in credit risk — lifetime ECL, not yet impaired."""

    THREE = 3
    """Credit-impaired — lifetime ECL, interest on the net carrying amount."""


#: Rule identifiers recorded on every decision. Strings rather than an enum so
#: that a decision record replayed from storage years later does not depend on
#: this module still defining the same members.
CREDIT_IMPAIRED = "stage3_credit_impaired"
DPD_BACKSTOP = "stage2_dpd_backstop"
EWS_RED_FLAG = "stage2_ews_red_flag"
SICR_PD_RATIO = "stage2_sicr_pd_ratio"
NO_TRIGGER = "stage1_no_trigger"


@dataclass(frozen=True)
class StagingInput:
    """Everything the staging rules read for one account, at one snapshot.

    ``lifetime_pd_at_origination`` is ``None`` for the back book, where no such
    number was ever produced (LH-308). That is a state the engine has to handle,
    not an input error — it is the normal case on day one of a P3 deployment.
    """

    account_id: str
    snapshot: str
    dpd: int | None = None
    written_off: bool | None = None
    lifetime_pd: float | None = None
    lifetime_pd_at_origination: float | None = None
    ews_red_flag: bool = False

    def __post_init__(self) -> None:
        for name in ("lifetime_pd", "lifetime_pd_at_origination"):
            value = getattr(self, name)
            if value is not None and not 0.0 <= value <= 1.0:
                raise StagingError(
                    f"{self.account_id}: {name} is {value}, outside [0, 1]"
                )


@dataclass(frozen=True)
class StagingDecision:
    """One staged account, with the rule that put it there.

    ``triggers`` lists every rule that fired, not just the binding one. Two
    accounts both in Stage 2, one on arrears and one on PD deterioration, are
    different portfolios to a collections team, and a feed that records only
    the resulting stage cannot tell them apart afterwards.
    """

    account_id: str
    snapshot: str
    stage: Stage
    triggers: tuple[str, ...]
    provenance: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "account_id": self.account_id,
            "snapshot": self.snapshot,
            "stage": int(self.stage),
            "triggers": list(self.triggers),
            "provenance": dict(self.provenance),
        }


@dataclass(frozen=True)
class Undeterminable:
    """The account is not Stage 3 and no evaluable Stage 2 arm fired.

    Deliberately not a :class:`Stage`. It cannot be summed into a provision, it
    cannot be written to a staging feed, and it will not compare equal to
    ``Stage.ONE`` in a reporting query that forgot to check.
    """

    account_id: str
    snapshot: str
    reason: str
    unevaluable_rules: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "account_id": self.account_id,
            "snapshot": self.snapshot,
            "stage": None,
            "undeterminable_reason": self.reason,
            "unevaluable_rules": list(self.unevaluable_rules),
        }


@dataclass
class StagingPolicy:
    """The staging rules, with their grounding attached.

    ``sicr_threshold`` is a ratio: Stage 2 when
    ``lifetime_pd / lifetime_pd_at_origination > threshold``. SRS §7.3.4
    illustrates 2x; Phase 3 §8 puts the real number on the do-not-invent list,
    so the illustration is not a default and none is offered.
    """

    sicr_threshold: object = SICR_THRESHOLD
    dpd_backstop_days: object = DPD_BACKSTOP_DAYS
    ews_enabled: bool = False
    """Wired when P4 ships. Off by default because P4 does not exist, and a
    staging engine that reads a flag nothing writes reports a clean Stage 2
    count that is clean for the wrong reason."""

    @property
    def sicr_evaluable(self) -> bool:
        return not isinstance(self.sicr_threshold, Pending)

    @property
    def blockers(self) -> list[str]:
        out = []
        if not self.sicr_evaluable:
            out.append(f"SICR threshold: {self.sicr_threshold}")
        if not self.ews_enabled:
            out.append("EWS red flags are not wired (P4 not shipped)")
        return out

    def _backstop_days(self) -> int:
        value = self.dpd_backstop_days
        return value.value if isinstance(value, Grounded) else int(value)

    def classify(self, item: StagingInput) -> StagingDecision | Undeterminable:
        """Stage the account, or say why it cannot be staged."""
        triggers: list[str] = []
        provenance: dict = {}

        impaired = is_default(OutcomeObservation(
            max_dpd=item.dpd or 0, written_off=item.written_off))
        if impaired:
            triggers.append(CREDIT_IMPAIRED)
            provenance[CREDIT_IMPAIRED] = (
                "lending_hub.definitions.is_default (Master Appendix A)"
            )
            return StagingDecision(
                item.account_id, item.snapshot, Stage.THREE,
                tuple(triggers), provenance)

        backstop = self._backstop_days()
        if item.dpd is not None and item.dpd >= backstop:
            triggers.append(DPD_BACKSTOP)
            provenance[DPD_BACKSTOP] = (
                f"dpd {item.dpd} >= {backstop} "
                f"[{Source.SPEC.value}: {DPD_BACKSTOP_DAYS.citation}]"
            )

        if self.ews_enabled and item.ews_red_flag:
            triggers.append(EWS_RED_FLAG)
            provenance[EWS_RED_FLAG] = "P4 early-warning red flag"

        unevaluable: list[str] = []
        if self.sicr_evaluable:
            ratio = self._pd_ratio(item)
            if ratio is None:
                unevaluable.append(SICR_PD_RATIO)
            elif ratio > float(self.sicr_threshold):
                triggers.append(SICR_PD_RATIO)
                provenance[SICR_PD_RATIO] = (
                    f"lifetime PD ratio {ratio:.4f} > {self.sicr_threshold}"
                )
        else:
            unevaluable.append(SICR_PD_RATIO)

        if triggers:
            return StagingDecision(
                item.account_id, item.snapshot, Stage.TWO,
                tuple(triggers), provenance)

        if unevaluable:
            return Undeterminable(
                account_id=item.account_id,
                snapshot=item.snapshot,
                reason=(
                    "no evaluable Stage 2 arm fired, but the SICR arm could not "
                    "be evaluated, so 'not Stage 2' is not established. "
                    + "; ".join(self._why_unevaluable(item))
                ),
                unevaluable_rules=tuple(unevaluable),
            )

        return StagingDecision(
            item.account_id, item.snapshot, Stage.ONE,
            (NO_TRIGGER,),
            {NO_TRIGGER: "every Stage 2 arm evaluated and none fired"},
        )

    def stage(self, item: StagingInput) -> StagingDecision:
        """Stage the account, raising when it cannot be staged.

        The raising path is the point. Returning Stage 1 here would understate
        the provision by exactly the amount the SICR rule exists to capture.
        """
        result = self.classify(item)
        if isinstance(result, Undeterminable):
            raise Ungrounded(
                f"{item.account_id} at {item.snapshot} cannot be staged: "
                f"{result.reason} Stage 1 is not a safe default — it carries "
                "12-month ECL where Stage 2 carries lifetime ECL."
            )
        return result

    def _pd_ratio(self, item: StagingInput) -> float | None:
        if item.lifetime_pd is None or item.lifetime_pd_at_origination is None:
            return None
        if item.lifetime_pd_at_origination <= 0:
            return None
        return item.lifetime_pd / item.lifetime_pd_at_origination

    def _why_unevaluable(self, item: StagingInput) -> list[str]:
        out = []
        if not self.sicr_evaluable:
            out.append(f"threshold {self.sicr_threshold} (Phase 3 §8 do-not-invent)")
        if item.lifetime_pd_at_origination is None:
            out.append(
                "no lifetime PD at origination for this account (LH-308); SICR is "
                "defined relative to origination and the back book has no such "
                "number"
            )
        elif item.lifetime_pd is None:
            out.append("no current lifetime PD supplied")
        return out


@dataclass
class StagingRun:
    """Aggregate of one staging pass, with the undeterminable count on its face."""

    decisions: list[StagingDecision] = field(default_factory=list)
    undeterminable: list[Undeterminable] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.decisions) + len(self.undeterminable)

    def counts(self) -> dict[str, int]:
        out = {f"stage_{s.value}": 0 for s in Stage}
        for decision in self.decisions:
            out[f"stage_{int(decision.stage)}"] += 1
        out["undeterminable"] = len(self.undeterminable)
        return out

    def to_dict(self) -> dict:
        return {
            "accounts": self.total,
            "counts": self.counts(),
            "undeterminable_fraction": (
                round(len(self.undeterminable) / self.total, 4) if self.total else 0.0
            ),
        }


def run_staging(
    policy: StagingPolicy, items: Sequence[StagingInput]
) -> StagingRun:
    """Stage a population, collecting the undeterminable rather than dropping them."""
    run = StagingRun()
    for item in items:
        result = policy.classify(item)
        if isinstance(result, Undeterminable):
            run.undeterminable.append(result)
        else:
            run.decisions.append(result)
    return run

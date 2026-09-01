"""Agri lifecycle and the suitability duty (WS-4.B Step 5).

Phase 4 §5 Step 5:

    Calendar-driven from P2: sowing confirmed → input top-up eligibility; good
    harvest → equipment-loan campaign; drought flag → **suppress marketing,
    offer restructuring** (suitability duty). Monthly human suitability audit:
    recommended EMIs vs. stressed affordability; drought-flagged customers
    received support, not sales.

The drought rule is the one that has to be structural
------------------------------------------------------
The first two lifecycle rules are commercial: a confirmed sowing makes an input
top-up sensible, a good harvest makes equipment finance sensible. The third is a
**duty**, and it runs against the commercial grain — a drought-flagged farmer is
in acute need of credit, which makes them unusually likely to accept an offer.
So every signal a take-up model reads says *market to this person now*, and the
suitability duty says the opposite.

That asymmetry is why :func:`lifecycle_action` returns a suppression as a typed
outcome rather than a filter applied afterwards, and why
:class:`SuitabilityVerdict` carries the drought state on every recommendation.
A marketing suppression implemented as a downstream filter is one refactor away
from being lost, and its absence is invisible: the campaign simply performs
well.

The audit is monthly and human, and this module does not replace it
--------------------------------------------------------------------
§5 Step 5 asks for a monthly *human* audit on two questions: were recommended
EMIs within stressed affordability, and did drought-flagged customers receive
support rather than sales. :func:`audit` computes both and returns findings for
a human to review. It does not sign anything off — an automated suitability
audit that passed itself would be the control auditing its own subject.

What this does not port
-----------------------
No campaign system, no marketing suppression list, no case creation. This
decides what *should* happen; wiring it to an outbound channel is Track B. The
restructuring terms a drought-flagged customer is offered are LH-506 and are
refused here, as in ``ews.agri_triggers``.

Workstream: WS-4.B Step 5 (SRS §6, §3)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Sequence

from lending_hub.definitions.provenance import Pending, Ungrounded
from lending_hub.reco.feasible import Applicant, FeasibleSet, Offer, Segment, emi

#: The two-season sowing-verification rule governing disbursal tranching.
#: Phase 4 §6 shipping ladder step 3 and Phase 2 §8 both name it; nobody has
#: stated it. Registered in Phase 2 as LH-403.
TRANCHING_RULE = Pending(
    owner="Agri Credit Head + Credit Policy",
    ticket="LH-403",
    note="how much of a sanctioned limit releases against which sowing evidence",
)


class SuitabilityError(Exception):
    """A lifecycle decision or audit cannot be made from what was supplied."""


class LifecycleStage(str, Enum):
    """Where a borrower sits in the crop cycle, from the P2 monitoring stream."""

    SOWING_CONFIRMED = "sowing_confirmed"
    GOOD_HARVEST = "good_harvest"
    DROUGHT_FLAGGED = "drought_flagged"
    UNKNOWN = "unknown"
    """No P2 signal for this borrower. Deliberately not treated as "no drought":
    an unmonitored plot and a healthy one are different states, and defaulting
    the first to the second markets to exactly the farmers the bank cannot see."""


class ActionKind(str, Enum):
    OFFER = "offer"
    SUPPRESS_MARKETING = "suppress_marketing"
    NO_ACTION = "no_action"


@dataclass(frozen=True)
class LifecycleAction:
    """What §5 Step 5 says to do at this stage, and why.

    ``kind`` is typed rather than boolean because a suppression is not the
    absence of an offer — it is a positive instruction that also carries a
    support obligation, and the two collapse into each other if suppression is
    modelled as "no offer".
    """

    borrower_id: str
    stage: LifecycleStage
    kind: ActionKind
    reason: str
    eligible_products: tuple[str, ...] = ()
    support_required: bool = False

    def __post_init__(self) -> None:
        if not self.reason:
            raise SuitabilityError(f"{self.borrower_id}: an action needs its reason")
        if self.kind is ActionKind.OFFER and not self.eligible_products:
            raise SuitabilityError(
                f"{self.borrower_id}: an offer action must name which products "
                "became eligible. 'Offer something' is not a lifecycle rule."
            )
        if self.kind is ActionKind.SUPPRESS_MARKETING and not self.support_required:
            raise SuitabilityError(
                f"{self.borrower_id}: suppression without a support obligation is "
                "just silence. Phase 4 §5 Step 5 requires drought-flagged "
                "customers receive support, not merely an absence of sales."
            )


def lifecycle_action(
    borrower_id: str,
    stage: LifecycleStage,
    *,
    input_products: Sequence[str] = (),
    equipment_products: Sequence[str] = (),
) -> LifecycleAction:
    """Map a P2 lifecycle stage to the action §5 Step 5 prescribes.

    The drought branch returns a suppression with a support obligation attached,
    never an empty offer list. That distinction is the suitability duty: a
    drought-flagged farmer is in acute need of credit and therefore unusually
    likely to *accept* — so every take-up signal points at marketing to them,
    and the duty points the other way.
    """
    if stage is LifecycleStage.DROUGHT_FLAGGED:
        return LifecycleAction(
            borrower_id=borrower_id,
            stage=stage,
            kind=ActionKind.SUPPRESS_MARKETING,
            reason=(
                "drought flag from P2: Phase 4 §5 Step 5 requires marketing "
                "suppressed and restructuring offered. A drought-flagged farmer "
                "is in acute need and unusually likely to accept, which is "
                "exactly why the duty runs against the take-up signal."
            ),
            support_required=True,
        )

    if stage is LifecycleStage.SOWING_CONFIRMED:
        if not input_products:
            raise SuitabilityError(
                f"{borrower_id}: sowing confirmed but no input products "
                "configured. §5 Step 5 makes sowing an eligibility trigger for "
                "input top-ups, and a trigger with nothing to offer is a rule "
                "that silently does nothing."
            )
        return LifecycleAction(
            borrower_id=borrower_id,
            stage=stage,
            kind=ActionKind.OFFER,
            reason="sowing confirmed from P2: input top-up eligibility opens",
            eligible_products=tuple(input_products),
        )

    if stage is LifecycleStage.GOOD_HARVEST:
        if not equipment_products:
            raise SuitabilityError(
                f"{borrower_id}: good harvest but no equipment products configured"
            )
        return LifecycleAction(
            borrower_id=borrower_id,
            stage=stage,
            kind=ActionKind.OFFER,
            reason="good harvest from P2: equipment-loan campaign eligibility opens",
            eligible_products=tuple(equipment_products),
        )

    return LifecycleAction(
        borrower_id=borrower_id,
        stage=stage,
        kind=ActionKind.NO_ACTION,
        reason=(
            "no P2 lifecycle signal. An unmonitored plot is not a healthy one, "
            "so no campaign eligibility opens on the absence of a flag."
        ),
    )


def restructuring_terms(action: LifecycleAction) -> str:
    """The terms a drought-flagged customer should be offered. Raises.

    §5 Step 5 requires restructuring be offered and does not say on what terms,
    and those terms are RBI natural-calamity norms as the bank implements them
    (LH-506). A restructuring on invented terms is a contractual variation
    nobody approved.
    """
    if action.kind is not ActionKind.SUPPRESS_MARKETING:
        raise SuitabilityError(
            f"{action.borrower_id}: restructuring applies to drought-flagged "
            f"borrowers, not to a {action.stage.value} one"
        )
    raise Ungrounded(
        "the natural-calamity restructuring terms are not ratified (LH-506). "
        "Phase 4 §5 Step 5 requires restructuring be offered and does not say on "
        "what terms; those are RBI norms as this bank implements them, and a "
        "restructuring offered on invented terms is a contractual variation "
        "nobody approved."
    )


@dataclass(frozen=True)
class SuitabilityFinding:
    """One recommendation that failed a suitability check."""

    borrower_id: str
    check: str
    detail: str


@dataclass(frozen=True)
class SuitabilityVerdict:
    """The monthly audit's output — findings for a human, not a sign-off."""

    period_end: date
    recommendations_reviewed: int
    findings: tuple[SuitabilityFinding, ...]

    @property
    def clean(self) -> bool:
        return not self.findings

    @property
    def by_check(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for finding in self.findings:
            counts[finding.check] = counts.get(finding.check, 0) + 1
        return counts

    def sign_off(self) -> None:
        """Refuses. §5 Step 5 requires a *human* monthly audit.

        An automated audit that signed itself off would be the control auditing
        its own subject, and Phase 4 §8's "suitability audit clean" would then
        be a statement this module makes about itself.
        """
        raise SuitabilityError(
            "this audit produces findings for a human reviewer and does not "
            "sign itself off. Phase 4 §5 Step 5 specifies a monthly human "
            "suitability audit, and an automated control that cleared its own "
            "subject would make §8's 'suitability audit clean' a claim this "
            "module makes about itself."
        )


@dataclass(frozen=True)
class Recommendation:
    """One offer actually recommended to one borrower, with its context."""

    borrower_id: str
    offer: Offer
    stage: LifecycleStage
    recommended_on: date


def audit(
    recommendations: Sequence[Recommendation],
    applicants: dict[str, Applicant],
    *,
    period_end: date,
) -> SuitabilityVerdict:
    """The two checks §5 Step 5 names, computed for a human to review.

    Check 1 — **recommended EMIs against stressed affordability**. Note the
    phrase: not against *expected* affordability, which the feasible set already
    enforces. This is the stricter question of whether the recommendation still
    holds under P2's StressedIncome, and an offer can be feasible and fail it.

    Check 2 — **drought-flagged customers received support, not sales**. Any
    offer recommended to a drought-flagged borrower is a finding, regardless of
    its terms.
    """
    findings: list[SuitabilityFinding] = []

    for recommendation in recommendations:
        applicant = applicants.get(recommendation.borrower_id)
        if applicant is None:
            raise SuitabilityError(
                f"{recommendation.borrower_id} was recommended an offer but is "
                "not in the applicant set. An audit that skipped them would "
                "report clean on a population it did not review."
            )

        if recommendation.stage is LifecycleStage.DROUGHT_FLAGGED:
            findings.append(
                SuitabilityFinding(
                    borrower_id=recommendation.borrower_id,
                    check="drought_marketing_suppression",
                    detail=(
                        f"{recommendation.offer.product} recommended to a "
                        "drought-flagged borrower; §5 Step 5 requires support, "
                        "not sales"
                    ),
                )
            )

        if applicant.segment is not Segment.RETAIL:
            stressed = applicant.stressed_annual_cash_flow
            if stressed is None:
                findings.append(
                    SuitabilityFinding(
                        borrower_id=recommendation.borrower_id,
                        check="stressed_affordability",
                        detail=(
                            "no StressedIncome available, so the recommendation "
                            "could not be tested against stressed affordability "
                            "at all"
                        ),
                    )
                )
                continue
            annual_service = recommendation.offer.emi * 12.0
            if annual_service > stressed:
                findings.append(
                    SuitabilityFinding(
                        borrower_id=recommendation.borrower_id,
                        check="stressed_affordability",
                        detail=(
                            f"annual debt service {annual_service:,.2f} exceeds "
                            f"stressed cash flow {stressed:,.2f}"
                        ),
                    )
                )

    return SuitabilityVerdict(
        period_end=period_end,
        recommendations_reviewed=len(recommendations),
        findings=tuple(findings),
    )


def tranche_release(action: LifecycleAction, sanctioned_amount: float) -> float:
    """How much of a sanctioned limit releases on this evidence. Raises.

    Phase 4 §6's shipping ladder makes live agri origination conditional on "the
    two-season sowing-verification rule for disbursal tranching
    `[POLICY: Agri Credit Head]`", and Phase 2 §8 puts tranching rules on its
    do-not-invent list (LH-403). Releasing a guessed fraction is disbursing
    money against a rule nobody wrote.
    """
    if sanctioned_amount <= 0:
        raise SuitabilityError("sanctioned amount must be positive")
    raise Ungrounded(
        f"the disbursal-tranching rule is not ratified ({TRANCHING_RULE}). "
        "Phase 4 §6 makes live agri origination conditional on a two-season "
        "sowing-verification rule and Phase 2 §8 forbids inventing one; "
        "releasing a guessed fraction disburses money against a rule nobody "
        "wrote."
    )

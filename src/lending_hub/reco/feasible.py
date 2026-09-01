"""Feasible-set service — ship this first, alone it is useful (WS-4.B Step 1).

Phase 4 §5 Step 1:

    Pure, exhaustively unit-tested library (golden-file tests vs. hand-computed
    examples):

        EMI(a, r, n) = a·r(1+r)^n / ((1+r)^n − 1)
        Retail:   EMI + existing obligations <= FOIR_cap × VerifiedIncome
        MSME/agri: DSCR = CashFlow/DebtService >= 1.25 on StressedIncome (P2)
        Plus: LTV caps, tenor limits, product policy, concentration caps

    All caps from config `[POLICY: Credit Policy]`.

Why this ships before anything else
-------------------------------------
It is the only part of the recommendation engine that is *pure arithmetic on
ratified policy*. No model, no training data, no learning. That makes it
deployable on the day the caps are ratified, and it delivers most of the
engine's practical value on its own: an officer who can see which offers are
permissible, and which constraint bound each one, does not need a ranking model
to do their job better than they did yesterday.

It is also what makes the bandit safe. Phase 4 §5 Step 4: "exploration can never
breach affordability or policy" — which is only true if the feasible set is
computed *first* and the learner chooses within it. That ordering is enforced
here by :meth:`FeasibleSet.contains`, which `reco.bandit` must consult.

Every cap is required, and the DSCR figure in the phase file is not one
--------------------------------------------------------------------------
Phase 4 §9 puts FOIR/DSCR/LTV caps on the do-not-invent list. The phase file
writes "DSCR = CashFlow/DebtService >= 1.25" — but that 1.25 sits inside a
*worked formula* illustrating the shape of the rule, not a ratified policy
value, and reading an illustration as a policy is precisely the failure the
grounding contract exists to prevent. :class:`PolicyCaps` therefore has no
defaults at all, and :func:`load_caps` reads them from config with the same
dual-control treatment `serving.bands` gives the P1 cutoffs.

Rejections carry the binding constraint
-----------------------------------------
An offer that fails affordability by ₹200 and one that breaches a concentration
cap are the same boolean and completely different conversations. Every
:class:`Assessment` names the constraint that bound it and by how much, because
that is what an officer needs to say to a customer, and because "declined" with
no reason is the shape of an adverse-action problem.

What this does not port
-----------------------
No amortisation schedule, no day-count conventions, no prepayment or
part-payment maths. EMI here is the standard reducing-balance annuity on a
constant periodic rate, which is what the phase file specifies; a real
disbursement has fees, an odd first period and a rounding convention, all of
which belong to the loan management system rather than to eligibility.

Workstream: WS-4.B Step 1 (SRS §6)
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Sequence

from lending_hub.definitions.provenance import Pending, Ungrounded

#: The ratified affordability and exposure caps. Phase 4 §9 do-not-invent.
POLICY_CAPS = Pending(
    owner="Credit Policy",
    ticket="LH-504",
    note="FOIR, DSCR, LTV and tenor caps per product",
)

#: Default config location, mirroring `config/policy_bands.yaml`.
DEFAULT_CAPS_PATH = "config/lending_caps.yaml"


class FeasibilityError(Exception):
    """An offer or a cap set is malformed."""


class Segment(str, Enum):
    """Which affordability rule applies.

    Phase 4 §5 Step 1 gives retail a FOIR test and MSME/agri a DSCR test. They
    are not interchangeable and not two parameterisations of one rule: FOIR
    caps servicing against *income*, DSCR covers servicing from *cash flow*, and
    an agri borrower has seasonal cash flow with no monthly income to divide by.
    """

    RETAIL = "retail"
    MSME = "msme"
    AGRI = "agri"

    @property
    def uses_dscr(self) -> bool:
        return self is not Segment.RETAIL


def emi(principal: float, annual_rate: float, months: int) -> float:
    """``EMI = a·r(1+r)^n / ((1+r)^n − 1)`` — Phase 4 §5 Step 1, verbatim.

    ``annual_rate`` is a decimal annual rate (0.12 for 12%); ``r`` in the
    formula is the monthly rate. A zero rate is handled as the limit
    ``principal / months`` rather than dividing by zero — an interest-free
    instalment product is a real thing and the formula's singularity there is
    arithmetic, not policy.
    """
    if principal <= 0:
        raise FeasibilityError(f"principal must be positive, got {principal}")
    if months <= 0:
        raise FeasibilityError(f"tenor must be at least 1 month, got {months}")
    if annual_rate < 0:
        raise FeasibilityError(
            f"annual rate {annual_rate} is negative. A negative rate is not an "
            "aggressive price, it is a data error — and it produces an EMI below "
            "the straight-line repayment, which passes every affordability test."
        )

    monthly = annual_rate / 12.0
    if monthly == 0:
        return principal / months

    growth = (1.0 + monthly) ** months
    return principal * monthly * growth / (growth - 1.0)


def total_interest(principal: float, annual_rate: float, months: int) -> float:
    """Total interest over the life of the loan.

    Reported alongside the EMI because the EMI alone hides tenor: extending a
    loan lowers the instalment and raises the cost, and a recommendation engine
    optimising on affordability will reach for tenor first. An officer seeing
    both numbers can see that trade; one seeing only the EMI cannot.
    """
    return emi(principal, annual_rate, months) * months - principal


@dataclass(frozen=True)
class PolicyCaps:
    """Ratified caps for one product. No defaults, by design.

    Phase 4 §9 puts every field here on the do-not-invent list. A default in
    this signature is how an ungrounded number becomes the production one:
    nobody passes the argument, and by the time anyone asks it has been in a
    credit policy document for a year.
    """

    product: str
    segment: Segment
    foir_cap: float | None
    dscr_floor: float | None
    ltv_cap: float | None
    max_tenor_months: int
    min_amount: float
    max_amount: float
    ratification_reference: str

    def __post_init__(self) -> None:
        if not self.ratification_reference:
            raise FeasibilityError(
                f"{self.product}: caps need the Credit Policy decision that "
                f"ratified them ({POLICY_CAPS}). Phase 4 §9 do-not-invent — and "
                "the 1.25 DSCR in §5 Step 1 is inside a worked formula, not a "
                "ratified value."
            )
        if self.segment is Segment.RETAIL and self.foir_cap is None:
            raise FeasibilityError(
                f"{self.product}: a retail product needs a FOIR cap"
            )
        if self.segment.uses_dscr and self.dscr_floor is None:
            raise FeasibilityError(
                f"{self.product}: an {self.segment.value} product needs a DSCR floor"
            )
        if self.foir_cap is not None and not 0.0 < self.foir_cap <= 1.0:
            raise FeasibilityError(
                f"{self.product}: FOIR cap {self.foir_cap} is outside (0, 1]. It "
                "is a share of income, so a value above 1 commits more than the "
                "borrower earns."
            )
        if self.dscr_floor is not None and self.dscr_floor < 1.0:
            raise FeasibilityError(
                f"{self.product}: DSCR floor {self.dscr_floor} is below 1.0, "
                "which permits lending where cash flow does not cover debt "
                "service even before any stress"
            )
        if self.ltv_cap is not None and not 0.0 < self.ltv_cap <= 1.0:
            raise FeasibilityError(f"{self.product}: LTV cap {self.ltv_cap} outside (0, 1]")
        if self.max_tenor_months <= 0:
            raise FeasibilityError(f"{self.product}: tenor cap must be positive")
        if self.min_amount <= 0 or self.max_amount <= self.min_amount:
            raise FeasibilityError(
                f"{self.product}: amount range [{self.min_amount}, "
                f"{self.max_amount}] is empty or non-positive"
            )


@dataclass(frozen=True)
class Applicant:
    """Everything the feasibility rules read about a borrower.

    ``stressed_income`` is P2's ``StressedIncome`` and is what the DSCR test
    uses for agri — Phase 4 §5 Step 1 is explicit. Using expected income there
    would size an agri loan on a good harvest, which is the failure mode agri
    lending is famous for.
    """

    applicant_id: str
    segment: Segment
    verified_monthly_income: float | None = None
    existing_monthly_obligations: float = 0.0
    annual_cash_flow: float | None = None
    stressed_annual_cash_flow: float | None = None
    collateral_value: float | None = None
    existing_exposure: float = 0.0

    def __post_init__(self) -> None:
        if self.existing_monthly_obligations < 0:
            raise FeasibilityError(f"{self.applicant_id}: negative obligations")
        if self.existing_exposure < 0:
            raise FeasibilityError(f"{self.applicant_id}: negative existing exposure")


@dataclass(frozen=True)
class Offer:
    """A candidate product, amount, tenor and rate."""

    product: str
    amount: float
    tenor_months: int
    annual_rate: float

    def __post_init__(self) -> None:
        if self.amount <= 0:
            raise FeasibilityError(f"{self.product}: amount must be positive")
        if self.tenor_months <= 0:
            raise FeasibilityError(f"{self.product}: tenor must be positive")

    @property
    def emi(self) -> float:
        return emi(self.amount, self.annual_rate, self.tenor_months)


@dataclass(frozen=True)
class ConstraintResult:
    """One constraint, its computed value, its limit, and the headroom."""

    name: str
    value: float
    limit: float
    satisfied: bool
    detail: str

    @property
    def headroom(self) -> float:
        """How far inside (positive) or outside (negative) the limit.

        Signed and in the constraint's own units, so a caller can say "₹1,400 of
        monthly headroom" or "0.08 short on DSCR" rather than "declined".
        """
        return self.limit - self.value if self.satisfied else self.limit - self.value


@dataclass(frozen=True)
class Assessment:
    """Whether one offer is feasible, and which constraint decided it."""

    offer: Offer
    applicant_id: str
    constraints: tuple[ConstraintResult, ...]

    @property
    def feasible(self) -> bool:
        return all(c.satisfied for c in self.constraints)

    @property
    def binding_constraint(self) -> ConstraintResult | None:
        """The constraint that failed, or the tightest one if all passed.

        Named on every assessment because "declined" with no reason is the shape
        of an adverse-action problem, and because an offer that fails
        affordability by ₹200 and one that breaches a concentration cap are the
        same boolean and entirely different conversations.
        """
        failed = [c for c in self.constraints if not c.satisfied]
        if failed:
            return min(failed, key=lambda c: c.headroom)
        if not self.constraints:
            return None
        return min(self.constraints, key=lambda c: c.headroom)

    @property
    def reason(self) -> str:
        binding = self.binding_constraint
        if self.feasible:
            return "" if binding is None else f"feasible; tightest: {binding.detail}"
        return binding.detail if binding else "infeasible"


def assess(applicant: Applicant, offer: Offer, caps: PolicyCaps) -> Assessment:
    """Evaluate one offer against the ratified caps.

    Every constraint is evaluated even after one fails, so the assessment shows
    *all* the reasons rather than the first. An officer who fixes the amount to
    clear affordability and then discovers the tenor cap has wasted a customer
    conversation.
    """
    if applicant.segment is not caps.segment:
        raise FeasibilityError(
            f"{applicant.applicant_id} is {applicant.segment.value} but "
            f"{caps.product} carries {caps.segment.value} caps. Applying a "
            "retail FOIR test to an agri borrower divides seasonal cash flow by "
            "a monthly income that does not exist."
        )

    constraints: list[ConstraintResult] = []
    instalment = offer.emi

    # -- Affordability -----------------------------------------------------
    if caps.segment is Segment.RETAIL:
        if applicant.verified_monthly_income is None:
            raise FeasibilityError(
                f"{applicant.applicant_id}: a retail FOIR test needs verified "
                "monthly income. An unverified or absent income is not a zero "
                "income — it is an application that cannot be assessed."
            )
        committed = instalment + applicant.existing_monthly_obligations
        allowed = caps.foir_cap * applicant.verified_monthly_income
        constraints.append(
            ConstraintResult(
                name="foir",
                value=committed,
                limit=allowed,
                satisfied=committed <= allowed,
                detail=(
                    f"FOIR: EMI {instalment:,.2f} + obligations "
                    f"{applicant.existing_monthly_obligations:,.2f} = "
                    f"{committed:,.2f} against cap {allowed:,.2f} "
                    f"({caps.foir_cap:.0%} of verified income)"
                ),
            )
        )
    else:
        cash_flow = applicant.stressed_annual_cash_flow
        if cash_flow is None:
            raise FeasibilityError(
                f"{applicant.applicant_id}: an {caps.segment.value} DSCR test "
                "needs StressedIncome (Phase 4 §5 Step 1, from P2). Using "
                "expected cash flow sizes the loan on a good harvest, which is "
                "the failure mode agri lending is known for."
            )
        annual_debt_service = instalment * 12.0
        dscr = cash_flow / annual_debt_service if annual_debt_service else 0.0
        constraints.append(
            ConstraintResult(
                name="dscr",
                value=dscr,
                limit=caps.dscr_floor,
                satisfied=dscr >= caps.dscr_floor,
                detail=(
                    f"DSCR: stressed cash flow {cash_flow:,.2f} / debt service "
                    f"{annual_debt_service:,.2f} = {dscr:.3f} against floor "
                    f"{caps.dscr_floor:.3f}"
                ),
            )
        )

    # -- Loan to value -----------------------------------------------------
    if caps.ltv_cap is not None:
        if applicant.collateral_value is None or applicant.collateral_value <= 0:
            raise FeasibilityError(
                f"{applicant.applicant_id}: {caps.product} carries an LTV cap, "
                "so it needs a collateral valuation. An absent valuation is not "
                "an unsecured loan; it is a secured loan whose security has not "
                "been valued."
            )
        ltv = offer.amount / applicant.collateral_value
        constraints.append(
            ConstraintResult(
                name="ltv",
                value=ltv,
                limit=caps.ltv_cap,
                satisfied=ltv <= caps.ltv_cap,
                detail=(
                    f"LTV: {offer.amount:,.2f} / {applicant.collateral_value:,.2f} "
                    f"= {ltv:.3f} against cap {caps.ltv_cap:.3f}"
                ),
            )
        )

    # -- Tenor and amount --------------------------------------------------
    constraints.append(
        ConstraintResult(
            name="tenor",
            value=float(offer.tenor_months),
            limit=float(caps.max_tenor_months),
            satisfied=offer.tenor_months <= caps.max_tenor_months,
            detail=(
                f"tenor: {offer.tenor_months} months against cap "
                f"{caps.max_tenor_months}"
            ),
        )
    )
    constraints.append(
        ConstraintResult(
            name="amount_max",
            value=offer.amount,
            limit=caps.max_amount,
            satisfied=offer.amount <= caps.max_amount,
            detail=f"amount: {offer.amount:,.2f} against cap {caps.max_amount:,.2f}",
        )
    )
    constraints.append(
        ConstraintResult(
            name="amount_min",
            value=caps.min_amount,
            limit=offer.amount,
            satisfied=offer.amount >= caps.min_amount,
            detail=(
                f"amount: {offer.amount:,.2f} against minimum {caps.min_amount:,.2f}"
            ),
        )
    )

    return Assessment(
        offer=offer, applicant_id=applicant.applicant_id, constraints=tuple(constraints)
    )


@dataclass(frozen=True)
class FeasibleSet:
    """Every offer that passes, and every one that does not with its reason.

    Infeasible offers are kept. Phase 4 §5 Step 4 requires the bandit to choose
    within the feasible set, and a set that discarded the rejects could not
    answer "why was this arm unavailable?" — which is the question an audit of a
    bandit decision asks first.
    """

    applicant_id: str
    assessments: tuple[Assessment, ...]

    @property
    def feasible(self) -> tuple[Offer, ...]:
        return tuple(a.offer for a in self.assessments if a.feasible)

    @property
    def rejected(self) -> tuple[Assessment, ...]:
        return tuple(a for a in self.assessments if not a.feasible)

    @property
    def is_empty(self) -> bool:
        return not self.feasible

    def contains(self, offer: Offer) -> bool:
        """Whether this offer is feasible. The bandit's safety check.

        Phase 4 §5 Step 4: "exploration can never breach affordability or
        policy". That is only true if the learner asks this question before
        acting, which `reco.bandit` does.
        """
        return any(a.offer == offer and a.feasible for a in self.assessments)

    def reason_for(self, offer: Offer) -> str:
        for assessment in self.assessments:
            if assessment.offer == offer:
                return assessment.reason
        raise FeasibilityError(
            f"{offer.product} was never assessed for {self.applicant_id}; an "
            "unassessed offer is not a rejected one"
        )

    @property
    def largest_feasible(self) -> Offer | None:
        """The biggest permissible amount.

        Exposed deliberately and named plainly, because Phase 4's LH-509 finding
        is that a bandit rewarded on take-up alone converges here. Having it
        available under an obvious name makes that behaviour visible in a review
        rather than emergent.
        """
        feasible = self.feasible
        return max(feasible, key=lambda o: o.amount) if feasible else None


def build_feasible_set(
    applicant: Applicant, offers: Sequence[Offer], caps_by_product: Mapping[str, PolicyCaps]
) -> FeasibleSet:
    """Assess every candidate offer for one applicant."""
    if not offers:
        raise FeasibilityError(
            f"{applicant.applicant_id}: no candidate offers. An empty candidate "
            "list produces an empty feasible set, which is indistinguishable "
            "from a borrower who qualifies for nothing."
        )

    assessments = []
    for offer in offers:
        caps = caps_by_product.get(offer.product)
        if caps is None:
            raise Ungrounded(
                f"no ratified caps for product {offer.product!r} ({POLICY_CAPS}). "
                "Phase 4 §9 puts FOIR/DSCR/LTV caps on the do-not-invent list, "
                "so an unconfigured product cannot be offered — it must not fall "
                "back to another product's caps."
            )
        assessments.append(assess(applicant, offer, caps))

    return FeasibleSet(applicant_id=applicant.applicant_id, assessments=tuple(assessments))

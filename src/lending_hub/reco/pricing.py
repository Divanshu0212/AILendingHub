"""Risk-based pricing on ALM config — never on constants (WS-4.B Step 2).

Phase 4 §5 Step 2:

    `rate = cost_of_funds + opex + E[loss] + capital_charge + margin`, with
    `E[loss] = PD·LGD·EAD` from P1/P3 models. Funds cost, opex, hurdle from ALM
    tables `[POLICY: ALCO]` — **never hard-coded**. Floors/ceilings per policy
    and RBI fair-practice norms.

"Never hard-coded" is a statement about time, not tidiness
------------------------------------------------------------
The emphasis in the phase file is doing real work. ALM components are not
constants that happen to be unknown — they **move**, monthly or faster. A cost
of funds is a treasury number that tracks the policy rate; an opex allocation
changes with the cost-to-income ratio; a hurdle is reset by ALCO. So a pricing
service that reads a constant is not merely ungrounded, it is *wrong within a
quarter even if the constant was right on the day it was written*, and nothing
in the output changes to say so.

That is why :class:`AlmTable` carries an ``effective_from`` and
:func:`price` refuses a table that is stale relative to the pricing date. A
stale table is the specific failure this design exists to catch: it produces
plausible rates, indefinitely, from last year's funding cost.

The expected-loss term is where the phases meet
-------------------------------------------------
``E[loss] = PD·LGD·EAD`` is the one place P1 and P3 both feed a customer-facing
number. PD comes from P1's application model or P3's behavioural one; LGD and
EAD come from P3. Each is blocked in its own phase for its own reason — and the
important consequence is that **an ungrounded LGD does not degrade the price, it
invalidates it**, because the loss term is what makes the price risk-based
rather than a flat sheet.

Floors and ceilings are a conduct control
-------------------------------------------
RBI fair-practice norms bound what may be charged. A computed rate above the
ceiling is not "an expensive customer" — it is a customer the bank must decline
rather than price, and :class:`PricedOffer` says so with
:attr:`PricedOffer.exceeds_ceiling` instead of silently clamping. Clamping is
the dangerous behaviour: it converts a decline into an offer at exactly the
ceiling, which is both a mis-priced loan and a fair-lending pattern that shows
up as a cluster of customers priced identically at the cap.

What this does not port
-----------------------
No treasury system, no FTP curve, no capital model. ``capital_charge`` arrives
as a component from the ALM table rather than being computed from RWA here —
Basel capital allocation is a finance function, and a pricing service that
recomputed it would be a second implementation of a number the bank already
has (Master §2 rule 2).

Workstream: WS-4.B Step 2 (SRS §6)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping

from lending_hub.definitions.provenance import Pending, Ungrounded

#: The ALM pricing components. Phase 4 §9 do-not-invent, and §5 Step 2 is
#: explicit that they come from ALM tables and are never hard-coded.
ALM_COMPONENTS = Pending(
    owner="ALCO",
    ticket="LH-505",
    note="cost of funds, opex allocation, capital charge, hurdle margin",
)

#: Rate floors and ceilings under policy and RBI fair-practice norms.
RATE_BOUNDS = Pending(
    owner="ALCO + Compliance",
    ticket="LH-505",
    note="per-product rate floor and ceiling under RBI fair-practice norms",
)

#: How stale an ALM table may be before pricing refuses it, in days. Not from
#: the phase file — an engineering guard. ALM components reset at least
#: monthly, so a table older than a quarter is describing a different funding
#: environment. Reported as a Phase 4 finding: the phase file requires the
#: components come from tables and says nothing about their freshness, which is
#: the failure that actually happens.
MAX_ALM_TABLE_AGE_DAYS = 92


class PricingError(Exception):
    """A rate cannot be computed from what was supplied."""


@dataclass(frozen=True)
class AlmTable:
    """One vintage of the ALM pricing components, with the date it took effect.

    Every field is a decimal annual rate. There are no defaults: Phase 4 §5
    Step 2 says these come from ALM tables `[POLICY: ALCO]`, and a default here
    would be the number the bank prices on for as long as nobody looks.
    """

    product: str
    effective_from: date
    cost_of_funds: float
    opex_allocation: float
    capital_charge: float
    hurdle_margin: float
    rate_floor: float | None
    rate_ceiling: float | None
    source_reference: str

    def __post_init__(self) -> None:
        if not self.source_reference:
            raise PricingError(
                f"{self.product}: an ALM table must name the ALCO decision or "
                f"treasury publication it came from ({ALM_COMPONENTS}). Without "
                "it, nobody auditing a rate two years on can tell which table "
                "priced it."
            )
        for name, value in (
            ("cost_of_funds", self.cost_of_funds),
            ("opex_allocation", self.opex_allocation),
            ("capital_charge", self.capital_charge),
            ("hurdle_margin", self.hurdle_margin),
        ):
            if value < 0:
                raise PricingError(
                    f"{self.product}: {name} is {value}. A negative component "
                    "subsidises the rate from somewhere unnamed."
                )
            if value > 1.0:
                raise PricingError(
                    f"{self.product}: {name} is {value}, above 100%. These are "
                    "decimal annual rates, not percentages — a table populated "
                    "in percent prices every loan a hundred times over."
                )
        if (
            self.rate_floor is not None
            and self.rate_ceiling is not None
            and self.rate_floor > self.rate_ceiling
        ):
            raise PricingError(
                f"{self.product}: floor {self.rate_floor} exceeds ceiling "
                f"{self.rate_ceiling}, so no rate is permissible"
            )

    @property
    def base_rate(self) -> float:
        """Everything except the borrower-specific expected loss."""
        return (
            self.cost_of_funds
            + self.opex_allocation
            + self.capital_charge
            + self.hurdle_margin
        )

    def age_days(self, as_of: date) -> int:
        return (as_of - self.effective_from).days


@dataclass(frozen=True)
class ExpectedLoss:
    """``PD · LGD · EAD``, with each component's provenance.

    ``ead_fraction`` is EAD as a share of the sanctioned amount, so the product
    is a *rate* comparable with the other components. For a term loan drawn in
    full it is 1.0; for anything revolving it is the CCF question P3 could not
    answer at all (LH-303).
    """

    pd: float
    lgd: float
    ead_fraction: float
    pd_source: str
    lgd_source: str

    def __post_init__(self) -> None:
        for name, value in (("pd", self.pd), ("lgd", self.lgd)):
            if not 0.0 <= value <= 1.0:
                raise PricingError(f"{name} {value} is outside [0, 1]")
        if self.ead_fraction <= 0:
            raise PricingError(
                f"EAD fraction {self.ead_fraction} must be positive; a zero "
                "exposure at default prices the loss term out of existence"
            )
        if not self.pd_source or not self.lgd_source:
            raise PricingError(
                "expected loss must name where its PD and LGD came from. They "
                "are produced by different phases against different populations, "
                "and a rate built from a mismatched pair is not risk-based — it "
                "is two models' outputs multiplied together."
            )

    @property
    def rate(self) -> float:
        return self.pd * self.lgd * self.ead_fraction


@dataclass(frozen=True)
class PricedOffer:
    """A rate with every component visible.

    The breakdown is not a debugging aid. A risk-based rate that cannot be
    decomposed cannot be explained to a customer who asks why theirs is higher,
    and it cannot be reconciled by Finance against the ALM table it claims to
    come from.
    """

    product: str
    priced_on: date
    alm_reference: str
    cost_of_funds: float
    opex_allocation: float
    capital_charge: float
    hurdle_margin: float
    expected_loss: float
    rate_floor: float | None
    rate_ceiling: float | None

    @property
    def computed_rate(self) -> float:
        """The rate before floors and ceilings are considered."""
        return (
            self.cost_of_funds
            + self.opex_allocation
            + self.capital_charge
            + self.hurdle_margin
            + self.expected_loss
        )

    @property
    def below_floor(self) -> bool:
        return self.rate_floor is not None and self.computed_rate < self.rate_floor

    @property
    def exceeds_ceiling(self) -> bool:
        """Whether this borrower may not be priced at all.

        Deliberately not clamped. A computed rate above the ceiling means the
        risk cannot be priced within fair-practice norms, so the answer is
        decline — not an offer at exactly the ceiling. Clamping produces a
        mis-priced loan *and* a fair-lending pattern: a cluster of customers all
        priced identically at the cap, which is what a regulator looks for.
        """
        return self.rate_ceiling is not None and self.computed_rate > self.rate_ceiling

    @property
    def offerable_rate(self) -> float:
        """The rate that may be quoted, or a refusal.

        Raises when the computed rate exceeds the ceiling. The floor *is*
        applied, because a floor is a minimum the bank charges rather than a
        statement about the borrower — pricing below it undercuts the bank, not
        the customer.
        """
        if self.exceeds_ceiling:
            raise PricingError(
                f"{self.product}: computed rate {self.computed_rate:.4f} exceeds "
                f"the ceiling {self.rate_ceiling:.4f}. This borrower cannot be "
                "priced within fair-practice norms and must be declined — "
                "quoting the ceiling would be a mis-priced loan and would put "
                "this customer in a cluster priced identically at the cap."
            )
        if self.below_floor:
            return self.rate_floor
        return self.computed_rate

    @property
    def breakdown(self) -> dict[str, float]:
        return {
            "cost_of_funds": self.cost_of_funds,
            "opex_allocation": self.opex_allocation,
            "capital_charge": self.capital_charge,
            "hurdle_margin": self.hurdle_margin,
            "expected_loss": self.expected_loss,
            "computed_rate": self.computed_rate,
        }

    @property
    def risk_share(self) -> float:
        """Share of the rate attributable to expected loss.

        The number that says whether pricing is meaningfully risk-based. If it
        is a fraction of a percent of the total, the model is decorating a rate
        that is really a flat sheet.
        """
        if self.computed_rate <= 0:
            raise PricingError("cannot decompose a non-positive rate")
        return self.expected_loss / self.computed_rate


def price(
    table: AlmTable,
    expected_loss: ExpectedLoss,
    *,
    as_of: date,
    max_table_age_days: int = MAX_ALM_TABLE_AGE_DAYS,
) -> PricedOffer:
    """Compute a risk-based rate from an ALM table and an expected loss.

    Refuses a stale table. That is the failure this module is built around: a
    stale table produces plausible rates indefinitely from last year's funding
    cost, and nothing in the output says so. The phase file requires the
    components come from tables and says nothing about their freshness, which is
    raised as a Phase 4 finding.
    """
    age = table.age_days(as_of)
    if age < 0:
        raise PricingError(
            f"{table.product}: ALM table takes effect {table.effective_from}, "
            f"after the pricing date {as_of}. Pricing against a future table "
            "quotes a rate that was not in force."
        )
    if age > max_table_age_days:
        raise PricingError(
            f"{table.product}: ALM table is {age} days old (limit "
            f"{max_table_age_days}). Cost of funds tracks the policy rate and "
            "resets at least monthly, so this table describes a different "
            "funding environment — and a stale table produces plausible rates "
            "indefinitely with nothing in the output to say so."
        )

    return PricedOffer(
        product=table.product,
        priced_on=as_of,
        alm_reference=table.source_reference,
        cost_of_funds=table.cost_of_funds,
        opex_allocation=table.opex_allocation,
        capital_charge=table.capital_charge,
        hurdle_margin=table.hurdle_margin,
        expected_loss=expected_loss.rate,
        rate_floor=table.rate_floor,
        rate_ceiling=table.rate_ceiling,
    )


def load_alm_table(product: str, tables: Mapping[str, AlmTable]) -> AlmTable:
    """Fetch the ratified table for a product, refusing a fallback.

    An unconfigured product must not borrow another product's components. A
    personal-loan funding cost applied to a gold loan is not an approximation —
    the two are funded differently, and the resulting rate is wrong in a
    direction nobody can predict.
    """
    table = tables.get(product)
    if table is None:
        raise Ungrounded(
            f"no ALM table for product {product!r} ({ALM_COMPONENTS}). Phase 4 "
            "§5 Step 2 requires funds cost, opex and hurdle from ALM tables and "
            "says they are never hard-coded; an unconfigured product cannot "
            "borrow another's, because products are funded differently and the "
            "resulting rate is wrong in an unpredictable direction."
        )
    return table

"""Exposure at default and the credit conversion factor (WS-3.1 Step 6).

Two products, two entirely different problems, and SRS §7.3.3 is explicit that
they are not the same calculation:

* **Term loans** — EAD is the amortised balance at default. That is arithmetic
  from the contract, computable with no model and no policy input, and
  :func:`scheduled_balance` does it.
* **Revolvers** (KCC, OD, credit lines) — the borrower draws down as they
  deteriorate, so EAD exceeds today's balance by an amount that has to be
  estimated: ``CCF = (EAD - B₀) / (L - B₀)``.

Why the CCF model is not fitted here
------------------------------------
It has neither data nor a floor.

*No data.* No revolving product exists on any track available to this
repository. Fannie Mae is amortising term mortgages, where ``L == B₀`` and the
CCF denominator is identically zero — the formula is not merely hard to
estimate on that data, it is undefined. Home Credit's revolving slice carries
no limit history, so ``L`` is unknown at the reference date. :func:`fit_ccf`
refuses rather than fitting the degenerate case, because a CCF regression that
silently drops every zero denominator returns a confident number computed from
whichever rows had a data error.

*No floor.* Regulatory CCF floors are `[POLICY]` (Phase 3 §8, LH-303), and a
CCF is one of the few model outputs that is routinely floored rather than used
raw.

The interfaces are here in full so that a Track B swap has something to
implement against, and so the gate report can distinguish "not measured" from
"not measurable" — which for this workstream is the honest answer.

Reference: Moral, "EAD Estimates for Facilities with Explicit Limits", in
*The Basel II Risk Parameters*, Springer 2011.

Workstream: WS-3.1 Step 6 (SRS §7.3.3)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from lending_hub.definitions.provenance import Grounded, Pending, Source, Ungrounded

#: Regulatory CCF floors, and which products they bind (Phase 3 §8).
CCF_FLOORS = Pending(
    owner="Risk Committee + Regulatory Reporting",
    ticket="LH-303",
    note="regulatory CCF floors and the products they apply to",
)

#: Minimum headroom for a CCF observation to be defined at all. Not a modelling
#: choice — below this the denominator is zero and the ratio does not exist.
MINIMUM_HEADROOM_MINOR_UNITS = Grounded(
    value=1,
    source=Source.SPEC,
    citation="SRS §7.3.3 — CCF = (EAD - B0) / (L - B0); the ratio needs L > B0",
)


class EADError(Exception):
    """The exposure calculation cannot be performed as asked."""


# --------------------------------------------------------------------------
# Term loans — arithmetic, no model
# --------------------------------------------------------------------------


def scheduled_balance(
    principal_minor_units: int,
    annual_rate: float,
    term_months: int,
    months_elapsed: int,
) -> int:
    """Outstanding balance of a level-payment amortising loan.

    ``B_n = P·[(1+i)^N - (1+i)^n] / [(1+i)^N - 1]`` with ``i`` the monthly rate.
    Returned in minor units, rounded once at the end — rounding each month
    instead accumulates a drift that shows up as an unexplained reconciliation
    break against the servicing system.

    A zero rate is handled separately rather than by a small-``i`` limit: the
    closed form divides by ``(1+i)^N - 1``, which is exactly zero there.
    """
    if principal_minor_units < 0:
        raise EADError("principal cannot be negative")
    if term_months <= 0:
        raise EADError("term must be positive")
    if annual_rate < 0:
        raise EADError("a negative annual rate is not supported")
    if months_elapsed < 0:
        raise EADError("months elapsed cannot be negative")
    if months_elapsed >= term_months:
        return 0

    if annual_rate == 0:
        remaining = (term_months - months_elapsed) / term_months
        return int(round(principal_minor_units * remaining))

    i = annual_rate / 12.0
    grown_term = (1.0 + i) ** term_months
    grown_now = (1.0 + i) ** months_elapsed
    balance = principal_minor_units * (grown_term - grown_now) / (grown_term - 1.0)
    return int(round(balance))


def term_loan_ead(
    principal_minor_units: int,
    annual_rate: float,
    term_months: int,
    months_elapsed: int,
) -> int:
    """EAD for an amortising term loan — the scheduled balance.

    No CCF and no model: a term loan has no undrawn limit to convert. Named
    separately from :func:`scheduled_balance` so that a caller reaching for
    "EAD" on a term product finds the right answer rather than assuming the
    revolver machinery applies.
    """
    return scheduled_balance(
        principal_minor_units, annual_rate, term_months, months_elapsed)


# --------------------------------------------------------------------------
# Revolvers — the CCF
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CCFObservation:
    """One defaulted revolving facility, observed at a reference date and at default.

    ``balance_at_reference`` is ``B₀`` — the drawn balance at the reference
    date, typically twelve months before default. ``limit_at_reference`` is
    ``L``. ``exposure_at_default`` is the drawn balance when default occurred.
    """

    account_id: str
    balance_at_reference: int
    limit_at_reference: int
    exposure_at_default: int

    @property
    def headroom(self) -> int:
        return self.limit_at_reference - self.balance_at_reference

    @property
    def defined(self) -> bool:
        """Whether the CCF ratio exists for this facility."""
        return self.headroom >= MINIMUM_HEADROOM_MINOR_UNITS.value


def realised_ccf(observation: CCFObservation, *, clip: bool = True) -> float:
    """``(EAD - B₀) / (L - B₀)`` for one facility.

    Raises on zero headroom rather than returning a large number or skipping
    the row. A fully-drawn facility is a real and common state, and it carries
    genuine information — but it is information about *utilisation*, not about
    conversion, and averaging it into a CCF is how a term-loan portfolio
    produces a CCF.
    """
    if not observation.defined:
        raise EADError(
            f"{observation.account_id}: limit {observation.limit_at_reference} does "
            f"not exceed balance {observation.balance_at_reference}, so there is no "
            "undrawn amount to convert and CCF is undefined. This is the normal "
            "state for a term loan and for a fully-drawn revolver; both belong "
            "outside the CCF sample, not inside it with a substituted value."
        )
    raw = (
        observation.exposure_at_default - observation.balance_at_reference
    ) / observation.headroom
    if not clip:
        return raw
    return min(1.0, max(0.0, raw))


def apply_floor(ccf: float, *, floors=CCF_FLOORS) -> float:
    """Apply the regulatory floor. Raises until LH-303 supplies it."""
    if isinstance(floors, Pending):
        raise Ungrounded(
            f"the regulatory CCF floor is not supplied: {floors}. Phase 3 §8 puts "
            "CCF floors on the do-not-invent list; an unfloored CCF is a model "
            "output, not a regulatory exposure."
        )
    return max(ccf, float(floors))


@dataclass
class CCFSample:
    """What a candidate CCF sample actually contains, before any fitting."""

    total: int
    defined: int
    zero_headroom: int

    @property
    def usable_fraction(self) -> float:
        return self.defined / self.total if self.total else 0.0

    def to_dict(self) -> dict:
        return {
            "observations": self.total,
            "ccf_defined": self.defined,
            "zero_headroom": self.zero_headroom,
            "usable_fraction": round(self.usable_fraction, 4),
        }


def inspect_sample(observations: Sequence[CCFObservation]) -> CCFSample:
    """Count how many observations have a defined CCF at all."""
    defined = sum(1 for o in observations if o.defined)
    return CCFSample(
        total=len(observations),
        defined=defined,
        zero_headroom=len(observations) - defined,
    )


def fit_ccf(observations: Sequence[CCFObservation], *_args, **_kwargs):
    """Fit a CCF model. Refuses — see the module docstring.

    This is not a stub awaiting effort. There is no revolving product on any
    track this repository can reach, so there is nothing to fit; and the output
    would be floored by a value that does not exist (LH-303). Both are reported
    together because either one alone would look like a scheduling problem.
    """
    sample = inspect_sample(observations)
    raise EADError(
        "no CCF model can be fitted here.\n"
        f"  data:  {sample.defined} of {sample.total} observations have a defined "
        "CCF. No revolving product exists on Track A or Track P — Fannie Mae is "
        "amortising term debt where L == B0 and the denominator is identically "
        "zero, and Home Credit's revolving slice carries no limit history.\n"
        f"  floor: {CCF_FLOORS} — Phase 3 §8 do-not-invent.\n"
        "term_loan_ead() covers the amortising case, which is the whole of the "
        "available book. Reported as 'not measurable' rather than 'not measured' "
        "in the Phase 3 gate pack."
    )

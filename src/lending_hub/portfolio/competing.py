"""Competing risks — prepayment against default (WS-3.1 Step 4).

A loan that prepaid did not "leave before we could see the outcome". It left in
a way that makes default impossible, and the difference between those two
statements is the whole of this module.

The error it prevents
---------------------
The standard single-risk survival model treats prepayment as censoring, which
assumes a prepaid loan would have gone on to default at the same rate as one
that stayed. That assumption is not approximately true on a mortgage book — it
is close to backwards, because the borrowers who can refinance are the ones
whose credit improved. The resulting ``1 - Π(1 - h_default)`` overstates
lifetime default, and it does so most on exactly the segments where prepayment
is heaviest, which is where pricing decisions are made.

:meth:`CompetingRisks.incidence` returns the cumulative incidence function,
which is the correct quantity, **and** the naive figure beside it, so the gap
is a number in the report rather than a caveat nobody quantified.

Two formulations, as Phase 3 asks
---------------------------------
* **Cause-specific hazards** (production): one discrete-time hazard per cause,
  combined into the CIF. Each answers "given still performing, what is the
  chance of *this* outcome this month".
* **Fine-Gray subdistribution** (sensitivity check): keeps accounts that had
  the competing event *in* the risk set, so a single hazard maps directly onto
  the CIF. Implemented as a risk-set transformation over the same GBM.

The Fine-Gray weighting caveat
------------------------------
Fine-Gray's inverse-probability-of-censoring weights are 1 whenever censoring
is purely administrative — every account observed to the same extract date —
which is the Track P case here and the case for most batch panels. Under
*random* censoring the weights are not 1 and this construction is biased;
:func:`subdistribution_rows` refuses rather than fitting quietly, because a
Fine-Gray fit that silently drops its weights looks exactly like one that did
not need them.

Reference: Fine & Gray, "A proportional hazards model for the subdistribution
of a competing risk", *JASA* 94(446), 1999.

Workstream: WS-3.1 Step 4 (SRS §7.3.2d)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from lending_hub.portfolio.hazard import HazardModel, fit_hazard
from lending_hub.portfolio.panel import Event, HazardRow, Panel, Spell
from lending_hub.scoring.gbm import MonotoneConstraints

#: The three states of the multinomial target. "perform" is the reference
#: category — the account was at risk all month and nothing happened.
CAUSES = ("default", "prepay")


class CompetingRisksError(Exception):
    """The competing-risks decomposition cannot be formed as asked."""


@dataclass
class CumulativeIncidence:
    """CIF per cause over a horizon, with the naive figure for comparison."""

    months: list[int]
    default: list[float]
    prepay: list[float]
    event_free: list[float]
    naive_default: list[float]
    normalised_months: int = 0
    """Months where the cause-specific hazards summed above 1 and were scaled
    back. Separately-fitted binary models carry no constraint that they sum to
    a probability; how often it bites is a fit-quality signal, not a detail."""

    def default_at(self, months_ahead: int) -> float:
        return self._at(self.default, months_ahead)

    def prepay_at(self, months_ahead: int) -> float:
        return self._at(self.prepay, months_ahead)

    def naive_at(self, months_ahead: int) -> float:
        return self._at(self.naive_default, months_ahead)

    def overstatement_at(self, months_ahead: int) -> float:
        """How much treating prepayment as censoring inflates lifetime default.

        Always non-negative: the naive curve ignores the chance the account
        leaves first, so it can only over-count.
        """
        return self.naive_at(months_ahead) - self.default_at(months_ahead)

    def _at(self, series: list[float], months_ahead: int) -> float:
        if months_ahead <= 0:
            return 0.0
        if months_ahead > len(series):
            raise CompetingRisksError(
                f"incidence runs {len(series)} months; asked for {months_ahead}"
            )
        return series[months_ahead - 1]

    def closes(self, tolerance: float = 1e-9) -> bool:
        """Whether ``S(t) + CIF_default(t) + CIF_prepay(t) == 1`` throughout.

        The decomposition is exhaustive by construction, so this is an
        arithmetic self-check rather than a model property — but it is the
        check that catches a sign error or a misaligned index, and those are
        the errors that produce a plausible curve.
        """
        return all(
            abs(s + d + p - 1.0) <= tolerance
            for s, d, p in zip(self.event_free, self.default, self.prepay)
        )

    def to_dict(self) -> dict:
        return {
            "months": list(self.months),
            "cif_default": [round(v, 6) for v in self.default],
            "cif_prepay": [round(v, 6) for v in self.prepay],
            "event_free_survival": [round(v, 6) for v in self.event_free],
            "naive_default_ignoring_competition": [
                round(v, 6) for v in self.naive_default
            ],
            "decomposition_closes": self.closes(1e-6),
            "months_with_hazards_renormalised": self.normalised_months,
        }


@dataclass
class CompetingRisks:
    """Cause-specific hazard models combined into a cumulative incidence."""

    default: HazardModel
    prepay: HazardModel

    @property
    def promotable(self) -> tuple[bool, str]:
        for name, model in (("default", self.default), ("prepay", self.prepay)):
            ok, why = model.promotable
            if not ok:
                return False, f"{name} hazard: {why}"
        return True, "both cause-specific hazards promotable"

    def hazards(self, covariates: dict, month: int) -> tuple[float, float, bool]:
        """``(h_default, h_prepay, renormalised)`` for one month.

        The two models are fitted separately, so nothing forces their sum below
        1. When it exceeds 1 both are scaled back proportionally — that keeps
        the CIF a probability, and the flag says it happened rather than
        hiding the repair.
        """
        h_default = self.default.hazard(covariates, month)
        h_prepay = self.prepay.hazard(covariates, month)
        total = h_default + h_prepay
        if total > 1.0:
            return h_default / total, h_prepay / total, True
        return h_default, h_prepay, False

    def incidence(
        self,
        covariates: dict,
        *,
        from_month: int,
        horizon: int,
    ) -> CumulativeIncidence:
        """Cumulative incidence for each cause over ``horizon`` months.

        ``CIF_j(t) = Σ_{k≤t} S(k-1)·h_j(k)`` — the chance of leaving by cause
        ``j`` by month ``t``, having survived everything up to ``k``. The
        ``S(k-1)`` factor is what the naive curve leaves out.
        """
        if horizon <= 0:
            raise CompetingRisksError("horizon must be positive")

        months, cif_d, cif_p, event_free, naive = [], [], [], [], []
        alive = 1.0
        naive_alive = 1.0
        cumulative_d = 0.0
        cumulative_p = 0.0
        renormalised = 0

        for step in range(1, horizon + 1):
            month = from_month + step
            h_d, h_p, scaled = self.hazards(covariates, month)
            if scaled:
                renormalised += 1

            cumulative_d += alive * h_d
            cumulative_p += alive * h_p
            alive *= (1.0 - h_d - h_p)
            naive_alive *= (1.0 - h_d)

            months.append(month)
            cif_d.append(cumulative_d)
            cif_p.append(cumulative_p)
            event_free.append(alive)
            naive.append(1.0 - naive_alive)

        return CumulativeIncidence(
            months=months,
            default=cif_d,
            prepay=cif_p,
            event_free=event_free,
            naive_default=naive,
            normalised_months=renormalised,
        )

    def to_dict(self) -> dict:
        ok, why = self.promotable
        return {
            "model": "cause_specific_discrete_time_hazards",
            "causes": list(CAUSES),
            "promotable": ok,
            "promotable_blocker": "" if ok else why,
            "default_hazard": self.default.to_dict(),
            "prepay_hazard": self.prepay.to_dict(),
        }


def fit_competing_risks(
    rows: Sequence[HazardRow],
    features: Sequence[str],
    constraints: MonotoneConstraints,
    *,
    validation_rows: Sequence[HazardRow] | None = None,
    prepay_constraints: MonotoneConstraints | None = None,
    **gbm_kwargs,
) -> CompetingRisks:
    """Fit one discrete-time hazard per cause over the same risk set.

    ``prepay_constraints`` defaults to ``constraints``, but the two are
    separable on purpose: a feature that must push default *up* often pushes
    prepayment *down*, so a single ratified direction list applied to both
    would impose a relationship nobody agreed to.
    """
    default_model = fit_hazard(
        rows, features, constraints, cause="default",
        validation_rows=validation_rows, **gbm_kwargs)
    prepay_model = fit_hazard(
        rows, features, prepay_constraints or constraints, cause="prepay",
        validation_rows=validation_rows, **gbm_kwargs)
    return CompetingRisks(default=default_model, prepay=prepay_model)


# --------------------------------------------------------------------------
# Fine-Gray subdistribution (sensitivity check)
# --------------------------------------------------------------------------


def subdistribution_rows(
    panel: Panel,
    *,
    cause: str = "default",
    horizon: int,
) -> list[HazardRow]:
    """The Fine-Gray risk set: competing-event accounts stay in it.

    In the cause-specific formulation an account that prepays leaves the risk
    set. Fine-Gray keeps it, with target 0, for every month out to the horizon —
    which is what makes a single hazard map straight onto the CIF instead of
    needing the ``S(k-1)`` factor.

    Refuses when censoring is not purely administrative. Fine-Gray's IPCW
    weights are 1 only when every account is followed to the same date; with
    accounts dropping out at different times the weights matter, and this
    construction has no way to carry them.
    """
    if cause not in CAUSES:
        raise CompetingRisksError(f"unknown cause {cause!r}; expected one of {CAUSES}")
    if horizon <= 0:
        raise CompetingRisksError("horizon must be positive")

    for spell in panel.spells:
        if spell.censored and spell.last_snapshot != panel.extract_end:
            raise CompetingRisksError(
                f"account {spell.account_id} is censored at {spell.last_snapshot}, "
                f"before the extract end {panel.extract_end}. Fine-Gray needs "
                "inverse-probability-of-censoring weights under non-administrative "
                "censoring, and this construction carries none. Use the "
                "cause-specific decomposition, which handles it correctly."
            )

    rows: list[HazardRow] = []
    for spell in panel.spells:
        spell_rows = [
            r for r in _spell_hazard_rows(spell)
            if r.months_on_book < horizon
        ]
        rows.extend(spell_rows)

        competing = (
            spell.event is not None
            and _cause_of(spell.event) not in (None, cause)
        )
        if not competing or not spell_rows:
            continue

        # Held in the risk set past the competing event, contributing zeros.
        last = spell_rows[-1]
        for m in range(last.months_on_book + 1, horizon):
            rows.append(HazardRow(
                account_id=spell.account_id,
                snapshot=last.snapshot,
                months_on_book=m,
                features=dict(last.features),
                event=None,
            ))
    return rows


def _spell_hazard_rows(spell: Spell) -> list[HazardRow]:
    from lending_hub.portfolio.panel import hazard_rows
    return hazard_rows(spell)


def _cause_of(event: Event) -> str | None:
    if event is Event.DEFAULT:
        return "default"
    if event in (Event.PREPAID, Event.MATURED):
        return "prepay"
    return None


def observed_incidence(
    panel: Panel,
    *,
    horizon: int,
) -> CumulativeIncidence:
    """Non-parametric Aalen-Johansen incidence — the curve a model must match.

    The empirical counterpart of :meth:`CompetingRisks.incidence`, built from
    observed cause-specific hazards rather than a fitted model. This is the
    benchmark: a competing-risks model that does not reproduce it on the
    training sample has a problem no metric on the default cause will reveal.
    """
    if horizon <= 0:
        raise CompetingRisksError("horizon must be positive")

    rows = panel.hazard()
    at_risk: dict[int, int] = {}
    events: dict[str, dict[int, int]] = {c: {} for c in CAUSES}
    for row in rows:
        at_risk[row.months_on_book] = at_risk.get(row.months_on_book, 0) + 1
        if row.cause in events:
            bucket = events[row.cause]
            bucket[row.months_on_book] = bucket.get(row.months_on_book, 0) + 1

    months, cif_d, cif_p, event_free, naive = [], [], [], [], []
    alive = 1.0
    naive_alive = 1.0
    cumulative_d = cumulative_p = 0.0

    for m in range(horizon):
        n = at_risk.get(m, 0)
        h_d = events["default"].get(m, 0) / n if n else 0.0
        h_p = events["prepay"].get(m, 0) / n if n else 0.0
        cumulative_d += alive * h_d
        cumulative_p += alive * h_p
        alive *= (1.0 - h_d - h_p)
        naive_alive *= (1.0 - h_d)
        months.append(m)
        cif_d.append(cumulative_d)
        cif_p.append(cumulative_p)
        event_free.append(alive)
        naive.append(1.0 - naive_alive)

    return CumulativeIncidence(
        months=months, default=cif_d, prepay=cif_p,
        event_free=event_free, naive_default=naive,
    )

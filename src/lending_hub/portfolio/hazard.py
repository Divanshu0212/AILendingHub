"""Discrete-time hazard model — the Phase 3 production challenger (WS-3.1 Step 3).

Survival recast as a classification problem the platform already knows how to
solve: one row per account-month at risk, target "the event happened in *this*
month", and a survival curve rebuilt afterwards as ``S(t) = Π(1 - h_k)``.

That recasting is the whole trick, and it buys three things Cox cannot give
here. Censoring is handled by construction — a censored account simply stops
contributing rows, with no weighting scheme. Time-varying covariates need no
special formulation, because each row already carries its own month's values.
And the month is modelled *directly* rather than approximated around, which
matters on a monthly panel where Cox's continuous-time likelihood is tying
~96% of its events (see :mod:`lending_hub.portfolio.cox`).

Reusing the Phase 1 GBM
-----------------------
This module fits **no boosting machinery of its own**. Master §2 rule 2 allows
one reference implementation per algorithm, and
:func:`lending_hub.scoring.gbm.fit_gbm` is it. What is here is the recasting,
the survival reconstruction, and the assumptions both require — which is the
part that is specific to survival and the part worth reviewing.

Two assumptions, stated because they are otherwise invisible
------------------------------------------------------------
1. **Covariates are carried forward.** ``S(t)`` for an account observed today
   needs hazards at months it has not reached, so the covariates are held at
   their last observed values while ``months_on_book`` advances. Behavioural
   features drift, so a 60-month curve is more assumption than measurement past
   the first year. :meth:`SurvivalCurve.extrapolated_from` records where the
   measured part stops.
2. **The baseline is learned, not dummied.** Phase 3 WS-3.1 Step 3 says
   "month-on-book dummies for the baseline hazard", which is right for the
   canonical *logistic* discrete-time model and wrong for a tree ensemble:
   dummies discard the ordering of months, so the model cannot pool information
   between month 13 and month 14 and must relearn each one. ``months_on_book``
   is passed as an ordered numeric feature instead and the tree recovers the
   baseline shape itself; :func:`baseline_hazard` reads it back out for the
   diagnostic the dummies existed to provide. Raised as a Phase 3 finding.

Reference: Tutz & Schmid, *Modeling Discrete Time-to-Event Data*, Springer 2016;
Dirick, Claeskens & Baesens, *JORS* 68(6), 2017.

Workstream: WS-3.1 Step 3 (SRS §7.3.2c)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from lending_hub.portfolio.panel import HazardRow
from lending_hub.scoring.gbm import (
    UNCONSTRAINED,
    GBM,
    GBMError,
    MonotoneConstraints,
    fit_gbm,
)

#: The month-on-book column. Named once so the feature list, the constraint
#: set and the survival reconstruction cannot drift apart.
TIME_FEATURE = "months_on_book"


class HazardError(Exception):
    """The hazard model cannot be fitted or read as asked."""


def hazard_design(
    rows: Sequence[HazardRow],
    features: Sequence[str],
    *,
    cause: str = "default",
) -> tuple[list[dict], list[int]]:
    """Design matrix and target for the discrete-time hazard.

    ``cause`` selects which competing event is the target. Rows for *other*
    causes stay in the sample with target 0 — they were at risk during that
    month, and dropping them would remove exactly the accounts whose leaving
    the model is supposed to explain.
    """
    if TIME_FEATURE in features:
        raise HazardError(
            f"{TIME_FEATURE!r} is added automatically; listing it again would "
            "put the baseline in the design matrix twice"
        )
    design: list[dict] = []
    labels: list[int] = []
    for row in rows:
        record = {name: row.features.get(name) for name in features}
        record[TIME_FEATURE] = row.months_on_book
        design.append(record)
        labels.append(1 if row.cause == cause else 0)
    return design, labels


def hazard_features(features: Sequence[str]) -> list[str]:
    """The model's feature list: the caller's, plus the time axis."""
    return list(features) + [TIME_FEATURE]


def with_time_axis(constraints: MonotoneConstraints) -> MonotoneConstraints:
    """Extend a constraint set with the time axis, explicitly unconstrained.

    The P1 GBM requires a direction for *every* feature so that nothing is
    unconstrained by accident. ``months_on_book`` genuinely must be
    unconstrained — the baseline hazard rises to a seasoning peak and falls
    again, so either direction would force away the shape the model is there to
    find — and this records that as a decision rather than an omission. The
    ratified flag is carried through untouched: adding the time axis is not a
    route to marking an unratified list ratified.
    """
    if TIME_FEATURE in constraints.directions:
        if constraints.directions[TIME_FEATURE] != UNCONSTRAINED:
            raise HazardError(
                f"{TIME_FEATURE!r} already carries a monotone direction. The "
                "baseline hazard is not monotone in months on book, so a "
                "constraint on it forces the shape the model exists to discover."
            )
        return constraints
    return MonotoneConstraints(
        directions={**constraints.directions, TIME_FEATURE: UNCONSTRAINED},
        ratified=constraints.ratified,
        provenance=(
            f"{constraints.provenance}; {TIME_FEATURE} unconstrained by "
            "construction (discrete-time baseline hazard)"
        ),
    )


@dataclass
class SurvivalCurve:
    """``S(t)`` for one account, rebuilt from month-by-month hazards."""

    account_id: str
    from_month: int
    hazards: list[float]
    survival: list[float]
    observed_until: int

    @property
    def horizon(self) -> int:
        return len(self.hazards)

    def at(self, months_ahead: int) -> float:
        """S at ``months_ahead`` months from the observation point."""
        if months_ahead <= 0:
            return 1.0
        if months_ahead > len(self.survival):
            raise HazardError(
                f"curve runs {len(self.survival)} months; asked for {months_ahead}"
            )
        return self.survival[months_ahead - 1]

    def pd(self, months_ahead: int) -> float:
        """Cumulative default probability over the next ``months_ahead`` months."""
        return 1.0 - self.at(months_ahead)

    @property
    def extrapolated_from(self) -> int:
        """The month after which the curve rests on carried-forward covariates.

        Everything past this point is a projection under assumption 1 above.
        Reporting it beside the curve is the difference between a lifetime PD
        that can be defended and one that cannot.
        """
        return max(0, self.observed_until - self.from_month)

    def to_dict(self) -> dict:
        return {
            "account_id": self.account_id,
            "from_month": self.from_month,
            "horizon_months": self.horizon,
            "extrapolated_from_month": self.extrapolated_from,
            "survival": [round(v, 6) for v in self.survival],
            "hazards": [round(v, 6) for v in self.hazards],
        }


@dataclass
class HazardModel:
    """A fitted discrete-time hazard model and the survival maths over it."""

    gbm: GBM
    features: list[str]
    cause: str
    rows_fitted: int
    events_fitted: int

    @property
    def promotable(self) -> tuple[bool, str]:
        """Governance state, with the ticket that actually owns this feature set.

        The GBM reports LH-202, which is the *application* direction list. The
        behavioural features here — DPD trajectory, utilisation trend,
        times-in-arrears — are a different set and were never ratified; that is
        LH-310. Delegating the message unchanged would send a reader to the
        wrong committee, and the committee would correctly say the question was
        already answered.
        """
        ok, why = self.gbm.promotable
        if ok:
            return True, why
        if not self.gbm.constraints.ratified:
            return False, (
                "monotone directions for the behavioural feature set are not "
                "ratified (LH-310). LH-202 covers application features only; the "
                "behavioural set is different and needs its own direction list."
            )
        return False, why

    def hazard(self, covariates: dict, months_on_book: int) -> float:
        """``h(m | x)`` — P(event in month m | alive at the start of it)."""
        row = dict(covariates)
        row[TIME_FEATURE] = months_on_book
        return self.gbm.predict(row)

    def curve(
        self,
        covariates: dict,
        *,
        from_month: int,
        horizon: int,
        account_id: str = "",
        observed_until: int | None = None,
    ) -> SurvivalCurve:
        """``S(t)`` for ``horizon`` months beyond ``from_month``.

        The product form ``Π(1 - h_k)`` is exact for discrete time — it is not
        an approximation to a continuous-time integral, which is the usual
        reason to be nervous about a cumulative-product survival curve.
        """
        if horizon <= 0:
            raise HazardError("horizon must be positive")
        if from_month < 0:
            raise HazardError("from_month cannot be negative")

        hazards: list[float] = []
        survival: list[float] = []
        alive = 1.0
        for step in range(1, horizon + 1):
            h = self.hazard(covariates, from_month + step)
            hazards.append(h)
            alive *= (1.0 - h)
            survival.append(alive)
        return SurvivalCurve(
            account_id=account_id,
            from_month=from_month,
            hazards=hazards,
            survival=survival,
            observed_until=from_month if observed_until is None else observed_until,
        )

    def lifetime_pd(self, covariates: dict, *, from_month: int, remaining_term: int) -> float:
        """Lifetime PD over the remaining contractual term (IFRS-9 input)."""
        return self.curve(
            covariates, from_month=from_month, horizon=remaining_term
        ).pd(remaining_term)

    def to_dict(self) -> dict:
        ok, why = self.promotable
        return {
            "model": "discrete_time_hazard_gbm",
            "cause": self.cause,
            "features": list(self.features),
            "time_feature": TIME_FEATURE,
            "rows_fitted": self.rows_fitted,
            "events_fitted": self.events_fitted,
            "event_rate_per_account_month": (
                self.events_fitted / self.rows_fitted if self.rows_fitted else None
            ),
            "promotable": ok,
            "promotable_blocker": "" if ok else why,
            "gbm": self.gbm.to_dict(),
        }


def fit_hazard(
    rows: Sequence[HazardRow],
    features: Sequence[str],
    constraints: MonotoneConstraints,
    *,
    cause: str = "default",
    validation_rows: Sequence[HazardRow] | None = None,
    **gbm_kwargs,
) -> HazardModel:
    """Fit the discrete-time hazard by boosting on the account-month risk set.

    Every keyword beyond ``cause`` and ``validation_rows`` is passed through to
    :func:`lending_hub.scoring.gbm.fit_gbm` untouched — there is one boosting
    implementation in this repo and this is not a second one.
    """
    if not rows:
        raise HazardError("cannot fit a hazard model on an empty risk set")

    design, labels = hazard_design(rows, features, cause=cause)
    events = sum(labels)
    if events == 0:
        raise HazardError(
            f"no {cause!r} events in the risk set. A hazard model fitted with no "
            "events predicts a constant zero, which scores perfectly on every "
            "discrimination metric that ignores the base rate."
        )

    all_features = hazard_features(features)
    constraints = with_time_axis(constraints)
    for name in features:
        try:
            constraints.direction(name)
        except GBMError as exc:
            raise HazardError(str(exc)) from exc

    validation = None
    if validation_rows:
        v_design, v_labels = hazard_design(validation_rows, features, cause=cause)
        validation = (v_design, v_labels)

    gbm = fit_gbm(design, labels, all_features, constraints,
                  validation=validation, **gbm_kwargs)

    return HazardModel(
        gbm=gbm,
        features=all_features,
        cause=cause,
        rows_fitted=len(design),
        events_fitted=events,
    )


def baseline_hazard(
    model: HazardModel,
    reference: dict,
    *,
    max_month: int,
) -> list[tuple[int, float]]:
    """The fitted hazard by month on book at a fixed covariate vector.

    This is the diagnostic the month-on-book dummies were there to provide:
    the shape of the baseline, read back out of a model that learned it from an
    ordered numeric feature instead. Evaluated at ``reference`` because a tree
    ensemble has no "at the mean" in the GLM sense — the caller must say which
    account the baseline is drawn for, and the answer depends on it.
    """
    if max_month < 1:
        raise HazardError("max_month must be at least 1")
    return [(m, model.hazard(reference, m)) for m in range(1, max_month + 1)]


def observed_hazard(rows: Sequence[HazardRow], *, cause: str = "default") -> list[tuple[int, float]]:
    """Empirical hazard by month on book — the curve the model must match.

    The denominator is the number *at risk* in that month, not the number of
    accounts. Using the account count would divide by a constant and turn the
    hazard into a density, which falls away at long durations for the trivial
    reason that few accounts get there.
    """
    at_risk: dict[int, int] = {}
    events: dict[int, int] = {}
    for row in rows:
        at_risk[row.months_on_book] = at_risk.get(row.months_on_book, 0) + 1
        if row.cause == cause:
            events[row.months_on_book] = events.get(row.months_on_book, 0) + 1
    return [
        (m, events.get(m, 0) / at_risk[m])
        for m in sorted(at_risk)
        if at_risk[m] > 0
    ]

"""Agri triggers — deterministic rules over the P2 monitoring stream (WS-4.A Step 4).

Phase 4 §4 Step 4 states four things, and the fourth is the one that carries
policy weight:

    Non-sowing by policy cutoff date; NDVI z-score < −1.5 at crop-critical stage
    on >= 2 consecutive revisits; district SPEI-3 <= −1.5. **District-wide events
    route to portfolio actions** (restructuring campaigns per RBI
    natural-calamity norms), **not individual collection pressure**.

Why that last sentence is the whole module
--------------------------------------------
A drought is not a credit event caused by a borrower. When SPEI-3 for a district
crosses −1.5, every farmer in it is affected simultaneously, and the correct
response is a restructuring campaign under RBI natural-calamity norms — not
three hundred collection calls. Routing a district event down the individual
path is wrong in three separate ways at once:

* it is **operationally absurd** — the whole district alerts on the same day and
  buries the officers covering it (which is LH-507, the per-officer cap);
* it is **analytically wrong** — the signal says nothing about any individual
  borrower's behaviour, so it has no discriminating power *within* the district,
  and its per-signal precision would be measured against a base rate it cannot
  beat;
* it is **conduct-relevant** — pressing farmers for repayment during a declared
  calamity is the behaviour RBI's norms exist to prevent.

So :class:`AgriTrigger` carries a :class:`TriggerScope`, and
:func:`route_by_scope` separates the two streams structurally. There is no
configuration in which a district trigger produces an individual action.

Deterministic, and that is a feature
--------------------------------------
Unlike every other Workstream A signal, these are rules rather than models. A
non-sowing flag is a calendar comparison; an SPEI threshold is a lookup. That
makes them the only signals in the catalogue whose behaviour is fully
predictable before deployment — worth stating because it means their failure
mode is a *wrong input*, not a wrong inference, and the input quality checks
matter more here than any threshold.

What is blocked
----------------
The **non-sowing cutoff date is the crop calendar** (LH-102), so
:func:`non_sowing_trigger` cannot fire without it. The two remote-sensing
thresholds are `[SPEC]` from the phase file and are constants here. And the
relief treatment a district trigger routes *to* is LH-506 / LH-405 — this
module can identify the event and refuses to name the action.

What this does not port
-----------------------
No streaming, and no imagery. NDVI z-scores and SPEI values arrive from the P2
package (``agri.indices``, ``agri.drought``); this module consumes them. Phase 2
has no Track P at all (ADR-0013), so nothing here has ever been evaluated on a
real plot.

Workstream: WS-4.A Step 4 (SRS §10.3 agri, §3)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Sequence

from lending_hub.agri.drought import DroughtIndex
from lending_hub.definitions import AGRI_SEASON_CALENDAR
from lending_hub.definitions.provenance import Grounded, Pending, Source, Ungrounded

#: NDVI z-score below which a plot is flagged, at a crop-critical stage.
#: `[SPEC]` — Phase 4 §4 Step 4 states −1.5.
NDVI_ZSCORE_THRESHOLD = Grounded(
    value=-1.5, source=Source.SPEC, citation="Phase 4 §4 Step 4"
)

#: Consecutive revisits the NDVI z-score must stay below the threshold.
#: `[SPEC]` — Phase 4 §4 Step 4 states ">= 2 consecutive revisits". The
#: requirement is a cloud-artefact guard: a single depressed reading is as
#: likely to be thin cloud as crop stress (see `agri.indices`).
NDVI_CONSECUTIVE_REVISITS = Grounded(
    value=2, source=Source.SPEC, citation="Phase 4 §4 Step 4"
)

#: District SPEI-3 at or below which a district-wide drought event is raised.
#: `[SPEC]` — Phase 4 §4 Step 4 states −1.5. Note this is *stricter* than the
#: WS-2.3 drought-frequency threshold of −1.0: that one counts historical dry
#: seasons for a land-quality feature, this one triggers an action now. Same
#: index, different purposes, and aliasing them would make a routine dry season
#: launch a restructuring campaign.
SPEI_DISTRICT_THRESHOLD = Grounded(
    value=-1.5, source=Source.SPEC, citation="Phase 4 §4 Step 4"
)

#: The SPEI timescale the district trigger reads. `[SPEC]` — "SPEI-3".
SPEI_TIMESCALE_MONTHS = Grounded(
    value=3, source=Source.SPEC, citation="Phase 4 §4 Step 4"
)

#: What a district calamity event actually does to obligations, ageing and the
#: default label. `[POLICY]` under RBI norms — the same value Phase 2 registered
#: as LH-405, repeated here because Phase 4 is where it becomes an *action*.
CALAMITY_RELIEF_TREATMENT = Pending(
    owner="Credit Policy + Compliance",
    ticket="LH-506",
    note="RBI natural-calamity relief treatment: obligations, ageing, labelling",
)


class AgriTriggerError(Exception):
    """An agri trigger cannot be evaluated on what was supplied."""


class TriggerScope(str, Enum):
    """Whether a trigger is about one borrower or about a whole district.

    The distinction that Phase 4 §4 Step 4 makes load-bearing. It is an enum
    rather than a boolean because the routing decision reads it and a boolean
    named ``is_district`` invites ``not is_district`` to mean "individual",
    which stops being true the moment a third scope (a block, a mandi
    catchment) is added.
    """

    INDIVIDUAL = "individual"
    """About this borrower's plot: their crop, their sowing, their land."""

    DISTRICT = "district"
    """About every borrower in the district simultaneously. Routes to portfolio
    action, never to individual collection pressure."""


class AgriTriggerType(str, Enum):
    NON_SOWING = "non_sowing"
    NDVI_STRESS = "ndvi_stress"
    DISTRICT_DROUGHT = "district_drought"


@dataclass(frozen=True)
class AgriTrigger:
    """One fired agri trigger, with the scope that decides how it is routed."""

    trigger_type: AgriTriggerType
    scope: TriggerScope
    subject_id: str
    """Plot or borrower id for an individual trigger; district code for a
    district one. Typed loosely on purpose — the routing layer must not be able
    to treat a district code as a borrower."""

    observed_on: date
    detail: str
    evidence: dict

    def __post_init__(self) -> None:
        if not self.subject_id:
            raise AgriTriggerError("a trigger must name its subject")
        if not self.detail:
            raise AgriTriggerError(
                f"{self.trigger_type.value}: a trigger must carry a human-readable "
                "reason. Phase 4 §4 Step 5 requires trigger reasons on every "
                "case, and a reason generated at routing time is a reason nobody "
                "can trace to the rule that fired."
            )

    @property
    def permits_individual_action(self) -> bool:
        """Whether this trigger may result in contacting one borrower.

        False for every district-scoped trigger, unconditionally. See the module
        docstring for the three independent reasons.
        """
        return self.scope is TriggerScope.INDIVIDUAL


def non_sowing_trigger(
    plot_id: str,
    *,
    sowing_observed: bool,
    as_of: date,
    cutoff: date | None = None,
) -> AgriTrigger | None:
    """Fire when sowing has not been observed by the policy cutoff date.

    ``cutoff`` is the sowing window's end for this zone and crop, which comes
    from the ratified crop calendar (LH-102) and the sowing windows (LH-402).
    It has no default and raises when absent: a cutoff invented here would
    declare a farmer to have failed to sow while they were still inside their
    actual planting window, which is both wrong and the most damaging possible
    false positive in this workstream — it fires at the exact moment a farmer
    needs an input loan rather than a collections call.
    """
    if cutoff is None:
        raise Ungrounded(
            f"the sowing cutoff date for {plot_id} is not grounded "
            f"({AGRI_SEASON_CALENDAR}). Phase 2 §8 and Phase 4 §9 both forbid "
            "inventing a crop calendar, and a cutoff guessed here would declare "
            "a farmer to have failed to sow while they were still inside their "
            "planting window — firing exactly when they need an input loan "
            "rather than a collections call."
        )
    if sowing_observed:
        return None
    if as_of < cutoff:
        return None

    return AgriTrigger(
        trigger_type=AgriTriggerType.NON_SOWING,
        scope=TriggerScope.INDIVIDUAL,
        subject_id=plot_id,
        observed_on=as_of,
        detail=(
            f"no sowing observed by the ratified cutoff {cutoff} "
            f"(as of {as_of}, {(as_of - cutoff).days} days past)"
        ),
        evidence={"cutoff": cutoff.isoformat(), "days_past_cutoff": (as_of - cutoff).days},
    )


@dataclass(frozen=True)
class NdviObservation:
    """One plot NDVI z-score at one revisit, with its crop-stage flag.

    ``crop_critical`` comes from the crop calendar: whether this revisit falls
    in a stage where depressed vigour predicts yield loss. Outside those stages
    a low NDVI is normal — a harvested field reads near zero and is not in
    distress.
    """

    plot_id: str
    acquired: date
    z_score: float
    crop_critical: bool


def ndvi_stress_trigger(
    observations: Sequence[NdviObservation],
    *,
    threshold: float | None = None,
    consecutive: int | None = None,
) -> AgriTrigger | None:
    """Fire on sustained depressed vigour at a crop-critical stage.

    Requires the z-score to stay below the threshold across consecutive
    *crop-critical* revisits. Both parts matter: the consecutive requirement is
    a cloud guard (a single depressed reading is as likely to be thin cloud as
    crop stress), and the crop-critical filter stops a harvested field reading
    as a failed one.

    Observations must be in ascending date order — "consecutive" is meaningless
    otherwise, and an unordered series would silently satisfy the rule from
    non-adjacent revisits.
    """
    limit = threshold if threshold is not None else NDVI_ZSCORE_THRESHOLD.value
    run_required = consecutive if consecutive is not None else NDVI_CONSECUTIVE_REVISITS.value

    if run_required < 1:
        raise AgriTriggerError(f"consecutive revisits must be >= 1, got {run_required}")
    if not observations:
        return None

    dates = [o.acquired for o in observations]
    if dates != sorted(dates):
        raise AgriTriggerError(
            "NDVI observations are not in ascending date order. 'Consecutive' "
            "has no meaning on an unordered series, and the rule would be "
            "satisfied by non-adjacent revisits."
        )
    if len({o.plot_id for o in observations}) > 1:
        raise AgriTriggerError(
            "observations span more than one plot; a stress run is a property "
            "of a single plot's trajectory"
        )

    critical = [o for o in observations if o.crop_critical]
    run: list[NdviObservation] = []
    for observation in critical:
        if observation.z_score < limit:
            run.append(observation)
            if len(run) >= run_required:
                return AgriTrigger(
                    trigger_type=AgriTriggerType.NDVI_STRESS,
                    scope=TriggerScope.INDIVIDUAL,
                    subject_id=observation.plot_id,
                    observed_on=observation.acquired,
                    detail=(
                        f"NDVI z-score below {limit} on {len(run)} consecutive "
                        f"crop-critical revisits "
                        f"({run[0].acquired} to {run[-1].acquired})"
                    ),
                    evidence={
                        "z_scores": [round(o.z_score, 3) for o in run],
                        "threshold": limit,
                        "revisits": len(run),
                    },
                )
        else:
            run = []
    return None


def district_drought_trigger(
    district_code: str,
    spei: DroughtIndex,
    *,
    observed_on: date,
    threshold: float | None = None,
) -> AgriTrigger | None:
    """Fire a **district-scoped** event on SPEI-3 at or below the threshold.

    ``observed_on`` is required and is not derived from the clock.
    :class:`DroughtIndex` carries a *calendar month* rather than a date, because
    it is fitted per calendar month across many years — so there is no year in
    it to read. Defaulting to today would stamp every case in a historical
    backtest with the current year, which is invisible in the output and
    destroys the lead-time measurement that is the whole point of the backtest.

    Refuses an index computed at a timescale other than SPEI-3. That is not
    pedantry: SPEI-1 tracks a dry month and SPEI-12 a dry year, and the phase
    file specifies 3 because it matches a cropping season. Reading a SPEI-12
    against a −1.5 threshold declares a calamity from a different phenomenon.
    """
    limit = threshold if threshold is not None else SPEI_DISTRICT_THRESHOLD.value

    if spei.timescale_months != SPEI_TIMESCALE_MONTHS.value:
        raise AgriTriggerError(
            f"{district_code}: SPEI-{spei.timescale_months} supplied where "
            f"SPEI-{SPEI_TIMESCALE_MONTHS.value} is specified. SPEI-1 tracks a "
            "dry month and SPEI-12 a dry year; the phase file specifies 3 "
            "because it matches a cropping season, and reading another "
            "timescale against this threshold declares a calamity from a "
            "different phenomenon."
        )

    if spei.value > limit:
        return None

    return AgriTrigger(
        trigger_type=AgriTriggerType.DISTRICT_DROUGHT,
        scope=TriggerScope.DISTRICT,
        subject_id=district_code,
        observed_on=observed_on,
        detail=(
            f"district SPEI-{spei.timescale_months} at {spei.value:.3f}, "
            f"at or below {limit} ({spei.category})"
        ),
        evidence={
            "spei": round(spei.value, 4),
            "timescale_months": spei.timescale_months,
            "category": spei.category,
            "fitted_on_seasons": spei.fitted_on,
            "calendar_month": spei.calendar_month,
        },
    )


@dataclass(frozen=True)
class ScopedRouting:
    """Triggers split by what may be done about them."""

    individual: tuple[AgriTrigger, ...]
    portfolio: tuple[AgriTrigger, ...]

    @property
    def portfolio_districts(self) -> tuple[str, ...]:
        return tuple(sorted({t.subject_id for t in self.portfolio}))

    def suppressed_borrowers(self, district_of: dict[str, str]) -> tuple[str, ...]:
        """Individual triggers suppressed because their district is in calamity.

        Phase 4 §5 Step 5 makes this a **suitability duty**: a drought flag
        means "suppress marketing, offer restructuring". The same logic applies
        to collections — an individual non-sowing trigger inside a
        drought-declared district is not evidence about that farmer, it is the
        district event observed one plot at a time, and acting on it
        individually is the pressure §4 Step 4 forbids.
        """
        affected = set(self.portfolio_districts)
        return tuple(
            sorted(
                t.subject_id
                for t in self.individual
                if district_of.get(t.subject_id) in affected
            )
        )


def route_by_scope(triggers: Sequence[AgriTrigger]) -> ScopedRouting:
    """Split triggers into individual and portfolio streams.

    The structural enforcement of Phase 4 §4 Step 4. There is no argument that
    makes a district trigger route to individual action.
    """
    return ScopedRouting(
        individual=tuple(t for t in triggers if t.permits_individual_action),
        portfolio=tuple(t for t in triggers if not t.permits_individual_action),
    )


def relief_action(trigger: AgriTrigger) -> str:
    """What a district calamity trigger should cause. Raises.

    The module can identify the event; naming the action is RBI norm
    interpretation and bank policy (LH-506). This raising stub exists so the
    routing path is complete and the gap is visible at the point of use rather
    than as an absence.
    """
    if trigger.scope is not TriggerScope.DISTRICT:
        raise AgriTriggerError(
            f"{trigger.subject_id}: relief actions apply to district events, not "
            f"{trigger.scope.value} ones"
        )
    raise Ungrounded(
        f"the natural-calamity relief treatment is not ratified "
        f"({CALAMITY_RELIEF_TREATMENT}). Phase 4 §4 Step 4 routes district "
        "events to 'restructuring campaigns per RBI natural-calamity norms', "
        "which names the source of the rule and not the rule. What a "
        "declaration does to obligations, DPD ageing and the default label is a "
        "policy mapping, and a restructuring offered on invented terms is a "
        "contractual variation nobody approved."
    )

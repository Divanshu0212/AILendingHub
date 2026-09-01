"""Account-month panel — the substrate every Phase 3 model reads.

Phase 3 asks four different questions of the same rows, and the questions want
different shapes:

* **Behavioural PD** (WS-3.1 Step 1) wants one row per account-month with a
  *forward-looking* target: does this account default in the next 12 months?
* **Discrete-time hazard** (WS-3.1 Step 3) wants the *risk set*: one row per
  account-month the account was still alive at the start of, with a target of
  "the event happened in this month".
* **Competing risks** (WS-3.1 Step 4) wants the same risk set with a
  three-valued event, because a prepaid loan has not been censored — it has
  left in a way that makes default impossible.
* **Transition matrices** (WS-3.2 Step 2) want consecutive month pairs.

Building those four shapes from one :class:`Spell` is the whole point of this
module. The alternative — each model slicing the raw performance rows itself —
is how a behavioural model ends up with the current month's DPD on both sides
of the equation.

Point-in-time discipline (Master Appendix A, *Observation point*)
-----------------------------------------------------------------
For a snapshot at month ``t``, features may use months ``<= t`` and the target
may use months ``> t``. There is no overlap and no configuration that creates
one. This is stricter than it looks: on a behavioural panel the leak is not an
exotic join, it is the natural thing to write, because the DPD column that
defines the target is sitting in the feature row.

What this does not port
-----------------------
No Delta/Iceberg time travel and no Feast point-in-time join — those are the
Track B backends behind ``featurestore.ports``. This builds the panel in memory
from an iterator of observations, which is what a laptop can do and what a test
can assert on.

Workstream: WS-3.1 (SRS §7.3.1, §7.3.2), WS-3.2 (SRS §9.3.2)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Iterable, Iterator, Sequence

from lending_hub.definitions import (
    DEFAULT_DPD_THRESHOLD_DAYS,
    OUTCOME_WINDOW_MONTHS,
    Label,
    OutcomeObservation,
    label,
    month_end,
)

#: Appendix A's behavioural outcome window: "next-12-months rolling". Imported,
#: never retyped (Master §2 rule 6) — the application and behavioural windows
#: are the same number today and there is no guarantee they stay that way.
BEHAVIOURAL_HORIZON_MONTHS = OUTCOME_WINDOW_MONTHS.value


class PanelError(Exception):
    """The panel does not satisfy an invariant a downstream model relies on."""


class Event(str, Enum):
    """How a spell ended. Absence of an event is censoring, not an event."""

    DEFAULT = "default"
    """Appendix A default observed. The spell ends at first default: a model of
    time-to-*first*-default must not keep an account at risk after the event it
    is predicting, and Fannie loans do cure and re-default."""

    PREPAID = "prepaid"
    """Closed without credit loss — paid off, refinanced, or matured. A
    competing risk, emphatically not a censoring event: the account did not
    "leave before we could see", it left in a way that makes default
    impossible."""

    MATURED = "matured"
    """Ran to scheduled term. Kept distinct from PREPAID because prepayment is
    a *behaviour* worth modelling and maturity is the contract expiring; a
    prepayment model that counts maturities is measuring the amortisation
    schedule."""


#: Events that terminate the spell without a credit loss. Both compete with
#: default; the distinction between them matters to the prepayment model, not
#: to the default one.
NON_LOSS_EVENTS = frozenset({Event.PREPAID, Event.MATURED})


@dataclass(frozen=True)
class AccountMonth:
    """One account, one month-end snapshot.

    ``dpd`` is ``None`` when the servicer reported no status, never ``0``.
    Collapsing an unreported month to "current" is the single easiest way to
    understate a default rate, and it is silent — the row still looks complete.
    """

    account_id: str
    snapshot: date
    months_on_book: int
    dpd: int | None
    balance_minor_units: int = 0
    features: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.snapshot != month_end(self.snapshot):
            raise PanelError(
                f"{self.account_id}: snapshot {self.snapshot} is not a month-end. "
                "Appendix A fixes the behavioural observation point at month-end; "
                "a mid-month snapshot silently changes what 'as of' means."
            )
        if self.months_on_book < 0:
            raise PanelError(
                f"{self.account_id}: months_on_book {self.months_on_book} is negative"
            )

    @property
    def observed(self) -> bool:
        return self.dpd is not None

    @property
    def in_default(self) -> bool:
        """Whether this month's DPD alone meets the Appendix A DPD arm."""
        return self.dpd is not None and self.dpd >= DEFAULT_DPD_THRESHOLD_DAYS.value


@dataclass
class Spell:
    """One account's observed history and how it ended.

    A spell is censored when ``event is None``: the account was still alive and
    still on the book when the extract stopped. That is a different statement
    from "nothing happened", and every model here has to treat it as one.
    """

    account_id: str
    months: list[AccountMonth]
    event: Event | None = None
    event_month: date | None = None
    origination: date | None = None
    attributes: dict = field(default_factory=dict)
    """Origination-time attributes, constant over the spell. Kept off the
    monthly rows so that a feature builder cannot accidentally treat one as
    time-varying and read a later value."""

    def __post_init__(self) -> None:
        self.months.sort(key=lambda m: m.snapshot)
        seen = set()
        for m in self.months:
            if m.account_id != self.account_id:
                raise PanelError(
                    f"spell {self.account_id} contains a month for {m.account_id}"
                )
            if m.snapshot in seen:
                raise PanelError(
                    f"{self.account_id}: duplicate snapshot {m.snapshot}. Two rows "
                    "for one account-month means the panel key is wrong, and every "
                    "count computed from it is inflated by an unknown factor."
                )
            seen.add(m.snapshot)
        if (self.event is None) != (self.event_month is None):
            raise PanelError(
                f"{self.account_id}: event and event_month must be set together — "
                f"got event={self.event}, event_month={self.event_month}"
            )
        if self.event_month is not None and self.months:
            if self.event_month < self.months[0].snapshot:
                raise PanelError(
                    f"{self.account_id}: event at {self.event_month} precedes the "
                    f"first observed month {self.months[0].snapshot}"
                )

    @property
    def last_snapshot(self) -> date | None:
        return self.months[-1].snapshot if self.months else None

    @property
    def censored(self) -> bool:
        return self.event is None

    def month_at(self, snapshot: date) -> AccountMonth | None:
        for m in self.months:
            if m.snapshot == snapshot:
                return m
        return None

    def window(self, start_exclusive: date, end_inclusive: date) -> list[AccountMonth]:
        """Months in ``(start, end]`` — the target window, never the feature one."""
        return [
            m for m in self.months
            if start_exclusive < m.snapshot <= end_inclusive
        ]


def add_months(day: date, months: int) -> date:
    """Month-end ``months`` after ``day``'s month. Calendar-safe at year ends."""
    total = (day.year * 12 + day.month - 1) + months
    return month_end(date(total // 12, total % 12 + 1, 1))


def months_between(start: date, end: date) -> int:
    return (end.year * 12 + end.month) - (start.year * 12 + start.month)


# --------------------------------------------------------------------------
# Shape 1 — behavioural targets (WS-3.1 Step 1)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class BehaviouralRow:
    """One account-month with a forward-looking Appendix A label.

    ``label`` is ``None`` when the outcome is *not determined* — the window ran
    past the end of the extract. That is distinct from INDETERMINATE, which is
    a determined outcome that Appendix A excludes from training. Merging the
    two loses the ability to say how much of the panel is unusable because it
    is recent versus how much is unusable because it is ambiguous, and only the
    first shrinks as data arrives.
    """

    account_id: str
    snapshot: date
    months_on_book: int
    features: dict
    label: Label | None
    window_end: date
    max_dpd_in_window: int | None
    determined_by: str
    """Why the outcome is or is not determined: ``observed``, ``terminated``,
    ``censored``, or ``unobserved``."""

    @property
    def trainable(self) -> bool:
        return self.label in (Label.GOOD, Label.BAD)

    @property
    def target(self) -> int | None:
        if self.label is Label.BAD:
            return 1
        if self.label is Label.GOOD:
            return 0
        return None


def behavioural_rows(
    spell: Spell,
    *,
    extract_end: date,
    horizon_months: int = BEHAVIOURAL_HORIZON_MONTHS,
    min_months_on_book: int = 0,
) -> list[BehaviouralRow]:
    """One row per account-month, labelled over the *following* ``horizon`` months.

    The rules, in the order they are applied:

    1. A default anywhere in ``(t, t+h]`` makes the row BAD. This includes the
       loss dispositions, which is why the event type is consulted and not only
       the DPD column — a loan disposed of at a loss after a servicer stopped
       reporting DPD would otherwise read as GOOD.
    2. A non-loss termination in the window makes the row GOOD and *determined*.
       It left the book; there is no future in which it then defaults. Dropping
       these instead would bias the sample towards borrowers who could not
       refinance — the exact defect ``fanniemae.LoanOutcome`` documents.
    3. Otherwise, if ``t+h`` is past ``extract_end`` the row is undetermined.
    4. Otherwise Appendix A's ``label()`` decides from the window's max DPD.
       The arrears band that makes a row INDETERMINATE is never named here —
       ``label()`` owns it, and this module would be a second copy to keep in
       step (Master §2 rule 6).

    Note what is *not* here: the feature row at ``t`` is passed through
    untouched, and no month after ``t`` contributes to it.
    """
    if horizon_months <= 0:
        raise PanelError("horizon_months must be positive")

    rows: list[BehaviouralRow] = []
    for m in spell.months:
        if m.months_on_book < min_months_on_book:
            continue
        window_end = add_months(m.snapshot, horizon_months)
        forward = spell.window(m.snapshot, window_end)

        observed = [x.dpd for x in forward if x.dpd is not None]
        max_dpd = max(observed) if observed else None

        event_in_window = (
            spell.event is not None
            and spell.event_month is not None
            and m.snapshot < spell.event_month <= window_end
        )

        if event_in_window and spell.event is Event.DEFAULT:
            rows.append(BehaviouralRow(
                m.account_id, m.snapshot, m.months_on_book, dict(m.features),
                Label.BAD, window_end, max_dpd, "observed",
            ))
            continue

        if event_in_window and spell.event in NON_LOSS_EVENTS:
            # Determined by leaving. Appendix A still decides the label from
            # what was seen on the way out: a loan can run 60 DPD and then be
            # paid off by a relative, and that is INDETERMINATE, not GOOD.
            outcome = label(OutcomeObservation(max_dpd=max_dpd or 0, written_off=False))
            rows.append(BehaviouralRow(
                m.account_id, m.snapshot, m.months_on_book, dict(m.features),
                outcome, window_end, max_dpd, "terminated",
            ))
            continue

        if window_end > extract_end:
            rows.append(BehaviouralRow(
                m.account_id, m.snapshot, m.months_on_book, dict(m.features),
                None, window_end, max_dpd, "censored",
            ))
            continue

        if max_dpd is None:
            # The window is inside the extract but carries no observed status at
            # all. max_dpd of 0 here would mean "nothing seen", and label() would
            # read it as GOOD.
            rows.append(BehaviouralRow(
                m.account_id, m.snapshot, m.months_on_book, dict(m.features),
                None, window_end, None, "unobserved",
            ))
            continue

        outcome = label(OutcomeObservation(max_dpd=max_dpd, written_off=False))
        rows.append(BehaviouralRow(
            m.account_id, m.snapshot, m.months_on_book, dict(m.features),
            outcome, window_end, max_dpd, "observed",
        ))
    return rows


# --------------------------------------------------------------------------
# Shape 2 — the discrete-time risk set (WS-3.1 Steps 3 and 4)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class HazardRow:
    """One account-month *at risk*, with the event that occurred in it.

    ``event is None`` means the account survived the month. The final row of a
    censored spell also has ``event is None`` — the difference is that no later
    row exists, which is exactly how censoring enters a discrete-time
    likelihood. There is no "censored" event value, because inventing one
    invites a model to predict it.
    """

    account_id: str
    snapshot: date
    months_on_book: int
    features: dict
    event: Event | None

    @property
    def defaulted(self) -> int:
        return 1 if self.event is Event.DEFAULT else 0

    @property
    def prepaid(self) -> int:
        return 1 if self.event in NON_LOSS_EVENTS else 0

    @property
    def cause(self) -> str:
        """Multinomial target for the competing-risks model (WS-3.1 Step 4)."""
        if self.event is Event.DEFAULT:
            return "default"
        if self.event in NON_LOSS_EVENTS:
            return "prepay"
        return "perform"


def hazard_rows(spell: Spell) -> list[HazardRow]:
    """The risk set: every month the account entered still alive.

    Months strictly after the event are dropped — an account cannot be at risk
    of a first default after its first default. Months *at* the event are kept,
    carrying the event, because that is the month the hazard is estimated for.

    A spell whose event month has no corresponding observation still yields the
    event: servicers stop reporting DPD once a loan is in foreclosure, so
    requiring an observed row for the event month would discard a large share of
    real defaults — on the Fannie 2007 vintage, most of them.
    """
    rows: list[HazardRow] = []
    event_month = spell.event_month

    for m in spell.months:
        if event_month is not None and m.snapshot > event_month:
            continue
        at_event = event_month is not None and m.snapshot == event_month
        rows.append(HazardRow(
            m.account_id, m.snapshot, m.months_on_book, dict(m.features),
            spell.event if at_event else None,
        ))

    if event_month is not None and not any(r.event is not None for r in rows):
        # The event month was never reported. Carry the last observed feature
        # row forward one step rather than dropping the event: last-observation-
        # carried-forward is a stated assumption, and losing the event is not.
        if not spell.months:
            return rows
        last = spell.months[-1]
        rows.append(HazardRow(
            spell.account_id,
            event_month,
            last.months_on_book + max(1, months_between(last.snapshot, event_month)),
            dict(last.features),
            spell.event,
        ))
    return rows


# --------------------------------------------------------------------------
# Shape 3 — consecutive month pairs (WS-3.2 Step 2)
# --------------------------------------------------------------------------


def transition_pairs(spell: Spell) -> Iterator[tuple[AccountMonth, AccountMonth]]:
    """Consecutive observed month pairs, for the DPD transition matrix.

    Only *adjacent* months are yielded. A gap in reporting is not a transition:
    treating a jump from March to July as one month's movement would put the
    whole four-month deterioration into a single cell of the matrix and make
    the roll rate look catastrophic.
    """
    for a, b in zip(spell.months, spell.months[1:]):
        if months_between(a.snapshot, b.snapshot) != 1:
            continue
        yield a, b


# --------------------------------------------------------------------------
# The panel itself
# --------------------------------------------------------------------------


@dataclass
class PanelSummary:
    """What a pass over the panel found. Stamped with its track by the caller."""

    accounts: int = 0
    account_months: int = 0
    events: dict = field(default_factory=dict)
    censored: int = 0
    unobserved_months: int = 0
    first_snapshot: date | None = None
    last_snapshot: date | None = None

    def to_dict(self) -> dict:
        return {
            "accounts": self.accounts,
            "account_months": self.account_months,
            "events": dict(sorted(self.events.items())),
            "censored_spells": self.censored,
            "unobserved_months": self.unobserved_months,
            "first_snapshot": self.first_snapshot.isoformat() if self.first_snapshot else None,
            "last_snapshot": self.last_snapshot.isoformat() if self.last_snapshot else None,
        }


@dataclass
class Panel:
    """A set of spells plus the extract boundary they were observed through.

    ``extract_end`` is not cosmetic. It is the date that separates "did not
    default" from "has not defaulted yet", and every determination in this
    module consults it. A panel that does not know when its data stops cannot
    label anything honestly.
    """

    spells: list[Spell]
    extract_end: date
    dataset: str = ""
    track: str = ""

    def __post_init__(self) -> None:
        ids = [s.account_id for s in self.spells]
        if len(ids) != len(set(ids)):
            raise PanelError(
                "duplicate account ids in the panel — spells must be one per account"
            )

    def summary(self) -> PanelSummary:
        out = PanelSummary()
        out.accounts = len(self.spells)
        for spell in self.spells:
            out.account_months += len(spell.months)
            out.unobserved_months += sum(1 for m in spell.months if not m.observed)
            if spell.event is None:
                out.censored += 1
            else:
                out.events[spell.event.value] = out.events.get(spell.event.value, 0) + 1
            for m in spell.months:
                if out.first_snapshot is None or m.snapshot < out.first_snapshot:
                    out.first_snapshot = m.snapshot
                if out.last_snapshot is None or m.snapshot > out.last_snapshot:
                    out.last_snapshot = m.snapshot
        return out

    def behavioural(
        self,
        *,
        horizon_months: int = BEHAVIOURAL_HORIZON_MONTHS,
        min_months_on_book: int = 0,
    ) -> list[BehaviouralRow]:
        out: list[BehaviouralRow] = []
        for spell in self.spells:
            out.extend(behavioural_rows(
                spell,
                extract_end=self.extract_end,
                horizon_months=horizon_months,
                min_months_on_book=min_months_on_book,
            ))
        return out

    def hazard(self) -> list[HazardRow]:
        out: list[HazardRow] = []
        for spell in self.spells:
            out.extend(hazard_rows(spell))
        return out

    def pairs(self) -> Iterator[tuple[AccountMonth, AccountMonth]]:
        for spell in self.spells:
            yield from transition_pairs(spell)


def split_by_snapshot(
    rows: Sequence,
    *,
    cutoff: date,
) -> tuple[list, list]:
    """Out-of-time split on the snapshot date.

    Phase 3 §7 requires out-of-time validation "by snapshot month", and on a
    panel that is the only split that means anything: a random split puts
    January and February of the *same account* on opposite sides, so the model
    is tested on a row it has effectively already seen. The resulting metric is
    not slightly optimistic, it is measuring the wrong thing.
    """
    before = [r for r in rows if r.snapshot <= cutoff]
    after = [r for r in rows if r.snapshot > cutoff]
    return before, after

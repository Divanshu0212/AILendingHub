"""Fannie Mae performance file as a Phase 3 account-month panel (ADR-0004).

The Phase 0 adapter (:mod:`lending_hub.sources.fanniemae`) folds the monthly
rows into *one outcome per loan*, which is what an application scorecard needs.
Phase 3 needs the opposite: the months themselves, as a panel, because
behavioural PD, survival, competing risks and transition matrices are all
statements about what happens between one month and the next.

This is the same file read a second way, and it reuses that module's empirically
derived column map rather than restating it.

What this data supports, and what it does not
---------------------------------------------
Supports, genuinely: a 15+ year monthly panel with real delinquency
trajectories, real prepayment (the 2020-21 refinance wave is in it), and real
workout cashflows behind :mod:`lending_hub.portfolio.lgd`.

Does not support, and the code says so rather than pretending:

* **Prepayment and maturity are one code.** Fannie's ``01`` is "Prepaid *or*
  Matured", so :class:`~lending_hub.portfolio.panel.Event.MATURED` is never
  emitted. On a 2007 vintage of 30-year loans that is nearly harmless — almost
  nothing has matured — but a prepayment *model* fitted on this cannot separate
  the two behaviours, and the 15-year slice is where it would matter.
* **No revolving product**, so no CCF (see :mod:`lending_hub.portfolio.ead`).
* **US conforming mortgages**, not this bank's book. Nothing computed here is
  Phase 3 gate evidence (ADR-0003, ADR-0004).

Sampling
--------
The 2007Q1 file is 4.3 GB and tens of millions of rows. :func:`load_panel`
samples *whole loans* by a stable hash of the loan id, never rows — sampling
rows would tear holes in the trajectories that every trailing-window feature
and every transition pair depends on, and the damage would look like real
missingness.

Workstream: WS-3.1, WS-3.2 (SRS §7, §9) · ADR-0004
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date
from typing import Iterator

from lending_hub.definitions import DEFAULT_DPD_THRESHOLD_DAYS, month_end
from lending_hub.portfolio.panel import AccountMonth, Event, Panel, Spell
from lending_hub.sources.fanniemae import (
    CREDIT_LOSS_DISPOSITIONS,
    DATASET,
    FIELDS,
    TRACK,
    Disposition,
    dlq_to_dpd_days,
    get,
    parse_mmyyyy,
)

#: Zero-balance code for a loan that left without a credit loss.
PREPAID_OR_MATURED = Disposition.PREPAID_OR_MATURED.value

#: Codes that end the spell but are neither default nor prepayment. A
#: repurchase is Fannie taking the loan back from the pool for a
#: representation-and-warranty breach; the borrower's behaviour is not what
#: ended it, so it is censoring rather than an event.
CENSORING_DISPOSITIONS = frozenset({
    Disposition.REPURCHASED.value,
    Disposition.NOTE_SALE.value,
    Disposition.REPERFORMING_SALE.value,
})

#: Origination attributes carried onto every spell. All fixed before the loan
#: exists, so none can leak (the Phase 0 adapter's ORIGINATION_FEATURES logic).
PANEL_ATTRIBUTES = (
    ("credit_score", "credit_score_b", "int"),
    ("oltv", "oltv", "float"),
    ("dti", "dti", "float"),
    ("orig_rate", "orig_rate", "float"),
    ("orig_upb", "orig_upb", "float"),
    ("orig_term", "orig_term", "int"),
    ("num_borrowers", "num_borrowers", "int"),
    ("first_time_buyer", "first_time_buyer", "flag"),
    ("purpose", "purpose", "str"),
    ("occupancy", "occupancy", "str"),
    ("channel", "channel", "str"),
    ("state", "state", "str"),
)


class PanelLoadError(Exception):
    """The panel cannot be built from this file."""


def sampled(loan_id: str, rate: float) -> bool:
    """Stable whole-loan sample. Same loan, same answer, across runs and files."""
    if rate >= 1.0:
        return True
    if rate <= 0.0:
        return False
    digest = hashlib.blake2b(loan_id.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") / float(1 << 64) < rate


def _cast(value: str, kind: str):
    value = value.strip()
    if not value:
        return None
    try:
        if kind == "int":
            return int(float(value))
        if kind == "float":
            return float(value)
        if kind == "flag":
            return 1 if value == "Y" else 0
    except ValueError:
        return None
    return value


@dataclass
class PanelSummary:
    """What one pass over the file found. Stamped Track P."""

    dataset: str = DATASET
    track: str = TRACK
    vintage: str = ""
    rows_read: int = 0
    loans_sampled: int = 0
    sample_rate: float = 1.0
    account_months: int = 0
    unknown_status_rows: int = 0
    events: dict = field(default_factory=dict)
    censored: int = 0
    first_period: str = ""
    last_period: str = ""
    maturity_indistinguishable: bool = True

    def to_dict(self) -> dict:
        return {
            "dataset": self.dataset,
            "track": self.track,
            "vintage": self.vintage,
            "rows_read": self.rows_read,
            "loans_sampled": self.loans_sampled,
            "sample_rate": self.sample_rate,
            "account_months": self.account_months,
            "unknown_status_rows": self.unknown_status_rows,
            "events": dict(sorted(self.events.items())),
            "censored_spells": self.censored,
            "first_period": self.first_period,
            "last_period": self.last_period,
            "limitations": [
                "Fannie's zero-balance code 01 is 'Prepaid or Matured'; the two "
                "cannot be separated, so Event.MATURED is never emitted.",
                "No revolving product, so no CCF is estimable (LH-303).",
                "US conforming mortgages, not this bank's book — not Phase 3 "
                "gate evidence (ADR-0003, ADR-0004).",
            ],
        }


def load_panel(
    path: str,
    *,
    sample_rate: float = 0.02,
    max_months: int | None = None,
    row_limit: int | None = None,
    vintage: str = "",
) -> tuple[Panel, PanelSummary]:
    """Stream the performance file into a :class:`Panel`.

    One pass, whole-loan sampling, and no attempt to hold the file. Rows arrive
    grouped by loan in these extracts but that is not relied on — spells are
    accumulated in a dict and assembled at the end.
    """
    if not 0.0 < sample_rate <= 1.0:
        raise PanelLoadError(f"sample_rate must be in (0, 1], got {sample_rate}")

    months: dict[str, list[AccountMonth]] = {}
    attributes: dict[str, dict] = {}
    origination: dict[str, date | None] = {}
    disposition: dict[str, tuple[str, date | None]] = {}
    default_at: dict[str, date] = {}

    summary = PanelSummary(vintage=vintage, sample_rate=sample_rate)
    threshold = DEFAULT_DPD_THRESHOLD_DAYS.value
    first_period = last_period = None

    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for index, line in enumerate(handle):
            if row_limit is not None and index >= row_limit:
                break
            row = line.rstrip("\n").split("|")
            if len(row) < FIELDS['zb_upb'] + 1:
                continue
            summary.rows_read += 1

            loan_id = row[FIELDS["loan_id"]].strip()
            if not sampled(loan_id, sample_rate):
                continue

            period = parse_mmyyyy(row[FIELDS["act_period"]])
            if period is None:
                continue
            if first_period is None or period < first_period:
                first_period = period
            if last_period is None or period > last_period:
                last_period = period

            if loan_id not in attributes:
                attributes[loan_id] = {
                    name: _cast(row[FIELDS[column]], kind)
                    for name, column, kind in PANEL_ATTRIBUTES
                }
                origination[loan_id] = parse_mmyyyy(row[FIELDS["orig_date"]])

            dpd = dlq_to_dpd_days(row[FIELDS["dlq_status"]])
            if dpd is None:
                summary.unknown_status_rows += 1

            age = _cast(row[FIELDS["loan_age"]], "int")
            if age is None or age < 0:
                start = origination.get(loan_id)
                age = (
                    (period.year - start.year) * 12 + period.month - start.month
                    if start else 0
                )
            if max_months is not None and age > max_months:
                continue

            balance = _cast(row[FIELDS["current_upb"]], "float") or 0.0
            months.setdefault(loan_id, []).append(AccountMonth(
                account_id=loan_id,
                snapshot=month_end(period),
                months_on_book=age,
                dpd=dpd,
                balance_minor_units=int(round(balance * 100)),
            ))

            if dpd is not None and dpd >= threshold and loan_id not in default_at:
                default_at[loan_id] = month_end(period)

            code = row[FIELDS["zb_code"]].strip()
            if code:
                zb_date = parse_mmyyyy(row[FIELDS["zb_date"]]) or period
                disposition[loan_id] = (code, month_end(zb_date))

    spells: list[Spell] = []
    for loan_id, account_months in months.items():
        event, event_month = _resolve_event(
            loan_id, disposition.get(loan_id), default_at.get(loan_id))
        # A spell cannot carry an event before its first observed month.
        if event_month is not None and account_months:
            earliest = min(m.snapshot for m in account_months)
            if event_month < earliest:
                event, event_month = None, None
        spells.append(Spell(
            account_id=loan_id,
            months=account_months,
            event=event,
            event_month=event_month,
            origination=origination.get(loan_id),
            attributes=attributes.get(loan_id, {}),
        ))
        summary.account_months += len(account_months)
        if event is None:
            summary.censored += 1
        else:
            summary.events[event.value] = summary.events.get(event.value, 0) + 1

    summary.loans_sampled = len(spells)
    summary.first_period = first_period.isoformat() if first_period else ""
    summary.last_period = last_period.isoformat() if last_period else ""

    extract_end = month_end(last_period) if last_period else date.today()
    return Panel(
        spells=spells,
        extract_end=extract_end,
        dataset=DATASET,
        track=TRACK,
    ), summary


def _resolve_event(
    loan_id: str,
    disposition: tuple[str, date | None] | None,
    default_month: date | None,
) -> tuple[Event | None, date | None]:
    """Decide how a spell ended.

    Order matters and is not arbitrary. Appendix A's DPD arm fires the moment
    the account crosses the threshold, which is typically *months* before the
    property is disposed of — so a loan that crossed the Appendix A threshold
    and was later sold at a loss defaults on the crossing date, not the
    disposition date. Taking the later
    date would push every crisis-vintage default a year to the right and make
    the seasoning curve wrong for the whole book.
    """
    code = disposition[0] if disposition else None
    disposed_at = disposition[1] if disposition else None

    if default_month is not None:
        return Event.DEFAULT, default_month

    # Disposition is a str-Enum, so a raw code string compares and hashes
    # equal to its member — verified rather than assumed, because the answer
    # differs between Enum flavours and a silent False here would drop every
    # loss disposition that never reported a delinquency at the threshold.
    if code in CREDIT_LOSS_DISPOSITIONS:
        return Event.DEFAULT, disposed_at

    if code == PREPAID_OR_MATURED:
        # Never Event.MATURED: Fannie's 01 conflates the two and this adapter
        # will not guess which one happened.
        return Event.PREPAID, disposed_at

    if code in CENSORING_DISPOSITIONS:
        return None, None

    return None, None

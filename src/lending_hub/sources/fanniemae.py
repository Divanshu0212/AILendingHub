"""Fannie Mae Single-Family Loan Performance adapter (Track P — ADR-0004).

Maps the Data Dynamics combined acquisition-and-performance extract onto the
platform's own definitions, so Appendix A's label logic runs against real loans
with real month-end delinquency histories.

File shape
----------
Despite the ``.csv`` extension the export is **pipe-delimited with no header
row**, 113 fields, one row per loan per reporting month, with origination
attributes repeated on every row. Both supplied vintages (2007Q1, 2019Q1) share
the layout.

The column map below was **derived empirically** by profiling value
distributions over the supplied files — not transcribed from a remembered file
layout. That is the `[DATA]` discipline Master §2 rule 1 requires: a field index
that is one position out silently reads the wrong column, and every downstream
number would be confidently wrong. :func:`verify_layout` re-checks the mapping
against any file before it is trusted.

Workstream: WS-0.1.1, WS-0.3.4 (Appendix A applied to real data) · ADR-0004
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Iterator

from lending_hub.definitions import (
    OUTCOME_WINDOW_MONTHS,
    Label,
    OutcomeObservation,
    label,
    outcome_window,
)

DATASET = "fannie_mae_sf_loan_performance"
TRACK = "P"
EXPECTED_FIELDS = 113

#: Field name -> zero-based index. Derived by profiling; see :func:`verify_layout`.
FIELDS: dict[str, int] = {
    "pool_id": 0,
    "loan_id": 1,
    "act_period": 2,        # MMYYYY — the monthly reporting period
    "channel": 3,
    "seller": 4,
    "servicer": 5,
    "orig_rate": 7,
    "curr_rate": 8,
    "orig_upb": 9,
    "current_upb": 11,
    "orig_term": 12,
    "orig_date": 13,        # MMYYYY — origination month
    "first_pay": 14,
    "loan_age": 15,
    "maturity_date": 18,
    "oltv": 19,
    "ocltv": 20,
    "num_borrowers": 21,
    "dti": 22,
    "credit_score_b": 23,
    "credit_score_c": 24,
    "first_time_buyer": 25,
    "purpose": 26,
    "property_type": 27,
    "num_units": 28,
    "occupancy": 29,
    "state": 30,
    "msa": 31,
    "zip3": 32,
    "mi_pct": 33,
    "product": 34,
    "dlq_status": 39,       # months delinquent, zero-padded; "XX" = unknown
    "payment_history": 40,
    "mod_flag": 41,
    "zb_code": 43,          # zero balance / disposition code
    "zb_date": 44,
    "zb_upb": 45,
}

#: Columns knowable at origination. An application scorecard may use these and
#: nothing else — every one is fixed before the loan exists, so no as-of filter
#: can make them leak.
ORIGINATION_FEATURES = (
    "credit_score_b",
    "oltv",
    "ocltv",
    "dti",
    "orig_rate",
    "orig_term",
    "num_borrowers",
    "num_units",
    "orig_upb",
    "first_time_buyer",
    "purpose",
    "property_type",
    "occupancy",
    "channel",
    "state",
)

#: Columns a naive pipeline picks up by joining the performance table and taking
#: the most recent row per loan. Every one post-dates the credit decision.
#: ``mod_flag`` is the worst of them: a loan is modified *because* it is in
#: distress, so it is close to a copy of the target wearing a different name.
LATEST_ROW_FEATURES = (
    "mod_flag",
    "loan_age",
    "current_upb",
    "curr_rate",
)

#: Value sets each column must be drawn from, for :func:`verify_layout`.
_LAYOUT_SIGNATURE = {
    "channel": {"R", "C", "B"},
    "occupancy": {"P", "I", "S"},
    "purpose": {"P", "C", "R"},
    "property_type": {"SF", "PU", "CO", "MH", "CP"},
}

#: Fannie's status is *months* delinquent; Appendix A is in *days*. The
#: conversion is 30 days per reported month, matching Fannie's own bucket
#: definition (each status step is one 30-day increment). Status "03" then lands
#: exactly on ``DEFAULT_DPD_THRESHOLD_DAYS``, and statuses "01" and "02" land
#: inside the band between ``INDETERMINATE_DPD_LOWER_DAYS`` and
#: ``INDETERMINATE_DPD_UPPER_DAYS`` — the two definitions align with no tuning,
#: which is why this dataset is worth the disk space. The thresholds are named
#: rather than restated so this comment cannot go stale independently of them.
DAYS_PER_DELINQUENT_MONTH = 30

#: "XX" is *unknown*, not current. Reading it as 0 would silently relabel a
#: servicer reporting gap as a performing month — the single easiest way to
#: understate a default rate on this dataset.
UNKNOWN_DLQ = "XX"


class Disposition(str, Enum):
    """Zero-balance codes observed in the supplied vintages."""

    PREPAID_OR_MATURED = "01"
    THIRD_PARTY_SALE = "02"
    SHORT_SALE_OR_CHARGE_OFF = "03"
    REPURCHASED = "06"
    DEED_IN_LIEU_OR_REO = "09"
    NOTE_SALE = "15"
    REPERFORMING_SALE = "16"


#: Which dispositions are a credit loss, i.e. the Appendix A "write-off" arm.
#: Prepayment is emphatically not one — a loan that paid off early is the best
#: outcome available, and counting "01" as a write-off would invert the label on
#: the large majority of the 2019 vintage.
CREDIT_LOSS_DISPOSITIONS = frozenset(
    {
        Disposition.THIRD_PARTY_SALE,
        Disposition.SHORT_SALE_OR_CHARGE_OFF,
        Disposition.DEED_IN_LIEU_OR_REO,
    }
)


class LayoutError(Exception):
    """The file does not match the derived column map."""


def parse_mmyyyy(value: str) -> date | None:
    """Parse Fannie's MMYYYY month stamp to the first of that month."""
    value = value.strip()
    if len(value) != 6 or not value.isdigit():
        return None
    month, year = int(value[:2]), int(value[2:])
    if not 1 <= month <= 12:
        return None
    return date(year, month, 1)


def dlq_to_dpd_days(status: str) -> int | None:
    """Convert a reported delinquency status to days past due.

    Returns ``None`` for an unknown status, which callers must propagate as
    *not observed* rather than collapsing to zero.
    """
    status = status.strip()
    if not status or status == UNKNOWN_DLQ:
        return None
    if not status.isdigit():
        return None
    return int(status) * DAYS_PER_DELINQUENT_MONTH


def iter_rows(path: str, limit: int | None = None) -> Iterator[list[str]]:
    """Stream raw field lists. Never loads the file — these run to gigabytes."""
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for index, line in enumerate(handle):
            if limit is not None and index >= limit:
                return
            parts = line.rstrip("\n").split("|")
            if len(parts) != EXPECTED_FIELDS:
                raise LayoutError(
                    f"{path}:{index + 1} has {len(parts)} fields, expected "
                    f"{EXPECTED_FIELDS}. This is not the Data Dynamics "
                    "single-family performance layout."
                )
            yield parts


def get(row: list[str], name: str) -> str:
    return row[FIELDS[name]].strip()


def verify_layout(path: str, sample: int = 50_000) -> None:
    """Confirm the column map holds for this file before trusting any number.

    Checks that categorical columns contain only their expected code sets. A
    field index one position out reads a plausible-looking wrong column, and
    every downstream figure would be confidently wrong with nothing to notice.
    """
    seen: dict[str, set[str]] = {name: set() for name in _LAYOUT_SIGNATURE}
    rows = 0

    for row in iter_rows(path, limit=sample):
        rows += 1
        for name in _LAYOUT_SIGNATURE:
            value = get(row, name)
            if value:
                seen[name].add(value)

    if rows == 0:
        raise LayoutError(f"{path} is empty")

    for name, allowed in _LAYOUT_SIGNATURE.items():
        unexpected = seen[name] - allowed
        if unexpected:
            raise LayoutError(
                f"{path}: column {name!r} (index {FIELDS[name]}) contains "
                f"{sorted(unexpected)[:5]}, which is not in the expected code set "
                f"{sorted(allowed)}. The column map does not fit this file."
            )


@dataclass
class LoanOutcome:
    """One loan's Appendix A outcome over its 12-month window."""

    loan_id: str
    origination: date
    window_end: date
    max_dpd: int = 0
    months_observed: int = 0
    months_unknown: int = 0
    months_known: int = 0
    written_off: bool | None = None
    disposition: str | None = None
    terminated_at: date | None = None
    orig_upb_minor_units: int = 0
    credit_score: int | None = None
    state: str = ""

    #: Attributes known at origination — the only ones an application scorecard
    #: may use. Captured from the loan's first in-window row.
    origination_features: dict = field(default_factory=dict)

    #: Attributes read from the loan's *latest* row. These post-date the
    #: decision and exist here solely so the leakage experiment can demonstrate
    #: what a naive "join the table, take the latest row" pipeline picks up.
    #: They must never reach a production feature set.
    latest_row_features: dict = field(default_factory=dict)

    #: Months the window should contain — imported, never retyped (Master §2
    #: rule 6). Overridden per run when analysing a longer horizon.
    expected_months: int = OUTCOME_WINDOW_MONTHS.value

    def outcome_determined(self, extract_end: date | None) -> bool:
        """Whether this loan's 12-month outcome is actually known.

        Two ways a window can be short, and they are **not** interchangeable:

        1. **The loan terminated inside the window** — prepaid, matured, or was
           disposed of after a credit loss. The outcome is determined: it left
           the book, and there is no future in which it then defaults. Excluding
           these would be a serious error on this dataset, because the 2019
           vintage prepaid en masse in the 2020-21 refinance wave; the survivors
           are systematically worse credits, so the sample would quietly become
           a sample of borrowers who *could not* refinance.
        2. **The extract ends before the window does** — genuinely censored, and
           excluded. This hits the newest cohorts hardest, which are exactly the
           ones a fresh model is fitted to.

        A third case looks like censoring and is not. A quarterly acquisition
        file's reporting periods begin at the *acquisition quarter*, so a loan
        originated a month or two earlier has no rows for those first months.
        That gap cannot hide a 90-DPD event: the first payment is not yet due
        (Fannie's own FIRST_PAY runs about two months after origination), so a
        loan physically cannot be three payments down. Counting rows and
        requiring twelve would discard most of the vintage for no reason.
        """
        if self.months_known == 0:
            # Every month in the window carried an unknown status. There is no
            # observed performance at all, so the loan is not GOOD — it is
            # unobserved, and `max_dpd == 0` here means "nothing seen", not
            # "nothing happened". This is the same distinction the platform draws
            # everywhere else between None and False.
            return False
        if self.terminated_at is not None and self.terminated_at < self.window_end:
            return True
        if extract_end is not None and self.window_end <= extract_end:
            return True
        return False

    def observation(self) -> OutcomeObservation:
        return OutcomeObservation(
            max_dpd=self.max_dpd,
            written_off=self.written_off,
        )

    def label(self, extract_end: date | None = None) -> Label | None:
        """Appendix A label, or None when the outcome is not determined."""
        if not self.outcome_determined(extract_end):
            return None
        return label(self.observation())


@dataclass
class ExtractSummary:
    """What a pass over one vintage found. Stamped Track P (ADR-0004)."""

    dataset: str = DATASET
    track: str = TRACK
    vintage: str = ""
    rows_read: int = 0
    loans: int = 0
    fully_observed: int = 0
    terminated_in_window: int = 0
    censored: int = 0
    labels: dict[str, int] = field(default_factory=dict)
    dispositions: dict[str, int] = field(default_factory=dict)
    unknown_dlq_rows: int = 0
    extract_end: str = ""

    @property
    def bad_rate(self) -> float | None:
        """Bad rate over *trainable* loans. None when nothing was observed."""
        good = self.labels.get(Label.GOOD.value, 0)
        bad = self.labels.get(Label.BAD.value, 0)
        if good + bad == 0:
            return None
        return bad / (good + bad)

    @property
    def indeterminate_rate(self) -> float | None:
        total = sum(self.labels.values())
        if total == 0:
            return None
        return self.labels.get(Label.INDETERMINATE.value, 0) / total

    def to_dict(self) -> dict:
        return {
            "dataset": self.dataset,
            "track": self.track,
            "vintage": self.vintage,
            "rows_read": self.rows_read,
            "loans": self.loans,
            "outcome_determined": self.fully_observed,
            "terminated_in_window": self.terminated_in_window,
            "censored_excluded": self.censored,
            "extract_end": self.extract_end,
            "labels": dict(sorted(self.labels.items())),
            "bad_rate": self.bad_rate,
            "indeterminate_rate": self.indeterminate_rate,
            "dispositions": dict(sorted(self.dispositions.items())),
            "unknown_dlq_rows": self.unknown_dlq_rows,
            "definition": "lending_hub.definitions (Master Appendix A v1.1)",
            "track_note": (
                "Track P: real data, but not this bank's portfolio. These figures "
                "describe US conforming mortgages of this vintage and are not "
                "Phase 0 gate evidence (ADR-0004)."
            ),
        }


def build_outcomes(
    path: str,
    *,
    limit: int | None = None,
    outcome_months: int | None = None,
) -> tuple[dict[str, LoanOutcome], ExtractSummary]:
    """Fold the monthly performance rows into one Appendix A outcome per loan.

    Streams in a single pass. Only months inside each loan's own outcome window
    contribute — a delinquency long after the window says nothing about the
    outcome, and including it would silently redefine the target. The window
    length comes from ``lending_hub.definitions.outcome_window``.
    """
    if outcome_months is None:
        outcome_months = OUTCOME_WINDOW_MONTHS.value

    outcomes: dict[str, LoanOutcome] = {}
    summary = ExtractSummary()
    extract_end: date | None = None

    for row in iter_rows(path, limit=limit):
        summary.rows_read += 1

        loan_id = get(row, "loan_id")
        origination = parse_mmyyyy(get(row, "orig_date"))
        period = parse_mmyyyy(get(row, "act_period"))
        if not loan_id or origination is None or period is None:
            continue

        if extract_end is None or period > extract_end:
            extract_end = period

        outcome = outcomes.get(loan_id)
        if outcome is None:
            _, window_end = outcome_window(origination, months=outcome_months)
            outcome = LoanOutcome(
                loan_id=loan_id,
                origination=origination,
                window_end=window_end,
                expected_months=outcome_months,
                orig_upb_minor_units=_to_minor_units(get(row, "orig_upb")),
                credit_score=_to_int(get(row, "credit_score_b")),
                state=get(row, "state"),
            )
            outcomes[loan_id] = outcome

        if period >= outcome.window_end:
            continue

        if not outcome.origination_features:
            outcome.origination_features = {
                name: get(row, name) for name in ORIGINATION_FEATURES
            }

        # Overwritten every row, so it ends up holding the latest in-window row.
        outcome.latest_row_features = {
            name: get(row, name) for name in LATEST_ROW_FEATURES
        }

        outcome.months_observed += 1

        status = get(row, "dlq_status")
        dpd = dlq_to_dpd_days(status)
        if dpd is None:
            outcome.months_unknown += 1
            summary.unknown_dlq_rows += 1
        else:
            outcome.months_known += 1
            outcome.max_dpd = max(outcome.max_dpd, dpd)

        zb_code = get(row, "zb_code")
        if zb_code:
            outcome.disposition = zb_code
            outcome.terminated_at = parse_mmyyyy(get(row, "zb_date")) or period
            summary.dispositions[zb_code] = summary.dispositions.get(zb_code, 0) + 1
            try:
                outcome.written_off = Disposition(zb_code) in CREDIT_LOSS_DISPOSITIONS
            except ValueError:
                # An unmapped disposition is left as not-observed rather than
                # guessed either way; it will surface in the summary counts.
                outcome.written_off = None

    summary.loans = len(outcomes)
    summary.extract_end = extract_end.isoformat() if extract_end else ""
    for outcome in outcomes.values():
        outcome_label = outcome.label(extract_end)
        if outcome_label is None:
            summary.censored += 1
            continue
        summary.fully_observed += 1
        if outcome.terminated_at is not None and outcome.terminated_at < outcome.window_end:
            summary.terminated_in_window += 1
        summary.labels[outcome_label.value] = summary.labels.get(outcome_label.value, 0) + 1

    return outcomes, summary


def _to_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_minor_units(value: str) -> int:
    """Currency as integer minor units — never float (WS-0.1.5)."""
    value = value.strip()
    if not value:
        return 0
    if "." in value:
        whole, _, frac = value.partition(".")
        return int(whole or 0) * 100 + int((frac + "00")[:2])
    return int(value) * 100

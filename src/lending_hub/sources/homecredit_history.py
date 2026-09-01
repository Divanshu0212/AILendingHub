"""Home Credit history tables — bureau records and prior repayment behaviour.

The application table is what an applicant *says*. These two tables are what the
credit system already *knows*, and in retail credit that is where most of the
signal is. The Phase 1 feature catalogue (WS-1.1 Step 2) leads with the bureau
group for exactly this reason — enquiries, utilisation, DPD history, file age —
and until these tables are read, that group is declared and empty.

Two sources, two very different shapes
--------------------------------------
``bureau.csv`` — 1.72M rows, one per credit record held at another lender.
Aggregated per applicant into the four SRS §4.3.1 bureau concepts.

``POS_CASH_balance.csv`` — 10.0M rows, one per prior Home Credit loan per month,
carrying ``SK_DPD``: **observed days past due**. This is repayment behaviour
rather than a proxy for it, and it is the strongest single class of predictor in
retail credit.

Point-in-time, within the limits of the source
----------------------------------------------
``MONTHS_BALANCE`` is months relative to the application, negative meaning before
it. Only strictly-negative months are aggregated. Month ``0`` is documented by the
publisher as "the information at application", which is *probably* knowable at
decision time and not certainly so — and the cost of excluding it is one month of
history, while the cost of including it wrongly is a leak in the strongest feature
in the set. When the two costs are that asymmetric the conservative reading is not
a judgement call.

That is as far as it goes. The source is declared ``point_in_time_unsafe`` in the
registry: there is no absolute timeline and no ingestion timestamp, so these
aggregates inherit the limitation and no model built on them may claim
point-in-time correctness (Track P finding F6).

Both readers stream. ``POS_CASH_balance.csv`` is 392 MB and holds ten million
rows; loading it would be the only part of this pipeline that needed a large
machine, and the aggregation does not require one.

Workstream: WS-1.1 Step 2 (bureau + behavioural feature groups) · ADR-0004, ADR-0010
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field

#: Days that count as "recent" for an enquiry-burst counter. One year, matching
#: the SRS §4.3.1 bureau group's "enquiries" concept, which is conventionally
#: measured over a rolling year. Stated as a constant so a different window is a
#: visible change rather than an edit inside a loop.
RECENT_WINDOW_DAYS = 365

#: Publisher-documented meaning of ``MONTHS_BALANCE`` 0 is "at application", which
#: is not certainly pre-decision. Only strictly earlier months are aggregated.
LATEST_SAFE_MONTHS_BALANCE = -1


class HistoryError(Exception):
    """A history table does not have the expected layout."""


#: Bureau aggregates, each with the credit rationale WS-1.1 Step 2 requires.
#: A feature nobody can justify is a feature nobody can defend to a regulator,
#: whatever its information value.
BUREAU_FEATURES: dict[str, str] = {
    "bureau_record_count":
        "File thickness. A thin bureau file is a real segment, not a data defect",
    "bureau_active_count":
        "Live obligations elsewhere — the denominator of affordability the bank cannot see",
    "bureau_closed_count":
        "Successfully retired credit. Distinguishes thin-file-new from thin-file-recovered",
    "bureau_file_age_days":
        "Days since the oldest bureau record. SRS §4.3.1 'file age'",
    "bureau_days_since_last":
        "Recency of the most recent bureau record",
    "bureau_recent_count":
        "Records opened in the last year. An enquiry burst is the classic "
        "synthetic-identity signature when paired with a new file",
    "bureau_max_days_overdue":
        "Worst observed days overdue anywhere on file. Past repayment behaviour is "
        "the most-replicated predictor of future default",
    "bureau_max_amount_overdue":
        "Worst overdue amount — severity where days give frequency",
    "bureau_sum_debt":
        "Total outstanding debt across lenders",
    "bureau_sum_credit":
        "Total sanctioned credit across lenders",
    "bureau_debt_ratio":
        "Debt over sanctioned limit. SRS §4.3.1 'utilisation'; sustained high "
        "utilisation is the strongest retail risk signal after delinquency",
    "bureau_prolong_count":
        "Times a bureau credit was prolonged — the nearest available proxy for a "
        "restructure, and a distress signal rather than a neutral one",
    "bureau_active_overdue_count":
        "Live credits currently in arrears. Present-tense distress, not history",
}

#: Prior-repayment aggregates from POS_CASH_balance.
POS_FEATURES: dict[str, str] = {
    "pos_months_observed":
        "Months of prior repayment history. Zero means no prior relationship, "
        "which is a segment and not a missing value",
    "pos_max_dpd":
        "Worst observed days past due on a prior loan with this lender. Observed "
        "behaviour, not a proxy for it",
    "pos_mean_dpd":
        "Average days past due across observed months — persistence where the max "
        "gives severity",
    "pos_months_in_arrears":
        "Count of months with any days past due. Distinguishes one bad month from "
        "a pattern",
    "pos_max_dpd_tolerated":
        "Worst DPD net of the publisher's grace tolerance, so a payment that was "
        "late by the calendar but not by the contract is not counted as arrears",
    "pos_completed_count":
        "Prior loans carried to completion. The positive half of the history",
}


@dataclass
class HistorySummary:
    """What one pass over a history table found."""

    table: str
    rows_read: int = 0
    applicants: int = 0
    rows_skipped_future: int = 0
    """POS rows at or after the application month, excluded on the conservative
    reading of ``MONTHS_BALANCE``."""

    def to_dict(self) -> dict:
        return {
            "table": self.table,
            "rows_read": self.rows_read,
            "applicants_covered": self.applicants,
            "rows_excluded_not_strictly_before_application": self.rows_skipped_future,
            "point_in_time_unsafe": True,
            "note": (
                "Aggregated from a source declared point_in_time_unsafe: no absolute "
                "timeline, no ingestion timestamp. Structure is exercisable; "
                "point-in-time correctness is not (Track P finding F6)."
            ),
        }


def _f(raw: str) -> float | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def load_bureau(path: str, *, keys: set[str] | None = None) -> tuple[dict[str, dict], HistorySummary]:
    """Aggregate ``bureau.csv`` to one row per applicant.

    ``keys`` restricts the aggregation to applicants actually in the training
    extract. Without it a 60,000-row experiment still carries aggregates for all
    305,811 applicants in the bureau file, which is memory spent on rows nothing
    will ever join to.
    """
    summary = HistorySummary(table="bureau")
    acc: dict[str, dict] = {}

    with open(path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"SK_ID_CURR", "CREDIT_ACTIVE", "DAYS_CREDIT", "CREDIT_DAY_OVERDUE"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise HistoryError(f"{path} is missing {sorted(missing)}; not a bureau extract")

        for raw in reader:
            summary.rows_read += 1
            key = (raw.get("SK_ID_CURR") or "").strip()
            if not key or (keys is not None and key not in keys):
                continue

            bucket = acc.setdefault(key, {
                "n": 0, "active": 0, "closed": 0, "recent": 0, "prolong": 0.0,
                "active_overdue": 0, "oldest": None, "newest": None,
                "max_day_overdue": None, "max_amt_overdue": None,
                "sum_debt": 0.0, "sum_credit": 0.0,
            })
            bucket["n"] += 1

            status = (raw.get("CREDIT_ACTIVE") or "").strip()
            if status == "Active":
                bucket["active"] += 1
            elif status == "Closed":
                bucket["closed"] += 1

            days = _f(raw.get("DAYS_CREDIT", ""))
            if days is not None:
                bucket["oldest"] = days if bucket["oldest"] is None else min(bucket["oldest"], days)
                bucket["newest"] = days if bucket["newest"] is None else max(bucket["newest"], days)
                if days > -RECENT_WINDOW_DAYS:
                    bucket["recent"] += 1

            for column, field_name in (
                ("CREDIT_DAY_OVERDUE", "max_day_overdue"),
                ("AMT_CREDIT_MAX_OVERDUE", "max_amt_overdue"),
            ):
                value = _f(raw.get(column, ""))
                if value is not None:
                    current = bucket[field_name]
                    bucket[field_name] = value if current is None else max(current, value)

            for column, field_name in (
                ("AMT_CREDIT_SUM_DEBT", "sum_debt"),
                ("AMT_CREDIT_SUM", "sum_credit"),
                ("CNT_CREDIT_PROLONG", "prolong"),
            ):
                value = _f(raw.get(column, ""))
                if value is not None:
                    bucket[field_name] += value

            overdue = _f(raw.get("AMT_CREDIT_SUM_OVERDUE", ""))
            if status == "Active" and overdue is not None and overdue > 0:
                bucket["active_overdue"] += 1

    out: dict[str, dict] = {}
    for key, b in acc.items():
        credit = b["sum_credit"]
        out[key] = {
            "bureau_record_count": float(b["n"]),
            "bureau_active_count": float(b["active"]),
            "bureau_closed_count": float(b["closed"]),
            "bureau_file_age_days": None if b["oldest"] is None else -b["oldest"],
            "bureau_days_since_last": None if b["newest"] is None else -b["newest"],
            "bureau_recent_count": float(b["recent"]),
            "bureau_max_days_overdue": b["max_day_overdue"],
            "bureau_max_amount_overdue": b["max_amt_overdue"],
            "bureau_sum_debt": b["sum_debt"],
            "bureau_sum_credit": credit,
            # None rather than 0.0 when there is no sanctioned credit to divide by:
            # an undefined utilisation is not a utilisation of zero, and the
            # separate-bin null policy is there to hold exactly this case.
            "bureau_debt_ratio": (b["sum_debt"] / credit) if credit else None,
            "bureau_prolong_count": b["prolong"],
            "bureau_active_overdue_count": float(b["active_overdue"]),
        }
    summary.applicants = len(out)
    return out, summary


def load_pos_cash(path: str, *, keys: set[str] | None = None) -> tuple[dict[str, dict], HistorySummary]:
    """Aggregate ``POS_CASH_balance.csv`` to one row per applicant.

    Streams by column index rather than :class:`csv.DictReader`: ten million rows
    through a dict-per-row constructor is roughly three times the work, and this is
    the one table in the set where that is the difference between a minute and
    several.
    """
    summary = HistorySummary(table="pos_cash_balance")
    acc: dict[str, dict] = {}

    with open(path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise HistoryError(f"{path} is empty") from exc

        try:
            i_key = header.index("SK_ID_CURR")
            i_month = header.index("MONTHS_BALANCE")
            i_dpd = header.index("SK_DPD")
            i_dpd_def = header.index("SK_DPD_DEF")
            i_status = header.index("NAME_CONTRACT_STATUS")
        except ValueError as exc:
            raise HistoryError(f"{path} is not a POS_CASH_balance extract: {exc}") from exc

        for row in reader:
            summary.rows_read += 1
            if len(row) <= i_status:
                continue
            key = row[i_key].strip()
            if not key or (keys is not None and key not in keys):
                continue

            month = _f(row[i_month])
            if month is None or month > LATEST_SAFE_MONTHS_BALANCE:
                summary.rows_skipped_future += 1
                continue

            bucket = acc.setdefault(key, {
                "months": 0, "dpd_sum": 0.0, "dpd_max": 0.0,
                "arrears_months": 0, "dpd_def_max": 0.0, "completed": 0,
            })
            bucket["months"] += 1

            dpd = _f(row[i_dpd])
            if dpd is not None:
                bucket["dpd_sum"] += dpd
                bucket["dpd_max"] = max(bucket["dpd_max"], dpd)
                if dpd > 0:
                    bucket["arrears_months"] += 1

            dpd_def = _f(row[i_dpd_def])
            if dpd_def is not None:
                bucket["dpd_def_max"] = max(bucket["dpd_def_max"], dpd_def)

            if row[i_status].strip() == "Completed":
                bucket["completed"] += 1

    out: dict[str, dict] = {}
    for key, b in acc.items():
        months = b["months"]
        out[key] = {
            "pos_months_observed": float(months),
            "pos_max_dpd": b["dpd_max"],
            "pos_mean_dpd": (b["dpd_sum"] / months) if months else None,
            "pos_months_in_arrears": float(b["arrears_months"]),
            "pos_max_dpd_tolerated": b["dpd_def_max"],
            "pos_completed_count": float(b["completed"]),
        }
    summary.applicants = len(out)
    return out, summary

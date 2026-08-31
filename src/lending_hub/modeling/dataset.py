"""Training-set construction from a Track P extract.

Turns loan outcomes into an encoded design matrix. Two feature sets are built
from the same pass so the leakage experiment compares like with like:

``pit``
    Origination attributes only — everything is fixed before the loan exists, so
    no as-of filter can make it leak. This is what an application scorecard may
    legitimately use.

``naive``
    The same, plus whatever a pipeline picks up by joining the performance table
    and taking the most recent row per loan. Every added column post-dates the
    credit decision.

Nothing here decides which set is *correct* — that is Appendix A and WS-0.2.1.
This module only makes the difference measurable.

Workstream: WS-0.2.1 · ADR-0004
"""

from __future__ import annotations

import csv
import math
import pathlib
from dataclasses import dataclass, field

from lending_hub.definitions import Label
from lending_hub.sources.fanniemae import build_outcomes

#: Numeric features and the plausible range each is clipped to. Clipping is not
#: cleaning: Fannie encodes some missings as extreme sentinels, and an
#: unclipped 9999 DTI would dominate a standardised model.
NUMERIC_RANGES: dict[str, tuple[float, float]] = {
    "credit_score_b": (300.0, 850.0),
    "oltv": (1.0, 200.0),
    "ocltv": (1.0, 250.0),
    "dti": (1.0, 65.0),
    "orig_rate": (0.5, 20.0),
    "orig_term": (60.0, 480.0),
    "num_borrowers": (1.0, 10.0),
    "num_units": (1.0, 4.0),
    "orig_upb": (10_000.0, 3_000_000.0),
}

CATEGORICAL_FEATURES = (
    "first_time_buyer",
    "purpose",
    "property_type",
    "occupancy",
    "channel",
)

NAIVE_NUMERIC_RANGES: dict[str, tuple[float, float]] = {
    "loan_age": (0.0, 480.0),
    "curr_rate": (0.5, 20.0),
}

NAIVE_CATEGORICAL_FEATURES = ("mod_flag",)


@dataclass
class Design:
    """An encoded design matrix with its column names."""

    columns: list[str] = field(default_factory=list)
    rows: list[list[float]] = field(default_factory=list)
    labels: list[int] = field(default_factory=list)
    keys: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.rows)

    @property
    def positives(self) -> int:
        return sum(self.labels)

    @property
    def base_rate(self) -> float | None:
        if not self.labels:
            return None
        return self.positives / len(self.labels)


def _num(value: str, bounds: tuple[float, float]) -> tuple[float, float]:
    """Return ``(value, missing_flag)``.

    A missing numeric becomes the midpoint plus an explicit missing indicator,
    rather than a silent zero. Zero is a real credit score in no dataset, and
    imputing it teaches the model that missingness means "worst possible".
    """
    low, high = bounds
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return (low + high) / 2, 1.0
    if math.isnan(parsed):
        return (low + high) / 2, 1.0
    return min(max(parsed, low), high), 0.0


def build_design(
    path: str,
    *,
    outcome_months: int,
    leaky: bool = False,
    limit: int | None = None,
) -> Design:
    """Build a design matrix from one extract.

    Indeterminates are dropped — Appendix A excludes them from training targets
    and keeps them in scoring and reporting, and this function builds training
    targets. Censored loans are dropped too: an undetermined outcome is not a
    zero.
    """
    outcomes, summary = build_outcomes(path, limit=limit, outcome_months=outcome_months)
    extract_end = None
    if summary.extract_end:
        from datetime import date

        year, month, day = (int(p) for p in summary.extract_end.split("-"))
        extract_end = date(year, month, day)

    numeric = dict(NUMERIC_RANGES)
    categorical = list(CATEGORICAL_FEATURES)
    if leaky:
        numeric.update(NAIVE_NUMERIC_RANGES)
        categorical += list(NAIVE_CATEGORICAL_FEATURES)

    levels = _collect_levels(outcomes, categorical, leaky)

    design = Design()
    design.columns = (
        [name for name in numeric]
        + [f"{name}_missing" for name in numeric]
        + [f"{name}={level}" for name in categorical for level in levels[name]]
    )

    for loan_id, outcome in outcomes.items():
        outcome_label = outcome.label(extract_end)
        if outcome_label is None or outcome_label is Label.INDETERMINATE:
            continue

        source = dict(outcome.origination_features)
        if leaky:
            source.update(outcome.latest_row_features)

        values: list[float] = []
        missing: list[float] = []
        for name, bounds in numeric.items():
            value, flag = _num(source.get(name, ""), bounds)
            values.append(value)
            missing.append(flag)

        encoded: list[float] = []
        for name in categorical:
            observed = source.get(name, "")
            encoded += [1.0 if observed == level else 0.0 for level in levels[name]]

        design.rows.append(values + missing + encoded)
        design.labels.append(1 if outcome_label is Label.BAD else 0)
        design.keys.append(loan_id)

    return design


def _collect_levels(outcomes, categorical, leaky) -> dict[str, list[str]]:
    """Fixed level sets, so train and test encode to identical columns.

    A level seen only in the test extract would otherwise shift every column
    after it — the encoding equivalent of an off-by-one, and just as silent.
    """
    seen: dict[str, set[str]] = {name: set() for name in categorical}
    for outcome in outcomes.values():
        source = dict(outcome.origination_features)
        if leaky:
            source.update(outcome.latest_row_features)
        for name in categorical:
            value = source.get(name, "")
            if value:
                seen[name].add(value)
    return {name: sorted(values) for name, values in seen.items()}


def align(design: Design, columns: list[str]) -> Design:
    """Re-index a design onto another's columns, filling absent ones with zero."""
    index = {name: i for i, name in enumerate(design.columns)}
    out = Design(columns=list(columns), labels=list(design.labels), keys=list(design.keys))
    for row in design.rows:
        out.rows.append([row[index[name]] if name in index else 0.0 for name in columns])
    return out


def write_csv(design: Design, path: str | pathlib.Path) -> None:
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["loan_id", "label", *design.columns])
        for key, y, row in zip(design.keys, design.labels, design.rows):
            writer.writerow([key, y, *row])

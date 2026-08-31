"""Home Credit Default Risk adapter (Track P — ADR-0004, ADR-0010).

ADR-0010 selects this source for the Phase 1 application scorecard: it is the
only Track P dataset with the right *product shape* — unsecured consumer cash and
revolving loans, one row per application, 307,511 applications — and the only one
carrying the protected attributes fairness testing needs.

Three things this adapter must not let anyone forget
-----------------------------------------------------
**The label is not Appendix A.** ``TARGET`` is Home Credit's own definition of
payment difficulty, with its own window and its own thresholds, published without
the DPD history that would let Appendix A be applied instead. So every target
table built here is stamped :data:`LabelProvenance.VENDOR` with the definition
written out, and ``appendix_a_aligned`` comes back False. A model fitted on it is
not predicting what a bank model would predict, however similar the AUC looks.

**There is no clock.** Every time column is a relative day offset from an
unstated per-application reference date, so no vintage exists and no out-of-time
split can be constructed. The source registry declares this
(``point_in_time_unsafe: true``), and that declaration is what gates
:func:`lending_hub.scoring.splits.holdout_without_time_axis`.

**Protected attributes are separated at the door.** ``CODE_GENDER``, the age band
derived from ``DAYS_BIRTH`` and the region columns are read into a
:class:`~lending_hub.scoring.features.ProtectedAttributeAccess`, never into the
feature dict. :func:`load` returns them as a separate value, so a caller that
wants to use gender as a feature has to write code that visibly does that.

Feature selection here is deliberately narrow: bureau-ish, application and
affordability columns whose meaning is documented in the dataset's own column
description. The 100-odd building-fabric columns (``APARTMENTS_AVG`` and family)
are excluded — not because they lack signal, but because "average number of
elevators in the applicant's building" is not a credit rationale anyone will
defend to a regulator, and WS-1.1 Step 2 requires one per feature.

Workstream: WS-1.1 Steps 1-2 · ADR-0004, ADR-0010
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date
from typing import Iterator

DATASET = "home_credit_default_risk"
SOURCE_ID = "home_credit_default_risk"
TRACK = "P"

#: The vendor's own label definition, recorded on every target table built here.
TARGET_DEFINITION = (
    "Home Credit TARGET: 1 = client with payment difficulties, defined by the "
    "publisher as a late payment beyond their stated tolerance on at least one of "
    "the first instalments. It is NOT Master Appendix A default: the window, the "
    "threshold and the non-DPD arms are all the vendor's, and the DPD history "
    "needed to apply Appendix A instead is not published with this file."
)

#: Numeric columns kept as features, with the plausible range each is clipped to.
#: Clipping is not cleaning: Home Credit encodes some missings as sentinels —
#: DAYS_EMPLOYED carries 365243 for pensioners, which is exactly 1000 years and
#: would dominate any scaled model — and an unclipped sentinel is a feature about
#: employment status wearing a tenure column's name.
NUMERIC_FEATURES: dict[str, tuple[float, float]] = {
    "AMT_INCOME_TOTAL": (10_000.0, 5_000_000.0),
    "AMT_CREDIT": (10_000.0, 5_000_000.0),
    "AMT_ANNUITY": (1_000.0, 300_000.0),
    "AMT_GOODS_PRICE": (10_000.0, 5_000_000.0),
    "EXT_SOURCE_1": (0.0, 1.0),
    "EXT_SOURCE_2": (0.0, 1.0),
    "EXT_SOURCE_3": (0.0, 1.0),
    "DAYS_EMPLOYED": (-20_000.0, 0.0),
    "DAYS_ID_PUBLISH": (-8_000.0, 0.0),
    "DAYS_REGISTRATION": (-25_000.0, 0.0),
    "CNT_FAM_MEMBERS": (1.0, 12.0),
    "DEF_30_CNT_SOCIAL_CIRCLE": (0.0, 20.0),
    "AMT_REQ_CREDIT_BUREAU_QRT": (0.0, 20.0),
    "AMT_REQ_CREDIT_BUREAU_YEAR": (0.0, 30.0),
}

#: Derived affordability ratios. Built here rather than left to the model because
#: a ratio is the thing a credit officer actually reasons about, and a tree can
#: only approximate it by splitting twice.
DERIVED_FEATURES = ("credit_to_income", "annuity_to_income", "credit_to_goods")

#: Categorical columns kept, one-hot encoded on load.
CATEGORICAL_FEATURES = (
    "NAME_CONTRACT_TYPE",
    "NAME_INCOME_TYPE",
    "NAME_EDUCATION_TYPE",
    "NAME_FAMILY_STATUS",
    "FLAG_OWN_CAR",
    "FLAG_OWN_REALTY",
)

#: Never features. Read into ProtectedAttributeAccess and nothing else.
PROTECTED_COLUMNS = ("CODE_GENDER", "DAYS_BIRTH", "REGION_RATING_CLIENT")

#: DAYS_EMPLOYED sentinel for "not employed" (pensioners and the unemployed).
DAYS_EMPLOYED_SENTINEL = 365243

#: Home Credit publishes gender as M / F / XNA. XNA is not a third gender, it is
#: an absent value, and treating it as a group would produce a fairness finding
#: about a population that does not exist.
UNKNOWN_GENDER = "XNA"


class HomeCreditError(Exception):
    """The extract does not match the expected layout."""


def age_band(days_birth: float | None) -> str | None:
    """Ten-year age band from the negative day offset Home Credit publishes.

    Bands rather than the raw age: fairness testing compares *groups*, and a
    per-year comparison on 307k applications produces 60 groups of which most are
    too small to say anything about.
    """
    if days_birth is None:
        return None
    years = int(-days_birth / 365.25)
    if years < 18 or years > 100:
        return None
    lower = (years // 10) * 10
    return f"{lower}-{lower + 9}"


@dataclass
class LoadSummary:
    """What one pass over the extract found."""

    dataset: str = DATASET
    track: str = TRACK
    rows_read: int = 0
    kept: int = 0
    skipped_no_label: int = 0
    positives: int = 0
    unknown_gender: int = 0
    feature_names: list[str] = field(default_factory=list)

    @property
    def base_rate(self) -> float | None:
        return self.positives / self.kept if self.kept else None

    def to_dict(self) -> dict:
        return {
            "dataset": self.dataset,
            "track": self.track,
            "source_id": SOURCE_ID,
            "rows_read": self.rows_read,
            "kept": self.kept,
            "skipped_no_label": self.skipped_no_label,
            "positives": self.positives,
            "base_rate": self.base_rate,
            "unknown_gender": self.unknown_gender,
            "n_features": len(self.feature_names),
            "label_definition": TARGET_DEFINITION,
            "appendix_a_aligned": False,
            "point_in_time_unsafe": True,
            "track_note": (
                "Track P: real applications, but not this bank's portfolio and not "
                "an Appendix A label. Not gate evidence (ADR-0004)."
            ),
        }


def _number(raw: str, bounds: tuple[float, float] | None = None) -> float | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    if bounds is None:
        return value
    low, high = bounds
    return min(max(value, low), high)


def _levels(path: str, limit: int | None) -> dict[str, list[str]]:
    """Fixed categorical level sets, collected in a first pass.

    Collected up front so the encoding is identical for every row and every
    later split. A level first seen halfway through shifts every column after
    it — the encoding equivalent of an off-by-one, and just as silent.
    """
    seen: dict[str, set[str]] = {name: set() for name in CATEGORICAL_FEATURES}
    with open(path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader):
            if limit is not None and index >= limit:
                break
            for name in CATEGORICAL_FEATURES:
                value = (row.get(name) or "").strip()
                if value:
                    seen[name].add(value)
    return {name: sorted(values) for name, values in seen.items()}


def iter_rows(path: str, limit: int | None = None) -> Iterator[dict]:
    with open(path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if "TARGET" not in (reader.fieldnames or []):
            raise HomeCreditError(
                f"{path} has no TARGET column: this is application_test.csv or a "
                "different file. The unlabelled split cannot build a target table."
            )
        for index, row in enumerate(reader):
            if limit is not None and index >= limit:
                return
            yield row


def load(path: str, *, limit: int | None = None) -> tuple[list[dict], list[int], dict, LoadSummary]:
    """Read the extract into rows, labels, protected attributes and a summary.

    Returns four values, and the third is the point: protected attributes come
    back *separately*, so using gender as a feature requires code that visibly
    merges two dictionaries rather than code that forgets to exclude a column.
    """
    levels = _levels(path, limit)
    feature_names: list[str] = (
        list(NUMERIC_FEATURES)
        + [f"{name}_missing" for name in NUMERIC_FEATURES]
        + list(DERIVED_FEATURES)
        + [f"{name}={level}" for name in CATEGORICAL_FEATURES for level in levels[name]]
    )

    rows: list[dict] = []
    labels: list[int] = []
    protected: dict[str, dict] = {}
    summary = LoadSummary(feature_names=feature_names)

    for raw in iter_rows(path, limit):
        summary.rows_read += 1
        target = (raw.get("TARGET") or "").strip()
        if target not in ("0", "1"):
            summary.skipped_no_label += 1
            continue

        row: dict = {}
        for name, bounds in NUMERIC_FEATURES.items():
            source = raw.get(name, "")
            if name == "DAYS_EMPLOYED" and _number(source) == DAYS_EMPLOYED_SENTINEL:
                # Not a tenure of a thousand years; a flag for "no employment
                # record". Read as missing, so the separate-bin policy handles it.
                source = ""
            value = _number(source, bounds)
            row[name] = value
            row[f"{name}_missing"] = 1.0 if value is None else 0.0

        income = _number(raw.get("AMT_INCOME_TOTAL", ""))
        credit = _number(raw.get("AMT_CREDIT", ""))
        annuity = _number(raw.get("AMT_ANNUITY", ""))
        goods = _number(raw.get("AMT_GOODS_PRICE", ""))
        row["credit_to_income"] = credit / income if income and credit else None
        row["annuity_to_income"] = annuity / income if income and annuity else None
        row["credit_to_goods"] = credit / goods if goods and credit else None

        for name in CATEGORICAL_FEATURES:
            observed = (raw.get(name) or "").strip()
            for level in levels[name]:
                row[f"{name}={level}"] = 1.0 if observed == level else 0.0

        application_id = (raw.get("SK_ID_CURR") or "").strip()
        gender = (raw.get("CODE_GENDER") or "").strip()
        if gender == UNKNOWN_GENDER or not gender:
            gender = None
            summary.unknown_gender += 1

        protected[application_id] = {
            "gender": gender,
            "age_band": age_band(_number(raw.get("DAYS_BIRTH", ""))),
            # Home Credit publishes no postcode. The region rating is the nearest
            # geographic proxy it has, and it is used *as* the pincode probe
            # rather than pretending a pincode exists.
            "pincode": (raw.get("REGION_RATING_CLIENT") or "").strip() or None,
        }

        row["application_id"] = application_id
        rows.append(row)
        labels.append(int(target))
        summary.kept += 1
        summary.positives += int(target)

    if not rows:
        raise HomeCreditError(f"{path} produced no labelled rows")
    return rows, labels, protected, summary


def to_applications(
    rows: list[dict], labels: list[int], *, decided_at: date, vintage: str
) -> list:
    """Wrap loaded rows as :class:`~lending_hub.scoring.target.Application` records.

    ``decided_at`` and ``vintage`` are *constants* here, and deliberately so: this
    source has no time axis, so every application shares one placeholder cohort.
    That is what makes :func:`lending_hub.scoring.splits.split_by_vintage` refuse
    it — one vintage cannot produce an out-of-time test — and forces the caller
    onto the registry-gated non-temporal path.
    """
    from lending_hub.scoring.target import Application

    return [
        Application(
            application_id=row["application_id"],
            decided_at=decided_at,
            vintage=vintage,
            attributes={k: v for k, v in row.items() if k != "application_id"},
            vendor_label=label,
        )
        for row, label in zip(rows, labels)
    ]

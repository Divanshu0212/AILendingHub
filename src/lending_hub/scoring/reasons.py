"""The reason-code dictionary: codes in code, sentences in data.

Phase 1 §4 WS-1.1 Step 6: "top-5 negative SHAP features → approved reason-code
dictionary `[POLICY: Compliance]`. The mapping table is *data* (editable by
legal), not code."

That sentence is a design constraint, and this module is what makes it hold.
Nothing under ``src/`` contains a customer-facing reason sentence. The table lives
in ``config/reason_codes.yaml``, a decision record stores the *code*, and the
sentence is looked up from the versioned table at render time — which is also
what lets an adverse-action letter be regenerated years later in the wording that
was actually in force, rather than in today's.

Every sentence in the shipped table is a placeholder, and :meth:`ReasonCodeTable.render`
raises on one. Reason-code wording is `[POLICY: Compliance]` (LH-203). A drafted
sentence that reads plausibly is indistinguishable from an approved one within a
few months, and by then it is in letters.

Workstream: WS-1.1 Step 6 · SRS §11.2 adverse action, §4.3.2
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from dataclasses import dataclass
from typing import Sequence

from lending_hub.decisionlog import ReasonCode
from lending_hub.definitions import Pending, Ungrounded

from .explain import Explanation

DEFAULT_TABLE = pathlib.Path("config/reason_codes.yaml")

ADVERSE_WHEN_HIGH = "adverse_when_high"
ADVERSE_WHEN_LOW = "adverse_when_low"


class ReasonTableError(Exception):
    """The reason-code table is not usable as written."""


class UnmappedReason(ReasonTableError):
    """A top adverse driver has no approved reason code.

    Raised rather than dropped. Quietly omitting the unmapped driver and sending
    the next code down the list produces a letter that states reasons which are
    *not* the principal ones — which is the specific thing adverse-action rules
    exist to prevent.
    """


@dataclass(frozen=True)
class ReasonEntry:
    """One row of the dictionary."""

    code: str
    feature: str
    direction: str
    wording: Pending | str

    @property
    def ratified(self) -> bool:
        return not isinstance(self.wording, Pending)


@dataclass
class ReasonCodeTable:
    """The loaded dictionary, addressable by feature."""

    model: str
    owner: str
    status: str
    entries: list[ReasonEntry]
    source_path: str = ""

    @property
    def by_feature(self) -> dict[str, ReasonEntry]:
        return {entry.feature: entry for entry in self.entries}

    @property
    def ratified(self) -> bool:
        return bool(self.entries) and all(entry.ratified for entry in self.entries)

    def version(self) -> str:
        """Content hash of the table, recorded on every decision that used it."""
        payload = [
            {"code": e.code, "feature": e.feature, "direction": e.direction,
             "wording": str(e.wording)}
            for e in sorted(self.entries, key=lambda e: e.code)
        ]
        blob = json.dumps(
            {"model": self.model, "entries": payload}, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    def render(self, code: str) -> str:
        """The customer-facing sentence for a code. Raises while it is `[POLICY]`."""
        entry = next((e for e in self.entries if e.code == code), None)
        if entry is None:
            raise ReasonTableError(f"{code!r} is not in the reason-code dictionary")
        if isinstance(entry.wording, Pending):
            raise Ungrounded(
                f"{entry.wording} — reason-code wording for {code!r} is not ratified. "
                "An adverse-action letter cannot be rendered from a draft sentence."
            )
        return entry.wording

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "owner": self.owner,
            "status": self.status,
            "version": self.version(),
            "ratified": self.ratified,
            "codes": [
                {"code": e.code, "feature": e.feature, "direction": e.direction,
                 "ratified": e.ratified}
                for e in self.entries
            ],
        }


def load_table(path: str | pathlib.Path = DEFAULT_TABLE) -> ReasonCodeTable:
    """Load and validate the dictionary."""
    path = pathlib.Path(path)
    if not path.exists():
        raise ReasonTableError(f"reason-code table not found: {path}")

    try:
        import yaml
    except ModuleNotFoundError as exc:  # pragma: no cover - environment dependent
        raise ReasonTableError(
            "PyYAML is needed to read the reason-code table: "
            "pip install -r requirements-dev.txt"
        ) from exc

    with path.open("r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle)

    if not isinstance(document, dict):
        raise ReasonTableError(f"{path}: expected a mapping at the top level")

    entries: list[ReasonEntry] = []
    seen_codes: set[str] = set()
    seen_features: set[str] = set()

    for index, raw in enumerate(document.get("codes") or []):
        if not isinstance(raw, dict):
            raise ReasonTableError(f"{path}: codes[{index}] is not a mapping")
        for field in ("code", "feature", "direction", "wording"):
            if not raw.get(field):
                raise ReasonTableError(f"{path}: codes[{index}] is missing {field!r}")
        if raw["direction"] not in (ADVERSE_WHEN_HIGH, ADVERSE_WHEN_LOW):
            raise ReasonTableError(
                f"{path}: codes[{index}] direction {raw['direction']!r} must be "
                f"{ADVERSE_WHEN_HIGH!r} or {ADVERSE_WHEN_LOW!r}"
            )
        if raw["code"] in seen_codes:
            raise ReasonTableError(f"{path}: duplicate code {raw['code']!r}")
        if raw["feature"] in seen_features:
            # One feature, one code. Two codes for one feature means the choice
            # between them is made somewhere in code, which is the thing this
            # table exists to prevent.
            raise ReasonTableError(
                f"{path}: feature {raw['feature']!r} already has a code; a feature "
                "maps to exactly one reason code"
            )
        seen_codes.add(raw["code"])
        seen_features.add(raw["feature"])

        wording = Pending.parse(str(raw["wording"])) or str(raw["wording"])
        entries.append(
            ReasonEntry(
                code=raw["code"],
                feature=raw["feature"],
                direction=raw["direction"],
                wording=wording,
            )
        )

    if not entries:
        raise ReasonTableError(f"{path}: the dictionary is empty")

    return ReasonCodeTable(
        model=document.get("model", ""),
        owner=document.get("owner", ""),
        status=document.get("status", ""),
        entries=entries,
        source_path=str(path),
    )


def map_reasons(
    explanation: Explanation,
    table: ReasonCodeTable,
    *,
    top: int = 5,
    strict: bool = True,
) -> list[ReasonCode]:
    """Turn the top adverse SHAP drivers into decision-log reason codes.

    Returns :class:`~lending_hub.decisionlog.ReasonCode` objects — code and
    contribution, never wording. The decision log deliberately has no field for a
    rendered sentence (Master §3.3), so this cannot accidentally freeze one.
    """
    mapping = table.by_feature
    drivers = explanation.adverse(top)

    unmapped = [d.feature for d in drivers if d.feature not in mapping]
    if unmapped and strict:
        raise UnmappedReason(
            f"no approved reason code for {sorted(unmapped)}. These are among the "
            "top adverse drivers of this decision, so omitting them would produce a "
            "letter stating reasons that are not the principal ones. Add the codes "
            "to the dictionary (config/reason_codes.yaml)."
        )

    return [
        ReasonCode(
            code=mapping[driver.feature].code,
            contribution=driver.shap,
            source="model",
        )
        for driver in drivers
        if driver.feature in mapping
    ]


def check_directions(table: ReasonCodeTable, directions: dict[str, int]) -> list[str]:
    """Cross-check the dictionary against the ratified monotonicity list.

    A code saying "adverse when high" on a feature the policy list constrains as
    *decreasing* in PD describes the opposite of the model. Both statements are
    plausible in isolation; the disagreement is only visible when they are put
    side by side, which nothing does unless something like this does it.
    """
    from .gbm import DECREASING, INCREASING

    problems: list[str] = []
    for entry in table.entries:
        direction = directions.get(entry.feature)
        if direction is None:
            continue
        if entry.direction == ADVERSE_WHEN_HIGH and direction == DECREASING:
            problems.append(
                f"{entry.code}: says adverse when high, but the ratified list "
                f"constrains {entry.feature} as decreasing in PD"
            )
        if entry.direction == ADVERSE_WHEN_LOW and direction == INCREASING:
            problems.append(
                f"{entry.code}: says adverse when low, but the ratified list "
                f"constrains {entry.feature} as increasing in PD"
            )
    return problems


def unratified_codes(table: ReasonCodeTable) -> list[str]:
    return sorted(entry.code for entry in table.entries if not entry.ratified)

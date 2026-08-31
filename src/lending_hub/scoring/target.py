"""Target-table construction for the application scorecard.

Phase 1 §4 WS-1.1 Step 1: "Versioned SQL script builds the target table: unit =
application; *bad* = [Appendix A default] within the outcome window of disbursal
(import from definitions package — never re-type). Exclusions (fraud-tagged,
staff loans, restructures) listed explicitly in the script; no undocumented
filters."

Two design choices here carry the weight, and both exist to stop a target table
from lying about itself.

**Every dropped row is attributed.** :class:`TargetLedger` reconciles
``applications_in == kept + excluded + undetermined``, and the build raises if it
does not. "No undocumented filters" is otherwise a promise about the author's
diligence rather than a property of the output — an accidental filter inside a
join condition drops rows that nobody counts, and the resulting bad rate is wrong
in a direction nobody can reconstruct.

**An exclusion whose flag is absent is a failure, not a no-op.** Phase 1 names
three exclusions. Two of them — fraud-tagged and distress restructures — depend on
code sets that are still `[POLICY]` (LH-101, LH-103), and a bank extract that does
not carry the flag will match zero rows. A filter that silently excludes nothing
reports a clean run, so :class:`Exclusion` declares which field it reads and the
build refuses to call an unenforceable exclusion "applied".

Indeterminates are **kept in the table** with ``trainable=False`` rather than
dropped. Appendix A excludes them from training targets and requires them in
scoring and reporting; a builder that drops them makes the reporting half
impossible to satisfy downstream.

Workstream: WS-1.1 Step 1 · SRS §4.2, Master Appendix A
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Callable, Iterable, Sequence

from lending_hub.definitions import (
    DEFINITIONS_VERSION,
    Label,
    OutcomeObservation,
    Pending,
    Scoring,
    fingerprint,
    label as appendix_a_label,
    observation_point,
)


class TargetError(Exception):
    """The target table cannot be built as specified."""


class UnenforceableExclusion(TargetError):
    """A declared exclusion reads a field the extract does not carry.

    Raised rather than warned. An exclusion that matches nothing because its
    column is missing is indistinguishable, in the ledger, from an exclusion that
    matched nothing because the population is clean — and the two have opposite
    implications for the bad rate.
    """


class LabelProvenance(str, Enum):
    """Where a row's label came from. Recorded on every table and model card."""

    APPENDIX_A = "appendix_a"
    """Derived by :func:`lending_hub.definitions.label` from an observed outcome."""

    VENDOR = "vendor"
    """Supplied ready-made by the source. Not Appendix A, however similar it looks.

    Home Credit's ``TARGET`` is the case this exists for: a vendor's own
    definition of payment difficulty, with its own window and its own thresholds.
    Treating it as Appendix A would make every downstream comparison against a
    bank model an apples-to-oranges claim that nothing in the pipeline could
    detect.
    """


@dataclass(frozen=True)
class Application:
    """One application, at its Appendix A observation point.

    ``attributes`` holds candidate feature inputs and must already be as-of
    ``decided_at`` — this module does not enforce point-in-time correctness, which
    is :mod:`lending_hub.featurestore.pit`'s job. ``flags`` holds the exclusion
    signals, kept separate so a flag can never be mistaken for a feature.
    """

    application_id: str
    decided_at: date
    vintage: str
    """The split key: the cohort this application belongs to (e.g. "2019Q1")."""

    attributes: dict = field(default_factory=dict)
    flags: dict = field(default_factory=dict)

    observation: OutcomeObservation | None = None
    """The observed outcome. ``None`` means the outcome is not determined —
    censored, or the window has not closed. Distinct from an outcome of zero."""

    vendor_label: int | None = None
    """A ready-made label, for sources that publish one instead of an outcome
    history. Mutually exclusive with ``observation``."""

    def __post_init__(self) -> None:
        if self.observation is not None and self.vendor_label is not None:
            raise TargetError(
                f"{self.application_id}: both an observed outcome and a vendor label. "
                "Pick one — a row labelled two ways is a row whose definition nobody "
                "can state."
            )
        if self.vendor_label not in (None, 0, 1):
            raise TargetError(f"{self.application_id}: vendor_label must be 0, 1 or None")
        # The observation point is Appendix A's, and it is checked rather than
        # assumed: an application scored on a timestamp other than its final
        # decision has features from the wrong instant.
        observation_point(Scoring.APPLICATION, final_decision_at=self.decided_at)


@dataclass(frozen=True)
class Exclusion:
    """One explicitly declared reason a row leaves the target population.

    ``reads`` names the flag field the predicate depends on. It is not
    decoration: the build checks that the field is actually present on the
    population before it will report the exclusion as applied.
    """

    code: str
    reason: str
    grounding: str
    """The clause or policy that requires this exclusion. `[SPEC]` clause, or the
    committee that owns it."""

    reads: str
    predicate: Callable[[dict], bool]
    blocked_by: Pending | None = None
    """Set when the flag itself depends on an unresolved `[POLICY]` code set. The
    exclusion is still declared — what is blocked is the bank's ability to
    populate the field, not this program's ability to name the filter."""


def _flag(field_name: str) -> Callable[[dict], bool]:
    return lambda flags: bool(flags.get(field_name))


#: Phase 1 §4 WS-1.1 Step 1 names exactly these three. They are listed here, in
#: code, rather than in a SQL comment, so that the set is importable, testable and
#: diffable — Phase 1 requires them "listed explicitly in the script".
PHASE_1_EXCLUSIONS: tuple[Exclusion, ...] = (
    Exclusion(
        code="FRAUD_TAGGED",
        reason=(
            "Confirmed-fraud accounts are excluded from the credit target. Fraud is "
            "modelled by WS-1.2; leaving these rows in teaches the credit scorecard "
            "to predict fraud with credit features, which is neither model's job and "
            "degrades both."
        ),
        grounding="Phase_1_Credit_Scoring_Fraud.md §4 WS-1.1 Step 1 [SPEC]",
        reads="fraud_confirmed",
        predicate=_flag("fraud_confirmed"),
        blocked_by=Pending(
            owner="Fraud Head",
            ticket="LH-101",
            note=(
                "the approved fraud-desk disposition taxonomy. Until it exists no "
                "extract can populate fraud_confirmed, and this exclusion matches "
                "nothing for the wrong reason."
            ),
        ),
    ),
    Exclusion(
        code="STAFF_LOAN",
        reason=(
            "Staff loans price and perform on employment terms, not credit terms. "
            "They are a different product wearing the same product code."
        ),
        grounding="Phase_1_Credit_Scoring_Fraud.md §4 WS-1.1 Step 1 [SPEC]",
        reads="staff_loan",
        predicate=_flag("staff_loan"),
    ),
    Exclusion(
        code="RESTRUCTURE",
        reason=(
            "Restructured accounts have had their contractual terms changed, so the "
            "outcome observed is the outcome of the restructure, not of the original "
            "underwriting decision."
        ),
        grounding="Phase_1_Credit_Scoring_Fraud.md §4 WS-1.1 Step 1 [SPEC]",
        reads="restructured",
        predicate=_flag("restructured"),
        blocked_by=Pending(
            owner="Credit Policy",
            ticket="LH-103",
            note=(
                "the CBS reason codes that mark a restructure. Appendix A already "
                "needs them to identify distress restructures as defaults; the same "
                "code set decides which rows leave the population here."
            ),
        ),
    ),
)


@dataclass(frozen=True)
class TargetRow:
    """One row of the target table."""

    application_id: str
    decided_at: date
    vintage: str
    label: Label
    trainable: bool
    """False for indeterminates. Appendix A keeps them in scoring and reporting
    and out of training targets, so both consumers read one table."""

    attributes: dict = field(default_factory=dict)

    @property
    def y(self) -> int:
        """The binary training target. Only meaningful when ``trainable``."""
        if not self.trainable:
            raise TargetError(
                f"{self.application_id} is {self.label.value}; Appendix A excludes it "
                "from training targets. Filter on .trainable before reading .y"
            )
        return 1 if self.label is Label.BAD else 0


@dataclass
class TargetLedger:
    """What the build did to every input row, and whether it adds up."""

    applications_in: int = 0
    kept: int = 0
    undetermined: int = 0
    excluded: dict[str, int] = field(default_factory=dict)
    labels: dict[str, int] = field(default_factory=dict)
    unenforceable: list[str] = field(default_factory=list)
    exclusions_declared: list[str] = field(default_factory=list)

    @property
    def excluded_total(self) -> int:
        return sum(self.excluded.values())

    @property
    def trainable(self) -> int:
        return self.labels.get(Label.GOOD.value, 0) + self.labels.get(Label.BAD.value, 0)

    @property
    def bads(self) -> int:
        return self.labels.get(Label.BAD.value, 0)

    @property
    def bad_rate(self) -> float | None:
        """Bad rate over trainable rows. ``None`` when nothing is trainable.

        Not zero. A population with no observed outcome has an unknown bad rate,
        and rendering that as 0.0 puts a number on a dashboard that reads as
        "no defaults" rather than "no data".
        """
        if self.trainable == 0:
            return None
        return self.bads / self.trainable

    def reconciles(self) -> bool:
        return self.applications_in == self.kept + self.undetermined + self.excluded_total

    def to_dict(self) -> dict:
        return {
            "applications_in": self.applications_in,
            "kept": self.kept,
            "undetermined": self.undetermined,
            "excluded": dict(sorted(self.excluded.items())),
            "excluded_total": self.excluded_total,
            "exclusions_declared": sorted(self.exclusions_declared),
            "unenforceable_exclusions": sorted(self.unenforceable),
            "labels": dict(sorted(self.labels.items())),
            "trainable": self.trainable,
            "bads": self.bads,
            "bad_rate": self.bad_rate,
            "reconciles": self.reconciles(),
        }


@dataclass
class TargetTable:
    """The target table plus everything needed to say what it is."""

    rows: list[TargetRow]
    ledger: TargetLedger
    provenance: LabelProvenance
    dataset: str
    definitions_version: str = DEFINITIONS_VERSION
    definitions_fingerprint: str = ""
    label_note: str = ""
    """Required for a vendor label: what the source's definition actually is."""

    def __len__(self) -> int:
        return len(self.rows)

    @property
    def trainable_rows(self) -> list[TargetRow]:
        return [row for row in self.rows if row.trainable]

    def manifest(self) -> dict:
        return {
            "dataset": self.dataset,
            "label_provenance": self.provenance.value,
            "label_note": self.label_note,
            "definitions_version": self.definitions_version,
            "definitions_fingerprint": self.definitions_fingerprint,
            "appendix_a_aligned": self.provenance is LabelProvenance.APPENDIX_A,
            "ledger": self.ledger.to_dict(),
            "vintages": sorted({row.vintage for row in self.rows}),
        }

    def manifest_hash(self) -> str:
        blob = json.dumps(self.manifest(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def build_target_table(
    applications: Iterable[Application],
    *,
    dataset: str,
    exclusions: Sequence[Exclusion] = PHASE_1_EXCLUSIONS,
    provenance: LabelProvenance = LabelProvenance.APPENDIX_A,
    label_note: str = "",
    require_enforceable: bool = True,
) -> TargetTable:
    """Build the target table, attributing every row that does not survive.

    ``require_enforceable`` controls what happens when a declared exclusion reads
    a flag that no input row carries. The default refuses, because "the filter
    removed nothing" and "the filter could not run" produce identical ledgers and
    opposite conclusions. Set it False only for a population that legitimately has
    no such flag — a public dataset with no fraud tagging at all — and take the
    limitation onto the model card.
    """
    applications = list(applications)

    if provenance is LabelProvenance.VENDOR and not label_note:
        raise TargetError(
            "a vendor label must state the source's own definition. Without it, "
            "nobody downstream can tell what the model was fitted to predict."
        )

    present_flags: set[str] = set()
    for application in applications:
        present_flags |= set(application.flags)

    ledger = TargetLedger(
        applications_in=len(applications),
        exclusions_declared=[exclusion.code for exclusion in exclusions],
    )
    for exclusion in exclusions:
        if exclusion.reads not in present_flags:
            ledger.unenforceable.append(exclusion.code)

    if ledger.unenforceable and require_enforceable:
        detail = ", ".join(
            f"{code} (reads {next(e.reads for e in exclusions if e.code == code)!r})"
            for code in ledger.unenforceable
        )
        raise UnenforceableExclusion(
            f"{detail}: no input row carries this flag, so the exclusion cannot run. "
            "An exclusion that matches nothing because its column is missing looks "
            "exactly like a clean population in the ledger. Supply the flag, drop the "
            "exclusion deliberately, or pass require_enforceable=False and record the "
            "limitation on the model card."
        )

    rows: list[TargetRow] = []
    for application in applications:
        excluded_by = next(
            (e.code for e in exclusions if e.code not in ledger.unenforceable
             and e.predicate(application.flags)),
            None,
        )
        if excluded_by is not None:
            ledger.excluded[excluded_by] = ledger.excluded.get(excluded_by, 0) + 1
            continue

        row_label = _label_for(application, provenance)
        if row_label is None:
            ledger.undetermined += 1
            continue

        ledger.kept += 1
        ledger.labels[row_label.value] = ledger.labels.get(row_label.value, 0) + 1
        rows.append(
            TargetRow(
                application_id=application.application_id,
                decided_at=application.decided_at,
                vintage=application.vintage,
                label=row_label,
                trainable=row_label is not Label.INDETERMINATE,
                attributes=dict(application.attributes),
            )
        )

    if not ledger.reconciles():
        raise TargetError(
            f"ledger does not reconcile: {ledger.applications_in} in, "
            f"{ledger.kept} kept + {ledger.undetermined} undetermined + "
            f"{ledger.excluded_total} excluded. Rows have gone missing inside the "
            "build, which is the undocumented filter Phase 1 forbids."
        )

    return TargetTable(
        rows=rows,
        ledger=ledger,
        provenance=provenance,
        dataset=dataset,
        definitions_fingerprint=fingerprint(),
        label_note=label_note,
    )


def _label_for(application: Application, provenance: LabelProvenance) -> Label | None:
    if provenance is LabelProvenance.APPENDIX_A:
        if application.observation is None:
            return None
        return appendix_a_label(application.observation)

    if application.vendor_label is None:
        return None
    # A vendor label is binary by construction: the source published a decision,
    # not an outcome history, so there is no indeterminate band to preserve.
    return Label.BAD if application.vendor_label == 1 else Label.GOOD

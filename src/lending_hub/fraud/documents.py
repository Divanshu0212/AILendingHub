"""Document checks v1 — deterministic arithmetic, and the AA-first rule.

Phase 1 §4 WS-1.2 Step 5: "OCR (docTR/Tesseract) + deterministic cross-field
arithmetic: salary-slip totals, bank-statement balance continuity across months,
IFSC validity. **AA-first rule:** where Account-Aggregator consent exists, AA data
overrides uploaded PDFs; 'AA refused + PDF uploaded' becomes a model feature.
(Tamper-detection CNNs are Phase 6.)"

Nothing here is a model
-----------------------
Every check is arithmetic with a right answer. That is the point of shipping them
first: a salary slip whose deductions do not subtract to its stated net is
*wrong*, not suspicious, and it needs no threshold, no training data and no
explanation beyond the sum. Layer 4's tamper-detection CNNs are Phase 6 precisely
because they are the part that needs judgement.

Money is integer minor units throughout, matching the WS-0.1.4 stream schemas.
Float rupees would force a tolerance on every comparison, and a tolerance on a
continuity check is a place for a small forgery to live.

Why AA-first is a rule and not a preference
-------------------------------------------
Account-Aggregator data is fetched from the source bank under consent, so the
applicant never handles it and cannot alter it. An uploaded PDF passed through
the applicant's hands. When both exist and disagree, the question is not which is
more likely correct — it is that only one of them is evidence. So
:func:`reconcile` does not average, does not warn and does not prefer: AA wins,
and the disagreement is recorded as a signal.

The second half is subtler and is the one people drop. SRS §5.3.4 says to treat
"customer refuses AA but uploads PDF" as a risk signal. That is a statement about
a *choice*, and it only means anything if the platform distinguishes "AA was
offered and refused" from "AA was never offered" — which is a product-flow fact,
not a document fact. :class:`ConsentPosture` carries it, and
:func:`aa_first_features` emits nothing at all when the posture is unknown rather
than defaulting to the innocent reading.

Workstream: WS-1.2 Step 5 · SRS §5.3.4, §5.2 (FR-4)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, Sequence

from lending_hub.definitions import Pending

#: IFSC format, defined by RBI and public: four alphabetic bank characters, a
#: reserved '0', then six alphanumeric branch characters. Format only — see
#: :data:`BRANCH_DIRECTORY`.
IFSC_PATTERN = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")

#: Whether a format-valid IFSC names a branch that exists.
BRANCH_DIRECTORY = Pending(
    owner="Payments Operations",
    ticket="LH-210",
    note=(
        "the authoritative bank-branch directory (or the NPCI/RBI lookup) that "
        "says whether a format-valid IFSC is a real branch. Format validity is a "
        "regex; existence is a lookup, and a forger who knows the format passes "
        "the regex every time"
    ),
)


class DocumentError(Exception):
    """The document cannot be checked as supplied."""


class CheckStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    NOT_CHECKABLE = "not_checkable"
    """A required field was absent or unreadable. Distinct from FAIL: a missing
    field is an extraction problem, and reporting it as a failed check sends a
    fraud analyst to look for a forgery that is really a bad scan."""


class ConsentPosture(str, Enum):
    """What the applicant did about Account Aggregator consent."""

    GRANTED = "granted"
    REFUSED = "refused"
    """Offered and declined. The risk-signal case."""

    NOT_OFFERED = "not_offered"
    """The flow never asked — no signal at all, and not the applicant's choice."""

    UNKNOWN = "unknown"
    """The platform did not record it. Emits no feature; see the module docstring."""


@dataclass(frozen=True)
class CheckResult:
    check: str
    status: CheckStatus
    detail: str
    evidence: dict = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        return self.status is CheckStatus.FAIL

    def to_dict(self) -> dict:
        return {
            "check": self.check,
            "status": self.status.value,
            "detail": self.detail,
            "evidence": self.evidence,
        }


class OCRPort(Protocol):
    """Track B is docTR or Tesseract; Track A is already-extracted fields.

    OCR is deliberately outside this module. Extraction is a vision problem with
    its own error modes, and mixing it with the arithmetic would mean an
    unreadable scan and a forged total came back as the same finding.
    """

    def extract(self, document_bytes: bytes) -> dict:
        ...


@dataclass(frozen=True)
class SalarySlip:
    """Extracted salary-slip fields, money in integer minor units."""

    employee_name: str
    period: str
    earnings: dict[str, int]
    deductions: dict[str, int]
    stated_gross: int | None = None
    stated_net: int | None = None


def check_salary_slip(slip: SalarySlip) -> list[CheckResult]:
    """Recompute the totals the slip states.

    Two separate checks, not one. A slip whose components sum to the wrong gross
    has a different problem from one whose gross minus deductions misses the net,
    and a forger who edits one line usually breaks exactly one of them.
    """
    results: list[CheckResult] = []
    computed_gross = sum(slip.earnings.values())
    computed_net = computed_gross - sum(slip.deductions.values())

    if slip.stated_gross is None:
        results.append(
            CheckResult(
                "salary_slip_gross", CheckStatus.NOT_CHECKABLE,
                "no stated gross was extracted from the slip",
            )
        )
    else:
        matched = slip.stated_gross == computed_gross
        results.append(
            CheckResult(
                "salary_slip_gross",
                CheckStatus.PASS if matched else CheckStatus.FAIL,
                (
                    "earnings sum to the stated gross"
                    if matched
                    else f"earnings sum to {computed_gross}, slip states {slip.stated_gross}"
                ),
                {"computed": computed_gross, "stated": slip.stated_gross},
            )
        )

    if slip.stated_net is None:
        results.append(
            CheckResult(
                "salary_slip_net", CheckStatus.NOT_CHECKABLE,
                "no stated net was extracted from the slip",
            )
        )
    else:
        matched = slip.stated_net == computed_net
        results.append(
            CheckResult(
                "salary_slip_net",
                CheckStatus.PASS if matched else CheckStatus.FAIL,
                (
                    "gross less deductions equals the stated net"
                    if matched
                    else f"gross less deductions is {computed_net}, slip states {slip.stated_net}"
                ),
                {"computed": computed_net, "stated": slip.stated_net},
            )
        )
    return results


@dataclass(frozen=True)
class StatementMonth:
    """One month of a bank statement, money in integer minor units."""

    period: str
    opening_balance: int
    closing_balance: int
    credits: int
    debits: int


def check_balance_continuity(months: Sequence[StatementMonth]) -> list[CheckResult]:
    """Two independent arithmetic identities across a statement.

    Within a month: ``closing == opening + credits − debits``.
    Between months: this month's opening equals last month's closing.

    Both, because they fail differently. Editing a single transaction breaks the
    within-month identity; editing a closing balance to inflate an average breaks
    the between-month one, and a check that tested only one of them would miss
    half the forgeries it exists for.
    """
    if not months:
        raise DocumentError("no statement months supplied")

    results: list[CheckResult] = []
    for month in months:
        expected = month.opening_balance + month.credits - month.debits
        matched = expected == month.closing_balance
        results.append(
            CheckResult(
                f"statement_month_arithmetic:{month.period}",
                CheckStatus.PASS if matched else CheckStatus.FAIL,
                (
                    "opening plus credits less debits equals closing"
                    if matched
                    else f"expected closing {expected}, statement shows "
                         f"{month.closing_balance}"
                ),
                {"expected": expected, "stated": month.closing_balance},
            )
        )

    for previous, current in zip(months, months[1:]):
        matched = previous.closing_balance == current.opening_balance
        results.append(
            CheckResult(
                f"statement_continuity:{previous.period}->{current.period}",
                CheckStatus.PASS if matched else CheckStatus.FAIL,
                (
                    "closing balance carries into the next month's opening"
                    if matched
                    else f"{previous.period} closes at {previous.closing_balance} but "
                         f"{current.period} opens at {current.opening_balance}"
                ),
                {
                    "previous_closing": previous.closing_balance,
                    "next_opening": current.opening_balance,
                },
            )
        )
    return results


def check_ifsc(code: str) -> CheckResult:
    """Validate an IFSC's *format*. Existence is a lookup, and it is blocked.

    The distinction matters more than it looks, and Phase 1 §4 WS-1.2 Step 5
    (v1.1) now names both halves separately: a forger who knows the format passes
    the regex every time, so a green "IFSC valid" on a format check alone is close
    to worthless as a fraud control while reading exactly like a meaningful one on
    a checklist. Report which of the two was performed.
    """
    normalised = (code or "").strip().upper()
    if not normalised:
        return CheckResult("ifsc_format", CheckStatus.NOT_CHECKABLE, "no IFSC supplied")
    if not IFSC_PATTERN.match(normalised):
        return CheckResult(
            "ifsc_format", CheckStatus.FAIL,
            f"{normalised!r} is not a valid IFSC: four alphabetic bank characters, "
            "a reserved '0', then six alphanumeric branch characters",
            {"ifsc": normalised},
        )
    return CheckResult(
        "ifsc_format", CheckStatus.PASS,
        "format is valid; branch existence is not checked — "
        f"{BRANCH_DIRECTORY}",
        {"ifsc": normalised, "existence_checked": False},
    )


@dataclass(frozen=True)
class Reconciliation:
    """The outcome of comparing an uploaded document against AA data."""

    field_name: str
    aa_value: int | None
    document_value: int | None
    used_value: int | None
    source: str
    disagreed: bool

    def to_dict(self) -> dict:
        return {
            "field": self.field_name,
            "aa_value": self.aa_value,
            "document_value": self.document_value,
            "used_value": self.used_value,
            "source": self.source,
            "disagreed": self.disagreed,
        }


def reconcile(
    field_name: str, *, aa_value: int | None, document_value: int | None
) -> Reconciliation:
    """The AA-first rule.

    Where both exist, AA wins outright — no averaging, no tolerance, no
    preference weighting. AA data is fetched from the source bank under consent
    and never passed through the applicant's hands; the uploaded document did.
    When they disagree the question is not which is more likely correct, it is
    that only one of them is evidence.

    The disagreement itself is preserved, because a *contradicted* document is a
    far stronger signal than a merely absent one.
    """
    if aa_value is not None:
        return Reconciliation(
            field_name=field_name,
            aa_value=aa_value,
            document_value=document_value,
            used_value=aa_value,
            source="account_aggregator",
            disagreed=document_value is not None and document_value != aa_value,
        )
    return Reconciliation(
        field_name=field_name,
        aa_value=None,
        document_value=document_value,
        used_value=document_value,
        source="uploaded_document" if document_value is not None else "none",
        disagreed=False,
    )


def aa_first_features(
    posture: ConsentPosture, *, documents_uploaded: int, reconciliations: Sequence[Reconciliation] = ()
) -> dict[str, float]:
    """Model features from the applicant's AA posture and any contradictions.

    Emits nothing when the posture is UNKNOWN. A refusal is a *choice*, and it is
    only a signal if the platform can tell it apart from never having been asked —
    which is a product-flow fact, not a document fact. Defaulting an unrecorded
    posture to "not refused" would mean every application from a flow that forgot
    to log consent reads as the innocent case.
    """
    if posture is ConsentPosture.UNKNOWN:
        return {}

    features: dict[str, float] = {
        "aa_consent_granted": 1.0 if posture is ConsentPosture.GRANTED else 0.0,
        "aa_refused_with_documents": (
            1.0 if posture is ConsentPosture.REFUSED and documents_uploaded > 0 else 0.0
        ),
    }
    if reconciliations:
        features["aa_document_disagreements"] = float(
            sum(1 for item in reconciliations if item.disagreed)
        )
    return features


@dataclass
class DocumentCheckReport:
    """Everything the orchestrator needs from document checks v1."""

    application_id: str
    results: list[CheckResult] = field(default_factory=list)
    reconciliations: list[Reconciliation] = field(default_factory=list)
    posture: ConsentPosture = ConsentPosture.UNKNOWN
    documents_uploaded: int = 0

    @property
    def failures(self) -> list[CheckResult]:
        return [result for result in self.results if result.failed]

    @property
    def not_checkable(self) -> list[CheckResult]:
        return [r for r in self.results if r.status is CheckStatus.NOT_CHECKABLE]

    def features(self) -> dict[str, float]:
        base = {
            "doc_check_failures": float(len(self.failures)),
            "doc_check_not_checkable": float(len(self.not_checkable)),
        }
        base.update(
            aa_first_features(
                self.posture,
                documents_uploaded=self.documents_uploaded,
                reconciliations=self.reconciliations,
            )
        )
        return base

    def to_dict(self) -> dict:
        return {
            "application_id": self.application_id,
            "posture": self.posture.value,
            "documents_uploaded": self.documents_uploaded,
            "failures": [r.to_dict() for r in self.failures],
            "not_checkable": [r.to_dict() for r in self.not_checkable],
            "results": [r.to_dict() for r in self.results],
            "reconciliations": [r.to_dict() for r in self.reconciliations],
            "features": self.features(),
            "tamper_detection": "Phase 6 (SRS §5.3.4); not attempted here",
        }

"""GL reconciliation.

Phase 0 WS-0.1.5: "reconciliation: portfolio totals vs. finance GL within 0.1%;
the reconciliation script is committed and rerunnable."

Two things this script will not do:

* **Invent the GL mapping.** Which loan products roll up to which GL account is on
  the Phase 0 do-not-invent list (LH-150). A reconciliation built on a guessed
  mapping produces a number that looks like agreement and means nothing.
* **Reconcile in floating point.** Amounts are integer minor units end to end.
  Summing rupees as floats across millions of rows accumulates error at the same
  order of magnitude as the 0.1% tolerance, so the test would be measuring its
  own arithmetic.

Workstream: WS-0.1.5
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime

from lending_hub.definitions.provenance import Pending

#: Phase 0 WS-0.1.5 / §7 exit criteria: "GL delta <= 0.1%". [SPEC]
GL_TOLERANCE = 0.001

#: The product -> GL account mapping. [POLICY] — Phase 0 §8 do-not-invent list.
GL_ACCOUNT_MAPPING = Pending(
    owner="Finance Controller",
    ticket="LH-150",
    note="which loan products and balance types roll up to which GL account",
)


@dataclass
class AccountDelta:
    gl_account: str
    platform_minor_units: int
    gl_minor_units: int

    @property
    def delta_minor_units(self) -> int:
        return self.platform_minor_units - self.gl_minor_units

    @property
    def relative_delta(self) -> float | None:
        """None when the GL side is zero — a delta against nothing is not a ratio."""
        if self.gl_minor_units == 0:
            return None
        return abs(self.delta_minor_units) / abs(self.gl_minor_units)

    @property
    def within_tolerance(self) -> bool:
        if self.gl_minor_units == 0:
            return self.platform_minor_units == 0
        return self.relative_delta <= GL_TOLERANCE

    def to_dict(self) -> dict:
        return {
            "gl_account": self.gl_account,
            "platform_minor_units": self.platform_minor_units,
            "gl_minor_units": self.gl_minor_units,
            "delta_minor_units": self.delta_minor_units,
            "relative_delta": self.relative_delta,
            "within_tolerance": self.within_tolerance,
        }


@dataclass
class ReconciliationReport:
    track: str
    as_of: str
    deltas: list[AccountDelta] = field(default_factory=list)
    unmapped_products: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """Every account within tolerance, nothing unmapped, and something measured.

        An unmapped product silently drops balances out of the platform total and
        makes the reconciliation *look better*, so it has to fail the run rather
        than appear as a note.
        """
        return (
            bool(self.deltas)
            and not self.unmapped_products
            and all(d.within_tolerance for d in self.deltas)
        )

    def to_dict(self) -> dict:
        return {
            "track": self.track,
            "as_of": self.as_of,
            "tolerance": GL_TOLERANCE,
            "accounts": [d.to_dict() for d in self.deltas],
            "unmapped_products": self.unmapped_products,
            "passed": self.passed,
            "mapping_source": str(GL_ACCOUNT_MAPPING),
        }


def reconcile(
    platform_balances: list[dict],
    gl_balances: dict[str, int],
    product_to_gl_account: dict[str, str],
    *,
    track: str,
    as_of: str,
) -> ReconciliationReport:
    """Compare platform balances against GL totals, per GL account.

    ``platform_balances`` rows carry ``product_code`` and ``balance_minor_units``
    (integers). ``product_to_gl_account`` is supplied by the caller because it is
    a `[POLICY]` mapping — this function applies one, it does not know one.
    """
    report = ReconciliationReport(track=track, as_of=as_of)
    totals: dict[str, int] = defaultdict(int)
    unmapped: set[str] = set()

    for row in platform_balances:
        product = row["product_code"]
        amount = row["balance_minor_units"]
        if not isinstance(amount, int):
            raise TypeError(
                f"{product}: balance_minor_units must be an integer, got "
                f"{type(amount).__name__}. Float money accumulates error at the "
                "same order as the 0.1% tolerance."
            )
        account = product_to_gl_account.get(product)
        if account is None:
            unmapped.add(product)
            continue
        totals[account] += amount

    report.unmapped_products = sorted(unmapped)

    for account in sorted(set(totals) | set(gl_balances)):
        report.deltas.append(
            AccountDelta(account, totals.get(account, 0), gl_balances.get(account, 0))
        )

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--track", choices=["A", "B"], default="B")
    parser.add_argument("--out", default="reports/gl_reconciliation.json")
    args = parser.parse_args(argv)

    print(
        "GL reconciliation cannot run.\n"
        f"  The product -> GL account mapping is {GL_ACCOUNT_MAPPING} "
        "(Phase 0 §8 do-not-invent list),\n"
        "  and the finance GL extract requires source access (LH-120).\n\n"
        "  The comparison logic is implemented and unit-tested in\n"
        "  lending_hub.lakehouse.reconcile.reconcile(); it needs the mapping and\n"
        "  the two balance sets to produce a number. A reconciliation run on a\n"
        "  guessed mapping would produce agreement that means nothing, which is\n"
        "  worse than no number at all.",
        file=sys.stderr,
    )
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "status": "blocked",
                "blocked_on": ["LH-150", "LH-120"],
                "tolerance": GL_TOLERANCE,
                "generated_at": datetime.now(UTC).isoformat(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

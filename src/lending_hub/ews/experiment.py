"""Track P runner — the EWS detection layer on a real mortgage panel.

ADR-0014 splits Phase 4 in two: **detection** is measurable on Track P, and
**disposition and action** are not measurable at all and are not simulated. This
module is the measurable half, and its output is deliberately narrow.

What it measures
-----------------
One question, the central EWS claim: **does hazard deterioration precede
default, and by how long?** The Fannie Mae panel supplies real accounts, real
defaults and the real trajectories that preceded them, so the answer is a fact
about mortgage lending rather than a property of a simulator.

Concretely: fit the P3 behavioural hazard model on months before the split, then
walk each held-out account month by month computing a 30-day PD velocity, rank
each month's velocities into a portfolio percentile, raise an alert when an
account enters the top band, and score the resulting alerts against observed
defaults with :mod:`lending_hub.ews.backtest`.

What it deliberately does not measure
---------------------------------------
No precision. Precision needs confirmed-relevant dispositions from a collections
desk (LH-510), and the available substitute — scoring alerts against whether the
account later defaulted — measures the opposite of what it is named for, because
an alert that found real distress the bank then cured would count as a false
positive. The report says "not measurable" and carries the reason rather than
carrying a number.

No offers, no take-up, no bandit. The reward is undefined (LH-509) and every
input is LH-510.

The percentile band is swept, not chosen
------------------------------------------
LH-501 has not ratified an alert percentile, so this runner reports capture and
lead time **across a sweep of bands** rather than picking one. That is more
useful than an arbitrary choice anyway: the sweep is exactly the table a
Collections Head needs to set the budget, because it maps alert volume onto
capture rate on this book.

Workstream: WS-4.A (SRS §10), ADR-0014
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
from datetime import date, datetime, timedelta, timezone

from lending_hub.definitions import fingerprint
from lending_hub.ews import backtest as bt
from lending_hub.ews.routing import Tier
from lending_hub.ews.velocity import (
    MIN_PORTFOLIO_FOR_PERCENTILE,
    PdReading,
    portfolio_percentiles,
    velocity,
)
from lending_hub.portfolio import behavioural as beh
from lending_hub.portfolio.panel import split_by_snapshot
from lending_hub.scoring.gbm import MonotoneConstraints
from lending_hub.sources import fanniemae_panel

#: Out-of-time split. The same date Phase 3 uses, so the two runs describe the
#: same train/test boundary and their numbers can be read side by side.
SPLIT_SNAPSHOT = "2012-12-31"

#: Percentile bands to sweep. The trigger percentile is LH-501 and is not
#: chosen here; this is the table that would let it be chosen.
PERCENTILE_SWEEP = (0.90, 0.95, 0.98, 0.99)


def _as_date(text: str) -> date:
    return date.fromisoformat(text)


def run(path: str, output: str, *, sample_rate: float, row_limit: int | None) -> dict:
    started = time.time()
    report: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "track": "P",
        "dataset": "fannie_mae_sf_loan_performance",
        "vintage": os.path.basename(path).replace(".csv", ""),
        "definitions_fingerprint": fingerprint(),
        "gate_evidence": False,
        "note": (
            "Track P (ADR-0004, ADR-0014): real US conforming mortgages, not "
            "this bank's portfolio. These figures prove the Phase 4 detection "
            "code paths run against real data and measure whether hazard "
            "deterioration precedes default. They are not Phase 4 gate evidence. "
            "No precision figure appears here: precision needs collections "
            "dispositions (LH-510) and the default outcome is not a substitute."
        ),
    }

    print(f"loading {path} at sample rate {sample_rate} ...")
    panel, load_summary = fanniemae_panel.load_panel(
        path, sample_rate=sample_rate, row_limit=row_limit, vintage=report["vintage"]
    )
    report["panel"] = load_summary.to_dict()
    print(
        f"  {load_summary.loans_sampled:,} loans, "
        f"{load_summary.account_months:,} account-months"
    )

    # ------------------------------------------------------------ hazard model
    print("fitting the P3 behavioural hazard model ...")
    origination = ["oltv", "credit_score", "dti", "orig_rate", "orig_term"]
    rows = beh.build_design(panel, min_months_on_book=3)
    names = beh.feature_names(origination)
    train, test = split_by_snapshot(rows, cutoff=_as_date(SPLIT_SNAPSHOT))

    if not train or not test:
        raise SystemExit(
            f"split at {SPLIT_SNAPSHOT} left {len(train)} train / {len(test)} test "
            "rows; widen the sample or move the split"
        )

    constraints = MonotoneConstraints.for_experiment(
        names, reason="Track P EWS velocity run; behavioural directions are LH-310"
    )
    model = beh.fit_behavioural(
        train, names, constraints,
        horizon_months=12, n_trees=40, max_depth=4, learning_rate=0.1,
    )
    report["hazard_model"] = {
        "train_rows": len(train),
        "test_rows": len(test),
        "features": len(names),
        "split_snapshot": SPLIT_SNAPSHOT,
    }
    print(f"  trained on {len(train):,} rows, {len(names)} features")

    # ------------------------------------------------- PD readings per account
    print("scoring monthly PDs on held-out months ...")
    readings: dict[str, list[PdReading]] = {}
    for row in test:
        pd_value = model.predict(row.features)
        readings.setdefault(row.account_id, []).append(
            PdReading(account_id=row.account_id, as_of=row.snapshot, pd=pd_value)
        )
    for series in readings.values():
        series.sort(key=lambda r: r.as_of)

    report["pd_readings"] = {
        "accounts": len(readings),
        "readings": sum(len(v) for v in readings.values()),
    }

    # -------------------------------------------------- velocities by snapshot
    print("computing 30-day PD velocities ...")
    by_snapshot: dict[date, list] = {}
    for account_id, series in readings.items():
        for previous, current in zip(series, series[1:]):
            gap = (current.as_of - previous.as_of).days
            if not 25 <= gap <= 35:
                continue
            try:
                by_snapshot.setdefault(current.as_of, []).append(
                    velocity(previous, current)
                )
            except Exception:  # pragma: no cover - defensive on real data
                continue

    usable = {
        snapshot: velocities
        for snapshot, velocities in by_snapshot.items()
        if len(velocities) >= MIN_PORTFOLIO_FOR_PERCENTILE
    }
    report["velocity"] = {
        "snapshots_with_velocities": len(by_snapshot),
        "snapshots_rankable": len(usable),
        "min_portfolio_for_percentile": MIN_PORTFOLIO_FOR_PERCENTILE,
        "total_velocities": sum(len(v) for v in usable.values()),
    }
    print(
        f"  {len(usable):,} snapshots rankable "
        f"({sum(len(v) for v in usable.values()):,} velocities)"
    )

    if not usable:
        report["capture_sweep"] = {
            "state": "not measurable",
            "reason": (
                "no snapshot had enough concurrent accounts to form a portfolio "
                f"percentile (minimum {MIN_PORTFOLIO_FOR_PERCENTILE}). Raise the "
                "sample rate."
            ),
        }
        report["elapsed_seconds"] = round(time.time() - started, 1)
        _write(report, output)
        return report

    # ------------------------------------------------------- observed defaults
    #
    # Scored against **reachable** defaults only. The detector alerts on
    # held-out snapshots, so a default that happened before the first of them
    # could not have been alerted on by construction. Including those in the
    # denominator does not measure a worse detector, it measures the split — and
    # on this panel it would report capture at roughly a tenth of its real value,
    # because the 2007Q1 vintage front-loads its defaults into the 2008-11 credit
    # event, which sits entirely before the out-of-time boundary.
    all_defaults = []
    for spell in panel.spells:
        if spell.event is not None and spell.event.value == "default" and spell.event_month:
            all_defaults.append(
                bt.ObservedDefault(
                    account_id=spell.account_id, defaulted_on=spell.event_month
                )
            )

    first_alertable = min(usable)
    defaults = [d for d in all_defaults if d.defaulted_on > first_alertable]
    unreachable = len(all_defaults) - len(defaults)

    report["observed_defaults"] = {
        "in_panel": len(all_defaults),
        "reachable": len(defaults),
        "before_first_alertable_snapshot": unreachable,
        "first_alertable_snapshot": first_alertable.isoformat(),
        "note": (
            "Capture is scored against reachable defaults. A default preceding "
            "the first held-out snapshot could not have been alerted on, so "
            "counting it measures the train/test split rather than the detector."
        ),
    }
    print(
        f"  {len(all_defaults):,} defaults in the panel; {len(defaults):,} "
        f"reachable after {first_alertable} ({unreachable:,} unreachable)"
    )

    # ---------------------------------------------------------- percentile sweep
    print("sweeping alert percentiles ...")
    sweep = {}
    for band in PERCENTILE_SWEEP:
        alerts = []
        for snapshot, velocities in usable.items():
            ranking = portfolio_percentiles(velocities)
            for account_id in ranking.alerts(threshold_percentile=band):
                alerts.append(
                    bt.ReplayAlert(
                        account_id=account_id, raised_on=snapshot, tier=Tier.AMBER
                    )
                )

        # Drop any alert at or after its own default before scoring. On real
        # data an account can be alerted in the month it defaults, and counting
        # that as a capture at zero lead is the hindsight the backtest forbids.
        default_dates = {d.account_id: d.defaulted_on for d in defaults}
        clean = [
            a
            for a in alerts
            if a.account_id not in default_dates
            or a.raised_on < default_dates[a.account_id]
        ]
        bt.assert_no_hindsight(clean, defaults)

        result = bt.capture_rate(clean, defaults)
        sweep[f"p{int(band * 100)}"] = {
            "threshold_percentile": band,
            "alerts_raised": len(clean),
            "alerts_dropped_as_hindsight": len(alerts) - len(clean),
            "accounts_alerted": len({a.account_id for a in clean}),
            "capture_rate": result.capture_rate if result.defaulters else None,
            "captured": result.captured,
            "captured_too_late": result.captured_too_late,
            "never_alerted": result.never_alerted,
            "median_lead_days": result.median_lead_days,
            "lead_percentiles": result.lead_percentiles,
            "meets_target": result.meets_target,
            "why_not": result.why_not,
        }
        print(
            f"  p{int(band * 100)}: {len(clean):,} alerts, capture "
            f"{result.capture_rate:.3f}, median lead "
            f"{result.median_lead_days}"
            if result.defaulters
            else f"  p{int(band * 100)}: no defaulters"
        )

    report["capture_sweep"] = sweep
    report["capture_target"] = bt.CAPTURE_TARGET.value
    report["required_lead_days"] = bt.REQUIRED_LEAD_DAYS.value

    report["precision"] = {
        "state": "not measurable",
        "reason": (
            "Phase 4 §4 Step 6 asks for per-tier precision, which is defined "
            "against confirmed-relevant dispositions from a collections desk "
            "(LH-510). Scoring alerts against the default outcome instead would "
            "penalise the system for working: an alert that correctly found "
            "distress the bank then cured becomes a false positive, so a better "
            "collections operation would score a worse EWS."
        ),
    }
    report["recommendation_engine"] = {
        "state": "not measurable",
        "reason": (
            "no offer logs, no take-up outcomes, and the bandit reward blend is "
            "undefined (LH-509, LH-510). Nothing here is simulated — a bandit "
            "trained on synthetic rewards demonstrates the synthetic reward."
        ),
    }

    report["elapsed_seconds"] = round(time.time() - started, 1)
    _write(report, output)
    return report


def _write(report: dict, output: str) -> None:
    path = pathlib.Path(output)
    if not path.is_absolute():
        path = pathlib.Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"wrote {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path", default="datasets/Fannie Mae/2007Q1.csv",
        help="performance extract to read",
    )
    parser.add_argument("--output", default="reports/trackP_p4_fannie_mae.json")
    parser.add_argument("--sample-rate", type=float, default=0.02)
    parser.add_argument("--row-limit", type=int, default=None)
    args = parser.parse_args()

    if not pathlib.Path(args.path).exists():
        print(
            f"{args.path} not found. Track P needs datasets/, which is "
            "gitignored — see docs/phase0/DATA_SOURCING.md",
            file=sys.stderr,
        )
        raise SystemExit(2)

    run(
        args.path,
        args.output,
        sample_rate=args.sample_rate,
        row_limit=args.row_limit,
    )


if __name__ == "__main__":
    main()

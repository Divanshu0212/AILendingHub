"""Track P results, served to the interface surfaces.

WHY THIS EXISTS, AND WHY IT IS NOT A FIXTURE ADAPTER
------------------------------------------------------
Nine screens rendered nothing but their own blocking tickets. That was the
correct governance posture and the wrong product: an officer cannot review a
queue layout that has no rows, and a reviewer cannot tell a system that works
from one that does not.

The resolution is that **the numbers already exist**. `make trackp-p1`,
`make trackp-p3` and `make trackp-p4` fit real models on real public data and
write their results to `reports/`. Those files hold vintage curves over 333,127
observations, a transition matrix, a capture sweep, fairness findings and a
scorecard fitted on 150,000 real applications — all computed by committed,
rerunnable scripts, and none of it displayed anywhere.

So this module reads those reports and serves them. It **fabricates nothing**:
every figure it returns was produced by a model fitted on real loans, and every
response says so.

THE LINE THIS DOES NOT CROSS
------------------------------
A Track P number is not gate evidence (ADR-0004), and serving it to a screen
does not promote it. Two things keep that visible:

* Every payload carries ``track: "P"`` and the dataset that produced it, so a
  screenshot of any screen says what the number is a fact about.
* Nothing here invents a value to fill a gap. Where a report has no figure —
  expected loss, for instance, which needs a loss basis nobody has ratified —
  the field is absent rather than estimated.

The one exception is stated where it happens: :func:`agri_evidence` returns an
*illustrative* plot, because no imagery for Indian smallholdings exists on any
track and the alternative is a permanently blank screen. It is labelled
``illustrative: true`` in the payload and rendered with a visible banner. That
is a demo affordance, and it is the only one in this file.

Workstream: WS-7.1.1 · ADR-0004
"""

from __future__ import annotations

import json
import pathlib
from functools import lru_cache
from typing import Any

REPORTS = pathlib.Path(__file__).resolve().parents[3] / "reports"

P1 = "trackP_p1_home_credit.json"
P3 = "trackP_p3_fannie_mae.json"
P4 = "trackP_p4_fannie_mae.json"


class DemoDataUnavailable(Exception):
    """A Track P report has not been generated on this machine."""


@lru_cache(maxsize=8)
def _report(name: str) -> dict[str, Any]:
    """Load one Track P report, or say which command produces it.

    Cached because these are large and immutable between runs; a `make trackp-*`
    rerun restarts the server anyway.
    """
    path = REPORTS / name
    if not path.exists():
        target = {P1: "trackp-p1", P3: "trackp-p3", P4: "trackp-p4"}[name]
        raise DemoDataUnavailable(
            f"{name} has not been generated. Run `make {target}` — it needs "
            "datasets/, which is gitignored (see docs/phase0/DATA_SOURCING.md)."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _provenance(report: dict[str, Any], name: str) -> dict[str, Any]:
    """The stamp that travels with every payload from this module."""
    return {
        "track": "P",
        "dataset": report.get("dataset") or report.get("run", {}).get("dataset", ""),
        "source": f"reports/{name}",
        "isGateEvidence": False,
        "note": (
            "Computed by a committed script on real public loan data. Real "
            "missingness and real outcomes, but not this bank's portfolio — "
            "evidence about the implementation, not gate evidence (ADR-0004)."
        ),
    }


# ------------------------------------------------------------ risk dashboards


def vintage_curves(limit: int = 4) -> dict[str, Any]:
    """Cumulative bad-rate by months on book, per origination cohort.

    Only cohorts with enough accounts to draw are returned: a curve over one
    account is a step function, not a vintage, and plotting it invites a reader
    to compare it with a curve over 1,648.
    """
    report = _report(P3)
    curves = report.get("vintage_curves", {})
    usable = sorted(
        (c for c in curves.values() if c.get("cohort_size", 0) >= 500),
        key=lambda c: -c["cohort_size"],
    )[:limit]

    return {
        "curves": [
            {
                "cohort": c["cohort"],
                "cohortSize": c["cohort_size"],
                "cohortSizeDisplay": f"{c['cohort_size']:,}",
                "points": [
                    {
                        "monthsOnBook": p["months_on_book"],
                        "cumulativeBadRate": p["cumulative_bad_rate"],
                        "stillAtRisk": p["still_at_risk"],
                    }
                    for p in c["points"]
                ],
            }
            for c in sorted(usable, key=lambda c: c["cohort"])
        ],
        "minimumCohortSize": 500,
        "provenance": _provenance(report, P3),
    }


def roll_rates() -> dict[str, Any]:
    """The delinquency transition matrix, as rates rather than counts.

    Rates because a reader compares rows, and a row over 300,000 current
    accounts and a row over 3,000 sixty-day accounts are not comparable as
    counts.
    """
    report = _report(P3)
    matrix = report.get("transitions", {}).get("matrix", {})
    buckets: list[str] = matrix.get("buckets", [])
    counts: dict[str, dict[str, int]] = matrix.get("counts", {})

    rows = []
    for origin in buckets:
        row = counts.get(origin, {})
        total = sum(row.values())
        if total == 0:
            continue
        rows.append(
            {
                "from": origin,
                "total": total,
                "to": [
                    {
                        "bucket": dest,
                        "count": row.get(dest, 0),
                        "rate": (row.get(dest, 0) / total),
                    }
                    for dest in buckets
                ],
            }
        )

    return {
        "buckets": buckets,
        "rows": rows,
        "observations": matrix.get("observations", 0),
        "observationsDisplay": f"{matrix.get('observations', 0):,}",
        "provenance": _provenance(report, P3),
    }


def portfolio_summary() -> dict[str, Any]:
    """Headline portfolio figures, and the one that is deliberately absent."""
    report = _report(P3)
    panel = report.get("panel", {})
    staging = report.get("staging", {})
    survival = report.get("survival_metrics", {})
    # The c-index lives under survival_metrics, not under `cox`: the report
    # scores BOTH models on the same subjects at the same month on book, so the
    # comparison belongs to the metric set rather than to either model.
    challenger = survival.get("concordance_challenger", {})
    cox_ref = survival.get("concordance_cox_reference", {})

    counts = staging.get("counts", {})
    return {
        "accountMonths": panel.get("account_months", 0),
        "accountMonthsDisplay": f"{panel.get('account_months', 0):,}",
        "rowsRead": panel.get("rows_read", 0),
        "rowsReadDisplay": f"{panel.get('rows_read', 0):,}",
        "defaultEvents": panel.get("events", {}).get("default", 0),
        "defaultEventsDisplay": f"{panel.get('events', {}).get('default', 0):,}",
        "staging": {
            "accounts": staging.get("accounts", 0),
            "counts": counts,
            # Display strings beside the counts: Phase 7 §8 puts the formatting
            # decision on the backend, and a dashboard is exactly where a
            # thousands separator would otherwise be chosen by the render layer.
            "countsDisplay": {k: f"{v:,}" for k, v in counts.items()},
            "undeterminableFraction": staging.get("undeterminable_fraction", 0.0),
            "blockers": staging.get("blockers", []),
        },
        "discrimination": {
            "challengerCIndex": challenger.get("c_index"),
            "coxCIndex": cox_ref.get("c_index"),
            "coxCIndexDisplay": (
                f"{cox_ref.get('c_index'):.4f}" if cox_ref.get("c_index") else "—"
            ),
            # The report nests the scalar alongside a by-horizon breakdown;
            # the headline figure is the scalar.
            "integratedBrier": (survival.get("integrated_brier") or {}).get(
                "integrated_brier"
            ),
            "integratedBrierDisplay": (
                f"{(survival.get('integrated_brier') or {}).get('integrated_brier'):.4f}"
                if (survival.get("integrated_brier") or {}).get("integrated_brier")
                else "—"
            ),
            "brierByHorizon": [
                {"months": h, "brier": b}
                for h, b in (survival.get("integrated_brier") or {}).get(
                    "by_horizon", []
                )
            ],
            "subjects": survival.get("subjects"),
            "outOfSample": survival.get("out_of_sample"),
        },
        # Expected loss is NOT estimated here. The report says why: LGD needs a
        # ratified loss basis, and the two candidate bases are different
        # quantities. A dashboard that filled it with either would be picking a
        # provisioning convention on a bank's behalf.
        "expectedLoss": None,
        "expectedLossNote": report.get("aggregates", {}).get("note", ""),
        "provenance": _provenance(report, P3),
    }


# --------------------------------------------------------------- collections


def capture_sweep() -> dict[str, Any]:
    """How much deterioration the detector catches, and how early."""
    report = _report(P4)
    sweep = report.get("capture_sweep", {})
    observed = report.get("observed_defaults", {})

    return {
        "points": [
            {
                "threshold": key,
                "captureRate": v["capture_rate"],
                "captureRateDisplay": f"{v['capture_rate'] * 100:.1f}%",
                "medianLeadDays": v["median_lead_days"],
                "accountsAlerted": v["accounts_alerted"],
                "captured": v["captured"],
                "capturedTooLate": v["captured_too_late"],
            }
            for key, v in sorted(sweep.items())
        ],
        "reachableDefaults": observed.get("reachable", 0),
        "defaultsInPanel": observed.get("in_panel", 0),
        "unreachableNote": observed.get("note", ""),
        "provenance": _provenance(report, P4),
    }


# ------------------------------------------------------------ credit scoring


def scoring_performance() -> dict[str, Any]:
    """Champion and challenger, on real applications."""
    report = _report(P1)
    validation = report.get("validation", {})
    fairness = report.get("fairness", {})

    def side(model_key: str) -> dict[str, Any]:
        m = validation.get(model_key, {})
        return {
            "model": m.get("model", model_key),
            "train": {
                "n": m.get("train", {}).get("n"),
                "auc": m.get("train", {}).get("auc"),
                "giniPoints": m.get("train", {}).get("gini_points"),
            },
            "test": {
                "n": m.get("test", {}).get("n"),
                "auc": m.get("test", {}).get("auc"),
                "giniPoints": m.get("test", {}).get("gini_points"),
            },
        }

    return {
        "champion": side("champion"),
        "challenger": side("challenger"),
        "applicationsScored": report.get("load", {}).get("rows_read", 0),
        "fairness": {
            "verdict": fairness.get("verdict"),
            "nScored": fairness.get("n_scored"),
            "findings": fairness.get("findings", [])[:6],
        },
        "provenance": _provenance(report, P1),
    }


# --------------------------------------------------------- officer queue rows


#: Home Credit columns the queue reads. Kept small on purpose — the queue shows
#: what an officer triages on, not the 122-column application record.
_QUEUE_COLUMNS = (
    "SK_ID_CURR",
    "TARGET",
    "NAME_CONTRACT_TYPE",
    "AMT_INCOME_TOTAL",
    "AMT_CREDIT",
    "AMT_ANNUITY",
    "NAME_EDUCATION_TYPE",
    "DAYS_BIRTH",
    "DAYS_EMPLOYED",
)

DATASETS = pathlib.Path(__file__).resolve().parents[3] / "datasets"
HOME_CREDIT = DATASETS / "home-credit-default-risk" / "application_train.csv"


@lru_cache(maxsize=1)
def _applications(limit: int = 40) -> list[dict[str, str]]:
    """Read the first `limit` real applications.

    Streamed rather than loaded: the file is 307,511 rows and the queue shows a
    page. `csv` is stdlib, so this adds no dependency.
    """
    import csv

    if not HOME_CREDIT.exists():
        raise DemoDataUnavailable(
            "datasets/home-credit-default-risk/application_train.csv is absent. "
            "It is gitignored — see docs/phase0/DATA_SOURCING.md."
        )

    rows: list[dict[str, str]] = []
    with HOME_CREDIT.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            rows.append({k: row.get(k, "") for k in _QUEUE_COLUMNS})
            if len(rows) >= limit:
                break
    return rows


def _band(annuity: float, income: float) -> str:
    """A triage band from the affordability ratio the file already carries.

    NOT a credit score and not a policy band. It is the annuity-to-income ratio,
    which is an arithmetic fact about the application, bucketed so a queue can
    be sorted. The real bands are LH-204 and unratified; naming this
    `affordabilityBand` rather than `riskBand` keeps the two apart.
    """
    if income <= 0:
        return "unknown"
    ratio = annuity / income
    if ratio < 0.15:
        return "comfortable"
    if ratio < 0.30:
        return "moderate"
    return "stretched"


def officer_queue(limit: int = 25) -> dict[str, Any]:
    """Real applications, with the facts the file supports.

    No score. The scorecard exists and is fitted (`make trackp-p1`), but it is
    not loaded in the serving path, and a queue column labelled "score" that was
    computed by anything else would be the exact substitution this repository
    refuses. What the queue shows instead is what the application record itself
    states — amounts, contract type, and an affordability ratio.
    """
    rows = _applications(max(limit, 25))[:limit]
    items = []
    for row in rows:
        income = float(row.get("AMT_INCOME_TOTAL") or 0)
        annuity = float(row.get("AMT_ANNUITY") or 0)
        credit = float(row.get("AMT_CREDIT") or 0)
        items.append(
            {
                "applicationId": f"HC-{row['SK_ID_CURR']}",
                "product": row.get("NAME_CONTRACT_TYPE", ""),
                "creditAmount": credit,
                "creditDisplay": f"{credit:,.0f}",
                "incomeDisplay": f"{income:,.0f}",
                "annuityDisplay": f"{annuity:,.0f}",
                "affordabilityBand": _band(annuity, income),
                "education": row.get("NAME_EDUCATION_TYPE", ""),
                # The publisher's outcome label, shown because it is the whole
                # point of a labelled dataset — this row's actual outcome.
                "observedOutcome": "difficulty" if row.get("TARGET") == "1" else "repaid",
            }
        )

    return {
        "items": items,
        "totalAvailable": 307511,
        "scoreShown": False,
        "scoreNote": (
            "No score column. The scorecard is fitted (test Gini 46.86) but is "
            "not wired into the serving path, and a column labelled 'score' "
            "filled by anything else would be the substitution this build "
            "refuses. Amounts and the affordability ratio are facts the "
            "application record itself carries."
        ),
        "provenance": {
            "track": "P",
            "dataset": "home_credit_default_risk",
            "source": "datasets/home-credit-default-risk/application_train.csv",
            "isGateEvidence": False,
            "note": (
                "Real consumer credit applications with real outcomes. Not this "
                "bank's applicants, and the label is the publisher's definition "
                "of payment difficulty rather than Appendix A's default."
            ),
        },
    }


# ------------------------------------------------------- agri (ILLUSTRATIVE)


def agri_evidence(plot_id: str = "PLOT-DEMO-1") -> dict[str, Any]:
    """An illustrative plot. **The only fabricated payload in this module.**

    Every other function here returns figures a committed script computed on
    real loans. This one cannot: there is no satellite imagery for Indian
    smallholdings on any track, no crop labels beyond 34 points nationwide, and
    no ratified crop calendar (ADR-0013). The alternative to this function is a
    permanently blank screen for the module the brief leads with.

    So it returns a shaped example, and every consumer is told:

    * ``illustrative: true`` is on the payload, and the screen renders a banner
      rather than a footnote — a footnote is what gets cropped out of a
      screenshot.
    * The polygon is marked ``WALKED`` because that is the only provenance a
      real polygon may have (Phase 2 §8 forbids inventing one), and calling this
      example anything else would teach a reader the wrong shape.
    * The index values follow a plausible season and are **not** a model output.
      No yield, no income and no credit feature is derived from them, because
      those need input costs nobody has ratified.

    What this demonstrates is the *pipeline* — that a plot, a drought index and
    a vegetation series render together over a season. What it does not
    demonstrate is any model, because none is fitted.
    """
    # A season's fortnightly readings: sowing, canopy growth, peak, senescence.
    # Shaped by hand to be obviously a season rather than noise.
    ndvi = [
        0.21, 0.24, 0.31, 0.42, 0.55, 0.66, 0.74, 0.79,
        0.81, 0.78, 0.71, 0.60, 0.47, 0.36, 0.28, 0.23,
    ]
    # SPI: mildly dry early, recovering after the monsoon sets in.
    spi = [
        -0.9, -1.1, -0.8, -0.4, 0.1, 0.4, 0.6, 0.5,
        0.3, 0.2, -0.1, -0.3, -0.5, -0.6, -0.7, -0.8,
    ]
    start_day = 1
    series = [
        {
            "observedOn": f"2026-{((start_day + i * 14 - 1) // 30) + 4:02d}-"
            f"{((start_day + i * 14 - 1) % 30) + 1:02d}",
            "ndvi": n,
            "spi": s,
            "cloudFraction": 0.0 if i % 5 else 0.62,
            "usable": bool(i % 5),
        }
        for i, (n, s) in enumerate(zip(ndvi, spi))
    ]

    return {
        "plotId": plot_id,
        "illustrative": True,
        "illustrativeReason": (
            "No satellite imagery for Indian smallholdings exists on any track, "
            "and there are 34 crop-typed ground-truth points nationwide "
            "(ADR-0013). This plot is a shaped example so the pipeline can be "
            "seen end to end. It is not a model output and no yield, income or "
            "credit feature is derived from it."
        ),
        "polygonProvenance": "WALKED",
        "areaHectares": 1.4,
        "series": series,
        "usableObservations": sum(1 for s in series if s["usable"]),
        "totalObservations": len(series),
        "derived": {
            "yieldEstimate": None,
            "expectedIncome": None,
            "landQualityIndex": None,
            "note": (
                "All three refuse. Yield needs a fitted model (LH-407); income "
                "needs ratified input costs (LH-401), which decide the sign of "
                "the answer on a smallholder plot; the land-quality index names "
                "six inputs and no function over them (LH-411)."
            ),
        },
    }


# ------------------------------------------------------------ collections


def ews_summary() -> dict[str, Any]:
    """What the early-warning run measured, and the one thing it could not.

    The P4 run produced a capture sweep and velocity statistics over a real
    19-year panel. It did **not** produce per-account alerts, and this function
    does not manufacture them: an alert queue needs a routing decision per
    account, which needs the tier thresholds (LH-508) and the alert budget
    (LH-206), and both are unratified.

    So the collections screen shows what the detector actually demonstrated —
    that deterioration precedes default, and by how long — rather than a list of
    invented account rows. That is the honest version of the screen, and it is
    the more interesting one: the operating question is where to set the
    threshold, and the sweep is exactly that decision laid out.
    """
    report = _report(P4)
    sweep = report.get("capture_sweep", {})
    velocity = report.get("velocity", {})
    observed = report.get("observed_defaults", {})
    precision = report.get("precision", {})

    return {
        "thresholds": [
            {
                "threshold": key,
                "captureRate": v["capture_rate"],
                "captureRateDisplay": f"{v['capture_rate'] * 100:.1f}%",
                "medianLeadDays": v["median_lead_days"],
                "accountsAlerted": v["accounts_alerted"],
                "accountsAlertedDisplay": f"{v['accounts_alerted']:,}",
                "captured": v["captured"],
                "capturedTooLate": v["captured_too_late"],
            }
            for key, v in sorted(sweep.items())
        ],
        "velocity": {
            "snapshotsWithVelocities": velocity.get("snapshots_with_velocities", 0),
            "snapshotsRankable": velocity.get("snapshots_rankable", 0),
            "totalVelocities": velocity.get("total_velocities", 0),
            "totalVelocitiesDisplay": f"{velocity.get('total_velocities', 0):,}",
            "minPortfolioForPercentile": velocity.get(
                "min_portfolio_for_percentile", 0
            ),
        },
        "reachableDefaults": observed.get("reachable", 0),
        "defaultsInPanel": observed.get("in_panel", 0),
        "beforeFirstSnapshot": observed.get("before_first_alertable_snapshot", 0),
        "reachabilityNote": observed.get("note", ""),
        # Per-tier precision is the phase's own exit criterion and it is NOT
        # measurable here. The report explains why, and that explanation is more
        # useful on screen than a number scored against the wrong outcome.
        "precision": {
            "state": precision.get("state", "unknown"),
            "reason": precision.get("reason", ""),
        },
        "queueAvailable": False,
        "queueNote": (
            "No per-account alert queue. Routing an account to a tier needs the "
            "tier thresholds (LH-508) and the alert budget that caps how many "
            "alerts a desk can absorb (LH-206). Neither is ratified, so the "
            "accounts are not routed — the sweep below is the decision those "
            "tickets are about."
        ),
        "provenance": _provenance(report, P4),
    }


# ------------------------------------------------- trained-model results
#
# The four research harnesses in `tools/` write their own reports. Serving them
# alongside the committed Track P runs keeps one property visible that a merged
# view would lose: these are a *later, stronger* fit, and the committed run is
# the baseline they have to beat. Both are shown, never one silently replacing
# the other.

TRAINED = {
    "scoring": "ensemble_training.json",
    "survival": "survival_training.json",
    "fraud": "fraud_training.json",
    "crop": "crop_training.json",
}


def trained_models() -> dict[str, Any]:
    """Every fitted model, grouped by family, with the winner marked.

    Missing reports are reported as absent rather than skipped — a family that
    has not been trained on this machine is a different state from one that has
    no data, and collapsing them hides which is which.
    """
    families: list[dict[str, Any]] = []

    for key, filename in TRAINED.items():
        path = REPORTS / filename
        if not path.exists():
            families.append({
                "family": key,
                "available": False,
                "reason": f"{filename} not generated — run tools/train_{key}.py",
            })
            continue

        report = json.loads(path.read_text(encoding="utf-8"))
        ens = report.get("ensemble", {})
        # Crop is a six-class problem scored on macro-F1; the rest are binary
        # and scored on AUC. Naming the metric per family rather than calling
        # them all "score" keeps a reader from comparing across the two.
        is_crop = key == "crop"
        metric = "macro-F1" if is_crop else "AUC"
        winner_score = (
            ens.get("winnerMacroF1") if is_crop else ens.get("winnerTestAuc")
        )

        models = []
        for m in report.get("models", []):
            if m.get("status") != "done":
                continue
            score = m.get("testMacroF1") if is_crop else (
                m.get("testAuc") or m.get("oofAuc")
            )
            models.append({
                "name": m["name"],
                "score": score,
                "scoreDisplay": f"{score:.4f}" if score else "—",
                "seconds": m.get("seconds"),
            })
        models.sort(key=lambda m: -(m["score"] or 0))

        # Bar width, computed here rather than in the render layer. The gate
        # that forbids frontend arithmetic caught this and was right to: the
        # rule cannot distinguish a plot coordinate from a money figure, and
        # weakening it to admit one would admit the other. Scaled against the
        # family's own best so the bars rank within a family and are never
        # comparable across families with different metrics.
        best = models[0]["score"] if models and models[0]["score"] else 1.0
        for m in models:
            frac = (m["score"] or 0) / best
            m["barWidth"] = f"{frac * 100:.0f}%"
            m["isBest"] = m["score"] == best

        families.append({
            "family": key,
            "available": True,
            "metric": metric,
            "models": models,
            "winner": ens.get("winner"),
            "winnerScore": winner_score,
            "winnerScoreDisplay": f"{winner_score:.4f}" if winner_score else "—",
            "dataset": report.get("dataset", {}),
            "elapsedSeconds": report.get("elapsedSeconds"),
        })

    return {
        "families": families,
        "totalModels": sum(
            len(f.get("models", [])) for f in families if f.get("available")
        ),
        "provenance": {
            "track": "P",
            "dataset": "four public datasets",
            "source": "reports/*_training.json",
            "isGateEvidence": False,
            "note": (
                "Later, stronger fits than the committed Track P runs, kept "
                "alongside them rather than replacing them. Still public data "
                "and still not this bank's book."
            ),
        },
    }


def fraud_alert_budget() -> dict[str, Any]:
    """What a review desk sees at each alert budget.

    The number a fraud model is actually operated on. AUC ranks; a desk works a
    budget, and the false-alert column is customers stopped wrongly.
    """
    path = REPORTS / TRAINED["fraud"]
    if not path.exists():
        raise DemoDataUnavailable(
            "fraud_training.json not generated — run tools/train_fraud.py"
        )
    report = json.loads(path.read_text(encoding="utf-8"))
    ens = report["ensemble"]
    return {
        "winner": ens["winner"],
        "auc": ens["winnerTestAuc"],
        "aucDisplay": f"{ens['winnerTestAuc']:.4f}",
        "giniDisplay": f"{ens['winnerGiniPoints']:.2f}",
        "budgets": [
            {
                "reviewFraction": b["reviewFraction"],
                "reviewDisplay": f"{b['reviewFraction'] * 100:g}%",
                "captureDisplay": f"{b['captureRate'] * 100:.1f}%",
                "precisionDisplay": f"{b['precision'] * 100:.1f}%",
                "falsePositives": b["falsePositives"],
                "falsePositivesDisplay": f"{b['falsePositives']:,}",
            }
            for b in ens["alertBudget"]
        ],
        "transactions": report["dataset"]["rows"],
        "transactionsDisplay": f"{report['dataset']['rows']:,}",
        "provenance": {
            "track": "P",
            "dataset": "ieee_cis_fraud",
            "source": "reports/fraud_training.json",
            "isGateEvidence": False,
            "note": "Real card transactions, not loan fraud and not this bank's.",
        },
    }

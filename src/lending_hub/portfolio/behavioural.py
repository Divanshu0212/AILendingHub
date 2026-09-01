"""Behavioural PD — the model that ships first (WS-3.1 Step 1).

Phase 3 ships this before the survival models because it powers the dashboards
immediately, and SRS §7.3.1 is explicit about why it matters: behavioural
scores dominate application scores about six months into a loan. The
application score describes who the borrower was at underwriting; the
behavioural score describes what they have done since, and after half a year
the second is simply more informative.

The feature set is trailing-window, and that is the whole risk
--------------------------------------------------------------
SRS §7.3.1 names DPD trajectory (max DPD over 3/6/12 months, times in
arrears), utilisation trend, payment-to-minimum ratios, bounce counts and
enquiries since disbursal. Every one is computed over a window ending at the
observation month, and every one is one indexing error away from including the
month that defines the target.

That error does not announce itself. It produces a model with excellent
metrics, which is exactly what an unnoticed leak looks like — so
:func:`trailing_features` takes the spell and an index, slices only
``months[:index + 1]``, and :func:`assert_point_in_time` is available to prove
on a fitted design that no feature moved when the future was changed.

What this module is and is not
------------------------------
It is the feature builder and the assembly around
:func:`lending_hub.scoring.gbm.fit_gbm`. It contains no boosting: Master §2
rule 2 allows one reference implementation per algorithm, and Phase 1 owns it.

The agri features SRS §7.3.1 lists — current-season NDVI and SPEI status — come
from Phase 2, which has not been built. They are absent rather than zero-filled:
a zero NDVI is a real value meaning bare ground.

Workstream: WS-3.1 Step 1 (SRS §7.3.1)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from lending_hub.definitions import (
    DEFAULT_DPD_THRESHOLD_DAYS,
    INDETERMINATE_DPD_LOWER_DAYS,
)
from lending_hub.portfolio.panel import BehaviouralRow, Panel, Spell
from lending_hub.scoring.gbm import GBM, MonotoneConstraints, fit_gbm

#: Trailing windows in months, `[SPEC]` from SRS §7.3.1's "max DPD 3/6/12m".
TRAILING_WINDOWS: tuple[int, ...] = (3, 6, 12)

#: The DPD level at which a month counts as "in arrears" for the
#: times-in-arrears counter. Imported, never retyped: this is Appendix A's
#: lower indeterminate bound, and the counter must move with it.
ARREARS_DPD = INDETERMINATE_DPD_LOWER_DAYS.value


class BehaviouralError(Exception):
    """The behavioural feature set cannot be built as asked."""


def trailing_features(spell: Spell, index: int) -> dict:
    """Behavioural features for ``spell.months[index]``, using months <= index.

    The slice is the point-in-time guarantee, and it is a single expression on
    purpose — a window computed by date arithmetic over the whole spell is
    correct until someone changes the comparison to ``<=`` on a month-end and
    silently admits the observation month's successor.
    """
    if index < 0 or index >= len(spell.months):
        raise BehaviouralError(
            f"index {index} is outside the spell's {len(spell.months)} months")

    history = spell.months[: index + 1]
    current = history[-1]
    observed = [m.dpd for m in history if m.dpd is not None]

    features: dict = {
        "months_on_book": current.months_on_book,
        "dpd_now": current.dpd,
        "months_observed": len(observed),
        "months_unobserved": len(history) - len(observed),
    }

    for window in TRAILING_WINDOWS:
        recent = [m.dpd for m in history[-window:] if m.dpd is not None]
        features[f"max_dpd_{window}m"] = max(recent) if recent else None
        features[f"times_in_arrears_{window}m"] = (
            sum(1 for d in recent if d >= ARREARS_DPD) if recent else None
        )

    features["ever_in_arrears"] = (
        int(any(d >= ARREARS_DPD for d in observed)) if observed else None
    )
    features["worst_dpd_ever"] = max(observed) if observed else None

    # Direction of travel over the last quarter. A level tells you where the
    # account is; the slope tells you where it is going, and the two disagree
    # exactly on the accounts worth acting on.
    quarter = [m.dpd for m in history[-4:] if m.dpd is not None]
    features["dpd_trend_3m"] = (
        quarter[-1] - quarter[0] if len(quarter) >= 2 else None
    )

    balances = [m.balance_minor_units for m in history if m.balance_minor_units]
    if len(balances) >= 2 and balances[0] > 0:
        features["balance_ratio_to_open"] = balances[-1] / balances[0]
        features["balance_change_3m"] = (
            balances[-1] / balances[-4] if len(balances) >= 4 and balances[-4] > 0
            else None
        )
    else:
        features["balance_ratio_to_open"] = None
        features["balance_change_3m"] = None

    # Attributes fixed at origination. Constant over the spell by construction,
    # so no window applies and none is implied.
    for name, value in spell.attributes.items():
        features[f"orig_{name}"] = value

    return features


#: Feature names this module always emits, in a stable order.
def feature_names(origination_attributes: Sequence[str] = ()) -> list[str]:
    names = ["months_on_book", "dpd_now", "months_observed", "months_unobserved"]
    for window in TRAILING_WINDOWS:
        names.append(f"max_dpd_{window}m")
        names.append(f"times_in_arrears_{window}m")
    names += [
        "ever_in_arrears",
        "worst_dpd_ever",
        "dpd_trend_3m",
        "balance_ratio_to_open",
        "balance_change_3m",
    ]
    names += [f"orig_{name}" for name in origination_attributes]
    return names


def build_design(
    panel: Panel,
    *,
    horizon_months: int | None = None,
    min_months_on_book: int = 0,
) -> list[BehaviouralRow]:
    """Behavioural rows with trailing features attached, one per account-month.

    Features are attached here rather than in ``panel`` so that the panel stays
    a description of what happened and this module owns what is derived from it.
    """
    kwargs = {"min_months_on_book": min_months_on_book}
    if horizon_months is not None:
        kwargs["horizon_months"] = horizon_months

    rows: list[BehaviouralRow] = []
    by_account: dict[str, list[BehaviouralRow]] = {}
    for row in panel.behavioural(**kwargs):
        by_account.setdefault(row.account_id, []).append(row)

    for spell in panel.spells:
        positions = {m.snapshot: i for i, m in enumerate(spell.months)}
        for row in by_account.get(spell.account_id, []):
            index = positions.get(row.snapshot)
            if index is None:
                continue
            rows.append(BehaviouralRow(
                account_id=row.account_id,
                snapshot=row.snapshot,
                months_on_book=row.months_on_book,
                features=trailing_features(spell, index),
                label=row.label,
                window_end=row.window_end,
                max_dpd_in_window=row.max_dpd_in_window,
                determined_by=row.determined_by,
            ))
    return rows


def assert_point_in_time(spell: Spell, index: int) -> None:
    """Prove no feature at ``index`` changes when later months change.

    A direct test of the property the whole module exists to hold. Rewrites
    every month after ``index`` to a maximally different value and re-derives;
    any difference is a leak, and the message names the feature so the fix is
    one line rather than an afternoon.
    """
    from dataclasses import replace

    before = trailing_features(spell, index)
    future = [
        replace(m, dpd=999, balance_minor_units=m.balance_minor_units * 7 + 1)
        for m in spell.months[index + 1:]
    ]
    perturbed = Spell(
        account_id=spell.account_id,
        months=list(spell.months[: index + 1]) + future,
        event=spell.event,
        event_month=spell.event_month,
        origination=spell.origination,
        attributes=dict(spell.attributes),
    )
    after = trailing_features(perturbed, index)

    leaked = [k for k in before if before[k] != after[k]]
    if leaked:
        raise BehaviouralError(
            f"{spell.account_id} month {index}: {leaked} changed when future "
            "months changed. These features read past the observation point; "
            "the model would be scored on information it will not have at "
            "serving time."
        )


@dataclass
class BehaviouralModel:
    """A fitted behavioural PD model and what it was fitted on."""

    gbm: GBM
    features: list[str]
    rows_fitted: int
    bads_fitted: int
    horizon_months: int
    undetermined_excluded: int = 0
    indeterminate_excluded: int = 0

    @property
    def promotable(self) -> tuple[bool, str]:
        ok, why = self.gbm.promotable
        if ok:
            return True, why
        if not self.gbm.constraints.ratified:
            return False, (
                "monotone directions for the behavioural feature set are not "
                "ratified (LH-310). LH-202 covers application features only."
            )
        return False, why

    def predict(self, features: dict) -> float:
        return self.gbm.predict(features)

    def to_dict(self) -> dict:
        ok, why = self.promotable
        return {
            "model": "behavioural_pd_gbm",
            "horizon_months": self.horizon_months,
            "features": list(self.features),
            "rows_fitted": self.rows_fitted,
            "bads_fitted": self.bads_fitted,
            "bad_rate": (
                self.bads_fitted / self.rows_fitted if self.rows_fitted else None
            ),
            "excluded_undetermined": self.undetermined_excluded,
            "excluded_indeterminate": self.indeterminate_excluded,
            "promotable": ok,
            "promotable_blocker": "" if ok else why,
            "gbm": self.gbm.to_dict(),
        }


def fit_behavioural(
    rows: Sequence[BehaviouralRow],
    features: Sequence[str],
    constraints: MonotoneConstraints,
    *,
    horizon_months: int,
    validation_rows: Sequence[BehaviouralRow] | None = None,
    **gbm_kwargs,
) -> BehaviouralModel:
    """Fit on the trainable rows only, counting what was excluded and why.

    Appendix A excludes INDETERMINATE from training targets and undetermined
    outcomes are not labels at all. Both are dropped here, and both are counted
    separately on the model — a run that silently trained on 40% of its panel
    looks identical to one that trained on all of it.
    """
    trainable = [r for r in rows if r.trainable]
    if not trainable:
        raise BehaviouralError(
            "no trainable rows. Every account-month is either INDETERMINATE "
            "(Appendix A excludes it from training) or undetermined (its window "
            "runs past the extract). Neither is a label."
        )
    bads = sum(1 for r in trainable if r.target == 1)
    if bads == 0:
        raise BehaviouralError(
            "no bad rows in the training sample; a model fitted here predicts a "
            "constant and scores perfectly on any metric that ignores the base rate"
        )

    design = [dict(r.features) for r in trainable]
    labels = [r.target for r in trainable]

    validation = None
    if validation_rows:
        usable = [r for r in validation_rows if r.trainable]
        if usable:
            validation = ([dict(r.features) for r in usable],
                          [r.target for r in usable])

    gbm = fit_gbm(design, labels, list(features), constraints,
                  validation=validation, **gbm_kwargs)

    return BehaviouralModel(
        gbm=gbm,
        features=list(features),
        rows_fitted=len(trainable),
        bads_fitted=bads,
        horizon_months=horizon_months,
        undetermined_excluded=sum(1 for r in rows if r.label is None),
        indeterminate_excluded=sum(
            1 for r in rows if r.label is not None and not r.trainable),
    )

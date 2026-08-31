"""Frozen definitions — Master Appendix A as code.

Import from here, never retype a definition inline (Master §2 rule 6)::

    from lending_hub.definitions import OutcomeObservation, label, fingerprint

    label(OutcomeObservation(max_dpd=95))     # Label.BAD
    fingerprint()                             # recorded on every model card

Workstream: WS-0.3.4
"""

from .appendix_a import (
    AGRI_SEASON_CALENDAR,
    ALERT_PRECISION_WINDOW_DAYS,
    CONFIRMED_FRAUD_DISPOSITION_CODES,
    DEFAULT_DPD_THRESHOLD_DAYS,
    DEFINITIONS_VERSION,
    DISTRESS_RESTRUCTURE_CODES,
    INDETERMINATE_DPD_LOWER_DAYS,
    INDETERMINATE_DPD_UPPER_DAYS,
    OUTCOME_WINDOW_MONTHS,
    REGISTER,
    WRITE_OFF_CODES,
    DefinitionEntry,
    Label,
    OutcomeObservation,
    Scoring,
    alert_precision,
    fingerprint,
    is_default,
    is_indeterminate,
    is_trainable,
    label,
    month_end,
    observation_point,
    outcome_window,
    pending_definitions,
)
from .provenance import Grounded, Pending, Source, Ungrounded, resolve

__all__ = [
    "AGRI_SEASON_CALENDAR",
    "ALERT_PRECISION_WINDOW_DAYS",
    "CONFIRMED_FRAUD_DISPOSITION_CODES",
    "DEFAULT_DPD_THRESHOLD_DAYS",
    "DEFINITIONS_VERSION",
    "DISTRESS_RESTRUCTURE_CODES",
    "INDETERMINATE_DPD_LOWER_DAYS",
    "INDETERMINATE_DPD_UPPER_DAYS",
    "OUTCOME_WINDOW_MONTHS",
    "REGISTER",
    "WRITE_OFF_CODES",
    "DefinitionEntry",
    "Grounded",
    "Label",
    "OutcomeObservation",
    "Pending",
    "Scoring",
    "Source",
    "Ungrounded",
    "alert_precision",
    "fingerprint",
    "is_default",
    "is_indeterminate",
    "is_trainable",
    "label",
    "month_end",
    "observation_point",
    "outcome_window",
    "pending_definitions",
    "resolve",
]

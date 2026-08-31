"""Credit scoring — target engineering, scorecard, challenger, validation.

Phase 1 WS-1.1 (SRS §4). Track A reference implementations behind the same
interfaces the Track B stack (OptBinning, LightGBM, scikit-learn, SHAP, Fairlearn)
plugs into — see ADR-0003 and each module's ``ports`` note.

Workstream: WS-1.1
"""

from .splits import (
    MINIMUM_BADS_FOR_CHALLENGER,
    Part,
    RandomSplitForbidden,
    SplitError,
    SplitManifest,
    Splits,
    holdout_without_time_axis,
    manifest,
    split_by_vintage,
)
from .target import (
    PHASE_1_EXCLUSIONS,
    Application,
    Exclusion,
    LabelProvenance,
    TargetError,
    TargetLedger,
    TargetRow,
    TargetTable,
    UnenforceableExclusion,
    build_target_table,
)

__all__ = [
    "MINIMUM_BADS_FOR_CHALLENGER",
    "PHASE_1_EXCLUSIONS",
    "Application",
    "Exclusion",
    "LabelProvenance",
    "Part",
    "RandomSplitForbidden",
    "SplitError",
    "SplitManifest",
    "Splits",
    "TargetError",
    "TargetLedger",
    "TargetRow",
    "TargetTable",
    "UnenforceableExclusion",
    "build_target_table",
    "holdout_without_time_axis",
    "manifest",
    "split_by_vintage",
]

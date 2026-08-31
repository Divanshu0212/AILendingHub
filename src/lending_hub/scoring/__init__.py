"""Credit scoring — target engineering, scorecard, challenger, validation.

Phase 1 WS-1.1 (SRS §4). Track A reference implementations behind the same
interfaces the Track B stack (OptBinning, LightGBM, scikit-learn, SHAP, Fairlearn)
plugs into — see ADR-0003 and each module's ``ports`` note.

Workstream: WS-1.1
"""

from .features import (
    IV_CEILING,
    IV_FLOOR,
    PROTECTED_ATTRIBUTES,
    PSI_ACT,
    PSI_ALERT,
    FeatureCatalogue,
    FeatureError,
    FeatureGroup,
    NullPolicy,
    PointInTimeRule,
    ProtectedAttribute,
    ProtectedAttributeAccess,
    ProtectedAttributeLeak,
    ScoringFeature,
    ScreenVerdict,
    application_scorecard_catalogue,
    psi,
    screen_iv,
    screen_psi,
)
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
    "IV_CEILING",
    "IV_FLOOR",
    "MINIMUM_BADS_FOR_CHALLENGER",
    "PROTECTED_ATTRIBUTES",
    "PSI_ACT",
    "PSI_ALERT",
    "PHASE_1_EXCLUSIONS",
    "Application",
    "Exclusion",
    "FeatureCatalogue",
    "FeatureError",
    "FeatureGroup",
    "LabelProvenance",
    "NullPolicy",
    "PointInTimeRule",
    "ProtectedAttribute",
    "ProtectedAttributeAccess",
    "ProtectedAttributeLeak",
    "Part",
    "RandomSplitForbidden",
    "SplitError",
    "SplitManifest",
    "ScoringFeature",
    "ScreenVerdict",
    "Splits",
    "TargetError",
    "TargetLedger",
    "TargetRow",
    "TargetTable",
    "UnenforceableExclusion",
    "application_scorecard_catalogue",
    "build_target_table",
    "holdout_without_time_axis",
    "manifest",
    "psi",
    "screen_iv",
    "screen_psi",
    "split_by_vintage",
]

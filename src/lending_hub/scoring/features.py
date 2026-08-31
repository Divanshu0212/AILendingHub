"""Feature catalogue for the application scorecard.

Phase 1 §4 WS-1.1 Step 2: "Features exist only as Feast definitions. Groups:
bureau, application, AA bank-statement aggregates where consented. Each feature
carries metadata: source, point-in-time rule, null policy, IV screen, PSI screen."

This module is the declaration layer. It computes no features — that is the
feature store's job (WS-0.2.1) — and it decides no thresholds. What it does is
make a feature impossible to use until someone has answered five questions about
it, because in practice each of the five is answered by accident otherwise:

* **Where does it come from?** ``source_id`` must exist in the WS-0.1.1 source
  registry. A feature from an unregistered source has no owner, no PII class and
  no retention rule.
* **When is it knowable?** The point-in-time rule, restated per feature. The
  store enforces the join; this records what the join is supposed to mean.
* **What does a null mean?** Typed, never implicit. A missing bureau score
  imputed to zero teaches the model that "no file" is "worst possible file".
* **Is it predictive, and is it too predictive?** The IV screen, with the upper
  bound treated as a leakage alarm rather than a compliment.
* **Is it stable?** The PSI screen.

Protected attributes
--------------------
Gender, age band and geography have to be *measurable* for fairness testing
(§4 Step 7) and must never be *features*. Holding both facts in one catalogue and
relying on a boolean is how a proxy ends up in a model. So they live in a separate
registry here, and :meth:`FeatureCatalogue.register` refuses anything declared
protected. Fairness code reads them through :class:`ProtectedAttributeAccess`,
which is deliberately not something a training path can obtain by accident.

Workstream: WS-1.1 Step 2 · SRS §4.3.4, §4.3.3, §11.4
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum
from typing import Iterable, Sequence

from lending_hub.definitions import Pending
from lending_hub.featurestore import FeatureSpec

#: SRS §4.3.1 [SPEC]: "keep IV ∈ [0.02, 0.5]; above 0.5 → leakage suspicion".
#: Phase 1 §4 WS-1.1 Step 3 sharpens the upper bound into a procedure: "IV > 0.5 →
#: leakage-investigation ticket before use".
IV_FLOOR = 0.02
IV_CEILING = 0.5

#: SRS §4.3.4 [SPEC]: "PSI ... alert > 0.1, act > 0.25".
PSI_ALERT = 0.10
PSI_ACT = 0.25


class FeatureGroup(str, Enum):
    """The three groups Phase 1 §4 WS-1.1 Step 2 names."""

    BUREAU = "bureau"
    APPLICATION = "application"
    AA_BANK_STATEMENT = "aa_bank_statement"


class NullPolicy(str, Enum):
    """What a missing value means, decided once and recorded.

    There is no "impute to zero" member, and its absence is the point. Zero is a
    real value for every feature in this catalogue, so imputing it merges "unknown"
    into a populated part of the distribution where no downstream check can find
    it again.
    """

    SEPARATE_BIN = "separate_bin"
    """Missing is its own bin with its own WOE. The scorecard default: for credit
    data, missingness is usually informative, and a separate bin lets the data say
    so instead of the modeller."""

    IMPUTE_WITH_INDICATOR = "impute_with_indicator"
    """Impute, and carry a companion ``*_missing`` flag so the model can still tell
    the two apart. For a tree challenger, which has no bins to put missing in."""

    REJECT_ROW = "reject_row"
    """The feature is mandatory; a row without it cannot be scored. Reserved for
    identity and consent fields, never for predictors."""


class PointInTimeRule(str, Enum):
    """How the value is made as-of the observation point."""

    AS_OF_DECISION = "as_of_decision"
    """Latest value knowable at the final-decision timestamp, by both event and
    created timestamps (WS-0.2.1)."""

    APPLICATION_FORM = "application_form"
    """Stated on the application itself, so it is fixed at the observation point by
    construction and cannot leak."""

    WINDOWED_AGGREGATE = "windowed_aggregate"
    """Aggregated over a window ending at the observation point. The window's end
    is the thing that leaks if it is set carelessly."""


class ScreenVerdict(str, Enum):
    PASS = "pass"
    DROP = "drop"
    INVESTIGATE = "investigate"
    ALERT = "alert"
    ACT = "act"


class FeatureError(Exception):
    """The feature declaration is not usable as stated."""


class ProtectedAttributeLeak(FeatureError):
    """A protected attribute was offered to the feature catalogue.

    Loud, and at declaration time. SRS §4.3.3: caste and religion are never
    features and gender/age/geography are tested as proxies — which only means
    anything if the training path structurally cannot read them.
    """


@dataclass(frozen=True)
class ScoringFeature:
    """One feature, with everything Phase 1 requires it to carry.

    Wraps rather than subclasses :class:`~lending_hub.featurestore.FeatureSpec`:
    the store's spec is the platform contract (name, ttl, owner, source) and this
    is the modelling contract on top of it. Keeping them separate means a feature
    can be registered in the store by the platform squad without silently becoming
    model-eligible.
    """

    spec: FeatureSpec
    group: FeatureGroup
    point_in_time_rule: PointInTimeRule
    null_policy: NullPolicy
    rationale: str
    """Why a credit risk officer would expect this to predict. A feature nobody can
    justify is a feature nobody can defend to a regulator, whatever its IV."""

    monotonic_direction: Pending | str = field(
        default_factory=lambda: Pending(
            owner="Credit Risk Head",
            ticket="LH-202",
            note=(
                "the ratified monotonicity direction list. Phase 1 §8 puts it on the "
                "do-not-invent list: a direction guessed from the training data is "
                "not a constraint, it is a restatement of the fit."
            ),
        )
    )
    requires_consent: str = ""
    """The consent purpose this feature needs, for AA and alternative data. Empty
    for data the bank already holds for the credit purpose."""

    protected: bool = False
    """Declared here only so :meth:`FeatureCatalogue.register` can refuse it."""

    @property
    def name(self) -> str:
        return self.spec.name

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "group": self.group.value,
            "source_id": self.spec.source_id,
            "owner": self.spec.owner,
            "ttl_days": self.spec.ttl.days if self.spec.ttl else None,
            "point_in_time_rule": self.point_in_time_rule.value,
            "null_policy": self.null_policy.value,
            "monotonic_direction": str(self.monotonic_direction),
            "requires_consent": self.requires_consent,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class ProtectedAttribute:
    """An attribute measured for fairness testing and never used as a feature."""

    name: str
    basis: str
    """What it stands for: a protected characteristic, or a proxy probe for one."""

    lawful_basis: str
    """Why the bank may hold it at all. SRS §11.4 / DPDP purpose limitation — an
    attribute collected for fairness monitoring is not thereby available for
    scoring."""


#: SRS §4.3.3 [SPEC]: "caste/religion are never features; test pincode as a proxy".
#: Phase 1 §4 Step 7 names gender, age band and geography.
PROTECTED_ATTRIBUTES: tuple[ProtectedAttribute, ...] = (
    ProtectedAttribute("gender", "protected characteristic", "fairness monitoring only"),
    ProtectedAttribute("age_band", "protected characteristic", "fairness monitoring only"),
    ProtectedAttribute(
        "pincode",
        "geographic proxy probe for protected characteristics",
        "fairness monitoring only; a pincode is also an address component held for "
        "KYC, and the two uses are not interchangeable",
    ),
)

PROTECTED_NAMES = frozenset(a.name for a in PROTECTED_ATTRIBUTES)


class FeatureCatalogue:
    """The registered feature set for one model."""

    def __init__(self, model: str, known_sources: Iterable[str] | None = None):
        self.model = model
        self._features: dict[str, ScoringFeature] = {}
        self._known_sources = set(known_sources) if known_sources is not None else None

    def register(self, feature: ScoringFeature) -> ScoringFeature:
        if feature.protected or feature.name in PROTECTED_NAMES:
            raise ProtectedAttributeLeak(
                f"{feature.name!r} is a protected attribute or proxy probe. It is "
                "measured for fairness testing (SRS §4.3.3) and is never a feature. "
                "Read it through ProtectedAttributeAccess, which no training path "
                "holds."
            )
        if feature.name in self._features:
            raise FeatureError(f"{feature.name!r} is already registered")
        if self._known_sources is not None and feature.spec.source_id not in self._known_sources:
            raise FeatureError(
                f"{feature.name!r} cites source {feature.spec.source_id!r}, which is "
                "not in the source registry (WS-0.1.1). An unregistered source has no "
                "owner, no PII class and no retention rule."
            )
        self._features[feature.name] = feature
        return feature

    def __len__(self) -> int:
        return len(self._features)

    def __contains__(self, name: object) -> bool:
        return name in self._features

    def __getitem__(self, name: str) -> ScoringFeature:
        return self._features[name]

    @property
    def names(self) -> list[str]:
        return sorted(self._features)

    def group(self, group: FeatureGroup) -> list[ScoringFeature]:
        return [f for f in self._features.values() if f.group is group]

    def requiring_consent(self) -> list[ScoringFeature]:
        return sorted(
            (f for f in self._features.values() if f.requires_consent), key=lambda f: f.name
        )

    def available_for(self, consent_purposes: Sequence[str]) -> list[str]:
        """Feature names usable for an applicant with these consents.

        SRS CS-2 requires a coverage flag on every score. This is what produces it:
        a thin-consent applicant is scored on fewer features, and the decision
        record has to say which ones were absent rather than treating them as
        missing-at-random.
        """
        granted = set(consent_purposes)
        return sorted(
            f.name
            for f in self._features.values()
            if not f.requires_consent or f.requires_consent in granted
        )

    def unresolved_monotonicity(self) -> list[str]:
        """Features whose monotonic direction is still `[POLICY]`-blocked."""
        return sorted(
            f.name for f in self._features.values() if isinstance(f.monotonic_direction, Pending)
        )

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "features": [self._features[name].to_dict() for name in self.names],
            "protected_attributes": [a.name for a in PROTECTED_ATTRIBUTES],
            "unresolved_monotonicity": self.unresolved_monotonicity(),
        }


class ProtectedAttributeAccess:
    """The only route to protected attributes, held by fairness code alone.

    A separate object rather than a flag on the catalogue. The distinction that
    matters is not "is this feature protected" — that is a boolean someone can
    forget to check — but "can this code path reach protected data at all", which
    is a property of what it was handed.
    """

    def __init__(self, values: dict[str, dict]):
        self._values = values

    def for_entity(self, entity_id: str) -> dict:
        return dict(self._values.get(entity_id, {}))

    def series(self, attribute: str, entity_ids: Sequence[str]) -> list:
        if attribute not in PROTECTED_NAMES:
            raise FeatureError(
                f"{attribute!r} is not a declared protected attribute; this accessor "
                "exists for fairness measurement, not as a second feature store"
            )
        return [self._values.get(entity_id, {}).get(attribute) for entity_id in entity_ids]


def screen_iv(information_value: float) -> tuple[ScreenVerdict, str]:
    """SRS §4.3.1 IV screen, with the ceiling treated as an alarm.

    An IV above the ceiling is not a strong feature; on credit data it is almost
    always the target in disguise — a post-decision field, a collections flag, a
    column the bank populates only for accounts that went bad. Phase 1 requires a
    leakage-investigation ticket *before use*, so this returns INVESTIGATE rather
    than PASS.
    """
    if information_value < IV_FLOOR:
        return ScreenVerdict.DROP, (
            f"IV {information_value:.4f} is below the {IV_FLOOR} floor: no usable "
            "separation, and every retained weak feature costs stability"
        )
    if information_value > IV_CEILING:
        return ScreenVerdict.INVESTIGATE, (
            f"IV {information_value:.4f} exceeds the {IV_CEILING} ceiling. Raise a "
            "leakage-investigation ticket before use (Phase 1 §4 WS-1.1 Step 3): on "
            "credit data this is usually a post-decision field, not a strong one"
        )
    return ScreenVerdict.PASS, f"IV {information_value:.4f} is inside [{IV_FLOOR}, {IV_CEILING}]"


def psi(expected: Sequence[float], actual: Sequence[float]) -> float:
    """Population Stability Index (SRS §4.3.4): ``Σ (aᵢ − eᵢ)·ln(aᵢ/eᵢ)``.

    Both arguments are bin *proportions* over the same bin edges. An empty bin on
    either side makes the term infinite, so it is floored — with the floor stated
    rather than hidden, because the choice of floor changes the number and a PSI
    quoted without it is not reproducible.
    """
    if len(expected) != len(actual):
        raise FeatureError("PSI needs the same bin edges on both sides")
    if not expected:
        raise FeatureError("PSI is undefined over zero bins")

    floor = 1e-6
    total = 0.0
    for e, a in zip(expected, actual):
        e = max(e, floor)
        a = max(a, floor)
        total += (a - e) * math.log(a / e)
    return total


def screen_psi(value: float) -> tuple[ScreenVerdict, str]:
    """SRS §4.3.4 stability screen: alert above 0.1, act above 0.25."""
    if value > PSI_ACT:
        return ScreenVerdict.ACT, (
            f"PSI {value:.4f} is above the {PSI_ACT} action threshold: the population "
            "has moved far enough that the fitted relationship is not the current one"
        )
    if value > PSI_ALERT:
        return ScreenVerdict.ALERT, f"PSI {value:.4f} is above the {PSI_ALERT} alert threshold"
    return ScreenVerdict.PASS, f"PSI {value:.4f} is within tolerance"


def _spec(name: str, source_id: str, owner: str, ttl_days: int | None, description: str):
    return FeatureSpec(
        name=name,
        ttl=timedelta(days=ttl_days) if ttl_days else None,
        owner=owner,
        source_id=source_id,
        description=description,
    )


def application_scorecard_catalogue(known_sources: Iterable[str] | None = None) -> FeatureCatalogue:
    """The Phase 1 candidate feature set, one entry per §4 Step 2 group.

    Deliberately a *candidate* set: which of these survives the IV and PSI screens
    is `[DATA]`, computed by the binning step on the real population, and no
    feature is promised a place here. What is fixed is that every candidate names
    a registered source, a point-in-time rule, a null policy and a rationale before
    anyone fits anything.
    """
    catalogue = FeatureCatalogue("application_pd", known_sources=known_sources)

    catalogue.register(ScoringFeature(
        spec=_spec("bureau_enquiries_recent", "bureau", "Credit DS", 30,
                   "Count of credit enquiries in the recent window"),
        group=FeatureGroup.BUREAU,
        point_in_time_rule=PointInTimeRule.WINDOWED_AGGREGATE,
        null_policy=NullPolicy.SEPARATE_BIN,
        rationale=(
            "Enquiry bursts precede credit stress and are the classic synthetic-"
            "identity signature when paired with a new file"
        ),
    ))
    catalogue.register(ScoringFeature(
        spec=_spec("bureau_utilisation", "bureau", "Credit DS", 30,
                   "Revolving balance over sanctioned limit"),
        group=FeatureGroup.BUREAU,
        point_in_time_rule=PointInTimeRule.AS_OF_DECISION,
        null_policy=NullPolicy.SEPARATE_BIN,
        rationale="Sustained high utilisation is the most-replicated retail risk signal",
    ))
    catalogue.register(ScoringFeature(
        spec=_spec("bureau_worst_delinquency", "bureau", "Credit DS", 30,
                   "Worst delinquency observed on the bureau file"),
        group=FeatureGroup.BUREAU,
        point_in_time_rule=PointInTimeRule.WINDOWED_AGGREGATE,
        null_policy=NullPolicy.SEPARATE_BIN,
        rationale="Past repayment behaviour is the strongest single predictor of future default",
    ))
    catalogue.register(ScoringFeature(
        spec=_spec("bureau_file_age_months", "bureau", "Credit DS", 30,
                   "Months since the oldest trade on file"),
        group=FeatureGroup.BUREAU,
        point_in_time_rule=PointInTimeRule.AS_OF_DECISION,
        null_policy=NullPolicy.SEPARATE_BIN,
        rationale=(
            "Thin and new files carry genuinely different risk, and the null here is "
            "the new-to-credit segment rather than a data defect"
        ),
    ))
    catalogue.register(ScoringFeature(
        spec=_spec("declared_income", "los", "Credit DS", None,
                   "Income stated on the application"),
        group=FeatureGroup.APPLICATION,
        point_in_time_rule=PointInTimeRule.APPLICATION_FORM,
        null_policy=NullPolicy.REJECT_ROW,
        rationale="Affordability anchor; mandatory on the form, so a null is a capture defect",
    ))
    catalogue.register(ScoringFeature(
        spec=_spec("existing_obligations", "bureau", "Credit DS", 30,
                   "Sum of existing EMI obligations"),
        group=FeatureGroup.APPLICATION,
        point_in_time_rule=PointInTimeRule.AS_OF_DECISION,
        null_policy=NullPolicy.SEPARATE_BIN,
        rationale="The denominator of affordability; obligations invisible to the bank drive FOIR error",
    ))
    catalogue.register(ScoringFeature(
        spec=_spec("requested_tenure_months", "los", "Credit DS", None,
                   "Tenure requested by the applicant"),
        group=FeatureGroup.APPLICATION,
        point_in_time_rule=PointInTimeRule.APPLICATION_FORM,
        null_policy=NullPolicy.REJECT_ROW,
        rationale="Longer tenures self-select for affordability pressure at a given amount",
    ))
    catalogue.register(ScoringFeature(
        spec=_spec("aa_income_regularity", "account_aggregator", "Credit DS", 90,
                   "Regularity of credits into the primary account"),
        group=FeatureGroup.AA_BANK_STATEMENT,
        point_in_time_rule=PointInTimeRule.WINDOWED_AGGREGATE,
        null_policy=NullPolicy.SEPARATE_BIN,
        requires_consent="account_aggregator_credit_assessment",
        rationale=(
            "For thin-file applicants, observed salary regularity substitutes for a "
            "bureau history the applicant does not have"
        ),
    ))
    catalogue.register(ScoringFeature(
        spec=_spec("aa_balance_volatility", "account_aggregator", "Credit DS", 90,
                   "Dispersion of end-of-day balances"),
        group=FeatureGroup.AA_BANK_STATEMENT,
        point_in_time_rule=PointInTimeRule.WINDOWED_AGGREGATE,
        null_policy=NullPolicy.SEPARATE_BIN,
        requires_consent="account_aggregator_credit_assessment",
        rationale="Volatility around a low mean distinguishes thin cash buffers from thin files",
    ))
    catalogue.register(ScoringFeature(
        spec=_spec("aa_bounce_count", "account_aggregator", "Credit DS", 90,
                   "Count of returned debits in the window"),
        group=FeatureGroup.AA_BANK_STATEMENT,
        point_in_time_rule=PointInTimeRule.WINDOWED_AGGREGATE,
        null_policy=NullPolicy.SEPARATE_BIN,
        requires_consent="account_aggregator_credit_assessment",
        rationale="A bounce is a realised liquidity failure, not a proxy for one",
    ))
    return catalogue

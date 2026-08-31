"""Decision Orchestrator stub.

Phase 0 WS-0.2.4 ships "a model server behind a Decision Orchestrator API stub".
SRS §2.2 fixes the shape: a Business Rules Engine wraps all ML scores and policy
rules always take precedence, because regulators require policy overridability
and an audit trail of every decision.

Two behaviours here are load-bearing rather than cosmetic:

* **Policy precedence is structural.** A policy rule that fires decides the
  outcome, and the model score is still recorded. An orchestrator where the model
  decides and policy merely adjusts cannot demonstrate overridability, whatever
  its documentation says.
* **Model unavailability is a decision path, not an exception.** SRS §12 requires
  graceful degradation to policy-rule decisioning with the request queued for
  re-score. A 500 here would be an availability breach.

Phase 0 shipped no decisioning logic: the cutoffs, bands and rules are all
`[POLICY]` from P1 onward. What shipped was the path, the logging, and the
fallback.

Phase 1 §5.2 adds the band configuration — and adds it as *config*, never as code
constants. ``bands`` is therefore an injected :class:`~lending_hub.serving.bands.BandConfig`
whose version is recorded on every decision. When it is absent, or ungrounded, or
lacking dual-control approval, the orchestrator keeps the Phase 0 behaviour and
refers every scored application to a human. That is not a degraded mode: it is
what a platform with no approved decision boundary should do, and making it the
default is what stops a missing config from being filled in with something
plausible.

Workstream: WS-0.2.4, Phase 1 §5.2 · SRS §2.2, §2.3
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Callable, Sequence

from lending_hub.decisionlog import Actor, DecisionRecord, ModelRef, Outcome, ReasonCode
from lending_hub.definitions import Ungrounded

from .bands import BandConfig, BandConfigError


class ModelUnavailable(Exception):
    """The model server did not answer. Handled, never propagated to the caller."""


@dataclass(frozen=True)
class PolicyRule:
    """A deterministic rule evaluated before any model score is considered.

    ``version`` is on the rule, not on the engine, so a decision record can name
    the exact rule that fired years later.
    """

    rule_id: str
    version: str
    outcome: Outcome
    predicate: Callable[[dict], bool]
    reason_code: str

    def fires(self, context: dict) -> bool:
        return bool(self.predicate(context))


@dataclass
class Timings:
    """Per-request latency, in milliseconds — the WS-0.2.4 gate is on p99."""

    feature_fetch_ms: float = 0.0
    score_ms: float = 0.0
    total_ms: float = 0.0


@dataclass
class DecisionResponse:
    decision_id: str
    outcome: Outcome
    decided_by: Actor
    scores: dict
    reason_codes: list[ReasonCode]
    timings: Timings
    record: DecisionRecord
    degraded: bool = False


@dataclass
class Orchestrator:
    """Track A orchestrator. The same flow the Track B service implements."""

    feature_store: object
    scorer: Callable[[dict], dict] | None
    policy_rules: Sequence[PolicyRule] = field(default_factory=tuple)
    policy_version: str = "policy-0.1.0-phase0-stub"
    model_ref: ModelRef | None = None
    features: Sequence[str] = ()
    bands: BandConfig | None = None
    """Phase 1 §5.2 band config. Absent, ungrounded or unapproved means refer."""

    @property
    def effective_policy_version(self) -> str:
        """Policy version, including the band-config hash when one is in force.

        Composed rather than stored so a config swapped between requests cannot
        be logged under the previous version — the record has to name the bands
        that actually decided, not the ones configured at start-up.
        """
        if self.bands is None:
            return self.policy_version
        return f"{self.policy_version}+bands:{self.bands.version()}"

    def decide(self, application: dict) -> DecisionResponse:
        started = time.perf_counter()
        timings = Timings()
        entity_key = application["customer_token"]

        fetch_start = time.perf_counter()
        feature_values = self.feature_store.get_online_features(entity_key, list(self.features))
        timings.feature_fetch_ms = (time.perf_counter() - fetch_start) * 1000

        context = {**application, **feature_values}

        # Policy first. A rule that fires decides; the model is still scored and
        # logged so that overridability is evidenced rather than asserted.
        fired = [rule for rule in self.policy_rules if rule.fires(context)]

        scores: dict = {}
        degraded = False
        score_start = time.perf_counter()
        if self.scorer is not None:
            try:
                scores = self.scorer(feature_values)
            except ModelUnavailable:
                degraded = True
        timings.score_ms = (time.perf_counter() - score_start) * 1000

        if fired:
            outcome, decided_by = fired[0].outcome, Actor.POLICY_RULE
            reason_codes = [ReasonCode(rule.reason_code, source="policy") for rule in fired]
        elif degraded or self.scorer is None:
            # SRS §12: fall back to policy-rule decisioning and queue for re-score.
            outcome, decided_by = Outcome.REFER, Actor.FALLBACK
            reason_codes = [ReasonCode("SYS_MODEL_UNAVAILABLE", source="platform")]
        else:
            outcome, decided_by = Outcome.REFER, Actor.MODEL
            reason_codes = [ReasonCode("P0_NO_CUTOFF_CONFIGURED", source="platform")]
            if self.bands is not None and "pd" in scores:
                try:
                    outcome = self.bands.outcome_for(scores["pd"])
                    reason_codes = [
                        ReasonCode(
                            f"BAND_{outcome.value.upper()}",
                            contribution=scores["pd"],
                            source="policy_band",
                        )
                    ]
                except Ungrounded:
                    # The cutoffs are still [POLICY] (LH-204). Refer, and say which
                    # of the two reasons applies rather than merging them.
                    reason_codes = [
                        ReasonCode("P1_CUTOFFS_NOT_RATIFIED", source="platform")
                    ]
                except BandConfigError:
                    # A configured-but-unapprovable band set is a control failure,
                    # not a scoring outcome, and it must not look like one.
                    reason_codes = [
                        ReasonCode("P1_BANDS_NOT_DUAL_APPROVED", source="platform")
                    ]

        timings.total_ms = (time.perf_counter() - started) * 1000
        decision_id = application.get("decision_id") or str(uuid.uuid4())

        record = DecisionRecord(
            decision_id=decision_id,
            decided_at=datetime.now(UTC),
            subject_token=entity_key,
            application_id=application.get("application_id", ""),
            outcome=outcome,
            decided_by=decided_by,
            inputs={k: v for k, v in application.items() if k != "customer_token"},
            feature_values=feature_values,
            models=[self.model_ref] if self.model_ref and not degraded else [],
            scores=scores,
            reason_codes=reason_codes,
            policy_version=self.effective_policy_version,
            rules_fired=[f"{r.rule_id}@{r.version}" for r in fired],
            consent_ids=application.get("consent_ids", []),
        )

        return DecisionResponse(
            decision_id=decision_id,
            outcome=outcome,
            decided_by=decided_by,
            scores=scores,
            reason_codes=reason_codes,
            timings=timings,
            record=record,
            degraded=degraded,
        )

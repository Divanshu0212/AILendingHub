"""The two answer types, and the reason there is no third.

Every gateway handler returns exactly one of:

* a payload, whose model-derived leaves carry :class:`ModelAttribution`; or
* an :class:`Unavailable`, naming the ticket that blocks it.

That is the same shape `assistant.validate()` gives an answer and
`agri.registry.VillageLocation.area_hectares` gives an area: the refusal is a
value the caller can read, not an omission the caller has to notice.

WHY UNAVAILABLE IS A 200 AND NOT A 500
----------------------------------------
An unratified FOIR cap is not a server fault, and rendering it as one puts a
governance stop in the same bucket as a crashed process. The frontend's
`GatewayError` path shows "something went wrong"; a screen that says "offers are
unavailable because LH-504 has not been ratified by Credit Policy" is the
information a reviewer needs, and it can only say that if the payload carries
the ticket. Phase 3's distinction between *not measured* and *not measurable*
is the same argument one layer up — collapsing two states into one column is how
the second never gets escalated.

So `Unavailable` is a 200 with a discriminated body, and the four fields are all
required. A reason with no ticket is a shrug.

WHY THIS MODULE HAS NO `attribute()` HELPER THAT INVENTS A TRIPLET
--------------------------------------------------------------------
:class:`ModelAttribution` requires a non-empty model id and version, and there
is no constructor here that fills them from a default, a config key or the
string "unknown". `frontend/src/lib/gateway/provenance.ts` refuses to render an
attributed value without the triplet — so the only way to satisfy that guard
without a real model is to forge a model identity, and a forged model id is
worse than the number it decorates: the number is merely wrong, while the id
sends an auditor to a model card that describes something else.

Workstream: WS-7.1.1 (SRS §11.6a)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


class GatewayContractError(Exception):
    """A handler tried to build a response the client would refuse to render."""


@dataclass(frozen=True)
class ModelAttribution:
    """Mirrors `ModelAttribution` in `frontend/src/lib/gateway/provenance.ts`.

    Three of `decisionlog.record.ModelRef`'s seven fields: two to name the model
    and one to link the decision. The other four live behind the audit-trail
    link.

    ``decision_log_id`` is nullable for one reason and it is not convenience:
    some model-derived values are produced outside a decision — a dashboard
    aggregate, a batch EWS evaluation — and forging a decision id for them would
    put entries in the audit trail that correspond to no decision.
    """

    model_id: str
    model_version: str
    decision_log_id: str | None

    def __post_init__(self) -> None:
        if not self.model_id or not self.model_version:
            raise GatewayContractError(
                "a model attribution needs a real model id and version. There is "
                "no placeholder value here: the client renders the id as the "
                "provenance of the number beside it, so a synthesised id sends an "
                "auditor to a model card describing a different model."
            )

    def to_json(self) -> dict[str, Any]:
        return {
            "modelId": self.model_id,
            "modelVersion": self.model_version,
            "decisionLogId": self.decision_log_id,
        }

    @classmethod
    def for_model(cls, artifact: Any, decision_log_id: str | None) -> ModelAttribution:
        """Build the triplet from a registered `mlops.artifact.ModelArtifact`.

        The only supported route to an attribution. It takes an artifact rather
        than two strings so that the model naming a response is one the registry
        knows about — a caller with a model id in hand and no artifact behind it
        is the case this signature is shaped to make awkward.
        """
        name = getattr(artifact, "name", "")
        version = getattr(artifact, "version", "")
        if not name or not version:
            raise GatewayContractError(
                "artifact does not name a model. `ModelAttribution.for_model` "
                "takes a registered artifact so that the id in a response "
                "resolves to a model card."
            )
        return cls(model_id=name, model_version=str(version), decision_log_id=decision_log_id)


@dataclass(frozen=True)
class Attributed:
    """A value inseparable from the model that produced it.

    Mirrors `Attributed<T>`. The pairing is the point: there is no code path in
    this package that serialises a model-derived number without one, because
    building this object is the only way to get the field into a payload.
    """

    value: Any
    attribution: ModelAttribution

    def to_json(self) -> dict[str, Any]:
        value = self.value
        return {
            "value": value.to_json() if isinstance(value, FormattedNumber) else value,
            "attribution": self.attribution.to_json(),
        }


@dataclass(frozen=True)
class FormattedNumber:
    """The raw figure and the string the BACKEND chose to display.

    Mirrors `FormattedNumber`. The `display` string is authoritative and it is
    composed here rather than in the client, because rounding a repayment figure
    on a screen a customer will hold the bank to is a disclosure decision
    (Phase 7 §8). `amount` exists for sorting and accessibility announcements.

    `display` is a *formatting* choice over a number this gateway did not
    invent, which is the line that keeps it on the right side of §8: the number
    came from `reco.feasible`, and only its rendering happens here.
    """

    amount: float
    display: str
    currency: str | None = None

    def __post_init__(self) -> None:
        if not self.display:
            raise GatewayContractError(
                "a FormattedNumber needs a display string. The client renders "
                "`display` and never formats `amount` itself, so an empty one "
                "renders as a blank where a figure should be."
            )

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"amount": self.amount, "display": self.display}
        if self.currency is not None:
            out["currency"] = self.currency
        return out


@dataclass(frozen=True)
class Unavailable(Exception):
    """A capability this deployment cannot serve, and the ticket that blocks it.

    Raised by a handler and caught by the router, which renders it as a 200 with
    a discriminated body. Every field is required:

    * ``capability`` — what was asked for, in the caller's vocabulary.
    * ``ticket`` — the blocking-ticket id, registered under `docs/phase*/`.
    * ``owner`` — the committee or squad that can close it. A ticket with no
      owner is a ticket nobody is chasing.
    * ``reason`` — why, in a sentence a screen can render to a reviewer.
    """

    capability: str
    ticket: str
    owner: str
    reason: str

    def __post_init__(self) -> None:
        for field_name in ("capability", "ticket", "owner", "reason"):
            if not getattr(self, field_name):
                raise GatewayContractError(
                    f"an Unavailable needs a {field_name}. A refusal with no "
                    "ticket and no owner is a shrug — it tells a screen that "
                    "something is missing and not who is holding it, which is "
                    "the state this response type exists to prevent."
                )

    def to_json(self) -> dict[str, Any]:
        return {
            "status": "unavailable",
            "capability": self.capability,
            "ticket": self.ticket,
            "owner": self.owner,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class UnavailableResponse:
    """The wire form of an :class:`Unavailable`, for callers that inspect it."""

    body: Mapping[str, Any]

    @property
    def ticket(self) -> str:
        return str(self.body["ticket"])

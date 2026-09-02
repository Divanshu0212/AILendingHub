"""Every endpoint that cannot be served, and the ticket that blocks each one.

This is the larger half of the gateway, and it is supposed to be. The frontend's
`AbsentAdapter` rejects every call with a ticket-bearing error; this module is
the same refusal on the server side, with two differences that matter.

First, it is **per capability rather than per build**. `AbsentAdapter` says "no
gateway is configured", which is true of a whole deployment. These say "the
feasible set needs FOIR/DSCR/LTV caps that Credit Policy has not ratified
(LH-504)", which is true of one route and names who can change it. A screen can
render the second; the first only tells a reviewer the build is unwired.

Second, it distinguishes **what is missing**. The refusals below fall into three
kinds, and collapsing them would repeat the error Phase 3 named:

* *No ratified policy value* — LH-504 caps, LH-505 pricing, LH-502 actions,
  LH-702 override codes, LH-703 freshness tolerances. A committee can close
  these tomorrow.
* *No data* — LH-510 dispositions, LH-601 corpus. Time and collection close
  these; no decision does.
* *No fitted model* — every route the client marks `modelDerived`. This one is
  the reason the whole gateway serves zero fabricated numbers: a model-derived
  response needs a `{modelId, modelVersion, decisionLogId}` triplet the client
  will refuse to render without, and no artifact in this repository can supply
  one honestly (ADR-0016, ADR-0015, ADR-0013).

WHY THE LAST KIND IS NOT A GATEWAY BUG
----------------------------------------
It would be trivial to make these routes return data. A `DecisionSummary` needs
an outcome, a score, some reason codes and a triplet; every field is a string or
a number and nothing in the wire format resists being filled in. That is exactly
why the refusal has to be structural rather than a habit: the frontend
deliberately ships no fixture adapter because "a plausible SCREEN survives review
with a wider audience", and a gateway that served the same fixtures over HTTP
would defeat that decision from a directory the frontend reviewer never opens.

Workstream: WS-7.1.1 (SRS §11.6a)
"""

from __future__ import annotations

from typing import Any, Mapping

from lending_hub.gateway.contract import Unavailable

#: Why a `modelDerived` route cannot be served, in one place.
#:
#: Repeated verbatim rather than paraphrased per endpoint, because the reason is
#: genuinely identical across all of them and eight slightly different wordings
#: would read as eight different problems.
NO_FITTED_MODEL = (
    "This response is classified model-derived by the client "
    "(frontend/src/lib/gateway/endpoints.ts), so it must carry "
    "{model_id, model_version, decision_log_id}. No model artifact is fitted in "
    "this repository: P1/P3 ship stdlib ports with no trained weights committed, "
    "P2's three networks are absent by decision (ADR-0013), P5 binds no LLM "
    "(ADR-0015) and P6 fits no challenger (ADR-0016). Synthesising a triplet "
    "would name a model that does not exist, which sends an auditor to a model "
    "card describing something else — so this route returns unavailable rather "
    "than a score with a forged provenance."
)


def _blocked(capability: str, ticket: str, owner: str, reason: str):
    """Build a handler that always raises the same :class:`Unavailable`.

    A factory rather than a table so that each route below reads as a decision
    someone made about that route, and so a new endpoint cannot be added by
    appending a row nobody classified.
    """

    def handler(*_args: Any, **_kwargs: Any) -> Mapping[str, Any]:
        raise Unavailable(capability=capability, ticket=ticket, owner=owner, reason=reason)

    handler.__name__ = f"blocked_{ticket.replace('-', '_').lower()}"
    handler.__doc__ = f"Always unavailable: {capability} ({ticket}, {owner})."
    return handler


# ------------------------------------------------------------- WS-7.3 workbench

# The queue is NOT model-derived by the client's classification, and it is still
# blocked — on data rather than on a model. That pairing is worth noticing: the
# absence of a fitted model is not the only thing stopping this gateway, and a
# reader who assumed it was would expect the queue to work.
fetch_queue = _blocked(
    "officer work queue",
    "LH-120",
    "Named source owners",
    "The queue reads the LOS application pipeline and the collections case "
    "manager. Phase 0 §3 lists the data-sharing approvals for both as entry "
    "criteria that have not landed, so there is no application table to page "
    "through. Note this is a DATA stop, not a model one — the queue row carries "
    "no score.",
)

fetch_case_file = _blocked(
    "unified case file", "LH-706", "Platform (API gateway squad)", NO_FITTED_MODEL
)

fetch_override_reasons = _blocked(
    "override reason-code taxonomy",
    "LH-702",
    "Model Risk + Credit Policy",
    "Phase 7 §4 WS-7.3.3 makes a reason code mandatory on every override and "
    "calls overrides the model-risk team's primary signal for where the model is "
    "systematically wrong — which is only true if the codes partition the ways a "
    "model can be wrong. The phase file names no codes and no owner for them. "
    "Distinct from LH-203, which is customer-facing decline wording: different "
    "audience, different approvers, different revision cadence.",
)

submit_override = _blocked(
    "decision override",
    "LH-702",
    "Model Risk + Credit Policy",
    "An override cannot be recorded without a reason code from the ratified "
    "taxonomy (LH-702), and there is no decision to override: no model produced "
    "one. Accepting the POST and storing a free-text reason would put a record "
    "in the model-risk signal that no taxonomy can aggregate.",
)

fetch_audit_trail = _blocked(
    "audit trail", "LH-706", "Platform (API gateway squad)", NO_FITTED_MODEL
)


# ----------------------------------------------------------- WS-7.5 collections

fetch_alert_queue = _blocked(
    "collections alert queue",
    "LH-502",
    "Collections Head",
    "An `ews.routing.Alert` cannot be constructed without an owner, an SLA and a "
    "recommended action — the constructor refuses, because an alert missing any "
    "of the three is a notification and the difference stops being visible once "
    "it is in a queue. The action library and its SLAs are LH-502 and "
    "unratified, so no Alert can be built to serve. " + NO_FITTED_MODEL,
)

fetch_alert = _blocked(
    "collections alert",
    "LH-502",
    "Collections Head",
    "Same constructor refusal as the queue: no ratified action library, so no "
    "Alert exists. " + NO_FITTED_MODEL,
)

fetch_outcome_codes = _blocked(
    "disposition outcome-code vocabulary",
    "LH-502",
    "Collections Head",
    "`ews.routing.Disposition` requires a non-empty outcome code and defines no "
    "vocabulary. The codes belong with the action library (LH-502). An outcome "
    "code is P6's training data — an alert closed against an invented code is a "
    "case that trains the wrong thing, which is worse than one that trains "
    "nothing.",
)

fetch_action_library = _blocked(
    "recommended-action library",
    "LH-502",
    "Collections Head",
    "The set of interventions an officer may be told to take, and how long they "
    "have. Phase 4 §9 do-not-invent.",
)

capture_disposition = _blocked(
    "alert disposition capture",
    "LH-502",
    "Collections Head",
    "A disposition needs an outcome code from a vocabulary that does not exist "
    "(LH-502) and an alert to attach to that cannot be constructed. Phase 4 §3 "
    "also lists 24 months of dispositions as an entry criterion that has not "
    "landed (LH-510) — the desk this endpoint writes to was never staffed.",
)


# ------------------------------------------------------------- WS-7.4 dashboards

fetch_dashboard_panels = _blocked(
    "risk dashboard panels",
    "LH-703",
    "Data Platform + Risk Reporting",
    "Every panel carries a freshness badge, and WS-7.4.3 makes it "
    "non-negotiable — but a badge needs a tolerance to be a badge rather than a "
    "timestamp, and the SRS's five-minute figure is the streaming ingestion SLO, "
    "not the tolerance for a vintage curve rebuilt nightly. Serving panels with "
    "an invented tolerance would mark four of six views permanently stale or "
    "permanently fresh, and the badge would be manufacturing exactly the false "
    "confidence WS-7.4.3 names. The metrics themselves need P3 aggregates over "
    "bank data (LH-120).",
)


# --------------------------------------------------------------- WS-7.2 customer

fetch_decision = _blocked(
    "application decision", "LH-706", "Platform (API gateway squad)", NO_FITTED_MODEL
)

fetch_feasible_set = _blocked(
    "feasible offer set",
    "LH-504",
    "Credit Policy",
    "`reco.feasible.PolicyCaps` has no defaults by design: the FOIR, DSCR, LTV "
    "and tenor caps are Phase 4 §9 do-not-invent, and the 1.25 DSCR the phase "
    "file quotes sits inside a worked formula illustrating the shape of the "
    "rule, not a ratified value. `config/lending_caps.yaml` does not exist, so "
    "`build_feasible_set` raises Ungrounded on every product. The rate each "
    "offer would carry is separately blocked on ALM pricing (LH-505). "
    "`POST /v1/quotes/instalment` serves a real EMI from caller-supplied inputs "
    "— it is arithmetic, not an eligibility, and it implies no offer.",
)

fetch_disclosure = _blocked(
    "disclosure document",
    "LH-701",
    "Compliance + Content Ops",
    "Phase 7 §4 WS-7.1.5 requires disclosure copy to come from a versioned, "
    "dated document registry and never to be hardcoded. That registry is a "
    "deliverable of no phase: P5 builds a corpus for the assistant, and nothing "
    "in P0–P6 creates the UI-copy store or its ratification workflow. A rendered "
    "body composed here would be an unratified sentence with a version number "
    "on it, which is worse than a missing one.",
)

grant_consent = _blocked(
    "consent capture",
    "LH-112",
    "Compliance",
    "A consent artifact records assent to a specific wording of a specific "
    "purpose, and the wording is Phase 0 do-not-invent (LH-112, DPDP purpose "
    "limitation). Storing a consent against a document this gateway invented "
    "would produce an artifact that looks like evidence of informed consent and "
    "is evidence of nothing.",
)

start_document_check = _blocked(
    "document OCR / forgery check",
    "LH-120",
    "Named source owners",
    "The document checks need the KYC and document sources whose data-sharing "
    "approvals are Phase 0 entry criteria (LH-120), and the forgery model is a "
    "P6 challenger with no labelled forgery set to fit against (ADR-0016).",
)

fetch_conversation = _blocked(
    "assistant conversation",
    "LH-601",
    "Product SMEs + Compliance",
    "There is no document corpus (LH-601) and no LLM is bound (LH-604, "
    "ADR-0015). Every claim renders with its citation or an explicit unverified "
    "state, and a turn served from nothing would be a claim with no citation "
    "that the UI is required to display rather than suppress — an uncited "
    "sentence on a customer screen, which is the specific failure Phase 5 "
    "exists to prevent. " + NO_FITTED_MODEL,
)


__all__ = [
    "NO_FITTED_MODEL",
    "fetch_queue",
    "fetch_case_file",
    "fetch_override_reasons",
    "submit_override",
    "fetch_audit_trail",
    "fetch_alert_queue",
    "fetch_alert",
    "fetch_outcome_codes",
    "fetch_action_library",
    "capture_disposition",
    "fetch_dashboard_panels",
    "fetch_decision",
    "fetch_feasible_set",
    "fetch_disclosure",
    "grant_consent",
    "start_document_check",
    "fetch_conversation",
]

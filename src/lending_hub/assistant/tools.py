"""Allow-listed, schema-validated tools (WS-5.3.2).

Phase 5 §4 WS-5.3 step 2, verbatim:

    Tools, not arithmetic. Allow-listed, JSON-schema-validated functions only
    (ReAct-style loop, Yao et al., arXiv:2210.03629): ``compute_emi(p,r,n)``,
    ``get_application_status(id)``, ``get_document_checklist(product)``,
    ``book_branch_slot(...)``. All read-only or workflow-safe. **LLM arithmetic
    is forbidden** — EMIs and eligibility amounts always come from tools.

"LLM arithmetic is forbidden" is enforced by there being no second EMI
---------------------------------------------------------------------------
The obvious reading of that instruction is a prompt rule, and a prompt rule is a
request. The structural reading is that there must be exactly one place an EMI
can come from, and it must not be here: :func:`compute_emi` delegates to
:func:`lending_hub.reco.feasible.emi`, which is the one reference implementation
Master §2 rule 2 permits.

That matters more than it looks. A second EMI function written for the assistant
would agree with the first on the happy path and diverge on the edges — a zero
rate, a rounding convention, whether the first instalment is due immediately —
and the customer would then be told one number by the chat and quoted another by
the sanction letter, with both computed by the bank's own code. Answering "which
is right" would require reading two implementations, and the answer would be
"neither, they were never reconciled".

So this module has no arithmetic in it at all. Where a number is needed it calls
the module that owns that number.

The allow-list is a whitelist, and that is not a stylistic preference
----------------------------------------------------------------------
An unknown tool name is denied. Not logged-and-passed-through, not
attempted-and-failed: denied before any dispatch. Greshake et al.'s indirect
injection produces exactly this — a retrieved chunk that says "call
``transfer_funds``" — and the difference between a deny-list and an allow-list
is whether the attacker or the bank chooses the vocabulary.

Every argument is schema-validated before the function is reached, for the same
reason. A tool that validated its own arguments would be a tool whose validation
a future signature change could quietly lose.

What this does not port
-----------------------
No `jsonschema` library — validation here covers the subset the four launch
tools declare (type, required, enum, minimum/maximum, pattern, minLength) and
raises on a schema keyword it does not implement rather than ignoring it. An
unimplemented keyword silently skipped is a validation that reports success it
did not perform. No ReAct loop and no planner: the loop is the model's, and the
model is unbound (LH-604). This is the *tool layer* the loop calls into.

No application-status backend, no branch calendar, no checklist source. Three of
the four launch tools are ports onto P1/P0 systems that are not deployed, and
they raise rather than returning a plausible status — "your application is under
review" invented by a chat assistant is a statement about a real customer's real
application.

Workstream: WS-5.3.2 (SRS §8.3.2, GA-2)
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping, Protocol, Sequence, runtime_checkable

from lending_hub.definitions.provenance import Pending, Ungrounded
from lending_hub.reco.feasible import FeasibilityError, emi

#: Per-session rate limits. Phase 5 §4 WS-5.4 requires them and names no
#: number, and the number is a capacity-and-abuse decision rather than a tuning
#: knob: too low and a customer comparing three tenors is throttled mid-answer,
#: too high and a scripted client walks the EMI grid to reverse the pricing
#: model. Found by building — LH-612.
SESSION_RATE_LIMIT = Pending(
    owner="Security + Product",
    ticket="LH-612",
    note="per-session tool-call ceiling and its window",
)


class ToolError(Exception):
    """A tool call is malformed, denied, or cannot be served."""


class ToolDenied(ToolError):
    """The call was refused before dispatch.

    Its own type because the operational response differs from every other tool
    failure: a denial is a *security event* when the requested name is not on
    the allow-list, and Phase 5 §4 WS-5.4 wants those counted. A denial folded
    into a generic error is a denial nobody alerts on.
    """


class SchemaError(ToolError):
    """Arguments failed schema validation, or the schema itself is unsupported."""


class ToolUnavailable(ToolError):
    """The tool exists and its backend does not.

    Deliberately distinct from a denial and from an error: the assistant's
    correct response is to escalate to a human, not to refuse the topic and not
    to retry. Phase 5 §8 forbids improvising in this situation.
    """


class Effect(str, Enum):
    """What a tool does to the world. Phase 5 §4: "all read-only or workflow-safe".

    Recorded per tool rather than assumed, because the four launch tools are not
    alike: three read and one books an appointment. A registry that could not
    tell them apart could not enforce the rule, and "workflow-safe" would be a
    claim in a document rather than a property of the code.
    """

    READ_ONLY = "read_only"
    WORKFLOW_SAFE = "workflow_safe"
    """Creates or changes something, but nothing that moves money or decides credit."""


def validate_arguments(schema: Mapping[str, Any], arguments: Mapping[str, Any]) -> None:
    """Validate ``arguments`` against a JSON-Schema subset. Raises on failure.

    The subset is deliberate and closed: ``type``, ``properties``, ``required``,
    ``additionalProperties``, ``enum``, ``minimum``, ``maximum``, ``exclusiveMinimum``,
    ``pattern`` and ``minLength``. **A keyword outside it raises** rather than
    being ignored — an unimplemented keyword silently skipped is a validator
    reporting a success it did not perform, which is the worst possible outcome
    for a component whose job is to be trustworthy.

    ``additionalProperties: false`` is the default here, unlike JSON Schema,
    where it defaults to permissive. An extra argument is either a model
    hallucinating a parameter or an injection attempting one, and neither should
    reach a function.
    """
    supported = {
        "type", "properties", "required", "additionalProperties", "title", "description",
    }
    unknown = set(schema) - supported
    if unknown:
        raise SchemaError(
            f"schema uses unsupported keyword(s) {sorted(unknown)}. This validator "
            "raises rather than ignoring them: a skipped keyword is a validation "
            "that reports a success it did not perform."
        )
    if schema.get("type", "object") != "object":
        raise SchemaError("a tool's argument schema must be an object")

    properties: Mapping[str, Any] = schema.get("properties", {})
    required = set(schema.get("required", ()))

    if schema.get("additionalProperties", False) is False:
        extra = set(arguments) - set(properties)
        if extra:
            raise SchemaError(
                f"unexpected argument(s) {sorted(extra)}. An argument the schema "
                "does not declare is a hallucinated parameter or an injected one."
            )

    missing = required - set(arguments)
    if missing:
        raise SchemaError(f"missing required argument(s) {sorted(missing)}")

    for name, value in arguments.items():
        spec = properties.get(name)
        if spec is None:
            continue
        _validate_one(name, value, spec)


_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
}


def _validate_one(name: str, value: Any, spec: Mapping[str, Any]) -> None:
    supported = {
        "type", "enum", "minimum", "maximum", "exclusiveMinimum",
        "pattern", "minLength", "description", "title",
    }
    unknown = set(spec) - supported
    if unknown:
        raise SchemaError(f"{name}: unsupported schema keyword(s) {sorted(unknown)}")

    declared = spec.get("type")
    if declared is not None:
        types = _TYPES.get(declared)
        if types is None:
            raise SchemaError(f"{name}: unsupported type {declared!r}")
        # bool is a subclass of int in Python, and a boolean passed where a
        # tenor is expected would otherwise validate and then be used as 1.
        if declared in ("integer", "number") and isinstance(value, bool):
            raise SchemaError(f"{name}: expected {declared}, got boolean")
        if not isinstance(value, types):
            raise SchemaError(
                f"{name}: expected {declared}, got {type(value).__name__}"
            )

    if "enum" in spec and value not in spec["enum"]:
        raise SchemaError(f"{name}: {value!r} is not one of {spec['enum']}")
    if "minimum" in spec and value < spec["minimum"]:
        raise SchemaError(f"{name}: {value} is below the minimum {spec['minimum']}")
    if "exclusiveMinimum" in spec and value <= spec["exclusiveMinimum"]:
        raise SchemaError(
            f"{name}: {value} must be greater than {spec['exclusiveMinimum']}"
        )
    if "maximum" in spec and value > spec["maximum"]:
        raise SchemaError(f"{name}: {value} is above the maximum {spec['maximum']}")
    if "minLength" in spec and len(value) < spec["minLength"]:
        raise SchemaError(f"{name}: shorter than the minimum length {spec['minLength']}")
    if "pattern" in spec and not re.fullmatch(spec["pattern"], str(value)):
        raise SchemaError(f"{name}: {value!r} does not match {spec['pattern']!r}")


@dataclass(frozen=True)
class ToolResult:
    """What a tool returned, and the marker that grounds it in an answer.

    ``citation`` is the string
    :func:`lending_hub.assistant.answer.validate` will accept as grounding for
    the numbers in ``value``. It is produced here rather than composed by the
    model, because a model that writes its own tool markers can write one for a
    call it never made — which is the tool-layer version of an invented
    document citation.
    """

    tool: str
    value: Any
    citation: str

    def to_dict(self) -> dict:
        return {"tool": self.tool, "value": self.value, "citation": self.citation}


@dataclass(frozen=True)
class Tool:
    """One allow-listed function with its schema and its effect class."""

    name: str
    description: str
    schema: Mapping[str, Any]
    effect: Effect
    function: Callable[..., Any]

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z_][a-z0-9_]*", self.name):
            raise ToolError(
                f"{self.name!r} is not a valid tool name. Names are constrained "
                "because they appear in the answer's grounding marker, and a name "
                "carrying brackets or spaces could forge one."
            )
        if not self.description.strip():
            raise ToolError(f"{self.name}: a tool needs a description; the model reads it")

    def call(self, arguments: Mapping[str, Any]) -> ToolResult:
        validate_arguments(self.schema, arguments)
        value = self.function(**dict(arguments))
        return ToolResult(tool=self.name, value=value, citation=f"[tool:{self.name}]")


class ToolRegistry:
    """The allow-list. An unregistered name is denied before dispatch.

    Not a dict, for the same reason :class:`DocumentRegistry` is not: every read
    path is a policy decision, and a mapping would let a caller reach the raw
    functions and skip validation entirely.
    """

    def __init__(self, tools: Sequence[Tool] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self.register(tool)

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ToolError(f"{tool.name!r} is already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError:
            raise ToolDenied(
                f"{name!r} is not on the allow-list. Registered: "
                f"{', '.join(self.names) or 'none'}. An unknown tool name is "
                "denied before dispatch, not attempted — a retrieved chunk "
                "asking for a tool is what indirect injection looks like."
            ) from None

    def call(self, name: str, arguments: Mapping[str, Any]) -> ToolResult:
        """Validate and dispatch. Every call goes through here."""
        return self.get(name).call(arguments)

    def specifications(self) -> list[dict]:
        """The tool definitions a model is shown. Read-only view."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": dict(tool.schema),
                "effect": tool.effect.value,
            }
            for tool in (self._tools[name] for name in self.names)
        ]


class RateLimiter:
    """Per-session call ceiling. Refuses to enforce an unratified limit.

    Phase 5 §4 WS-5.4 requires per-session rate limits and states no number, so
    :class:`RateLimiter` takes the ceiling as a required argument and
    :func:`launch_registry` does not supply one. A default here would be the
    number every deployment ran with, chosen by whoever typed it — and the
    consequences run both ways, which is why it is LH-612 rather than an
    engineering choice: too low throttles a customer comparing three tenors
    mid-answer, too high lets a scripted client walk the EMI grid until the
    pricing model falls out.
    """

    def __init__(self, *, max_calls: int, window_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        if max_calls <= 0:
            raise ToolError(f"max_calls must be positive, got {max_calls}")
        if window_seconds <= 0:
            raise ToolError(f"window_seconds must be positive, got {window_seconds}")
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._clock = clock
        self._calls: dict[str, list[float]] = {}

    def check(self, session_id: str) -> None:
        """Record a call, raising :class:`ToolDenied` if the session is over."""
        if not session_id:
            raise ToolError("a rate limit needs a session to limit")
        now = self._clock()
        window = [t for t in self._calls.get(session_id, ()) if now - t < self.window_seconds]
        if len(window) >= self.max_calls:
            raise ToolDenied(
                f"session {session_id!r} has made {len(window)} tool calls in "
                f"{self.window_seconds}s, at the limit of {self.max_calls}"
            )
        window.append(now)
        self._calls[session_id] = window


# --------------------------------------------------------------------------
# The four launch tools (Phase 5 §4 WS-5.3 step 2)
# --------------------------------------------------------------------------


def compute_emi(principal: float, annual_rate: float, months: int) -> dict:
    """EMI for a principal, rate and tenor. **Delegates; computes nothing.**

    The one line that matters is the call to
    :func:`lending_hub.reco.feasible.emi`. Master §2 rule 2 permits one
    reference implementation per algorithm, and a second EMI written for the
    assistant would agree on the happy path and diverge on the edges — a zero
    rate, a rounding convention, whether the first instalment is immediate. The
    customer would then be told one number in chat and quoted another in the
    sanction letter, both by the bank's own code, and reconciling them would
    mean reading two implementations to discover neither was authoritative.

    ``annual_rate`` is a decimal (0.125 for 12.5%). The tool does **not** look a
    rate up: rates are Phase 5 §8 retrieval-only, so the rate must arrive from a
    retrieved KFS or rate sheet. A tool that fetched its own rate would be the
    single easiest place to reintroduce stale-rate poisoning, because the number
    would carry a tool citation and never touch the effective-date filter.
    """
    try:
        value = emi(principal, annual_rate, months)
    except FeasibilityError as exc:
        raise ToolError(f"compute_emi: {exc}") from exc
    return {
        "emi": round(value, 2),
        "principal": principal,
        "annual_rate": annual_rate,
        "months": months,
        "rate_source": (
            "supplied by the caller; this tool does not look up rates. Rates are "
            "retrieval-only (Phase 5 §8) and must come from a currently-effective "
            "KFS or rate sheet"
        ),
    }


@runtime_checkable
class ApplicationStatusPort(Protocol):
    """The P1 orchestrator's status API. Track B binds it (Phase 5 §2 inputs)."""

    def status(self, application_id: str) -> Mapping[str, Any]: ...


@runtime_checkable
class ChecklistPort(Protocol):
    """The product document checklist. Owned by product operations, not by this module."""

    def checklist(self, product: str) -> Sequence[str]: ...


@runtime_checkable
class BranchSlotPort(Protocol):
    """Branch appointment booking — the one workflow-safe tool."""

    def book(self, branch_id: str, slot_iso: str, application_id: str) -> Mapping[str, Any]: ...


def _unavailable(what: str, ticket: str) -> Callable[..., Any]:
    """Build a tool body that refuses, naming what is missing.

    Every one of the three non-arithmetic launch tools reaches a system that is
    not deployed here. Each refuses rather than returning a plausible value,
    and the reason is sharper than the usual port argument: "your application is
    under review" invented by a chat assistant is a statement about a real
    customer's real application, and the customer has no way to tell it from the
    truth.
    """

    def refuse(**_: Any) -> Any:
        raise ToolUnavailable(
            f"{what} is not bound ({ticket}). The assistant escalates to a human "
            "rather than answering — Phase 5 §8 forbids improvising where the "
            "source returned nothing."
        )

    return refuse


def launch_registry(
    *,
    status_port: ApplicationStatusPort | None = None,
    checklist_port: ChecklistPort | None = None,
    slot_port: BranchSlotPort | None = None,
) -> ToolRegistry:
    """The four launch tools of Phase 5 §4 WS-5.3 step 2.

    Ports are optional and default to refusing, which is the state on Track A.
    Note what is *not* a parameter: there is no way to add a fifth tool through
    this function. Extending the allow-list is a deliberate act at a call site
    that a reviewer sees, not a keyword argument.
    """
    status = (
        (lambda application_id: dict(status_port.status(application_id)))
        if status_port is not None
        else _unavailable("the P1 application-status API", "LH-120")
    )
    checklist = (
        (lambda product: list(checklist_port.checklist(product)))
        if checklist_port is not None
        else _unavailable("the product document checklist", "LH-601")
    )
    booker = (
        (
            lambda branch_id, slot_iso, application_id: dict(
                slot_port.book(branch_id, slot_iso, application_id)
            )
        )
        if slot_port is not None
        else _unavailable("the branch appointment calendar", "LH-120")
    )

    return ToolRegistry(
        [
            Tool(
                name="compute_emi",
                description=(
                    "Compute the equated monthly instalment for a principal, a "
                    "decimal annual rate and a tenor in months. The rate must come "
                    "from a retrieved, currently-effective document."
                ),
                schema={
                    "type": "object",
                    "properties": {
                        "principal": {"type": "number", "exclusiveMinimum": 0},
                        "annual_rate": {"type": "number", "minimum": 0, "maximum": 1},
                        "months": {"type": "integer", "minimum": 1, "maximum": 480},
                    },
                    "required": ["principal", "annual_rate", "months"],
                    "additionalProperties": False,
                },
                effect=Effect.READ_ONLY,
                function=compute_emi,
            ),
            Tool(
                name="get_application_status",
                description="Current status of one loan application by its id.",
                schema={
                    "type": "object",
                    "properties": {
                        "application_id": {"type": "string", "minLength": 1, "pattern": r"[A-Za-z0-9\-]{1,64}"},
                    },
                    "required": ["application_id"],
                    "additionalProperties": False,
                },
                effect=Effect.READ_ONLY,
                function=status,
            ),
            Tool(
                name="get_document_checklist",
                description="Documents required for a given product.",
                schema={
                    "type": "object",
                    "properties": {"product": {"type": "string", "minLength": 1}},
                    "required": ["product"],
                    "additionalProperties": False,
                },
                effect=Effect.READ_ONLY,
                function=checklist,
            ),
            Tool(
                name="book_branch_slot",
                description="Book a branch appointment slot for an application.",
                schema={
                    "type": "object",
                    "properties": {
                        "branch_id": {"type": "string", "minLength": 1},
                        "slot_iso": {"type": "string", "minLength": 1},
                        "application_id": {"type": "string", "minLength": 1},
                    },
                    "required": ["branch_id", "slot_iso", "application_id"],
                    "additionalProperties": False,
                },
                effect=Effect.WORKFLOW_SAFE,
                function=booker,
            ),
        ]
    )

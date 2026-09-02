#!/usr/bin/env python3
"""Assemble the Phase 5 gate evidence pack.

Master §3.1: each phase ends with a Gate Review presenting an evidence pack.
Phase 5 §7 states six exit criteria.

**Phase 5 is the first phase whose central guarantee is structural rather than
measured**, and communicating that without overclaiming is this pack's main job.
Phase 4 introduced a "provable on Track A" column for propensity completeness;
Phase 5 has more in it, and the temptation to let a structural guarantee read as
a measurement is correspondingly larger.

So every structural claim in this pack states two things: what it guarantees,
and the code path it guarantees it over. "Uncited-numeric leak rate = 0" is true
of answers that went through `validate()`, and says nothing about a generation
service that did not.

Per ADR-0003, ADR-0004 and ADR-0015, only Track B numbers are gate evidence.
There is no Track P for this phase and that is a decision rather than an unrun
job — see ADR-0015 for why public RAG benchmarks test the wrong property.

Exit code 0 whether or not the gate passes — a report that failed CI when the
gate failed would create pressure to stop generating it.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from datetime import UTC, datetime

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from lending_hub.assistant.answer import leak_audit  # noqa: E402
from lending_hub.assistant.faithfulness import (  # noqa: E402
    CONTAINMENT_TARGET,
    FAITHFULNESS_GATE,
    WEEKLY_AUDIT_SAMPLE_RATE,
)
from lending_hub.assistant.goldenset import MIN_TRIPLES, harness_report  # noqa: E402
from lending_hub.assistant.registry import DocumentRegistry  # noqa: E402
from lending_hub.assistant.retrieval import HIT_RATE_GATE, HIT_RATE_K  # noqa: E402
from lending_hub.assistant.templates import library_report, load_default_library  # noqa: E402
from lending_hub.assistant.tools import launch_registry  # noqa: E402
from lending_hub.definitions.provenance import TBD_PATTERN  # noqa: E402

REPORTS = REPO / "reports"
MODEL_CARDS = REPO / "docs/phase5/model_cards"
TICKETS = REPO / "docs/phase5/blocking_tickets.md"

#: Phase 5 §7, verbatim, with the workstream each belongs to.
CRITERIA = [
    (f"Retrieval hit-rate@{HIT_RATE_K} >= {HIT_RATE_GATE:.0%} on the golden set", "WS-5.2"),
    (f"Answer faithfulness >= {FAITHFULNESS_GATE:.0%}", "WS-5.4"),
    ("Uncited-numeric leak rate = 0 in weekly audits (hard gate)", "WS-5.3.1"),
    ("Containment >= [POLICY: target] with correct-escalation >= 95%", "WS-5.4"),
    ("Red-team sign-off current", "WS-5.4"),
    ("Compliance sign-off on KFS/disclosure behavior", "WS-5.3.3"),
]

#: Criteria no data reachable from here can produce, with why. Each names the
#: ticket rather than saying "blocked", because the four blockers are different
#: kinds of thing and are fixed by different people.
NOT_MEASURABLE = {
    CRITERIA[0][0]: (
        "hit-rate is defined *on the golden set, against the corpus*, and "
        "neither exists (LH-602, LH-601). The metric and its admission gate are "
        "implemented and tested; the number they would compute has no inputs. "
        "No public benchmark substitutes — see ADR-0015: the stale-rate failure "
        "this phase is built around happens when retrieval *succeeds*, and no "
        "public corpus has documents that supersede each other"
    ),
    CRITERIA[1][0]: (
        "requires generated answers, which requires a bound model (LH-604). The "
        "RAGAS decomposition and aggregation are implemented; the entailment "
        "judgement is a port, and the obvious fallback is worse than nothing — "
        "a lexical-overlap groundedness score is highest exactly where a "
        "negation has been flipped"
    ),
    CRITERIA[3][0]: (
        "no sessions, and the target itself is unratified (LH-605). Containment "
        "is also the one metric in this phase that improves when the assistant "
        "gets more reckless, so a target set without correct-escalation beside "
        "it rewards answering questions the assistant should refuse"
    ),
    CRITERIA[4][0]: (
        "the three suites (injection, jailbreak, PII-leak) run in CI as required "
        "by §5 step 2, and a green suite is **not** the sign-off. They exercise "
        "the deterministic defences against the attacks we wrote down; there is "
        "no model (LH-604), so nothing tests whether a model resists a "
        "jailbreak. The sign-off is a human act by a security function that does "
        "not exist here"
    ),
    CRITERIA[5][0]: (
        "a human act by a function that does not exist here. Its inputs are "
        "LH-606 (conversational PII classes) and LH-111 (log retention), neither "
        "of which is supplied"
    ),
}


def _open_tickets() -> list[tuple[str, str]]:
    if not TICKETS.exists():
        return []
    rows = re.findall(
        r"^\|\s*([A-Z]{2,}-\d+)\s*\|\s*([^|]+)\|[^|]*\|[^|]*\|\s*([^|]+)\|",
        TICKETS.read_text(encoding="utf-8"),
        re.M,
    )
    return [(t, owner.strip()) for t, owner, status in rows if "open" in status.lower()]


def _model_cards() -> list[tuple[str, bool]]:
    if not MODEL_CARDS.exists():
        return []
    out = []
    for path in sorted(MODEL_CARDS.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        signed = bool(
            re.search(r"^\|\s*(Signed|Signature|Validator)\b", text, re.M | re.I)
        ) and not TBD_PATTERN.search(text)
        out.append((path.name, signed))
    return out


def _structural_state() -> dict:
    """Everything this repository can establish, computed rather than asserted.

    Each entry is produced by calling the code it describes, so a claim in this
    pack that stopped being true fails here rather than persisting in a
    document. That matters more for structural guarantees than for measurements:
    a stale measurement is obviously old, and a stale guarantee reads as current.
    """
    corpus = DocumentRegistry().governance_report(datetime.now(UTC).date())
    tools = launch_registry()
    templates = library_report(load_default_library())
    return {
        "leak_audit": leak_audit([]),
        "corpus": corpus,
        "golden_set": harness_report(),
        "tools": {
            "registered": list(tools.names),
            "count": len(tools),
        },
        "templates": templates,
    }


def build() -> list[str]:
    lines: list[str] = []
    add = lines.append
    state = _structural_state()

    add("# Phase 5 — gate evidence pack")
    add("")
    add(f"Generated {datetime.now(UTC).isoformat()} by `tools/phase5_gate_report.py`.")
    add("")
    add("**Phase 5 is the first phase whose central guarantee is structural**")
    add("rather than measured. Phase 4 introduced one such column (propensity")
    add("completeness); Phase 5 has several, and the risk that a structural")
    add("guarantee is read as a measurement is correspondingly larger. So every")
    add("structural claim below names the **code path it guards**, because that")
    add("is exactly what a guarantee does not cover.")
    add("")
    add("There is **no Track P** for this phase, and that is a decision rather")
    add("than an unrun job: public RAG benchmarks exist and test the wrong")
    add("property. See [ADR-0015](../docs/adr/0015-phase5-assistant-track.md).")
    add("")
    add("Per ADR-0003 and ADR-0004, **only Track B numbers are gate evidence.**")
    add("")

    add("## Exit criteria (Phase 5 §7)")
    add("")
    add("| # | Criterion | Workstream | Track | Measured | State |")
    add("|---|---|---|---|---|---|")
    for index, (name, workstream) in enumerate(CRITERIA, start=1):
        if name in NOT_MEASURABLE:
            add(f"| {index} | {name} | {workstream} | — | — | **not measurable** — {NOT_MEASURABLE[name]} |")
            continue
        # Criterion 3 — the one this repository satisfies.
        audit = state["leak_audit"]
        add(
            f"| {index} | {name} | {workstream} | A | "
            f"leak rate {audit['leak_rate']:.1f}, basis **{audit['basis']}** | "
            "**structurally guaranteed on Track A** — `ValidatedAnswer` cannot be "
            "constructed holding a kept sentence with an uncited numeric claim, "
            "so the rate cannot be non-zero along this path. Stronger than the "
            "criterion asks (a weekly audit samples, and a sample can show a rate "
            "is low but never that it is zero) and narrower than it sounds — see "
            "below |"
        )
    add("")
    add("**Track B evidence: 0 of 6.**")
    add("")

    add("## Criterion 3 — what the guarantee covers, and what it does not")
    add("")
    add("Phase 5 §7 makes the uncited-numeric leak rate a hard gate measured in")
    add("weekly audits. This repository takes the other route, the same one")
    add("Phase 4 took for propensity completeness: the validator strips an")
    add("uncited numeric sentence before the answer object exists, and an answer")
    add("stripped of all its numeric content becomes a handoff rather than a")
    add("thinner answer.")
    add("")
    add("Two limits travel with that and are not optional reading:")
    add("")
    add("* **It guards a code path, not a product.** A generation service that")
    add("  renders model output without calling `validate()` is outside the")
    add("  guarantee. The validator returns a new object rather than mutating a")
    add("  string precisely so that skipping it leaves nothing to render.")
    add("* **It is about citation, not truth.** A cited number can still be")
    add("  wrong — if the citation is to a partially superseded circular")
    add("  (LH-608), or the retrieval was poisoned. Effective-date filtering and")
    add("  the faithfulness scorer address that, and neither is measurable here.")
    add("")

    add("## What is exact, and is therefore built and tested in full")
    add("")
    add("This is the column that makes Phase 5 unlike Phase 2. Most of what the")
    add("phase file specifies is deterministic and needs no corpus, no golden")
    add("set and no model.")
    add("")
    add("| Component | Status |")
    add("|---|---|")
    add("| Effective-date filtering (`assistant.registry`) | **done** — undated ingestion refused by constructor; `effective()` requires an as-of date with no default |")
    add("| Structure-aware chunking (`assistant.chunking`) | **done** — tables atomic over the token ceiling; metadata inherited |")
    add("| BM25 (`assistant.retrieval`) | **done** — full Robertson & Zaragoza port, pinned against hand-computed scores |")
    add("| Reciprocal-rank fusion (`assistant.retrieval`) | **done** — Cormack et al., k=60, needs no score normalisation |")
    add("| Numeric-claim validator (`assistant.answer`) | **done** — adversarially tested; the phase's central control |")
    add("| Tool schema validation and allow-list (`assistant.tools`) | **done** — closed schema subset that raises on an unimplemented keyword |")
    add("| Guardrail patterns (`assistant.guardrails`) | **done** — fences, refusal ids, injection scan, PII redaction |")
    add("| Faithfulness decomposition + suppression (`assistant.faithfulness`) | **done** — the entailment judgement is a port |")
    add("| Golden-set admission gate (`assistant.goldenset`) | **done** — refuses to score an inadmissible set |")
    add("")

    add("## Deliverables (Phase 5 §6)")
    add("")
    corpus = state["corpus"]
    golden = state["golden_set"]
    templates = state["templates"]
    add("| # | Item | State |")
    add("|---|---|---|")
    add(
        f"| 1 | Document registry + dated ingestion | **done**; corpus empty "
        f"({corpus['registered']} documents registered) — LH-601 |"
    )
    add(
        f"| 2 | Chunking; golden set v1 (>= {MIN_TRIPLES} triples) | chunking **done**; "
        f"golden set **absent** — {golden['blocking_ticket']}, which depends on "
        f"{golden['depends_on']} |"
    )
    add("| 3 | Hybrid retrieval + reranker; hit-rate@5 report | BM25/RRF/metric **done**; dense leg and reranker unbound (LH-604); no hit-rate |")
    add("| 4 | Generation service + citation contract + numeric validator | validator **done**; no generation service (LH-604) |")
    add(
        f"| 5 | Tool layer (4 launch tools) + schema validation + rate limits | "
        f"**done** — {', '.join(state['tools']['registered'])}. `compute_emi` "
        f"delegates to `reco.feasible.emi`; the other three refuse without their "
        f"backends. Rate ceiling unratified (LH-612) |"
    )
    add(
        f"| 6 | Adverse-action template library | selection and ordering **done**; "
        f"{templates['templates']} templates over {templates['codes']} codes, "
        f"**none ratified** — {', '.join(templates['blocking_tickets'])} |"
    )
    add("| 7 | Guardrails; injection/jailbreak/PII red-team suites in CI | **done** — the three suites are `tests/test_assistant_redteam.py` and run on every commit, which is the cadence §5 step 2 asks for |")
    add(
        f"| 8 | Faithfulness scorer + suppression + weekly audit | scorer and "
        f"suppression **done**; entailment is a port (LH-604). Audit sample rate "
        f"{WEEKLY_AUDIT_SAMPLE_RATE:.0%} is [SPEC]; no sessions to sample |"
    )
    add("| 9 | Officer beta report; escalation flow | **not done** — 50 officers for 6 weeks (§5 step 1). The escalation *contract* exists in `answer.py` |")
    add("| 10 | DPDP/RBI-KFS compliance review memo | **not done** — inputs are LH-606 and LH-111 |")
    add("")

    add("## Nothing here is fabricated")
    add("")
    add("No corpus document, no golden-set triple, no adverse-action sentence")
    add("and no generated answer exists in this repository, and no LLM is called")
    add("anywhere. The argument is ADR-0015's and it is worth restating, because")
    add("Phase 5 is the easiest phase in the programme to demo convincingly:")
    add("")
    add("A faithfulness number computed over a fabricated corpus measures the")
    add("fabricator. Worse than Phase 4's simulated collections desk, because")
    add("the corpus author, the golden-set author and the retrieval author would")
    add("be the same person — so the assistant would score well exactly to the")
    add("extent that the questions were written against documents written to")
    add("answer them.")
    add("")
    add("And a fabricated rate circular is the *specific* failure this phase")
    add("exists to prevent. Stale-rate poisoning is named as the #1 RAG failure")
    add("in banks; a synthetic rate sheet sitting in a repository whose grounding")
    add("checker exists to stop invented numbers is a contradiction a future")
    add("reader resolves in the wrong direction.")
    add("")
    add("Test fixtures are a different matter and are used freely — Master §2")
    add("rule 3 puts synthetic data in `tests/fixtures/`. No fixture document is")
    add("servable outside a test, and no number computed on one is reported here.")
    add("")

    add("## Model cards (Master §2 rule 5)")
    add("")
    cards = _model_cards()
    if not cards:
        add("No model cards.")
    else:
        add("| Card | Signed |")
        add("|---|---|")
        for name, signed in cards:
            add(f"| {name} | {'yes' if signed else '**no**'} |")
        add("")
        add("None signed: Master §3.1 requires an independent validator who is not")
        add("the developer, and there is none. Two of these document components")
        add("that are not statistical models — a retriever and a validator — and")
        add("that is deliberate: a retrieval configuration decides which document")
        add("a customer is answered from, which is a model-risk surface whatever")
        add("it is called.")
    add("")

    add("## Open blocking tickets")
    add("")
    tickets = _open_tickets()
    if not tickets:
        add("None registered.")
    else:
        add("| Ticket | Owner |")
        add("|---|---|")
        for ticket, owner in tickets:
            add(f"| {ticket} | {owner} |")
        add("")
        add(f"{len(tickets)} open. Six are Phase 5 §8 do-not-invent values.")
        add("**Six were found by building** — LH-606 (conversational PII is not")
        add("schema PII), LH-607 (an injection defence with no stated response),")
        add("LH-608 (partial supersession, which effective dates cannot express),")
        add("LH-610 (a language slice with no minimum size), LH-611 (tool-sourced")
        add("numbers versus document-sourced ones), LH-612 (the per-session tool")
        add("ceiling).")
        add("")
        add("**LH-601 and LH-602 are the pair to read.** The corpus and the golden")
        add("set block four of the six exit criteria between them, and the second")
        add("depends on the first: a triple's answer is only correct relative to")
        add("documents that exist, so the set cannot be curated before the corpus")
        add("is. That changes the scheduling question from \"when will SMEs write")
        add("it\" to \"when will there be something to write it against\".")
        add("")
        add("**LH-608 is the one that will surprise people.** Two circulars")
        add("effective at once, the later amending the earlier in part. Retrieval")
        add("returning both lets the model pick between two live rates; superseding")
        add("the earlier drops its unamended clauses. Effective dates cannot")
        add("express it, and the phase file names neither case.")
    add("")

    add("## Gate outcome")
    add("")
    add("**Fail.** No criterion has Track B evidence. Four cannot have any")
    add("without a corpus, a golden set, a bound model and a deployed service;")
    add("two require human sign-offs by functions that do not exist here.")
    add("")
    add("One criterion — the uncited-numeric leak rate — is satisfied more")
    add("strongly than it is stated, as a property of a type rather than a")
    add("sampled measurement, over the code path `validate()` guards.")
    add("")
    add("What a Track B team receives: a complete deterministic spine — dated")
    add("corpus governance, structure-aware chunking, an exact BM25, rank fusion,")
    add("an adversarially tested numeric-claim validator, an allow-listed tool")
    add("layer whose EMI is the bank's one reference implementation, and")
    add("guardrails that treat retrieved documents as untrusted — with the LLM,")
    add("the embedder, the vector store, the reranker and the entailment model as")
    add("five unbound ports, and a validator that will strip its model's output")
    add("without asking.")

    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 5 gate evidence pack")
    parser.add_argument("--output", default="reports/phase5_gate.md")
    args = parser.parse_args(argv)

    output = pathlib.Path(args.output)
    if not output.is_absolute():
        output = REPO / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(build()) + "\n", encoding="utf-8")

    print(f"phase 5 gate pack -> {output}")
    print(f"open tickets: {len(_open_tickets())}")
    print("track P run: none by decision (ADR-0015)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

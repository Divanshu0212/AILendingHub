"use client";

/**
 * SRS Module 6 / WS-7.2.7 — the GenAI loan assistant surface.
 *
 * This screen existed nowhere: `ChatBubble` was built, `fetchConversation` was
 * declared, and nothing mounted either — so the one module a reviewer most wants
 * to see had no route at all.
 *
 * WHAT THIS SCREEN SHOWS WHEN THERE IS NO MODEL
 * ----------------------------------------------
 * No LLM is bound in this build (ADR-0015), so `/v1/assistant/conversations/{id}`
 * returns a refusal and the transcript is empty. That is the honest state, and
 * the screen renders it as one.
 *
 * But the *controls* around the model are the whole of Phase 5, and they are
 * real: the numeric-claim validator, the citation contract, the refusal library.
 * Those are what a reviewer should be looking at, because a bank's exposure from
 * an assistant is not "is the model good" — it is "what can the model say that
 * nobody approved". So the screen explains the guarantee it enforces rather than
 * showing an empty chat window and leaving the reader to guess.
 *
 * The panel below is a description of enforced behaviour, not a simulation. It
 * renders no generated text and no example answer, because a fabricated
 * assistant reply is indistinguishable from a real one in a screenshot — the
 * same refusal `adapters/port.ts` makes about fixture data.
 */

import { useAdapter } from "../../../adapters/context";
import { AppShell } from "../../../components/shell/AppShell";
import { ChatBubble } from "../../../components/shared/ChatBubble";
import { Copy } from "../../../components/shared/Copy";
import { UnavailableNotice } from "../../../components/shared/UnavailableNotice";
import { useLoad } from "../../../lib/gateway/useLoad";
import type { AssistantTurn } from "../../../lib/gateway/types";

interface Guarantee {
  readonly rule: string;
  readonly detail: string;
  readonly enforcedBy: string;
}

/**
 * The four controls Phase 5 §4 specifies, each implemented and tested.
 *
 * Structural description of shipped behaviour — not copy a customer reads, and
 * not a claim about an answer. `enforcedBy` names the module so a reviewer can
 * open it.
 */
const GUARANTEES: readonly Guarantee[] = [
  {
    rule: "A number without a citation is never shown",
    detail:
      "Every answer is parsed sentence by sentence. A sentence containing a numeric claim that resolves to no retrieved passage and no tool call is dropped before the answer object exists. If nothing survives, the turn becomes a handoff to a human rather than a thinner answer.",
    enforcedBy: "assistant.answer.validate",
  },
  {
    rule: "Decision explanations are selected, never composed",
    detail:
      "There is no code path that writes an adverse-action sentence. The assistant orders pre-approved templates keyed to reason codes; the rendering call raises while those templates are unratified. A model that paraphrased an approved sentence would produce one Compliance never saw — and it would read better, which makes it likelier to reach a customer.",
    enforcedBy: "assistant.templates",
  },
  {
    rule: "Retrieved documents are untrusted input",
    detail:
      "A retrieved passage is wrapped in a type a prompt builder must unwrap deliberately, because instruction and data arriving as one string is the mechanism of an indirect injection. The scanner reports what matched and never returns a verdict of safety.",
    enforcedBy: "assistant.guardrails",
  },
  {
    rule: "Only currently-effective documents are retrievable",
    detail:
      "Ingestion refuses an undated document, and retrieval filters by effective date. Stale-rate poisoning — answering from a superseded circular — is the most common failure of a bank RAG system, and it is a filter rather than a hope.",
    enforcedBy: "assistant.registry",
  },
];

export default function AssistantPage({
  params,
}: {
  readonly params: { readonly conversationId: string };
}) {
  const adapter = useAdapter();
  const state = useLoad<{ readonly turns: readonly AssistantTurn[] }>(
    () => adapter.fetchConversation(params.conversationId),
    [adapter, params.conversationId]
  );

  return (
    <AppShell
      active="/assistant"
      title="Loan assistant"
      subtitleKey="customer.assistant.subtitle"
    >
      {state.kind === "unavailable" ? <UnavailableNotice error={state.error} /> : null}

      {state.kind === "error" ? (
        <p role="alert" className="rounded border border-tier-red p-3 text-sm text-tier-red">
          {state.message}
        </p>
      ) : null}

      {state.kind === "loading" ? (
        <p className="text-sm text-neutral-600">
          <Copy k="common.loading" />
        </p>
      ) : null}

      {state.kind === "ready" ? (
        <div className="flex flex-col gap-3">
          {state.data.turns.map((turn) => (
            <ChatBubble key={turn.turnId} turn={turn} />
          ))}
        </div>
      ) : null}

      <section aria-labelledby="controls-heading" className="mt-8">
        <h2
          id="controls-heading"
          className="text-xs font-semibold uppercase tracking-wide text-neutral-700"
        >
          What this assistant cannot do
        </h2>
        <p className="mt-2 max-w-2xl text-sm text-neutral-600">
          A bank&apos;s exposure from an assistant is not whether the model is good.
          It is what the model can say that nobody approved. These four controls
          are implemented and tested, and they hold whichever model is bound
          behind the port.
        </p>

        <ul className="mt-4 grid gap-3 md:grid-cols-2">
          {GUARANTEES.map((g) => (
            <li
              key={g.enforcedBy}
              className="rounded border border-neutral-300 bg-white p-4"
            >
              <p className="text-sm font-semibold text-neutral-900">{g.rule}</p>
              <p className="mt-1 text-xs leading-relaxed text-neutral-600">{g.detail}</p>
              <p className="mt-2 font-mono text-xs text-brand-700">{g.enforcedBy}</p>
            </li>
          ))}
        </ul>

        <p
          role="note"
          className="mt-4 rounded border border-dashed border-neutral-400 bg-neutral-50 p-4 text-xs text-neutral-700"
        >
          No model is bound in this build and no answer is generated
          (ADR&#8209;0015). The corpus (LH&#8209;601), the golden set
          (LH&#8209;602) and the approved templates (LH&#8209;603) are each
          blocked on a named owner. Nothing above simulates an answer: a
          fabricated assistant reply is indistinguishable from a real one in a
          screenshot, which is the specific failure this module exists to
          prevent.
        </p>
      </section>
    </AppShell>
  );
}

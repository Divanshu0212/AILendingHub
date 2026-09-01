"use client";

/**
 * Shared component 3 of 7 (SRS §11.5) — the citation-linked chat bubble.
 *
 * Phase 7 §4 WS-7.2.7: "every claim renders with its citation affordance or an
 * explicit 'unverified' state — the frontend never suppresses or paraphrases a
 * missing citation into a confident-looking sentence."
 *
 * Three things follow, and the third is the one that gets missed:
 *
 * 1. A claim with citations renders them, inline and clickable.
 * 2. A claim without citations renders an UNVERIFIED marker. Not a footnote — a
 *    marker on the claim itself, because a footnote at the bottom of a bubble
 *    does not attach to the sentence a customer will quote back.
 * 3. AN UNCITED CLAIM IS STILL RENDERED. The instruction is not to suppress it.
 *    Dropping the uncited sentence and showing the cited ones produces a bubble
 *    that reads as fully grounded — the assistant made a claim, and the UI
 *    removed the evidence that it did. That is a worse outcome than showing it
 *    marked, and it is the one a well-meaning developer implements.
 *
 * The bubble is therefore built from CLAIMS, not from a string. There is no prop
 * that takes rendered assistant text, so there is no way to render a turn whose
 * claims were never separated from each other.
 */

import type { AssistantTurn, AssistantClaim, Citation } from "../../lib/gateway/types";
import { AuditLink } from "./AuditLink";
import { Copy } from "./Copy";

function CitationChip({ citation }: { citation: Citation }) {
  return (
    <a
      href={`/documents/${encodeURIComponent(citation.document.documentId)}?v=${encodeURIComponent(citation.document.version)}`}
      className="ml-1 inline-flex items-center rounded bg-blue-50 px-1.5 py-0.5 font-mono text-xs text-blue-900 underline underline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700"
      data-citation-id={citation.citationId}
      data-document-id={citation.document.documentId}
      data-document-version={citation.document.version}
    >
      {citation.label}
    </a>
  );
}

function ClaimText({ claim }: { claim: AssistantClaim }) {
  const uncited = claim.citations.length === 0;

  return (
    <span
      className={uncited ? "border-b-2 border-dotted border-amber-600" : undefined}
      data-claim-id={claim.claimId}
      data-verified={claim.verified}
    >
      {claim.text}
      {uncited ? (
        <span
          className="ml-1 inline-flex items-center rounded bg-amber-50 px-1.5 py-0.5 font-mono text-xs text-amber-900"
          role="note"
        >
          <Copy k="customer.assistant.unverifiedClaim" />
        </span>
      ) : (
        claim.citations.map((c) => <CitationChip key={c.citationId} citation={c} />)
      )}
    </span>
  );
}

export function ChatBubble({ turn }: { turn: AssistantTurn }) {
  const isAssistant = turn.role === "assistant";

  return (
    <li
      className={`max-w-prose rounded-lg border p-3 ${
        isAssistant ? "border-neutral-300 bg-white" : "ml-auto border-blue-200 bg-blue-50"
      }`}
      data-turn-id={turn.turnId}
      data-role={turn.role}
    >
      <p className="text-sm leading-relaxed text-neutral-900">
        {turn.claims.map((claim) => (
          <ClaimText key={claim.claimId} claim={claim} />
        ))}
      </p>
      {turn.attribution ? (
        <p className="mt-2">
          <AuditLink attribution={turn.attribution} />
        </p>
      ) : null}
    </li>
  );
}

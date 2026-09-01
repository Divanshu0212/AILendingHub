"use client";

/**
 * Renders one copy key from the document registry (WS-7.1.5).
 *
 * There is no `fallback` prop and there will not be one. A fallback is where
 * unratified English enters a regulated screen: someone adds it "just for the
 * demo", the demo becomes the pilot, and the sentence is in a screenshot before
 * anyone asks who approved it.
 *
 * The missing state is deliberately conspicuous. A subtle placeholder gets
 * shipped; a bracketed, ticket-bearing one gets fixed.
 */

import { useCopy } from "../../i18n/context";
import { isResolved } from "../../i18n/registry";

export function Copy({ k }: { k: string }) {
  const t = useCopy();
  const result = t(k);

  if (isResolved(result)) {
    return (
      <span data-copy-key={k} data-copy-doc={result.source.documentId} data-copy-version={result.source.version}>
        {result.text}
      </span>
    );
  }

  return (
    <span
      data-copy-key={k}
      data-copy-missing={result.reason}
      className="inline-flex items-center gap-1 rounded border border-dashed border-amber-600 bg-amber-50 px-1 font-mono text-xs text-amber-900"
      role="note"
    >
      <span aria-hidden="true">&#9888;</span>
      <span>
        {k} &middot; {result.reason} &middot; {result.ticket}
      </span>
    </span>
  );
}

/**
 * A block-level disclosure, rendered only from a ratified registry document.
 *
 * When the document is not ratified this renders a BLOCKING notice rather than
 * the body, because Phase 7 §4 WS-7.1.5's framing is that a wrong on-screen rate
 * or fee is the same failure as an ungrounded LLM answer — and the response to
 * an ungrounded answer is to withhold it, not to caveat it.
 */
export function Disclosure({
  documentId,
  body,
  version,
  effectiveFrom,
  ratified,
}: {
  documentId: string;
  body: string;
  version: string;
  effectiveFrom: string;
  ratified: boolean;
}) {
  if (!ratified) {
    return (
      <div
        role="alert"
        className="rounded border border-amber-600 bg-amber-50 p-3 text-sm text-amber-900"
        data-disclosure-blocked={documentId}
      >
        <p className="font-mono text-xs">
          {documentId} v{version} &middot; not ratified &middot; LH-701
        </p>
      </div>
    );
  }

  return (
    <section
      className="rounded border border-neutral-300 bg-white p-4 text-sm text-neutral-900"
      data-disclosure={documentId}
      aria-label={documentId}
    >
      <div className="whitespace-pre-wrap">{body}</div>
      <p className="mt-3 border-t border-neutral-200 pt-2 font-mono text-xs text-neutral-500">
        {documentId} &middot; v{version} &middot; effective {effectiveFrom}
      </p>
    </section>
  );
}

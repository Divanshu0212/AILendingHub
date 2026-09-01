"use client";

/**
 * Shared component 6 of 7 (SRS §11.5) — the consent & disclosure banner.
 *
 * Phase 7 §4 WS-7.1.5 attaches its "never hardcoded in frontend code" clause
 * specifically to this component, and Phase 7 §8 puts "disclosure/consent copy
 * wording" first on the do-not-invent list.
 *
 * SO THIS COMPONENT HAS NO ENGLISH IN IT AT ALL.
 *
 * It takes a `DisclosureDocument` — id, version, effective date, ratified flag,
 * body — and renders it. There is no `title` string, no "I agree" label, no
 * purpose description. Every one of those is copy, and every one of them is
 * exactly the kind of sentence that gets typed in as a placeholder and never
 * removed. WS-7.2.2 logs the consent record "with the same rigor as a credit
 * decision", and a consent record whose displayed wording nobody can reconstruct
 * is not that.
 *
 * WHAT MAKES THIS A CONSENT ARTIFACT RATHER THAN A CHECKBOX
 * ---------------------------------------------------------
 * The submitted `ConsentRequest` carries `documentId` AND `documentVersion`. The
 * customer did not consent to a purpose in the abstract; they consented to a
 * specific text on a specific date, and DPDP-era disputes are about which text.
 * Sending the purpose alone would produce a consent record that cannot answer
 * the only question anyone ever asks of one.
 *
 * REFUSAL BEHAVIOUR
 * -----------------
 * An unratified document does not render an accept control. Not a disabled one —
 * none. A greyed-out button next to draft text still shows the customer the
 * draft text.
 */

import { useState } from "react";
import type { ConsentRequest, DisclosureDocument } from "../../lib/gateway/types";
import { Copy, Disclosure } from "./Copy";

export function ConsentBanner({
  document,
  purposeId,
  onAccept,
  pending,
  acceptLabelKey,
}: {
  document: DisclosureDocument;
  purposeId: string;
  onAccept: (request: ConsentRequest) => void;
  pending: boolean;
  /** Registry key for the accept control's label. No default. */
  acceptLabelKey: string;
}) {
  const [checked, setChecked] = useState(false);
  const inputId = `consent-${purposeId}`;

  return (
    <section
      className="rounded border border-neutral-400 bg-neutral-50 p-4"
      data-consent-purpose={purposeId}
      data-document-id={document.documentId}
      data-document-version={document.version}
      aria-labelledby={`${inputId}-heading`}
    >
      <h2 id={`${inputId}-heading`} className="sr-only">
        {/* The accessible name is the document id, not an authored heading. */}
        {document.documentId}
      </h2>

      <Disclosure
        documentId={document.documentId}
        body={document.body}
        version={document.version}
        effectiveFrom={document.effectiveFrom}
        ratified={document.ratified}
      />

      {document.ratified ? (
        <div className="mt-4 flex items-start gap-3">
          {/* WCAG 2.2 AA 2.5.8 target size: the 24px minimum is met by the
              surrounding label's padding, not by the box itself. */}
          <input
            id={inputId}
            type="checkbox"
            checked={checked}
            onChange={(e) => setChecked(e.target.checked)}
            className="mt-1 h-5 w-5 shrink-0"
          />
          <label htmlFor={inputId} className="cursor-pointer py-1 text-sm text-neutral-900">
            {/* The consent sentence is part of the ratified document body above.
                There is no separate label text, because a label that restates
                the consent in the developer's words is a second, unratified
                consent sentence sitting next to the approved one. */}
            <span className="font-mono text-xs text-neutral-600">
              {document.documentId} v{document.version}
            </span>
          </label>
        </div>
      ) : null}

      {document.ratified ? (
        <button
          type="button"
          disabled={!checked || pending}
          onClick={() =>
            onAccept({
              purposeId,
              documentId: document.documentId,
              documentVersion: document.version,
              accepted: true,
            })
          }
          className="mt-3 min-h-[44px] rounded bg-neutral-900 px-4 py-2 text-sm text-white disabled:cursor-not-allowed disabled:bg-neutral-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700"
        >
          {/* The control's label is registry copy, resolved through <Copy>. It
              renders the missing-key placeholder when the registry is absent,
              which is ugly and correct: an unlabelled submit button on a consent
              screen is an accessibility failure (WCAG 2.2 AA 4.1.2) and a
              hardcoded one is a governance failure. The missing state is the
              only honest third option. */}
          <Copy k={acceptLabelKey} />
        </button>
      ) : null}
    </section>
  );
}

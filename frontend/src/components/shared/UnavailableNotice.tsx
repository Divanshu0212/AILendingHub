/**
 * A capability the deployment cannot serve, rendered as the gap it is.
 *
 * The visual language is deliberately the one `UnifiedCaseFile`'s `CasePanel`
 * already uses for an unavailable panel: a neutral dashed frame, `role="note"`,
 * monospace, and a `data-panel-state` attribute so a DOM snapshot preserves the
 * distinction a screenshot might not. Matching it is the point — an officer who
 * has learned what a dashed neutral box means on the case file should not have
 * to learn it again on the offers screen.
 *
 * WHY NOT THE RED ALERT BOX
 * -------------------------
 * Every screen already catches a failed fetch into `role="alert"` with a red
 * border, which is right for a 500 and wrong for this. The gateway answers a
 * blocked capability with a 200 precisely so the two stay separable
 * (`gateway/contract.py`), and rendering them identically would throw that
 * away at the last step. "Retry" is the correct affordance for one and
 * meaningless for the other.
 *
 * WHY THE TICKET AND OWNER ARE ON SCREEN
 * --------------------------------------
 * They are what makes this actionable. "Offers unavailable" tells a reviewer
 * the build is incomplete; "Credit Policy has not ratified LH-504" tells them
 * who to ask. That is the same reason `Unavailable` refuses to construct
 * without both, and it would be wasted if the UI dropped them.
 *
 * NO COPY IS AUTHORED HERE. The `reason` string is backend-supplied — the
 * gateway composes it next to the refusal it describes — and the labels around
 * it come from the chrome registry. This component chooses no wording.
 */

import type { CapabilityUnavailableError } from "../../lib/gateway/unavailable";

export function UnavailableNotice({
  error,
  className,
}: {
  error: CapabilityUnavailableError;
  className?: string;
}) {
  return (
    <div
      role="note"
      data-panel-state="unavailable"
      className={
        className ??
        "mt-4 rounded border border-dashed border-neutral-400 bg-neutral-50 p-4 text-sm text-neutral-700"
      }
    >
      <p className="font-mono text-xs uppercase tracking-wide text-neutral-500">
        {error.capability}
      </p>
      {/* Backend-supplied sentence. The gateway writes it beside the refusal it
          describes, which is the only place that can state it accurately. */}
      <p className="mt-2 text-neutral-800">{error.reason}</p>
      <p className="mt-3 font-mono text-xs text-neutral-600">
        <span data-field="ticket">{error.ticket}</span>
        <span aria-hidden="true"> &middot; </span>
        <span data-field="owner">{error.owner}</span>
      </p>
    </div>
  );
}

"use client";

/**
 * Shared component 1 of 7 (SRS §11.5) — the reason-code card.
 *
 * Phase 7 §4 WS-7.1.2 states why this is shared rather than copied:
 *
 *   "each surface consumes, never forks, these components — this is what keeps
 *    the reason-code rendering on the customer decision screen and the officer
 *    decision panel provably identical."
 *
 * "Provably" is the load-bearing word. Two implementations that agree today
 * diverge on the first bug fix applied to one of them, and the divergence is
 * invisible: both screens keep rendering plausible reasons. So there is exactly
 * one of these, both surfaces import it, and the only difference between them is
 * a prop.
 *
 * THE MISSING-WORDING CASE IS THE NORMAL CASE
 * -------------------------------------------
 * `config/reason_codes.yaml` ships every `wording` as TBD[Compliance, LH-203],
 * and `scoring.reasons` raises rather than rendering a placeholder — because "an
 * adverse-action letter carrying a sentence nobody approved is a regulatory
 * finding, not a rough edge."
 *
 * This component mirrors that refusal exactly. `sentence: null` renders the CODE
 * and a pending-ratification state. It does not render a humanised version of
 * the code ("bureau enquiries high"), which is the tempting move and is worse
 * than the raw code: a de-underscored code reads as approved copy, so nobody
 * files the ticket.
 *
 * CONTRIBUTION IS NOT SHOWN TO CUSTOMERS
 * --------------------------------------
 * A signed SHAP contribution is a model-internal quantity. On an officer screen
 * it is diagnostic; on a customer screen it is a number the customer will try to
 * act on and cannot interpret. `audience` gates it. That distinction is not in
 * the phase file and is raised as P7-F5.
 */

import type { ReasonCode } from "../../lib/gateway/types";
import type { ModelAttribution } from "../../lib/gateway/provenance";
import { AuditLink } from "./AuditLink";

export function ReasonCodeCard({
  reason,
  audience,
  rank,
}: {
  reason: ReasonCode;
  audience: "customer" | "officer";
  /**
   * Display rank, SERVER-supplied.
   *
   * This started as `index + 1` and the no-client-math check caught it, which
   * looked like a false positive and is not. Reason ordering is a model output:
   * SRS §4.3.1 ranks reason codes by points-below-max, and the SRS change log
   * records that rule being *corrected* in v1.2. A frontend that numbers an
   * array 1..n has silently adopted whatever order the JSON happened to arrive
   * in as the adverse-action ordering — and if the backend later re-sorts, the
   * two disagree with nothing to show for it. Raised as P7-F6.
   */
  rank: string;
}) {
  const pending = reason.sentence === null;

  return (
    <li
      className="rounded border border-neutral-300 bg-white p-3"
      data-reason-code={reason.code}
      data-reason-source={reason.source}
    >
      <div className="flex items-start gap-3">
        <span
          className="mt-0.5 shrink-0 rounded bg-neutral-100 px-2 py-0.5 font-mono text-xs text-neutral-700"
          aria-label={`reason ${rank}`}
        >
          {rank}
        </span>
        <div className="min-w-0 flex-1">
          {pending ? (
            <p
              className="rounded border border-dashed border-amber-600 bg-amber-50 p-2 text-sm text-amber-900"
              role="note"
            >
              <span className="font-mono">{reason.code}</span>
              <span className="mt-1 block font-mono text-xs">
                wording pending ratification &middot; LH-203
              </span>
            </p>
          ) : (
            <p className="text-sm text-neutral-900">{reason.sentence}</p>
          )}

          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-xs text-neutral-500">
            <span>{reason.code}</span>
            <span>{reason.source}</span>
            {audience === "officer" && reason.contribution !== null ? (
              // Rendered as the raw value the backend sent. No rounding, no sign
              // flip, no percentage — every one of those is an interpretation.
              <span data-contribution={reason.contribution}>{String(reason.contribution)}</span>
            ) : null}
            {reason.copyRef ? (
              <span>
                {reason.copyRef.documentId} v{reason.copyRef.version}
              </span>
            ) : null}
          </div>
        </div>
      </div>
    </li>
  );
}

/**
 * The list wrapper. Takes the reason set's attribution once rather than per
 * card, because the reasons come from one explanation of one score.
 *
 * `attribution` is required. A reason list with no model behind it is exactly
 * what §11.6b forbids, and the type is what makes that unwritable.
 */
export function ReasonCodeList({
  reasons,
  attribution,
  audience,
}: {
  reasons: readonly ReasonCode[];
  attribution: ModelAttribution;
  audience: "customer" | "officer";
}) {
  return (
    <div>
      <ol className="space-y-2">
        {reasons.map((r) => (
          <ReasonCodeCard key={r.code} reason={r} audience={audience} rank={r.rankDisplay} />
        ))}
      </ol>
      <p className="mt-2">
        <AuditLink attribution={attribution} />
      </p>
    </div>
  );
}

"use client";

/**
 * WS-7.3.3 — the override control.
 *
 * Phase 7 §4 WS-7.3.3, verbatim:
 *
 *   "every override requires a reason code and logs officer ID, timestamp, and
 *    the model version overridden (UX-5) — this is a hard requirement, not a
 *    nice-to-have, because overrides are the model-risk team's primary signal
 *    for where the model is systematically wrong."
 *
 * FOUR FIELDS, THREE OF WHICH THE OFFICER DOES NOT SUPPLY
 * ------------------------------------------------------
 * The requirement names four things to log. Only ONE of them is a form field:
 *
 *   reason code            <- the officer chooses it
 *   officer ID             <- the authenticated session
 *   timestamp              <- the server clock
 *   model version          <- the decision being overridden
 *
 * That split is the design. A client-supplied officer id on an audit record is a
 * client-asserted officer id; a client-supplied timestamp is a client-asserted
 * one. Both would appear in the model-risk team's primary signal looking exactly
 * as authentic as the real thing, and neither is recoverable afterwards. So
 * `OverrideRequest` carries neither, and `submitOverride` sends neither.
 *
 * The model version IS carried, and is taken from the decision the officer is
 * looking at rather than from "the current champion". Those differ precisely
 * when it matters: an override entered while a promotion is rolling out belongs
 * to the version that produced the score on the screen, not to whatever is
 * serving by the time the POST lands.
 *
 * WHY THE CONFIRMATION STEP EXISTS
 * --------------------------------
 * The two-step confirm is not friction theatre. An override is a decision the
 * bank will defend to a regulator, and the officer's own record of why is the
 * only contemporaneous account of it. A single-click override in a queue of
 * forty applications produces a reason code chosen by whichever option was
 * first in the list, which is worse than no taxonomy at all — it looks like
 * signal.
 *
 * WHAT THIS COMPONENT REFUSES
 * ---------------------------
 * - No reason code selected -> submit is unavailable. There is no "other" that
 *   bypasses the taxonomy, and no free-text-only path.
 * - `requiresNote` on the chosen code and an empty note -> submit unavailable.
 * - No `modelVersionOverridden` on the decision -> the control does not render
 *   at all, and says why. Overriding a decision whose model version is unknown
 *   produces an audit record that cannot answer the question it exists for.
 * - The reason-code list is fetched, never a constant (LH-702).
 */

import { useState } from "react";
import type { DecisionOutcome, OverrideReasonOption, OverrideRequest } from "../../lib/gateway/types";
import { Copy } from "../shared/Copy";

const OUTCOMES: readonly DecisionOutcome[] = ["approve", "decline", "refer"];

export function OverrideControl({
  decisionId,
  currentOutcome,
  modelVersionOverridden,
  reasonOptions,
  officerId,
  onSubmit,
  submitting,
}: {
  decisionId: string;
  currentOutcome: DecisionOutcome;
  /** Null when the decision carries no model version. Blocks the control. */
  modelVersionOverridden: string | null;
  reasonOptions: readonly OverrideReasonOption[];
  /** Displayed for confirmation only. NOT sent — the server reads the session. */
  officerId: string;
  onSubmit: (req: OverrideRequest) => void;
  submitting: boolean;
}) {
  const [reasonCode, setReasonCode] = useState("");
  const [toOutcome, setToOutcome] = useState<DecisionOutcome | "">("");
  const [note, setNote] = useState("");
  const [confirming, setConfirming] = useState(false);

  if (modelVersionOverridden === null) {
    return (
      <div role="alert" className="rounded border border-amber-600 bg-amber-50 p-3 text-sm text-amber-900">
        <p className="font-mono text-xs">
          override unavailable &middot; decision carries no model version
        </p>
        <p className="mt-1 text-xs">
          {/* Stated rather than silently hidden: a missing override button on a
              busy screen reads as a permissions problem, and the officer files
              a helpdesk ticket instead of a data one. */}
          WS-7.3.3 requires the overridden model version on the audit record.
        </p>
      </div>
    );
  }

  const selected = reasonOptions.find((o) => o.code === reasonCode) ?? null;
  const noteMissing = selected?.requiresNote === true && note.trim().length === 0;
  const ready = reasonCode !== "" && toOutcome !== "" && !noteMissing && !submitting;

  if (reasonOptions.length === 0) {
    return (
      <div role="alert" className="rounded border border-amber-600 bg-amber-50 p-3 text-sm text-amber-900">
        <p className="font-mono text-xs">
          override unavailable &middot; no ratified reason-code taxonomy &middot; LH-702
        </p>
      </div>
    );
  }

  return (
    <section
      className="rounded border border-neutral-400 bg-white p-4"
      aria-labelledby="override-heading"
      data-decision-id={decisionId}
    >
      <h3 id="override-heading" className="text-sm font-semibold text-neutral-900">
        <Copy k="workbench.override.title" />
      </h3>

      <div className="mt-3 space-y-3">
        <div>
          <label htmlFor="override-outcome" className="block text-xs font-medium text-neutral-700">
            <Copy k="workbench.decision.title" />
          </label>
          <select
            id="override-outcome"
            value={toOutcome}
            onChange={(e) => {
              setToOutcome(e.target.value as DecisionOutcome | "");
              setConfirming(false);
            }}
            className="mt-1 min-h-[44px] w-full rounded border border-neutral-400 bg-white px-2 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700"
            required
          >
            <option value="" />
            {OUTCOMES.filter((o) => o !== currentOutcome).map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label htmlFor="override-reason" className="block text-xs font-medium text-neutral-700">
            <Copy k="workbench.override.reasonRequired" />
          </label>
          <select
            id="override-reason"
            value={reasonCode}
            onChange={(e) => {
              setReasonCode(e.target.value);
              setConfirming(false);
            }}
            className="mt-1 min-h-[44px] w-full rounded border border-neutral-400 bg-white px-2 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700"
            required
            aria-required="true"
          >
            {/* No pre-selected first option. A default reason code is a reason
                code chosen by the list order, which the model-risk team would
                then read as the most common failure mode. */}
            <option value="" />
            {reasonOptions.map((o) => (
              <option key={o.code} value={o.code}>
                {o.code} &mdash; {o.label}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label htmlFor="override-note" className="block text-xs font-medium text-neutral-700">
            note{selected?.requiresNote ? " (required)" : ""}
          </label>
          <textarea
            id="override-note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={3}
            className="mt-1 w-full rounded border border-neutral-400 px-2 py-1 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700"
            aria-required={selected?.requiresNote ? "true" : "false"}
            aria-invalid={noteMissing}
          />
        </div>

        {/* What WILL be logged, shown before the officer commits. The officer id
            and the model version are displayed as read-only facts, not fields —
            the officer is being told what the record will say, not asked. */}
        <dl className="rounded bg-neutral-50 p-3 font-mono text-xs text-neutral-700">
          <div className="flex justify-between gap-4">
            <dt>officer</dt>
            <dd>{officerId}</dd>
          </div>
          <div className="flex justify-between gap-4">
            <dt>model version overridden</dt>
            <dd>{modelVersionOverridden}</dd>
          </div>
          <div className="flex justify-between gap-4">
            <dt>timestamp</dt>
            <dd>server</dd>
          </div>
        </dl>

        {confirming ? (
          <div role="alert" className="rounded border border-neutral-900 bg-neutral-50 p-3">
            <p className="text-sm text-neutral-900">
              <Copy k="workbench.override.confirmPrompt" />
            </p>
            <div className="mt-3 flex gap-2">
              <button
                type="button"
                onClick={() =>
                  onSubmit({
                    decisionId,
                    reasonCode,
                    modelVersionOverridden,
                    toOutcome: toOutcome as DecisionOutcome,
                    note: note.trim() === "" ? null : note.trim(),
                  })
                }
                disabled={submitting}
                className="min-h-[44px] rounded bg-neutral-900 px-4 text-sm text-white disabled:bg-neutral-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700"
              >
                <Copy k="common.action.submit" />
              </button>
              <button
                type="button"
                onClick={() => setConfirming(false)}
                className="min-h-[44px] rounded border border-neutral-400 px-4 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700"
              >
                <Copy k="common.action.cancel" />
              </button>
            </div>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setConfirming(true)}
            disabled={!ready}
            className="min-h-[44px] rounded border border-neutral-900 px-4 text-sm text-neutral-900 disabled:cursor-not-allowed disabled:border-neutral-300 disabled:text-neutral-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700"
          >
            <Copy k="workbench.override.title" />
          </button>
        )}

        <p className="text-xs text-neutral-600">
          <Copy k="workbench.override.loggedNotice" />
        </p>
      </div>
    </section>
  );
}

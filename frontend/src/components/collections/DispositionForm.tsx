"use client";

/**
 * WS-7.5.3 — action & disposition capture, mandatory before an alert can be closed.
 *
 * Phase 7 §4 WS-7.5.3:
 *
 *   "this is the same disposition-completeness discipline P1 established for
 *    fraud and P4 depends on for its uplift learning loop (P6 WS-6.4) — a UI
 *    that lets an agent close an alert without a disposition silently breaks
 *    that loop downstream."
 *
 * THE WORD DOING THE WORK IS *SILENTLY*
 * -------------------------------------
 * Nothing fails when an alert closes without a disposition. The queue looks
 * healthier. The agent's numbers improve. The breakage surfaces in P6, months
 * later, as a training set with a hole in it that correlates with exactly the
 * cases agents found hardest to categorise — which is a biased hole, not a
 * random one, and is worse than a smaller unbiased sample.
 *
 * HOW THIS IS ENFORCED, IN THREE PLACES
 * -------------------------------------
 * 1. IN THE API SURFACE. `endpoints.ts` has no `closeAlert` function. The only
 *    route to a closed alert is `captureDisposition`. A developer cannot write
 *    the bypass because the bypass has no name.
 * 2. IN THE TYPE. `DispositionRequest.outcomeCode` is a required string, and
 *    `ews.routing.Disposition.__post_init__` raises on an empty one. Both ends
 *    refuse.
 * 3. IN THIS FORM. No submit without an outcome code and an action. There is no
 *    "skip", no "close without disposition", and no escape hatch behind a
 *    modifier key.
 *
 * `confirmedRelevant` IS NOT "DID IT DEFAULT"
 * -------------------------------------------
 * The Python docstring is emphatic and the UI must not undo it: `confirmed_relevant`
 * asks "whether the alert identified real deterioration, NOT whether the account
 * subsequently defaulted. An alert that correctly identified distress the bank
 * then successfully cured is a true positive, and scoring it against the default
 * outcome would penalise the system for working."
 *
 * An agent presented with a checkbox labelled "was this alert correct?" will
 * answer the default question, because that is the question collections work is
 * about. So the control is an explicit two-option radio group with no default
 * selection, and its labels come from the registry where Compliance and the
 * Collections Head can word the distinction. A silent default here would fill
 * P6's training set with the wrong label.
 *
 * WHY THERE IS NO ACTION DROPDOWN CONTENT
 * ---------------------------------------
 * The action library is LH-502 and the outcome codes belong with it. Both lists
 * are fetched. When either is empty this form REFUSES TO RENDER and says which
 * ticket, rather than offering a free-text box — a free-text disposition
 * vocabulary is not a vocabulary, and P6 would be training on strings.
 */

import { useState } from "react";
import type { ActionOption, DispositionRequest, OutcomeCodeOption } from "../../lib/gateway/types";
import { Copy } from "../shared/Copy";

export function DispositionForm({
  alertId,
  outcomeCodes,
  actions,
  onSubmit,
  submitting,
}: {
  alertId: string;
  outcomeCodes: readonly OutcomeCodeOption[];
  actions: readonly ActionOption[];
  onSubmit: (req: DispositionRequest) => void;
  submitting: boolean;
}) {
  const [outcomeCode, setOutcomeCode] = useState("");
  const [actionTaken, setActionTaken] = useState("");
  const [confirmedRelevant, setConfirmedRelevant] = useState<boolean | null>(null);
  const [note, setNote] = useState("");

  if (outcomeCodes.length === 0 || actions.length === 0) {
    return (
      <div role="alert" className="rounded border border-amber-600 bg-amber-50 p-3 text-sm text-amber-900">
        <p className="font-mono text-xs">
          disposition capture unavailable &middot; no ratified action library or outcome-code
          vocabulary &middot; LH-502
        </p>
        <p className="mt-2 text-xs">
          {/* Refusal, not a free-text fallback. A free-text disposition
              vocabulary is not a vocabulary, and P6 would train on strings. */}
          An alert cannot be closed while this is true. WS-7.5.3.
        </p>
      </div>
    );
  }

  const ready =
    outcomeCode !== "" && actionTaken !== "" && confirmedRelevant !== null && !submitting;

  return (
    <form
      className="space-y-4"
      data-alert-id={alertId}
      onSubmit={(e) => {
        e.preventDefault();
        if (!ready) return;
        onSubmit({
          alertId,
          confirmedRelevant: confirmedRelevant === true,
          outcomeCode,
          actionTaken,
          note: note.trim() === "" ? null : note.trim(),
        });
      }}
    >
      <h3 className="text-sm font-semibold text-neutral-900">
        <Copy k="collections.disposition.title" />
      </h3>

      {/* The relevance question. No default selection, two explicit options,
          registry-worded — see the module docstring on why a checkbox here fills
          P6's training set with the default label instead of the relevance one. */}
      <fieldset className="rounded border border-neutral-300 p-3">
        <legend className="px-1 text-xs font-medium text-neutral-700">
          <Copy k="collections.disposition.outcomeRequired" />
        </legend>
        <div className="space-y-2">
          <label className="flex min-h-[44px] cursor-pointer items-center gap-2 text-sm">
            <input
              type="radio"
              name="confirmed-relevant"
              checked={confirmedRelevant === true}
              onChange={() => setConfirmedRelevant(true)}
              className="h-5 w-5"
            />
            <span className="font-mono text-xs">confirmed-relevant</span>
          </label>
          <label className="flex min-h-[44px] cursor-pointer items-center gap-2 text-sm">
            <input
              type="radio"
              name="confirmed-relevant"
              checked={confirmedRelevant === false}
              onChange={() => setConfirmedRelevant(false)}
              className="h-5 w-5"
            />
            <span className="font-mono text-xs">not-relevant</span>
          </label>
        </div>
      </fieldset>

      <div>
        <label htmlFor="disposition-outcome" className="block text-xs font-medium text-neutral-700">
          outcome code
        </label>
        <select
          id="disposition-outcome"
          value={outcomeCode}
          onChange={(e) => setOutcomeCode(e.target.value)}
          required
          aria-required="true"
          className="mt-1 min-h-[44px] w-full rounded border border-neutral-400 bg-white px-2 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700"
        >
          <option value="" />
          {outcomeCodes.map((o) => (
            <option key={o.code} value={o.code}>
              {o.code} &mdash; {o.label}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label htmlFor="disposition-action" className="block text-xs font-medium text-neutral-700">
          action taken
        </label>
        <select
          id="disposition-action"
          value={actionTaken}
          onChange={(e) => setActionTaken(e.target.value)}
          required
          aria-required="true"
          className="mt-1 min-h-[44px] w-full rounded border border-neutral-400 bg-white px-2 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700"
        >
          <option value="" />
          {actions.map((a) => (
            <option key={a.actionId} value={a.actionId}>
              {a.actionId} &mdash; {a.label}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label htmlFor="disposition-note" className="block text-xs font-medium text-neutral-700">
          note
        </label>
        <textarea
          id="disposition-note"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={3}
          className="mt-1 w-full rounded border border-neutral-400 px-2 py-1 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700"
        />
      </div>

      {/* There is no second button. No 'close without disposition', no 'skip',
          no 'save for later' that leaves the alert closed. WS-7.5.3. */}
      <button
        type="submit"
        disabled={!ready}
        className="min-h-[44px] rounded bg-neutral-900 px-4 text-sm text-white disabled:cursor-not-allowed disabled:bg-neutral-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700"
      >
        <Copy k="common.action.submit" />
      </button>
    </form>
  );
}

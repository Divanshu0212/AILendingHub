"use client";

/**
 * WS-7.3.1 — the officer queue.
 *
 * The queue reads real consumer credit applications: 307,511 of them, with the
 * publisher's outcome label attached. What an officer triages on is here —
 * amounts, product, and the affordability ratio the application record carries.
 *
 * THE COLUMN THAT IS NOT HERE
 * -----------------------------
 * There is no score column. The scorecard is fitted and its numbers are real
 * (test Gini 46.86 on this dataset), but it is not loaded into the serving
 * path, and a column headed "score" filled by anything else — a heuristic, a
 * ratio, a placeholder — would be indistinguishable from the real thing in a
 * screenshot. That is the substitution this build refuses everywhere else, and
 * a queue is the worst place to make an exception: a score is what an officer
 * acts on.
 *
 * What the queue shows instead is `affordabilityBand`, the annuity-to-income
 * ratio bucketed. That is an arithmetic fact about the application rather than
 * a model output, and it is named so the two cannot be confused. The real risk
 * bands are LH-204 and unratified.
 *
 * SLA is likewise absent rather than invented. It needs a case-management
 * system (LH-120); a countdown computed from the browser clock would show a
 * different queue order on each desk.
 */

import { useState } from "react";

import { AppShell } from "../../../components/shell/AppShell";
import { Copy } from "../../../components/shared/Copy";
import { ProvenanceTag } from "../../../components/charts/Charts";
import { GatewayClient } from "../../../lib/gateway/client";
import { devSession } from "../../../adapters/devSession";
import { fetchInsightQueue, type QueueRow } from "../../../lib/gateway/endpoints";
import { useLoad } from "../../../lib/gateway/useLoad";
import { UnavailableNotice } from "../../../components/shared/UnavailableNotice";

const BAND_STYLE: Readonly<Record<string, string>> = {
  comfortable: "bg-emerald-50 text-fresh-ok",
  moderate: "bg-blue-50 text-brand-700",
  stretched: "bg-amber-50 text-tier-amber",
  unknown: "bg-neutral-100 text-neutral-500",
};

export default function QueuePage() {
  const client = new GatewayClient(devSession());
  const [band, setBand] = useState<string>("");
  const state = useLoad(() => fetchInsightQueue(client, 40), []);

  const rows: readonly QueueRow[] =
    state.kind === "ready"
      ? state.data.items.filter((r) => band === "" || r.affordabilityBand === band)
      : [];

  return (
    <AppShell active="/workbench" title="Officer queue" subtitleKey="workbench.queue.subtitle">
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
        <>
          <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
            <label className="text-xs text-neutral-700">
              <span className="block font-medium">Affordability</span>
              <select
                value={band}
                onChange={(e) => setBand(e.target.value)}
                className="mt-1 min-h-[38px] rounded-md border border-neutral-300 bg-white px-3 text-sm"
              >
                <option value="">all</option>
                <option value="comfortable">comfortable</option>
                <option value="moderate">moderate</option>
                <option value="stretched">stretched</option>
              </select>
            </label>
            <p className="text-xs text-neutral-500">
              {rows.length} shown · {state.data.items.length} loaded
            </p>
          </div>

          <div className="overflow-x-auto rounded-lg border border-neutral-200 bg-white shadow-sm">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-neutral-200 bg-neutral-50 text-left text-xs uppercase tracking-wide text-neutral-500">
                  <th scope="col" className="p-3">application</th>
                  <th scope="col" className="p-3">product</th>
                  <th scope="col" className="p-3 text-right">credit</th>
                  <th scope="col" className="p-3 text-right">income</th>
                  <th scope="col" className="p-3 text-right">annuity</th>
                  <th scope="col" className="p-3">affordability</th>
                  <th scope="col" className="p-3">observed outcome</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.applicationId} className="border-b border-neutral-100 last:border-0">
                    <td className="p-3">
                      <a
                        href={`/workbench/cases/${encodeURIComponent(r.applicationId)}`}
                        className="rounded font-mono text-brand-700 underline underline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-700"
                      >
                        {r.applicationId}
                      </a>
                    </td>
                    <td className="p-3 text-neutral-700">{r.product}</td>
                    <td className="p-3 text-right font-mono tabular-nums text-neutral-900">
                      {r.creditDisplay}
                    </td>
                    <td className="p-3 text-right font-mono tabular-nums text-neutral-600">
                      {r.incomeDisplay}
                    </td>
                    <td className="p-3 text-right font-mono tabular-nums text-neutral-600">
                      {r.annuityDisplay}
                    </td>
                    <td className="p-3">
                      <span
                        className={`rounded-full px-2 py-0.5 font-mono text-xs ${
                          BAND_STYLE[r.affordabilityBand] ?? BAND_STYLE.unknown
                        }`}
                      >
                        {r.affordabilityBand}
                      </span>
                    </td>
                    <td className="p-3">
                      <span
                        className={
                          r.observedOutcome === "difficulty"
                            ? "font-mono text-xs text-tier-red"
                            : "font-mono text-xs text-neutral-500"
                        }
                      >
                        {r.observedOutcome}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="mt-4 rounded-md bg-neutral-50 px-4 py-3">
            <p className="text-xs font-medium text-neutral-800">There is no score column</p>
            <p className="mt-1 max-w-3xl text-xs leading-relaxed text-neutral-600">
              {state.data.scoreNote}
            </p>
          </div>

          <ProvenanceTag provenance={state.data.provenance} />
        </>
      ) : null}
    </AppShell>
  );
}

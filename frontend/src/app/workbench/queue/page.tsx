"use client";

/**
 * WS-7.3.1 — the officer queue, filterable by product, risk band and SLA.
 *
 * The SLA column shows a server-rendered remaining string and a server-computed
 * breach flag. The frontend does not subtract `slaDueAt` from the browser clock:
 * a branch terminal with a skewed clock would show a different queue order than
 * the desk next to it, and SLA compliance is a reported figure (§8 exit
 * criterion 2 for collections; the same discipline applies here).
 *
 * No risk-band values are enumerated here. The band edges are LH-204 and
 * unratified, so the filter options come from the gateway — a client-side list
 * of band names would be the band taxonomy, hardcoded, in a dropdown.
 */

import { useState } from "react";
import { useAdapter } from "../../../adapters/context";
import type { Page, QueueItem, QueueFilters } from "../../../lib/gateway/endpoints";
import { useLoad } from "../../../lib/gateway/useLoad";
import { Copy } from "../../../components/shared/Copy";
import { UnavailableNotice } from "../../../components/shared/UnavailableNotice";
import { AppShell } from "../../../components/shell/AppShell";

export default function QueuePage() {
  const adapter = useAdapter();
  const [filters, setFilters] = useState<QueueFilters>({});
  const state = useLoad<Page<QueueItem>>(() => adapter.fetchQueue(filters), [adapter, filters]);

  return (
    <AppShell active="/workbench" title="Officer queue" subtitleKey="workbench.queue.subtitle">

      <div className="mt-4 flex flex-wrap gap-3">
        <label className="text-xs text-neutral-700">
          <span className="block">SLA</span>
          <select
            value={filters.slaState ?? ""}
            onChange={(e) =>
              setFilters({
                ...filters,
                slaState: (e.target.value || undefined) as QueueFilters["slaState"],
              })
            }
            className="mt-1 min-h-[44px] rounded border border-neutral-400 bg-white px-2 text-sm"
          >
            <option value="" />
            <option value="within">within</option>
            <option value="due-soon">due-soon</option>
            <option value="breached">breached</option>
          </select>
        </label>
      </div>

      {state.kind === "unavailable" ? <UnavailableNotice error={state.error} /> : null}

      {state.kind === "error" ? (
        <p role="alert" className="mt-4 rounded border border-tier-red p-3 text-sm text-tier-red">
          {state.message}
        </p>
      ) : null}

      {state.kind === "loading" ? (
        <p className="mt-4 text-sm text-neutral-600">
          <Copy k="common.loading" />
        </p>
      ) : state.kind === "ready" ? (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-neutral-300 text-left text-xs uppercase tracking-wide text-neutral-500">
                <th scope="col" className="p-2">application</th>
                <th scope="col" className="p-2">product</th>
                <th scope="col" className="p-2">band</th>
                <th scope="col" className="p-2">received</th>
                <th scope="col" className="p-2">SLA</th>
              </tr>
            </thead>
            <tbody>
              {state.data.items.map((item) => (
                <tr key={item.applicationId} className="border-b border-neutral-200">
                  <td className="p-2">
                    <a
                      href={`/workbench/cases/${encodeURIComponent(item.applicationId)}`}
                      className="rounded font-mono text-blue-800 underline underline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700"
                    >
                      {item.applicationId}
                    </a>
                  </td>
                  <td className="p-2 text-neutral-900">{item.product}</td>
                  <td className="p-2 font-mono text-neutral-900">{item.riskBand}</td>
                  <td className="p-2 font-mono text-neutral-600">{item.receivedAt}</td>
                  <td className="p-2 font-mono">
                    <span className={item.slaBreached ? "text-tier-red" : "text-neutral-900"}>
                      {item.slaRemainingDisplay}
                    </span>
                    {item.slaBreached ? (
                      <span className="ml-2 rounded bg-tier-red px-1.5 py-0.5 text-xs text-white">
                        breached
                      </span>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </AppShell>
  );
}

"use client";

/**
 * WS-7.5.1 — the prioritized queue by EWS tier (Amber/Red).
 *
 * Ordering is the gateway's. The frontend does not sort by tier then SLA,
 * because "prioritized" is a collections-desk policy: whether a Red alert at
 * hour 20 of a 24-hour SLA outranks an Amber at hour 70 of 72 is a workload
 * decision, and `apply_officer_cap` in ews/routing.py already sorts worst-first
 * on the server side with the same question open (LH-507).
 *
 * The undisposed count is shown prominently because it is the §8 exit criterion
 * ("disposition-capture completeness = 100% in the collections console pilot")
 * made visible to the person who can move it. A completeness metric that only
 * appears in a monthly pack is a metric nobody is accountable for on the day.
 */

import { useState } from "react";
import { useAdapter } from "../../../adapters/context";
import type { AlertQueueFilters, Page } from "../../../lib/gateway/endpoints";
import type { Alert } from "../../../lib/gateway/types";
import { TierBadge } from "../../../components/shared/AlertViewer";
import { Copy } from "../../../components/shared/Copy";
import { UnavailableNotice } from "../../../components/shared/UnavailableNotice";
import { useLoad } from "../../../lib/gateway/useLoad";
import { AppShell } from "../../../components/shell/AppShell";

export default function CollectionsQueuePage() {
  const adapter = useAdapter();
  const [filters, setFilters] = useState<AlertQueueFilters>({});
  const state = useLoad<Page<Alert>>(() => adapter.fetchAlertQueue(filters), [adapter, filters]);

  const page = state.kind === "ready" ? state.data : null;
  const undisposed = page ? page.items.filter((a) => a.disposition === null) : [];

  return (
    <AppShell active="/collections" title="Collections queue" subtitleKey="collections.queue.subtitle">

      <div className="mt-4 flex flex-wrap gap-3">
        <label className="text-xs text-neutral-700">
          <span className="block">tier</span>
          <select
            value={filters.tier ?? ""}
            onChange={(e) =>
              setFilters({ ...filters, tier: (e.target.value || undefined) as Alert["tier"] })
            }
            className="mt-1 min-h-[44px] rounded border border-neutral-400 bg-white px-2 text-sm"
          >
            <option value="" />
            <option value="RED">RED</option>
            <option value="AMBER">AMBER</option>
          </select>
        </label>
        <label className="text-xs text-neutral-700">
          <span className="block">SLA</span>
          <select
            value={filters.slaState ?? ""}
            onChange={(e) =>
              setFilters({
                ...filters,
                slaState: (e.target.value || undefined) as AlertQueueFilters["slaState"],
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

      {page === null ? (
        state.kind === "loading" ? (
          <p className="mt-4 text-sm text-neutral-600">
            <Copy k="common.loading" />
          </p>
        ) : null
      ) : (
        <>
          {/* The §8 completeness figure, on the screen of the person who moves it.
              Rendered as a count of items, not as a percentage — a percentage
              would be arithmetic, and the raw count is the actionable number. */}
          <p className="mt-4 rounded bg-neutral-100 p-3 font-mono text-xs text-neutral-800">
            undisposed in view: {undisposed.length} of {page.items.length}
          </p>

          <div className="mt-4 overflow-x-auto">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-neutral-300 text-left text-xs uppercase tracking-wide text-neutral-500">
                  <th scope="col" className="p-2">tier</th>
                  <th scope="col" className="p-2">alert</th>
                  <th scope="col" className="p-2">account</th>
                  <th scope="col" className="p-2">action</th>
                  <th scope="col" className="p-2">owner</th>
                  <th scope="col" className="p-2">SLA due</th>
                  <th scope="col" className="p-2">disposition</th>
                </tr>
              </thead>
              <tbody>
                {page.items.map((a) => (
                  <tr key={a.alertId} className="border-b border-neutral-200">
                    <td className="p-2">
                      <TierBadge tier={a.tier} />
                    </td>
                    <td className="p-2">
                      <a
                        href={`/collections/alerts/${encodeURIComponent(a.alertId)}`}
                        className="rounded font-mono text-blue-800 underline underline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700"
                      >
                        {a.alertId}
                      </a>
                    </td>
                    <td className="p-2 font-mono text-neutral-900">{a.accountId}</td>
                    <td className="p-2 text-neutral-900">{a.recommendedAction}</td>
                    <td className="p-2 font-mono text-neutral-700">{a.ownerId}</td>
                    <td className="p-2 font-mono">
                      <span className={a.slaBreached ? "text-tier-red" : "text-neutral-900"}>
                        {a.slaDueAt}
                      </span>
                    </td>
                    <td className="p-2 font-mono text-xs">
                      {a.disposition ? (
                        <span className="text-neutral-700">{a.disposition.outcomeCode}</span>
                      ) : (
                        <span className="rounded bg-amber-100 px-1.5 py-0.5 text-amber-900">
                          required
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </AppShell>
  );
}

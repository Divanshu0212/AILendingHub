"use client";

/**
 * WS-7.4 — risk & portfolio dashboards.
 *
 * Phase 7 §4 WS-7.4: "Thin UI layer over the P3 OLAP store and dashboard API —
 * this workstream does not reimplement any P3 metric logic, it renders what P3
 * computes."
 *
 * So this file has no metric in it. It fetches panels and renders them through
 * the shared `Panel`, which takes freshness as a required prop. That is the
 * whole of WS-7.4.3's non-negotiable requirement, implemented as a type: there
 * is no code path to a panel without a badge.
 *
 * ROLE DIFFERENCES ARE PERMISSION AND LAYOUT, NEVER NUMBERS
 * --------------------------------------------------------
 * WS-7.4.2 is explicit about this and it is easy to violate by accident. The CRO
 * view and the portfolio-manager view are the same `dashboardId` fetched by
 * different roles; the gateway decides which panels come back. There is no
 * client-side filter that hides a panel from a role, because a client-side
 * filter is a client-side permission, and there is no per-role transform of a
 * metric, because that is how two roles come to quote different NPA figures in
 * the same meeting.
 *
 * THE SIX VIEWS ARE ROUTES, NOT COMPONENTS
 * ----------------------------------------
 * SRS §9.2 names six: portfolio overview, vintage & roll-rate, concentration &
 * weather-overlay map, model-health, scenario widget, drill-through account
 * list. Each is a `dashboardId`. They are not six components here because the
 * only thing that differs between them is which panels the backend returns —
 * building six bespoke layouts would put chart-selection logic in the frontend,
 * and a chart type is a claim about the data's shape.
 *
 * The weather-overlay map and the scenario widget are the two that will
 * eventually need more than a panel list (a choropleth and an input form). Both
 * are P3/P2-gated and neither has a data source here, so neither is built.
 */

import { useEffect, useState } from "react";
import { useAdapter } from "../../../adapters/context";
import { Panel } from "../../../components/shared/FreshnessBadge";
import { AuditLink } from "../../../components/shared/AuditLink";
import { Copy } from "../../../components/shared/Copy";
import type { DashboardPanel } from "../../../lib/gateway/types";
import { AppShell } from "../../../components/shell/AppShell";

export default function DashboardPage({ params }: { params: { dashboardId: string } }) {
  const adapter = useAdapter();
  const [panels, setPanels] = useState<readonly DashboardPanel[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    adapter
      .fetchDashboardPanels(params.dashboardId)
      .then((r) => {
        if (!cancelled) setPanels(r.panels);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [adapter, params.dashboardId]);

  if (error) {
    return (
      <AppShell active="/dashboards" title="Risk dashboard" subtitleKey="dashboards.portfolio.subtitle">
        <p role="alert" className="rounded border border-tier-red p-3 text-sm text-tier-red">
          {error}
        </p>
      </AppShell>
    );
  }

  if (panels === null) {
    return (
      <AppShell active="/dashboards" title="Risk dashboard" subtitleKey="dashboards.portfolio.subtitle">
        <p className="text-sm text-neutral-600">
          <Copy k="common.loading" />
        </p>
      </AppShell>
    );
  }

  return (
    <AppShell active="/dashboards" title="Risk dashboard" subtitleKey="dashboards.portfolio.subtitle">
      <h2 className="mb-4 text-lg font-semibold text-neutral-900">
        <Copy k="dashboards.portfolio.title" />
      </h2>

      <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
        {panels.map((panel) => (
          <Panel
            key={panel.panelId}
            title={panel.title}
            freshness={panel.freshness}
            drillThroughHref={panel.drillThroughHref}
          >
            <dl className="space-y-2">
              {panel.metrics.map((m) => (
                <div key={m.key} className="flex items-baseline justify-between gap-4">
                  <dt className="text-sm text-neutral-600">{m.label}</dt>
                  <dd className="text-right">
                    {/* `.display` only. `.amount` is present and unread. */}
                    <span className="font-mono text-base text-neutral-900">{m.value.display}</span>
                    {m.delta ? (
                      <span className="ml-2 font-mono text-xs text-neutral-600">
                        {/* Backend-computed delta. Not this value minus a
                            previously fetched one - two fetches at different
                            freshness would produce a delta belonging to neither. */}
                        {m.delta.display}
                      </span>
                    ) : null}
                  </dd>
                </div>
              ))}
            </dl>
            {panel.attribution ? (
              <p className="mt-3">
                <AuditLink attribution={panel.attribution} />
              </p>
            ) : null}
          </Panel>
        ))}
      </div>
    </AppShell>
  );
}

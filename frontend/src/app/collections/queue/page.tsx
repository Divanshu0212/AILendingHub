"use client";

/**
 * WS-7.5.1 — the collections console.
 *
 * There is no alert queue on this screen, and that is the finding rather than a
 * gap. Routing an account to Amber or Red needs the tier thresholds (LH-508)
 * and the alert budget that caps how many alerts a desk can absorb (LH-206).
 * Neither is ratified, so no account is routed — and a queue of invented rows
 * would be a queue an officer could work, which is the worst kind of fiction
 * because it looks like an operating system.
 *
 * What the screen shows instead is what the detector actually demonstrated on
 * 338,210 real account-months: that deterioration precedes default, and by how
 * long, at each alerting threshold. That IS the decision the two tickets are
 * about, laid out — so the screen is more useful than a fake queue, not less.
 */

import { AppShell } from "../../../components/shell/AppShell";
import { BarChart, ProvenanceTag } from "../../../components/charts/Charts";
import { Copy } from "../../../components/shared/Copy";
import { GatewayClient } from "../../../lib/gateway/client";
import { devSession } from "../../../adapters/devSession";
import { fetchEws } from "../../../lib/gateway/endpoints";
import { useLoad } from "../../../lib/gateway/useLoad";
import { UnavailableNotice } from "../../../components/shared/UnavailableNotice";

function Card({ children }: { readonly children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-neutral-200 bg-white p-5 shadow-sm">
      {children}
    </section>
  );
}

export default function CollectionsQueuePage() {
  const client = new GatewayClient(devSession());
  const state = useLoad(() => fetchEws(client), []);

  return (
    <AppShell
      active="/collections"
      title="Collections"
      subtitleKey="collections.queue.subtitle"
    >
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
        <div className="flex flex-col gap-5">
          <Card>
            <h2 className="text-sm font-semibold text-neutral-900">
              Does deterioration precede default?
            </h2>
            <p className="mt-1 max-w-3xl text-xs leading-relaxed text-neutral-600">
              Tested on {state.data.reachableDefaults} defaults the detector could
              realistically have reached, out of {state.data.defaultsInPanel} in the
              panel. The other {state.data.beforeFirstSnapshot} happened before the
              detector had any history to look at.
            </p>

            <div className="mt-4 grid gap-5 lg:grid-cols-2">
              <BarChart
                title="Capture rate"
                caption="share of reachable defaults alerted in time"
                bars={state.data.thresholds.map((t) => ({
                  label: t.threshold,
                  value: t.captureRate,
                  display: t.captureRateDisplay,
                  sub: `${t.accountsAlertedDisplay} alerted`,
                  highlight: t.threshold === "p99",
                }))}
              />
              <BarChart
                title="Median lead time"
                caption="days between first alert and default"
                bars={state.data.thresholds.map((t) => ({
                  label: t.threshold,
                  value: t.medianLeadDays,
                  display: `${t.medianLeadDays}d`,
                  sub: `${t.captured} caught`,
                  highlight: t.threshold === "p99",
                }))}
              />
            </div>

            <div className="mt-4 rounded-md bg-blue-50 px-4 py-3">
              <p className="text-xs leading-relaxed text-neutral-700">
                Reading the two together is the operating decision. A looser
                threshold catches more and alerts more people; a tighter one
                halves both the workload and the catch. Where the bar sits
                belongs to the Collections Head, and the sweep is what that
                choice looks like.
              </p>
            </div>

            <ProvenanceTag provenance={state.data.provenance} />
          </Card>

          <div className="grid gap-5 lg:grid-cols-2">
            <Card>
              <h2 className="text-sm font-semibold text-neutral-900">
                Behavioural velocity
              </h2>
              <div className="mt-3 flex flex-wrap gap-6">
                <div>
                  <p className="font-mono text-2xl font-semibold tabular-nums text-brand-800">
                    {state.data.velocity.totalVelocitiesDisplay}
                  </p>
                  <p className="mt-0.5 text-xs text-neutral-500">velocities computed</p>
                </div>
                <div>
                  <p className="font-mono text-2xl font-semibold tabular-nums text-brand-800">
                    {state.data.velocity.snapshotsRankable}
                  </p>
                  <p className="mt-0.5 text-xs text-neutral-500">
                    snapshots large enough to rank
                  </p>
                </div>
              </div>
              <p className="mt-3 text-xs leading-relaxed text-neutral-600">
                A percentile needs a portfolio behind it. Snapshots with fewer
                than {state.data.velocity.minPortfolioForPercentile} accounts are
                not ranked, because a percentile over a handful of accounts
                describes the handful.
              </p>
            </Card>

            <Card>
              <h2 className="text-sm font-semibold text-neutral-900">
                Alert precision
              </h2>
              <p className="mt-2 inline-block rounded-full bg-amber-50 px-2.5 py-1 font-mono text-xs text-tier-amber">
                {state.data.precision.state}
              </p>
              <p className="mt-3 text-xs leading-relaxed text-neutral-600">
                {state.data.precision.reason}
              </p>
            </Card>
          </div>

          <Card>
            <h2 className="text-sm font-semibold text-neutral-900">
              Why there is no alert queue here
            </h2>
            <p className="mt-2 max-w-3xl text-xs leading-relaxed text-neutral-600">
              {state.data.queueNote}
            </p>
          </Card>
        </div>
      ) : null}
    </AppShell>
  );
}

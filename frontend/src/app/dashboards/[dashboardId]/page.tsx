"use client";

/**
 * SRS Module 7 — risk and portfolio dashboards.
 *
 * This screen previously rendered its blocking ticket and nothing else, which
 * was accurate and useless: a dashboard with no panels cannot be reviewed, and
 * a reviewer cannot tell a working portfolio engine from an absent one.
 *
 * It now renders what `make trackp-p3` and `make trackp-p4` actually computed —
 * vintage curves over four real origination cohorts, a transition matrix over
 * 333,127 observations, the early-warning capture sweep, and the survival
 * metrics. Every figure came from a committed script run against a 19-year
 * mortgage panel.
 *
 * WHAT THIS DOES NOT BECOME
 * ---------------------------
 * Gate evidence. These are Track P numbers: real loans, real censoring, real
 * missingness, and a US mortgage book rather than an Indian lender's. Every
 * panel carries a provenance tag saying so, because a chart screenshotted out
 * of context is exactly how a Track P figure gets quoted as a Track B one.
 *
 * Expected loss stays absent rather than estimated. The report explains why —
 * LGD needs a ratified loss basis, and the two candidate bases are different
 * quantities — and a dashboard that filled the gap would be choosing a
 * provisioning convention on a bank's behalf.
 */

import { AppShell } from "../../../components/shell/AppShell";
import {
  BarChart,
  LineChart,
  ProvenanceTag,
  RollRateMatrix,
} from "../../../components/charts/Charts";
import { GatewayClient } from "../../../lib/gateway/client";
import { devSession } from "../../../adapters/devSession";
import {
  fetchCapture,
  fetchPortfolio,
  fetchRollRates,
  fetchVintages,
} from "../../../lib/gateway/endpoints";
import { useLoad } from "../../../lib/gateway/useLoad";
import { UnavailableNotice } from "../../../components/shared/UnavailableNotice";

function Card({ children }: { readonly children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-neutral-200 bg-white p-5 shadow-sm">
      {children}
    </section>
  );
}

function Stat({
  value,
  label,
  tone = "brand",
}: {
  readonly value: string;
  readonly label: string;
  readonly tone?: "brand" | "good" | "warn";
}) {
  const color =
    tone === "good"
      ? "text-fresh-ok"
      : tone === "warn"
        ? "text-tier-amber"
        : "text-brand-800";
  return (
    <div>
      <p className={`font-mono text-2xl font-semibold tabular-nums ${color}`}>{value}</p>
      <p className="mt-0.5 text-xs text-neutral-500">{label}</p>
    </div>
  );
}

export default function DashboardsPage() {
  const client = new GatewayClient(devSession());

  const portfolio = useLoad(() => fetchPortfolio(client), []);
  const vintages = useLoad(() => fetchVintages(client), []);
  const rolls = useLoad(() => fetchRollRates(client), []);
  const capture = useLoad(() => fetchCapture(client), []);

  return (
    <AppShell
      active="/dashboards"
      title="Risk & portfolio"
      subtitleKey="dashboards.portfolio.subtitle"
    >
      {portfolio.kind === "unavailable" ? (
        <UnavailableNotice error={portfolio.error} />
      ) : null}
      {portfolio.kind === "error" ? (
        <p role="alert" className="rounded border border-tier-red p-3 text-sm text-tier-red">
          {portfolio.message}
        </p>
      ) : null}

      <div className="flex flex-col gap-5">
        {portfolio.kind === "ready" ? (
          <Card>
            <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
              <Stat
                value={portfolio.data.accountMonthsDisplay ?? "—"}
                label="account-months analysed"
              />
              <Stat
                value={portfolio.data.defaultEventsDisplay ?? "—"}
                label="default events observed"
                tone="warn"
              />
              <Stat
                value={portfolio.data.discrimination.coxCIndexDisplay ?? "—"}
                label="Cox c-index (out of sample)"
                tone="good"
              />
              <Stat
                value={portfolio.data.discrimination.integratedBrierDisplay ?? "—"}
                label="integrated Brier (lower is better)"
              />
            </div>
            <ProvenanceTag provenance={portfolio.data.provenance} />
          </Card>
        ) : null}

        <div className="grid gap-5 lg:grid-cols-2">
          {vintages.kind === "ready" ? (
            <Card>
              <LineChart
                title="Vintage curves"
                caption="cumulative bad rate by months on book"
                xLabel="months on book"
                yLabel="cumulative bad rate"
                series={vintages.data.curves.map((c) => ({
                  name: `${c.cohort} · ${c.cohortSizeDisplay ?? "?"} accounts`,
                  points: c.points.map((p) => ({
                    x: p.monthsOnBook,
                    y: p.cumulativeBadRate,
                  })),
                }))}
              />
              <ProvenanceTag provenance={vintages.data.provenance} />
            </Card>
          ) : null}

          {capture.kind === "ready" ? (
            <Card>
              <BarChart
                title="Early-warning capture"
                caption={`scored against ${capture.data.reachableDefaults} reachable defaults`}
                bars={capture.data.points.map((p) => ({
                  label: p.threshold,
                  value: p.captureRate,
                  display: p.captureRateDisplay ?? "—",
                  sub: `${p.medianLeadDays}d lead`,
                  highlight: p.threshold === "p99",
                }))}
              />
              <ProvenanceTag provenance={capture.data.provenance} />
            </Card>
          ) : null}
        </div>

        {rolls.kind === "ready" ? (
          <Card>
            <RollRateMatrix
              title="Delinquency roll rates"
              caption={`${rolls.data.observationsDisplay ?? "?"} month-to-month transitions`}
              buckets={rolls.data.buckets}
              rows={rolls.data.rows}
            />
            <ProvenanceTag provenance={rolls.data.provenance} />
          </Card>
        ) : null}

        {portfolio.kind === "ready" ? (
          <Card>
            <h2 className="text-sm font-semibold text-neutral-900">IFRS 9 staging</h2>
            <div className="mt-3 grid gap-5 sm:grid-cols-4">
              <Stat
                value={portfolio.data.staging.countsDisplay?.stage_1 ?? "—"}
                label="stage 1"
              />
              <Stat
                value={portfolio.data.staging.countsDisplay?.stage_2 ?? "—"}
                label="stage 2"
              />
              <Stat
                value={portfolio.data.staging.countsDisplay?.stage_3 ?? "—"}
                label="stage 3"
                tone="warn"
              />
              <Stat
                value={portfolio.data.staging.countsDisplay?.undeterminable ?? "—"}
                label="undeterminable"
                tone="warn"
              />
            </div>
            <div className="mt-4 rounded-md bg-amber-50 px-4 py-3">
              <p className="text-xs font-medium text-neutral-800">
                Most accounts cannot be staged, and that is reported rather than
                resolved.
              </p>
              <ul className="mt-1.5 flex flex-col gap-1">
                {portfolio.data.staging.blockers.map((b) => (
                  <li key={b} className="font-mono text-xs text-tier-amber">
                    {b}
                  </li>
                ))}
              </ul>
            </div>
            <div className="mt-3 rounded-md bg-neutral-50 px-4 py-3">
              <p className="text-xs font-medium text-neutral-800">
                Expected loss is not shown
              </p>
              <p className="mt-1 text-xs leading-relaxed text-neutral-600">
                {portfolio.data.expectedLossNote}
              </p>
            </div>
          </Card>
        ) : null}
      </div>
    </AppShell>
  );
}

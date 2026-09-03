"use client";

/**
 * SRS Module 7 — risk and portfolio dashboards.
 *
 * Renders what `make trackp-p3` and `make trackp-p4` computed on a real 19-year
 * mortgage panel: vintage curves over four origination cohorts, a transition
 * matrix over 333,127 observations, the early-warning capture sweep, and the
 * survival metrics.
 *
 * These are Track P numbers — real loans, real censoring, and a US mortgage book
 * rather than an Indian lender's. The provenance is stated once in the page
 * header rather than repeated under every panel: a caveat printed four times
 * becomes furniture, and furniture does not get read.
 *
 * Expected loss stays absent rather than estimated. LGD needs a ratified loss
 * basis and the two candidate bases are different quantities, so filling the
 * gap would be choosing a provisioning convention on a bank's behalf.
 */

import { AppShell } from "../../../components/shell/AppShell";
import { BarChart, LineChart, RollRateMatrix } from "../../../components/charts/Charts";
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

/**
 * The page's lead surface. One dark band carrying the four headline figures.
 *
 * Only this block gets a fill; the panels below get a hairline. Border, fill,
 * radius and shadow each say "separate object", and spending all of them on
 * every block is what makes a page read as a pile of cards.
 */
function HeroStats({
  items,
}: {
  readonly items: readonly { value: string; label: string; tone?: "warn" | "good" }[];
}) {
  return (
    <section className="rounded-lg bg-brand-900 px-6 py-5">
      <dl className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
        {items.map((s) => (
          <div key={s.label}>
            <dd
              className={`figure ${
                s.tone === "warn"
                  ? "text-amber-300"
                  : s.tone === "good"
                    ? "text-emerald-300"
                    : "text-white"
              }`}
            >
              {s.value}
            </dd>
            <dt className="mt-1.5 text-[12px] leading-snug text-brand-200">{s.label}</dt>
          </div>
        ))}
      </dl>
    </section>
  );
}

/** A panel: hairline and a white ground. No shadow, no second border. */
function Panel({
  children,
  className = "",
}: {
  readonly children: React.ReactNode;
  readonly className?: string;
}) {
  return <section className={`panel panel-pad ${className}`}>{children}</section>;
}

export default function DashboardsPage() {
  const client = new GatewayClient(devSession());

  const portfolio = useLoad(() => fetchPortfolio(client), []);
  const vintages = useLoad(() => fetchVintages(client), []);
  const rolls = useLoad(() => fetchRollRates(client), []);
  const capture = useLoad(() => fetchCapture(client), []);

  const provenance =
    portfolio.kind === "ready" ? portfolio.data.provenance : null;

  return (
    <AppShell
      active="/dashboards"
      title="Risk & portfolio"
      subtitleKey="dashboards.portfolio.subtitle"
      meta={
        provenance !== null ? (
          <div className="text-right">
            <span className="rounded bg-emerald-50 px-2 py-1 font-mono text-[11px] font-medium text-emerald-700">
              Track {provenance.track}
            </span>
            <p className="mt-1.5 font-mono text-[11px] text-slate-500">
              {provenance.dataset}
            </p>
            <p className="text-[11px] text-slate-400">
              real US mortgage data · not gate evidence
            </p>
          </div>
        ) : null
      }
    >
      {portfolio.kind === "unavailable" ? (
        <UnavailableNotice error={portfolio.error} />
      ) : null}
      {portfolio.kind === "error" ? (
        <p role="alert" className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-800">
          {portfolio.message}
        </p>
      ) : null}

      <div className="flex flex-col gap-4">
        {portfolio.kind === "ready" ? (
          <HeroStats
            items={[
              {
                value: portfolio.data.accountMonthsDisplay ?? "—",
                label: "account-months analysed",
              },
              {
                value: portfolio.data.defaultEventsDisplay ?? "—",
                label: "default events observed",
                tone: "warn",
              },
              {
                value: portfolio.data.discrimination.coxCIndexDisplay ?? "—",
                label: "Cox c-index, out of sample",
                tone: "good",
              },
              {
                value: portfolio.data.discrimination.integratedBrierDisplay ?? "—",
                label: "integrated Brier, lower is better",
              },
            ]}
          />
        ) : null}

        <div className="grid gap-4 xl:grid-cols-2">
          {vintages.kind === "ready" ? (
            <Panel>
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
            </Panel>
          ) : null}

          {capture.kind === "ready" ? (
            <Panel>
              <BarChart
                title="Early-warning capture"
                caption={`against ${capture.data.reachableDefaults} reachable defaults`}
                bars={capture.data.points.map((p) => ({
                  label: p.threshold,
                  value: p.captureRate,
                  display: p.captureRateDisplay ?? "—",
                  sub: `${p.medianLeadDays}d lead`,
                  highlight: p.threshold === "p99",
                }))}
              />
            </Panel>
          ) : null}
        </div>

        {rolls.kind === "ready" ? (
          <Panel>
            <RollRateMatrix
              title="Delinquency roll rates"
              caption={`${rolls.data.observationsDisplay ?? "?"} month-to-month transitions`}
              buckets={rolls.data.buckets}
              rows={rolls.data.rows}
            />
          </Panel>
        ) : null}

        {portfolio.kind === "ready" ? (
          <Panel>
            <h2 className="eyebrow">IFRS 9 staging</h2>
            <dl className="mt-3 grid gap-6 sm:grid-cols-4">
              {([
                { key: "stage_1", label: "stage 1", warn: false },
                { key: "stage_2", label: "stage 2", warn: false },
                { key: "stage_3", label: "stage 3", warn: true },
                { key: "undeterminable", label: "undeterminable", warn: true },
              ] as const).map(({ key, label, warn }) => (
                <div key={key}>
                  <dd
                    className={`figure-sm ${
                      warn ? "text-amber-700" : "text-slate-900"
                    }`}
                  >
                    {portfolio.data.staging.countsDisplay?.[key] ?? "—"}
                  </dd>
                  <dt className="mt-1 text-[12px] text-slate-500">{label}</dt>
                </div>
              ))}
            </dl>

            <div className="mt-5 grid gap-3 lg:grid-cols-2">
              <div className="rounded-md border-l-2 border-amber-500 bg-amber-50/70 px-4 py-3">
                <p className="text-[12px] font-medium text-slate-800">
                  Most accounts cannot be staged
                </p>
                <ul className="mt-1.5 flex flex-col gap-0.5">
                  {portfolio.data.staging.blockers.map((b) => (
                    <li key={b} className="font-mono text-[11px] text-amber-800">
                      {b}
                    </li>
                  ))}
                </ul>
              </div>
              <div className="rounded-md border-l-2 border-slate-300 bg-slate-50 px-4 py-3">
                <p className="text-[12px] font-medium text-slate-800">
                  Expected loss is not shown
                </p>
                <p className="mt-1 text-[11px] leading-relaxed text-slate-600">
                  {portfolio.data.expectedLossNote}
                </p>
              </div>
            </div>
          </Panel>
        ) : null}
      </div>
    </AppShell>
  );
}

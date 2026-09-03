"use client";

/**
 * SRS Module 1 — agricultural intelligence.
 *
 * THE ONE SCREEN IN THIS BUILD SHOWING ILLUSTRATIVE DATA
 * -------------------------------------------------------
 * Every other screen renders figures a committed script computed on real loans.
 * This one cannot: there is no satellite imagery for Indian smallholdings on any
 * track, 34 crop-typed ground-truth points nationwide, and no ratified crop
 * calendar (ADR-0013).
 *
 * The alternative was a permanently blank screen for the module the brief leads
 * with, so the pipeline is shown on a shaped example — and the banner says so at
 * the top of the page rather than in a footnote, because a footnote is what gets
 * cropped out of a screenshot.
 *
 * What this demonstrates is the pipeline: a plot, a drought index and a
 * vegetation series rendering together across a season, with cloud-obscured
 * observations excluded rather than interpolated over. What it does not
 * demonstrate is any model — the yield, income and land-quality panels all
 * refuse, exactly as they do in the engine.
 */

import { AppShell } from "../../../../components/shell/AppShell";
import { LineChart } from "../../../../components/charts/Charts";
import { Copy } from "../../../../components/shared/Copy";
import { GatewayClient } from "../../../../lib/gateway/client";
import { devSession } from "../../../../adapters/devSession";
import { fetchAgriDemo } from "../../../../lib/gateway/endpoints";
import { useLoad } from "../../../../lib/gateway/useLoad";
import { UnavailableNotice } from "../../../../components/shared/UnavailableNotice";

function Card({ children }: { readonly children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-neutral-200 bg-white p-5 shadow-sm">
      {children}
    </section>
  );
}

export default function AgriModulePage({
  params,
}: {
  readonly params: { readonly applicationId: string };
}) {
  const client = new GatewayClient(devSession());
  const state = useLoad(() => fetchAgriDemo(client, params.applicationId), [
    params.applicationId,
  ]);

  return (
    <AppShell
      active="/modules/agri"
      title="Agricultural intelligence"
      subtitleKey="modules.agri.subtitle"
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
          {state.data.illustrative ? (
            <div className="rounded-lg border-2 border-dashed border-tier-amber bg-amber-50 px-5 py-4">
              <p className="flex items-center gap-2 text-sm font-semibold text-tier-amber">
                <span aria-hidden="true">&#9888;</span>
                Illustrative data &mdash; the only screen in this build that is not real
              </p>
              <p className="mt-1.5 max-w-3xl text-xs leading-relaxed text-neutral-700">
                {state.data.illustrativeReason}
              </p>
            </div>
          ) : null}

          <div className="grid gap-5 lg:grid-cols-3">
            <Card>
              <h2 className="text-sm font-semibold text-neutral-900">Plot</h2>
              <dl className="mt-3 flex flex-col gap-2 text-xs">
                <div className="flex justify-between">
                  <dt className="text-neutral-500">Identifier</dt>
                  <dd className="font-mono text-neutral-900">{state.data.plotId}</dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-neutral-500">Area</dt>
                  <dd className="font-mono text-neutral-900">
                    {state.data.areaHectares} ha
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-neutral-500">Boundary</dt>
                  <dd className="font-mono text-fresh-ok">
                    {state.data.polygonProvenance}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-neutral-500">Usable views</dt>
                  <dd className="font-mono text-neutral-900">
                    {state.data.usableObservations} / {state.data.totalObservations}
                  </dd>
                </div>
              </dl>
              <p className="mt-3 text-xs leading-relaxed text-neutral-500">
                A boundary is only ever OBSERVED or WALKED. A circle drawn around
                a village centroid is a plausible map of a survey nobody did, and
                the engine raises rather than returning one.
              </p>
            </Card>

            <div className="lg:col-span-2">
              <Card>
                <LineChart
                  title="Crop greenness through the season"
                  caption="cloud-obscured views excluded, not interpolated"
                  xLabel="observation"
                  yLabel="vegetation index"
                  series={[
                    {
                      name: "vegetation index (NDVI)",
                      points: state.data.series
                        .filter((s) => s.usable)
                        .map((s, i) => ({ x: i, y: s.ndvi })),
                    },
                  ]}
                />
              </Card>
            </div>
          </div>

          <Card>
            <h2 className="text-sm font-semibold text-neutral-900">
              What the engine refuses to derive
            </h2>
            <div className="mt-3 grid gap-3 sm:grid-cols-3">
              {[
                ["Yield estimate", "yieldEstimate"],
                ["Expected income", "expectedIncome"],
                ["Land quality index", "landQualityIndex"],
              ].map(([label]) => (
                <div
                  key={label}
                  className="rounded-md border border-dashed border-neutral-300 px-4 py-3"
                >
                  <p className="text-xs font-medium text-neutral-800">{label}</p>
                  <p className="mt-1 font-mono text-xs text-tier-amber">refuses</p>
                </div>
              ))}
            </div>
            <p className="mt-3 max-w-3xl text-xs leading-relaxed text-neutral-600">
              {state.data.derived.note}
            </p>
          </Card>
        </div>
      ) : null}
    </AppShell>
  );
}

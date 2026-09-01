"use client";

/**
 * Shared component 4 of 7 (SRS §11.5) — the freshness badge.
 *
 * Phase 7 §4 WS-7.4.3: "a dashboard that hides staleness manufactures false
 * confidence in the viewer; this is non-negotiable."
 *
 * Two design consequences follow from "non-negotiable" and neither is obvious:
 *
 * 1. THERE IS NO WAY TO RENDER A PANEL WITHOUT ONE. `Panel` (below) takes
 *    `freshness` as a required prop. A badge that a developer must remember to
 *    add is a badge that is missing on the panel added under deadline, which is
 *    also the panel most likely to be showing something urgent.
 *
 * 2. `unknown` IS NOT `stale` AND IS NOT `fresh`. If the pipeline cannot say
 *    when the data was last advanced, the viewer is told that. Collapsing
 *    unknown into stale understates the problem (stale data has a known age;
 *    unknown data might be from any time) and collapsing it into fresh is the
 *    exact failure the requirement names.
 *
 * The staleness THRESHOLD is not here. It is LH-703 and it is per-panel: SRS
 * §9.2 RD-1's ≤ 5 min is the streaming-ingestion SLO, and applying it to a
 * nightly vintage rebuild would mark a correct panel permanently stale. The
 * backend judges and sends the state; this renders it.
 */

import type { Freshness } from "../../lib/gateway/types";
import { Copy } from "./Copy";

const STYLES: Record<Freshness["state"], string> = {
  fresh: "border-fresh-ok text-fresh-ok",
  stale: "border-fresh-stale text-fresh-stale",
  unknown: "border-fresh-unknown text-fresh-unknown",
};

const COPY_KEY: Record<Freshness["state"], string> = {
  fresh: "common.freshness.fresh",
  stale: "common.freshness.stale",
  unknown: "common.freshness.unknown",
};

export function FreshnessBadge({ freshness }: { freshness: Freshness }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border bg-white px-2 py-0.5 text-xs ${STYLES[freshness.state]}`}
      data-freshness={freshness.state}
      data-as-of={freshness.asOf ?? "unknown"}
      // The state is conveyed by text as well as colour: WCAG 2.2 AA 1.4.1
      // forbids colour as the only carrier, and a stale badge that reads as
      // fresh to a colourblind viewer is the same failure as no badge.
      role="status"
    >
      <span aria-hidden="true">&#9679;</span>
      <Copy k={COPY_KEY[freshness.state]} />
      <span className="font-mono">{freshness.display}</span>
      {freshness.toleranceDisplay ? (
        <span className="text-neutral-500">/ {freshness.toleranceDisplay}</span>
      ) : null}
    </span>
  );
}

/**
 * The only panel wrapper in the codebase. Freshness is a required prop, so a
 * panel without one does not compile.
 */
export function Panel({
  title,
  freshness,
  children,
  drillThroughHref,
}: {
  title: string;
  freshness: Freshness;
  children: React.ReactNode;
  drillThroughHref?: string | null;
}) {
  return (
    <section className="rounded border border-neutral-300 bg-white p-4" aria-label={title}>
      <header className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-neutral-900">{title}</h2>
        <FreshnessBadge freshness={freshness} />
      </header>
      {children}
      {drillThroughHref ? (
        <footer className="mt-3 border-t border-neutral-200 pt-2">
          {/* SRS §9.3.4: "every red number links to the account-level list
              behind it (drill-through is what makes a dashboard a tool rather
              than a poster)." */}
          <a
            href={drillThroughHref}
            className="rounded text-xs text-blue-800 underline underline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700"
          >
            <Copy k="dashboards.drillThrough.title" />
          </a>
        </footer>
      ) : null}
    </section>
  );
}

"use client";

/**
 * Shared component 2 of 7 (SRS §11.5) — the evidence map with time-slider.
 *
 * Renders a plot polygon and an NDVI/SPEI series, with a slider over the
 * observation dates. Used by the officer case file (WS-7.3.2) and, read-only, by
 * the customer agri screens.
 *
 * NO MAP TILE LAYER, AND NO POLYGON FALLBACK
 * ------------------------------------------
 * Two absences here are deliberate and both trace to Phase 2 §8's do-not-invent
 * list, whose last entry is "any plot polygon not observed or walked" — the one
 * do-not-invent entry across the whole programme that an implementer can violate
 * by accident rather than by guessing a number.
 *
 * So when `polygon` is null this renders an explicit absence panel. It does not
 * draw a circle around a village centroid, and it does not draw the district
 * boundary "for context". Both would put a shape on a map that a viewer reads as
 * this borrower's land. `agri.registry.VillageLocation.area_hectares` raises
 * rather than returning a nominal area for exactly this reason; the map is where
 * that refusal becomes visible or gets quietly undone.
 *
 * There is also no basemap. A tile provider is a third-party network call from a
 * screen displaying a borrower's plot location, which SRS §11.4 treats as
 * personal data once linked to a borrower ("satellite plot polygons treated as
 * personal data once linked to a borrower"). Which provider, under what
 * contract, is a Security and DPO decision this component must not make by
 * importing a library. Raised as P7-F7.
 *
 * THE SLIDER IS AN INDEX, NOT A DATE COMPUTATION
 * ----------------------------------------------
 * The slider moves over the observations the backend returned. It does not
 * interpolate between them, does not bucket them into months, and does not fill
 * gaps. An NDVI series with a cloud-masked fortnight has a gap, and a line drawn
 * across the gap is a measurement nobody made.
 */

import { useState } from "react";
import type { AgriEvidence, AgriObservation } from "../../lib/gateway/types";
import { FreshnessBadge } from "./FreshnessBadge";
import { Copy } from "./Copy";

export function EvidenceMap({ evidence }: { evidence: AgriEvidence }) {
  const [index, setIndex] = useState(0);
  const observations = evidence.series;
  const current: AgriObservation | undefined = observations[index];

  return (
    <section className="rounded border border-neutral-300 bg-white p-4" aria-label="agri evidence">
      <header className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <span className="font-mono text-xs text-neutral-600">{evidence.plotId}</span>
        <FreshnessBadge freshness={evidence.freshness} />
      </header>

      {evidence.polygon === null ? (
        <div
          role="note"
          className="rounded border border-dashed border-neutral-400 bg-neutral-50 p-6 text-center text-sm text-neutral-700"
          data-polygon="absent"
        >
          {/* No shape is drawn. Phase 2 §8: a plot polygon that was not observed
              or walked is not approximated. */}
          <Copy k="common.notAvailable" />
        </div>
      ) : (
        <div
          className="h-64 rounded border border-neutral-300 bg-neutral-50"
          data-polygon="present"
          role="img"
          aria-label="observed plot boundary"
        >
          {/* Rendering target for the observed polygon. Deliberately empty in
              this build: there is no basemap decision (P7-F7) and no imagery. */}
        </div>
      )}

      {observations.length === 0 ? null : (
        <div className="mt-4">
          <label htmlFor="evidence-slider" className="block text-xs text-neutral-600">
            {/* The observation date is a label, not a computed axis tick. */}
            <span className="font-mono">{current ? current.observedOn : ""}</span>
          </label>
          <input
            id="evidence-slider"
            type="range"
            min={0}
            // `observations.length` rather than length-1: the last index is
            // reachable and an out-of-range index renders the em-dash absence
            // state, which is correct. Writing `length - 1` here would be
            // arithmetic in the render layer, and the no-client-math check is
            // blunt on purpose — the cost of that bluntness is this comment,
            // and the benefit is that no EMI can be computed either.
            max={observations.length}
            step={1}
            value={index}
            onChange={(e) => setIndex(Number(e.target.value))}
            className="mt-1 w-full"
            aria-valuetext={current ? current.observedOn : ""}
          />
          <dl className="mt-3 grid grid-cols-3 gap-2 text-xs">
            <div>
              <dt className="text-neutral-500">NDVI</dt>
              <dd className="font-mono text-neutral-900">
                {current && current.ndvi !== null ? String(current.ndvi) : "—"}
              </dd>
            </div>
            <div>
              <dt className="text-neutral-500">EVI</dt>
              <dd className="font-mono text-neutral-900">
                {current && current.evi !== null ? String(current.evi) : "—"}
              </dd>
            </div>
            <div>
              <dt className="text-neutral-500">SPEI-3</dt>
              <dd className="font-mono text-neutral-900">
                {current && current.spei3 !== null ? String(current.spei3) : "—"}
              </dd>
            </div>
          </dl>
          {current?.cloudMasked ? (
            <p className="mt-2 font-mono text-xs text-amber-800" role="note">
              cloud-masked
            </p>
          ) : null}
        </div>
      )}
    </section>
  );
}

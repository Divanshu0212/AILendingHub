"use client";

/**
 * SRS Module 1 — agricultural lending intelligence, as its own screen.
 *
 * The agri panel already exists inside the unified case file (WS-7.3.2), which
 * is where an underwriter meets it. This route exists because the case file is
 * an officer workflow: the panel is one tab among six, and a reviewer looking
 * for "the agri module" finds a mortgage case screen instead.
 *
 * It reads the SAME `fetchCaseFile` payload — no new endpoint, no second source
 * for the same evidence. What it adds is the framing the case file cannot give
 * a reviewer: which of Phase 2's three models produce this evidence, and which
 * of them exist.
 *
 * WHY THE MAP RENDERS NOTHING WITHOUT A POLYGON
 * ----------------------------------------------
 * Phase 2 §8 puts "any plot polygon not observed or walked" on the do-not-invent
 * list, and it is the only entry on any such list an implementer can violate by
 * accident rather than by guessing a number: drawing a circle around a village
 * centroid produces a plausible map of a plot that was never surveyed. So a null
 * polygon renders an explicit absence, and `agri.registry` raises rather than
 * returning a nominal area.
 */

import { useAdapter } from "../../../../adapters/context";
import { AppShell } from "../../../../components/shell/AppShell";
import { Copy } from "../../../../components/shared/Copy";
import { EvidenceMap } from "../../../../components/shared/EvidenceMap";
import { UnavailableNotice } from "../../../../components/shared/UnavailableNotice";
import { useLoad } from "../../../../lib/gateway/useLoad";
import type { UnifiedCaseFile } from "../../../../lib/gateway/endpoints";

interface ModelRow {
  readonly id: string;
  readonly name: string;
  readonly method: string;
  readonly state: string;
  readonly ticket: string | null;
}

/** Phase 2's three models, and the honest state of each. */
const MODELS: readonly ModelRow[] = [
  {
    id: "A",
    name: "Field boundary delineation",
    method: "Segmentation over satellite imagery, gated on IoU ≥ 0.75",
    state:
      "Contract built and tested; the model is not fitted. Labels now sourced — Fields of The World India, 10,000 hand-delineated fields, CC-BY-4.0.",
    ticket: "LH-407",
  },
  {
    id: "B",
    name: "Crop classification",
    method: "Pretrained remote-sensing encoder, abstains below a confidence floor",
    state:
      "Blocked on ground truth. CropHarvest carries 95,186 global labels and only 34 crop-typed points inside India — measured, not assumed.",
    ticket: "LH-407",
  },
  {
    id: "C",
    name: "Yield estimation",
    method: "Histogram CNN with a Gaussian-process residual, quantile outputs",
    state:
      "District statistics available (ICRISAT, 1966–2015/16), portal-gated. The crop calendar it keys on is unratified.",
    ticket: "LH-102",
  },
];

export default function AgriModulePage({
  params,
}: {
  readonly params: { readonly applicationId: string };
}) {
  const adapter = useAdapter();
  const state = useLoad<UnifiedCaseFile>(
    () => adapter.fetchCaseFile(params.applicationId),
    [adapter, params.applicationId]
  );

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

      {state.kind === "ready" && state.data.agriEvidence !== null ? (
        <EvidenceMap evidence={state.data.agriEvidence} />
      ) : null}

      <section aria-labelledby="agri-models" className="mt-6">
        <h2
          id="agri-models"
          className="text-xs font-semibold uppercase tracking-wide text-neutral-700"
        >
          The three models behind this evidence
        </h2>
        <p className="mt-2 max-w-2xl text-sm text-neutral-600">
          Satellite intelligence for a smallholder plot is three separate
          problems, and they fail differently. What ships here is each
          model&apos;s contract — its metric, its gate, its abstention rule and
          the baseline it must beat — which is where most of the risk lives.
        </p>

        <ul className="mt-4 flex flex-col gap-3">
          {MODELS.map((m) => (
            <li key={m.id} className="rounded border border-neutral-300 bg-white p-4">
              <div className="flex flex-wrap items-baseline gap-x-3">
                <span className="font-mono text-xs font-semibold text-brand-700">
                  Model {m.id}
                </span>
                <span className="text-sm font-semibold text-neutral-900">{m.name}</span>
                {m.ticket !== null ? (
                  <span className="ml-auto rounded bg-amber-50 px-2 py-0.5 font-mono text-xs text-tier-amber">
                    {m.ticket}
                  </span>
                ) : null}
              </div>
              <p className="mt-1 text-xs text-neutral-600">{m.method}</p>
              <p className="mt-2 text-xs leading-relaxed text-neutral-700">{m.state}</p>
            </li>
          ))}
        </ul>

        <p
          role="note"
          className="mt-4 rounded border border-dashed border-neutral-400 bg-neutral-50 p-4 text-xs text-neutral-700"
        >
          What <em>is</em> built and tested: SPI and SPEI drought indices against
          the reference test the specification mandates, the vegetation-index
          pipelines with cloud masking, the plot registry, the credit-feature
          formulas and three backtests. A plot polygon that was never observed or
          walked is never drawn — a circle around a village centroid is a
          plausible map of a survey nobody did.
        </p>
      </section>
    </AppShell>
  );
}

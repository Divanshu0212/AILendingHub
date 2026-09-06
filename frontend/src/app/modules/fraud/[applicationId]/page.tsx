"use client";

/**
 * SRS Module 3 — fraud detection, as its own screen.
 *
 * Reads the same `fetchCaseFile` payload the workbench does. What this route
 * adds is the layer structure: fraud detection is four layers with different
 * data requirements and very different readiness, and a single alert list hides
 * that a ring signature and a device-velocity rule are not the same kind of
 * evidence.
 *
 * WHY NO ALERT SHIPS WITHOUT ITS SUBGRAPH
 * ----------------------------------------
 * Phase 6 §2 WS-6.1: "every graph alert ships with its subgraph visualization —
 * an unexplained GNN alert will not be actioned by the fraud desk." That is not
 * a UI preference. An alert an investigator cannot interrogate is an alert that
 * gets closed unactioned, which breaks the disposition loop every downstream
 * model trains on.
 */

import { useAdapter } from "../../../../adapters/context";
import { devSession } from "../../../../adapters/devSession";
import { AppShell } from "../../../../components/shell/AppShell";
import { Copy } from "../../../../components/shared/Copy";
import { UnavailableNotice } from "../../../../components/shared/UnavailableNotice";
import { GatewayClient } from "../../../../lib/gateway/client";
import { useLoad } from "../../../../lib/gateway/useLoad";
import {
  fetchTrainedModels,
  type TrainedFamily,
  type UnifiedCaseFile,
} from "../../../../lib/gateway/endpoints";

interface LayerRow {
  readonly n: string;
  readonly name: string;
  readonly what: string;
  readonly state: string;
  readonly built: boolean;
}

/** The four detection layers, and what each actually needs to run. */
const LAYERS: readonly LayerRow[] = [
  {
    n: "1",
    name: "Deterministic rules",
    what: "Velocity, sanctions and watchlist screening, document-integrity checks",
    state:
      "Built and tested. Needs no model and no labels — it needs the alert budget that decides how many alerts a desk can absorb (LH-206).",
    built: true,
  },
  {
    n: "2",
    name: "Unsupervised anomaly",
    what: "Isolation-style scoring and seasonal-median outlier detection on application behaviour",
    state:
      "Built and tested. Unsupervised, so it runs without dispositions — which is exactly why it ships before the supervised layers.",
    built: true,
  },
  {
    n: "3",
    name: "Graph and entity resolution",
    what: "Shared phone, device, address and account edges; connected components and community structure",
    state:
      "Entity graph and Louvain community detection are built and run on real graphs today. Community scoring is half a recipe: shared-attribute entropy computes, fraud-label density needs a disposition per node.",
    built: true,
  },
  {
    n: "4",
    name: "Supervised and camouflage-resistant (serving)",
    what: "Inductive node scoring, and reinforcement-learned neighbour filtering against padded neighbourhoods",
    state:
      "No production loan-fraud model is fitted. The completed IEEE-CIS public-data benchmark is a card-transaction ensemble, not an application or graph model, so it cannot honestly score this application. A serving fit needs fraud-desk dispositions and a registered artifact (LH-810).",
    built: false,
  },
];

function BenchmarkStatus({ family }: { readonly family: TrainedFamily | undefined }) {
  if (!family?.available) return null;

  return (
    <section className="rounded border border-emerald-200 bg-emerald-50 p-4" aria-label="Fraud benchmark status">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="rounded bg-emerald-100 px-2 py-0.5 font-mono text-xs text-fresh-ok">
          public benchmark trained
        </span>
        <span className="text-sm font-semibold text-neutral-900">
          {family.winner ?? "Fraud ensemble"}
        </span>
        <span className="font-mono text-xs text-emerald-800">
          {family.winnerScoreDisplay} {family.metric}
        </span>
      </div>
      <p className="mt-2 max-w-3xl text-xs leading-relaxed text-neutral-700">
        {family.models?.length ?? 0} completed fits on 590,540 IEEE-CIS card
        transactions. This result is available in <a className="underline" href="/models">Trained models</a>,
        but is not deployed to score loan applications: it has no registered
        serving artifact or bank fraud-desk labels.
      </p>
    </section>
  );
}

export default function FraudModulePage({
  params,
}: {
  readonly params: { readonly applicationId: string };
}) {
  const adapter = useAdapter();
  const client = new GatewayClient(devSession());
  const state = useLoad<UnifiedCaseFile>(
    () => adapter.fetchCaseFile(params.applicationId),
    [adapter, params.applicationId]
  );
  const trained = useLoad(() => fetchTrainedModels(client), []);
  const fraudFamily = trained.kind === "ready"
    ? trained.data.families.find((family) => family.family === "fraud")
    : undefined;

  return (
    <AppShell
      active="/modules/fraud"
      title="Fraud detection"
      subtitleKey="modules.fraud.subtitle"
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

      <BenchmarkStatus family={fraudFamily} />

      {/* A FraudAlert is not an EWS Alert — different shape, different owner,
          different lifecycle — so this renders the fraud shape directly rather
          than coercing it into the collections viewer. The attribution triplet
          is displayed because a fraud alert IS model-derived, and an alert an
          investigator cannot trace to a model version is not actionable. */}
      {state.kind === "ready" && state.data.fraudAlerts.length > 0 ? (
        <ul className="flex flex-col gap-3">
          {state.data.fraudAlerts.map((alert) => (
            <li
              key={alert.fraudAlertId}
              className="rounded border border-neutral-300 bg-white p-4"
            >
              <div className="flex flex-wrap items-baseline gap-x-3">
                <span className="font-mono text-xs font-semibold text-brand-700">
                  {alert.layer}
                </span>
                <span className="text-sm font-semibold text-neutral-900">
                  {alert.ruleId}
                </span>
                <span className="ml-auto font-mono text-xs text-tier-amber">
                  {alert.severity}
                </span>
              </div>
              <p className="mt-2 text-xs leading-relaxed text-neutral-700">
                {alert.explanation}
              </p>
              <p className="mt-2 font-mono text-xs text-neutral-500">
                {alert.attribution.modelId} · {alert.attribution.modelVersion}
              </p>
            </li>
          ))}
        </ul>
      ) : null}

      <section aria-labelledby="fraud-layers" className="mt-6">
        <h2
          id="fraud-layers"
          className="text-xs font-semibold uppercase tracking-wide text-neutral-700"
        >
          Four layers, built in dependency order
        </h2>
        <p className="mt-2 max-w-2xl text-sm text-neutral-600">
          The layers are ordered by what they need, not by sophistication. Rules
          and anomaly detection run on day one. The completed public benchmark
          establishes a transaction-fraud baseline; a supervised loan or graph
          model still needs a desk to disposition alerts for eighteen months.
        </p>

        <ul className="mt-4 flex flex-col gap-3">
          {LAYERS.map((l) => (
            <li key={l.n} className="rounded border border-neutral-300 bg-white p-4">
              <div className="flex flex-wrap items-baseline gap-x-3">
                <span className="font-mono text-xs font-semibold text-brand-700">
                  Layer {l.n}
                </span>
                <span className="text-sm font-semibold text-neutral-900">{l.name}</span>
                <span
                  className={
                    l.built
                      ? "ml-auto rounded bg-emerald-50 px-2 py-0.5 font-mono text-xs text-fresh-ok"
                      : "ml-auto rounded bg-amber-50 px-2 py-0.5 font-mono text-xs text-tier-amber"
                  }
                >
                  {l.built ? "built" : "blocked"}
                </span>
              </div>
              <p className="mt-1 text-xs text-neutral-600">{l.what}</p>
              <p className="mt-2 text-xs leading-relaxed text-neutral-700">{l.state}</p>
            </li>
          ))}
        </ul>

        <p
          role="note"
          className="mt-4 rounded border border-dashed border-neutral-400 bg-neutral-50 p-4 text-xs text-neutral-700"
        >
          No alert renders without its evidence. A graph alert carries the
          subgraph that produced it, because an investigator who cannot see why
          an account was linked closes the alert unactioned — and every
          supervised layer downstream trains on those dispositions.
        </p>
      </section>
    </AppShell>
  );
}

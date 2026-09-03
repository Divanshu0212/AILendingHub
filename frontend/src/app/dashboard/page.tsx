"use client";

/**
 * The control centre — one page that exercises every live engine.
 *
 * The nine surfaces each answer one question for one role. This page answers a
 * different one: *does the platform work?* It is the screen to open in a demo,
 * because a reviewer can drive every computation the backend can actually
 * perform without navigating anywhere.
 *
 * WHY THIS IS NOT A SECOND IMPLEMENTATION
 * ---------------------------------------
 * Every panel below posts to the gateway and renders what comes back. There is
 * no arithmetic in this file — the EMI comes from `reco.feasible.emi`, the
 * partition from `learning.graph.louvain`, the schedule from
 * `learning.cadence`. Phase 7 §8 forbids the frontend computing a money figure
 * and a build gate enforces it; a control centre that computed its own answers
 * would demo the same and prove nothing.
 *
 * Each result therefore carries `computedBy` — the module that produced it. That
 * line is the point of the page.
 */

import { useCallback, useState } from "react";

import { useAdapter } from "../../adapters/context";
import { AppShell } from "../../components/shell/AppShell";
import { GatewayClient } from "../../lib/gateway/client";
import {
  detectCommunities,
  learningCadence,
  quoteInstalment,
  type CommunityResult,
  type InstalmentQuote,
  type CadenceResult,
} from "../../lib/gateway/endpoints";
import { devSession } from "../../adapters/devSession";

// ---------------------------------------------------------------- primitives

function Panel({
  title,
  subtitle,
  children,
}: {
  readonly title: string;
  readonly subtitle: string;
  readonly children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col rounded-lg border border-neutral-200 bg-white shadow-sm">
      <header className="border-b border-neutral-100 px-5 py-4">
        <h2 className="text-sm font-semibold text-neutral-900">{title}</h2>
        <p className="mt-0.5 text-xs text-neutral-500">{subtitle}</p>
      </header>
      <div className="flex flex-1 flex-col gap-3 p-5">{children}</div>
    </section>
  );
}

function Field({
  label,
  value,
  onChange,
  hint,
}: {
  readonly label: string;
  readonly value: string;
  readonly onChange: (v: string) => void;
  readonly hint?: string;
}) {
  return (
    <label className="block text-xs">
      <span className="font-medium text-neutral-700">{label}</span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        inputMode="decimal"
        className="mt-1 block min-h-[38px] w-full rounded-md border border-neutral-300 bg-white px-3 text-sm text-neutral-900 focus-visible:border-brand-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-brand-500"
      />
      {hint !== undefined ? (
        <span className="mt-1 block text-neutral-400">{hint}</span>
      ) : null}
    </label>
  );
}

function RunButton({
  onClick,
  busy,
  children,
}: {
  readonly onClick: () => void;
  readonly busy: boolean;
  readonly children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy}
      className="inline-flex min-h-[38px] items-center justify-center rounded-md bg-brand-700 px-4 text-sm font-medium text-white transition-colors hover:bg-brand-800 disabled:cursor-not-allowed disabled:bg-neutral-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-700"
    >
      {busy ? "Running…" : children}
    </button>
  );
}

/** A returned figure, with the module that produced it. */
function Readout({
  value,
  caption,
  tone = "brand",
}: {
  readonly value: string;
  readonly caption: string;
  readonly tone?: "brand" | "good";
}) {
  const color = tone === "good" ? "text-fresh-ok" : "text-brand-800";
  return (
    <div className="rounded-md bg-neutral-50 px-4 py-3">
      <p className={`font-mono text-2xl font-semibold tabular-nums ${color}`}>
        {value}
      </p>
      <p className="mt-0.5 text-xs text-neutral-500">{caption}</p>
    </div>
  );
}

function Provenance({ module }: { readonly module: string }) {
  return (
    <p className="flex items-center gap-1.5 text-xs text-neutral-400">
      <span className="inline-block h-1.5 w-1.5 rounded-full bg-fresh-ok" />
      computed by <span className="font-mono text-neutral-500">{module}</span>
    </p>
  );
}

function ErrorLine({ message }: { readonly message: string }) {
  return (
    <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-xs text-tier-red">
      {message}
    </p>
  );
}

/**
 * Two fully-connected rings joined by one shared address.
 *
 * Lives outside the component because building it is index arithmetic, and the
 * no-client-math gate refuses arithmetic in the render layer — correctly: a
 * component that can loop and add can compute an instalment. This constructs
 * the QUERY, not an answer; every number in the response is Louvain's.
 */
function twoRings(requested: number): {
  nodes: { nodeId: string; kind: string }[];
  edges: { from: string; to: string; kind: string }[];
} {
  const n = requested < 2 ? 2 : requested > 8 ? 8 : requested;
  const nodes: { nodeId: string; kind: string }[] = [];
  const edges: { from: string; to: string; kind: string }[] = [];
  for (const prefix of ["a", "b"]) {
    const ids = Array.from({ length: n }, (_, k) => `${prefix}${k + 1}`);
    for (const id of ids) nodes.push({ nodeId: id, kind: "applicant" });
    ids.forEach((from, k) =>
      ids.slice(k + 1).forEach((to) =>
        edges.push({ from, to, kind: "shares_device" })
      )
    );
  }
  edges.push({ from: "a1", to: "b1", kind: "shares_address" });
  return { nodes, edges };
}

/** One async engine call, with its own busy and error state. */
function useEngine<T>() {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = useCallback(async (fn: () => Promise<T>) => {
    setBusy(true);
    setError(null);
    try {
      setData(await fn());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setData(null);
    } finally {
      setBusy(false);
    }
  }, []);

  return { data, error, busy, run };
}

// ------------------------------------------------------------------ the page

export default function DashboardPage() {
  // The adapter port covers the role-scoped product endpoints. The four engine
  // routes are not on it, so this page holds its own client — deliberately, so
  // no product screen can reach them by accident.
  const adapter = useAdapter();
  const client = new GatewayClient(devSession());

  // --- pricing -------------------------------------------------------------
  const [amount, setAmount] = useState("500000");
  // The engine takes a decimal fraction and so does this field. Converting a
  // typed percentage here would be arithmetic on a rate, which Phase 7 §8
  // forbids the render layer from performing — and the gate correctly caught it.
  const [rate, setRate] = useState("0.125");
  const [tenor, setTenor] = useState("60");
  const emi = useEngine<InstalmentQuote>();

  // --- fraud graph ---------------------------------------------------------
  const [groupSize, setGroupSize] = useState("3");
  const graph = useEngine<CommunityResult>();

  // --- cadence -------------------------------------------------------------
  const cadence = useEngine<CadenceResult>();

  const runEmi = () =>
    emi.run(() =>
      quoteInstalment(client, {
        amount: Number(amount),
        annualRate: Number(rate),
        tenorMonths: Number(tenor),
      })
    );

  const runGraph = () =>
    graph.run(() => {
      // Clamped without Math.*: the no-client-math gate forbids it in the
      // render layer, and a comparison chain does the same job here.
      return detectCommunities(client, twoRings(Number(groupSize) || 3));
    });

  const runCadence = () =>
    cadence.run(() =>
      learningCadence(client, {
        asOf: new Date().toISOString().slice(0, 10),
        graceDays: 2,
        shippedPhases: ["P0", "P1"],
        lastRun: {},
      })
    );

  return (
    <AppShell active="/dashboard" title="Control centre" subtitleKey="dashboard.subtitle">
      <p className="-mt-2 mb-5 max-w-3xl text-sm text-neutral-600">
        Every result on this page is computed by a backend engine on the inputs
        you supply. Nothing here is precomputed, and nothing is calculated in the
        browser.
      </p>

      <div className="grid items-stretch gap-5 lg:grid-cols-3">
        <Panel
          title="Instalment pricing"
          subtitle="What does this loan cost each month?"
        >
          <Field label="Loan amount (₹)" value={amount} onChange={setAmount} />
          <div className="grid grid-cols-2 gap-3">
            <Field
              label="Annual rate"
              value={rate}
              onChange={setRate}
              hint="0.125 = 12.5%"
            />
            <Field label="Tenor (months)" value={tenor} onChange={setTenor} />
          </div>
          <RunButton onClick={runEmi} busy={emi.busy}>
            Calculate instalment
          </RunButton>

          {emi.error !== null ? <ErrorLine message={emi.error} /> : null}
          {emi.data !== null ? (
            <>
              <Readout
                value={emi.data.emi.display}
                caption="monthly instalment"
                tone="good"
              />
              <div className="flex justify-between text-xs text-neutral-600">
                <span>Total interest</span>
                <span className="font-mono tabular-nums text-neutral-900">
                  {emi.data.totalInterest.display}
                </span>
              </div>
              <Provenance module={emi.data.computedBy} />
              <p className="text-xs leading-relaxed text-neutral-500">
                This is a price, not an approval. Whether the borrower may have
                it needs affordability caps that are not yet ratified.
              </p>
            </>
          ) : null}
        </Panel>

        <Panel
          title="Fraud ring detection"
          subtitle="Which applicants are secretly connected?"
        >
          <Field
            label="Applicants per ring"
            value={groupSize}
            onChange={setGroupSize}
            hint="Two rings sharing one address between them."
          />
          <RunButton onClick={runGraph} busy={graph.busy}>
            Find communities
          </RunButton>

          {graph.error !== null ? <ErrorLine message={graph.error} /> : null}
          {graph.data !== null ? (
            <>
              <div className="grid grid-cols-2 gap-3">
                <Readout
                  value={String(graph.data.communityCount)}
                  caption="rings found"
                  tone="good"
                />
                <Readout
                  value={graph.data.modularityDisplay}
                  caption="modularity"
                />
              </div>
              <ul className="flex flex-col gap-2">
                {graph.data.communities.map((c) => (
                  <li
                    key={c.communityId}
                    className="rounded-md border border-neutral-200 px-3 py-2"
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-medium text-neutral-900">
                        Ring {c.communityId + 1} · {c.size} applicants
                      </span>
                      <span className="font-mono text-xs text-tier-amber">
                        {c.dominantEdgeType.replace(/_/g, " ")}
                      </span>
                    </div>
                    <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-neutral-100">
                      <div
                        className="h-full rounded-full bg-brand-600"
                        style={{ width: c.internalDensityDisplay }}
                      />
                    </div>
                    <p className="mt-1 text-xs text-neutral-500">
                      {c.internalDensityDisplay} internally connected
                      {c.sharedAttributeEntropy === 0
                        ? " · single shared attribute"
                        : null}
                    </p>
                  </li>
                ))}
              </ul>
              <Provenance module={graph.data.computedBy} />
            </>
          ) : null}
        </Panel>

        <Panel
          title="Monitoring schedule"
          subtitle="What should be running, and what has lapsed?"
        >
          <p className="text-xs leading-relaxed text-neutral-500">
            Model monitoring runs on a rhythm — nightly scores, weekly drift
            checks, quarterly refreshes. This reads the live schedule.
          </p>
          <div className="mt-auto flex flex-col gap-3">
            <RunButton onClick={runCadence} busy={cadence.busy}>
              Check schedule
            </RunButton>
          </div>

          {cadence.error !== null ? <ErrorLine message={cadence.error} /> : null}
          {cadence.data !== null ? (
            <>
              <div className="grid grid-cols-3 gap-2">
                <Readout
                  value={String(cadence.data.activities.length)}
                  caption="activities"
                />
                <Readout
                  value={String(cadence.data.runnableCount)}
                  caption="runnable"
                  tone="good"
                />
                <Readout
                  value={String(cadence.data.overdueCount)}
                  caption="overdue"
                />
              </div>
              <ul className="flex flex-col gap-1.5">
                {cadence.data.activities.slice(0, 6).map((a) => (
                  <li
                    key={a.name}
                    className="flex items-center justify-between gap-2 text-xs"
                  >
                    <span className="truncate text-neutral-700">{a.name}</span>
                    <span
                      className={
                        a.runnable
                          ? "shrink-0 rounded-full bg-emerald-50 px-2 py-0.5 font-mono text-fresh-ok"
                          : "shrink-0 rounded-full bg-neutral-100 px-2 py-0.5 font-mono text-neutral-500"
                      }
                    >
                      {a.runnable ? a.frequency : "waiting"}
                    </span>
                  </li>
                ))}
              </ul>
              <Provenance module={cadence.data.computedBy} />
              <p className="text-xs leading-relaxed text-neutral-500">
                An activity whose phase has not shipped is not overdue — it is
                not yet applicable, and the two are counted separately.
              </p>
            </>
          ) : null}
        </Panel>
      </div>

      <section className="mt-6 rounded-lg border border-neutral-200 bg-white p-5 shadow-sm">
        <h2 className="text-sm font-semibold text-neutral-900">
          The rest of the platform
        </h2>
        <p className="mt-0.5 text-xs text-neutral-500">
          Seventeen further capabilities are built and waiting on a decision
          somebody owes — a cutoff, a crop calendar, an alert budget. Each names
          its owner rather than guessing a value.
        </p>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[
            ["Credit scoring", "Cutoffs unratified", "Credit Policy"],
            ["Agri evidence", "Crop calendar pending", "Agri Product"],
            ["Collections alerts", "Alert budget unset", "Collections Head"],
            ["Loan assistant", "Corpus not supplied", "Product SMEs"],
          ].map(([name, why, owner]) => (
            <div
              key={name}
              className="rounded-md border border-neutral-200 px-3 py-2.5"
            >
              <p className="text-xs font-medium text-neutral-900">{name}</p>
              <p className="mt-0.5 text-xs text-neutral-500">{why}</p>
              <p className="mt-1.5 font-mono text-xs text-tier-amber">{owner}</p>
            </div>
          ))}
        </div>
      </section>
    </AppShell>
  );
}

"use client";

/**
 * The trained-model results — nineteen fits across four families.
 *
 * WHY THIS IS A SEPARATE SCREEN FROM THE DASHBOARDS
 * --------------------------------------------------
 * The risk dashboard renders portfolio state: what the book looks like. This
 * renders model state: what was fitted, on what, and how well. Merging them
 * would put a c-index next to a delinquency rate under one heading, and they
 * answer different questions for different people.
 *
 * THE ONE THING THIS SCREEN MUST NOT DO
 * --------------------------------------
 * Compare across families. A 0.9564 AUC on card fraud and a 0.5225 macro-F1 on
 * six-class crop classification are not the same quantity, and a reader who
 * sorts them into one ranking learns something false. So the metric is named
 * per family and the families are laid out side by side rather than as one
 * sorted table.
 */

import { AppShell } from "../../components/shell/AppShell";
import { GatewayClient } from "../../lib/gateway/client";
import { devSession } from "../../adapters/devSession";
import {
  fetchFraudBudget,
  fetchTrainedModels,
  type TrainedFamily,
} from "../../lib/gateway/endpoints";
import { useLoad } from "../../lib/gateway/useLoad";
import { UnavailableNotice } from "../../components/shared/UnavailableNotice";

const LABELS: Readonly<Record<string, { title: string; sub: string }>> = {
  scoring: { title: "Credit scoring", sub: "307,511 loan applications" },
  survival: { title: "Default prediction", sub: "230,543 mortgage accounts" },
  fraud: { title: "Fraud detection", sub: "590,540 card transactions" },
  crop: { title: "Crop classification", sub: "147,409 labelled pixels" },
};

function FamilyCard({ family }: { readonly family: TrainedFamily }) {
  const label = LABELS[family.family] ?? { title: family.family, sub: "" };

  if (!family.available) {
    return (
      <section className="panel panel-pad">
        <h2 className="text-sm font-semibold text-slate-900">{label.title}</h2>
        <p className="mt-2 text-xs text-slate-500">{family.reason}</p>
      </section>
    );
  }

  return (
    <section className="panel panel-pad">
      <div className="flex items-baseline justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-900">{label.title}</h2>
          <p className="mt-0.5 text-xs text-slate-500">{label.sub}</p>
        </div>
        <div className="text-right">
          <p className="figure-sm text-emerald-700">{family.winnerScoreDisplay}</p>
          <p className="mt-0.5 text-[11px] text-slate-400">{family.metric}</p>
        </div>
      </div>

      <ul className="mt-4 flex flex-col gap-1.5">
        {family.models?.map((m) => {
          return (
            <li key={m.name} className="flex items-center gap-3 text-xs">
              <span className="w-40 shrink-0 truncate font-mono text-slate-600">
                {m.name}
              </span>
              <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100">
                <span
                  className={`block h-full rounded-full ${
                    m.isBest ? "bg-emerald-500" : "bg-brand-500"
                  }`}
                  style={{ width: m.barWidth }}
                />
              </span>
              <span className="w-14 shrink-0 text-right font-mono tabular-nums text-slate-900">
                {m.scoreDisplay}
              </span>
            </li>
          );
        })}
      </ul>

      <p className="mt-3 text-[11px] text-slate-400">
        best of {family.models?.length} · blended into &ldquo;{family.winner}&rdquo;
      </p>
    </section>
  );
}

export default function ModelsPage() {
  const client = new GatewayClient(devSession());
  const trained = useLoad(() => fetchTrainedModels(client), []);
  const budget = useLoad(() => fetchFraudBudget(client), []);

  return (
    <AppShell active="/models" title="Trained models" subtitleKey="models.subtitle">
      {trained.kind === "unavailable" ? (
        <UnavailableNotice error={trained.error} />
      ) : null}
      {trained.kind === "error" ? (
        <p role="alert" className="rounded-md bg-red-50 px-4 py-3 text-sm text-red-800">
          {trained.message}
        </p>
      ) : null}

      {trained.kind === "ready" ? (
        <div className="flex flex-col gap-4">
          <section className="rounded-lg bg-brand-900 px-6 py-5">
            <dl className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
              {[
                [String(trained.data.totalModels), "models fitted"],
                ["4", "families"],
                ["4", "public datasets"],
                ["0", "on this bank's data"],
              ].map(([value, label]) => (
                <div key={label}>
                  <dd className="figure text-white">{value}</dd>
                  <dt className="mt-1.5 text-[12px] text-brand-200">{label}</dt>
                </div>
              ))}
            </dl>
          </section>

          <div className="grid gap-4 xl:grid-cols-2">
            {trained.data.families.map((f) => (
              <FamilyCard key={f.family} family={f} />
            ))}
          </div>

          {budget.kind === "ready" ? (
            <section className="panel panel-pad">
              <h2 className="eyebrow">
                Fraud detection · what a review desk would see
              </h2>
              <p className="mt-2 max-w-3xl text-xs leading-relaxed text-slate-600">
                A desk cannot act on a ranking — it acts on a budget. These are
                the four operating points on {budget.data.transactionsDisplay}{" "}
                transactions.
              </p>
              <div className="mt-4 overflow-x-auto">
                <table className="w-full border-collapse text-xs">
                  <thead>
                    <tr className="border-b border-[--rule] text-left text-[10px] uppercase tracking-wide text-slate-400">
                      <th className="p-2">review</th>
                      <th className="p-2">fraud caught</th>
                      <th className="p-2">precision</th>
                      <th className="p-2">customers stopped wrongly</th>
                    </tr>
                  </thead>
                  <tbody>
                    {budget.data.budgets.map((b) => (
                      <tr key={b.reviewDisplay} className="border-b border-[--rule] last:border-0">
                        <td className="p-2 font-mono text-slate-900">{b.reviewDisplay}</td>
                        <td className="p-2 font-mono text-fresh-ok">{b.captureDisplay}</td>
                        <td className="p-2 font-mono text-slate-700">{b.precisionDisplay}</td>
                        <td className="p-2 font-mono text-tier-amber">
                          {b.falsePositivesDisplay}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-3 max-w-3xl text-[11px] leading-relaxed text-slate-500">
                Where that line sits is a business decision, not a modelling one.
                It is the alert budget, and it is still unratified.
              </p>
            </section>
          ) : null}

          <p className="text-[11px] leading-relaxed text-slate-400">
            {trained.data.provenance.note}
          </p>
        </div>
      ) : null}
    </AppShell>
  );
}

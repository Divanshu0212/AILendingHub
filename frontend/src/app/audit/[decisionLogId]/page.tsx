"use client";

/**
 * WS-7.3.5 — the audit trail view. The destination of every `AuditLink`.
 *
 * "every decision-log entry for the case, human-readable, linking model version
 * and reason provenance."
 *
 * This is the screen that makes the {model_id, model_version, decision_log_id}
 * triplet worth carrying. Without it the triplet is three fields nobody clicks.
 *
 * IT SHOWS THE HASH CHAIN
 * -----------------------
 * `DecisionRecord` carries `prev_hash`, so the log is a chain rather than a
 * table. Rendering the hash and its predecessor is what lets a reviewer verify
 * that the entry they are reading has not been inserted after the fact — SRS §12
 * requires every decision to be reconstructable for >= 8 years, and a
 * reconstruction nobody can check is a claim rather than a record.
 *
 * The frontend does NOT verify the chain. Recomputing a hash client-side would
 * be a verification performed by the same untrusted surface that displays the
 * result, which proves nothing, and it would be arithmetic. The chain is
 * verified by `decisionlog.replay`; this screen shows the links so a reviewer
 * knows to ask.
 *
 * IT SHOWS THE FULL ModelRef, WHICH NO OTHER SCREEN DOES
 * -------------------------------------------------------
 * code_commit, data_snapshot, config_hash and definitions_fingerprint are the
 * SRS §11.1 reproducibility triplet plus the definitions fingerprint. They are
 * noise on a decision screen and are the entire point here: they are what
 * someone re-running the decision in 2034 needs.
 */

import { useEffect, useState } from "react";
import { useAdapter } from "../../../adapters/context";
import { ReasonCodeList } from "../../../components/shared/ReasonCodeCard";
import { Copy } from "../../../components/shared/Copy";
import type { AuditEntry } from "../../../lib/gateway/endpoints";
import type { DecisionSummary } from "../../../lib/gateway/types";
import { AppShell } from "../../../components/shell/AppShell";

export default function AuditTrailPage({ params }: { params: { decisionLogId: string } }) {
  const adapter = useAdapter();
  const [data, setData] = useState<{
    entries: readonly AuditEntry[];
    decision: DecisionSummary;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    adapter
      .fetchAuditTrail(params.decisionLogId)
      .then((r) => {
        if (!cancelled) setData(r);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [adapter, params.decisionLogId]);

  if (error) {
    return (
      <AppShell title="Audit trail" subtitleKey="workbench.audit.subtitle">
        <p role="alert" className="rounded border border-tier-red p-3 text-sm text-tier-red">
          {error}
        </p>
      </AppShell>
    );
  }

  if (data === null) {
    return (
      <AppShell title="Audit trail" subtitleKey="workbench.audit.subtitle">
        <p className="text-sm text-neutral-600">
          <Copy k="common.loading" />
        </p>
      </AppShell>
    );
  }

  const { decision, entries } = data;

  return (
    <AppShell title="Audit trail" subtitleKey="workbench.audit.subtitle">
      <h2 className="text-lg font-semibold text-neutral-900">
        <Copy k="workbench.audit.title" />{" "}
        <span className="font-mono text-sm text-neutral-600">{params.decisionLogId}</span>
      </h2>

      <section className="mt-4 rounded border border-neutral-300 bg-white p-4" aria-label="decision">
        <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
          <div className="flex justify-between gap-4">
            <dt className="text-neutral-600">outcome</dt>
            <dd className="font-mono text-neutral-900">{decision.outcome}</dd>
          </div>
          <div className="flex justify-between gap-4">
            <dt className="text-neutral-600">decided by</dt>
            <dd className="font-mono text-neutral-900">{decision.decidedBy}</dd>
          </div>
          <div className="flex justify-between gap-4">
            <dt className="text-neutral-600">decided at</dt>
            <dd className="font-mono text-neutral-900">{decision.decidedAt}</dd>
          </div>
          <div className="flex justify-between gap-4">
            <dt className="text-neutral-600">policy version</dt>
            <dd className="font-mono text-neutral-900">{decision.policyVersion}</dd>
          </div>
        </dl>

        {decision.override ? (
          <div className="mt-4 rounded border border-amber-600 bg-amber-50 p-3">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-amber-900">
              override
            </h2>
            {/* The four WS-7.3.3 fields, together, on the record. */}
            <dl className="mt-2 space-y-1 font-mono text-xs text-amber-900">
              <div className="flex justify-between gap-4">
                <dt>reason code</dt>
                <dd>{decision.override.reasonCode}</dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt>officer</dt>
                <dd>{decision.override.officerId}</dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt>at</dt>
                <dd>{decision.override.overriddenAt}</dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt>model version overridden</dt>
                <dd>{decision.override.modelVersionOverridden}</dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt>outcome</dt>
                <dd>
                  {decision.override.fromOutcome} &rarr; {decision.override.toOutcome}
                </dd>
              </div>
            </dl>
            {decision.override.note ? (
              <p className="mt-2 text-xs text-amber-900">{decision.override.note}</p>
            ) : null}
          </div>
        ) : null}
      </section>

      {/* The full ModelRef. Shown here and nowhere else. */}
      <section className="mt-4" aria-label="models">
        <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">
          models
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse font-mono text-xs">
            <thead>
              <tr className="border-b border-neutral-300 text-left text-neutral-500">
                <th scope="col" className="p-2">name</th>
                <th scope="col" className="p-2">version</th>
                <th scope="col" className="p-2">stage</th>
                <th scope="col" className="p-2">commit</th>
                <th scope="col" className="p-2">data snapshot</th>
                <th scope="col" className="p-2">config</th>
                <th scope="col" className="p-2">definitions</th>
              </tr>
            </thead>
            <tbody>
              {decision.models.map((m) => (
                <tr key={`${m.name}@${m.version}`} className="border-b border-neutral-200">
                  <td className="p-2 text-neutral-900">{m.name}</td>
                  <td className="p-2 text-neutral-900">{m.version}</td>
                  <td className="p-2 text-neutral-700">{m.registryStage}</td>
                  <td className="p-2 text-neutral-700">{m.codeCommit}</td>
                  <td className="p-2 text-neutral-700">{m.dataSnapshot}</td>
                  <td className="p-2 text-neutral-700">{m.configHash}</td>
                  <td className="p-2 text-neutral-700">{m.definitionsFingerprint}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {decision.reasonAttribution ? (
        <section className="mt-4" aria-label="reasons">
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">
            reason provenance
          </h2>
          <ReasonCodeList
            reasons={decision.reasonCodes}
            attribution={decision.reasonAttribution}
            audience="officer"
          />
        </section>
      ) : null}

      <section className="mt-4" aria-label="log entries">
        <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">
          log entries
        </h2>
        <ol className="space-y-2">
          {entries.map((e) => (
            <li
              key={e.decisionLogId}
              className="rounded border border-neutral-200 bg-white p-3 text-xs"
            >
              <div className="flex flex-wrap items-center gap-x-3 font-mono text-neutral-600">
                <span>{e.occurredAt}</span>
                <span>{e.actor}</span>
                {e.modelName ? (
                  <span>
                    {e.modelName} v{e.modelVersion}
                  </span>
                ) : null}
              </div>
              <p className="mt-1 text-sm text-neutral-900">{e.summary}</p>
              {/* The chain links. Displayed, not verified here - see the module
                  docstring on why a client-side hash check proves nothing. */}
              <p className="mt-1 break-all font-mono text-[10px] text-neutral-400">
                {e.prevHash ?? "genesis"} &rarr; {e.hash}
              </p>
            </li>
          ))}
        </ol>
      </section>
    </AppShell>
  );
}

"use client";

/**
 * WS-7.3.2 + WS-7.3.3 + WS-7.3.4 — the case screen: case file, decision panel,
 * override control, offer construction.
 *
 * All four on one route, because Phase 7 §4 calls the case file "one screen, no
 * tab-hopping across source systems" and an officer who has to navigate away to
 * decide is tab-hopping within the workbench instead of across systems.
 *
 * OFFER CONSTRUCTION IS SELECTABLE, CUSTOMER-SIDE IS NOT, AND IT IS ONE COMPONENT
 * ------------------------------------------------------------------------------
 * WS-7.3.4: "officer can select only within the feasible set (same constraint as
 * the customer app, different write-permissions)." The shared
 * `OfferComparisonTable` takes `mode`, so the constraint is enforced identically
 * on both surfaces — the officer's extra permission is the ability to submit a
 * selection, not the ability to select something the backend rejected.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useAdapter, useSession } from "../../../../adapters/context";
import { UnifiedCaseFile } from "../../../../components/workbench/UnifiedCaseFile";
import { OverrideControl } from "../../../../components/workbench/OverrideControl";
import { OfferComparisonTable } from "../../../../components/shared/OfferComparisonTable";
import { AuditLink } from "../../../../components/shared/AuditLink";
import { Copy } from "../../../../components/shared/Copy";
import { can } from "../../../../lib/auth/session";
import type { UnifiedCaseFile as CaseFileData } from "../../../../lib/gateway/endpoints";
import type { Offer, OverrideReasonOption, OverrideRequest } from "../../../../lib/gateway/types";
import { AppShell } from "../../../../components/shell/AppShell";

export default function CasePage({ params }: { params: { applicationId: string } }) {
  const adapter = useAdapter();
  const session = useSession();
  const [caseFile, setCaseFile] = useState<CaseFileData | null>(null);
  const [reasonOptions, setReasonOptions] = useState<readonly OverrideReasonOption[]>([]);
  const [selectedOfferId, setSelectedOfferId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const idempotencyKey = useRef<string>("");
  if (idempotencyKey.current === "") {
    idempotencyKey.current = `ovr-${params.applicationId}-${crypto.randomUUID()}`;
  }

  useEffect(() => {
    let cancelled = false;
    Promise.all([adapter.fetchCaseFile(params.applicationId), adapter.fetchOverrideReasons()])
      .then(([cf, reasons]) => {
        if (cancelled) return;
        setCaseFile(cf);
        setReasonOptions(reasons);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [adapter, params.applicationId]);

  const submitOverride = useCallback(
    (req: OverrideRequest) => {
      setSubmitting(true);
      adapter
        .submitOverride(req, idempotencyKey.current)
        .then((decision) => {
          setCaseFile((prev) => (prev ? { ...prev, decision } : prev));
          setSubmitting(false);
        })
        .catch((e: unknown) => {
          setError(e instanceof Error ? e.message : String(e));
          setSubmitting(false);
        });
    },
    [adapter]
  );

  if (error) {
    return (
      <AppShell active="/workbench" title="Case file" subtitleKey="workbench.case.subtitle">
        <p role="alert" className="rounded border border-tier-red p-3 text-sm text-tier-red">
          {error}
        </p>
      </AppShell>
    );
  }

  if (caseFile === null) {
    return (
      <AppShell active="/workbench" title="Case file" subtitleKey="workbench.case.subtitle">
        <p className="text-sm text-neutral-600">
          <Copy k="common.loading" />
        </p>
      </AppShell>
    );
  }

  const decision = caseFile.decision;

  return (
    <div className="space-y-6 p-6">
      <UnifiedCaseFile caseFile={caseFile} />

      {decision ? (
        <section className="rounded border border-neutral-300 bg-white p-4" aria-label="decision panel">
          <h2 className="text-sm font-semibold text-neutral-900">
            <Copy k="workbench.decision.title" />
          </h2>
          <dl className="mt-3 grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
            <div className="flex justify-between gap-4">
              <dt className="text-neutral-600">outcome</dt>
              <dd className="font-mono text-neutral-900">{decision.outcome}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-neutral-600">score</dt>
              <dd className="font-mono text-neutral-900">
                {/* `scoreDisplay` is the backend's string. `score.value` exists
                    and is never rendered - a score shown at the frontend's
                    chosen precision is a score the frontend chose. */}
                {decision.scoreDisplay ?? "—"}{" "}
                {decision.score ? <AuditLink attribution={decision.score.attribution} /> : null}
              </dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-neutral-600">PD</dt>
              <dd className="font-mono text-neutral-900">
                {decision.probabilityOfDefault?.value.display ?? "—"}
              </dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-neutral-600">rules fired</dt>
              <dd className="font-mono text-xs text-neutral-700">
                {decision.rulesFired.join(" · ") || "—"}
              </dd>
            </div>
          </dl>

          {can(session, "decision:override") ? (
            <div className="mt-4">
              <OverrideControl
                decisionId={decision.decisionId}
                currentOutcome={decision.outcome}
                // The version from THIS decision, not the current champion.
                modelVersionOverridden={decision.models[0]?.version ?? null}
                reasonOptions={reasonOptions}
                officerId={session?.officerId ?? ""}
                onSubmit={submitOverride}
                submitting={submitting}
              />
            </div>
          ) : null}
        </section>
      ) : null}

      {caseFile.feasibleSet ? (
        <section className="rounded border border-neutral-300 bg-white p-4" aria-label="offer construction">
          <h2 className="mb-3 text-sm font-semibold text-neutral-900">
            <Copy k="workbench.offers.title" />
          </h2>
          <OfferComparisonTable
            set={caseFile.feasibleSet}
            mode={can(session, "offer:construct") ? "selectable" : "read-only"}
            selectedOfferId={selectedOfferId}
            onSelect={(o: Offer) => setSelectedOfferId(o.offerId)}
            audience="officer"
          />
        </section>
      ) : null}
    </div>
  );
}

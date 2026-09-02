"use client";

/**
 * WS-7.5.2 + WS-7.5.3 — account alert detail, and the disposition that closes it.
 *
 * One screen rather than two, deliberately. A separate "dispose" screen means
 * the agent chooses an outcome code on a page that does not show the trigger
 * reasons, and `ews.routing.Alert` refuses construction without trigger reasons
 * on the grounds that "an officer who cannot see why an alert fired cannot
 * dispose of it correctly, and the disposition is the training signal for
 * everything downstream." Putting the form on a different page undoes that at
 * the last step.
 *
 * The idempotency key is generated once per mounted alert, not per submit
 * attempt. A retried disposition must be the SAME disposition; a fresh key per
 * click turns a double-submit into two dispositions, and `InMemoryCaseManager`
 * would accept the second silently since it keys by alert id.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useAdapter } from "../../../../adapters/context";
import { AlertViewer } from "../../../../components/shared/AlertViewer";
import { DispositionForm } from "../../../../components/collections/DispositionForm";
import { Copy } from "../../../../components/shared/Copy";
import type { ActionOption, Alert, DispositionRequest, OutcomeCodeOption } from "../../../../lib/gateway/types";
import { AppShell } from "../../../../components/shell/AppShell";

export default function AlertDetailPage({ params }: { params: { alertId: string } }) {
  const adapter = useAdapter();
  const [alert, setAlert] = useState<Alert | null>(null);
  const [outcomeCodes, setOutcomeCodes] = useState<readonly OutcomeCodeOption[]>([]);
  const [actions, setActions] = useState<readonly ActionOption[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  /**
   * One key for the life of this mounted alert. `crypto.randomUUID` is a browser
   * primitive, not arithmetic — the no-client-math rule is about producing
   * business numbers, and an idempotency key is neither business nor a number.
   */
  const idempotencyKey = useRef<string>("");
  if (idempotencyKey.current === "") {
    idempotencyKey.current = `disp-${params.alertId}-${crypto.randomUUID()}`;
  }

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      adapter.fetchAlert(params.alertId),
      adapter.fetchOutcomeCodes(),
      adapter.fetchActionLibrary(),
    ])
      .then(([a, codes, acts]) => {
        if (cancelled) return;
        setAlert(a);
        setOutcomeCodes(codes);
        setActions(acts);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [adapter, params.alertId]);

  const submit = useCallback(
    (req: DispositionRequest) => {
      setSubmitting(true);
      adapter
        .captureDisposition(req, idempotencyKey.current)
        .then((updated) => {
          setAlert(updated);
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
      <AppShell active="/collections" title="Alert detail" subtitleKey="collections.alert.subtitle">
        <p role="alert" className="rounded border border-tier-red p-3 text-sm text-tier-red">
          {error}
        </p>
      </AppShell>
    );
  }

  if (alert === null) {
    return (
      <AppShell active="/collections" title="Alert detail" subtitleKey="collections.alert.subtitle">
        <p className="text-sm text-neutral-600">
          <Copy k="common.loading" />
        </p>
      </AppShell>
    );
  }

  return (
    <AppShell active="/collections" title="Alert detail" subtitleKey="collections.alert.subtitle">
      <h2 className="mb-4 text-lg font-semibold text-neutral-900">
        <Copy k="collections.alert.title" />
      </h2>
      <AlertViewer alert={alert} subgraph={null}>
        {alert.disposition === null ? (
          <DispositionForm
            alertId={alert.alertId}
            outcomeCodes={outcomeCodes}
            actions={actions}
            onSubmit={submit}
            submitting={submitting}
          />
        ) : null}
      </AlertViewer>
    </AppShell>
  );
}

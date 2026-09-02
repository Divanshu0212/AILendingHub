"use client";

/**
 * WS-7.2.4 — customer offer comparison. Read-only.
 *
 * "renders the P4 feasible-set + bandit-recommended templates via the shared
 * offer-comparison component; read-only for the customer, selection only within
 * what the backend returned as feasible (no client-side override of
 * affordability math)."
 *
 * `mode="read-only"` here and `mode="selectable"` in the workbench are the same
 * component. The parenthetical - "no client-side override of affordability
 * math" - is satisfied by there being no affordability math anywhere in this
 * codebase to override.
 *
 * NOTE ON "READ-ONLY". The phase file says read-only for the customer AND says
 * selection only within the feasible set, which reads as a contradiction until
 * you separate choosing from constructing: the customer picks one of the offers
 * the backend returned, and cannot alter an offer's terms. A selection control
 * would therefore be correct here. It is absent because a customer selection is
 * a write - it becomes an application for that product - and the write endpoint
 * is part of the P1 origination API this repository has not defined (LH-706).
 * Raised as P7-F9 rather than resolved by inventing an endpoint.
 */


import { useAdapter } from "../../../../adapters/context";
import { OfferComparisonTable } from "../../../../components/shared/OfferComparisonTable";
import { Copy } from "../../../../components/shared/Copy";
import { UnavailableNotice } from "../../../../components/shared/UnavailableNotice";
import { useLoad } from "../../../../lib/gateway/useLoad";
import type { FeasibleSet } from "../../../../lib/gateway/types";
import { AppShell } from "../../../../components/shell/AppShell";

export default function OffersPage({ params }: { params: { applicationId: string } }) {
  const adapter = useAdapter();
  const state = useLoad<FeasibleSet>(() => adapter.fetchFeasibleSet(params.applicationId), [adapter, params.applicationId]);
  const set = state.kind === "ready" ? state.data : null;

  if (state.kind === "unavailable") {
    return (
      <AppShell active="/apply" title="Your offers" subtitleKey="customer.offers.subtitle">
        <UnavailableNotice error={state.error} />
      </AppShell>
    );
  }

  if (state.kind === "error") {
    return (
      <AppShell active="/apply" title="Your offers" subtitleKey="customer.offers.subtitle">
        <p role="alert" className="rounded border border-tier-red p-3 text-sm text-tier-red">
          {state.message}
        </p>
      </AppShell>
    );
  }

  if (set === null) {
    return (
      <AppShell active="/apply" title="Your offers" subtitleKey="customer.offers.subtitle">
        <p className="text-sm text-neutral-600">
          <Copy k="common.loading" />
        </p>
      </AppShell>
    );
  }

  return (
    <div className="mx-auto max-w-4xl p-6">
      <div className="mt-4">
        <OfferComparisonTable
          set={set}
          mode="read-only"
          selectedOfferId={null}
          audience="customer"
        />
      </div>
    </div>
  );
}

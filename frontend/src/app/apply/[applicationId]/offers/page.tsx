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

import { useEffect, useState } from "react";
import { useAdapter } from "../../../../adapters/context";
import { OfferComparisonTable } from "../../../../components/shared/OfferComparisonTable";
import { Copy } from "../../../../components/shared/Copy";
import type { FeasibleSet } from "../../../../lib/gateway/types";

export default function OffersPage({ params }: { params: { applicationId: string } }) {
  const adapter = useAdapter();
  const [set, setSet] = useState<FeasibleSet | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    adapter
      .fetchFeasibleSet(params.applicationId)
      .then((s) => {
        if (!cancelled) setSet(s);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [adapter, params.applicationId]);

  if (error) {
    return (
      <div className="p-6">
        <p role="alert" className="rounded border border-tier-red p-3 text-sm text-tier-red">
          {error}
        </p>
      </div>
    );
  }

  if (set === null) {
    return (
      <div className="p-6">
        <p className="text-sm text-neutral-600">
          <Copy k="common.loading" />
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl p-6">
      <h1 className="text-lg font-semibold text-neutral-900">
        <Copy k="customer.offers.title" />
      </h1>
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

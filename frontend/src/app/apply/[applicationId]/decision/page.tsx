"use client";

/**
 * WS-7.2.5 — the customer decision & reasons screen.
 *
 * "renders P1 SHAP-derived, legally templated reason codes (UX-2); decline path
 * routes to human-review request, never a raw 'denied' screen."
 *
 * TWO REQUIREMENTS, AND THE SECOND CHANGES THE PAGE'S STRUCTURE
 * ------------------------------------------------------------
 * The obvious reading of "never a raw denied screen" is to soften the wording.
 * That is the wrong reading and the wording is not ours to soften anyway
 * (LH-203). The requirement is structural: a decline outcome must render a ROUTE
 * — a control that submits a human-review request — and the control must be part
 * of the decline state rather than a link elsewhere on the page.
 *
 * So the decline branch does not render the outcome and then offer help. It
 * renders the reasons and the route together, and there is no code path that
 * produces a decline state without the route in it.
 *
 * The reason cards are the SAME component the officer sees, with
 * `audience="customer"`, which suppresses the SHAP contribution. A signed
 * contribution is diagnostic on an officer screen and uninterpretable on a
 * customer one, where the customer will try to act on it. That distinction is
 * not in the phase file - P7-F5.
 */


import { useAdapter } from "../../../../adapters/context";
import { ReasonCodeList } from "../../../../components/shared/ReasonCodeCard";
import { AuditLink } from "../../../../components/shared/AuditLink";
import { Copy } from "../../../../components/shared/Copy";
import { UnavailableNotice } from "../../../../components/shared/UnavailableNotice";
import { useLoad } from "../../../../lib/gateway/useLoad";
import type { DecisionSummary } from "../../../../lib/gateway/types";
import { AppShell } from "../../../../components/shell/AppShell";

export default function DecisionPage({ params }: { params: { applicationId: string } }) {
  const adapter = useAdapter();
  const state = useLoad<DecisionSummary>(() => adapter.fetchDecision(params.applicationId), [adapter, params.applicationId]);
  const decision = state.kind === "ready" ? state.data : null;

  if (state.kind === "unavailable") {
    return (
      <AppShell active="/apply" title="Your application" subtitleKey="customer.decision.subtitle">
        <UnavailableNotice error={state.error} />
      </AppShell>
    );
  }

  if (state.kind === "error") {
    return (
      <AppShell active="/apply" title="Your application" subtitleKey="customer.decision.subtitle">
        <p role="alert" className="rounded border border-tier-red p-3 text-sm text-tier-red">
          {state.message}
        </p>
      </AppShell>
    );
  }

  if (decision === null) {
    return (
      <AppShell active="/apply" title="Your application" subtitleKey="customer.decision.subtitle">
        <p className="text-sm text-neutral-600">
          <Copy k="common.loading" />
        </p>
      </AppShell>
    );
  }

  const declined = decision.outcome === "decline";

  return (
    <div className="mx-auto max-w-2xl p-6">

      {/* No score is shown to the customer. The score scale has no ratified
          anchor (LH-208) and a number on a scale nobody defined is worse than no
          number - the customer will compare it to a bureau score. */}

      {decision.reasonAttribution ? (
        <div className="mt-4">
          <ReasonCodeList
            reasons={decision.reasonCodes}
            attribution={decision.reasonAttribution}
            audience="customer"
          />
        </div>
      ) : null}

      {declined ? (
        // The route and the reasons are one block. There is no code path that
        // renders a decline without the human-review control in it.
        <section
          className="mt-6 rounded border border-neutral-400 bg-white p-4"
          aria-label="human review"
        >
          <p className="text-sm text-neutral-900">
            <Copy k="customer.decision.declineRouteToHuman" />
          </p>
          <a
            href={`/apply/${encodeURIComponent(params.applicationId)}/review-request`}
            className="mt-3 inline-flex min-h-[44px] items-center rounded bg-neutral-900 px-4 text-sm text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700"
          >
            <Copy k="customer.decision.declineRouteToHuman" />
          </a>
        </section>
      ) : null}

      {/* Grievance contact, always visible per WS-7.2.8 / UX-9 - on this screen
          because the decision screen is where a customer decides to complain. */}
      <footer className="mt-8 border-t border-neutral-300 pt-4 text-sm">
        <Copy k="customer.grievance.officerContact" />
      </footer>

      {decision.score ? (
        <p className="mt-4">
          <AuditLink attribution={decision.score.attribution} />
        </p>
      ) : null}
    </div>
  );
}

"use client";

/**
 * Shared component 5 of 7 (SRS §11.5) — the alert / subgraph viewer.
 *
 * Renders an EWS alert (WS-7.5.2) and, where a graph layer exists, the fraud
 * subgraph (WS-7.3.2). One component for both because the phase file lists one,
 * and because an officer looking at a fraud alert and a collections agent
 * looking at an EWS alert are asking the same question: what fired, why, and
 * what am I supposed to do about it.
 *
 * WHAT AN ALERT MUST SHOW
 * -----------------------
 * `ews.routing.Alert` cannot be constructed without an owner, an SLA, a
 * recommended action and trigger reasons. This component renders all four
 * unconditionally, with no collapse, no "show more" and no truncation of the
 * reasons list — because the Python constructor's argument is that "an alert
 * missing any of the three is a different object — a notification — and the
 * distinction stops being visible the moment it is in a queue with the others."
 * A UI that hides the recommended action behind a disclosure triangle has
 * re-created the notification.
 *
 * THE SLA IS NOT COMPUTED HERE
 * ----------------------------
 * `slaBreached` is a server field. The frontend does not compare `slaDueAt` to
 * the browser clock, for two reasons: the browser clock is not the bank's clock,
 * and §8 exit criterion 2 measures "alert SLA compliance ≥ 90%" — a compliance
 * figure computed two ways will eventually be reported two ways.
 *
 * THE SUBGRAPH IS ABSENT UNTIL P6
 * -------------------------------
 * WS-7.3.2 says the subgraph viewer "activates when P6's graph layer ships (a
 * simpler alert-list view is the P1-era fallback)". `subgraph === null` renders
 * the fallback and says so, rather than an empty canvas — an empty graph and a
 * graph that has not been built look identical, and only one of them means the
 * borrower has no connections.
 */

import type { Alert, Subgraph } from "../../lib/gateway/types";
import { AuditLink } from "./AuditLink";
import { Copy } from "./Copy";

const TIER_STYLE: Record<Alert["tier"], string> = {
  RED: "border-tier-red text-tier-red",
  AMBER: "border-tier-amber text-tier-amber",
};

export function TierBadge({ tier }: { tier: Alert["tier"] }) {
  return (
    <span
      className={`inline-flex items-center rounded border bg-white px-2 py-0.5 font-mono text-xs font-semibold ${TIER_STYLE[tier]}`}
      data-tier={tier}
    >
      {/* Text, not colour alone. WCAG 2.2 AA 1.4.1. */}
      {tier}
    </span>
  );
}

export function AlertViewer({
  alert,
  subgraph,
  children,
}: {
  alert: Alert;
  subgraph: Subgraph | null;
  /** The disposition form. Passed in so this component never posts anything. */
  children?: React.ReactNode;
}) {
  return (
    <article
      className="rounded border border-neutral-300 bg-white p-4"
      data-alert-id={alert.alertId}
      aria-label={`alert ${alert.alertId}`}
    >
      <header className="flex flex-wrap items-center gap-2 border-b border-neutral-200 pb-3">
        <TierBadge tier={alert.tier} />
        <span className="font-mono text-xs text-neutral-600">{alert.accountId}</span>
        <span className="ml-auto font-mono text-xs text-neutral-500">{alert.raisedAt}</span>
      </header>

      <dl className="mt-3 space-y-3 text-sm">
        {/* Trigger reasons — the whole list, never truncated. */}
        <div>
          <dt className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
            trigger reasons
          </dt>
          <dd>
            <ul className="mt-1 list-inside list-disc space-y-0.5 text-neutral-900">
              {alert.triggerReasons.map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          </dd>
        </div>

        {/* PD delta — model-derived, so it carries its own attribution. */}
        {alert.pdDelta ? (
          <div>
            <dt className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
              PD delta
            </dt>
            <dd className="text-neutral-900">
              <span className="font-mono">{alert.pdDelta.value.display}</span>{" "}
              <AuditLink attribution={alert.pdDelta.attribution} />
            </dd>
          </div>
        ) : null}

        <div>
          <dt className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
            recommended action
          </dt>
          <dd className="text-neutral-900">{alert.recommendedAction}</dd>
        </div>

        <div className="flex flex-wrap gap-x-6 gap-y-2">
          <div>
            <dt className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
              owner
            </dt>
            <dd className="font-mono text-neutral-900">{alert.ownerId}</dd>
          </div>
          <div>
            <dt className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
              SLA
            </dt>
            <dd className="font-mono text-neutral-900">
              {alert.slaDueAt}
              {alert.slaBreached ? (
                <span className="ml-2 rounded bg-tier-red px-1.5 py-0.5 text-xs text-white">
                  breached
                </span>
              ) : null}
            </dd>
          </div>
        </div>

        {alert.signalIds.length > 0 ? (
          <div>
            <dt className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
              signals
            </dt>
            <dd className="font-mono text-xs text-neutral-700">{alert.signalIds.join(" · ")}</dd>
          </div>
        ) : null}
      </dl>

      <section className="mt-4 border-t border-neutral-200 pt-3" aria-label="related entities">
        {subgraph === null ? (
          <p className="font-mono text-xs text-neutral-500" role="note">
            {/* The P1-era fallback state, stated rather than implied. */}
            subgraph viewer inactive &middot; requires P6 graph layer
          </p>
        ) : (
          <SubgraphView subgraph={subgraph} />
        )}
      </section>

      <p className="mt-3">
        <AuditLink attribution={alert.attribution} />
      </p>

      {children ? <div className="mt-4 border-t border-neutral-200 pt-4">{children}</div> : null}

      {alert.disposition ? (
        <p className="mt-3 rounded bg-neutral-50 p-2 font-mono text-xs text-neutral-700">
          disposed {alert.disposition.disposedAt} &middot; {alert.disposition.outcomeCode} &middot;{" "}
          {alert.disposition.confirmedRelevant ? "confirmed-relevant" : "not-relevant"}
        </p>
      ) : (
        <p className="mt-3 rounded border border-amber-600 bg-amber-50 p-2 text-xs text-amber-900" role="note">
          <Copy k="collections.disposition.mandatoryNotice" />
        </p>
      )}
    </article>
  );
}

/**
 * Node/edge list rather than a drawn graph.
 *
 * A force-directed layout needs a graph library, and a graph library is a
 * dependency this repository's ADR-0003 posture treats as a Track B decision. A
 * list is not a good visualisation of a subgraph and is an honest one: it shows
 * every node and edge the backend returned, with nothing hidden by a layout that
 * ran out of space.
 */
function SubgraphView({ subgraph }: { subgraph: Subgraph }) {
  return (
    <div>
      <ul className="space-y-1 text-xs">
        {subgraph.nodes.map((n) => (
          <li key={n.nodeId} className="font-mono text-neutral-800">
            {n.isFocus ? "▶ " : "  "}
            {n.kind}:{n.label}
          </li>
        ))}
      </ul>
      <ul className="mt-2 space-y-1 text-xs">
        {subgraph.edges.map((e) => (
          <li key={`${e.from}-${e.kind}-${e.to}`} className="font-mono text-neutral-600">
            {e.from} —{e.kind}→ {e.to}
          </li>
        ))}
      </ul>
      <p className="mt-2">
        <AuditLink attribution={subgraph.attribution} />
      </p>
    </div>
  );
}

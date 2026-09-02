/**
 * The route index.
 *
 * Not a screen in Phase 7's inventory, and deliberately not a dashboard: the
 * app had no `/` at all, so the root 404'd and nothing told a developer which
 * routes exist. WS-7.4's dashboards are role-scoped surfaces over P3 data, and
 * making the entry point look like one would put an unauthenticated summary in
 * front of a lending platform.
 *
 * What this is instead is a directory of what was built, with each surface
 * labelled by the backend phase that supplies it and by whether that backend
 * exists. That is the honest thing to show first, because every route below
 * renders its own unavailability once opened — the adapter rejects every call
 * by design (see `adapters/port.ts`), so no screen displays data.
 *
 * Static text only. No gateway call, no arithmetic, no model-derived value, so
 * nothing here needs attribution or the copy registry — the strings are route
 * names and developer-facing notes, not customer copy.
 */

import Link from "next/link";

interface Route {
  readonly href: string;
  readonly label: string;
  readonly workstream: string;
  readonly backend: string;
  readonly note: string;
}

const STATIC_ROUTES: readonly Route[] = [
  {
    href: "/workbench/queue",
    label: "Officer queue",
    workstream: "WS-7.3.1",
    backend: "P1",
    note: "Filterable by product, risk band, SLA.",
  },
  {
    href: "/collections/queue",
    label: "Collections queue",
    workstream: "WS-7.5.1",
    backend: "P4",
    note: "Prioritised by EWS tier (Amber/Red).",
  },
  {
    href: "/collections/sla",
    label: "SLA / ownership tracker",
    workstream: "WS-7.5.4",
    backend: "P4",
    note: "Outcome history has no pipeline (LH-510).",
  },
];

const DYNAMIC_ROUTES: readonly Route[] = [
  {
    href: "/workbench/cases/APP-1",
    label: "Unified case file",
    workstream: "WS-7.3.2",
    backend: "P1 · P2 · P6",
    note: "Phase 7 §4 calls this the single most important screen in the workbench.",
  },
  {
    href: "/apply/APP-1/decision",
    label: "Decision & reasons",
    workstream: "WS-7.2.5",
    backend: "P1",
    note: "Templated reason codes; decline routes to human review.",
  },
  {
    href: "/apply/APP-1/offers",
    label: "Offer comparison",
    workstream: "WS-7.2.4",
    backend: "P4",
    note: "Read-only; selection only within the backend feasible set.",
  },
  {
    href: "/collections/alerts/ALERT-1",
    label: "Alert detail & disposition",
    workstream: "WS-7.5.2",
    backend: "P4",
    note: "Disposition is mandatory before an alert can close.",
  },
  {
    href: "/dashboards/portfolio-overview",
    label: "Risk & portfolio dashboard",
    workstream: "WS-7.4",
    backend: "P3",
    note: "Generic panel renderer; P3 computes every metric.",
  },
  {
    href: "/audit/LOG-1",
    label: "Audit trail",
    workstream: "WS-7.3.5",
    backend: "P0",
    note: "Every decision-log entry for a case, human-readable.",
  },
];

function RouteList({ routes }: { readonly routes: readonly Route[] }) {
  return (
    <ul className="mt-3 space-y-2">
      {routes.map((route) => (
        <li key={route.href} className="rounded border border-neutral-300 bg-white p-3">
          <Link
            href={route.href}
            className="font-medium text-blue-800 underline underline-offset-2"
          >
            {route.label}
          </Link>
          <span className="ml-2 font-mono text-xs text-neutral-500">{route.href}</span>
          <p className="mt-1 text-xs text-neutral-600">
            <span className="font-mono">{route.workstream}</span>
            <span className="mx-2 text-neutral-400">|</span>
            <span>backend {route.backend}</span>
          </p>
          <p className="mt-1 text-xs text-neutral-700">{route.note}</p>
        </li>
      ))}
    </ul>
  );
}

export default function IndexPage() {
  return (
    <div className="min-h-screen bg-neutral-50">
      <header className="border-b border-brand-800 bg-brand-700">
        <div className="mx-auto max-w-3xl px-4 py-8">
          <p className="text-xs font-medium uppercase tracking-widest text-brand-200">
            AI-Powered Smart Lending Decision Hub
          </p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight text-white">
            Lending Hub
          </h1>
          <p className="mt-2 max-w-xl text-sm text-brand-100">
            Four interface surfaces over the Decision Orchestrator gateway.
          </p>
        </div>
      </header>
      <div className="mx-auto max-w-3xl p-6">

      <p
        role="note"
        className="mt-4 rounded border border-dashed border-neutral-400 bg-neutral-50 p-4 text-xs text-neutral-700"
      >
        Every route below renders, and none of them shows data. The gateway
        adapter rejects every call by design, because a demo adapter would put a
        score, a PD, an EMI and reason sentences on screen &mdash; the four
        things Phase 7 &sect;8 forbids inventing &mdash; and a demo screenshot is
        indistinguishable from a real one. Each screen states its own
        unavailability and names the ticket behind it.
      </p>

      <h2 className="mt-6 text-sm font-semibold uppercase tracking-wide text-neutral-700">
        Static routes
      </h2>
      <RouteList routes={STATIC_ROUTES} />

      <h2 className="mt-6 text-sm font-semibold uppercase tracking-wide text-neutral-700">
        Dynamic routes
      </h2>
      <p className="mt-1 text-xs text-neutral-600">
        The identifiers below are placeholders; any value routes.
      </p>
      <RouteList routes={DYNAMIC_ROUTES} />
      </div>
    </div>
  );
}

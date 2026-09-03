"use client";

/**
 * The application shell — a grouped sidebar and a page header.
 *
 * The previous shell was ten flat items in a top bar. Ten peers in a row give a
 * reader no way to build a mental model: an officer cannot tell which screens
 * belong to their job, and a reviewer cannot see that the platform has a shape.
 * Grouping them by the moment in the lifecycle they serve — originate, monitor,
 * explore — makes the structure legible without a word of explanation, and
 * moving the nav to a rail frees the full width for dense numeric content.
 *
 * WHAT THIS DOES NOT DO
 * ---------------------
 * No logo. TVS Credit's AspireMark is not reproduced anywhere in this build; a
 * rendered mark reads as licensed use.
 *
 * No counts or badges on nav items. Every number on a nav item would be one
 * this frontend computed or invented, and Phase 7 §8 forbids both.
 */

import Link from "next/link";
import type { ReactNode } from "react";

import { Copy } from "../shared/Copy";

export interface ShellSection {
  readonly label: string;
  readonly href: string;
  readonly surface: string;
}

interface NavGroup {
  readonly title: string;
  readonly items: readonly ShellSection[];
}

/**
 * The four SRS Module 9 surfaces plus the module views, grouped by the moment
 * in the credit lifecycle each serves.
 */
const GROUPS: readonly NavGroup[] = [
  {
    title: "Originate",
    items: [
      { label: "Officer queue", href: "/workbench/queue", surface: "WS-7.3" },
      { label: "Customer", href: "/apply/APP-1/decision", surface: "WS-7.2" },
      { label: "Assistant", href: "/assistant/CONV-1", surface: "WS-7.2.7" },
    ],
  },
  {
    title: "Monitor",
    items: [
      { label: "Risk & portfolio", href: "/dashboards/portfolio", surface: "WS-7.4" },
      { label: "Collections", href: "/collections/queue", surface: "WS-7.5" },
    ],
  },
  {
    title: "Evidence",
    items: [
      { label: "Control centre", href: "/dashboard", surface: "demo" },
      { label: "Agri intelligence", href: "/modules/agri/PLOT-DEMO-1", surface: "SRS M1" },
      { label: "Fraud detection", href: "/modules/fraud/APP-1", surface: "SRS M3" },
      { label: "Default prediction", href: "/modules/risk", surface: "SRS M5" },
    ],
  },
];

/** Flat list, kept for anything that enumerates surfaces. */
export const SECTIONS: readonly ShellSection[] = GROUPS.flatMap((g) => g.items);

function isActive(href: string, active: string | undefined): boolean {
  if (active === undefined) return false;
  // Segment-exact: "/dashboards/portfolio" starts with "/dashboard", so a bare
  // prefix test lights up two items at once.
  return href === active || href.startsWith(`${active}/`);
}

export function AppShell({
  children,
  active,
  title,
  subtitleKey,
  meta,
}: {
  readonly children: ReactNode;
  readonly active?: string;
  readonly title?: ReactNode;
  readonly subtitleKey?: string;
  /** Provenance or status, shown once per page rather than once per panel. */
  readonly meta?: ReactNode;
}) {
  return (
    <div className="min-h-screen bg-[--ground] lg:grid lg:grid-cols-[236px_1fr]">
      <aside className="border-b border-brand-800 bg-brand-900 lg:sticky lg:top-0 lg:h-screen lg:overflow-y-auto lg:border-b-0 lg:border-r">
        <div className="px-5 py-5">
          <Link
            href="/"
            className="block text-[15px] font-semibold tracking-tight text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
          >
            Lending Hub
          </Link>
          <p className="mt-0.5 text-[11px] leading-tight text-brand-300">
            Smart Lending Decision Hub
          </p>
        </div>

        <nav aria-label="Surfaces" className="px-3 pb-6">
          {GROUPS.map((group) => (
            <div key={group.title} className="mb-5">
              <p className="px-2 pb-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-brand-400">
                {group.title}
              </p>
              <ul className="flex flex-col gap-0.5">
                {group.items.map((item) => {
                  const on = isActive(item.href, active);
                  return (
                    <li key={item.href}>
                      <Link
                        href={item.href}
                        aria-current={on ? "page" : undefined}
                        className={
                          on
                            ? "block rounded-md bg-white/12 px-2.5 py-1.5 text-[13px] font-medium text-white"
                            : "block rounded-md px-2.5 py-1.5 text-[13px] text-brand-200 transition-colors hover:bg-white/8 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
                        }
                      >
                        {item.label}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </nav>
      </aside>

      <div className="flex min-h-screen flex-col">
        {title !== undefined ? (
          <header className="border-b border-[--rule] bg-[--surface] px-6 py-5 lg:px-8">
            <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
              <div>
                <h1 className="text-[22px] font-semibold text-slate-900">{title}</h1>
                {subtitleKey !== undefined ? (
                  <p className="mt-0.5 text-[13px] text-slate-500">
                    <Copy k={subtitleKey} />
                  </p>
                ) : null}
              </div>
              {meta !== undefined ? <div>{meta}</div> : null}
            </div>
          </header>
        ) : null}

        <main className="flex-1 px-6 py-6 lg:px-8">{children}</main>

        <footer className="px-6 pb-8 lg:px-8">
          <p className="border-t border-[--rule] pt-4 text-[11px] leading-relaxed text-slate-400">
            Every figure is computed by a backend engine and carries its model
            id, version and decision-log reference. Where a backend does not
            exist, the screen states the gap and names the blocking ticket
            rather than rendering a placeholder.
          </p>
        </footer>
      </div>
    </div>
  );
}

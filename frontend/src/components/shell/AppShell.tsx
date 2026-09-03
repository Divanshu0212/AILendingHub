/**
 * The application shell — masthead and surface navigation.
 *
 * Every screen previously rendered as bare content on a blank page, with no way
 * to reach any other screen. That is not a styling gap: an officer cannot move
 * from a queue to a case file, so the workbench cannot be walked through, and a
 * reviewer sees ten disconnected pages rather than one system.
 *
 * WHAT THIS DOES NOT DO
 * ---------------------
 * No logo. TVS Credit's AspireMark is not reproduced anywhere in this build —
 * a rendered mark reads as licensed use, and a hackathon entry must not imply
 * an endorsement it does not have. The wordmark here is set in type.
 *
 * No counts, no badges, no "12 pending" figures. Every number on a nav item
 * would be a number this frontend computed or invented, and Phase 7 §8 forbids
 * both. Navigation is structural only.
 *
 * The strings are route names, which is the same classification the C4 gate
 * exemption uses for `app/page.tsx`: structural chrome naming an affordance,
 * not customer copy carrying an effective date. They are held here rather than
 * in `i18n/chrome.ts` because a nav label and a page title are the same string
 * for the same screen, and duplicating them into the registry would create two
 * places for one name to drift.
 */

import Link from "next/link";
import type { ReactNode } from "react";

import { Copy } from "../shared/Copy";

export interface ShellSection {
  readonly label: string;
  readonly href: string;
  readonly surface: string;
}

/** The four surfaces of SRS Module 9, in the phase file's own build order. */
export const SECTIONS: readonly ShellSection[] = [
  { label: "Control centre", href: "/dashboard", surface: "demo" },
  { label: "Officer workbench", href: "/workbench/queue", surface: "WS-7.3" },
  { label: "Collections", href: "/collections/queue", surface: "WS-7.5" },
  { label: "Risk dashboards", href: "/dashboards/portfolio-overview", surface: "WS-7.4" },
  { label: "Customer", href: "/apply/APP-1/decision", surface: "WS-7.2" },
  { label: "Assistant", href: "/assistant/CONV-1", surface: "WS-7.2.7" },
  { label: "Agri", href: "/modules/agri/APP-1", surface: "SRS M1" },
  { label: "Fraud", href: "/modules/fraud/APP-1", surface: "SRS M3" },
  { label: "Risk models", href: "/modules/risk", surface: "SRS M5" },
];

export function AppShell({
  children,
  active,
  title,
  subtitleKey,
}: {
  readonly children: ReactNode;
  /** Href prefix of the active section, for nav highlighting. */
  readonly active?: string;
  readonly title?: ReactNode;
  /**
   * Copy key for the one-line orientation text under the title.
   *
   * A key rather than a string: a subtitle is a sentence, and the C4 gate is
   * right that a sentence in a component is copy. Structural subtitles live in
   * `i18n/chrome.ts`; one under a regulated prefix resolves to its ticket
   * placeholder, which is the correct outcome rather than an obstacle.
   */
  readonly subtitleKey?: string;
}) {
  return (
    <div className="min-h-screen bg-neutral-50">
      <header className="border-b border-brand-800 bg-brand-700">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <Link
            href="/"
            className="text-sm font-semibold tracking-tight text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
          >
            Lending Hub
          </Link>
          <nav aria-label="Surfaces" className="flex flex-wrap gap-x-1 gap-y-1">
            {SECTIONS.map((section) => {
              // Segment-exact, not prefix: "/dashboards/portfolio-overview"
              // startsWith "/dashboard", so a plain prefix test lit up two nav
              // items at once. The boundary character is what distinguishes a
              // section from one whose name merely begins the same way.
              const isActive =
                active !== undefined &&
                (section.href === active || section.href.startsWith(`${active}/`));
              return (
                <Link
                  key={section.href}
                  href={section.href}
                  aria-current={isActive ? "page" : undefined}
                  className={
                    isActive
                      ? "rounded bg-white px-3 py-1.5 text-sm font-medium text-brand-800"
                      : "rounded px-3 py-1.5 text-sm text-brand-100 hover:bg-brand-800 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
                  }
                >
                  {section.label}
                </Link>
              );
            })}
          </nav>
        </div>
      </header>

      {title !== undefined ? (
        <div className="border-b border-neutral-200 bg-white">
          <div className="mx-auto max-w-6xl px-4 py-4">
            <h1 className="text-xl font-semibold tracking-tight text-neutral-900">{title}</h1>
            {subtitleKey !== undefined ? (
              <p className="mt-1 text-sm text-neutral-600">
                <Copy k={subtitleKey} />
              </p>
            ) : null}
          </div>
        </div>
      ) : null}

      <div className="mx-auto max-w-6xl px-4 py-6">{children}</div>

      <footer className="mx-auto max-w-6xl px-4 pb-8 pt-2">
        <p className="border-t border-neutral-200 pt-4 text-xs text-neutral-500">
          Every figure on these screens is computed by a backend engine and
          carries its model id, version and decision-log reference. Where a
          backend does not exist, the screen states the gap and names the
          blocking ticket rather than rendering a placeholder value.
        </p>
      </footer>
    </div>
  );
}

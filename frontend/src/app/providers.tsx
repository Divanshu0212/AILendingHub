"use client";

/**
 * The client-side provider tree.
 *
 * Mounts the chrome copy registry (WS-7.1.5) so structural labels — page
 * titles, column headings, state words — render as text instead of as
 * `workbench.queue.title · no-registry · LH-701`.
 *
 * This is the resolution to P7-F8, which the root layout's skip-link comment
 * predicted: *"the registry needs a small set of chrome keys resolvable at
 * build time, which is a registry capability nobody has specified."* That set
 * is `i18n/chrome.ts`, and it is enforced rather than trusted — every
 * regulated prefix falls through to the ticket-bearing placeholder, so the
 * screens carrying customer-relied-upon text still show their gap.
 *
 * The locale stays `CHROME_LOCALE` rather than a negotiated one. A second
 * language is not a bundle addition here: it needs ratified copy for its
 * regulated keys too (LH-707), which is a governance step, not a file.
 */

import type { ReactNode } from "react";

import { AppProviders } from "../adapters/context";
import { devSession } from "../adapters/devSession";
import { selectAdapter } from "../adapters/http";
import { ChromeCopyRegistry, CHROME_LOCALE } from "../i18n/chrome";
import { LocaleProvider } from "../i18n/context";

const REGISTRY = new ChromeCopyRegistry();

/**
 * The adapter, chosen once.
 *
 * `selectAdapter` returns `AbsentAdapter` unless a gateway URL is configured
 * AND a session exists, so the default with nothing set up is unchanged: every
 * call refuses, and each screen renders its own ticket. Mounting it here is
 * what makes the HTTP path reachable at all — the wiring existed and nothing
 * used it, so the gateway could be running and answering and never be called.
 */
const SESSION = devSession();
const ADAPTER = selectAdapter(SESSION);

export function Providers({ children }: { children: ReactNode }) {
  return (
    <LocaleProvider registry={REGISTRY} locale={CHROME_LOCALE}>
      <AppProviders adapter={ADAPTER} session={SESSION}>
        {children}
      </AppProviders>
    </LocaleProvider>
  );
}

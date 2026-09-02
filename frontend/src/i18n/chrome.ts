/**
 * WS-7.1.5 — the chrome copy registry.
 *
 * WHY THIS EXISTS, AND THE LINE IT DOES NOT CROSS
 * -----------------------------------------------
 * `AbsentCopyRegistry` returns `no-registry` for every key, which is correct for
 * disclosure and wrong for chrome — and applying one rule to both made every
 * screen in the application unreadable. A page whose heading renders as
 * `workbench.queue.title · no-registry · LH-701` cannot be reviewed by the
 * officer who will use it, so the design feedback that would catch a bad queue
 * layout never arrives.
 *
 * The registry design is right about the thing it was designed for. A rate, an
 * APR sentence, a Key Fact Statement or an adverse-action reason must never ship
 * inside a frontend build: those change on regulatory deadlines rather than
 * release cadences, and a complaint six months later turns on *which version*
 * the customer was shown. None of that is true of the word "Queue".
 *
 * So this registry serves **structural labels only**, and the split is enforced
 * rather than described:
 *
 *   - Chrome — page titles, column headings, button labels, state words. These
 *     name a UI affordance. Nobody's complaint turns on them, they carry no
 *     effective date, and a wrong one is a usability bug rather than a
 *     mis-disclosure.
 *   - Regulated — anything a customer could rely on: consent wording, grievance
 *     contact details, disclosure bodies, reason sentences, any number. These
 *     stay unresolved and keep rendering their ticket, exactly as before.
 *
 * `REGULATED_PREFIXES` below is the enforcement, and :func:`chromeRegistry`
 * refuses to serve a key matching one even if a developer adds it to the table —
 * the guard is in code rather than in a review comment, because "just for the
 * demo" is precisely how unratified copy reaches a screenshot.
 *
 * WHAT THIS IS NOT
 * ----------------
 * Not a translation bundle: one locale, English, and `availableLocales` says so.
 * A second language ships through the real registry (LH-707), because a launch
 * language needs ratified copy for its regulated keys too, and that is a
 * governance step this file cannot shortcut.
 */

import type { DocumentRef } from "../lib/gateway/types";
import type { CopyRegistry, CopyResult, ResolvedCopy } from "./registry";

/** The locale this registry serves. Chrome only, and only English. */
export const CHROME_LOCALE = "en-IN";

/**
 * Key prefixes this registry will never serve, whatever the table says.
 *
 * Each is customer-relied-upon text with an effective date and an owner.
 * Serving one from a frontend build would put unratified wording on a regulated
 * screen — the failure WS-7.1.5 exists to prevent, and the one Phase 5's
 * `templates` module refuses at the same seam for the same reason.
 */
export const REGULATED_PREFIXES: readonly string[] = [
  "customer.consent.",
  "customer.grievance.",
  "customer.decision.",
  "disclosure.",
  "reason.",
  "kfs.",
  "apr.",
];

export function isRegulatedKey(key: string): boolean {
  return REGULATED_PREFIXES.some((prefix) => key.startsWith(prefix));
}

/**
 * The chrome strings. Structural labels, nothing a customer relies on.
 *
 * Deliberately terse: these name affordances, and a heading that explains
 * itself is a heading doing a paragraph's job.
 */
const CHROME: Readonly<Record<string, string>> = {
  "common.loading": "Loading",
  "common.error.generic": "Something went wrong",
  "common.error.unauthenticated": "Sign in to continue",
  "common.error.forbidden": "You do not have access to this",
  "common.action.retry": "Retry",
  "common.action.cancel": "Cancel",
  "common.action.submit": "Submit",
  "common.freshness.fresh": "Current",
  "common.freshness.stale": "Stale",
  "common.freshness.unknown": "Freshness unknown",
  "common.audit.link": "View audit trail",
  "common.audit.unavailable": "No audit reference",
  "common.model.attribution": "Model",

  "customer.home.title": "Home",
  "customer.precheck.title": "Eligibility pre-check",
  "customer.documents.title": "Documents",
  "customer.offers.title": "Your offers",
  "customer.servicing.title": "Your loan",
  "customer.assistant.title": "Assistant",

  "workbench.queue.title": "Officer queue",
  "workbench.case.title": "Case file",
  "workbench.decision.title": "Decision",
  "workbench.override.title": "Override",
  "workbench.offers.title": "Construct offer",
  "workbench.audit.title": "Audit trail",

  "dashboards.portfolio.title": "Portfolio overview",
  "dashboards.vintage.title": "Vintage & roll-rate",
  "dashboards.concentration.title": "Concentration",
  "dashboards.scenario.title": "Scenario",

  "collections.queue.title": "Collections queue",
  "collections.alert.title": "Alert detail",
  "collections.disposition.title": "Disposition",
  "collections.sla.title": "SLA & ownership",
};

/**
 * The document reference chrome resolves against.
 *
 * `documentId` says plainly that this is not a registry document, so a rendered
 * label's `data-copy-doc` attribute in the DOM distinguishes a chrome string
 * from a ratified one at a glance — including in a screenshot.
 */
const CHROME_SOURCE: DocumentRef = {
  documentId: "frontend-chrome-not-a-registry-document",
  version: "0.1.0",
  effectiveFrom: "1970-01-01",
  effectiveTo: null,
  locale: CHROME_LOCALE,
};

/**
 * A registry that serves chrome and refuses everything else.
 *
 * Regulated keys fall through to `no-registry` with their ticket, so the
 * screens that matter still show their gap and the WS-7.1.5 coverage check
 * still reports the real shortfall.
 */
export class ChromeCopyRegistry implements CopyRegistry {
  readonly availableLocales: readonly string[] = [CHROME_LOCALE];

  resolve(key: string, locale: string): CopyResult {
    if (isRegulatedKey(key)) {
      return { key, locale, reason: "no-registry", ticket: "LH-701" };
    }
    const text = CHROME[key];
    if (text === undefined) {
      return { key, locale, reason: "no-registry", ticket: "LH-701" };
    }
    if (locale !== CHROME_LOCALE) {
      return { key, locale, reason: "no-translation", ticket: "LH-707" };
    }
    const resolved: ResolvedCopy = { key, text, source: CHROME_SOURCE };
    return resolved;
  }
}

/** Every chrome key this registry can serve. Used by the coverage test. */
export const CHROME_KEYS: readonly string[] = Object.keys(CHROME);

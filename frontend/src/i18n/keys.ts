/**
 * WS-7.1.5 - full string externalization from day one.
 *
 * THIS FILE CONTAINS NO ENGLISH COPY, AND THAT IS THE POINT.
 *
 * Phase 7 §4 WS-7.1.5 and §8 both say disclosure and reason-code copy comes from
 * the versioned, dated document registry Module 6/P5 uses, "never hardcoded in
 * frontend code", and frames stale on-screen rate or fee text as the same
 * failure mode as an ungrounded LLM answer.
 *
 * The registry does not exist (LH-701). The tempting move is to type English
 * strings here and swap them later. That is exactly the failure the grounding
 * contract exists to prevent: a drafted sentence is indistinguishable from a
 * ratified one six months later, and it will have been screenshotted into a
 * product review by then.
 *
 * So this file declares the KEYS the surfaces reference and nothing else. A
 * missing key renders `MissingCopy` - a visible, deliberately ugly placeholder
 * naming the key and the ticket - rather than falling back to the key name or to
 * English, both of which look like a rendering bug rather than a governance gap.
 *
 * SCOPE NOTE. Not every string on a screen is disclosure copy. A column header
 * reading "Tier" is chrome. The phase file draws no line, and drawing one is
 * P7-F4 in the findings: this codebase treats ALL of it as registry-sourced,
 * which is over-strict and the safe direction to be wrong in.
 */

/** Every copy key the four surfaces reference. Grouped by surface. */
export const COPY_KEYS = {
  common: [
    "common.appName",
    "common.loading",
    "common.error.generic",
    "common.error.unauthenticated",
    "common.error.forbidden",
    "common.error.missingAttribution",
    "common.action.retry",
    "common.action.cancel",
    "common.action.submit",
    "common.freshness.fresh",
    "common.freshness.stale",
    "common.freshness.unknown",
    "common.audit.link",
    "common.audit.unavailable",
    "common.model.attribution",
    "common.notAvailable",
  ],
  customer: [
    "customer.home.title",
    "customer.precheck.title",
    "customer.precheck.softPullNotice",
    "customer.consent.title",
    "customer.consent.aaFlowTitle",
    "customer.documents.title",
    "customer.documents.ocrPending",
    "customer.offers.title",
    "customer.offers.readOnlyNotice",
    "customer.decision.title",
    "customer.decision.declineRouteToHuman",
    "customer.servicing.title",
    "customer.assistant.title",
    "customer.assistant.unverifiedClaim",
    "customer.grievance.title",
    "customer.grievance.officerContact",
  ],
  workbench: [
    "workbench.queue.title",
    "workbench.case.title",
    "workbench.case.panelUnavailable",
    "workbench.decision.title",
    "workbench.override.title",
    "workbench.override.reasonRequired",
    "workbench.override.confirmPrompt",
    "workbench.override.loggedNotice",
    "workbench.offers.title",
    "workbench.audit.title",
  ],
  dashboards: [
    "dashboards.portfolio.title",
    "dashboards.vintage.title",
    "dashboards.concentration.title",
    "dashboards.modelHealth.title",
    "dashboards.scenario.title",
    "dashboards.drillThrough.title",
  ],
  collections: [
    "collections.queue.title",
    "collections.alert.title",
    "collections.disposition.title",
    "collections.disposition.mandatoryNotice",
    "collections.disposition.outcomeRequired",
    "collections.sla.title",
  ],
} as const;

type Group = keyof typeof COPY_KEYS;
export type CopyKey = (typeof COPY_KEYS)[Group][number];

/** Flat list, for the registry-coverage check. */
export const ALL_COPY_KEYS: readonly string[] = Object.values(COPY_KEYS).flat();

/**
 * The launch language list is [POLICY] and unratified (LH-707).
 *
 * Phase 7 §3 requires ">= 4, per SRS UX-8" and §8 puts the language list on the
 * do-not-invent list. Four is a floor, not a list - it says how many, not which,
 * and picking four plausible Indian languages here would be inventing a market
 * decision. The value is whatever the registry serves; this constant records the
 * FLOOR the phase file states, which is [SPEC].
 */
export const MINIMUM_LAUNCH_LANGUAGES = 4;

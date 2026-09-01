"use client";

/**
 * WS-7.1.1 — the deep link to the audit trail, rendered beside every
 * model-derived value.
 *
 * SRS §11.6b's stated purpose for the triplet is "so the UI can deep-link to the
 * audit trail". This is that link, and it is a shared component so the link
 * exists identically on the customer decision screen and the officer decision
 * panel — the same reason the phase file gives for the shared reason-code card.
 *
 * The null-decisionLogId case renders the model attribution with NO link and an
 * explicit note. That is the honest rendering of a batch-scored value: the model
 * is named, and there is no decision to inspect because no decision was taken.
 * Linking to a fabricated id, or hiding the attribution entirely, would both
 * make a batch score look like a decision.
 */

import { auditTrailHref, type ModelAttribution } from "../../lib/gateway/provenance";
import { Copy } from "./Copy";

export function AuditLink({ attribution }: { attribution: ModelAttribution }) {
  const href = auditTrailHref(attribution);
  const label = `${attribution.modelId} v${attribution.modelVersion}`;

  if (!href) {
    return (
      <span
        className="font-mono text-xs text-neutral-500"
        data-model-id={attribution.modelId}
        data-model-version={attribution.modelVersion}
      >
        {label} &middot; <Copy k="common.audit.unavailable" />
      </span>
    );
  }

  return (
    <a
      href={href}
      className="rounded font-mono text-xs text-blue-800 underline underline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-700"
      data-model-id={attribution.modelId}
      data-model-version={attribution.modelVersion}
      data-decision-log-id={attribution.decisionLogId}
    >
      {label}
    </a>
  );
}

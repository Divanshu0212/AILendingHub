"use client";

/**
 * WS-7.3.2 — the unified case file.
 *
 * Phase 7 §4 calls this "the single most important screen in the workbench", and
 * the reason it gives is spatial rather than functional: "one screen, no
 * tab-hopping across source systems". The value is not that the data is
 * available — it already is, in five systems — but that an underwriter forms one
 * judgement instead of five sequential ones.
 *
 * That has a design consequence the phase file does not state: the panels must
 * be VISIBLE TOGETHER, not stacked behind an accordion. An accordion is
 * tab-hopping with fewer clicks. So this lays out in a grid and every panel
 * renders its summary in full; the drill-downs are the links.
 *
 * THE INCREMENTAL BUILD IS THE HARD PART
 * --------------------------------------
 * The phase file says: "ships with P1 data first, agri panel activates when P2
 * ships, fraud subgraph viewer activates when P6's graph layer ships (a simpler
 * alert-list view is the P1-era fallback)."
 *
 * The naive implementation renders whatever it got and omits the rest. That
 * produces the worst possible screen for the underwriter, because AN ABSENT
 * PANEL AND AN EMPTY PANEL LOOK IDENTICAL. "No fraud alerts on this applicant"
 * and "the fraud layer is not deployed" lead to opposite decisions and render as
 * the same blank rectangle.
 *
 * So every panel is present in the layout at all times, in one of three states:
 * populated, empty-but-checked, or unavailable-with-a-reason. `panelAvailability`
 * carries the third from the gateway — the frontend does not infer availability
 * from a null payload, because a timeout produces a null payload too.
 *
 * THE PANEL SET IS NOT CONFIGURABLE
 * ---------------------------------
 * There is no prop to hide a panel. An underwriter who can hide the fraud panel
 * has a case file that is unified for some cases and not others, and the ones
 * they hide it on are the ones where it was inconvenient.
 */

import type { UnifiedCaseFile as CaseFileData, PanelAvailability, PanelPayload } from "../../lib/gateway/endpoints";
import { EvidenceMap } from "../shared/EvidenceMap";
import { AlertViewer } from "../shared/AlertViewer";
import { ReasonCodeList } from "../shared/ReasonCodeCard";
import { AuditLink } from "../shared/AuditLink";
import { Copy } from "../shared/Copy";
import type { FraudAlert } from "../../lib/gateway/types";

/** The five panels WS-7.3.2 names, in the order it names them. */
const PANEL_IDS = ["bureau", "cashflow", "agri", "fraud", "reasons"] as const;
type PanelId = (typeof PANEL_IDS)[number];

function availabilityFor(
  list: readonly PanelAvailability[],
  panelId: PanelId
): PanelAvailability | null {
  return list.find((a) => a.panelId === panelId) ?? null;
}

/**
 * The three-state wrapper. Every panel goes through this, which is what makes
 * "unavailable" and "empty" impossible to confuse.
 */
function CasePanel({
  title,
  availability,
  isEmpty,
  children,
}: {
  title: string;
  availability: PanelAvailability | null;
  isEmpty: boolean;
  children: React.ReactNode;
}) {
  const unavailable = availability !== null && !availability.available;

  return (
    <section className="rounded border border-neutral-300 bg-white p-4" aria-label={title}>
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-neutral-500">
        {title}
      </h3>
      {unavailable ? (
        <p
          role="note"
          className="rounded border border-dashed border-neutral-400 bg-neutral-50 p-3 font-mono text-xs text-neutral-600"
          data-panel-state="unavailable"
        >
          {/* The reason is backend-supplied. "Not deployed in this environment"
              and "P2 has not gated" are different answers and the officer needs
              the right one. */}
          {availability?.unavailableReason ?? "unavailable"}
        </p>
      ) : isEmpty ? (
        <p
          className="rounded bg-neutral-50 p-3 text-xs text-neutral-700"
          data-panel-state="empty-checked"
        >
          {/* Distinct wording AND a distinct data attribute, so a screenshot and
              a DOM snapshot both preserve the distinction. */}
          checked &middot; nothing found
        </p>
      ) : (
        <div data-panel-state="populated">{children}</div>
      )}
    </section>
  );
}

function KeyValuePanel({ payload }: { payload: PanelPayload | null }) {
  if (!payload) return null;
  return (
    <dl className="space-y-1 text-sm">
      {payload.rows.map((row) => (
        <div key={row.label} className="flex justify-between gap-4">
          <dt className="text-neutral-600">{row.label}</dt>
          <dd
            className={`font-mono ${row.emphasis ? "font-semibold text-tier-red" : "text-neutral-900"}`}
          >
            {/* `display` only. There is no unit appended here, no percentage
                sign added, no thousands separator inserted. */}
            {row.display}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function FraudAlertList({ alerts }: { alerts: readonly FraudAlert[] }) {
  return (
    <ul className="space-y-2">
      {alerts.map((a) => (
        <li
          key={a.fraudAlertId}
          className="rounded border border-neutral-200 p-2 text-xs"
          data-fraud-alert-id={a.fraudAlertId}
        >
          <div className="flex items-center gap-2 font-mono text-neutral-600">
            <span>{a.layer}</span>
            <span>{a.ruleId}</span>
            <span className="ml-auto">{a.severity}</span>
          </div>
          <p className="mt-1 text-neutral-900">{a.explanation}</p>
          <p className="mt-1">
            <AuditLink attribution={a.attribution} />
          </p>
        </li>
      ))}
    </ul>
  );
}

export function UnifiedCaseFile({ caseFile }: { caseFile: CaseFileData }) {
  const av = caseFile.panelAvailability;

  return (
    <div className="space-y-4" data-application-id={caseFile.applicationId}>
      <h2 className="text-base font-semibold text-neutral-900">
        <Copy k="workbench.case.title" />{" "}
        <span className="font-mono text-sm text-neutral-600">{caseFile.applicationId}</span>
      </h2>

      {/* Grid, not accordion. The whole point of a unified case file is
          simultaneous visibility; an accordion is tab-hopping with fewer
          clicks. */}
      <div className="grid gap-4 lg:grid-cols-2">
        <CasePanel
          title="bureau summary"
          availability={availabilityFor(av, "bureau")}
          isEmpty={!caseFile.bureauSummary || caseFile.bureauSummary.rows.length === 0}
        >
          <KeyValuePanel payload={caseFile.bureauSummary} />
        </CasePanel>

        <CasePanel
          title="AA cash-flow summary"
          availability={availabilityFor(av, "cashflow")}
          isEmpty={!caseFile.cashFlowSummary || caseFile.cashFlowSummary.rows.length === 0}
        >
          <KeyValuePanel payload={caseFile.cashFlowSummary} />
        </CasePanel>

        <CasePanel
          title="agri evidence"
          availability={availabilityFor(av, "agri")}
          isEmpty={caseFile.agriEvidence === null}
        >
          {caseFile.agriEvidence ? <EvidenceMap evidence={caseFile.agriEvidence} /> : null}
        </CasePanel>

        <CasePanel
          title="fraud alerts"
          availability={availabilityFor(av, "fraud")}
          isEmpty={caseFile.fraudAlerts.length === 0 && caseFile.fraudSubgraph === null}
        >
          <FraudAlertList alerts={caseFile.fraudAlerts} />
        </CasePanel>

        <CasePanel
          title="reason codes"
          availability={availabilityFor(av, "reasons")}
          isEmpty={
            caseFile.decision === null ||
            caseFile.decision.reasonCodes.length === 0 ||
            caseFile.decision.reasonAttribution === null
          }
        >
          {caseFile.decision && caseFile.decision.reasonAttribution ? (
            <ReasonCodeList
              reasons={caseFile.decision.reasonCodes}
              attribution={caseFile.decision.reasonAttribution}
              audience="officer"
            />
          ) : null}
        </CasePanel>
      </div>
    </div>
  );
}

/** Re-exported so the collections console can reuse the same alert rendering. */
export { AlertViewer };

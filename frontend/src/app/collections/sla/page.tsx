"use client";

/**
 * WS-7.5.4 — the SLA / ownership tracker.
 *
 * Four numbers, all server-computed: alerts owned, breached, due soon, and
 * undisposed. None is derived here, including the ones that look like trivial
 * counts, because "% within SLA" is the §8 exit criterion and a compliance
 * figure computed in two places is a compliance figure eventually reported two
 * ways.
 *
 * WHAT THIS SCREEN CANNOT SHOW, AND SAYS SO
 * -----------------------------------------
 * The phase file's fourth item is "SLA/ownership tracker; outcome history
 * feeding back into P8/P6 learning". The outcome history is LH-510 — Phase 4's
 * register records that 24 months of alert dispositions are listed as an entry
 * criterion of P4 and as a deliverable of no phase. So the feedback half of this
 * screen has no data source, and the screen says that rather than rendering an
 * empty chart, which reads as "no outcomes yet" rather than "no pipeline".
 */

import { Copy } from "../../../components/shared/Copy";
import { AppShell } from "../../../components/shell/AppShell";

export default function SlaTrackerPage() {
  return (
    <AppShell active="/collections" title="SLA & ownership" subtitleKey="collections.sla.subtitle">

      <p
        role="note"
        className="mt-4 rounded border border-dashed border-neutral-400 bg-neutral-50 p-4 font-mono text-xs text-neutral-700"
      >
        SLA aggregates require the case-management system (LH-120) and the SLAs
        themselves (LH-502). Outcome history requires the disposition log
        (LH-510). No panel is rendered rather than an empty one: an empty chart
        reads as &quot;no outcomes yet&quot; where the truth is &quot;no
        pipeline&quot;.
      </p>
    </AppShell>
  );
}

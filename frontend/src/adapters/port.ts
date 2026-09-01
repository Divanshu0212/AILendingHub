/**
 * The adapter seam — the frontend's equivalent of `ports.py` (ADR-0003).
 *
 * Every screen depends on this interface, never on `GatewayClient` directly.
 * Two implementations exist:
 *
 *   `GatewayAdapter`  — Track B. Calls the real gateway through GatewayClient.
 *   `AbsentAdapter`   — the honest local state. Every method rejects.
 *
 * THERE IS NO MOCK ADAPTER WITH DATA IN IT, AND THAT IS A DECISION
 * ---------------------------------------------------------------
 * The obvious third implementation returns plausible loan applications so the
 * screens can be clicked through. It is not here, for the same reason ADR-0014
 * refuses a simulated collections desk and Master §2 rule 3 confines synthetic
 * data to `tests/fixtures/`.
 *
 * A fixture adapter would put a score, a PD, an EMI and a set of reason
 * sentences on screen. Those are precisely the four things this phase exists to
 * ensure are never invented client-side — and a screenshot of a demo build is
 * indistinguishable from a screenshot of a real one. The repository's whole
 * posture is that a plausible number is worse than a missing one because it
 * survives review; a plausible SCREEN is that failure with a wider audience,
 * since screens are what get shown to committees.
 *
 * What `AbsentAdapter` gives instead is a set of surfaces that render their
 * loading, error and unavailable states — which are the states this system will
 * actually be in for most of its build, and which are the ones nobody designs.
 *
 * If a demo is genuinely needed, the correct place for the fixtures is
 * `tests/fixtures/` under a Playwright/MSW harness, mounted only by a test
 * runner and never by `next dev`. That is a deliberate build step someone has to
 * take, which is the property that matters.
 */

import type {
  ActionOption,
  Alert,
  AssistantTurn,
  ConsentArtifact,
  ConsentRequest,
  DashboardPanel,
  DecisionSummary,
  DisclosureDocument,
  DispositionRequest,
  FeasibleSet,
  OutcomeCodeOption,
  OverrideReasonOption,
  OverrideRequest,
} from "../lib/gateway/types";
import type {
  AlertQueueFilters,
  AuditEntry,
  Page,
  QueueFilters,
  QueueItem,
  UnifiedCaseFile,
} from "../lib/gateway/endpoints";

export interface Adapter {
  // WS-7.3
  fetchQueue(f: QueueFilters): Promise<Page<QueueItem>>;
  fetchCaseFile(applicationId: string): Promise<UnifiedCaseFile>;
  fetchOverrideReasons(): Promise<readonly OverrideReasonOption[]>;
  submitOverride(req: OverrideRequest, idempotencyKey: string): Promise<DecisionSummary>;
  fetchAuditTrail(
    decisionLogId: string
  ): Promise<{ readonly entries: readonly AuditEntry[]; readonly decision: DecisionSummary }>;

  // WS-7.5
  fetchAlertQueue(f: AlertQueueFilters): Promise<Page<Alert>>;
  fetchAlert(alertId: string): Promise<Alert>;
  fetchOutcomeCodes(): Promise<readonly OutcomeCodeOption[]>;
  fetchActionLibrary(): Promise<readonly ActionOption[]>;
  captureDisposition(req: DispositionRequest, idempotencyKey: string): Promise<Alert>;

  // WS-7.4
  fetchDashboardPanels(dashboardId: string): Promise<{ readonly panels: readonly DashboardPanel[] }>;

  // WS-7.2
  fetchDecision(applicationId: string): Promise<DecisionSummary>;
  fetchFeasibleSet(applicationId: string): Promise<FeasibleSet>;
  fetchDisclosure(documentId: string, locale: string): Promise<DisclosureDocument>;
  grantConsent(req: ConsentRequest, idempotencyKey: string): Promise<ConsentArtifact>;
  fetchConversation(conversationId: string): Promise<{ readonly turns: readonly AssistantTurn[] }>;
}

/**
 * Thrown by every `AbsentAdapter` method. Carries the ticket, so the error the
 * screen renders names what is missing rather than saying "failed to fetch".
 */
export class BackendAbsentError extends Error {
  constructor(readonly operation: string) {
    super(
      `${operation}: no API gateway is configured. The P0 gateway route contract ` +
        `is LH-706 and this build ships no fixture data on purpose — see ` +
        `frontend/src/adapters/port.ts.`
    );
    this.name = "BackendAbsentError";
  }
}

export class AbsentAdapter implements Adapter {
  private reject<T>(operation: string): Promise<T> {
    return Promise.reject(new BackendAbsentError(operation));
  }

  fetchQueue(): Promise<Page<QueueItem>> {
    return this.reject("fetchQueue");
  }
  fetchCaseFile(): Promise<UnifiedCaseFile> {
    return this.reject("fetchCaseFile");
  }
  fetchOverrideReasons(): Promise<readonly OverrideReasonOption[]> {
    // Resolves EMPTY rather than rejecting: an empty taxonomy is a real,
    // renderable state that the override control handles by refusing to render
    // (LH-702), and exercising that path is more useful than a stack trace.
    return Promise.resolve([]);
  }
  submitOverride(): Promise<DecisionSummary> {
    return this.reject("submitOverride");
  }
  fetchAuditTrail(): Promise<{
    readonly entries: readonly AuditEntry[];
    readonly decision: DecisionSummary;
  }> {
    return this.reject("fetchAuditTrail");
  }
  fetchAlertQueue(): Promise<Page<Alert>> {
    return this.reject("fetchAlertQueue");
  }
  fetchAlert(): Promise<Alert> {
    return this.reject("fetchAlert");
  }
  fetchOutcomeCodes(): Promise<readonly OutcomeCodeOption[]> {
    // Same reasoning as fetchOverrideReasons: an empty outcome-code vocabulary
    // is LH-502's actual state, and the disposition form must refuse on it.
    return Promise.resolve([]);
  }
  fetchActionLibrary(): Promise<readonly ActionOption[]> {
    return Promise.resolve([]);
  }
  captureDisposition(): Promise<Alert> {
    return this.reject("captureDisposition");
  }
  fetchDashboardPanels(): Promise<{ readonly panels: readonly DashboardPanel[] }> {
    return this.reject("fetchDashboardPanels");
  }
  fetchDecision(): Promise<DecisionSummary> {
    return this.reject("fetchDecision");
  }
  fetchFeasibleSet(): Promise<FeasibleSet> {
    return this.reject("fetchFeasibleSet");
  }
  fetchDisclosure(): Promise<DisclosureDocument> {
    return this.reject("fetchDisclosure");
  }
  grantConsent(): Promise<ConsentArtifact> {
    return this.reject("grantConsent");
  }
  fetchConversation(): Promise<{ readonly turns: readonly AssistantTurn[] }> {
    return this.reject("fetchConversation");
  }
}

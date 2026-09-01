/**
 * Track B adapter — the real gateway behind the `Adapter` port.
 *
 * Thin by design. Every method is one `endpoints.ts` call with no branching, no
 * caching and no shaping: the moment an adapter starts merging two responses or
 * filling a default, it has become a place where a number can be produced
 * without a backend call.
 */

import type { Adapter } from "./port";
import type { GatewayClient } from "../lib/gateway/client";
import * as api from "../lib/gateway/endpoints";
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

export class GatewayAdapter implements Adapter {
  constructor(private readonly client: GatewayClient) {}

  fetchQueue(f: QueueFilters): Promise<Page<QueueItem>> {
    return api.fetchQueue(this.client, f);
  }
  fetchCaseFile(applicationId: string): Promise<UnifiedCaseFile> {
    return api.fetchCaseFile(this.client, applicationId);
  }
  fetchOverrideReasons(): Promise<readonly OverrideReasonOption[]> {
    return api.fetchOverrideReasons(this.client);
  }
  submitOverride(req: OverrideRequest, idempotencyKey: string): Promise<DecisionSummary> {
    return api.submitOverride(this.client, req, idempotencyKey);
  }
  fetchAuditTrail(decisionLogId: string): Promise<{
    readonly entries: readonly AuditEntry[];
    readonly decision: DecisionSummary;
  }> {
    return api.fetchAuditTrail(this.client, decisionLogId);
  }
  fetchAlertQueue(f: AlertQueueFilters): Promise<Page<Alert>> {
    return api.fetchAlertQueue(this.client, f);
  }
  fetchAlert(alertId: string): Promise<Alert> {
    return api.fetchAlert(this.client, alertId);
  }
  fetchOutcomeCodes(): Promise<readonly OutcomeCodeOption[]> {
    return api.fetchOutcomeCodes(this.client);
  }
  fetchActionLibrary(): Promise<readonly ActionOption[]> {
    return api.fetchActionLibrary(this.client);
  }
  captureDisposition(req: DispositionRequest, idempotencyKey: string): Promise<Alert> {
    return api.captureDisposition(this.client, req, idempotencyKey);
  }
  fetchDashboardPanels(dashboardId: string): Promise<{ readonly panels: readonly DashboardPanel[] }> {
    return api.fetchDashboardPanels(this.client, dashboardId);
  }
  fetchDecision(applicationId: string): Promise<DecisionSummary> {
    return api.fetchDecision(this.client, applicationId);
  }
  fetchFeasibleSet(applicationId: string): Promise<FeasibleSet> {
    return api.fetchFeasibleSet(this.client, applicationId);
  }
  fetchDisclosure(documentId: string, locale: string): Promise<DisclosureDocument> {
    return api.fetchDisclosure(this.client, documentId, locale);
  }
  grantConsent(req: ConsentRequest, idempotencyKey: string): Promise<ConsentArtifact> {
    return api.grantConsent(this.client, req, idempotencyKey);
  }
  fetchConversation(conversationId: string): Promise<{ readonly turns: readonly AssistantTurn[] }> {
    return api.fetchConversation(this.client, conversationId);
  }
}

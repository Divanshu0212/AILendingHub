/**
 * WS-7.1.1 - the typed endpoint surface. One function per gateway call.
 *
 * Every call that renders a score, reason or alert passes `modelDerived: true`
 * and names the paths that must carry the {model_id, model_version,
 * decision_log_id} triplet. Those path lists ARE the contract test the phase
 * file asks CI to run - keeping them next to the call means a new endpoint
 * cannot be added without a reviewer seeing whether it was classified.
 *
 * Endpoint paths are provisional (LH-706): P0's gateway is not published, so
 * these are the routes this client expects rather than routes anyone ratified.
 */

import type { GatewayClient } from "./client";
import type {
  ActionOption,
  AgriEvidence,
  Alert,
  AssistantTurn,
  ConsentArtifact,
  ConsentRequest,
  DashboardPanel,
  DecisionSummary,
  DisclosureDocument,
  DispositionRequest,
  FeasibleSet,
  FraudAlert,
  JobStatus,
  OutcomeCodeOption,
  OverrideReasonOption,
  OverrideRequest,
  Subgraph,
} from "./types";

// ------------------------------------------------------------- WS-7.3 queue

export interface QueueFilters {
  readonly product?: string;
  readonly riskBand?: string;
  readonly slaState?: "within" | "due-soon" | "breached";
  readonly cursor?: string;
}

export interface QueueItem {
  readonly applicationId: string;
  readonly product: string;
  readonly riskBand: string;
  readonly receivedAt: string;
  readonly slaDueAt: string;
  readonly slaBreached: boolean;
  /** Backend-supplied "2h 14m" style string. Never composed client-side. */
  readonly slaRemainingDisplay: string;
}

export interface Page<T> {
  readonly items: readonly T[];
  readonly nextCursor: string | null;
}

function query(params: Record<string, string | undefined>): string {
  const parts: string[] = [];
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") parts.push(`${encodeURIComponent(k)}=${encodeURIComponent(v)}`);
  }
  return parts.length ? `?${parts.join("&")}` : "";
}

export function fetchQueue(c: GatewayClient, f: QueueFilters): Promise<Page<QueueItem>> {
  // NOT model-derived: a queue row carries no score. The moment a risk band is
  // added as a model output rather than a policy bucket, this must be
  // reclassified - noted because that is exactly the change that slips through.
  return c.request(`/v1/workbench/queue${query(f as Record<string, string | undefined>)}`);
}

// ------------------------------------------------------- WS-7.3 unified case

/**
 * The single most important screen in the workbench (Phase 7 §4 WS-7.3.2).
 *
 * Each panel is nullable and separately unavailable, because the phase file
 * builds it incrementally: P1 data first, the agri panel when P2 ships, the
 * fraud subgraph when P6's graph layer ships. A null panel renders an explicit
 * "not available in this build" state, never an empty panel - an empty agri map
 * and an agri map for a borrower with no plot look identical.
 */
export interface UnifiedCaseFile {
  readonly applicationId: string;
  readonly decision: DecisionSummary | null;
  readonly bureauSummary: PanelPayload | null;
  readonly cashFlowSummary: PanelPayload | null;
  readonly agriEvidence: AgriEvidence | null;
  readonly fraudAlerts: readonly FraudAlert[];
  readonly fraudSubgraph: Subgraph | null;
  readonly feasibleSet: FeasibleSet | null;
  /** Which panels this deployment can serve, and why not where it cannot. */
  readonly panelAvailability: readonly PanelAvailability[];
}

export interface PanelAvailability {
  readonly panelId: string;
  readonly available: boolean;
  /** Backend-supplied reason, e.g. "phase P2 not gated". Never authored here. */
  readonly unavailableReason: string | null;
}

export interface PanelPayload {
  readonly rows: readonly PanelRow[];
}

export interface PanelRow {
  readonly label: string;
  readonly display: string;
  readonly emphasis: boolean;
}

export function fetchCaseFile(c: GatewayClient, applicationId: string): Promise<UnifiedCaseFile> {
  return c.request(`/v1/workbench/cases/${encodeURIComponent(applicationId)}`, {
    modelDerived: true,
    attributedPaths: [
      "decision.score",
      "decision.probabilityOfDefault",
      "fraudAlerts.[]",
      "fraudSubgraph",
      "feasibleSet.feasible.[]",
      "feasibleSet.recommendation",
    ],
  });
}

// ------------------------------------------------------------ WS-7.3.3 override

export function fetchOverrideReasons(c: GatewayClient): Promise<readonly OverrideReasonOption[]> {
  return c.request("/v1/workbench/override-reasons");
}

/**
 * WS-7.3.3 - the hard requirement.
 *
 * The request type makes reasonCode and modelVersionOverridden non-optional, so
 * an override missing either does not compile. officerId and timestamp are NOT
 * in the request: they are taken from the authenticated session and the server
 * clock respectively. A client-supplied officer id on an audit record is a
 * client-asserted officer id, and a client-supplied timestamp on an override is
 * a client-asserted one - both are the same class of mistake and both would show
 * up in the model-risk team's primary signal as authentic.
 */
export function submitOverride(
  c: GatewayClient,
  req: OverrideRequest,
  idempotencyKey: string
): Promise<DecisionSummary> {
  return c.request(`/v1/workbench/decisions/${encodeURIComponent(req.decisionId)}/override`, {
    method: "POST",
    body: {
      reasonCode: req.reasonCode,
      modelVersionOverridden: req.modelVersionOverridden,
      toOutcome: req.toOutcome,
      note: req.note,
    },
    idempotencyKey,
    modelDerived: true,
    attributedPaths: ["score"],
  });
}

// ---------------------------------------------------------------- audit trail

export interface AuditEntry {
  readonly decisionLogId: string;
  readonly occurredAt: string;
  readonly actor: string;
  readonly summary: string;
  readonly modelName: string | null;
  readonly modelVersion: string | null;
  /** Mirrors `DecisionRecord.prev_hash` - the chain link. */
  readonly prevHash: string | null;
  readonly hash: string;
}

export function fetchAuditTrail(c: GatewayClient, decisionLogId: string): Promise<{
  readonly entries: readonly AuditEntry[];
  readonly decision: DecisionSummary;
}> {
  return c.request(`/v1/audit/${encodeURIComponent(decisionLogId)}`, {
    modelDerived: true,
    attributedPaths: ["decision.score"],
  });
}

// ------------------------------------------------------------ WS-7.5 collections

export interface AlertQueueFilters {
  readonly tier?: "AMBER" | "RED";
  readonly ownerId?: string;
  readonly slaState?: "within" | "due-soon" | "breached";
  readonly cursor?: string;
}

export function fetchAlertQueue(c: GatewayClient, f: AlertQueueFilters): Promise<Page<Alert>> {
  return c.request(`/v1/collections/alerts${query(f as Record<string, string | undefined>)}`, {
    modelDerived: true,
    attributedPaths: ["items.[]"],
  });
}

export function fetchAlert(c: GatewayClient, alertId: string): Promise<Alert> {
  return c.request(`/v1/collections/alerts/${encodeURIComponent(alertId)}`, {
    modelDerived: true,
    attributedPaths: ["$"],
  });
}

export function fetchOutcomeCodes(c: GatewayClient): Promise<readonly OutcomeCodeOption[]> {
  return c.request("/v1/collections/outcome-codes");
}

export function fetchActionLibrary(c: GatewayClient): Promise<readonly ActionOption[]> {
  return c.request("/v1/collections/actions");
}

/**
 * WS-7.5.3 - disposition capture, mandatory before an alert can be closed.
 *
 * There is no `closeAlert` function in this module. That is the enforcement: the
 * only route to a closed alert is through a disposition, so a UI cannot close
 * one without capturing an outcome even by accident. The phase file's warning is
 * that "a UI that lets an agent close an alert without a disposition silently
 * breaks that loop downstream", and the word doing the work is *silently* - the
 * breakage surfaces in P6, months later, as a training set with a hole in it.
 */
export function captureDisposition(
  c: GatewayClient,
  req: DispositionRequest,
  idempotencyKey: string
): Promise<Alert> {
  return c.request(`/v1/collections/alerts/${encodeURIComponent(req.alertId)}/disposition`, {
    method: "POST",
    body: {
      confirmedRelevant: req.confirmedRelevant,
      outcomeCode: req.outcomeCode,
      actionTaken: req.actionTaken,
      note: req.note,
    },
    idempotencyKey,
    modelDerived: true,
    attributedPaths: ["$"],
  });
}

// ------------------------------------------------------------ WS-7.4 dashboards

export function fetchDashboardPanels(
  c: GatewayClient,
  dashboardId: string
): Promise<{ readonly panels: readonly DashboardPanel[] }> {
  return c.request(`/v1/dashboards/${encodeURIComponent(dashboardId)}/panels`);
}

// ------------------------------------------------------------- WS-7.2 customer

export function fetchDecision(c: GatewayClient, applicationId: string): Promise<DecisionSummary> {
  return c.request(`/v1/applications/${encodeURIComponent(applicationId)}/decision`, {
    modelDerived: true,
    attributedPaths: ["score", "probabilityOfDefault"],
  });
}

export function fetchFeasibleSet(c: GatewayClient, applicationId: string): Promise<FeasibleSet> {
  return c.request(`/v1/applications/${encodeURIComponent(applicationId)}/offers`, {
    modelDerived: true,
    attributedPaths: ["feasible.[]", "recommendation"],
  });
}

export function fetchDisclosure(
  c: GatewayClient,
  documentId: string,
  locale: string
): Promise<DisclosureDocument> {
  return c.request(`/v1/documents/${encodeURIComponent(documentId)}${query({ locale })}`);
}

export function grantConsent(
  c: GatewayClient,
  req: ConsentRequest,
  idempotencyKey: string
): Promise<ConsentArtifact> {
  return c.request("/v1/consents", { method: "POST", body: req, idempotencyKey });
}

/** WS-7.2.3 - document upload returns a job; OCR is polled, never awaited. */
export function startDocumentCheck(
  c: GatewayClient,
  applicationId: string,
  uploadId: string
): Promise<JobStatus<unknown>> {
  return c.request(`/v1/applications/${encodeURIComponent(applicationId)}/document-checks`, {
    method: "POST",
    body: { uploadId },
  });
}

// ------------------------------------------------------------- WS-7.2 assistant

export function fetchConversation(
  c: GatewayClient,
  conversationId: string
): Promise<{ readonly turns: readonly AssistantTurn[] }> {
  return c.request(`/v1/assistant/conversations/${encodeURIComponent(conversationId)}`, {
    modelDerived: true,
    attributedPaths: ["turns.[]"],
  });
}

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
import type { FormattedNumber } from "./provenance";
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

// ---------------------------------------------- engine calls (computed routes)
//
// The four gateway routes that return a value something actually computed,
// rather than a refusal naming a ticket. They are grouped here because they
// share a property none of the routes above have: the caller supplies the
// inputs, so the response depends on nothing a committee still owes.
//
// None is `modelDerived`. An EMI is a formula, Louvain is an algorithm, the
// doubly-robust estimator is an estimator and the cadence table is a
// transcription — none came from a fitted model, so none carries an attribution
// triplet and the client must not demand one.

export interface InstalmentQuote {
  readonly amount: FormattedNumber;
  readonly tenorMonths: number;
  readonly annualRate: FormattedNumber;
  readonly emi: FormattedNumber;
  readonly totalInterest: FormattedNumber;
  readonly computedBy: string;
  readonly feasibilityAssessed: boolean;
  readonly feasibilityNote: string;
}

/** `annualRate` is a DECIMAL fraction: 0.125 for 12.5%. The gateway refuses a
 *  value >= 1.0 rather than returning a real EMI for a 1250% rate. */
export function quoteInstalment(
  c: GatewayClient,
  body: { amount: number; annualRate: number; tenorMonths: number }
): Promise<InstalmentQuote> {
  return c.request("/v1/quotes/instalment", { method: "POST", body });
}

export interface CommunityScore {
  readonly communityId: number;
  readonly size: number;
  readonly sharedAttributeEntropy: number;
  readonly internalDensity: number;
  /** Backend-supplied display string. Phase 7 §8: the UI chooses no rounding. */
  readonly internalDensityDisplay: string;
  readonly dominantEdgeType: string;
  readonly nodeTypes: Readonly<Record<string, number>>;
}

export interface CommunityResult {
  readonly nodeCount: number;
  readonly edgeCount: number;
  readonly communityCount: number;
  readonly modularity: number;
  /** Backend-supplied display string — the UI chooses no rounding. */
  readonly modularityDisplay: string;
  readonly modularityIfSingleCommunity: number;
  readonly passes: number;
  readonly communities: readonly CommunityScore[];
  readonly computedBy: string;
  readonly fraudLabelDensity: unknown;
}

export interface GraphNodeInput {
  readonly nodeId: string;
  readonly kind: string;
}

export interface GraphEdgeInput {
  readonly from: string;
  readonly to: string;
  readonly kind: string;
}

export function detectCommunities(
  c: GatewayClient,
  body: { nodes: readonly GraphNodeInput[]; edges: readonly GraphEdgeInput[] }
): Promise<CommunityResult> {
  return c.request("/v1/graph/communities", { method: "POST", body });
}

export interface CadenceActivity {
  readonly name: string;
  readonly frequency: string;
  readonly owningPhase: string;
  readonly conditional: string | null;
  readonly runnable: boolean;
  readonly neverRun: boolean;
  readonly daysLate: number | null;
}

export interface CadenceResult {
  readonly asOf: string;
  readonly graceDays: number;
  /** The activities themselves — the gateway returns the list, not a count. */
  readonly activities: readonly CadenceActivity[];
  readonly runnableCount: number;
  readonly overdueCount: number;
  readonly computedBy: string;
}

export function learningCadence(
  c: GatewayClient,
  body: {
    asOf: string;
    graceDays: number;
    shippedPhases: readonly string[];
    lastRun: Readonly<Record<string, string>>;
  }
): Promise<CadenceResult> {
  return c.request("/v1/learning/cadence", { method: "POST", body });
}

// ------------------------------------------- Track P insights (gateway.demodata)
//
// Figures a committed script computed on real public loan data — vintage
// curves, roll rates, the capture sweep, scorecard performance, real
// applications. Not model-derived: nothing here came from a model held in the
// serving path, so none carries an attribution triplet.
//
// Every payload carries `provenance`, and every screen that renders one shows
// it. A Track P number is a fact about the dataset that produced it, and a
// screenshot of a chart should say which dataset that was.

export interface Provenance {
  readonly track: string;
  readonly dataset: string;
  readonly source: string;
  readonly isGateEvidence: boolean;
  readonly note: string;
}

export interface VintagePoint {
  readonly monthsOnBook: number;
  readonly cumulativeBadRate: number;
  readonly stillAtRisk: number;
}

export interface VintageCurve {
  readonly cohort: string;
  readonly cohortSize: number;
  readonly cohortSizeDisplay: string;
  readonly points: readonly VintagePoint[];
}

export function fetchVintages(
  c: GatewayClient
): Promise<{ curves: readonly VintageCurve[]; provenance: Provenance }> {
  return c.request("/v1/insights/vintages");
}

export interface RollRateCell {
  readonly bucket: string;
  readonly count: number;
  readonly rate: number;
}

export interface RollRateRow {
  readonly from: string;
  readonly total: number;
  readonly to: readonly RollRateCell[];
}

export function fetchRollRates(c: GatewayClient): Promise<{
  buckets: readonly string[];
  rows: readonly RollRateRow[];
  observations: number;
  observationsDisplay: string;
  provenance: Provenance;
}> {
  return c.request("/v1/insights/roll-rates");
}

export interface PortfolioSummary {
  readonly accountMonths: number;
  readonly accountMonthsDisplay: string;
  readonly rowsRead: number;
  readonly rowsReadDisplay: string;
  readonly defaultEvents: number;
  readonly defaultEventsDisplay: string;
  readonly staging: {
    readonly accounts: number;
    readonly counts: Readonly<Record<string, number>>;
    readonly countsDisplay: Readonly<Record<string, string>>;
    readonly undeterminableFraction: number;
    readonly blockers: readonly string[];
  };
  readonly discrimination: {
    readonly challengerCIndex: number | null;
    readonly coxCIndex: number | null;
    readonly coxCIndexDisplay: string;
    readonly integratedBrier: number | null;
    readonly integratedBrierDisplay: string;
    readonly brierByHorizon: readonly { months: number; brier: number }[];
    readonly subjects: number | null;
    readonly outOfSample: boolean | null;
  };
  readonly expectedLoss: null;
  readonly expectedLossNote: string;
  readonly provenance: Provenance;
}

export function fetchPortfolio(c: GatewayClient): Promise<PortfolioSummary> {
  return c.request("/v1/insights/portfolio");
}

export interface CapturePoint {
  readonly threshold: string;
  readonly captureRate: number;
  readonly captureRateDisplay: string;
  readonly medianLeadDays: number;
  readonly accountsAlerted: number;
  readonly captured: number;
  readonly capturedTooLate: number;
}

export function fetchCapture(c: GatewayClient): Promise<{
  points: readonly CapturePoint[];
  reachableDefaults: number;
  defaultsInPanel: number;
  unreachableNote: string;
  provenance: Provenance;
}> {
  return c.request("/v1/insights/capture");
}

export interface ModelSide {
  readonly model: string;
  readonly train: { n: number | null; auc: number | null; giniPoints: number | null };
  readonly test: { n: number | null; auc: number | null; giniPoints: number | null };
}

export function fetchScoring(c: GatewayClient): Promise<{
  champion: ModelSide;
  challenger: ModelSide;
  applicationsScored: number;
  fairness: {
    verdict: string | null;
    nScored: number | null;
    findings: readonly unknown[];
  };
  provenance: Provenance;
}> {
  return c.request("/v1/insights/scoring");
}

export interface QueueRow {
  readonly applicationId: string;
  readonly product: string;
  readonly creditAmount: number;
  readonly creditDisplay: string;
  readonly incomeDisplay: string;
  readonly annuityDisplay: string;
  readonly affordabilityBand: string;
  readonly education: string;
  readonly observedOutcome: string;
}

export function fetchInsightQueue(
  c: GatewayClient,
  limit = 25
): Promise<{
  items: readonly QueueRow[];
  totalAvailable: number;
  scoreShown: boolean;
  scoreNote: string;
  provenance: Provenance;
}> {
  return c.request(`/v1/insights/queue?limit=${limit}`);
}

export interface AgriObservationPoint {
  readonly observedOn: string;
  readonly ndvi: number;
  readonly spi: number;
  readonly cloudFraction: number;
  readonly usable: boolean;
}

export function fetchAgriDemo(
  c: GatewayClient,
  plotId: string
): Promise<{
  plotId: string;
  illustrative: boolean;
  illustrativeReason: string;
  polygonProvenance: string;
  areaHectares: number;
  series: readonly AgriObservationPoint[];
  usableObservations: number;
  totalObservations: number;
  derived: {
    yieldEstimate: null;
    expectedIncome: null;
    landQualityIndex: null;
    note: string;
  };
}> {
  return c.request(`/v1/insights/agri/${encodeURIComponent(plotId)}`);
}

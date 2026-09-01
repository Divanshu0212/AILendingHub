/**
 * WS-7.1.1 - the gateway's response shapes, as the four surfaces consume them.
 *
 * Every type here mirrors a dataclass that already exists in `src/lending_hub/`.
 * Where it mirrors one, the Python class is named. Where a field exists here and
 * not there, it is marked and the reason is stated - those are the places the
 * gateway must add something, and each is a finding in Phase_7_FINDINGS.md.
 *
 * Deliberately NOT here: any computed field. There is no `emi` derived from
 * amount/rate/tenor, no `totalPayable`, no `eligibleAmount`. Those come from
 * `reco.feasible` and arrive as `FormattedNumber`.
 */

import type { Attributed, FormattedNumber, ModelAttribution } from "./provenance";

// ---------------------------------------------------------------- freshness

/**
 * Mirrors nothing in the backend yet - this is the gateway contract the
 * freshness badge needs, and it does not exist. SRS §9.2 RD-1 sets dashboard
 * freshness <= 5 min and §9.3.1 lands aggregates in an OLAP store; neither says
 * what the API returns when the pipeline is behind.
 *
 * Three states rather than a boolean, because "stale" and "unknown" are
 * different failures and only the second is a monitoring gap. A badge that
 * renders `unknown` as `fresh` is the exact behaviour Phase 7 §4 WS-7.4.3 calls
 * manufacturing false confidence.
 */
export type FreshnessState = "fresh" | "stale" | "unknown";

export interface Freshness {
  readonly state: FreshnessState;
  /** ISO-8601 instant the underlying data was last advanced, or null if unknown. */
  readonly asOf: string | null;
  /** Backend-rendered relative string ("4 min ago"). Never composed here. */
  readonly display: string;
  /**
   * The tolerance this state was judged against, so the badge can say what
   * "stale" meant. Backend-supplied: the threshold is a policy value
   * (LH-703), not a UI constant.
   */
  readonly toleranceDisplay: string | null;
}

/** Every panel-shaped payload carries one. WS-7.4.3 makes this non-negotiable. */
export interface WithFreshness {
  readonly freshness: Freshness;
}

// ------------------------------------------------------------- reason codes

/**
 * Mirrors `lending_hub.decisionlog.record.ReasonCode` plus the rendered sentence.
 *
 * `sentence` is the ONLY place customer-facing reason wording appears in this
 * codebase, and it is a field on a response, never a literal. It is nullable
 * because `config/reason_codes.yaml` ships every wording as
 * TBD[Compliance, LH-203] and `scoring.reasons` raises rather than rendering a
 * placeholder. The UI must mirror that refusal: a null sentence renders the code
 * and an explicit "wording pending ratification" state, never a drafted
 * paraphrase.
 */
export interface ReasonCode {
  readonly code: string;
  /** Signed SHAP contribution; sign convention is the backend's. */
  readonly contribution: number | null;
  /** "model" | "rule" - mirrors ReasonCode.source. */
  readonly source: string;
  /**
   * Display rank within the reason set, server-supplied.
   *
   * Not derived from array position. SRS §4.3.1 defines the ranking rule
   * (points-below-max) and the SRS change log records that rule being corrected
   * in v1.2 — a frontend that numbers the array has adopted the transport order
   * as the adverse-action order. See P7-F6.
   */
  readonly rankDisplay: string;
  /** Legally templated sentence from the document registry. Null = unratified. */
  readonly sentence: string | null;
  /** Registry document id + version the sentence came from. Null iff sentence is. */
  readonly copyRef: DocumentRef | null;
}

// -------------------------------------------------------- document registry

/**
 * WS-7.1.5 - the versioned, dated document registry Module 6/P5 uses for its
 * corpus. It does not exist (LH-701). This is its interface.
 *
 * `effectiveFrom` is the field that makes this a control rather than a CMS: SRS
 * §8.3 requires document-effective-date discipline, and a disclosure rendered
 * from a document whose effective date has passed is the UI equivalent of an
 * ungrounded LLM answer - which is precisely the framing Phase 7 §4 WS-7.1.5
 * uses.
 */
export interface DocumentRef {
  readonly documentId: string;
  readonly version: string;
  readonly effectiveFrom: string;
  readonly effectiveTo: string | null;
  readonly locale: string;
}

export interface DisclosureDocument extends DocumentRef {
  /** Rendered body, registry-supplied. Never authored in this repository. */
  readonly body: string;
  /** Whether this document is ratified for display in this locale. */
  readonly ratified: boolean;
}

// --------------------------------------------------------------- decisions

export type DecisionOutcome = "approve" | "decline" | "refer" | "pending";

/**
 * Mirrors `lending_hub.decisionlog.record.DecisionRecord`, projected for display.
 *
 * `score` is `Attributed<number>` rather than `number`: the type is what stops a
 * screen rendering a score with no model behind it.
 */
export interface DecisionSummary {
  readonly decisionId: string;
  readonly applicationId: string;
  readonly decidedAt: string;
  readonly outcome: DecisionOutcome;
  /** "system" | "officer" | "policy_rule" - mirrors record.Actor. */
  readonly decidedBy: string;
  readonly score: Attributed<number> | null;
  readonly scoreDisplay: string | null;
  readonly probabilityOfDefault: Attributed<FormattedNumber> | null;
  readonly reasonCodes: readonly ReasonCode[];
  readonly reasonAttribution: ModelAttribution | null;
  readonly policyVersion: string;
  readonly rulesFired: readonly string[];
  readonly consentIds: readonly string[];
  readonly override: OverrideRecord | null;
  readonly models: readonly ModelRefFull[];
}

/** Mirrors `ModelRef` in full - shown on the audit-trail screen only. */
export interface ModelRefFull {
  readonly name: string;
  readonly version: string;
  readonly registryStage: string;
  readonly codeCommit: string;
  readonly dataSnapshot: string;
  readonly configHash: string;
  readonly definitionsFingerprint: string;
}

/**
 * WS-7.3.3 - what an override must record. Mirrors `DecisionRecord.override`,
 * which is an untyped `dict` in the backend; this is the shape the workbench
 * sends, and typing it here is the reason the officer form cannot omit a field.
 *
 * The phase file requires "a reason code and logs officer ID, timestamp, and the
 * model version overridden". All four are required and none is optional.
 */
export interface OverrideRecord {
  readonly overriddenAt: string;
  readonly officerId: string;
  readonly reasonCode: string;
  readonly modelVersionOverridden: string;
  readonly fromOutcome: DecisionOutcome;
  readonly toOutcome: DecisionOutcome;
  /** Free-text justification. Optional; the reason CODE is not. */
  readonly note: string | null;
}

/** The body of an override request. Every field non-optional by construction. */
export interface OverrideRequest {
  readonly decisionId: string;
  readonly reasonCode: string;
  readonly modelVersionOverridden: string;
  readonly toOutcome: DecisionOutcome;
  readonly note: string | null;
}

/**
 * The ratified list of override reason codes. Comes from the gateway; there is
 * no client-side list, because an override taxonomy the model-risk team reads as
 * its primary signal cannot be a constant in a component (LH-702).
 */
export interface OverrideReasonOption {
  readonly code: string;
  readonly label: string;
  readonly requiresNote: boolean;
}

// ------------------------------------------------------------------- alerts

/** Mirrors `lending_hub.ews.routing.Tier`. NONE never reaches the UI. */
export type AlertTier = "AMBER" | "RED";

/**
 * Mirrors `lending_hub.ews.routing.Alert`.
 *
 * The Python constructor refuses an alert with no owner, no SLA, no recommended
 * action or no trigger reasons. Those are non-optional here for the same reason:
 * the distinction between an alert and a notification stops being visible the
 * moment both are in the same queue.
 */
export interface Alert {
  readonly alertId: string;
  readonly accountId: string;
  readonly tier: AlertTier;
  readonly raisedAt: string;
  readonly triggerReasons: readonly string[];
  /** Mirrors `Alert.pd_delta`; null when the alert did not come from velocity. */
  readonly pdDelta: Attributed<FormattedNumber> | null;
  readonly recommendedAction: string;
  readonly slaHours: number;
  readonly slaDueAt: string;
  readonly ownerId: string;
  readonly signalIds: readonly string[];
  readonly disposition: Disposition | null;
  /**
   * Mirrors `Alert.breached_sla(now=)`. SERVER-computed - the frontend does not
   * compare timestamps to decide whether an SLA is breached, because that is
   * arithmetic on a compliance number (§8 exit criterion 2).
   */
  readonly slaBreached: boolean;
  readonly attribution: ModelAttribution;
}

/** Mirrors `lending_hub.ews.routing.Disposition`. */
export interface Disposition {
  readonly alertId: string;
  readonly disposedAt: string;
  readonly officerId: string;
  readonly confirmedRelevant: boolean;
  readonly outcomeCode: string;
}

/** The body of a disposition capture. Mirrors the Python `__post_init__` refusal. */
export interface DispositionRequest {
  readonly alertId: string;
  readonly confirmedRelevant: boolean;
  readonly outcomeCode: string;
  readonly actionTaken: string;
  readonly note: string | null;
}

/**
 * Gateway-supplied outcome-code vocabulary. `ews.routing.Disposition` requires a
 * non-empty `outcome_code` and defines no vocabulary; the action library and its
 * SLAs are LH-502, and the outcome codes belong with them. No list here.
 */
export interface OutcomeCodeOption {
  readonly code: string;
  readonly label: string;
  readonly closesAlert: boolean;
}

/** Gateway-supplied action library. LH-502 - never a constant in this codebase. */
export interface ActionOption {
  readonly actionId: string;
  readonly label: string;
  readonly slaHours: number;
}

// -------------------------------------------------------------- offers

/** Mirrors `lending_hub.reco.feasible.Offer` plus backend-computed display fields. */
export interface Offer {
  readonly offerId: string;
  readonly product: string;
  readonly amount: FormattedNumber;
  readonly tenorMonths: number;
  readonly annualRate: FormattedNumber;
  /** From `Offer.emi` - computed in `reco.feasible`, NEVER here. */
  readonly emi: FormattedNumber;
  readonly totalInterest: FormattedNumber;
  /** Mirrors `reco.bandit.BanditDecision.template_id`. */
  readonly templateId: string | null;
  readonly attribution: ModelAttribution;
}

/** Mirrors `lending_hub.reco.feasible.ConstraintResult`. */
export interface ConstraintResult {
  readonly name: string;
  readonly value: FormattedNumber;
  readonly limit: FormattedNumber;
  readonly satisfied: boolean;
  readonly detail: string;
  readonly headroom: FormattedNumber;
}

/** Mirrors `lending_hub.reco.feasible.Assessment`. */
export interface OfferAssessment {
  readonly offer: Offer;
  readonly feasible: boolean;
  readonly constraints: readonly ConstraintResult[];
  readonly bindingConstraintName: string | null;
  readonly reason: string;
}

/**
 * Mirrors `lending_hub.reco.feasible.FeasibleSet`.
 *
 * Both the customer app (WS-7.2.4, read-only) and the officer workbench
 * (WS-7.3.4, write) render this, and neither may select outside `feasible`. The
 * type carries `rejected` so a UI can EXPLAIN why an offer is absent, which is
 * the difference between a constrained picker and a picker that looks broken.
 */
export interface FeasibleSet {
  readonly applicantId: string;
  readonly feasible: readonly Offer[];
  readonly rejected: readonly OfferAssessment[];
  readonly isEmpty: boolean;
  /** Present only when a bandit chose. Mirrors `BanditDecision`. */
  readonly recommendation: BanditRecommendation | null;
}

/**
 * Mirrors `lending_hub.reco.bandit.BanditDecision`.
 *
 * `propensity` is non-optional here for the same reason it is non-optional
 * there: Phase 4 §8's "propensity logging completeness = 100%" is a property of
 * the type. A recommendation that reached a screen without one would be a
 * decision P6 cannot reweight.
 */
export interface BanditRecommendation {
  readonly decisionId: string;
  readonly templateId: string;
  readonly propensity: number;
  readonly isExploration: boolean;
  readonly consideredArms: readonly string[];
  readonly attribution: ModelAttribution;
}

// --------------------------------------------------------------- consent

/**
 * Mirrors the P0 WS-0.3 consent artifact. WS-7.2.2 logs this "with the same
 * rigor as a credit decision", so it carries an id that the decision record
 * references (`DecisionSummary.consentIds`).
 */
export interface ConsentArtifact {
  readonly consentId: string;
  readonly purpose: string;
  readonly grantedAt: string;
  readonly expiresAt: string | null;
  readonly document: DocumentRef;
  readonly withdrawn: boolean;
}

export interface ConsentRequest {
  readonly purposeId: string;
  readonly documentId: string;
  readonly documentVersion: string;
  readonly accepted: boolean;
}

// --------------------------------------------------------------- assistant

/**
 * WS-7.2.7 / SRS §8.3. Every claim renders with its citation affordance or an
 * explicit unverified state.
 *
 * `citations` being empty is a RENDERABLE state, not an error, and the component
 * must show it as unverified. Phase 7 §4 is explicit that the frontend "never
 * suppresses or paraphrases a missing citation into a confident-looking
 * sentence", which means the UI cannot drop an uncited claim either - dropping
 * it is also a way of hiding that it was made.
 */
export interface AssistantClaim {
  readonly claimId: string;
  readonly text: string;
  readonly citations: readonly Citation[];
  readonly verified: boolean;
}

export interface Citation {
  readonly citationId: string;
  readonly label: string;
  readonly document: DocumentRef;
  readonly snippet: string | null;
}

export interface AssistantTurn {
  readonly turnId: string;
  readonly role: "customer" | "officer" | "assistant";
  readonly claims: readonly AssistantClaim[];
  readonly attribution: ModelAttribution | null;
}

// ------------------------------------------------------------- fraud / graph

/** WS-7.3.2 fallback view - the P1-era alert list, before P6's graph layer. */
export interface FraudAlert {
  readonly fraudAlertId: string;
  readonly layer: string;
  readonly ruleId: string;
  readonly severity: string;
  readonly raisedAt: string;
  readonly explanation: string;
  readonly attribution: ModelAttribution;
}

/** WS-7.3.2 - activates only when P6's graph layer ships. */
export interface Subgraph {
  readonly nodes: readonly SubgraphNode[];
  readonly edges: readonly SubgraphEdge[];
  readonly attribution: ModelAttribution;
}

export interface SubgraphNode {
  readonly nodeId: string;
  readonly kind: string;
  /** Tokenised. SRS §11.4 - no raw PII crosses this boundary. */
  readonly label: string;
  readonly isFocus: boolean;
}

export interface SubgraphEdge {
  readonly from: string;
  readonly to: string;
  readonly kind: string;
}

// ------------------------------------------------------------- agri evidence

/** WS-7.3.2 agri panel; WS-7.2 evidence map. Activates when P2 ships. */
export interface AgriEvidence extends WithFreshness {
  readonly plotId: string;
  /**
   * GeoJSON of an OBSERVED or WALKED polygon. Phase 2 §8 do-not-invent: "any
   * plot polygon not observed or walked". Null means no polygon exists and the
   * map must render an explicit absence, never a circle around a village
   * centroid - which is what `agri.registry.VillageLocation.area_hectares`
   * raises rather than returning.
   */
  readonly polygon: unknown | null;
  readonly series: readonly AgriObservation[];
}

export interface AgriObservation {
  readonly observedOn: string;
  readonly ndvi: number | null;
  readonly evi: number | null;
  readonly spei3: number | null;
  readonly cloudMasked: boolean;
}

// ------------------------------------------------------------- dashboards

/** WS-7.4 - a rendered panel. The gateway computes; this carries. */
export interface DashboardPanel extends WithFreshness {
  readonly panelId: string;
  readonly title: string;
  readonly metrics: readonly DashboardMetric[];
  readonly drillThroughHref: string | null;
  readonly attribution: ModelAttribution | null;
}

export interface DashboardMetric {
  readonly key: string;
  readonly label: string;
  readonly value: FormattedNumber;
  /** Backend-computed delta vs baseline. Not derived from two fetched values. */
  readonly delta: FormattedNumber | null;
}

// ------------------------------------------------------------- async jobs

/** WS-7.1.4 - no UI request blocks > 2 s (§11.6c). */
export type JobState = "queued" | "running" | "succeeded" | "failed";

export interface JobStatus<T = unknown> {
  readonly jobId: string;
  readonly state: JobState;
  /** 0-100, backend-computed. Null when the job cannot estimate. */
  readonly percentComplete: number | null;
  readonly result: T | null;
  readonly errorCode: string | null;
  /** Server-supplied poll interval. The client does not invent a backoff. */
  readonly retryAfterMs: number;
}

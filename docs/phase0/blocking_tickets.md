# Phase 0 — Blocking ticket register

Every `TBD[owner, ticket-id]` placeholder in the tree must appear here.
`make grounding` fails on any placeholder that does not.

Master §2 rule 1: a value that is neither `[SPEC]`, `[DATA]`, nor `[POLICY]` stops the
work. This register is the list of stops — it is the honest measure of how much of
Phase 0 is waiting on the bank rather than on engineering.

| Ticket | Owner | Blocks | What is needed | Status |
|---|---|---|---|---|
| LH-101 | Fraud Head | Appendix A *Confirmed fraud*; P1 fraud labels | The approved fraud-desk disposition taxonomy — which codes constitute confirmed fraud. Suspicion is explicitly not a label. | open |
| LH-102 | Agri Credit Head | Appendix A *Agri season*; all of P2 | Ratified zone crop calendar: Kharif/Rabi/Zaid boundaries per zone. | open |
| LH-103 | Credit Policy + Finance Controller | Appendix A *Default / Bad* completeness | CBS reason codes that mark (a) distress restructuring and (b) write-off. The definition is `[SPEC]`; the code set that identifies it in the source system is a bank mapping. | open |
| LH-110 | DPO | Every `config/sources/*.yaml`; feature-store column allowlist | PII classification per source and per column. Named in the Phase 0 do-not-invent list. | open |
| LH-111 | DPO + Compliance | Per-table retention config; lakehouse purge jobs | Retention periods. Floor is the SRS CS-7 duty to reconstruct any decision for >= 8 years; the DPDP erasure right and RBI retention duties have to be reconciled per table. | open |
| LH-112 | Compliance | Account Aggregator consent artifact | Consent wording for alternative-data collection under DPDP purpose limitation. | open |
| LH-120 | Named source owners | Phase 0 entry criteria | Written data-sharing approvals and named business/technical owners for CBS, LOS, collections, bureau, AA, KYC. Phase 0 §3 lists these as *entry* criteria — the phase is formally not startable until they land. | open |
| LH-121 | Program (doc conflict) | Source registry completeness | SRS §2.1 lists eight sources and does not include LOS or collections, but Phase 0 §2 requires both as inputs and WS-0.1.3 builds the identity spine across CBS-LOS-collections. Registered both; SRS §2.1 needs the two rows added. Raised per Master §1 precedence (conflicts become tickets, never silent fixes). | open |
| LH-122 | Program (doc correction) | WS-0.1.3 join-rate gate | Phase 0 WS-0.1.3 sets the gate as ">= 99.5% of active loans join across the three systems". A healthy loan has no collections record, so that metric measures the delinquency rate, not data quality. Implemented as three separately-mandatory directions (loan→application, collections→loan, customer consistency); the phase doc needs the same correction. | open |
| LH-130 | Data Governance Council | Identity-spine survivorship | Attribute-level exceptions to system-of-record precedence — e.g. whether a collections-updated contact address supersedes the CBS address. Phase 0 §8 puts survivorship exceptions on the do-not-invent list. | open |
| LH-140 | Security Architecture | PII tokenization service | The production tokenization key and its KMS/HSM custody, rotation and re-tokenization procedure. Rotating the key changes every token, so the rotation plan has to say what happens to already-tokenized history — a key rotated without one silently breaks every join in the feature store. | open |
| LH-150 | Finance Controller | GL reconciliation (WS-0.1.5) | The product/balance-type to GL-account mapping. Phase 0 §8 puts GL mapping rules on the do-not-invent list, and a reconciliation built on a guessed mapping produces agreement that means nothing. | open |

## Why LH-103 exists

Appendix A names "restructure-due-to-distress" and "write-off" as default triggers. Both
are `[SPEC]` as *concepts*. Neither is computable until someone states which CBS reason
codes carry those meanings — and a restructure code set that wrongly includes voluntary
restructures inflates the bad rate across every model in the program.

`lending_hub.definitions.is_default` therefore accepts the flags as inputs rather than
deriving them, so the ungrounded part is isolated at the ETL boundary (Silver layer)
instead of being buried in the target definition.

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

## Why LH-103 exists

Appendix A names "restructure-due-to-distress" and "write-off" as default triggers. Both
are `[SPEC]` as *concepts*. Neither is computable until someone states which CBS reason
codes carry those meanings — and a restructure code set that wrongly includes voluntary
restructures inflates the bad rate across every model in the program.

`lending_hub.definitions.is_default` therefore accepts the flags as inputs rather than
deriving them, so the ungrounded part is isolated at the ETL boundary (Silver layer)
instead of being buried in the target definition.

# Identity-spine fixtures (Track A)

Synthetic data. Master §2 rule 3 confines it to `tests/fixtures/`, and
`lending_hub.identity.ports.FixtureReader` refuses to read a path outside this tree.

These rows exist to exercise the audit's **failure classification**, not to look like a
real portfolio. Every root cause the report can emit is represented at least once, so a
change that stops detecting one fails a test instead of silently reporting a better
number:

| Row | Exercises |
|---|---|
| `LN-1001` … `LN-1004` | clean three-way and two-way joins |
| `LN-2001` | active loan with no LOS application → `missing_application` |
| `LN-3001` | customer key differs between CBS and LOS → `customer_disagreement` |
| `CS-9001` | collections case for a loan absent from CBS → `orphan_collections_case` |
| `NA`, `0`, `X` | placeholder and truncated keys → `unusable_key` |
| `LN-4001` | inactive loan — excluded from the denominator entirely |

Nothing here may be copied into a training table, a Silver table, or a report.

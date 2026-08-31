# Fannie Mae format fixture (Track A)

Synthetic, in the Data Dynamics single-family performance layout (113 pipe-delimited
fields, no header). Master §2 rule 3 confines it here.

**This is not Fannie Mae data.** It is six hand-built loans in Fannie's *format*, one per
label path the adapter has to get right:

| Loan | Exercises |
|---|---|
| `LN00000000001` | clean 12 months → `GOOD` |
| `LN00000000002` | reaches status `03` (90+ DPD) → `BAD` |
| `LN00000000003` | peaks at status `02` (60-89 DPD) → `INDETERMINATE` |
| `LN00000000004` | prepays (ZB `01`) inside the window → determined `GOOD`, **not** censored |
| `LN00000000005` | REO disposition (ZB `09`) → `BAD` via the write-off arm |
| `LN00000000006` | `XX` status throughout → **censored**, because no month was observed; `max_dpd == 0` here means "nothing seen", not "nothing happened" |

The real extracts live in `datasets/` (gitignored) and are Track P (ADR-0004).

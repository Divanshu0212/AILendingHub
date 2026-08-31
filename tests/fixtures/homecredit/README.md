# Home Credit adapter fixtures

Six hand-written applications in the Home Credit `application_train.csv` column
layout, covering one adapter behaviour each. Synthetic (Master §2 rule 3) —
Track A only, never a training input.

| Row | Covers |
|---|---|
| 900001 | An ordinary labelled positive |
| 900002 | A missing `EXT_SOURCE_3` — must become a separate bin, never an imputed zero |
| 900003 | A missing `EXT_SOURCE_1` in a different column, so a fix that hard-codes one column fails |
| 900004 | `CODE_GENDER = XNA` and `DAYS_EMPLOYED = 365243` — an absent gender that is not a third group, and a pensioner sentinel that is not a thousand-year tenure |
| 900005 | Values far outside plausible range, to exercise clipping |
| 900006 | No `TARGET` — must be skipped and counted, never labelled good |

The real extract is 307,511 rows and is gitignored; see
[docs/phase0/DATA_SOURCING.md](../../../docs/phase0/DATA_SOURCING.md).

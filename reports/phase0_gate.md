# Phase 0 — gate evidence pack

Generated 2026-09-01T17:42:01.063827+00:00 by `tools/gate_report.py`.

Per ADR-0003, **only Track B numbers are gate evidence.** A Track A result
describes the code that computed it, not the portfolio.

## Numeric gates (Phase 0 §7)

| Gate | Workstream | Track | Result | State |
|---|---|---|---|---|
| Join rate ≥ 99.5% | WS-0.1.3 | A | loan_to_application=83.3333%, collections_to_loan=66.6667%, customer_consistency=80.0000% | **fail (Track A — not gate evidence)** |
| GL delta ≤ 0.1% | WS-0.1.5 | — | — | **blocked** on LH-150, LH-120 |
| Stream freshness < 60 s | WS-0.1.4 | — | — | **not run** |
| Scorecard parity ≥ 99.9% | WS-0.4 | A | 100.0000% | **pass (Track A — not gate evidence)** |
| Serving latency p99 | WS-0.2.4 | A | fetch p99=0.0022410022211261094ms, score p99=0.000166997779160738ms | **pass (Track A — not gate evidence)** |

Gates with Track B evidence: **0 of 5**.

## Outstanding blockers

See [blocking_tickets.md](../docs/phase0/blocking_tickets.md). Phase 0 cannot
be exited until the four numeric gates have Track B evidence — see
[STATUS.md](../docs/phase0/STATUS.md).

## Also required in the pack (Master §3.1)

- Model cards for every model — none exist yet; Phase 0 ships no models by design.
- Independent validation report — not applicable until a model exists.
- Security and privacy sign-off — blocked on LH-110, LH-111, LH-140.
- Decision-log spot-audit — `lending_hub.decisionlog.spot_audit`, needs logged decisions.


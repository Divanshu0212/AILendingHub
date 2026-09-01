"""Portfolio Brain — behavioural PD, survival, LGD/EAD, staging, dashboards.

Phase 3 (SRS §7 default prediction, SRS §9 real-time risk dashboards). This is
the read side of the hub: P1 decides whether to lend, P3 says what the resulting
book is worth and how it is moving.

Every module here is a stdlib-only reference implementation on the interfaces
Track B swaps out (ADR-0003), and every module docstring names both the
workstream it implements and what it deliberately does not port.

Workstream: WS-3.1, WS-3.2
"""

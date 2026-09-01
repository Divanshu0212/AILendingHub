"""Agri Intelligence — satellite, weather, crop and geo.

Phase 2 (SRS §3 agricultural lending intelligence). This is the evidence side of
the hub: P1 decides whether to lend against a *file*, and P2 says what the land
behind that file actually did over the last five seasons.

Every module here is a stdlib-only reference implementation on the interfaces
Track B swaps out (ADR-0003), and every module docstring names both the
workstream it implements and what it deliberately does not port.

**Read [ADR-0013](../../../docs/adr/0013-phase2-agri-track.md) before quoting
anything from this package.** Phase 2 has no Track P: there is no imagery, no
agri portfolio and no ratified crop calendar in this repository, so unlike
Phase 1 and Phase 3 there is no real-data run behind these modules. The
computations are verified against known-answer cases; nothing here has been
exercised on a scene.

Workstream: WS-2.1, WS-2.2, WS-2.3, WS-2.4
"""

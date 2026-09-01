"""Early-Warning System — signals, triggers, tiering and routing.

Phase 4 Workstream A (SRS §10). This is where the platform stops describing the
book and starts acting on it: an account-level system that flags likely
defaulters 30-120 days ahead and hands a human a recommended intervention with
an SLA.

Two things separate this package from every one before it.

**It is an action system.** Phase 4 §1: "every automated action has an owner, an
SLA, and a captured outcome." So an alert that cannot name its owner, its SLA or
where its outcome will be recorded is not a weaker alert — it is a notification,
and `ews.routing` refuses to produce one.

**Its own evaluation depends on data it cannot generate.** Signal precision is
defined against confirmed-relevant dispositions from a collections desk, and
there is no desk ([ADR-0014](../../../docs/adr/0014-phase4-action-systems-track.md)).
Nothing here simulates one. The detection layer is measurable on the Track P
panel and is measured; the disposition layer is not measurable and says so.

Workstream: WS-4.A (SRS §10)
"""

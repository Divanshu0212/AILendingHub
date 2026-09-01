"""Recommendation engine — feasible set, pricing, take-up, bandit.

Phase 4 Workstream B (SRS §6). Selects product, amount, tenor and price inside
hard policy constraints, with a learning layer that may explore **only within
the feasible set** — Phase 4 §5 Step 4: "exploration can never breach
affordability or policy."

The ordering in this package is the phase file's and it is deliberate:
`feasible` ships first and alone is useful, `pricing` reads ALM config and never
constants, `takeup` ranks, and `bandit` explores. Each layer can be deployed
without the one after it, which is what makes the shipping ladder in §6 real
rather than aspirational.

**Propensity logging is a constructor invariant here, not a logging call.**
Phase 4 §5 Step 4 and §8 both require 100% completeness because P6's off-policy
evaluation is impossible without it, and a requirement enforced by remembering
to call a logger is a requirement that holds until the first refactor.

Workstream: WS-4.B (SRS §6)
"""

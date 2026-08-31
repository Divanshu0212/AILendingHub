"""Adapters for externally-sourced reference datasets (Track P — ADR-0004).

Real data, but not this bank's data. Each adapter maps an external schema onto
``lending_hub.definitions`` so that Appendix A's label logic runs against real
loans. Numbers produced here are stamped Track P and are never gate evidence.

The CLI module :mod:`lending_hub.sources.profile` is not re-exported, so
``python -m`` does not double-import it.

Workstream: WS-0.1.1 · ADR-0004
"""

from . import fanniemae

__all__ = ["fanniemae"]

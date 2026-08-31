"""Fraud detection — layers 1 and 2, entity resolution, document checks, routing.

Phase 1 WS-1.2 (SRS §5). Track A reference implementations behind the interfaces
the Track B stack (splink, Flink, LightGBM, scikit-learn, docTR) plugs into —
see ADR-0003 and ADR-0011.

Workstream: WS-1.2
"""

from .entity_resolution import (
    GEOHASH_PRECISION,
    MATCH_THRESHOLD,
    ApplicationRecord,
    Edge,
    EdgeType,
    EntityGraph,
    EntityResolutionError,
    MatchScore,
    Node,
    NodeType,
    build_graph,
    candidate_pairs,
    compare,
    geohash,
    jaro,
    jaro_winkler,
    normalise_account,
    normalise_name,
    normalise_phone,
    resolve,
)

__all__ = [
    "GEOHASH_PRECISION",
    "MATCH_THRESHOLD",
    "ApplicationRecord",
    "Edge",
    "EdgeType",
    "EntityGraph",
    "EntityResolutionError",
    "MatchScore",
    "Node",
    "NodeType",
    "build_graph",
    "candidate_pairs",
    "compare",
    "geohash",
    "jaro",
    "jaro_winkler",
    "normalise_account",
    "normalise_name",
    "normalise_phone",
    "resolve",
]

"""Louvain community detection over the P1 entity graph — Phase 6 WS-6.1.

WS-6.1 step 1: *"Louvain community scoring (Blondel et al., arXiv:0803.0476):
dense clusters scored by fraud-label density and shared-attribute entropy; cheap
and explainable — deploy first."*

**Deploy first** is the instruction, and this module is the reason Phase 6 is not
entirely a contract layer. Louvain is *unsupervised*: it partitions a graph by
modularity alone. Every other WS-6.1 component — GraphSAGE's node scores,
CARE-GNN's neighbour filtering — trains on the fraud-desk dispositions that do
not exist here (ADR-0016). Community detection does not, so it runs on the real
:class:`~lending_hub.fraud.entity_resolution.EntityGraph` today, and P1 fixed
that schema for exactly this reuse.

The split inside this module is therefore the phase's split in miniature
--------------------------------------------------------------------------
* :func:`louvain` and :func:`modularity` are **complete**. Given a graph, the
  partition and its modularity are determined, and the tests pin them against
  hand-computed values on graphs small enough to verify by inspection.
* :func:`score_communities` is **half complete**. Of the two scoring inputs the
  phase file names, shared-attribute entropy is computable from the graph, and
  **fraud-label density is not** — it needs a label per node, which is a
  disposition. So :class:`CommunityScore` carries the entropy and refuses the
  density, rather than scoring on entropy alone and calling the result a fraud
  score.

That refusal is the load-bearing one. A community score built from the half of
the recipe that happens to be computable would rank communities plausibly,
because dense shared-attribute clusters *are* suspicious — and it would be
presented as the phase file's scorer while measuring something else entirely.

What this ports, and what it does not
---------------------------------------
Blondel et al.'s two-phase algorithm: local modularity optimisation by greedy
node moves, then graph aggregation, repeated until modularity stops improving.
Stdlib-only, per ADR-0003.

Not ported: the resolution parameter of the Reichardt–Bornholdt generalisation
(Louvain proper is γ=1, which is what the paper describes and what the phase
file cites), Leiden's refinement pass, and any parallel or randomised
node-ordering scheme. Node order is **sorted**, not shuffled: Louvain's result
depends on the order nodes are visited, and a randomised order would make the
partition irreproducible across runs — unacceptable for a signal that feeds a
fraud alert an officer must be able to re-derive.

Workstream: WS-6.1 · SRS §5.3.3
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from lending_hub.fraud.entity_resolution import EntityGraph


class CommunityError(Exception):
    """Raised when a community quantity is requested that the graph cannot support."""


#: Modularity gain below which a Louvain pass stops. [SPEC] Blondel et al. use a
#: small positive epsilon to terminate; the exact value affects only how many
#: near-zero-gain passes run, never the partition's validity.
MIN_MODULARITY_GAIN = 1e-7

#: Communities smaller than this are reported but never scored as rings.
#: [SPEC] A "community" of two nodes joined by one shared phone is an edge, and
#: the entropy of a two-node attribute set is not a meaningful quantity. The
#: threshold at which a ring is *alerted on* is a different question and is
#: LH-805, since it consumes the fraud alert budget (LH-206).
MIN_COMMUNITY_SIZE = 3


@dataclass(frozen=True)
class Partition:
    """An assignment of nodes to communities, with the modularity it achieves."""

    communities: tuple[frozenset[str], ...]
    modularity: float
    passes: int
    """Louvain aggregation levels run. Reported because a single-pass result on
    a graph that should have aggregated further is a sign of a disconnected or
    trivially-structured graph, not of a good partition."""

    def of(self, node_id: str) -> int:
        for index, community in enumerate(self.communities):
            if node_id in community:
                return index
        raise CommunityError(f"node {node_id!r} is in no community")

    @property
    def sizes(self) -> tuple[int, ...]:
        return tuple(len(c) for c in self.communities)


def _adjacency(graph: EntityGraph) -> dict[str, dict[str, float]]:
    """Undirected weighted adjacency. Parallel edges sum, self-loops kept.

    Edges between the same pair arise legitimately — two applicants can share a
    phone *and* a device — and summing them is what makes the pair's coupling
    stronger than either edge alone, which is the signal.
    """
    adj: dict[str, dict[str, float]] = {n: {} for n in graph.nodes}
    for edge in graph.edges:
        if edge.source not in adj or edge.target not in adj:
            raise CommunityError(
                f"edge {edge.source!r}->{edge.target!r} references a node absent "
                "from the graph; partitioning a graph with dangling edges would "
                "silently drop them"
            )
        adj[edge.source][edge.target] = adj[edge.source].get(edge.target, 0.0) + edge.weight
        if edge.source != edge.target:
            adj[edge.target][edge.source] = (
                adj[edge.target].get(edge.source, 0.0) + edge.weight
            )
    return adj


def modularity(graph: EntityGraph, communities: Sequence[frozenset[str]]) -> float:
    """Newman-Girvan modularity Q of a partition.

        Q = (1/2m) Σ_ij [ A_ij − k_i k_j / 2m ] δ(c_i, c_j)

    Computed directly from the definition rather than incrementally, because
    this is the function the incremental Louvain gain is tested against — an
    optimisation and its own reference cannot share an implementation.
    """
    adj = _adjacency(graph)
    two_m = sum(sum(row.values()) for row in adj.values())
    if two_m == 0:
        raise CommunityError("modularity is undefined on a graph with no edge weight")

    degree = {n: sum(row.values()) for n, row in adj.items()}
    total = 0.0
    for community in communities:
        for i in community:
            for j in community:
                total += adj.get(i, {}).get(j, 0.0) - degree[i] * degree[j] / two_m
    return total / two_m


def louvain(graph: EntityGraph) -> Partition:
    """Blondel et al.'s two-phase modularity optimisation.

    Deterministic: nodes are visited in sorted order at every level, so the same
    graph yields the same partition on every run and an officer can re-derive a
    ring alert months later.
    """
    if not graph.nodes:
        raise CommunityError("cannot partition an empty graph")
    adj = _adjacency(graph)
    two_m = sum(sum(row.values()) for row in adj.values())
    if two_m == 0:
        raise CommunityError("cannot partition a graph with no edges")

    # Each level works on an aggregated graph; membership maps original nodes
    # to the current level's super-nodes.
    membership: dict[str, str] = {n: n for n in graph.nodes}
    current = adj
    passes = 0

    while True:
        assignment = _one_level(current, two_m)
        if len(set(assignment.values())) == len(current):
            break
        membership = {
            original: assignment[super_node]
            for original, super_node in membership.items()
        }
        current = _aggregate(current, assignment)
        passes += 1
        if passes > len(graph.nodes):  # pragma: no cover - structural guard
            raise CommunityError("Louvain failed to converge")

    grouped: dict[str, set[str]] = {}
    for original, community in membership.items():
        grouped.setdefault(community, set()).add(original)
    communities = tuple(
        frozenset(members) for _, members in sorted(grouped.items(), key=lambda kv: kv[0])
    )
    return Partition(
        communities=communities,
        modularity=modularity(graph, communities),
        passes=max(passes, 1),
    )


def _one_level(adj: dict[str, dict[str, float]], two_m: float) -> dict[str, str]:
    """Greedy local moves until no single move improves modularity."""
    community = {n: n for n in adj}
    degree = {n: sum(row.values()) for n, row in adj.items()}
    tot = {n: degree[n] for n in adj}

    improved = True
    while improved:
        improved = False
        for node in sorted(adj):
            own = community[node]
            tot[own] -= degree[node]

            links: dict[str, float] = {}
            for neighbour, weight in adj[node].items():
                if neighbour == node:
                    continue
                links[community[neighbour]] = links.get(community[neighbour], 0.0) + weight

            best, best_gain = own, links.get(own, 0.0) - tot[own] * degree[node] / two_m
            for candidate, weight in sorted(links.items()):
                gain = weight - tot[candidate] * degree[node] / two_m
                if gain > best_gain + MIN_MODULARITY_GAIN:
                    best, best_gain = candidate, gain

            tot[best] += degree[node]
            if best != own:
                community[node] = best
                improved = True

    return community


def _aggregate(
    adj: dict[str, dict[str, float]], assignment: dict[str, str]
) -> dict[str, dict[str, float]]:
    """Collapse each community into one node, summing edge weights."""
    out: dict[str, dict[str, float]] = {}
    for source, row in adj.items():
        a = assignment[source]
        out.setdefault(a, {})
        for target, weight in row.items():
            b = assignment[target]
            out[a][b] = out[a].get(b, 0.0) + weight
    return out


@dataclass(frozen=True)
class CommunityScore:
    """One community's computable structure, and the score it cannot carry.

    The phase file scores communities by *"fraud-label density and
    shared-attribute entropy"*. One of those two is computable from a graph and
    the other is not, so this type holds the first and raises on the second
    rather than quietly presenting entropy as the scorer WS-6.1 describes.
    """

    community_id: int
    size: int
    shared_attribute_entropy: float
    """Shannon entropy over the edge types linking the community's members.

    Low entropy is the ring signature: a community held together by one shared
    attribute — twelve applicants, one device — is a stronger signal than one
    joined by a varied mix, which is what a family or a shared address block
    looks like."""

    internal_density: float
    """Realised edges over possible edges within the community."""

    dominant_edge_type: str
    node_types: dict[str, int] = field(default_factory=dict)

    @property
    def fraud_label_density(self) -> float:
        """Always raises. The other half of WS-6.1's scoring recipe.

        Needs a fraud label per node, which is a fraud-desk disposition. Phase 1
        enforced disposition capture from day one precisely so this would exist
        later; no alert has been dispositioned because the alert budget (LH-206)
        is unratified, so the desk was never staffed. LH-810 tracks the feed.
        """
        raise CommunityError(
            "fraud-label density needs a disposition per node. WS-6.1's feed is "
            "'P1 entity graph + >= 18 months of fraud-desk dispositions'; the graph "
            "is real and the dispositions do not exist (ADR-0016). Scoring on "
            "entropy alone would rank communities plausibly and would not be the "
            "scorer this workstream specifies"
        )


def score_communities(
    graph: EntityGraph, partition: Partition
) -> tuple[CommunityScore, ...]:
    """Structural scores for every community above :data:`MIN_COMMUNITY_SIZE`."""
    adj = _adjacency(graph)
    edge_types: dict[tuple[str, str], list[str]] = {}
    for edge in graph.edges:
        key = (edge.source, edge.target)
        edge_types.setdefault(key, []).append(edge.edge_type.value)

    scores: list[CommunityScore] = []
    for index, community in enumerate(partition.communities):
        if len(community) < MIN_COMMUNITY_SIZE:
            continue

        types: dict[str, int] = {}
        internal_edges = 0
        for (source, target), kinds in edge_types.items():
            if source in community and target in community:
                internal_edges += len(kinds)
                for kind in kinds:
                    types[kind] = types.get(kind, 0) + 1

        n = len(community)
        possible = n * (n - 1) / 2
        node_types: dict[str, int] = {}
        for node_id in community:
            kind = graph.nodes[node_id].node_type.value
            node_types[kind] = node_types.get(kind, 0) + 1

        scores.append(
            CommunityScore(
                community_id=index,
                size=n,
                shared_attribute_entropy=_entropy(types),
                internal_density=(internal_edges / possible) if possible else 0.0,
                dominant_edge_type=(
                    max(sorted(types), key=lambda k: types[k]) if types else ""
                ),
                node_types=node_types,
            )
        )
    return tuple(scores)


def _entropy(counts: dict[str, int]) -> float:
    """Shannon entropy in bits. Zero for a single category, which is the point."""
    total = sum(counts.values())
    if total == 0:
        return 0.0
    bits = -sum((c / total) * math.log2(c / total) for c in counts.values() if c > 0)
    # A single category gives -0.0, which compares equal to 0.0 but renders as
    # "-0.0" in every report. Normalise so a ring's defining score reads as zero.
    return bits + 0.0 if bits else 0.0

"""Louvain community detection over the P1 entity graph — Phase 6 WS-6.1.

The one Phase 6 component that runs on real data today, because community
detection is unsupervised: it needs the graph and not the dispositions.

The modularity values pinned below were computed independently from
Newman-Girvan's definition on graphs small enough to verify by inspection, not
read off this implementation.
"""

from __future__ import annotations

import unittest

from lending_hub.fraud.entity_resolution import (
    Edge,
    EdgeType,
    EntityGraph,
    Node,
    NodeType,
)
from lending_hub.learning.graph import (
    MIN_COMMUNITY_SIZE,
    CommunityError,
    louvain,
    modularity,
    score_communities,
)


def _two_triangles() -> EntityGraph:
    """Two 3-cliques joined by a single edge. The textbook partition case.

    Hand-computed: 7 edges of weight 1, so 2m = 14; degrees a1=3, a2=2, a3=2,
    b1=3, b2=2, b3=2. Q for the two-triangle partition = 0.357143.
    """
    graph = EntityGraph()
    for name in ("a1", "a2", "a3", "b1", "b2", "b3"):
        graph.add_node(Node(name, NodeType.APPLICANT))
    for source, target in (
        ("a1", "a2"),
        ("a2", "a3"),
        ("a1", "a3"),
        ("b1", "b2"),
        ("b2", "b3"),
        ("b1", "b3"),
        ("a1", "b1"),
    ):
        graph.add_edge(Edge(source, target, EdgeType.SHARES_DEVICE))
    return graph


class LouvainRecoversStructure(unittest.TestCase):
    def test_two_triangles_split_into_two_communities(self):
        partition = louvain(_two_triangles())
        self.assertEqual(len(partition.communities), 2)
        self.assertEqual(sorted(partition.sizes), [3, 3])

    def test_the_modularity_matches_the_hand_computation(self):
        partition = louvain(_two_triangles())
        self.assertAlmostEqual(partition.modularity, 0.357143, places=6)

    def test_members_of_a_triangle_land_together(self):
        partition = louvain(_two_triangles())
        self.assertEqual(partition.of("a1"), partition.of("a2"))
        self.assertEqual(partition.of("a1"), partition.of("a3"))
        self.assertNotEqual(partition.of("a1"), partition.of("b1"))


class DeterminismIsRequired(unittest.TestCase):
    """Louvain's result depends on node visit order.

    A randomised order would make a ring alert irreproducible, so an officer
    could not re-derive months later why an applicant was flagged. Sorted order
    is the deviation from the reference implementations, and it is deliberate.
    """

    def test_repeated_runs_give_an_identical_partition(self):
        graph = _two_triangles()
        first, second = louvain(graph), louvain(graph)
        self.assertEqual(
            [sorted(c) for c in first.communities],
            [sorted(c) for c in second.communities],
        )
        self.assertEqual(first.modularity, second.modularity)

    def test_insertion_order_does_not_change_the_partition(self):
        forward = louvain(_two_triangles())
        reversed_graph = EntityGraph()
        for name in reversed(("a1", "a2", "a3", "b1", "b2", "b3")):
            reversed_graph.add_node(Node(name, NodeType.APPLICANT))
        for source, target in reversed(
            [
                ("a1", "a2"),
                ("a2", "a3"),
                ("a1", "a3"),
                ("b1", "b2"),
                ("b2", "b3"),
                ("b1", "b3"),
                ("a1", "b1"),
            ]
        ):
            reversed_graph.add_edge(Edge(source, target, EdgeType.SHARES_DEVICE))
        self.assertEqual(
            sorted(sorted(c) for c in forward.communities),
            sorted(sorted(c) for c in louvain(reversed_graph).communities),
        )


class ModularityIsItsOwnReference(unittest.TestCase):
    """The incremental gain inside Louvain is tested against the direct
    definition; an optimisation and its reference cannot share an implementation.
    """

    def test_the_optimal_partition_beats_the_trivial_ones(self):
        graph = _two_triangles()
        found = louvain(graph)
        all_one = [frozenset(graph.nodes)]
        singletons = [frozenset({n}) for n in graph.nodes]
        self.assertGreater(found.modularity, modularity(graph, all_one))
        self.assertGreater(found.modularity, modularity(graph, singletons))

    def test_a_single_community_has_zero_modularity(self):
        """Σ(A_ij − k_i k_j/2m) over all pairs is identically zero."""
        graph = _two_triangles()
        self.assertAlmostEqual(
            modularity(graph, [frozenset(graph.nodes)]), 0.0, places=12
        )


class RefusalsOnDegenerateGraphs(unittest.TestCase):
    def test_an_empty_graph_is_refused(self):
        with self.assertRaises(CommunityError):
            louvain(EntityGraph())

    def test_a_graph_with_no_edges_is_refused(self):
        graph = EntityGraph()
        graph.add_node(Node("a1", NodeType.APPLICANT))
        with self.assertRaises(CommunityError):
            louvain(graph)

    def test_a_dangling_edge_is_refused_rather_than_dropped(self):
        graph = EntityGraph()
        graph.add_node(Node("a1", NodeType.APPLICANT))
        graph.add_edge(Edge("a1", "ghost", EdgeType.SHARES_PHONE))
        with self.assertRaises(CommunityError) as caught:
            louvain(graph)
        self.assertIn("dangling", str(caught.exception))


class ScoringIsHalfARecipe(unittest.TestCase):
    """WS-6.1 scores communities by "fraud-label density and shared-attribute
    entropy". One is computable from a graph; the other needs a disposition.
    """

    def test_fraud_label_density_raises_and_names_its_feed(self):
        graph = _two_triangles()
        score = score_communities(graph, louvain(graph))[0]
        with self.assertRaises(CommunityError) as caught:
            score.fraud_label_density
        message = str(caught.exception)
        self.assertIn("disposition", message)
        self.assertIn("ADR-0016", message)

    def test_a_single_attribute_community_has_zero_entropy(self):
        """The ring signature: twelve applicants held together by one device.

        Zero rather than -0.0, because the score renders in reports.
        """
        graph = _two_triangles()
        score = score_communities(graph, louvain(graph))[0]
        self.assertEqual(score.shared_attribute_entropy, 0.0)
        self.assertEqual(str(score.shared_attribute_entropy), "0.0")

    def test_a_mixed_attribute_community_has_higher_entropy(self):
        """What a family or a shared address block looks like, versus a ring."""
        graph = EntityGraph()
        for name in ("m1", "m2", "m3"):
            graph.add_node(Node(name, NodeType.APPLICANT))
        graph.add_edge(Edge("m1", "m2", EdgeType.SHARES_PHONE))
        graph.add_edge(Edge("m2", "m3", EdgeType.SHARES_ADDRESS))
        graph.add_edge(Edge("m1", "m3", EdgeType.SHARES_EMPLOYER))
        score = score_communities(graph, louvain(graph))[0]
        self.assertGreater(score.shared_attribute_entropy, 1.0)

    def test_a_clique_has_full_internal_density(self):
        graph = _two_triangles()
        self.assertAlmostEqual(
            score_communities(graph, louvain(graph))[0].internal_density, 1.0, places=12
        )

    def test_communities_below_the_size_floor_are_not_scored(self):
        """A two-node "community" joined by one phone is an edge, and the
        entropy of a two-element set is not a meaningful quantity."""
        graph = EntityGraph()
        for name in ("p1", "p2"):
            graph.add_node(Node(name, NodeType.APPLICANT))
        graph.add_edge(Edge("p1", "p2", EdgeType.SHARES_PHONE))
        self.assertEqual(score_communities(graph, louvain(graph)), ())
        self.assertEqual(MIN_COMMUNITY_SIZE, 3)

    def test_node_types_are_reported_per_community(self):
        graph = _two_triangles()
        score = score_communities(graph, louvain(graph))[0]
        self.assertEqual(score.node_types, {"applicant": 3})


if __name__ == "__main__":
    unittest.main()

"""Tests for entity resolution v1 and the Gold entity graph (WS-1.2 Step 1).

Jaro-Winkler is pinned against the values in the literature, because it is the
one piece here with a canonical answer and a port that silently disagrees with it
would move every match decision.

Workstream: WS-1.2 Step 1
"""

import unittest

from lending_hub.fraud.entity_resolution import (
    GEOHASH_PRECISION,
    MATCH_THRESHOLD,
    ApplicationRecord,
    EdgeType,
    EntityResolutionError,
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


class TestStringSimilarity(unittest.TestCase):
    def test_jaro_matches_the_canonical_examples(self):
        self.assertAlmostEqual(jaro("martha", "marhta"), 0.944444, places=5)
        self.assertAlmostEqual(jaro("dixon", "dicksonx"), 0.766666, places=5)
        self.assertAlmostEqual(jaro("crate", "trace"), 0.733333, places=5)

    def test_jaro_winkler_matches_the_canonical_examples(self):
        self.assertAlmostEqual(jaro_winkler("martha", "marhta"), 0.961111, places=5)
        self.assertAlmostEqual(jaro_winkler("dixon", "dicksonx"), 0.813333, places=5)

    def test_identical_strings_score_one(self):
        self.assertEqual(jaro_winkler("rajesh", "rajesh"), 1.0)

    def test_disjoint_strings_score_zero(self):
        self.assertEqual(jaro_winkler("abc", "xyz"), 0.0)

    def test_an_empty_string_scores_zero_not_one(self):
        self.assertEqual(jaro_winkler("", "rajesh"), 0.0)

    def test_similarity_is_symmetric(self):
        for left, right in (("rajesh kumar", "rajesh kumr"), ("sunita", "sunitha")):
            self.assertAlmostEqual(jaro_winkler(left, right), jaro_winkler(right, left))

    def test_the_prefix_bonus_favours_a_shared_beginning(self):
        # Why Jaro-Winkler is the standard choice for personal names: people
        # mistype the ends of names far more than the beginnings.
        self.assertGreater(jaro_winkler("kumar", "kumaz"), jaro_winkler("kumar", "zumar"))


class TestNormalisation(unittest.TestCase):
    def test_names_lose_accents_case_and_punctuation(self):
        self.assertEqual(normalise_name("  Ráj-esh   KUMAR. "), "raj esh kumar")

    def test_phone_keeps_the_last_ten_digits(self):
        self.assertEqual(normalise_phone("+91 98765 43210"), "9876543210")
        self.assertEqual(normalise_phone("098765-43210"), "9876543210")

    def test_a_short_phone_is_not_padded_or_dropped_silently(self):
        self.assertEqual(normalise_phone("12345"), "12345")

    def test_account_normalisation_preserves_leading_zeros(self):
        # Leading zeros are significant in account numbers; stripping them merges
        # two different accounts.
        self.assertEqual(normalise_account("00-1234 5678"), "0012345678")

    def test_normalisation_does_not_reorder_name_tokens(self):
        # Reordering is a matching decision, not a formatting one, and hiding it
        # inside a normaliser puts it where nobody reviews it.
        self.assertNotEqual(normalise_name("kumar rajesh"), normalise_name("rajesh kumar"))


class TestGeohash(unittest.TestCase):
    def test_a_known_location_encodes_to_its_known_cell(self):
        self.assertTrue(geohash(57.64911, 10.40744, 11).startswith("u4pruydqqvj"))

    def test_nearby_points_share_a_prefix(self):
        self.assertEqual(
            geohash(12.9716, 77.5946)[:5], geohash(12.9718, 77.5944)[:5]
        )

    def test_distant_points_share_no_prefix(self):
        self.assertNotEqual(geohash(12.9716, 77.5946)[0], geohash(51.5074, -0.1278)[0])

    def test_out_of_range_coordinates_are_refused(self):
        with self.assertRaises(EntityResolutionError):
            geohash(120.0, 0.0)
        with self.assertRaises(EntityResolutionError):
            geohash(0.0, 200.0)

    def test_precision_controls_the_length(self):
        self.assertEqual(len(geohash(12.9716, 77.5946, 9)), 9)


class TestBlocking(unittest.TestCase):
    def test_records_sharing_no_key_are_never_compared(self):
        # Blocking is a recall decision: a pair that shares no key never matches,
        # whatever its similarity.
        records = [
            ApplicationRecord("A", name="Rajesh Kumar", phone="9000000001"),
            ApplicationRecord("B", name="Zebra Xylophone", phone="9000000002"),
        ]
        self.assertEqual(candidate_pairs(records), set())

    def test_a_shared_phone_blocks_two_records_together(self):
        records = [
            ApplicationRecord("A", name="Rajesh Kumar", phone="+91 90000 00001"),
            ApplicationRecord("B", name="Different Person", phone="09000000001"),
        ]
        self.assertEqual(candidate_pairs(records), {("A", "B")})

    def test_a_shared_name_prefix_blocks_records_with_no_shared_identifier(self):
        # The case deliberate identity fraud is built to produce.
        records = [
            ApplicationRecord("A", name="Rajesh Kumar", phone="9000000001"),
            ApplicationRecord("B", name="Rajesh Kumr", phone="9000000002"),
        ]
        self.assertEqual(candidate_pairs(records), {("A", "B")})

    def test_a_shared_geohash_cell_blocks_neighbours(self):
        records = [
            ApplicationRecord("A", name="One", latitude=12.9716, longitude=77.5946),
            ApplicationRecord("B", name="Two", latitude=12.9717, longitude=77.5945),
        ]
        self.assertEqual(candidate_pairs(records), {("A", "B")})

    def test_a_duplicate_application_id_is_refused(self):
        with self.assertRaises(EntityResolutionError):
            candidate_pairs([ApplicationRecord("A", phone="9000000001"),
                             ApplicationRecord("A", phone="9000000001")])


class TestComparison(unittest.TestCase):
    def test_an_exact_identifier_match_is_deterministic(self):
        left = ApplicationRecord("A", name="Rajesh", phone="9000000001")
        right = ApplicationRecord("B", name="Sunita", phone="9000000001")
        score = compare(left, right)
        self.assertTrue(score.deterministic)
        self.assertEqual(score.evidence["phone"], 1.0)

    def test_a_name_only_match_is_not_deterministic(self):
        left = ApplicationRecord("A", name="Rajesh Kumar")
        right = ApplicationRecord("B", name="Rajesh Kumr")
        score = compare(left, right)
        self.assertFalse(score.deterministic)
        self.assertGreater(score.evidence["name"], 0.9)

    def test_the_score_is_never_labelled_a_probability_on_track_a(self):
        # ADR-0011: presenting a similarity as a match probability is the defect
        # recordlinkage was rejected for.
        score = compare(
            ApplicationRecord("A", name="Rajesh"), ApplicationRecord("B", name="Rajesh")
        )
        self.assertFalse(score.is_probability)
        self.assertFalse(score.to_dict()["is_probability"])

    def test_evidence_records_every_attribute_that_contributed(self):
        left = ApplicationRecord("A", name="Rajesh", phone="9000000001",
                                 employer="Acme Ltd", latitude=12.97, longitude=77.59)
        right = ApplicationRecord("B", name="Rajesh", phone="9000000001",
                                  employer="ACME  LTD.", latitude=12.97, longitude=77.59)
        evidence = compare(left, right).evidence
        self.assertEqual(sorted(evidence), ["address", "employer", "name", "phone"])


class TestGraph(unittest.TestCase):
    def setUp(self):
        self.records = [
            ApplicationRecord("A1", name="Rajesh Kumar", phone="+91 98765 43210",
                              device_id="D1", latitude=12.9716, longitude=77.5946),
            ApplicationRecord("A2", name="Rajesh Kumr", phone="098765-43210",
                              device_id="D1", latitude=12.9718, longitude=77.5944),
            ApplicationRecord("A3", name="Sunita Devi", phone="9000000001",
                              latitude=19.0760, longitude=72.8777),
        ]

    def test_the_graph_carries_the_p6_node_types(self):
        graph, _ = resolve(self.records, name_threshold=0.9)
        types = {node.node_type for node in graph.nodes.values()}
        self.assertIn(NodeType.APPLICANT, types)
        self.assertIn(NodeType.PHONE, types)
        self.assertIn(NodeType.DEVICE, types)
        self.assertIn(NodeType.ADDRESS, types)

    def test_every_edge_carries_the_evidence_that_created_it(self):
        graph, _ = resolve(self.records, name_threshold=0.9)
        for edge in graph.edges:
            self.assertTrue(edge.evidence, f"{edge.source}->{edge.target} has no evidence")

    def test_a_shared_device_puts_two_applicants_in_one_component(self):
        graph, _ = resolve(self.records, name_threshold=0.9)
        components = [c for c in graph.components() if "A1" in c]
        self.assertIn("A2", components[0])
        self.assertNotIn("A3", components[0])

    def test_an_unrelated_applicant_stays_in_its_own_component(self):
        graph, _ = resolve(self.records, name_threshold=0.9)
        self.assertEqual(len(graph.components()), 2)

    def test_an_unratified_threshold_is_stamped_into_the_graph(self):
        graph, _ = resolve(self.records, name_threshold=0.9)
        self.assertFalse(graph.threshold_ratified)
        self.assertIn("LH-209", graph.threshold_provenance)
        self.assertIn("LH-209", graph.to_dict()["threshold_provenance"])

    def test_a_ratified_threshold_must_cite_its_tuning_run(self):
        with self.assertRaises(EntityResolutionError):
            build_graph(self.records, [], name_threshold=0.9, threshold_ratified=True)

    def test_build_graph_has_no_default_threshold(self):
        # A default is how an untuned threshold becomes the production one.
        import inspect
        parameter = inspect.signature(build_graph).parameters["name_threshold"]
        self.assertIs(parameter.default, inspect.Parameter.empty)

    def test_an_out_of_range_threshold_is_refused(self):
        with self.assertRaises(EntityResolutionError):
            build_graph(self.records, [], name_threshold=1.7, threshold_ratified=False)

    def test_a_deterministic_pair_needs_no_name_edge(self):
        # A shared phone already links them through the phone node; adding a
        # threshold-dependent name edge would let a strong deterministic signal be
        # restated as a weak fuzzy one.
        graph, matches = resolve(self.records, name_threshold=0.5)
        name_edges = [e for e in graph.edges if e.edge_type is EdgeType.NAME_SIMILAR]
        self.assertEqual(name_edges, [])

    def test_the_threshold_placeholder_names_its_owner_and_ticket(self):
        self.assertEqual(MATCH_THRESHOLD.ticket, "LH-209")
        self.assertEqual(MATCH_THRESHOLD.owner, "Fraud Head")

    def test_geohash_precision_is_the_declared_blocking_cell(self):
        graph, _ = resolve(self.records, name_threshold=0.9)
        cells = [n for n in graph.nodes if n.startswith("geo:")]
        for cell in cells:
            self.assertEqual(len(cell.split(":")[1]), GEOHASH_PRECISION)


if __name__ == "__main__":
    unittest.main()

"""Tests for alert routing and the case queue (WS-1.2 Step 6).

The queue is a labelling pipeline wearing an operations interface: every one of
these tests is really about whether P6 will have a training set.

Workstream: WS-1.2 Step 6
"""

import unittest
from datetime import UTC, datetime

from lending_hub.fraud.routing import (
    ROUTING_BANDS,
    Action,
    Band,
    CaseQueue,
    Disposition,
    DispositionOutcome,
    DispositionTaxonomy,
    RoutingError,
    RoutingPolicy,
    route,
)

NOW = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)

DISPOSITIONS = [
    Disposition("F01", DispositionOutcome.CONFIRMED_FRAUD, "identity fraud"),
    Disposition("N01", DispositionOutcome.NOT_FRAUD, "verified genuine"),
    Disposition("I01", DispositionOutcome.INCONCLUSIVE, "worked, undecided"),
]


def taxonomy(ratified=False):
    if ratified:
        return DispositionTaxonomy.from_policy(
            DISPOSITIONS, decision_reference="test fixture standing in for LH-101"
        )
    return DispositionTaxonomy.for_experiment(DISPOSITIONS, reason="Track A")


def policy(ratified=False):
    bands = [Band(0.0, Action.PASS), Band(0.6, Action.STEP_UP), Band(0.9, Action.REFER)]
    if ratified:
        return RoutingPolicy.from_policy(bands, decision_reference="test fixture")
    return RoutingPolicy.for_experiment(bands, reason="Track A")


class TestRouting(unittest.TestCase):
    def test_the_three_srs_outcomes_and_only_those(self):
        self.assertEqual(
            sorted(action.value for action in Action), ["pass", "refer", "step_up"]
        )

    def test_scores_map_to_their_bands(self):
        self.assertIs(route(0.1, policy()), Action.PASS)
        self.assertIs(route(0.7, policy()), Action.STEP_UP)
        self.assertIs(route(0.95, policy()), Action.REFER)

    def test_a_band_edge_belongs_to_the_higher_band(self):
        self.assertIs(route(0.6, policy()), Action.STEP_UP)
        self.assertIs(route(0.9, policy()), Action.REFER)

    def test_a_score_outside_zero_one_is_refused(self):
        with self.assertRaises(RoutingError):
            route(1.4, policy())

    def test_bands_must_be_given_in_ascending_order(self):
        with self.assertRaises(RoutingError):
            RoutingPolicy.for_experiment(
                [Band(0.9, Action.REFER), Band(0.1, Action.STEP_UP)], reason="x"
            )

    def test_duplicate_band_edges_are_refused_as_ambiguous(self):
        with self.assertRaises(RoutingError):
            RoutingPolicy.for_experiment(
                [Band(0.5, Action.STEP_UP), Band(0.5, Action.REFER)], reason="x"
            )

    def test_unratified_bands_need_a_written_reason(self):
        with self.assertRaises(RoutingError):
            RoutingPolicy.for_experiment([Band(0.0, Action.PASS)], reason="")

    def test_route_has_no_default_policy(self):
        # A default band set becomes the production one by inertia.
        import inspect
        parameter = inspect.signature(route).parameters["policy"]
        self.assertIs(parameter.default, inspect.Parameter.empty)

    def test_the_bands_placeholder_names_its_owner(self):
        self.assertEqual(ROUTING_BANDS.ticket, "LH-206")


class TestDispositionsAreMandatory(unittest.TestCase):
    def setUp(self):
        self.queue = CaseQueue(taxonomy())
        self.queue.open_case(
            case_id="C1", application_id="A1", action=Action.REFER,
            score=0.95, opened_at=NOW, signal="velocity",
        )

    def test_a_case_cannot_be_closed_without_a_code(self):
        with self.assertRaises(TypeError):
            self.queue.close("C1", closed_at=NOW, analyst="an1")

    def test_a_free_text_disposition_is_refused(self):
        with self.assertRaises(RoutingError) as caught:
            self.queue.close("C1", code="looked fine", closed_at=NOW, analyst="an1")
        self.assertIn("training label", str(caught.exception))

    def test_a_disposition_must_name_the_analyst(self):
        with self.assertRaises(RoutingError):
            self.queue.close("C1", code="F01", closed_at=NOW, analyst="")

    def test_the_taxonomy_has_no_unknown_bucket(self):
        # An "unknown" outcome makes the mandatory-code rule a formality.
        self.assertNotIn(
            "unknown", [outcome.value for outcome in DispositionOutcome]
        )

    def test_closing_twice_is_refused(self):
        self.queue.close("C1", code="F01", closed_at=NOW, analyst="an1")
        with self.assertRaises(RoutingError):
            self.queue.close("C1", code="N01", closed_at=NOW, analyst="an2")

    def test_a_passed_application_never_opens_a_case(self):
        # Opening one would put every clean application into the disposition set
        # and drown the base rate the fraud model is fitted to.
        with self.assertRaises(RoutingError):
            self.queue.open_case(
                case_id="C9", application_id="A9", action=Action.PASS,
                score=0.1, opened_at=NOW,
            )

    def test_a_duplicate_case_id_is_refused(self):
        with self.assertRaises(RoutingError):
            self.queue.open_case(
                case_id="C1", application_id="A2", action=Action.REFER,
                score=0.95, opened_at=NOW,
            )


class TestTrainingLabels(unittest.TestCase):
    def build(self, ratified):
        queue = CaseQueue(taxonomy(ratified))
        for index, code in enumerate(["F01", "N01", "I01"]):
            case_id = f"C{index}"
            queue.open_case(
                case_id=case_id, application_id=f"A{index}", action=Action.REFER,
                score=0.95, opened_at=NOW, signal="velocity",
            )
            queue.close(case_id, code=code, closed_at=NOW, analyst="an1")
        queue.open_case(
            case_id="C9", application_id="A9", action=Action.STEP_UP,
            score=0.7, opened_at=NOW, signal="device",
        )
        return queue

    def test_labels_are_refused_while_the_taxonomy_is_unratified(self):
        with self.assertRaises(RoutingError) as caught:
            self.build(False).training_labels()
        self.assertIn("LH-101", str(caught.exception))

    def test_inconclusive_cases_are_excluded_not_labelled_zero(self):
        # "We looked and could not tell" is not evidence of innocence; folding it
        # into the negative class teaches the model the hardest cases are clean.
        labels = dict(self.build(True).training_labels())
        self.assertEqual(labels, {"A0": 1, "A1": 0})
        self.assertNotIn("A2", labels)

    def test_open_cases_contribute_no_label(self):
        labels = dict(self.build(True).training_labels())
        self.assertNotIn("A9", labels)

    def test_completeness_is_the_p6_readiness_number(self):
        self.assertAlmostEqual(self.build(True).completeness, 0.75)

    def test_an_empty_queue_has_no_completeness_rather_than_zero(self):
        self.assertIsNone(CaseQueue(taxonomy()).completeness)


class TestAlertPrecision(unittest.TestCase):
    def test_precision_uses_the_appendix_a_definition(self):
        queue = CaseQueue(taxonomy(True))
        for index, code in enumerate(["F01", "N01"]):
            queue.open_case(
                case_id=f"C{index}", application_id=f"A{index}", action=Action.REFER,
                score=0.95, opened_at=NOW, signal="velocity",
            )
            queue.close(f"C{index}", code=code, closed_at=NOW, analyst="an1")
        self.assertAlmostEqual(queue.precision(), 0.5)

    def test_precision_is_reported_per_signal(self):
        queue = CaseQueue(taxonomy(True))
        queue.open_case(case_id="C1", application_id="A1", action=Action.REFER,
                        score=0.95, opened_at=NOW, signal="velocity")
        queue.close("C1", code="F01", closed_at=NOW, analyst="an1")
        queue.open_case(case_id="C2", application_id="A2", action=Action.REFER,
                        score=0.95, opened_at=NOW, signal="device")
        queue.close("C2", code="N01", closed_at=NOW, analyst="an1")
        self.assertAlmostEqual(queue.precision("velocity"), 1.0)
        self.assertAlmostEqual(queue.precision("device"), 0.0)

    def test_no_alerts_gives_none_not_zero(self):
        # Appendix A: "no alerts fired" is not "every alert was wrong".
        self.assertIsNone(CaseQueue(taxonomy(True)).precision())


class TestTaxonomyGovernance(unittest.TestCase):
    def test_a_ratified_taxonomy_must_cite_its_decision(self):
        with self.assertRaises(RoutingError):
            DispositionTaxonomy.from_policy(DISPOSITIONS, decision_reference="")

    def test_a_stand_in_taxonomy_needs_a_reason(self):
        with self.assertRaises(RoutingError):
            DispositionTaxonomy.for_experiment(DISPOSITIONS, reason="")

    def test_an_unratified_taxonomy_carries_the_appendix_a_placeholder(self):
        self.assertIn("stand-in", taxonomy().provenance)
        self.assertIn("LH-101", str(DispositionTaxonomy().provenance))

    def test_the_queue_reports_its_taxonomy_state(self):
        payload = CaseQueue(taxonomy()).to_dict()
        self.assertFalse(payload["taxonomy_ratified"])
        self.assertIn("training set", payload["note"])


if __name__ == "__main__":
    unittest.main()

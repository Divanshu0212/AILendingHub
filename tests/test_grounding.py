"""Tests for the grounding-rule checker.

A CI gate that has never failed is a gate nobody trusts. These tests fire each
rule deliberately, and pin the exemptions so they cannot quietly widen into
"nothing is checked anymore".

Workstream: WS-0 (Master §2 enforcement)
"""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

import check_grounding as g  # noqa: E402


def files(*entries):
    """Build the (path, rel, text) triples the checker consumes."""
    return [(pathlib.Path(rel), rel, text) for rel, text in entries]


def rules(findings):
    return sorted(f.rule for f in findings)


class TestG1MalformedPlaceholders(unittest.TestCase):
    def test_bare_tbd_in_config_fails(self):
        found = g.check_placeholders(
            files(("config/sources/x.yaml", "retention:\n  period: TBD\n")), set(), False
        )
        self.assertIn("G1", rules(found))

    def test_placeholder_without_ticket_fails(self):
        found = g.check_placeholders(
            files(("config/sources/x.yaml", 'pii: "TBD[DPO]"\n')), set(), False
        )
        self.assertIn("G1", rules(found))

    def test_well_formed_placeholder_passes(self):
        found = g.check_placeholders(
            files(("config/sources/x.yaml", 'pii: "TBD[DPO, LH-110]"\n')), {"LH-110"}, False
        )
        self.assertEqual(rules(found), [])

    def test_python_string_value_is_checked(self):
        found = g.check_placeholders(
            files(("src/lending_hub/x.py", 'THRESHOLD = "TBD"\n')), set(), False
        )
        self.assertIn("G1", rules(found))

    def test_python_docstring_is_not_a_value(self):
        # Prose explaining the grammar must not trip the check, or people start
        # deleting the explanations to get a green build.
        found = g.check_placeholders(
            files(("src/lending_hub/x.py", '"""Write TBD when a value is missing."""\n')),
            set(), False,
        )
        self.assertEqual(rules(found), [])

    def test_fstring_building_a_placeholder_is_not_a_placeholder(self):
        found = g.check_placeholders(
            files(("src/lending_hub/x.py", 'def r(o, t):\n    return f"TBD[{o}, {t}]"\n')),
            set(), False,
        )
        self.assertEqual(rules(found), [])

    def test_markdown_prose_is_exempt_from_g1(self):
        found = g.check_placeholders(
            files(("docs/notes.md", "Write TBD when you do not know.\n")), set(), False
        )
        self.assertEqual(rules(found), [])


class TestG2TicketRegistration(unittest.TestCase):
    def test_unregistered_ticket_fails_anywhere_including_docs(self):
        found = g.check_placeholders(
            files(("docs/notes.md", "value is TBD[DPO, LH-999]\n")), {"LH-110"}, False
        )
        self.assertIn("G2", rules(found))

    def test_registered_ticket_passes(self):
        found = g.check_placeholders(
            files(("docs/notes.md", "value is TBD[DPO, LH-110]\n")), {"LH-110"}, False
        )
        self.assertEqual(rules(found), [])

    def test_ticket_cited_in_code_form_counts_as_used(self):
        # Pending(owner=..., ticket="LH-101") is the canonical Python form; without
        # this the register fills with false "stale ticket" notes.
        found = g.check_placeholders(
            files(("src/lending_hub/x.py", 'p = Pending(owner="Fraud Head", ticket="LH-101")\n')),
            {"LH-101"}, False,
        )
        self.assertEqual(rules(found), [])

    def test_uncited_ticket_is_a_note_not_a_failure(self):
        found = g.check_placeholders(files(("docs/notes.md", "nothing here\n")), {"LH-121"}, False)
        self.assertEqual(rules(found), ["G2-info"])


class TestG3ReleaseMode(unittest.TestCase):
    def test_release_mode_rejects_even_a_valid_placeholder(self):
        entry = files(("config/sources/x.yaml", 'pii: "TBD[DPO, LH-110]"\n'))
        self.assertEqual(rules(g.check_placeholders(entry, {"LH-110"}, False)), [])
        self.assertIn("G3", rules(g.check_placeholders(entry, {"LH-110"}, True)))


class TestG4DefinitionLeaks(unittest.TestCase):
    def test_retyped_dpd_threshold_is_caught(self):
        found = g.check_definition_leaks(
            files(("src/lending_hub/scoring.py", "bad = row.dpd >= 90\n"))
        )
        self.assertIn("G4", rules(found))

    def test_retyped_indeterminate_band_is_caught(self):
        found = g.check_definition_leaks(
            files(("src/lending_hub/scoring.py", "# exclude the 30-89 band\n"))
        )
        self.assertIn("G4", rules(found))

    def test_definitions_package_may_state_the_definition(self):
        found = g.check_definition_leaks(
            files(("src/lending_hub/definitions/appendix_a.py", "x = dpd >= 90\n"))
        )
        self.assertEqual(rules(found), [])

    def test_importing_the_constant_is_clean(self):
        found = g.check_definition_leaks(
            files((
                "src/lending_hub/scoring.py",
                "from lending_hub.definitions import DEFAULT_DPD_THRESHOLD_DAYS\n"
                "bad = row.dpd >= DEFAULT_DPD_THRESHOLD_DAYS.value\n",
            ))
        )
        self.assertEqual(rules(found), [])

    def test_docs_may_quote_appendix_a(self):
        # Only code and config are scanned; the phase docs *are* the source text.
        found = g.check_definition_leaks(files(("docs/phase0/STATUS.md", "DPD >= 90\n")))
        self.assertEqual(rules(found), [])


class TestG6WorkstreamCitations(unittest.TestCase):
    def test_module_without_a_workstream_citation_fails(self):
        found = g.check_workstream_citations(
            files(("src/lending_hub/x.py", '"""Does something."""\n'))
        )
        self.assertIn("G6", rules(found))

    def test_module_without_a_docstring_fails(self):
        found = g.check_workstream_citations(files(("src/lending_hub/x.py", "x = 1\n")))
        self.assertIn("G6", rules(found))

    def test_cited_module_passes(self):
        found = g.check_workstream_citations(
            files(("src/lending_hub/x.py", '"""Does something.\n\nWorkstream: WS-0.1.3\n"""\n'))
        )
        self.assertEqual(rules(found), [])

    def test_non_platform_code_is_not_required_to_cite(self):
        found = g.check_workstream_citations(files(("tools/x.py", "x = 1\n")))
        self.assertEqual(rules(found), [])


class TestRepositoryIsClean(unittest.TestCase):
    """The gate, run against the real tree — this is what CI executes."""

    def test_repo_passes_grounding_in_development_mode(self):
        self.assertEqual(g.main([]), 0)


if __name__ == "__main__":
    unittest.main()

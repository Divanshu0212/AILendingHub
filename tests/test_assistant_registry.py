"""Document registry and dated-corpus ingestion — WS-5.1.1.

Two rules carry this module and both are constructor or query invariants rather
than validation steps, because a validation step is something a caller can
forget. Phase 5 §4 WS-5.1 step 1: "ingestion refuses undated documents", and
"retrieval filters to currently-effective documents by default".

The second is the one that catches people. Stale-rate poisoning is not a
retrieval miss — the retriever succeeded and returned exactly the right passage
from last quarter's circular. So the tests below check the *default* direction of
the filter as hard as they check the filter itself: a safe behaviour that has to
be opted into is not a safe behaviour.
"""

from __future__ import annotations

import unittest
from datetime import date

from lending_hub.assistant.registry import (
    Conflict,
    Document,
    DocumentKind,
    DocumentRegistry,
    RegistryError,
    UndatedDocument,
)


def _doc(
    doc_id="CIRC-1",
    *,
    kind=DocumentKind.RATE_SHEET,
    owner="Product Head",
    effective_from=date(2026, 1, 1),
    effective_to=None,
    version="v1",
    text="The processing fee is 1.5% of the sanctioned amount.",
    language="en",
    product_tags=("personal_loan",),
    supersedes=(),
) -> Document:
    return Document(
        doc_id=doc_id,
        title=f"Title for {doc_id}",
        kind=kind,
        owner=owner,
        effective_from=effective_from,
        effective_to=effective_to,
        text=text,
        version=version,
        language=language,
        product_tags=product_tags,
        supersedes=supersedes,
    )


class IngestionRefusals(unittest.TestCase):
    """The phase file names exactly one refusal at ingest; it is enforced by type."""

    def test_undated_document_is_refused(self):
        """The phase file's one named refusal, and it must be a raise not a warning.

        A document with no effective date has no defined answer to "is this
        current?". Admitting it means that question gets asked at query time,
        where the only available answers are "assume current" (serves stale
        policy) and "assume not" (silently drops real policy).
        """
        with self.assertRaises(UndatedDocument):
            _doc(effective_from=None)

    def test_a_string_date_is_refused_as_undated(self):
        """A string that looks like a date is the realistic form of undated.

        Nobody passes ``None`` on purpose; an ingestion script reads "2026-01-01"
        out of a CSV and hands it over. Comparisons against a real date would
        then raise deep inside a filter, or worse, compare lexicographically and
        appear to work.
        """
        with self.assertRaises(UndatedDocument):
            _doc(effective_from="2026-01-01")

    def test_unowned_document_is_refused(self):
        """Phase 5 §3 makes named corpus owners an entry criterion.

        An unowned document is one nobody will ever retire, which is precisely
        how a corpus accumulates the stale documents the effective-date filter
        then has to work around.
        """
        with self.assertRaises(RegistryError):
            _doc(owner="   ")

    def test_unversioned_document_is_refused(self):
        """A citation that cannot name an exact text is not an audit trail.

        Master §3.3 requires a decision to be reproducible for eight years. If
        two texts can live under one citation, an answer stored today cannot be
        checked tomorrow against what it actually said.
        """
        with self.assertRaises(RegistryError):
            _doc(version="")

    def test_expiry_before_effect_is_refused(self):
        """A window that closes before it opens is never servable.

        Registering it silently would hide a data-entry error behind an empty
        result set — the document simply never appears, and nobody can tell that
        from it not existing.
        """
        with self.assertRaises(RegistryError):
            _doc(effective_from=date(2026, 6, 1), effective_to=date(2026, 1, 1))

    def test_empty_text_is_refused(self):
        with self.assertRaises(RegistryError):
            _doc(text="   ")


class EffectiveDateFiltering(unittest.TestCase):
    """The stale-rate defence. Inclusive at both ends, and default-on."""

    def setUp(self):
        self.registry = DocumentRegistry()
        self.old = _doc(
            "RATE-Q1",
            effective_from=date(2026, 1, 1),
            effective_to=date(2026, 3, 31),
            text="The rate is 11.0% p.a.",
        )
        self.new = _doc(
            "RATE-Q2",
            effective_from=date(2026, 4, 1),
            text="The rate is 12.5% p.a.",
        )
        self.registry.ingest_all([self.old, self.new])

    def test_boundaries_are_inclusive_at_both_ends(self):
        """Policy dates are inclusive; the half-open convention loses a day.

        A circular effective from the 1st binds on the 1st. Using the half-open
        interval that is correct for timestamps would lose or duplicate exactly
        one day of coverage at every rate change — the day on which two rates
        are simultaneously quotable.
        """
        self.assertTrue(self.old.is_effective_on(date(2026, 1, 1)))
        self.assertTrue(self.old.is_effective_on(date(2026, 3, 31)))
        self.assertFalse(self.old.is_effective_on(date(2025, 12, 31)))
        self.assertFalse(self.old.is_effective_on(date(2026, 4, 1)))

    def test_expired_rate_sheet_is_not_returned(self):
        """The whole module in one assertion: last quarter's rate is not servable."""
        live = self.registry.effective(date(2026, 6, 1))
        self.assertEqual([d.doc_id for d in live], ["RATE-Q2"])

    def test_expired_documents_are_retained_not_deleted(self):
        """Not servable and not stored are different requirements.

        An answer given in 2026 and audited in 2031 must resolve its citations
        against the text that was live in 2026. Deleting expired documents makes
        every historical answer unverifiable, which trades a stale-answer risk
        for an unauditable-answer certainty.
        """
        self.assertEqual(len(self.registry.all_versions()), 2)
        self.assertEqual(
            [d.doc_id for d in self.registry.expired(date(2026, 6, 1))], ["RATE-Q1"]
        )
        self.assertEqual(self.registry.get("RATE-Q1@v1").text, "The rate is 11.0% p.a.")

    def test_as_of_has_no_default(self):
        """A default of 'today' would make replay a re-answer.

        The point of storing a conversation is to be able to reproduce it. If
        the corpus query silently means "now", replaying a 2026 conversation in
        2031 resolves against the 2031 corpus and reports agreement or
        disagreement that is a fact about the intervening five years.
        """
        with self.assertRaises(TypeError):
            self.registry.effective()  # type: ignore[call-arg]
        with self.assertRaises(RegistryError):
            self.registry.effective("2026-06-01")  # type: ignore[arg-type]

    def test_future_documents_are_separated_from_expired(self):
        """A published-but-not-yet-binding circular is correct, not broken.

        The two states need opposite responses — a future document is waiting,
        an expired one is dangerous — so collapsing them into "not effective"
        loses the distinction an operator needs.
        """
        as_of = date(2026, 2, 1)
        self.assertEqual([d.doc_id for d in self.registry.not_yet_effective(as_of)], ["RATE-Q2"])
        self.assertEqual(self.registry.expired(as_of), [])

    def test_all_versions_is_the_conspicuous_opt_out(self):
        """The unsafe path is named so a reviewer sees it at the call site.

        ``all_versions()`` in a retrieval path is a bug visible from the method
        name, which is the only kind of bug that gets caught in review.
        """
        self.assertEqual(len(self.registry.all_versions()), 2)


class Narrowing(unittest.TestCase):
    def test_filters_compose_over_kind_product_and_language(self):
        registry = DocumentRegistry()
        registry.ingest_all(
            [
                _doc("A", kind=DocumentKind.FAQ, product_tags=("kcc",), language="en"),
                _doc("B", kind=DocumentKind.FAQ, product_tags=("kcc",), language="hi"),
                _doc("C", kind=DocumentKind.RATE_SHEET, product_tags=("kcc",)),
                _doc("D", kind=DocumentKind.FAQ, product_tags=("personal_loan",)),
            ]
        )
        got = registry.effective(
            date(2026, 6, 1), kind=DocumentKind.FAQ, product="kcc", language="en"
        )
        self.assertEqual([d.doc_id for d in got], ["A"])


class CitationIdentity(unittest.TestCase):
    def test_citation_key_pins_the_version(self):
        """A citation to an id alone becomes ambiguous the moment it is amended."""
        self.assertEqual(_doc("CIRC-9", version="v3").citation_key, "CIRC-9@v3")

    def test_same_key_different_text_is_refused(self):
        """Two texts under one citation make every stored answer unreproducible."""
        registry = DocumentRegistry()
        registry.ingest(_doc("CIRC-1", version="v1", text="Fee is 1.5%."))
        with self.assertRaises(RegistryError):
            registry.ingest(_doc("CIRC-1", version="v1", text="Fee is 2.0%."))

    def test_reingesting_identical_content_is_idempotent(self):
        """Ingestion runs on a schedule; a re-run must not be an error.

        Otherwise every nightly refresh fails on the unchanged 99% of the corpus
        and the real failures are lost in the noise.
        """
        registry = DocumentRegistry()
        first = registry.ingest(_doc("CIRC-1"))
        second = registry.ingest(_doc("CIRC-1"))
        self.assertIs(first, second)
        self.assertEqual(len(registry), 1)

    def test_content_hash_covers_the_dates_not_only_the_text(self):
        """The same words under different effective dates are a different fact.

        A hash over text alone would call this quarter's reissued circular
        identical to last quarter's, which is exactly the confusion the registry
        exists to prevent.
        """
        a = _doc("X", effective_from=date(2026, 1, 1))
        b = _doc("X", effective_from=date(2026, 7, 1))
        self.assertNotEqual(a.content_hash(), b.content_hash())

    def test_unresolvable_citation_raises_rather_than_returning_none(self):
        """A citation that does not resolve is a claimed source that does not exist.

        The answer validator must treat it as uncited. A ``None`` return invites
        a caller to fall through and treat the claim as fine.
        """
        with self.assertRaises(RegistryError):
            DocumentRegistry().get("NOPE@v1")


class Supersession(unittest.TestCase):
    """LH-608 — what effective dates cannot express."""

    def test_supersession_is_declared_never_inferred(self):
        """Adjacent dates on one product are the usual case, not supersession.

        An inference that is right nine times in ten produces a corpus in which
        nobody knows which tenth is wrong, and the wrong tenth silently drops
        clauses that are still policy.
        """
        registry = DocumentRegistry()
        registry.ingest_all(
            [
                _doc("OLD", effective_from=date(2026, 1, 1)),
                _doc("NEW", effective_from=date(2026, 2, 1)),
            ]
        )
        self.assertEqual(registry.superseded(), {})

    def test_declared_supersession_suppresses_the_conflict(self):
        registry = DocumentRegistry()
        registry.ingest_all(
            [
                _doc("OLD", effective_from=date(2026, 1, 1)),
                _doc("NEW", effective_from=date(2026, 2, 1), supersedes=("OLD",)),
            ]
        )
        self.assertEqual(registry.superseded(), {"OLD": ["NEW"]})
        self.assertEqual(registry.conflicts(date(2026, 6, 1)), [])

    def test_two_live_documents_on_one_product_are_surfaced(self):
        """The partial-amendment case, which is why LH-608 is open.

        Both are effective and both are correct in part. Retrieval returns both
        and the model picks; superseding the earlier drops its unamended
        clauses. Neither is safe, so the registry reports rather than resolves.
        """
        registry = DocumentRegistry()
        registry.ingest_all(
            [
                _doc("OLD", effective_from=date(2026, 1, 1)),
                _doc("NEW", effective_from=date(2026, 2, 1)),
            ]
        )
        conflicts = registry.conflicts(date(2026, 6, 1))
        self.assertEqual(len(conflicts), 1)
        self.assertIsInstance(conflicts[0], Conflict)
        self.assertEqual(conflicts[0].earlier, "OLD@v1")
        self.assertEqual(conflicts[0].later, "NEW@v1")

    def test_different_products_do_not_conflict(self):
        registry = DocumentRegistry()
        registry.ingest_all(
            [
                _doc("A", product_tags=("kcc",)),
                _doc("B", product_tags=("personal_loan",)),
            ]
        )
        self.assertEqual(registry.conflicts(date(2026, 6, 1)), [])

    def test_an_expired_document_cannot_conflict_with_a_live_one(self):
        """Supersession by expiry is the case that *is* fully expressible.

        When the old circular has an end date, the dates already resolve it and
        there is nothing for a human to rule on.
        """
        registry = DocumentRegistry()
        registry.ingest_all(
            [
                _doc("OLD", effective_from=date(2026, 1, 1), effective_to=date(2026, 1, 31)),
                _doc("NEW", effective_from=date(2026, 2, 1)),
            ]
        )
        self.assertEqual(registry.conflicts(date(2026, 6, 1)), [])


class GovernanceReport(unittest.TestCase):
    def test_zero_undated_is_reported_as_structural_not_measured(self):
        """A zero that cannot be anything else must say so, or it reads as evidence.

        "0 undated documents" looks like a clean audit result. It is not a
        result at all — an undated document cannot be registered, so there is
        nothing to count. Reporting the reason keeps a structural guarantee from
        being quoted as a measurement.
        """
        report = DocumentRegistry().governance_report(date(2026, 6, 1))
        self.assertEqual(report["undated"], 0)
        self.assertIn("structurally zero", report["undated_note"])
        self.assertEqual(report["unowned"], 0)
        self.assertIn("structurally zero", report["unowned_note"])

    def test_empty_corpus_names_its_ticket(self):
        """An empty corpus is LH-601, not an empty result."""
        report = DocumentRegistry().governance_report(date(2026, 6, 1))
        self.assertFalse(report["corpus_present"])
        self.assertIn("LH-601", report["corpus_note"])

    def test_counts_split_live_expired_and_future(self):
        registry = DocumentRegistry()
        registry.ingest_all(
            [
                _doc("PAST", effective_from=date(2025, 1, 1), effective_to=date(2025, 12, 31)),
                _doc("LIVE", effective_from=date(2026, 1, 1)),
                _doc("SOON", effective_from=date(2027, 1, 1)),
            ]
        )
        report = registry.governance_report(date(2026, 6, 1))
        self.assertEqual(report["registered"], 3)
        self.assertEqual(report["effective"], 1)
        self.assertEqual(report["expired_retained"], 1)
        self.assertEqual(report["not_yet_effective"], 1)


if __name__ == "__main__":
    unittest.main()

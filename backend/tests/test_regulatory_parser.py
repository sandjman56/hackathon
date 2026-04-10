"""Unit and smoke tests for the regulatory ingestion pipeline.

Most cases use small synthetic ``RawSection`` fixtures so they run fast
and stay deterministic. The trailing :class:`TestRealPdfSmoke` exercises
the actual NEPA-40CFR1500_1508.pdf to catch regressions where the parser
or chunker drift away from the real file.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

# Allow tests to run from repo root or from inside backend/.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rag.regulatory.breadcrumbs import build_breadcrumb  # noqa: E402
from rag.regulatory.chunker import (  # noqa: E402
    MAX_TOKENS,
    MIN_TOKENS,
    Chunk,
    chunk_section,
    chunk_sections,
    count_tokens,
)
from rag.regulatory.parser import (  # noqa: E402
    DocumentType,
    RawSection,
    parse_pdf,
)
from rag.regulatory.store import build_metadata  # noqa: E402
from rag.regulatory.xref import extract_cross_references  # noqa: E402

# Module-level constant reused by any test that needs the real seed PDF.
SEED_PDF = Path(__file__).resolve().parent.parent / "NEPA-40CFR1500_1508.pdf"


# --- factories ------------------------------------------------------------

def make_cfr(section: str, body: str, *, title: str = "Test", part: str | None = None) -> RawSection:
    if part is None:
        part = section.split(".")[0]
    return RawSection(
        document_type=DocumentType.CFR_REGULATION,
        section=section,
        title=title,
        body=body,
        citation=f"40 CFR \u00a7{section}",
        pages=[1],
        part=part,
        part_title="Test Part",
        parent_statute="NEPA",
        effective_date="1978-11-29",
    )


def make_definition(section: str, term: str, definition: str) -> RawSection:
    return RawSection(
        document_type=DocumentType.CFR_REGULATION,
        section=section,
        title=term,
        body=definition,
        citation=f"40 CFR \u00a7{section}",
        pages=[1],
        part="1508",
        part_title="Terminology and Index",
        parent_statute="NEPA",
        effective_date="1978-11-29",
    )


def make_statute(section: str, usc: str, body: str, statute_title: str | None = None) -> RawSection:
    return RawSection(
        document_type=DocumentType.STATUTE,
        section=section,
        title=f"Sec. {section}",
        body=body,
        citation=f"42 USC \u00a7{usc}",
        pages=[1],
        parent_statute="NEPA",
        statute_title=statute_title,
        effective_date="1970-01-01",
    )


# --- chunker behavior tests -----------------------------------------------

class TestSectionBoundaries(unittest.TestCase):
    """Two adjacent sections with sufficient body produce two chunks."""

    def test_two_sections_two_chunks(self):
        body = " ".join(["lorem ipsum"] * 200)  # ~400 tokens, above min
        sections = [
            make_cfr("1501.3", body, title="When to prepare an EA"),
            make_cfr("1501.4", body, title="Whether to prepare an EIS"),
        ]
        chunks = chunk_sections(sections)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].sources[0].section, "1501.3")
        self.assertEqual(chunks[1].sources[0].section, "1501.4")
        self.assertFalse(chunks[0].is_merged_siblings)


class TestLongSectionSplitting(unittest.TestCase):
    """Sections > MAX_TOKENS split on (a)/(b)/(c) paragraph boundaries."""

    def test_split_on_paragraph_labels(self):
        para = " ".join(["alpha"] * 600)
        body = (
            f"(a) {para} (b) {para} (c) {para} (d) {para}"
        )
        section = make_cfr("1502.14", body, title="Alternatives")
        self.assertGreater(count_tokens(body), MAX_TOKENS)
        chunks = chunk_section(section)
        self.assertGreater(len(chunks), 1)
        for c in chunks:
            self.assertLessEqual(c.token_count, MAX_TOKENS + 200)  # +overlap
            self.assertIsNotNone(c.subsection)
            self.assertTrue(c.subsection.startswith("("))
        # Overlap is applied between consecutive chunks
        # (subsequent chunk gets a head injection from the prior chunk)
        self.assertGreater(chunks[1].token_count, chunks[0].token_count - 50)
        # chunk_index/total_chunks_in_section are populated
        self.assertEqual(chunks[0].chunk_index, 0)
        self.assertEqual(chunks[0].total_chunks_in_section, len(chunks))


class TestShortSectionMerging(unittest.TestCase):
    """Two sub-MIN_TOKENS sibling sections merge into one chunk."""

    def test_two_runts_merge(self):
        tiny = "Each agency shall comply with this part."  # ~10 tokens
        sections = [
            make_cfr("1500.6", tiny, title="Agency authority"),
            make_cfr("1500.5", tiny, title="Reducing delay"),
        ]
        chunks = chunk_sections(sections)
        self.assertEqual(len(chunks), 1)
        self.assertTrue(chunks[0].is_merged_siblings)
        self.assertEqual(len(chunks[0].sources), 2)
        # Both citations preserved
        cits = [s.citation for s in chunks[0].sources]
        self.assertIn("40 CFR \u00a71500.6", cits)
        self.assertIn("40 CFR \u00a71500.5", cits)

    def test_runts_in_different_parts_do_not_merge(self):
        tiny = "Each agency shall comply with this part."
        sections = [
            make_cfr("1500.6", tiny, title="Agency authority", part="1500"),
            make_cfr("1501.1", tiny, title="Purpose", part="1501"),
        ]
        chunks = chunk_sections(sections)
        # They might *backward* merge, but never via a Part-crossing path
        for c in chunks:
            if c.is_merged_siblings:
                parts = {s.part for s in c.sources}
                self.assertEqual(len(parts), 1)


class TestDefinitionChunking(unittest.TestCase):
    """Each Part 1508 definition becomes its own chunk regardless of size."""

    def test_each_definition_is_its_own_chunk(self):
        sections = [
            make_definition("1508.7", "Cumulative impact", "means the impact on the environment which results from..."),
            make_definition("1508.8", "Effects", "include direct and indirect effects..."),
            make_definition("1508.9", "Environmental assessment", "means a concise public document..."),
        ]
        chunks = chunk_sections(sections)
        self.assertEqual(len(chunks), 3)
        for c in chunks:
            self.assertTrue(c.is_definition)
            self.assertFalse(c.is_merged_siblings)
            self.assertEqual(len(c.sources), 1)

    def test_definition_breadcrumb_marker(self):
        sec = make_definition("1508.7", "Cumulative impact", "means impact...")
        c = chunk_section(sec)[0]
        breadcrumb = build_breadcrumb(c)
        self.assertIn("[DEFINITION]", breadcrumb)
        self.assertIn("1508.7", breadcrumb)


# --- breadcrumb tests -----------------------------------------------------

class TestBreadcrumbFormats(unittest.TestCase):

    def test_cfr_breadcrumb(self):
        sec = make_cfr("1501.3", "body", title="When to prepare an EA")
        sec.part_title = "NEPA and Agency Planning"
        c = chunk_section(sec)[0]
        b = build_breadcrumb(c)
        self.assertIn("Title 40", b)
        self.assertIn("Chapter V", b)
        self.assertIn("Part 1501", b)
        self.assertIn("\u00a71501.3", b)
        self.assertIn("When to prepare an EA", b)
        self.assertNotIn("[DEFINITION]", b)

    def test_statute_breadcrumb(self):
        sec = make_statute("102", "4332", "body", statute_title="Title I — Congressional Declaration")
        c = chunk_section(sec)[0]
        b = build_breadcrumb(c)
        self.assertIn("NEPA", b)
        self.assertIn("Title I", b)
        self.assertIn("4332", b)


# --- xref extraction tests ------------------------------------------------

class TestCrossReferences(unittest.TestCase):

    def test_extracts_cfr_and_usc(self):
        body = (
            "Each agency shall (see \u00a71508.9) comply with the requirements "
            "of \u00a7\u00a71501.7(b)(2) and 1501.8 unless 42 U.S.C. \u00a74332 "
            "applies. See section 102(2)(C)."
        )
        refs = extract_cross_references(body, self_citation="40 CFR \u00a71500.5")
        self.assertIn("40 CFR \u00a71508.9", refs)
        self.assertIn("40 CFR \u00a71501.7", refs)
        self.assertIn("42 USC \u00a74332", refs)
        self.assertIn("NEPA \u00a7102", refs)

    def test_self_reference_excluded(self):
        body = "This section (\u00a71500.5) refers to \u00a71501.7."
        refs = extract_cross_references(body, self_citation="40 CFR \u00a71500.5")
        self.assertNotIn("40 CFR \u00a71500.5", refs)
        self.assertIn("40 CFR \u00a71501.7", refs)


# --- token + metadata invariants ------------------------------------------

class TestTokenInvariants(unittest.TestCase):
    """Real-PDF chunks live within sane token bounds (allowing definitions
    and the documented preamble exception)."""

    @classmethod
    def setUpClass(cls):
        cls.pdf = Path(__file__).resolve().parent.parent / "NEPA-40CFR1500_1508.pdf"
        if not cls.pdf.exists():
            raise unittest.SkipTest(f"PDF not found at {cls.pdf}")
        cls.sections, cls.warnings = parse_pdf(str(cls.pdf))
        cls.chunks = chunk_sections(cls.sections)

    def test_no_unbounded_oversize(self):
        # Definitions are allowed to exceed MAX_TOKENS (one-per-chunk rule).
        for c in self.chunks:
            if c.is_definition:
                continue
            self.assertLessEqual(
                c.token_count, MAX_TOKENS + 200,
                f"{c.sources[0].citation} = {c.token_count} tokens",
            )

    def test_orphan_runts_are_explained(self):
        # Allowed orphans: a section that is the FIRST or LAST in its
        # parent grouping with no eligible sibling. We accept these but
        # cap their count.
        runts = [
            c for c in self.chunks
            if c.token_count < MIN_TOKENS
            and not c.is_definition
            and not c.is_merged_siblings
        ]
        self.assertLessEqual(len(runts), 3, [c.sources[0].citation for c in runts])


class TestMetadataCompleteness(unittest.TestCase):

    def test_all_required_fields_present(self):
        sec = make_cfr("1501.3", "body text " * 50, title="When to prepare")
        c = chunk_section(sec)[0]
        breadcrumb = build_breadcrumb(c)
        meta = build_metadata(
            c, breadcrumb,
            source="40_CFR_1500-1508",
            source_file="NEPA.pdf",
            is_current=False,
        )
        required = {
            "source", "source_file", "citation", "title", "part",
            "part_title", "section", "chunk_index", "total_chunks_in_section",
            "document_type", "agency", "statute", "effective_date",
            "breadcrumb", "token_count", "page_numbers", "has_table",
            "is_definition", "cross_references", "is_current",
        }
        for k in required:
            self.assertIn(k, meta, f"missing key: {k}")
            if k != "subsection":
                self.assertIsNotNone(meta[k], f"None value: {k}")


# --- real-PDF smoke -------------------------------------------------------

class TestRealPdfSmoke(unittest.TestCase):
    """End-to-end sanity checks against the actual 40 CFR 1500-1508 PDF."""

    @classmethod
    def setUpClass(cls):
        cls.pdf = Path(__file__).resolve().parent.parent / "NEPA-40CFR1500_1508.pdf"
        if not cls.pdf.exists():
            raise unittest.SkipTest(f"PDF not found at {cls.pdf}")
        cls.sections, cls.warnings = parse_pdf(str(cls.pdf))
        cls.chunks = chunk_sections(cls.sections)

    def test_zero_parser_warnings(self):
        self.assertEqual(self.warnings, [])

    def test_all_nine_cfr_parts_present(self):
        parts = {
            s.part for s in self.sections
            if s.document_type == DocumentType.CFR_REGULATION and s.part
        }
        self.assertEqual(
            parts,
            {"1500", "1501", "1502", "1503", "1504", "1505", "1506", "1507", "1508"},
        )

    def test_part_1508_has_28_definition_sections(self):
        defs = [
            s for s in self.sections
            if s.document_type == DocumentType.CFR_REGULATION
            and s.part == "1508"
        ]
        # §1508.1 through §1508.28
        self.assertEqual(len(defs), 28)

    def test_statute_sections_present(self):
        nepa_secs = [s for s in self.sections
                     if s.document_type == DocumentType.STATUTE
                     and s.parent_statute == "NEPA"]
        # NEPA: Sec 2 (Purpose) + Sec 101-105 (6) + Sec 201-209 (9) = 16
        self.assertGreaterEqual(len(nepa_secs), 15)

    def test_executive_order_sections_present(self):
        eo_secs = [s for s in self.sections
                   if s.document_type == DocumentType.EXECUTIVE_ORDER]
        self.assertGreaterEqual(len(eo_secs), 3)

    def test_appendix_section_uses_2005_effective_date(self):
        # The 2005 amendment to §1506.9 lives on the last content page.
        appendix = [
            s for s in self.sections
            if s.section == "1506.9" and 46 in s.pages
        ]
        self.assertEqual(len(appendix), 1)
        self.assertEqual(appendix[0].effective_date, "2005-07-18")

    def test_chunks_carry_full_metadata(self):
        for c in self.chunks[:10]:
            breadcrumb = build_breadcrumb(c)
            meta = build_metadata(
                c, breadcrumb,
                source="40_CFR_1500-1508",
                source_file=self.pdf.name,
                is_current=False,
            )
            self.assertTrue(meta["citation"])
            self.assertTrue(meta["breadcrumb"])
            self.assertIsInstance(meta["page_numbers"], list)
            self.assertGreater(len(meta["page_numbers"]), 0)
            self.assertEqual(meta["is_current"], False)


class TestParsePdfFromBytes(unittest.TestCase):
    """parse_pdf must accept raw bytes so we can parse from DB BYTEA
    without writing the PDF to disk first."""

    def test_parse_pdf_accepts_bytes(self):
        pdf_path = SEED_PDF
        if not pdf_path.exists():
            self.skipTest("real PDF not present")
        raw = pdf_path.read_bytes()
        sections, warnings = parse_pdf(raw)
        self.assertGreater(len(sections), 50,
                           "should parse the same sections from bytes as from path")


if __name__ == "__main__":
    unittest.main(verbosity=2)

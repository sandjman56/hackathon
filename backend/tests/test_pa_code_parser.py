"""Unit and smoke tests for the PA Code parser."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

import pymupdf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rag.regulatory.parser import DocumentType, RawSection  # noqa: E402
from rag.regulatory.parser_pa_code import (  # noqa: E402
    LineType,
    classify_line,
    parse_pa_code_pdf,
    strip_browser_noise,
)

PA_CODE_PDF = Path(__file__).resolve().parent.parent / "PA-25-Chapter105.pdf"


# --- helper ---------------------------------------------------------------

def _make_pdf(text: str) -> bytes:
    """Create a tiny in-memory PDF with the given text."""
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 72), text, fontsize=10)
    blob = doc.tobytes()
    doc.close()
    return blob


# --- noise stripping ------------------------------------------------------

class TestNoiseStripping(unittest.TestCase):
    """Browser artifacts are removed from extracted text."""

    def test_strips_timestamp_header(self):
        text = "4/12/26, 11:28 AM\nPennsylvania Code\n§ 105.1. Definitions."
        result = strip_browser_noise(text)
        self.assertNotIn("4/12/26", result)
        self.assertNotIn("11:28 AM", result)
        self.assertIn("§ 105.1", result)

    def test_strips_about_blank_footer(self):
        text = "Some regulatory text here.\nabout:blank\n42/140"
        result = strip_browser_noise(text)
        self.assertNotIn("about:blank", result)
        self.assertNotIn("42/140", result)
        self.assertIn("Some regulatory text here.", result)

    def test_strips_pennsylvania_code_header(self):
        text = "4/12/26, 11:28 AM\nPennsylvania Code\nActual content here."
        result = strip_browser_noise(text)
        self.assertNotIn("Pennsylvania Code", result)
        self.assertIn("Actual content here.", result)

    def test_strips_close_window_link(self):
        text = "Close Window\nCHAPTER 105. DAM SAFETY"
        result = strip_browser_noise(text)
        self.assertNotIn("Close Window", result)
        self.assertIn("CHAPTER 105", result)

    def test_preserves_clean_text(self):
        text = "A person may not construct any structure without a permit."
        result = strip_browser_noise(text)
        self.assertEqual(result.strip(), text)


# --- line classification --------------------------------------------------

class TestLineClassification(unittest.TestCase):
    """Lines are classified correctly by type."""

    def test_section_header(self):
        result = classify_line("§ 105.14. Review of applications.")
        self.assertEqual(result.line_type, LineType.SECTION)
        self.assertEqual(result.section, "105.14")
        self.assertEqual(result.title, "Review of applications")

    def test_section_header_with_letter_suffix(self):
        result = classify_line("§ 105.13a. Complete applications.")
        self.assertEqual(result.line_type, LineType.SECTION)
        self.assertEqual(result.section, "105.13a")
        self.assertEqual(result.title, "Complete applications")

    def test_section_header_46a(self):
        result = classify_line(
            "§ 105.46a. Collection and disposal of waste materials."
        )
        self.assertEqual(result.line_type, LineType.SECTION)
        self.assertEqual(result.section, "105.46a")

    def test_reserved_section(self):
        result = classify_line("§ 105.72. [Reserved].")
        self.assertEqual(result.line_type, LineType.RESERVED)

    def test_subchapter_header(self):
        result = classify_line("Subchapter B. DAMS AND RESERVOIRS")
        self.assertEqual(result.line_type, LineType.SUBCHAPTER)
        self.assertEqual(result.letter, "B")
        self.assertEqual(result.title, "DAMS AND RESERVOIRS")

    def test_group_header(self):
        result = classify_line("GENERAL PROVISIONS")
        self.assertEqual(result.line_type, LineType.GROUP)
        self.assertEqual(result.title, "GENERAL PROVISIONS")

    def test_group_header_permit_applications(self):
        result = classify_line("PERMIT APPLICATIONS")
        self.assertEqual(result.line_type, LineType.GROUP)

    def test_metadata_authority(self):
        result = classify_line("Authority")
        self.assertEqual(result.line_type, LineType.META_BLOCK)
        self.assertEqual(result.meta_type, "authority")

    def test_metadata_source(self):
        result = classify_line("Source")
        self.assertEqual(result.line_type, LineType.META_BLOCK)
        self.assertEqual(result.meta_type, "source_history")

    def test_metadata_cross_references(self):
        result = classify_line("Cross References")
        self.assertEqual(result.line_type, LineType.META_BLOCK)
        self.assertEqual(result.meta_type, "cross_references")

    def test_metadata_notes_of_decisions(self):
        result = classify_line("Notes of Decisions")
        self.assertEqual(result.line_type, LineType.META_BLOCK)
        self.assertEqual(result.meta_type, "notes_of_decisions")

    def test_body_text(self):
        result = classify_line("A person may not construct any structure.")
        self.assertEqual(result.line_type, LineType.BODY)

    def test_appendix_reserved(self):
        result = classify_line("APPENDIX A")
        self.assertEqual(result.line_type, LineType.APPENDIX)

    def test_toc_entry_ignored(self):
        result = classify_line("105.14. Review of applications.")
        self.assertEqual(result.line_type, LineType.TOC_ENTRY)


# --- parse function -------------------------------------------------------

class TestParsePaCodePdf(unittest.TestCase):
    """Full parse of synthetic PA Code documents."""

    def test_parses_single_section(self):
        text = (
            "§ 105.2. Purposes.\n\n"
            "The purposes of this chapter are to:\n"
            "(1) Provide for the comprehensive regulation and supervision of dams.\n"
            "(2) Protect the health, safety, welfare and property of the people.\n"
        )
        blob = _make_pdf(text)
        sections, warnings = parse_pa_code_pdf(blob)
        self.assertEqual(len(sections), 1)
        s = sections[0]
        self.assertEqual(s.document_type, DocumentType.STATE_CODE)
        self.assertEqual(s.section, "105.2")
        self.assertEqual(s.title, "Purposes")
        self.assertEqual(s.citation, "25 Pa. Code § 105.2")
        self.assertIn("comprehensive regulation", s.body)

    def test_skips_reserved_sections(self):
        text = (
            "§ 105.71. Scope.\n\n"
            "This subchapter governs dams.\n\n"
            "§ 105.72. [Reserved].\n\n"
            "Source\n\nThe provisions of this section...\n\n"
            "§ 105.81. Permit applications.\n\n"
            "Permit applications must include the following.\n"
        )
        blob = _make_pdf(text)
        sections, _ = parse_pa_code_pdf(blob)
        section_nums = [s.section for s in sections]
        self.assertIn("105.71", section_nums)
        self.assertNotIn("105.72", section_nums)
        self.assertIn("105.81", section_nums)

    def test_separates_metadata_from_body(self):
        text = (
            "§ 105.2. Purposes.\n\n"
            "The purposes of this chapter are to provide regulation.\n\n"
            "Authority\n\n"
            "The provisions issued under section 7 of the act.\n\n"
            "Source\n\n"
            "Adopted September 10, 1971.\n\n"
            "Cross References\n\n"
            "This section cited in 25 Pa. Code § 105.14.\n"
        )
        blob = _make_pdf(text)
        sections, _ = parse_pa_code_pdf(blob)
        self.assertEqual(len(sections), 1)
        s = sections[0]
        self.assertIn("provide regulation", s.body)
        self.assertNotIn("issued under section 7", s.body)
        self.assertNotIn("Adopted September", s.body)
        self.assertNotIn("cited in 25 Pa", s.body)

    @unittest.skipUnless(PA_CODE_PDF.exists(), "PA Code PDF not present")
    def test_tracks_subchapter_context(self):
        """Real PDF assigns subchapter letters from Subchapter headers."""
        blob = PA_CODE_PDF.read_bytes()
        sections, _ = parse_pa_code_pdf(blob)
        # § 105.71 is in Subchapter B (Dams and Reservoirs)
        sec_71 = [s for s in sections if s.section == "105.71"]
        self.assertGreater(len(sec_71), 0, "§ 105.71 not found")
        self.assertEqual(sec_71[0].part, "B")
        self.assertEqual(sec_71[0].part_title, "DAMS AND RESERVOIRS")


# --- smoke tests against real PDF -----------------------------------------

class TestRealPdfSmoke(unittest.TestCase):
    """Smoke tests against the actual PA Code PDF."""

    @unittest.skipUnless(PA_CODE_PDF.exists(), "PA Code PDF not present")
    def test_parses_real_pdf(self):
        blob = PA_CODE_PDF.read_bytes()
        sections, warnings = parse_pa_code_pdf(blob)
        # Chapter 105 has roughly 80-160 non-reserved sections
        self.assertGreater(len(sections), 60)
        self.assertLess(len(sections), 200)

    @unittest.skipUnless(PA_CODE_PDF.exists(), "PA Code PDF not present")
    def test_all_sections_have_state_code_type(self):
        blob = PA_CODE_PDF.read_bytes()
        sections, _ = parse_pa_code_pdf(blob)
        for s in sections:
            self.assertEqual(
                s.document_type, DocumentType.STATE_CODE,
                f"wrong type for {s.section}",
            )

    @unittest.skipUnless(PA_CODE_PDF.exists(), "PA Code PDF not present")
    def test_all_citations_use_pa_code_format(self):
        blob = PA_CODE_PDF.read_bytes()
        sections, _ = parse_pa_code_pdf(blob)
        for s in sections:
            self.assertTrue(
                s.citation.startswith("25 Pa. Code §"),
                f"bad citation format: {s.citation}",
            )

    @unittest.skipUnless(PA_CODE_PDF.exists(), "PA Code PDF not present")
    def test_definitions_section_exists(self):
        blob = PA_CODE_PDF.read_bytes()
        sections, _ = parse_pa_code_pdf(blob)
        sec_105_1 = [s for s in sections if s.section == "105.1"]
        self.assertGreater(len(sec_105_1), 0, "§ 105.1 (Definitions) not found")

    @unittest.skipUnless(PA_CODE_PDF.exists(), "PA Code PDF not present")
    def test_no_reserved_sections_in_output(self):
        blob = PA_CODE_PDF.read_bytes()
        sections, _ = parse_pa_code_pdf(blob)
        for s in sections:
            self.assertNotIn(
                "[Reserved]", s.title,
                f"reserved section emitted: {s.section}",
            )

    @unittest.skipUnless(PA_CODE_PDF.exists(), "PA Code PDF not present")
    def test_metadata_not_in_body(self):
        blob = PA_CODE_PDF.read_bytes()
        sections, _ = parse_pa_code_pdf(blob)
        for s in sections:
            self.assertNotIn(
                "The provisions of this §",
                s.body,
                f"metadata leaked into body of {s.section}",
            )


# --- chunker --------------------------------------------------------------

from rag.regulatory.chunker import Chunk, chunk_section  # noqa: E402


class TestPaCodeChunking(unittest.TestCase):

    def test_pa_definition_treated_as_definition(self):
        raw = RawSection(
            document_type=DocumentType.STATE_CODE,
            section="105.1", title="Definitions",
            body="Wetlands\u2014Areas that are inundated by surface water.",
            citation="25 Pa. Code \u00a7 105.1",
            pages=[5], part="A", part_title="General Provisions",
        )
        chunks = chunk_section(raw)
        self.assertEqual(len(chunks), 1)
        self.assertTrue(chunks[0].is_definition)


# --- xref -----------------------------------------------------------------

from rag.regulatory.xref import extract_cross_references  # noqa: E402


class TestPaCodeXref(unittest.TestCase):

    def test_extracts_pa_code_ref(self):
        text = "as defined in 25 Pa. Code § 105.14(b) relating to review."
        refs = extract_cross_references(text)
        self.assertIn("25 Pa. Code § 105.14", refs)

    def test_extracts_bare_pa_section_ref(self):
        text = "the factors included in § 105.13(d) and § 105.14(b)."
        refs = extract_cross_references(text, self_citation="25 Pa. Code § 105.15")
        self.assertIn("25 Pa. Code § 105.13", refs)
        self.assertIn("25 Pa. Code § 105.14", refs)

    def test_extracts_pa_statute_ref(self):
        text = "Dam Safety and Encroachments Act (32 P.S. §§ 693.1—693.27)."
        refs = extract_cross_references(text)
        self.assertIn("32 P.S. § 693.1", refs)

    def test_excludes_self_citation(self):
        text = "25 Pa. Code § 105.14 and 25 Pa. Code § 105.15."
        refs = extract_cross_references(text, self_citation="25 Pa. Code § 105.14")
        self.assertNotIn("25 Pa. Code § 105.14", refs)
        self.assertIn("25 Pa. Code § 105.15", refs)

    def test_existing_federal_refs_still_work(self):
        text = "as required by 40 CFR §1501.3 and 42 USC §4332."
        refs = extract_cross_references(text)
        self.assertIn("40 CFR §1501.3", refs)
        self.assertIn("42 USC §4332", refs)


# --- breadcrumbs ----------------------------------------------------------

from rag.regulatory.breadcrumbs import build_breadcrumb  # noqa: E402
from rag.regulatory.chunker import Chunk  # noqa: E402


class TestStateCodeBreadcrumbs(unittest.TestCase):

    def _make_pa_raw(self, section="105.14", title="Review of applications",
                     part="A", part_title="General Provisions"):
        return RawSection(
            document_type=DocumentType.STATE_CODE,
            section=section, title=title,
            body="test body", citation=f"25 Pa. Code § {section}",
            pages=[1], part=part, part_title=part_title,
        )

    def test_basic_breadcrumb(self):
        raw = self._make_pa_raw()
        chunk = Chunk(sources=[raw], body="test", token_count=10)
        bc = build_breadcrumb(chunk)
        self.assertIn("Title 25", bc)
        self.assertIn("Chapter 105", bc)
        self.assertIn("Subchapter A", bc)
        self.assertIn("§ 105.14", bc)
        self.assertIn("Review of applications", bc)

    def test_definition_breadcrumb(self):
        raw = self._make_pa_raw(section="105.1", title="Definitions")
        chunk = Chunk(sources=[raw], body="Wetlands—areas...",
                      token_count=10, is_definition=True)
        bc = build_breadcrumb(chunk)
        self.assertIn("[DEFINITION]", bc)


# --- store metadata -------------------------------------------------------

from rag.regulatory.store import build_metadata, _ALLOWED_FILTER_KEYS  # noqa: E402


class TestPaCodeMetadata(unittest.TestCase):

    def _make_pa_chunk(self):
        raw = RawSection(
            document_type=DocumentType.STATE_CODE,
            section="105.14", title="Review of applications",
            body="Applications shall be reviewed.",
            citation="25 Pa. Code § 105.14",
            pages=[10], part="A", part_title="General Provisions",
        )
        return Chunk(sources=[raw], body=raw.body, token_count=8)

    def test_state_code_metadata_fields(self):
        chunk = self._make_pa_chunk()
        meta = build_metadata(
            chunk, breadcrumb="test breadcrumb",
            source="PA_25_Chapter105", source_file="PA-25-Chapter105.pdf",
            source_id="abc-123", is_current=True,
        )
        self.assertEqual(meta["document_type"], "state_code")
        self.assertEqual(meta["agency"], "PA DEP")
        self.assertEqual(meta["jurisdiction"], "Pennsylvania")
        self.assertEqual(meta["statute"], "PA Code")
        self.assertIn("pacodeandbulletin.gov", meta["url"])

    def test_jurisdiction_is_allowed_filter_key(self):
        self.assertIn("jurisdiction", _ALLOWED_FILTER_KEYS)


# --- parser auto-detect ---------------------------------------------------

from services.regulatory_ingest import detect_parser  # noqa: E402


class TestParserAutoDetect(unittest.TestCase):

    def _make_pdf(self, text: str) -> bytes:
        doc = pymupdf.open()
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 72), text, fontsize=10)
        blob = doc.tobytes()
        doc.close()
        return blob

    def test_detects_pa_code(self):
        blob = self._make_pdf("Pennsylvania Code\nCHAPTER 105. DAM SAFETY")
        self.assertEqual(detect_parser(blob), "pa_code")

    def test_detects_federal(self):
        blob = self._make_pdf("PART 1501—NEPA AND AGENCY PLANNING")
        self.assertEqual(detect_parser(blob), "federal")

    def test_defaults_to_federal(self):
        blob = self._make_pdf("Some random text with no clear markers.")
        self.assertEqual(detect_parser(blob), "federal")


if __name__ == "__main__":
    unittest.main()

# PA Code Chapter 105 Parser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a new parser for PA Code browser-printed PDFs so that 25 PA Code Chapter 105 (Dam Safety and Waterway Management) can be ingested into the regulatory screening RAG corpus alongside the existing NEPA federal corpus.

**Architecture:** New `parser_pa_code.py` module under `rag/regulatory/` with PA Code-specific section detection. The existing shared pipeline (chunker, embedder, store) is reused with minimal extensions: a new `STATE_CODE` document type, state-code breadcrumb format, PA citation xref patterns, and auto-detection in the ingest service.

**Tech Stack:** Python, pymupdf (fitz), regex, tiktoken, psycopg2/pgvector (existing)

**Spec:** `docs/superpowers/specs/2026-04-12-pa-code-parser-design.md`

**Source PDF:** `/Users/sanderschulman/Downloads/Pennsylvania Code.pdf` — copy into `backend/` as `PA-25-Chapter105.pdf` for test fixtures.

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `backend/rag/regulatory/parser_pa_code.py` | PA Code PDF parser: text extraction, noise stripping, section detection, metadata block extraction |
| Create | `backend/tests/test_pa_code_parser.py` | Unit + smoke tests for the PA Code parser |
| Modify | `backend/rag/regulatory/parser.py:36-39` | Add `STATE_CODE` to `DocumentType` enum |
| Modify | `backend/rag/regulatory/chunker.py:81-82` | Extend `_is_definition_section` to handle PA Code §105.1 |
| Modify | `backend/rag/regulatory/breadcrumbs.py:38-53` | Add `STATE_CODE` branch + `_state_code_breadcrumb` function |
| Modify | `backend/rag/regulatory/xref.py:23-35` | Add PA Code and PA Statute citation regexes |
| Modify | `backend/rag/regulatory/store.py:131-138` | Add `STATE_CODE` case to `build_metadata` |
| Modify | `backend/services/regulatory_ingest.py:66` | Auto-detect parser based on PDF content |

---

### Task 1: Add STATE_CODE to DocumentType enum

**Files:**
- Modify: `backend/rag/regulatory/parser.py:36-39`

- [ ] **Step 1: Add the new enum value**

In `backend/rag/regulatory/parser.py`, add `STATE_CODE` to the `DocumentType` enum:

```python
class DocumentType(str, Enum):
    CFR_REGULATION = "cfr_regulation"
    STATUTE = "statute"
    EXECUTIVE_ORDER = "executive_order"
    STATE_CODE = "state_code"
```

- [ ] **Step 2: Run existing tests to verify nothing breaks**

Run: `cd backend && python -m pytest tests/test_regulatory_parser.py -v`
Expected: All existing tests PASS (enum extension is backward-compatible)

- [ ] **Step 3: Commit**

```bash
git add backend/rag/regulatory/parser.py
git commit -m "feat(rag): add STATE_CODE to DocumentType enum"
```

---

### Task 2: Copy source PDF into backend for test fixtures

**Files:**
- Create: `backend/PA-25-Chapter105.pdf`

- [ ] **Step 1: Copy the PDF**

```bash
cp "/Users/sanderschulman/Downloads/Pennsylvania Code.pdf" backend/PA-25-Chapter105.pdf
```

- [ ] **Step 2: Add to .gitignore if PDFs aren't tracked, or git add**

Check if the NEPA PDF is tracked:

```bash
git ls-files backend/NEPA-40CFR1500_1508.pdf
```

If it's tracked, track this one too. If not, skip git add for the PDF. The test will `pytest.skip` if the file is absent.

- [ ] **Step 3: Commit (if tracked)**

```bash
git add backend/PA-25-Chapter105.pdf
git commit -m "chore: add PA Code Chapter 105 source PDF for parser development"
```

---

### Task 3: Build the PA Code parser — noise stripping and text extraction

**Files:**
- Create: `backend/rag/regulatory/parser_pa_code.py`
- Create: `backend/tests/test_pa_code_parser.py`

- [ ] **Step 1: Write the failing test for noise stripping**

Create `backend/tests/test_pa_code_parser.py`:

```python
"""Unit and smoke tests for the PA Code parser."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rag.regulatory.parser_pa_code import strip_browser_noise  # noqa: E402

PA_CODE_PDF = Path(__file__).resolve().parent.parent / "PA-25-Chapter105.pdf"


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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_pa_code_parser.py::TestNoiseStripping -v`
Expected: FAIL with `ImportError: cannot import name 'strip_browser_noise'`

- [ ] **Step 3: Implement strip_browser_noise**

Create `backend/rag/regulatory/parser_pa_code.py`:

```python
"""PDF -> ordered list of RawSection records for PA Code documents.

Handles browser-printed PDFs from pacodeandbulletin.gov (Chrome "Print to
PDF"). These have clean Unicode text but contain browser artifacts (timestamps,
about:blank footers, page numbers) that must be stripped.

The parser emits the same RawSection dataclass as the federal parser so the
shared chunker/embedder/store pipeline works without modification.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pymupdf

from .parser import DocumentType, RawSection

logger = logging.getLogger("eia.rag.regulatory.parser_pa_code")


# --- noise patterns -------------------------------------------------------

# Browser timestamp header: "4/12/26, 11:28 AM"
_RE_TIMESTAMP = re.compile(r"^\s*\d{1,2}/\d{1,2}/\d{2,4},?\s+\d{1,2}:\d{2}\s*[AP]M\s*$", re.MULTILINE)

# Right header: "Pennsylvania Code" (standalone line)
_RE_PA_CODE_HEADER = re.compile(r"^\s*Pennsylvania Code\s*$", re.MULTILINE)

# Left footer: "about:blank"
_RE_ABOUT_BLANK = re.compile(r"^\s*about:blank\s*$", re.MULTILINE)

# Page number footer: "N/140" or "1/140"
_RE_PAGE_NUMBER = re.compile(r"^\s*\d{1,3}/\d{1,3}\s*$", re.MULTILINE)

# "Close Window" link on page 1
_RE_CLOSE_WINDOW = re.compile(r"^\s*Close Window\s*$", re.MULTILINE)


def strip_browser_noise(text: str) -> str:
    """Remove browser-generated artifacts from page text."""
    text = _RE_TIMESTAMP.sub("", text)
    text = _RE_PA_CODE_HEADER.sub("", text)
    text = _RE_ABOUT_BLANK.sub("", text)
    text = _RE_PAGE_NUMBER.sub("", text)
    text = _RE_CLOSE_WINDOW.sub("", text)
    # Collapse multiple blank lines left by removals
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_pa_code_parser.py::TestNoiseStripping -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/rag/regulatory/parser_pa_code.py backend/tests/test_pa_code_parser.py
git commit -m "feat(rag): PA Code parser — noise stripping foundation"
```

---

### Task 4: PA Code parser — section header detection and parsing

**Files:**
- Modify: `backend/rag/regulatory/parser_pa_code.py`
- Modify: `backend/tests/test_pa_code_parser.py`

- [ ] **Step 1: Write failing tests for section detection**

Append to `backend/tests/test_pa_code_parser.py`:

```python
from rag.regulatory.parser_pa_code import (  # noqa: E402
    classify_line,
    LineType,
)


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

    def test_section_header_with_letter_suffix_46a(self):
        result = classify_line("§ 105.46a. Collection and disposal of waste materials.")
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
        self.assertEqual(result.meta_type, "source")

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
        # TOC lines have section number + title but no "§" prefix
        result = classify_line("105.14. Review of applications.")
        self.assertEqual(result.line_type, LineType.TOC_ENTRY)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_pa_code_parser.py::TestLineClassification -v`
Expected: FAIL with `ImportError: cannot import name 'classify_line'`

- [ ] **Step 3: Implement classify_line and LineType**

Add to `backend/rag/regulatory/parser_pa_code.py`:

```python
from enum import Enum


class LineType(str, Enum):
    SECTION = "section"
    RESERVED = "reserved"
    SUBCHAPTER = "subchapter"
    GROUP = "group"
    META_BLOCK = "meta_block"
    BODY = "body"
    APPENDIX = "appendix"
    TOC_ENTRY = "toc_entry"
    CHAPTER_TITLE = "chapter_title"


@dataclass
class LineClassification:
    """Result of classifying a single line of text."""
    line_type: LineType
    section: Optional[str] = None
    title: Optional[str] = None
    letter: Optional[str] = None
    meta_type: Optional[str] = None


# --- line detection regexes -----------------------------------------------

# Section header: "§ 105.14. Review of applications."
_RE_PA_SECTION = re.compile(
    r"^\s*§\s*(?P<section>\d+\.\d+[a-z]?)\.?\s+(?P<title>[A-Z].+?)\.?\s*$"
)

# Reserved section: "§ 105.72. [Reserved]."
_RE_RESERVED = re.compile(
    r"^\s*§\s*\d+\.\d+[a-z]?\.?\s+\[Reserved\]\.?\s*$"
)

# Subchapter: "Subchapter B. DAMS AND RESERVOIRS"
_RE_SUBCHAPTER = re.compile(
    r"^\s*Subchapter\s+(?P<letter>[A-Z])\.?\s+(?P<title>[A-Z].+?)\s*$"
)

# Section group headers: all-caps text like "GENERAL PROVISIONS"
# Must be at least 2 words to avoid matching single-word body lines
_RE_GROUP = re.compile(
    r"^(?P<title>[A-Z][A-Z,\s\-—]+[A-Z])\s*$"
)

# Known group header values (whitelist to avoid false positives on body text)
_KNOWN_GROUPS = {
    "GENERAL", "GENERAL PROVISIONS", "PERMIT APPLICATIONS",
    "PERMIT ISSUANCE, TRANSFER AND REVOCATION",
    "SUBMERGED LANDS OF THE COMMONWEALTH—LICENSES AND ANNUAL CHARGES",
    "CONSTRUCTION REQUIREMENTS AND PROCEDURES",
    "OPERATION, MAINTENANCE AND INSPECTION",
    "INVESTIGATION AND CORRECTION OF UNSAFE CONDITIONS—EMERGENCY PROCEDURES",
    "PERMITS", "PERMITS, LETTERS OF AMENDMENTS AND LETTERS OF AUTHORIZATIONS",
    "CLASSIFICATION AND DESIGN CRITERIA FOR APPROVAL OF CONSTRUCTION, OPERATION, MODIFICATION AND MAINTENANCE",
    "CONSTRUCTION REQUIREMENTS AND PROCEDURES",
    "STORAGE AND DISCHARGE",
    "PROTECTION AND RESTORATION OF AQUATIC LIFE",
    "OPERATION, MAINTENANCE AND EMERGENCIES",
    "CRITERIA FOR APPROVAL OF CONSTRUCTION OR MODIFICATION",
    "MAINTENANCE", "CONSTRUCTION AND MAINTENANCE",
    "CRITERIA FOR APPROVAL FOR CONSTRUCTION OR MODIFICATION",
    "WETLANDS", "GENERAL PERMITS",
}

# Metadata block headers
_META_KEYWORDS = {
    "Authority": "authority",
    "Source": "source",
    "Cross References": "cross_references",
    "Notes of Decisions": "notes_of_decisions",
}

# Appendix header: "APPENDIX A"
_RE_APPENDIX = re.compile(r"^\s*APPENDIX\s+[A-Z]\s*$")

# Chapter title: "CHAPTER 105. DAM SAFETY AND WATERWAY MANAGEMENT"
_RE_CHAPTER_TITLE = re.compile(r"^\s*CHAPTER\s+\d+\.\s+")

# TOC entry: "105.14. Review of applications." (no § prefix)
_RE_TOC_ENTRY = re.compile(r"^\s*\d+\.\d+[a-z]?\.?\s+[A-Z]")

# TOC section number with underline (hyperlink): "105.14."
_RE_TOC_LINKED = re.compile(r"^\s*\d+\.\d+[a-z]?\.\s*$")


def classify_line(line: str) -> LineClassification:
    """Classify a single line of PA Code text by its structural role."""
    stripped = line.strip()
    if not stripped:
        return LineClassification(LineType.BODY)

    # Reserved must be checked before general section pattern
    if _RE_RESERVED.match(stripped):
        return LineClassification(LineType.RESERVED)

    if (m := _RE_PA_SECTION.match(stripped)):
        return LineClassification(
            LineType.SECTION,
            section=m["section"],
            title=m["title"].rstrip("."),
        )

    if (m := _RE_SUBCHAPTER.match(stripped)):
        return LineClassification(
            LineType.SUBCHAPTER,
            letter=m["letter"],
            title=m["title"].strip(),
        )

    if _RE_APPENDIX.match(stripped):
        return LineClassification(LineType.APPENDIX)

    if _RE_CHAPTER_TITLE.match(stripped):
        return LineClassification(LineType.CHAPTER_TITLE)

    # Metadata blocks (exact match on known keywords)
    if stripped in _META_KEYWORDS:
        return LineClassification(
            LineType.META_BLOCK,
            meta_type=_META_KEYWORDS[stripped],
        )

    # Group headers: must match all-caps pattern AND be in known set
    if _RE_GROUP.match(stripped):
        # Normalize for lookup (collapse whitespace)
        normalized = " ".join(stripped.split())
        if normalized in _KNOWN_GROUPS:
            return LineClassification(LineType.GROUP, title=normalized)

    # TOC entries (section number without § prefix)
    if _RE_TOC_ENTRY.match(stripped) and not stripped.startswith("§"):
        return LineClassification(LineType.TOC_ENTRY)
    if _RE_TOC_LINKED.match(stripped):
        return LineClassification(LineType.TOC_ENTRY)

    return LineClassification(LineType.BODY)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_pa_code_parser.py -v`
Expected: All tests PASS (noise + classification)

- [ ] **Step 5: Commit**

```bash
git add backend/rag/regulatory/parser_pa_code.py backend/tests/test_pa_code_parser.py
git commit -m "feat(rag): PA Code parser — line classification and section detection"
```

---

### Task 5: PA Code parser — full parse_pa_code_pdf function

**Files:**
- Modify: `backend/rag/regulatory/parser_pa_code.py`
- Modify: `backend/tests/test_pa_code_parser.py`

- [ ] **Step 1: Write failing test for the main parse function**

Append to `backend/tests/test_pa_code_parser.py`:

```python
from rag.regulatory.parser_pa_code import parse_pa_code_pdf  # noqa: E402
from rag.regulatory.parser import DocumentType  # noqa: E402


class TestParsePaCodePdf(unittest.TestCase):
    """Full parse of a synthetic PA Code document."""

    def _make_minimal_pdf(self, text: str) -> bytes:
        """Create a tiny in-memory PDF with the given text."""
        doc = pymupdf.open()
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 72), text, fontsize=10)
        blob = doc.tobytes()
        doc.close()
        return blob

    def test_parses_single_section(self):
        text = (
            "§ 105.2. Purposes.\n\n"
            "The purposes of this chapter are to:\n"
            "(1) Provide for the comprehensive regulation and supervision of dams.\n"
            "(2) Protect the health, safety, welfare and property of the people.\n"
        )
        blob = self._make_minimal_pdf(text)
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
        blob = self._make_minimal_pdf(text)
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
        blob = self._make_minimal_pdf(text)
        sections, _ = parse_pa_code_pdf(blob)
        self.assertEqual(len(sections), 1)
        s = sections[0]
        self.assertIn("provide regulation", s.body)
        self.assertNotIn("issued under section 7", s.body)
        self.assertNotIn("Adopted September", s.body)
        self.assertNotIn("cited in 25 Pa", s.body)

    def test_tracks_subchapter_context(self):
        text = (
            "Subchapter B. DAMS AND RESERVOIRS\n\n"
            "GENERAL PROVISIONS\n\n"
            "§ 105.71. Scope.\n\n"
            "This subchapter governs dams.\n"
        )
        blob = self._make_minimal_pdf(text)
        sections, _ = parse_pa_code_pdf(blob)
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0].part, "B")
        self.assertEqual(sections[0].part_title, "DAMS AND RESERVOIRS")


class TestRealPdfSmoke(unittest.TestCase):
    """Smoke tests against the actual PA Code PDF."""

    @unittest.skipUnless(PA_CODE_PDF.exists(), "PA Code PDF not present")
    def test_parses_real_pdf(self):
        blob = PA_CODE_PDF.read_bytes()
        sections, warnings = parse_pa_code_pdf(blob)
        # Chapter 105 has roughly 80-100 non-reserved sections
        self.assertGreater(len(sections), 60)
        self.assertLess(len(sections), 150)

    @unittest.skipUnless(PA_CODE_PDF.exists(), "PA Code PDF not present")
    def test_all_sections_have_state_code_type(self):
        blob = PA_CODE_PDF.read_bytes()
        sections, _ = parse_pa_code_pdf(blob)
        for s in sections:
            self.assertEqual(s.document_type, DocumentType.STATE_CODE, f"wrong type for {s.section}")

    @unittest.skipUnless(PA_CODE_PDF.exists(), "PA Code PDF not present")
    def test_all_citations_use_pa_code_format(self):
        blob = PA_CODE_PDF.read_bytes()
        sections, _ = parse_pa_code_pdf(blob)
        for s in sections:
            self.assertTrue(
                s.citation.startswith("25 Pa. Code §"),
                f"bad citation format: {s.citation}"
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
            self.assertNotIn("[Reserved]", s.title, f"reserved section emitted: {s.section}")

    @unittest.skipUnless(PA_CODE_PDF.exists(), "PA Code PDF not present")
    def test_metadata_not_in_body(self):
        blob = PA_CODE_PDF.read_bytes()
        sections, _ = parse_pa_code_pdf(blob)
        for s in sections:
            # Authority blocks cite the Dam Safety Act — that string should
            # be in metadata, not body text
            self.assertNotIn(
                "The provisions of this §",
                s.body,
                f"metadata leaked into body of {s.section}"
            )
```

Add `import pymupdf` to the test file imports.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_pa_code_parser.py::TestParsePaCodePdf -v`
Expected: FAIL with `ImportError: cannot import name 'parse_pa_code_pdf'`

- [ ] **Step 3: Implement parse_pa_code_pdf**

Add the main parse function to `backend/rag/regulatory/parser_pa_code.py`:

```python
@dataclass
class _PaCodeMetadata:
    """Metadata blocks extracted from after a section."""
    authority: Optional[str] = None
    source_history: Optional[str] = None
    cross_references: Optional[str] = None
    notes_of_decisions: Optional[str] = None


def parse_pa_code_pdf(
    source: bytes | str | Path,
) -> tuple[list[RawSection], list[str]]:
    """Parse a PA Code browser-printed PDF into RawSection records.

    Args:
        source: PDF file path or raw bytes.

    Returns:
        (sections, warnings) — same contract as the federal ``parse_pdf``.
    """
    if isinstance(source, (str, Path)):
        doc = pymupdf.open(str(source))
    else:
        doc = pymupdf.open(stream=source, filetype="pdf")

    warnings: list[str] = []
    sections: list[RawSection] = []

    # Parser state
    current_subchapter_letter: Optional[str] = None
    current_subchapter_title: Optional[str] = None
    current_group: Optional[str] = None
    current_section: Optional[dict] = None
    current_meta_type: Optional[str] = None
    current_meta: _PaCodeMetadata = _PaCodeMetadata()
    in_appendix = False
    in_toc = True  # First few pages are TOC

    def _flush_section() -> None:
        """Emit the current section as a RawSection."""
        nonlocal current_section, current_meta, current_meta_type
        if current_section is None:
            return
        body = current_section["body"].strip()
        if not body:
            warnings.append(f"empty body for § {current_section['section']}")
            current_section = None
            current_meta = _PaCodeMetadata()
            current_meta_type = None
            return

        effective_date = _extract_effective_date(current_meta.source_history)

        sections.append(RawSection(
            document_type=DocumentType.STATE_CODE,
            section=current_section["section"],
            title=current_section["title"],
            body=body,
            citation=f"25 Pa. Code § {current_section['section']}",
            pages=sorted(set(current_section["pages"])),
            part=current_subchapter_letter,
            part_title=current_subchapter_title,
            parent_statute=None,
            statute_title=None,
            effective_date=effective_date,
        ))
        current_section = None
        current_meta = _PaCodeMetadata()
        current_meta_type = None

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        raw_text = page.get_text("text")
        text = strip_browser_noise(raw_text)
        page_num = page_idx + 1

        for line in text.split("\n"):
            cl = classify_line(line)

            # Skip appendices entirely
            if cl.line_type == LineType.APPENDIX:
                _flush_section()
                in_appendix = True
                continue
            if in_appendix:
                continue

            # Detect end of TOC: first real section header
            if cl.line_type == LineType.SECTION and in_toc:
                in_toc = False

            # Skip TOC entries
            if in_toc or cl.line_type == LineType.TOC_ENTRY:
                continue

            if cl.line_type == LineType.CHAPTER_TITLE:
                continue

            if cl.line_type == LineType.SUBCHAPTER:
                _flush_section()
                current_subchapter_letter = cl.letter
                current_subchapter_title = cl.title
                current_group = None
                continue

            if cl.line_type == LineType.GROUP:
                current_group = cl.title
                continue

            if cl.line_type == LineType.RESERVED:
                _flush_section()
                continue

            if cl.line_type == LineType.SECTION:
                _flush_section()
                current_section = {
                    "section": cl.section,
                    "title": cl.title,
                    "body": "",
                    "pages": [page_num],
                    "group": current_group,
                }
                current_meta_type = None
                continue

            if cl.line_type == LineType.META_BLOCK:
                current_meta_type = cl.meta_type
                continue

            if cl.line_type == LineType.BODY:
                stripped = line.strip()
                if not stripped:
                    continue
                # If we're inside a metadata block, accumulate there
                if current_meta_type is not None:
                    current_text = getattr(current_meta, current_meta_type) or ""
                    setattr(current_meta, current_meta_type, current_text + " " + stripped)
                    continue
                # Otherwise append to section body
                if current_section is not None:
                    current_section["body"] += stripped + "\n"
                    if page_num not in current_section["pages"]:
                        current_section["pages"].append(page_num)

    _flush_section()
    doc.close()

    logger.info(
        "PA Code parse complete: %d sections, %d warnings",
        len(sections), len(warnings),
    )
    return sections, warnings


# --- helpers --------------------------------------------------------------

_RE_EFFECTIVE_DATE = re.compile(
    r"effective\s+(\w+\s+\d{1,2},?\s+\d{4})", re.IGNORECASE
)


def _extract_effective_date(source_text: Optional[str]) -> Optional[str]:
    """Pull the first 'effective <date>' from a Source metadata block."""
    if not source_text:
        return None
    m = _RE_EFFECTIVE_DATE.search(source_text)
    if not m:
        return None
    return m.group(1).strip()
```

- [ ] **Step 4: Run all tests**

Run: `cd backend && python -m pytest tests/test_pa_code_parser.py -v`
Expected: All tests PASS (noise, classification, parse, smoke)

- [ ] **Step 5: Commit**

```bash
git add backend/rag/regulatory/parser_pa_code.py backend/tests/test_pa_code_parser.py
git commit -m "feat(rag): PA Code parser — full parse_pa_code_pdf implementation"
```

---

### Task 6: Extend breadcrumbs for STATE_CODE

**Files:**
- Modify: `backend/rag/regulatory/breadcrumbs.py:38-53`
- Modify: `backend/tests/test_pa_code_parser.py`

- [ ] **Step 1: Write failing test for state code breadcrumbs**

Append to `backend/tests/test_pa_code_parser.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_pa_code_parser.py::TestStateCodeBreadcrumbs -v`
Expected: FAIL with `ValueError: unknown document_type: state_code`

- [ ] **Step 3: Implement _state_code_breadcrumb in breadcrumbs.py**

Add to `backend/rag/regulatory/breadcrumbs.py`:

```python
# After the existing static parents, add:
_PA_TITLE_25 = "Title 25 \u2014 Environmental Protection"
_PA_CHAPTER_105 = "Chapter 105 \u2014 Dam Safety and Waterway Management"
```

In `build_breadcrumb`, add the STATE_CODE branch before the raise:

```python
    if primary.document_type == DocumentType.STATE_CODE:
        return _state_code_breadcrumb(chunk, primary)
```

Add the function:

```python
def _state_code_breadcrumb(chunk: Chunk, raw: RawSection) -> str:
    subchapter_label = f"Subchapter {raw.part}"
    if raw.part_title:
        subchapter_label = f"{subchapter_label} \u2014 {raw.part_title}"

    if chunk.is_merged_siblings and len(chunk.sources) > 1:
        first = chunk.sources[0]
        last = chunk.sources[-1]
        section_label = (
            f"\u00a7 {first.section}\u2013{last.section} \u2014 "
            + " / ".join(s.title for s in chunk.sources)
        )
    else:
        section_label = f"\u00a7 {raw.section} \u2014 {raw.title}"

    if chunk.is_definition:
        section_label = f"{section_label} [DEFINITION]"
    if chunk.subsection:
        section_label = f"{section_label} {chunk.subsection}"

    parts = [_PA_TITLE_25, _PA_CHAPTER_105, subchapter_label, section_label]
    return " > ".join(parts)
```

- [ ] **Step 4: Run tests**

Run: `cd backend && python -m pytest tests/test_pa_code_parser.py::TestStateCodeBreadcrumbs tests/test_regulatory_parser.py -v`
Expected: All PASS (new + existing breadcrumb tests)

- [ ] **Step 5: Commit**

```bash
git add backend/rag/regulatory/breadcrumbs.py backend/tests/test_pa_code_parser.py
git commit -m "feat(rag): state code breadcrumb format for PA Code chunks"
```

---

### Task 7: Extend xref for PA Code citations

**Files:**
- Modify: `backend/rag/regulatory/xref.py`
- Modify: `backend/tests/test_pa_code_parser.py`

- [ ] **Step 1: Write failing tests for PA citation extraction**

Append to `backend/tests/test_pa_code_parser.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_pa_code_parser.py::TestPaCodeXref -v`
Expected: FAIL — PA Code citations not recognized by current xref

- [ ] **Step 3: Add PA citation patterns to xref.py**

In `backend/rag/regulatory/xref.py`, add after the existing regex definitions:

```python
# PA Code: "25 Pa. Code § 105.14" / "§ 105.14(b)" (3-digit.digit+ pattern)
_RE_PA_CODE_REF = re.compile(
    r"(?:25\s*Pa\.?\s*Code\s+)?\u00a7{1,2}\s*(\d{2,3}\.\d+[a-z]?)(?:\([a-z0-9]+\))*"
)

# PA Statutes: "32 P.S. §§ 693.1" / "35 P.S. § 691.1"
_RE_PA_STATUTE_REF = re.compile(
    r"(\d{1,2})\s*P\.?\s*S\.?\s*\u00a7{1,2}\s*([\d.]+)"
)
```

In `extract_cross_references`, add before the return:

```python
    for m in _RE_PA_CODE_REF.finditer(text):
        section = m.group(1)
        # Only treat as PA Code ref if section starts with 1xx-2xx range
        # (avoids colliding with 4-digit CFR refs like §1501.3)
        if len(section.split(".")[0]) <= 3:
            _add(f"25 Pa. Code \u00a7 {section}")
    for m in _RE_PA_STATUTE_REF.finditer(text):
        title = m.group(1)
        section = m.group(2)
        _add(f"{title} P.S. \u00a7 {section}")
```

- [ ] **Step 4: Run all xref tests (new + existing)**

Run: `cd backend && python -m pytest tests/test_pa_code_parser.py::TestPaCodeXref tests/test_regulatory_parser.py -k xref -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/rag/regulatory/xref.py backend/tests/test_pa_code_parser.py
git commit -m "feat(rag): PA Code and PA Statute citation patterns in xref"
```

---

### Task 8: Extend chunker definition detection for PA Code

**Files:**
- Modify: `backend/rag/regulatory/chunker.py:81-82`
- Modify: `backend/tests/test_pa_code_parser.py`

- [ ] **Step 1: Write failing test**

Append to `backend/tests/test_pa_code_parser.py`:

```python
from rag.regulatory.chunker import chunk_section  # noqa: E402


class TestPaCodeChunking(unittest.TestCase):

    def test_pa_definition_treated_as_definition(self):
        raw = RawSection(
            document_type=DocumentType.STATE_CODE,
            section="105.1", title="Definitions",
            body="Wetlands—Areas that are inundated by surface water.",
            citation="25 Pa. Code § 105.1",
            pages=[5], part="A", part_title="General Provisions",
        )
        chunks = chunk_section(raw)
        self.assertEqual(len(chunks), 1)
        self.assertTrue(chunks[0].is_definition)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_pa_code_parser.py::TestPaCodeChunking -v`
Expected: FAIL — `is_definition` is False because `_is_definition_section` only checks `part == "1508"`

- [ ] **Step 3: Extend _is_definition_section**

In `backend/rag/regulatory/chunker.py`, change:

```python
def _is_definition_section(raw: RawSection) -> bool:
    return raw.document_type == DocumentType.CFR_REGULATION and raw.part == "1508"
```

To:

```python
def _is_definition_section(raw: RawSection) -> bool:
    if raw.document_type == DocumentType.CFR_REGULATION and raw.part == "1508":
        return True
    if raw.document_type == DocumentType.STATE_CODE and raw.section.endswith(".1"):
        return True
    return False
```

- [ ] **Step 4: Run tests (new + existing chunker tests)**

Run: `cd backend && python -m pytest tests/test_pa_code_parser.py::TestPaCodeChunking tests/test_regulatory_parser.py -k chunk -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/rag/regulatory/chunker.py backend/tests/test_pa_code_parser.py
git commit -m "feat(rag): chunker recognizes PA Code definition sections"
```

---

### Task 9: Extend store metadata for STATE_CODE

**Files:**
- Modify: `backend/rag/regulatory/store.py:131-168`
- Modify: `backend/tests/test_pa_code_parser.py`

- [ ] **Step 1: Write failing test**

Append to `backend/tests/test_pa_code_parser.py`:

```python
from rag.regulatory.store import build_metadata  # noqa: E402


class TestPaCodeMetadata(unittest.TestCase):

    def test_state_code_metadata_fields(self):
        raw = RawSection(
            document_type=DocumentType.STATE_CODE,
            section="105.14", title="Review of applications",
            body="An application will be reviewed.",
            citation="25 Pa. Code § 105.14",
            pages=[30, 31], part="A", part_title="General Provisions",
        )
        chunk = Chunk(sources=[raw], body=raw.body, token_count=10)
        bc = "Title 25 > Chapter 105 > Subchapter A > § 105.14"
        meta = build_metadata(
            chunk, bc,
            source="PA-25-Chapter105",
            source_file="PA-25-Chapter105.pdf",
            source_id="test-uuid",
            is_current=True,
        )
        self.assertEqual(meta["document_type"], "state_code")
        self.assertEqual(meta["citation"], "25 Pa. Code § 105.14")
        self.assertEqual(meta["agency"], "PA DEP")
        self.assertEqual(meta["jurisdiction"], "Pennsylvania")
        self.assertTrue(meta["is_current"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_pa_code_parser.py::TestPaCodeMetadata -v`
Expected: FAIL — `document_type` comes out as `"unknown"`, `agency` is `"CEQ"`

- [ ] **Step 3: Extend build_metadata for STATE_CODE**

In `backend/rag/regulatory/store.py`, update the `build_metadata` function.

Change the document_type mapping:

```python
    if primary.document_type == DocumentType.CFR_REGULATION:
        document_type = "cfr_regulation"
    elif primary.document_type == DocumentType.STATUTE:
        document_type = "statute"
    elif primary.document_type == DocumentType.EXECUTIVE_ORDER:
        document_type = "executive_order"
    elif primary.document_type == DocumentType.STATE_CODE:
        document_type = "state_code"
    else:
        document_type = "unknown"
```

Update the metadata dict construction to handle state code fields. Replace the hardcoded `agency` and `statute` lines:

```python
    is_state = primary.document_type == DocumentType.STATE_CODE

    return {
        "source": source,
        "source_file": source_file,
        "source_id": source_id,
        "citation": primary.citation,
        "all_citations": citations,
        "title": primary.title,
        "part": primary.part,
        "part_title": primary.part_title,
        "section": primary.section,
        "subsection": chunk.subsection,
        "chunk_index": chunk.chunk_index,
        "total_chunks_in_section": chunk.total_chunks_in_section,
        "document_type": document_type,
        "agency": "PA DEP" if is_state else "CEQ",
        "jurisdiction": "Pennsylvania" if is_state else "Federal",
        "statute": primary.parent_statute or ("PA Code" if is_state else "NEPA"),
        "statute_title": primary.statute_title,
        "effective_date": primary.effective_date,
        "is_current": is_current,
        "url": (
            "https://www.pacodeandbulletin.gov/Display/pacode?file=/secure/pacode/data/025/chapter105/chap105toc.html"
            if is_state else
            "https://www.ecfr.gov/current/title-40/chapter-V/subchapter-A"
        ),
        "breadcrumb": breadcrumb,
        "token_count": chunk.token_count,
        "page_numbers": pages,
        "has_table": chunk.has_table,
        "is_definition": chunk.is_definition,
        "is_merged_siblings": chunk.is_merged_siblings,
        "cross_references": cross_refs,
    }
```

Also add the `jurisdiction` key to the `_ALLOWED_FILTER_KEYS` set:

```python
_ALLOWED_FILTER_KEYS = {
    "part",
    "document_type",
    "statute",
    "section",
    "agency",
    "source",
    "jurisdiction",
    "is_current",
    "is_definition",
}
```

- [ ] **Step 4: Run all tests**

Run: `cd backend && python -m pytest tests/test_pa_code_parser.py::TestPaCodeMetadata tests/test_regulatory_parser.py tests/test_regulatory_store.py -v`
Expected: All PASS (new + existing)

- [ ] **Step 5: Commit**

```bash
git add backend/rag/regulatory/store.py backend/tests/test_pa_code_parser.py
git commit -m "feat(rag): store metadata supports STATE_CODE with PA DEP fields"
```

---

### Task 10: Auto-detect parser in ingest service

**Files:**
- Modify: `backend/services/regulatory_ingest.py`
- Modify: `backend/tests/test_pa_code_parser.py`

- [ ] **Step 1: Write failing test for auto-detection**

Append to `backend/tests/test_pa_code_parser.py`:

```python
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
        parser_name = detect_parser(blob)
        self.assertEqual(parser_name, "pa_code")

    def test_detects_federal(self):
        blob = self._make_pdf("PART 1501—NEPA AND AGENCY PLANNING")
        parser_name = detect_parser(blob)
        self.assertEqual(parser_name, "federal")

    def test_defaults_to_federal(self):
        blob = self._make_pdf("Some random text with no clear markers.")
        parser_name = detect_parser(blob)
        self.assertEqual(parser_name, "federal")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_pa_code_parser.py::TestParserAutoDetect -v`
Expected: FAIL with `ImportError: cannot import name 'detect_parser'`

- [ ] **Step 3: Implement detect_parser and integrate into ingest**

In `backend/services/regulatory_ingest.py`, add the import:

```python
from rag.regulatory.parser_pa_code import parse_pa_code_pdf
```

Add the detection function:

```python
def detect_parser(blob: bytes) -> str:
    """Sniff the first page of a PDF to pick the right parser.

    Returns:
        ``"pa_code"`` for PA Code browser-printed PDFs,
        ``"federal"`` for NEPA/CFR-style scanned reprints.
    """
    try:
        doc = pymupdf.open(stream=blob, filetype="pdf")
        first_page_text = doc[0].get_text("text") if len(doc) > 0 else ""
        doc.close()
    except Exception:
        return "federal"

    if "Pennsylvania Code" in first_page_text:
        return "pa_code"
    return "federal"
```

Add `import pymupdf` to the imports.

Then update `ingest_source_sync` to use the detected parser. Replace:

```python
        sections, parser_warnings = parse_pdf(blob)
```

With:

```python
        parser_type = detect_parser(blob)
        log("detected parser: %s", parser_type)
        if parser_type == "pa_code":
            sections, parser_warnings = parse_pa_code_pdf(blob)
        else:
            sections, parser_warnings = parse_pdf(blob)
```

Also update the "zero sections" error message to be parser-agnostic. Replace:

```python
            update_status(
                conn, source_id, status="failed",
                status_message=(
                    "Not a NEPA-style PDF (no CFR sections detected). "
                    "Only documents structured like 40 CFR 1500-1508 "
                    "can be ingested."
                ),
            )
```

With:

```python
            update_status(
                conn, source_id, status="failed",
                status_message=(
                    f"No sections detected by {parser_type} parser. "
                    "The PDF may not match any supported regulatory format."
                ),
            )
```

- [ ] **Step 4: Run all tests**

Run: `cd backend && python -m pytest tests/test_pa_code_parser.py tests/test_regulatory_ingest.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/regulatory_ingest.py backend/tests/test_pa_code_parser.py
git commit -m "feat(rag): auto-detect PA Code vs federal parser during ingestion"
```

---

### Task 11: End-to-end smoke test — full PA Code ingest pipeline

**Files:**
- Modify: `backend/tests/test_pa_code_parser.py`

- [ ] **Step 1: Write E2E test**

Append to `backend/tests/test_pa_code_parser.py`:

```python
class TestPaCodePipelineSmoke(unittest.TestCase):
    """Full parse -> chunk -> breadcrumb pipeline for the real PA Code PDF."""

    @unittest.skipUnless(PA_CODE_PDF.exists(), "PA Code PDF not present")
    def test_full_pipeline(self):
        from rag.regulatory.chunker import chunk_sections
        from rag.regulatory.breadcrumbs import build_breadcrumb

        blob = PA_CODE_PDF.read_bytes()
        sections, warnings = parse_pa_code_pdf(blob)

        chunks = chunk_sections(sections)
        self.assertGreater(len(chunks), 50, "expected at least 50 chunks")

        # Every chunk should produce a valid breadcrumb
        for chunk in chunks:
            bc = build_breadcrumb(chunk)
            self.assertIn("Title 25", bc)
            self.assertIn("Chapter 105", bc)
            self.assertTrue(len(bc) > 20, f"breadcrumb too short: {bc}")

        # Spot check: § 105.17 (Wetlands) should be present
        wetland_chunks = [
            c for c in chunks
            if any(s.section == "105.17" for s in c.sources)
        ]
        self.assertGreater(len(wetland_chunks), 0, "§ 105.17 Wetlands not found")

        # Spot check: § 105.18a (Permitting in wetlands) should be present
        permit_chunks = [
            c for c in chunks
            if any(s.section == "105.18a" for s in c.sources)
        ]
        self.assertGreater(len(permit_chunks), 0, "§ 105.18a not found")
```

- [ ] **Step 2: Run test**

Run: `cd backend && python -m pytest tests/test_pa_code_parser.py::TestPaCodePipelineSmoke -v`
Expected: PASS

- [ ] **Step 3: Run the full test suite to verify no regressions**

Run: `cd backend && python -m pytest tests/ -v --tb=short`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_pa_code_parser.py
git commit -m "test(rag): E2E smoke test for PA Code parse-chunk-breadcrumb pipeline"
```

---

### Task 12: Final commit — update __init__.py docstring

**Files:**
- Modify: `backend/rag/regulatory/__init__.py`

- [ ] **Step 1: Update module docstring**

```python
"""Regulatory document ingestion pipeline.

Parses legal PDFs into hierarchically chunked, metadata-rich records ready
for embedding and storage in pgvector. Supports multiple parser backends:

- ``parser.py`` — Federal CFR/NEPA-style scanned reprints
- ``parser_pa_code.py`` — PA Code browser-printed PDFs

The chunker, breadcrumb builder, embedder, and store layers are
document-agnostic; only the parser carries PDF-specific section detection.
"""
```

- [ ] **Step 2: Run full test suite one more time**

Run: `cd backend && python -m pytest tests/ -v --tb=short`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add backend/rag/regulatory/__init__.py
git commit -m "docs(rag): update module docstring for multi-parser support"
```

---

Plan complete and saved to `docs/superpowers/plans/2026-04-12-pa-code-parser.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
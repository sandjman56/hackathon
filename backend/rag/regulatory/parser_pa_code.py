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
from enum import Enum
from pathlib import Path
from typing import Optional

import pymupdf

from .parser import DocumentType, RawSection

logger = logging.getLogger("eia.rag.regulatory.parser_pa_code")


# --- noise patterns -------------------------------------------------------

# Browser timestamp header: "4/12/26, 11:28 AM"
_RE_TIMESTAMP = re.compile(
    r"^\s*\d{1,2}/\d{1,2}/\d{2,4},?\s+\d{1,2}:\d{2}\s*[AP]M\s*$",
    re.MULTILINE,
)

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


# --- line classification ---------------------------------------------------

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

# Reserved section: "§ 105.72. [Reserved]." or "§ 105.72. [Reserved]"
_RE_RESERVED = re.compile(
    r"^\s*§\s*\d+\.\d+[a-z]?\.?\s+\[Reserved\]\.?\s*$"
)

# Subchapter: "Subchapter B. DAMS AND RESERVOIRS"
_RE_SUBCHAPTER = re.compile(
    r"^\s*Subchapter\s+(?P<letter>[A-Z])\.?\s+(?P<title>[A-Z].+?)\s*$"
)

# Appendix header: "APPENDIX A"
_RE_APPENDIX = re.compile(r"^\s*APPENDIX\s+[A-Z]\s*$")

# Chapter title: "CHAPTER 105. DAM SAFETY AND WATERWAY MANAGEMENT"
_RE_CHAPTER_TITLE = re.compile(r"^\s*CHAPTER\s+\d+\.\s+")

# TOC entry: "105.14. Review of applications." (no § prefix)
_RE_TOC_ENTRY = re.compile(r"^\s*\d+\.\d+[a-z]?\.?\s+[A-Z]")

# TOC section number with underline (hyperlink): "105.14."
_RE_TOC_LINKED = re.compile(r"^\s*\d+\.\d+[a-z]?\.\s*$")

# Section group headers: all-caps text like "GENERAL PROVISIONS"
_RE_GROUP = re.compile(r"^(?P<title>[A-Z][A-Z,\s\-\u2014]+[A-Z])\s*$")

# Known group header values (whitelist to avoid false positives)
_KNOWN_GROUPS = {
    "GENERAL",
    "GENERAL PROVISIONS",
    "PERMIT APPLICATIONS",
    "PERMIT ISSUANCE, TRANSFER AND REVOCATION",
    "SUBMERGED LANDS OF THE COMMONWEALTH\u2014LICENSES AND ANNUAL CHARGES",
    "CONSTRUCTION REQUIREMENTS AND PROCEDURES",
    "OPERATION, MAINTENANCE AND INSPECTION",
    "INVESTIGATION AND CORRECTION OF UNSAFE CONDITIONS\u2014EMERGENCY PROCEDURES",
    "PERMITS",
    "PERMITS, LETTERS OF AMENDMENTS AND LETTERS OF AUTHORIZATIONS",
    "CLASSIFICATION AND DESIGN CRITERIA FOR APPROVAL OF CONSTRUCTION, OPERATION, MODIFICATION AND MAINTENANCE",
    "STORAGE AND DISCHARGE",
    "PROTECTION AND RESTORATION OF AQUATIC LIFE",
    "OPERATION, MAINTENANCE AND EMERGENCIES",
    "CRITERIA FOR APPROVAL OF CONSTRUCTION OR MODIFICATION",
    "CRITERIA FOR APPROVAL FOR CONSTRUCTION OR MODIFICATION",
    "MAINTENANCE",
    "CONSTRUCTION AND MAINTENANCE",
    "WETLANDS",
    "GENERAL PERMITS",
}

# Metadata block headers
_META_KEYWORDS = {
    "Authority": "authority",
    "Source": "source_history",
    "Cross References": "cross_references",
    "Notes of Decisions": "notes_of_decisions",
}


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
        normalized = " ".join(stripped.split())
        if normalized in _KNOWN_GROUPS:
            return LineClassification(LineType.GROUP, title=normalized)

    # TOC entries (section number without § prefix)
    if _RE_TOC_ENTRY.match(stripped) and not stripped.startswith("§"):
        return LineClassification(LineType.TOC_ENTRY)
    if _RE_TOC_LINKED.match(stripped):
        return LineClassification(LineType.TOC_ENTRY)

    return LineClassification(LineType.BODY)


# --- main parse function ---------------------------------------------------

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
        (sections, warnings) -- same contract as the federal ``parse_pdf``.
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
    current_meta = _PaCodeMetadata()
    in_appendix = False
    in_toc = True  # First few pages are TOC

    def _flush_section() -> None:
        """Emit the current section as a RawSection."""
        nonlocal current_section, current_meta, current_meta_type
        if current_section is None:
            return
        body = current_section["body"].strip()
        if not body:
            warnings.append(f"empty body for \u00a7 {current_section['section']}")
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
            citation=f"25 Pa. Code \u00a7 {current_section['section']}",
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
                # If inside a metadata block, accumulate there
                if current_meta_type is not None:
                    current_text = getattr(current_meta, current_meta_type) or ""
                    setattr(
                        current_meta,
                        current_meta_type,
                        (current_text + " " + stripped).strip(),
                    )
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

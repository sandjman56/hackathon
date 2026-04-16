"""PDF -> ordered list of RawEisSection records for EIS documents.

Unlike the regulatory parser, which is CFR-aware, this parser targets
FEIS chapter PDFs: numbered hierarchical headings (1, 1.1, 1.1.1, ...)
rendered at larger or bolder fonts than the body.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass
from typing import Optional

import pymupdf

logger = logging.getLogger("eia.rag.evaluation.parser")

# Matches a numbered heading that starts a block, e.g. "4.2.3 Groundwater".
# Anchored at start, requires at least one space between number and title.
HEADING_RE = re.compile(r"^(\d+(?:\.\d+){0,3})\s+(\S.*\S|\S)\s*$")

# Matches "Chapter N: Title" or "Chapter N Title"
CHAPTER_RE = re.compile(r"^Chapter\s+(\d+)\s*[:\-]?\s*(.+?)\s*$", re.IGNORECASE)

_TABLE_HINT_RE = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)


@dataclass
class RawEisSection:
    """One contiguous section pulled from an EIS PDF."""
    chapter: Optional[str]
    section_number: Optional[str]
    section_title: str
    breadcrumb: str
    body: str
    page_start: int
    page_end: int
    has_table_hint: bool = False


def classify_heading(
    text: str, *, size: float, is_bold: bool, body_size: float,
) -> Optional[tuple[str, Optional[str], str]]:
    """Classify a text block as ``(kind, number, title)`` or None.

    ``kind`` is one of ``"chapter"``, ``"section"``. Chapters match the
    ``CHAPTER_RE`` pattern regardless of font; sections require either a
    size bump (>1.15x body) or bold weight AND a numbered-heading match.
    """
    stripped = text.strip()
    if not stripped:
        return None

    m = CHAPTER_RE.match(stripped)
    if m:
        return ("chapter", m.group(1), m.group(2).strip())

    is_large = size > body_size * 1.15
    if not (is_large or is_bold):
        return None

    m = HEADING_RE.match(stripped)
    if m:
        return ("section", m.group(1), m.group(2).strip())
    return None


def _iter_blocks(doc):
    """Yield ``(page_num, text, max_size, is_bold)`` for each text block.

    ``max_size`` is the largest font size seen in the block's spans; a
    block is ``is_bold`` if the majority of its character count is in a
    bold-weight span.
    """
    for page_idx, page in enumerate(doc, start=1):
        raw = page.get_text("dict")
        for block in raw.get("blocks", []):
            if block.get("type") != 0:  # 0 = text, 1 = image
                continue
            lines = block.get("lines", [])
            spans = [sp for ln in lines for sp in ln.get("spans", [])]
            if not spans:
                continue
            text = " ".join(sp.get("text", "") for sp in spans).strip()
            if not text:
                continue
            max_size = max((sp.get("size", 0.0) for sp in spans), default=0.0)
            bold_chars = sum(
                len(sp.get("text", ""))
                for sp in spans
                if "Bold" in sp.get("font", "") or (sp.get("flags", 0) & 16)
            )
            total_chars = sum(len(sp.get("text", "")) for sp in spans)
            is_bold = total_chars > 0 and bold_chars * 2 >= total_chars
            yield (page_idx, text, max_size, is_bold)


def _modal_body_size(blocks: list[tuple[int, str, float, bool]]) -> float:
    """Return the most common font size among non-bold blocks (the body size)."""
    sizes = [round(sz, 1) for (_p, _t, sz, bold) in blocks if not bold]
    if not sizes:
        return 11.0
    return Counter(sizes).most_common(1)[0][0]


def parse_eis_pdf(blob: bytes) -> tuple[list[RawEisSection], list[str]]:
    """Parse an EIS PDF into sections. Returns (sections, warnings)."""
    warnings: list[str] = []
    try:
        doc = pymupdf.open(stream=blob, filetype="pdf")
    except Exception as exc:
        return [], [f"failed to open pdf: {exc}"]

    try:
        blocks = list(_iter_blocks(doc))
    finally:
        doc.close()

    if not blocks:
        warnings.append("no text blocks found in pdf")
        return [], warnings

    body_size = _modal_body_size(blocks)
    logger.info("body_size detected: %.1fpt across %d blocks",
                body_size, len(blocks))

    stack: list[tuple[str, Optional[str], str]] = []
    cur_chapter: Optional[str] = None
    cur_number: Optional[str] = None
    cur_title: str = ""
    cur_breadcrumb: str = ""
    cur_body: list[str] = []
    cur_page_start: int = 0
    cur_page_end: int = 0
    cur_has_table = False

    sections: list[RawEisSection] = []

    def flush():
        nonlocal cur_body, cur_has_table
        if cur_title and cur_body:
            sections.append(RawEisSection(
                chapter=cur_chapter,
                section_number=cur_number,
                section_title=cur_title,
                breadcrumb=cur_breadcrumb,
                body="\n".join(cur_body).strip(),
                page_start=cur_page_start,
                page_end=cur_page_end,
                has_table_hint=cur_has_table,
            ))
        cur_body = []
        cur_has_table = False

    for page_num, text, size, is_bold in blocks:
        classified = classify_heading(
            text, size=size, is_bold=is_bold, body_size=body_size,
        )
        if classified is not None:
            flush()
            kind, number, title = classified
            if kind == "chapter":
                stack = [(kind, number, f"Chapter {number}: {title}")]
                cur_chapter = number
                cur_number = None
                cur_title = f"Chapter {number}: {title}"
            else:
                depth = number.count(".") if number else 0
                stack = [
                    e for e in stack
                    if e[0] == "chapter"
                    or (e[1] is not None and e[1].count(".") < depth)
                ]
                stack.append((kind, number, f"{number} {title}"))
                first = number.split(".", 1)[0] if number else None
                cur_chapter = first
                cur_number = number
                cur_title = title
            cur_breadcrumb = " > ".join(label for _, _, label in stack)
            cur_page_start = page_num
            cur_page_end = page_num
        else:
            if cur_title:
                cur_body.append(text)
                cur_page_end = page_num
                if _TABLE_HINT_RE.search(text):
                    cur_has_table = True

    flush()

    if not sections:
        warnings.append("no headings detected — parser produced zero sections")

    return sections, warnings

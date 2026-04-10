"""PDF -> ordered list of RawSection records.

Walks the NEPA-40CFR1500_1508.pdf (or any structurally similar legal PDF)
and emits one :class:`RawSection` per CFR section, statute section, or
executive order section. Skips the table of contents, alphabetical index,
and footer noise.

The header detection logic is pluggable via :class:`SectionDetector` so that
later state-level documents (PennDOT CE manual, NYSDEC SEQR Handbook) can
reuse the same chunking/embedding/storage layers with a different detector.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterator, Optional

import pymupdf

from .normalize import (
    BOLD_CLOSE,
    BOLD_OPEN,
    html_to_marked_text,
    recover_chars,
    strip_bold_markers,
)

logger = logging.getLogger("eia.rag.regulatory.parser")


# --- data classes ---------------------------------------------------------

class DocumentType(str, Enum):
    CFR_REGULATION = "cfr_regulation"
    STATUTE = "statute"
    EXECUTIVE_ORDER = "executive_order"


@dataclass
class RawSection:
    """One contiguous section pulled from the PDF, before chunking."""

    document_type: DocumentType
    section: str           # e.g. "1501.3", "101", "EO11514.2"
    title: str             # e.g. "When to prepare an environmental assessment"
    body: str              # cleaned body text (no bold markers)
    citation: str          # e.g. "40 CFR §1501.3", "42 USC §4331", "EO 11514 §2"
    pages: list[int] = field(default_factory=list)
    part: Optional[str] = None          # CFR Part number (e.g. "1501")
    part_title: Optional[str] = None    # e.g. "NEPA and Agency Planning"
    parent_statute: Optional[str] = None  # "NEPA", "EQIA", "Clean Air Act"
    statute_title: Optional[str] = None   # "Title I — Congressional Declaration..."
    effective_date: Optional[str] = None  # ISO date if known


# --- mode + spans ---------------------------------------------------------

class _Mode(str, Enum):
    UNKNOWN = "unknown"
    TOC = "toc"
    CFR = "cfr"
    INDEX = "index"
    STATUTE = "statute"
    EO = "eo"


@dataclass
class _Span:
    """A page-ordered fragment: either a bold header candidate or body prose."""

    kind: str   # "bold" or "body"
    text: str
    page: int


# --- header regexes -------------------------------------------------------

# CFR Part header: "PART 1501—NEPA AND AGENCY PLANNING"
_RE_PART = re.compile(
    r"^\s*PART\s+(?P<num>\d{4})\s*[\u2014\-]\s*(?P<title>[A-Z][A-Z ,]+?)\s*$"
)

# CFR section header: "§1501.3 When to prepare an environmental assessment."
# Also accepts "Sec. 1506.9 Filing requirements." (used by 2005 appendix in
# the same PDF, where the font happens to be Arial instead of Times).
_RE_CFR_SECTION = re.compile(
    r"^\s*(?:\u00a7\s*|Sec\.\s*)(?P<part>\d{4})\.(?P<sub>\d+)\s+(?P<title>.+?)\.?\s*$"
)

# NEPA statute header: "Sec. 102 [42 USC § 4332]." or "PURPOSE\nSec. 2 [42 USC § 4321]."
_RE_NEPA_SECTION = re.compile(
    r"^\s*Sec\.\s*(?P<num>\d+)\s*\[42\s*USC\s*\u00a7\s*(?P<usc>\d+[a-z]?)\][\s.]*$"
)

# Environmental Quality Improvement Act header: "42 USC § 4372" or with trailing period
_RE_EQIA_SECTION = re.compile(
    r"^\s*42\s*USC\s*\u00a7\s*(?P<usc>\d+[a-z]?)\.?\s*$"
)

# Clean Air Act §309 nested heading: "§ 7609. Policy review"
_RE_CAA_SECTION = re.compile(
    r"^\s*\u00a7\s*(?P<usc>\d+)\.\s+(?P<title>.+?)\s*$"
)

# EO sections: "Section 1." or "Sec. 2." (number stands alone, body follows)
_RE_EO_SECTION = re.compile(
    r"^\s*(?:Section|Sec\.)\s*(?P<num>\d+)\.\s*(?P<title>.*?)\s*$"
)

# Statute "TITLE I" / "TITLE II" / "TITLE III" subdividers
_RE_TITLE_HEADING = re.compile(r"^\s*TITLE\s+(?P<roman>[IVX]+)\s*$")

# Document-boundary banners
_RE_TOC_BANNER = re.compile(r"^\s*TABLE OF CONTENTS\s*$")
_RE_INDEX_BANNER = re.compile(r"^\s*Index to Parts.*$", re.IGNORECASE)
_RE_NEPA_BANNER = re.compile(r"^\s*THE NATIONAL ENVIRONMENTAL POLICY\s*$")
_RE_EQIA_BANNER = re.compile(
    r"^\s*The Environmental Quality Improvement\s*$"
)
_RE_CAA_BANNER = re.compile(r"^\s*THE CLEAN AIR ACT\s*\u00a7\s*309.*$")
_RE_EO_BANNER = re.compile(r"^\s*Executive Order 11514.*$")

# Spurious bolds to ignore (page noise / cover art / footers)
_NOISE_PHRASES = {
    "Council on Environmental Quality",
    "Executive Office of the President",
    "REGULATIONS",
    "For Implementing The Procedural Provisions Of The",
    "NATIONAL",
    "ENVIRONMENTAL",
    "POLICY ACT",
    "Reprint",
    "40 CFR Parts 1500-1508",
    "(2005)",
    "Source:",
    "NEPAnet:",
}

# Subtitle lines that follow a TITLE heading
_TITLE_SUBTITLE_HINT = re.compile(
    r"^[A-Z][A-Za-z ,'\u2014]+$"  # Title-case-ish single line
)


# --- per-page span extraction --------------------------------------------

# Match a bold span (sentinels from normalize.html_to_marked_text)
_BOLD_SPAN_RE = re.compile(
    re.escape(BOLD_OPEN) + r"(.*?)" + re.escape(BOLD_CLOSE),
    re.DOTALL,
)


def _extract_spans(page_text: str, page_num: int) -> list[_Span]:
    """Walk a page's marked text and emit bold/body spans in document order.

    Spans are *not* merged here — title-continuation across bold wraps is
    handled in the state machine, where we have classification context to
    know whether two adjacent bolds belong to the same header.
    """
    spans: list[_Span] = []
    pos = 0
    for m in _BOLD_SPAN_RE.finditer(page_text):
        if m.start() > pos:
            body = page_text[pos:m.start()]
            if body.strip():
                spans.append(_Span("body", _collapse(body), page_num))
        bold = _collapse(m.group(1))
        if bold:
            spans.append(_Span("bold", bold, page_num))
        pos = m.end()
    if pos < len(page_text):
        tail = page_text[pos:]
        if tail.strip():
            spans.append(_Span("body", _collapse(tail), page_num))
    return spans


def _collapse(text: str) -> str:
    """Collapse whitespace runs and de-hyphenate words split across lines."""
    # De-hyphenate: "responsi-\nbilities" -> "responsibilities"
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)
    # Collapse all whitespace (including newlines) to single spaces
    text = re.sub(r"\s+", " ", text)
    return text.strip()




# --- header classification ------------------------------------------------

@dataclass
class _HeaderInfo:
    """Result of classifying a bold span."""

    kind: str  # "part" | "cfr_section" | "nepa_section" | "eqia_section"
               # | "caa_section" | "eo_section" | "title_heading"
               # | "boundary_toc" | "boundary_index" | "boundary_nepa"
               # | "boundary_eqia" | "boundary_caa" | "boundary_eo"
               # | "noise" | "unknown"
    fields: dict


def _classify_bold(text: str, mode: _Mode) -> _HeaderInfo:
    """Decide what a bold span means, given the current parser mode."""
    t = text.strip()
    if not t or t in _NOISE_PHRASES:
        return _HeaderInfo("noise", {})
    if len(t) <= 1:
        return _HeaderInfo("noise", {})  # stray glyph artifacts (e.g. page 27 'l')
    if t == "\u00a7":
        return _HeaderInfo("noise", {})  # stray section symbol from page footer
    if t.startswith(("http://", "https://")):
        return _HeaderInfo("noise", {})  # footer URLs

    if _RE_TOC_BANNER.match(t):
        return _HeaderInfo("boundary_toc", {})
    if _RE_INDEX_BANNER.match(t):
        return _HeaderInfo("boundary_index", {})
    if _RE_NEPA_BANNER.match(t):
        return _HeaderInfo("boundary_nepa", {})
    if _RE_EQIA_BANNER.match(t):
        return _HeaderInfo("boundary_eqia", {})
    if _RE_CAA_BANNER.match(t):
        return _HeaderInfo("boundary_caa", {})
    if _RE_EO_BANNER.match(t):
        return _HeaderInfo("boundary_eo", {})

    if (m := _RE_PART.match(t)):
        return _HeaderInfo(
            "part", {"num": m["num"], "title": _titlecase(m["title"])}
        )
    if (m := _RE_CFR_SECTION.match(t)):
        return _HeaderInfo(
            "cfr_section",
            {
                "part": m["part"],
                "section": f"{m['part']}.{m['sub']}",
                "title": m["title"].strip().rstrip("."),
            },
        )
    if mode == _Mode.STATUTE:
        if (m := _RE_NEPA_SECTION.match(t)):
            return _HeaderInfo(
                "nepa_section",
                {"num": m["num"], "usc": m["usc"]},
            )
        if (m := _RE_EQIA_SECTION.match(t)):
            return _HeaderInfo("eqia_section", {"usc": m["usc"]})
        if (m := _RE_CAA_SECTION.match(t)):
            return _HeaderInfo(
                "caa_section",
                {"usc": m["usc"], "title": m["title"].strip().rstrip(".")},
            )
        if _RE_TITLE_HEADING.match(t):
            return _HeaderInfo(
                "title_heading", {"roman": _RE_TITLE_HEADING.match(t)["roman"]}
            )
    if mode == _Mode.EO:
        if (m := _RE_EO_SECTION.match(t)):
            return _HeaderInfo(
                "eo_section",
                {"num": m["num"], "title": m["title"].strip().rstrip(".")},
            )

    return _HeaderInfo("unknown", {"text": t})


def _titlecase(upper: str) -> str:
    """Convert UPPERCASE part titles to Title Case for breadcrumbs."""
    minor = {"and", "of", "to", "the", "for", "in", "on", "or", "a", "an"}
    words = upper.lower().split()
    out = []
    for i, w in enumerate(words):
        if i > 0 and w in minor:
            out.append(w)
        else:
            out.append(w.capitalize())
    return " ".join(out)


# --- main parser ----------------------------------------------------------

# Hardcoded effective dates for known parent statutes
_EFFECTIVE_DATES = {
    "cfr_1978": "1978-11-29",   # 43 FR 55990
    "cfr_2005_appendix": "2005-07-18",  # 70 FR 41148
    "nepa_1969": "1970-01-01",  # Pub. L. 91-190
    "eqia_1970": "1970-04-03",
    "caa_309_1970": "1970-12-31",
    "eo_11514_1970": "1970-03-05",
}


def parse_pdf(pdf_source: "str | bytes | Path") -> tuple[list[RawSection], list[str]]:
    """Parse a NEPA-style legal PDF into ordered RawSection records.

    Args:
        pdf_source: Either a filesystem path (``str`` / ``Path``) or the
            raw PDF bytes. Bytes are passed through to PyMuPDF as a
            stream so callers don't have to write to disk.

    Returns:
        ``(sections, warnings)`` — ``sections`` is the ordered list of
        :class:`RawSection`; ``warnings`` collects character-recovery
        diagnostics and any unclassified bold headers we encountered.
    """
    if isinstance(pdf_source, (bytes, bytearray)):
        doc = pymupdf.open(stream=bytes(pdf_source), filetype="pdf")
        _source_label = f"<bytes len={len(pdf_source)}>"
    else:
        doc = pymupdf.open(str(pdf_source))
        _source_label = str(pdf_source)
    warnings: list[str] = []

    # Build the full ordered span stream across all pages
    all_spans: list[_Span] = []
    for i in range(len(doc)):
        html = doc[i].get_text("html")
        marked = html_to_marked_text(html)
        cleaned, page_warns = recover_chars(marked)
        for w in page_warns:
            warnings.append(f"page {i+1}: {w}")
        all_spans.extend(_extract_spans(cleaned, page_num=i + 1))

    # Walk spans with a state machine
    sections: list[RawSection] = []
    mode = _Mode.UNKNOWN
    current_part_title: Optional[str] = None
    current_statute_title: Optional[str] = None

    accumulating: Optional[RawSection] = None
    # When set, the next consecutive bold span(s) extend the title of the
    # most recent structural element (a CFR section, a Part header, a
    # statute TITLE heading, or a wrapped banner). Cleared when we hit a
    # body span or a bold that classifies as a new structural element.
    title_extension_target: Optional[str] = None
    part_title_buffer: Optional[str] = None
    # A preamble title (e.g. "PURPOSE" before "Sec. 2 [42 USC § 4321]") that
    # should attach to the next statute section we open.
    pending_section_title: Optional[str] = None

    def flush() -> None:
        nonlocal accumulating
        if accumulating is None:
            return
        accumulating.body = _finalize_body(accumulating.body)
        if accumulating.body or accumulating.title:
            sections.append(accumulating)
        accumulating = None

    def commit_part_title() -> None:
        nonlocal part_title_buffer, current_part_title
        if part_title_buffer is not None:
            current_part_title = _titlecase(part_title_buffer)
            part_title_buffer = None

    for span in all_spans:
        if span.kind == "body":
            # Any body text closes out a pending title continuation.
            if title_extension_target == "part":
                commit_part_title()
            title_extension_target = None
            if mode in (_Mode.UNKNOWN, _Mode.TOC, _Mode.INDEX):
                continue
            if accumulating is not None:
                accumulating.body += " " + span.text
                if span.page not in accumulating.pages:
                    accumulating.pages.append(span.page)
            continue

        # ---- Bold span ----
        info = _classify_bold(span.text, mode)
        kind = info.kind

        if kind == "noise":
            continue

        # If we're in a title-continuation window and this bold doesn't
        # itself start a new structural element, append it to whatever
        # we were extending.
        if kind == "unknown" and title_extension_target is not None:
            if title_extension_target == "section" and accumulating is not None:
                accumulating.title = (accumulating.title + " " + span.text).strip()
                if span.page not in accumulating.pages:
                    accumulating.pages.append(span.page)
                continue
            if title_extension_target == "part":
                part_title_buffer = (part_title_buffer or "") + " " + span.text
                continue
            if title_extension_target == "statute_title" and current_statute_title:
                addition = _titlecase(span.text)
                if " \u2014 " not in current_statute_title:
                    current_statute_title = (
                        current_statute_title + " \u2014 " + addition
                    )
                else:
                    current_statute_title = (
                        current_statute_title + " " + addition
                    )
                continue
            if title_extension_target == "banner":
                # Discard wrapped banner continuations — the banner served
                # only to switch modes; its remainder isn't useful content.
                continue

        # In statute mode, a short uppercase bold that doesn't classify as
        # a section is treated as a preamble title (e.g. "PURPOSE" sitting
        # above "Sec. 2 [42 USC § 4321]") to attach to the next section.
        if (
            kind == "unknown"
            and mode == _Mode.STATUTE
            and len(span.text) < 40
            and span.text.upper() == span.text
        ):
            pending_section_title = span.text.title()
            continue

        # A new structural element ends any pending continuation.
        if title_extension_target == "part":
            commit_part_title()
        title_extension_target = None

        if kind == "boundary_toc":
            mode = _Mode.TOC
            title_extension_target = "banner"
            continue
        if kind == "boundary_index":
            flush()
            mode = _Mode.INDEX
            title_extension_target = "banner"
            continue
        if kind == "boundary_nepa":
            flush()
            mode = _Mode.STATUTE
            current_statute_title = None
            title_extension_target = "banner"
            continue
        if kind == "boundary_eqia":
            flush()
            mode = _Mode.STATUTE
            current_statute_title = "Environmental Quality Improvement Act"
            title_extension_target = "banner"
            continue
        if kind == "boundary_caa":
            flush()
            mode = _Mode.STATUTE
            current_statute_title = "Clean Air Act \u00a7309"
            title_extension_target = "banner"
            continue
        if kind == "boundary_eo":
            flush()
            mode = _Mode.EO
            current_statute_title = None
            title_extension_target = "banner"
            continue

        if kind == "part":
            flush()
            mode = _Mode.CFR
            part_title_buffer = info.fields["title"]
            current_part_title = _titlecase(info.fields["title"])
            title_extension_target = "part"
            continue

        if kind == "cfr_section":
            flush()
            is_appendix = span.page >= 46
            accumulating = RawSection(
                document_type=DocumentType.CFR_REGULATION,
                section=info.fields["section"],
                title=info.fields["title"],
                body="",
                citation=f"40 CFR \u00a7{info.fields['section']}",
                pages=[span.page],
                part=info.fields["part"],
                part_title=current_part_title or _infer_part_title(info.fields["part"]),
                parent_statute="NEPA",
                effective_date=(
                    _EFFECTIVE_DATES["cfr_2005_appendix"]
                    if is_appendix
                    else _EFFECTIVE_DATES["cfr_1978"]
                ),
            )
            mode = _Mode.CFR
            title_extension_target = "section"
            continue

        if kind == "nepa_section":
            flush()
            num = info.fields["num"]
            usc = info.fields["usc"]
            title = pending_section_title or f"Sec. {num}"
            pending_section_title = None
            accumulating = RawSection(
                document_type=DocumentType.STATUTE,
                section=num,
                title=title,
                body="",
                citation=f"42 USC \u00a7{usc}",
                pages=[span.page],
                parent_statute="NEPA",
                statute_title=current_statute_title,
                effective_date=_EFFECTIVE_DATES["nepa_1969"],
            )
            continue

        if kind == "eqia_section":
            flush()
            usc = info.fields["usc"]
            accumulating = RawSection(
                document_type=DocumentType.STATUTE,
                section=usc,
                title=f"42 USC \u00a7{usc}",
                body="",
                citation=f"42 USC \u00a7{usc}",
                pages=[span.page],
                parent_statute="Environmental Quality Improvement Act",
                statute_title=current_statute_title,
                effective_date=_EFFECTIVE_DATES["eqia_1970"],
            )
            continue

        if kind == "caa_section":
            flush()
            usc = info.fields["usc"]
            accumulating = RawSection(
                document_type=DocumentType.STATUTE,
                section=usc,
                title=info.fields["title"],
                body="",
                citation=f"42 USC \u00a7{usc}",
                pages=[span.page],
                parent_statute="Clean Air Act",
                statute_title=current_statute_title,
                effective_date=_EFFECTIVE_DATES["caa_309_1970"],
            )
            continue

        if kind == "eo_section":
            flush()
            num = info.fields["num"]
            accumulating = RawSection(
                document_type=DocumentType.EXECUTIVE_ORDER,
                section=f"EO11514.{num}",
                title=info.fields["title"] or f"Section {num}",
                body="",
                citation=f"EO 11514 \u00a7{num}",
                pages=[span.page],
                parent_statute="Executive Order 11514",
                effective_date=_EFFECTIVE_DATES["eo_11514_1970"],
            )
            continue

        if kind == "title_heading":
            roman = info.fields["roman"]
            current_statute_title = f"Title {roman}"
            title_extension_target = "statute_title"
            continue

        if kind == "unknown":
            warnings.append(
                f"page {span.page}: unclassified bold span: {span.text[:80]!r}"
            )
            if accumulating is not None:
                accumulating.body += " " + span.text

    flush()
    logger.info(
        "Parsed %d sections from %s (warnings=%d)",
        len(sections),
        _source_label,
        len(warnings),
    )
    return sections, warnings


def _finalize_body(body: str) -> str:
    """Normalize body text after a section is closed."""
    body = strip_bold_markers(body)
    body = re.sub(r"\s+", " ", body).strip()
    return body


# Fallback Part titles for the rare case the appendix references a Part
# whose header isn't in scope at the time of detection.
_PART_TITLE_FALLBACK = {
    "1500": "Purpose, Policy, and Mandate",
    "1501": "NEPA and Agency Planning",
    "1502": "Environmental Impact Statement",
    "1503": "Commenting",
    "1504": "Predecision Referrals to the Council",
    "1505": "NEPA and Agency Decisionmaking",
    "1506": "Other Requirements of NEPA",
    "1507": "Agency Compliance",
    "1508": "Terminology and Index",
}


def _infer_part_title(part: str) -> Optional[str]:
    return _PART_TITLE_FALLBACK.get(part)

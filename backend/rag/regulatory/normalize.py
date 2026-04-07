"""Text recovery for the 2005 CEQ NEPA reprint.

The PDF was typeset in QuarkXPress with Type 1 fonts whose ToUnicode cmaps
are partially missing. PyMuPDF's plain ``get_text("text")`` returns U+FFFD
("replacement character") for any glyph it cannot map. The HTML extraction
mode uses a different code path that resolves glyph names via the Adobe
Glyph List, so it recovers most letters — but a handful of glyphs (the
section symbol, em-dash, and curly quotes on pages 5-34) still come through
as U+FFFD because their original glyph names are non-standard.

This module:
1. Strips HTML markup from ``get_text("html")`` output, preserving bold
   spans with sentinel control characters so the parser can detect headers.
2. Recovers the remaining U+FFFD characters by context (a section symbol
   immediately precedes a CFR section number; an em-dash follows ``PART NNNN``;
   paired replacement chars around a phrase are curly quotes).

The recovery is deterministic and produces a small list of warnings for any
U+FFFD that could not be confidently classified.
"""
from __future__ import annotations

import logging
import re
from html import unescape
from typing import Tuple

logger = logging.getLogger("eia.rag.regulatory.normalize")

# Sentinels we use to mark bold ranges from HTML so downstream regexes can
# identify headers without having to re-parse HTML. These are control chars
# that never appear in legal prose.
BOLD_OPEN = "\x01"
BOLD_CLOSE = "\x02"
REPL = "\ufffd"


_TAG_BOLD_OPEN = re.compile(r"<b\b[^>]*>", re.IGNORECASE)
_TAG_BOLD_CLOSE = re.compile(r"</b>", re.IGNORECASE)
_TAG_PARA_CLOSE = re.compile(r"</p>", re.IGNORECASE)
_TAG_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TAG_ANY = re.compile(r"<[^>]+>")
_WS_RUN = re.compile(r"[ \t]+")


def html_to_marked_text(html: str) -> str:
    """Convert PyMuPDF HTML output to plain text with bold sentinels.

    Args:
        html: Raw HTML from ``page.get_text("html")``.

    Returns:
        Plain text with ``BOLD_OPEN``/``BOLD_CLOSE`` control chars marking
        bold spans and HTML entities decoded.
    """
    text = _TAG_BOLD_OPEN.sub(BOLD_OPEN, html)
    text = _TAG_BOLD_CLOSE.sub(BOLD_CLOSE, text)
    text = _TAG_PARA_CLOSE.sub("\n", text)
    text = _TAG_BR.sub("\n", text)
    text = _TAG_ANY.sub("", text)
    text = unescape(text)
    text = _WS_RUN.sub(" ", text)
    return text


# --- character recovery ---------------------------------------------------

# §NNNN.NN — replacement char immediately followed by a 4-digit CFR section
_FFFD_SECTION_SYM = re.compile(REPL + r"(?=\d{4}\.\d)")
# §§NNNN.NN — double section symbol (used in cross-refs like "§§1501.7(b)(2)")
_FFFD_DOUBLE_SECTION = re.compile(REPL + REPL + r"(?=\d{4}\.\d)")
# PART NNNN—UPPERCASE — em-dash between Part number and Part title
_FFFD_PART_DASH = re.compile(r"(PART\s+\d{4})" + REPL + r"(?=[A-Z])")
# Sec. NN [42 USC § NNNN] — section symbol inside statute brackets
_FFFD_USC_SECTION = re.compile(r"(\[42\s*USC)\s*" + REPL + r"\s*(?=\d)")
# Sec. NN [5 USC § NNNN] etc.
_FFFD_USC_SECTION_GENERIC = re.compile(r"(\[\d+\s*USC)\s*" + REPL + r"\s*(?=\d)")
# Stand-alone "§ 7609" / "§ 309" inside statute body
_FFFD_LEADING_SYM = re.compile(r"(?<=\s)" + REPL + r"(?=\s*\d{2,5}\b)")
# Curly quote pairs: a balanced pair of replacement chars around a short phrase
_FFFD_QUOTE_PAIR = re.compile(REPL + r"([^\ufffd]{1,200}?)" + REPL)


def recover_chars(text: str) -> Tuple[str, list[str]]:
    """Restore section symbols, em-dashes, and curly quotes lost to font issues.

    Args:
        text: Marked text from :func:`html_to_marked_text`.

    Returns:
        ``(cleaned_text, warnings)`` — warnings is a list of human-readable
        messages for any U+FFFD that could not be confidently recovered.
    """
    text = _FFFD_DOUBLE_SECTION.sub("\u00a7\u00a7", text)
    text = _FFFD_SECTION_SYM.sub("\u00a7", text)
    text = _FFFD_PART_DASH.sub("\\1\u2014", text)
    text = _FFFD_USC_SECTION.sub("\\1 \u00a7 ", text)
    text = _FFFD_USC_SECTION_GENERIC.sub("\\1 \u00a7 ", text)
    text = _FFFD_LEADING_SYM.sub("\u00a7", text)

    # Curly quotes — replace paired replacement chars with straight quotes.
    # Repeated until no more pairs match (handles nested cases).
    while True:
        new = _FFFD_QUOTE_PAIR.sub(r'"\1"', text)
        if new == text:
            break
        text = new

    warnings: list[str] = []
    leftover = text.count(REPL)
    if leftover:
        # Capture small windows around each remaining U+FFFD for diagnostics.
        for m in re.finditer(REPL, text):
            start = max(0, m.start() - 20)
            end = min(len(text), m.end() + 20)
            ctx = text[start:end].replace(REPL, "?")
            warnings.append(f"unrecovered U+FFFD: ...{ctx!r}...")
    return text, warnings


def strip_bold_markers(text: str) -> str:
    """Remove ``BOLD_OPEN``/``BOLD_CLOSE`` control characters from text."""
    return text.replace(BOLD_OPEN, "").replace(BOLD_CLOSE, "")

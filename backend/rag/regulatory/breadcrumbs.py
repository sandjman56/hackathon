"""Breadcrumb header construction.

Every chunk gets a breadcrumb header prepended to its body *before* the
embedding call. The breadcrumb mirrors the legal hierarchy — Title >
Chapter > Part > Section — so that an embedding query like
"when must an agency prepare an environmental assessment" matches the
header instead of having to fish the answer out of paragraph text.

Three formats are supported:

1. **CFR regulation**
   ``Title 40 — Protection of Environment > Chapter V — Council on``
   ``Environmental Quality > Part 1501 — NEPA and Agency Planning``
   ``> §1501.3 — When to prepare an environmental assessment``

2. **Statute** (NEPA / EQIA / Clean Air Act §309)
   ``NEPA (42 USC §4321 et seq.) > Title I — Congressional Declaration``
   ``of National Environmental Policy > Sec. 102 — Action-forcing provisions``

3. **Definition** (Part 1508 entries)
   Same as CFR but appended with the literal token ``[DEFINITION]`` so
   retrievers can distinguish glossary entries from substantive provisions.
"""
from __future__ import annotations

from .chunker import Chunk
from .parser import DocumentType, RawSection

# Static parents that never change for this PDF
_CFR_TITLE_40 = "Title 40 \u2014 Protection of Environment"
_CHAPTER_V = "Chapter V \u2014 Council on Environmental Quality"
_NEPA_ROOT = "NEPA (42 USC \u00a74321 et seq.)"
_EQIA_ROOT = "Environmental Quality Improvement Act (42 USC \u00a74371 et seq.)"
_CAA_ROOT = "Clean Air Act \u00a7309 (42 USC \u00a77609)"
_EO_ROOT = "Executive Order 11514 (1970) — Protection and Enhancement of Environmental Quality"


def build_breadcrumb(chunk: Chunk) -> str:
    """Return the breadcrumb string for a chunk.

    Picks the appropriate format based on the chunk's primary source's
    ``document_type``. For sibling-merged chunks, the breadcrumb covers
    the *first* source's section identity but the citation list in the
    metadata records all merged sources.
    """
    primary = chunk.sources[0]
    if primary.document_type == DocumentType.CFR_REGULATION:
        return _cfr_breadcrumb(chunk, primary)
    if primary.document_type == DocumentType.STATUTE:
        return _statute_breadcrumb(chunk, primary)
    if primary.document_type == DocumentType.EXECUTIVE_ORDER:
        return _eo_breadcrumb(chunk, primary)
    raise ValueError(f"unknown document_type: {primary.document_type}")


def _cfr_breadcrumb(chunk: Chunk, raw: RawSection) -> str:
    part_label = f"Part {raw.part}"
    if raw.part_title:
        part_label = f"{part_label} \u2014 {raw.part_title}"

    if chunk.is_merged_siblings and len(chunk.sources) > 1:
        # e.g. "§1501.1-1501.3 — Purpose / Apply NEPA early / When to prepare..."
        first_section = chunk.sources[0].section
        last_section = chunk.sources[-1].section
        section_range = f"\u00a7{first_section}\u2013{last_section}"
        titles = " / ".join(s.title for s in chunk.sources)
        section_label = f"{section_range} \u2014 {titles}"
    else:
        section_label = f"\u00a7{raw.section} \u2014 {raw.title}"

    if chunk.is_definition:
        section_label = f"{section_label} [DEFINITION]"

    parts = [_CFR_TITLE_40, _CHAPTER_V, part_label, section_label]
    if chunk.subsection:
        parts[-1] = f"{parts[-1]} {chunk.subsection}"
    return " > ".join(parts)


def _statute_breadcrumb(chunk: Chunk, raw: RawSection) -> str:
    if raw.parent_statute == "NEPA":
        root = _NEPA_ROOT
    elif raw.parent_statute == "Environmental Quality Improvement Act":
        root = _EQIA_ROOT
    elif raw.parent_statute == "Clean Air Act":
        root = _CAA_ROOT
    else:
        root = raw.parent_statute or "Statute"

    parts = [root]
    if raw.statute_title and raw.statute_title not in root:
        parts.append(raw.statute_title)

    if chunk.is_merged_siblings and len(chunk.sources) > 1:
        first = chunk.sources[0]
        last = chunk.sources[-1]
        section_label = (
            f"{first.title}\u2013{last.title} "
            f"({first.citation} \u2013 {last.citation})"
        )
    else:
        section_label = f"{raw.title} ({raw.citation})"
    if chunk.subsection:
        section_label = f"{section_label} {chunk.subsection}"
    parts.append(section_label)
    return " > ".join(parts)


def _eo_breadcrumb(chunk: Chunk, raw: RawSection) -> str:
    section_label = f"{raw.title} ({raw.citation})"
    if chunk.subsection:
        section_label = f"{section_label} {chunk.subsection}"
    return f"{_EO_ROOT} > {section_label}"

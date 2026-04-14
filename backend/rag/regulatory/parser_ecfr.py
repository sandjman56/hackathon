"""eCFR XML → ordered list of RawSection records.

Parses the XML returned by the eCFR Versioner API. The response root is a
single <DIV5 TYPE="PART"> element (no wrapping envelope).

Public API:
  - parse_ecfr_xml(xml_bytes) -> tuple[list[RawSection], list[str]]

Depends on: xml.etree.ElementTree (stdlib), rag.regulatory.parser.RawSection
Used by: services/regulatory_ingest.py (via detect_parser dispatch)

Design spec: docs/superpowers/specs/2026-04-14-phase-1-ecfr-pipeline-design.md

Appendix tag structure (spike resolution):
  Observed in Phase 1 target parts (23 CFR 771, 33 CFR 323, 36 CFR 800):
  appendices arrive as <DIV9 TYPE="APPENDIX"> siblings of the part's
  <DIV8> sections. Ids take the form "Appendix A to Part 800". Dispatch
  lives in the main DIV8/DIV9 loop; id normalization in
  _normalize_appendix_id().

Warning-vs-log convention:
  - Append to the returned list[str] when something abnormal is observed
    that the operator should see (unrecognized structural tag, missing
    hierarchy_metadata, malformed section attribute).
  - Log at debug only for recognized-but-stripped formatting tags
    (<AMDDATE>, <EDNOTE>, <CITA>).
"""
from __future__ import annotations

import html
import json
import logging
from typing import Optional
from xml.etree import ElementTree as ET

from rag.regulatory.parser import DocumentType, RawSection

logger = logging.getLogger("eia.rag.regulatory.parser_ecfr")

# Tags treated as inline formatting; their text is preserved but tag is stripped.
_INLINE_STRIP_KEEP_TEXT = {"I", "E", "SU"}
# Tags whose entire content is discarded from body (but may be logged).
_BODY_DROP = {"FTREF", "CITA", "AMDDATE", "EDNOTE"}
# Tags captured separately (not part of <P> body).
_ANNOTATION_TAGS = {"FTNT"}


def parse_ecfr_xml(
    xml_bytes: bytes,
) -> tuple[list[RawSection], list[str]]:
    """Parse one CFR part's XML into RawSection records.

    Args:
        xml_bytes: The raw XML response body from
            GET /api/versioner/v1/full/{date}/title-{N}.xml?part={P}.

    Returns:
        (sections, warnings): ``sections`` in document order, ``warnings``
        as human-readable strings suitable for the DB parser_warnings count.

    Raises:
        ValueError: on empty input or unparseable XML.
    """
    if not xml_bytes or not xml_bytes.strip():
        raise ValueError("parse_ecfr_xml: empty xml input")

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ValueError(f"parse_ecfr_xml: malformed XML: {exc}") from exc

    if root.tag != "DIV5" or root.attrib.get("TYPE") != "PART":
        raise ValueError(
            f"parse_ecfr_xml: expected root <DIV5 TYPE='PART'>, got "
            f"<{root.tag} TYPE={root.attrib.get('TYPE')!r}>"
        )

    warnings: list[str] = []
    part_number = root.attrib.get("N", "").strip()
    part_title = _head_text(root)
    part_hierarchy = _parse_hierarchy(root, warnings)

    sections: list[RawSection] = []
    # Walk all descendants; preserve document order. Track subpart only for
    # warnings/logging (citation comes from hierarchy_metadata per-section).
    for el in _iter_content(root):
        tag = el.tag
        el_type = el.attrib.get("TYPE", "")

        if tag == "DIV8" and el_type == "SECTION":
            sections.append(
                _section_from_div8(el, part_number, part_title, warnings)
            )
        elif tag == "DIV9" and el_type == "APPENDIX":
            sections.append(
                _section_from_div9(el, part_number, part_title, warnings)
            )
        elif tag == "DIV6" and el_type == "SUBPART":
            continue  # subpart acts only as a container; recurse via _iter_content
        elif tag in {"HEAD", "AUTH", "SOURCE"}:
            continue  # part-level metadata already captured
        elif tag in _BODY_DROP:
            continue
        else:
            warnings.append(
                f"unexpected element <{tag} TYPE={el_type!r}> under DIV5; skipped"
            )
            logger.warning("unexpected element %s TYPE=%s", tag, el_type)

    if not sections:
        warnings.append(f"no sections found under DIV5 N={part_number!r}")
    return sections, warnings


# ---------------------------- helpers ----------------------------------


def _iter_content(root: ET.Element):
    """Yield SECTION/SUBPART/APPENDIX/other children, recursing into SUBPART."""
    for child in list(root):
        if child.tag == "DIV6" and child.attrib.get("TYPE") == "SUBPART":
            yield child  # subpart marker
            yield from _iter_content(child)
        else:
            yield child


def _head_text(el: ET.Element) -> str:
    head = el.find("HEAD")
    if head is None:
        return ""
    return _gather_text(head).strip()


def _parse_hierarchy(el: ET.Element, warnings: list[str]) -> Optional[dict]:
    raw = el.attrib.get("hierarchy_metadata")
    if not raw:
        warnings.append(
            f"<{el.tag} N={el.attrib.get('N')!r}>: missing hierarchy_metadata"
        )
        return None
    # Try direct parse first (section-level elements have properly escaped JSON).
    # Fall back to html.unescape for root/subpart elements which may use &quot;
    # due to double-encoding in the eCFR API response.
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    try:
        return json.loads(html.unescape(raw))
    except json.JSONDecodeError:
        warnings.append(
            f"<{el.tag} N={el.attrib.get('N')!r}>: hierarchy_metadata not valid JSON"
        )
        return None


def _section_from_div8(
    el: ET.Element, part: str, part_title: str, warnings: list[str]
) -> RawSection:
    n = el.attrib.get("N", "").strip()
    hier = _parse_hierarchy(el, warnings)
    head_text = _head_text(el)
    # Strip leading "§ {n}" if present so `title` is the heading prose.
    title = _strip_section_prefix(head_text, n)
    body = _collect_body(el)
    citation = _citation(hier, part, n, default=f"{part} CFR §{n}".strip())

    return RawSection(
        document_type=DocumentType.CFR_REGULATION,
        section=n,
        title=title,
        body=body,
        citation=citation,
        pages=[],
        part=part,
        part_title=part_title,
    )


def _normalize_appendix_id(n: str) -> str:
    """Derive a short, stable section id from a DIV9 N attribute.

    Real eCFR uses verbose ``N`` values like "Appendix A to Part 800" or
    "Appendix I". Prefer extracting the letter/roman-numeral token after
    the word "Appendix"; fall back to prefixing "App" for short letter-only
    values ("A" -> "AppA"); fall back to "App" for empty.
    """
    import re
    n = (n or "").strip()
    if not n:
        return "App"
    # "Appendix A to Part 800" -> "A"; "Appendix III" -> "III"; "Appendix A" -> "A"
    m = re.match(r"^\s*Appendix\s+([A-Z0-9IVX]+)\b", n, flags=re.IGNORECASE)
    if m:
        return f"App{m.group(1).upper()}"
    # Already a short letter/numeral like "A" or "I"
    if re.fullmatch(r"[A-Z0-9IVX]+", n):
        return f"App{n.upper()}"
    # Otherwise: prefix with "App" and strip whitespace to produce at least
    # a distinguishable-but-terse id.
    slug = re.sub(r"\s+", "_", n)
    return f"App_{slug}"


def _section_from_div9(
    el: ET.Element, part: str, part_title: str, warnings: list[str]
) -> RawSection:
    n = el.attrib.get("N", "").strip()
    hier = _parse_hierarchy(el, warnings)
    head_text = _head_text(el)
    section_id = _normalize_appendix_id(n)
    body = _collect_body(el)
    citation = _citation(hier, part, section_id, default=f"{part} CFR App. {n}".strip())

    return RawSection(
        document_type=DocumentType.CFR_REGULATION,
        section=section_id,
        title=head_text,
        body=body,
        citation=citation,
        pages=[],
        part=part,
        part_title=part_title,
    )


def _citation(
    hier: Optional[dict],
    part: str,
    section: str,
    *,
    default: str,
) -> str:
    if hier and isinstance(hier.get("citation"), str):
        return hier["citation"]
    return default


def _strip_section_prefix(head: str, n: str) -> str:
    # Heading looks like "§ 800.3  Initiation of the section 106 process."
    head = head.strip()
    markers = (f"§ {n}", f"§{n}", n)
    for m in markers:
        if head.startswith(m):
            return head[len(m):].lstrip(" .\u00a0\t").strip()
    return head


def _collect_body(section_el: ET.Element) -> str:
    parts: list[str] = []
    for p in section_el.findall("P"):
        text = _gather_text(p).strip()
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def _gather_text(el: ET.Element) -> str:
    """Depth-first text assembly, stripping known tags per convention."""
    chunks: list[str] = []
    if el.text:
        chunks.append(el.text)
    for child in el:
        if child.tag in _BODY_DROP:
            if child.tail:
                chunks.append(child.tail)
            continue
        if child.tag in _ANNOTATION_TAGS:
            # Footnote bodies — drop from inline flow (captured elsewhere later).
            if child.tail:
                chunks.append(child.tail)
            continue
        if child.tag in _INLINE_STRIP_KEEP_TEXT:
            chunks.append(_gather_text(child))
        else:
            chunks.append(_gather_text(child))
        if child.tail:
            chunks.append(child.tail)
    return "".join(chunks)

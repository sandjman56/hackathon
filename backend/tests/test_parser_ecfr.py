"""Golden-file tests for the eCFR XML parser."""
from __future__ import annotations

from pathlib import Path

import pytest

from rag.regulatory.parser import DocumentType
from rag.regulatory.parser_ecfr import parse_ecfr_xml

_FIXTURES = Path(__file__).parent / "fixtures" / "ecfr"


def _load(name: str) -> bytes:
    p = _FIXTURES / name
    if not p.exists():
        pytest.skip(f"fixture missing: {p}")
    return p.read_bytes()


def test_parse_36_cfr_800_basics():
    sections, warnings = parse_ecfr_xml(_load("title-36_part-800.xml"))
    assert len(sections) >= 10, "36 CFR 800 should have at least 10 sections"
    assert all(s.document_type == DocumentType.CFR_REGULATION for s in sections)
    assert all(s.part == "800" for s in sections)
    first = sections[0]
    assert first.section.startswith("800.")
    assert "36 CFR" in first.citation
    assert first.title
    assert first.body
    assert isinstance(warnings, list)


def test_parse_23_cfr_771_handles_footnotes():
    sections, warnings = parse_ecfr_xml(_load("title-23_part-771.xml"))
    assert len(sections) >= 5
    assert all(s.part == "771" for s in sections)
    # FTREF is stripped; FTNT body captured as a warning note or metadata
    joined_body = " ".join(s.body for s in sections)
    assert "<FTREF" not in joined_body
    assert "<SU>" not in joined_body


def test_parse_33_cfr_323_short_baseline():
    sections, warnings = parse_ecfr_xml(_load("title-33_part-323.xml"))
    assert len(sections) >= 3
    assert all(s.part == "323" for s in sections)


def test_parse_empty_xml_raises():
    with pytest.raises(ValueError, match="empty|no content"):
        parse_ecfr_xml(b"")


def test_parse_malformed_xml_raises():
    with pytest.raises(ValueError):
        parse_ecfr_xml(b"<not-closed>")


def test_parse_missing_hierarchy_metadata_falls_back():
    # Minimal valid eCFR shape with no hierarchy_metadata attribute.
    xml = (
        b'<DIV5 N="999" TYPE="PART">'
        b"<HEAD>PART 999 \xe2\x80\x94 Test Part</HEAD>"
        b'<DIV8 N="999.1" TYPE="SECTION">'
        b"<HEAD>\xc2\xa7 999.1 A section.</HEAD>"
        b"<P>Body text.</P>"
        b"</DIV8>"
        b"</DIV5>"
    )
    sections, warnings = parse_ecfr_xml(xml)
    assert len(sections) == 1
    assert sections[0].section == "999.1"
    # Citation is constructed when hierarchy_metadata is absent.
    assert "999.1" in sections[0].citation
    assert any("hierarchy_metadata" in w for w in warnings)

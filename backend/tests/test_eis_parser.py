from rag.evaluation.parser import (
    HEADING_RE,
    RawEisSection,
    classify_heading,
    parse_eis_pdf,
)


def test_heading_regex_matches_numbered():
    assert HEADING_RE.match("4.2.3 Groundwater")
    assert HEADING_RE.match("1.1 Project Overview")
    assert HEADING_RE.match("7 Effects")  # single-level


def test_heading_regex_rejects_non_headings():
    assert HEADING_RE.match("This sentence describes 4.2.3 of the proposal.") is None
    assert HEADING_RE.match("Traffic volumes have grown 34% over the last decade.") is None


def test_classify_heading_chapter():
    kind, number, title = classify_heading(
        "Chapter 4: Environmental Resources",
        size=18.0, is_bold=True, body_size=11.0,
    )
    assert kind == "chapter"
    assert number == "4"
    assert title == "Environmental Resources"


def test_classify_heading_section():
    kind, number, title = classify_heading(
        "4.2 Water Resources",
        size=14.0, is_bold=True, body_size=11.0,
    )
    assert kind == "section"
    assert number == "4.2"
    assert title == "Water Resources"


def test_classify_heading_body_text_returns_none():
    result = classify_heading(
        "Streams in the project area are classified as warm-water fisheries.",
        size=11.0, is_bold=False, body_size=11.0,
    )
    assert result is None


def test_raw_eis_section_dataclass():
    s = RawEisSection(
        chapter="4", section_number="4.2.3",
        section_title="Groundwater",
        breadcrumb="Chapter 4: Environmental Resources > 4.2 Water Resources > 4.2.3 Groundwater",
        body="Aquifer body text.",
        page_start=12, page_end=12,
    )
    assert s.chapter == "4"
    assert s.breadcrumb.endswith("Groundwater")


def test_parse_eis_pdf_builds_breadcrumbs(sample_eis_bytes):
    sections, warnings = parse_eis_pdf(sample_eis_bytes)
    assert len(sections) >= 5  # 3 chapters x at least one leaf each

    gw = next((s for s in sections if s.section_number == "4.1.2"), None)
    assert gw is not None, [s.section_number for s in sections]
    assert gw.chapter == "4"
    assert gw.section_title == "Groundwater"
    assert "Chapter 4" in gw.breadcrumb
    assert "4.1 Water Resources" in gw.breadcrumb
    assert "4.1.2 Groundwater" in gw.breadcrumb
    assert "aquifer" in gw.body.lower() or "sandstone" in gw.body.lower()


def test_parse_eis_pdf_handles_empty_document():
    import pymupdf
    doc = pymupdf.open()
    doc.new_page()
    blob = bytes(doc.write())
    doc.close()
    sections, warnings = parse_eis_pdf(blob)
    assert sections == []
    assert any(
        "no headings detected" in w.lower() or "no text blocks" in w.lower()
        for w in warnings
    )


def test_parse_eis_pdf_page_ranges_monotonic(sample_eis_bytes):
    sections, _ = parse_eis_pdf(sample_eis_bytes)
    for s in sections:
        assert s.page_start <= s.page_end
        assert s.page_start >= 1

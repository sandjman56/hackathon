"""detect_parser must dispatch on content_type, not sniff blindly."""
from __future__ import annotations

import pytest

from services.regulatory_ingest import detect_parser


def test_xml_routes_to_ecfr():
    result = detect_parser(b"<DIV5/>", content_type="application/xml")
    assert result == "ecfr_xml"


def test_pdf_with_pa_code_marker_routes_to_pa_code(tmp_path):
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Pennsylvania Code Title 25")
    blob = doc.tobytes()
    doc.close()
    result = detect_parser(blob, content_type="application/pdf")
    assert result == "pa_code"


def test_pdf_without_pa_marker_routes_to_federal():
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Title 40—Protection of Environment")
    blob = doc.tobytes()
    doc.close()
    result = detect_parser(blob, content_type="application/pdf")
    assert result == "federal"


def test_unknown_content_type_raises():
    with pytest.raises(ValueError, match="unsupported content_type"):
        detect_parser(b"garbage", content_type="text/plain")


def test_ingest_source_sync_rejects_xml_before_parser_exists(monkeypatch, db_conn):
    """Until Task 6 lands, hitting the XML branch must raise cleanly."""
    # This test will be deleted in Task 6 (superseded by test_regulatory_ingest_xml.py)
    from services.regulatory_ingest import ingest_source_sync
    # ... actual DB/row setup out of scope for this micro-test;
    # skip if the fixture needs infra that's not yet wired.
    pytest.skip("placeholder — replaced by test_regulatory_ingest_xml.py in Task 6")

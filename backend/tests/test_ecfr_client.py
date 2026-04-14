"""eCFR client: URL shape, retry loop, error paths. No network."""
from __future__ import annotations

import httpx
import pytest

from api_clients.ecfr import fetch_ecfr_xml, resolve_current_date


def _xml_response(body: bytes = b"<DIV5 N='800' TYPE='PART'/>") -> httpx.Response:
    return httpx.Response(
        status_code=200,
        content=body,
        headers={"content-type": "application/xml"},
    )


def test_fetch_ecfr_xml_builds_correct_url():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return _xml_response()

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = fetch_ecfr_xml(
            title=36, part="800", date="2024-01-01", client=client
        )
    assert result == b"<DIV5 N='800' TYPE='PART'/>"
    assert "/api/versioner/v1/full/2024-01-01/title-36.xml" in captured["url"]
    assert "part=800" in captured["url"]


def test_fetch_ecfr_xml_retries_on_500():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, content=b"boom")
        return _xml_response()

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = fetch_ecfr_xml(
            title=36, part="800", date="2024-01-01", client=client
        )
    assert result.startswith(b"<DIV5")
    assert calls["n"] == 2


def test_fetch_ecfr_xml_raises_after_exhausting_retries():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            fetch_ecfr_xml(
                title=36, part="800", date="2024-01-01", client=client
            )


def test_fetch_ecfr_xml_rejects_non_xml_content_type():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"<html>not xml</html>",
            headers={"content-type": "text/html"},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError, match="unexpected content-type"):
            fetch_ecfr_xml(
                title=36, part="800", date="2024-01-01", client=client
            )


def test_resolve_current_date_returns_latest_valid_date():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/api/versioner/v1/versions/title-36" in str(request.url)
        return httpx.Response(
            200,
            json={
                "content_versions": [
                    {"date": "2022-04-01", "amendment_date": "2022-04-01"},
                    {"date": "2024-06-15", "amendment_date": "2024-06-15"},
                    {"date": "2023-01-10", "amendment_date": "2023-01-10"},
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = resolve_current_date(title=36, client=client)
    assert result == "2024-06-15"

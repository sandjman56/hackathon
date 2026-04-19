"""eCFR Versioner API v1 HTTP client.

Fetches CFR title/part XML from ecfr.gov. Ingest-time client (not used
by agents at query time — unlike most api_clients/*.py modules).

Public API:
  - fetch_ecfr_xml(title, part, date, client, correlation_id) -> bytes
  - resolve_current_date(title, client, correlation_id) -> str

Depends on: httpx
Used by: services/ecfr_ingest.py

Design spec: docs/superpowers/specs/2026-04-14-phase-1-ecfr-pipeline-design.md
"""
from __future__ import annotations

import logging
import time

import httpx

logger = logging.getLogger("eia.api_clients.ecfr")

_ECFR_BASE_URL = "https://www.ecfr.gov/api/versioner/v1"
_MAX_RETRIES = 2
_RETRY_DELAY = 1.5  # seconds


def _tag(correlation_id: str | None) -> str:
    return f"[ECFR:{correlation_id or '-'}]"


def fetch_ecfr_xml(
    *,
    title: int,
    part: str,
    date: str,
    client: httpx.Client,
    correlation_id: str | None = None,
) -> bytes:
    """Fetch one CFR part as XML. Returns raw bytes.

    ``date`` must be an ISO YYYY-MM-DD string (callers resolve ``"current"``
    via :func:`resolve_current_date` first).

    Raises:
        httpx.HTTPStatusError: after retries exhausted
        RuntimeError: if response content-type is not XML
    """
    url = f"{_ECFR_BASE_URL}/full/{date}/title-{title}.xml"
    params = {"part": part}
    tag = _tag(correlation_id)
    logger.info("%s GET %s ?part=%s", tag, url, part)

    last_exc: Exception | None = None
    resp: httpx.Response | None = None
    for attempt in range(1, _MAX_RETRIES + 2):
        try:
            resp = client.get(url, params=params, timeout=30)
            logger.info("%s Response: HTTP %d (attempt %d)",
                        tag, resp.status_code, attempt)
            resp.raise_for_status()
            break
        except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
            last_exc = exc
            if attempt <= _MAX_RETRIES:
                logger.warning(
                    "%s Attempt %d failed (%s), retrying in %.1fs…",
                    tag, attempt, type(exc).__name__, _RETRY_DELAY,
                )
                time.sleep(_RETRY_DELAY)
            continue
    else:
        assert last_exc is not None
        raise last_exc

    assert resp is not None
    ct = resp.headers.get("content-type", "")
    if "xml" not in ct.lower():
        raise RuntimeError(
            f"unexpected content-type from eCFR: {ct!r} for title-{title} part {part}"
        )
    return resp.content


def resolve_current_date(
    *,
    title: int,
    client: httpx.Client,
    correlation_id: str | None = None,
) -> str:
    """Return the latest valid amendment date for a CFR title as ISO YYYY-MM-DD.

    Calls GET /api/versioner/v1/versions/title-{N} and picks the maximum date
    from the ``content_versions`` list. The Versioner API's ``current`` alias
    returns 404 directly on /full/, so the canonical flow is date-resolution
    then a dated fetch.

    Raises:
        httpx.HTTPStatusError: on 4xx/5xx from versions endpoint
        RuntimeError: if the response shape doesn't contain content_versions
    """
    url = f"{_ECFR_BASE_URL}/versions/title-{title}"
    tag = _tag(correlation_id)
    logger.info("%s GET %s (resolve current)", tag, url)

    resp = client.get(url, timeout=30)
    resp.raise_for_status()
    body = resp.json()
    versions = body.get("content_versions") or []
    if not versions:
        raise RuntimeError(
            f"eCFR versions endpoint for title-{title} returned no content_versions"
        )
    dates = [v.get("amendment_date") or v.get("date") for v in versions]
    dates = [d for d in dates if d]
    if not dates:
        raise RuntimeError(
            f"eCFR versions for title-{title}: no usable date fields"
        )
    return max(dates)

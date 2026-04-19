"""Orchestrator + upsert tests for the eCFR ingest service."""
from __future__ import annotations

import os
from datetime import date

import psycopg2
import pytest

from db.regulatory_sources import upsert_ecfr_source
from db.vector_store import init_db


@pytest.fixture
def real_conn():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    conn = psycopg2.connect(url)
    conn.autocommit = False
    try:
        init_db()
        yield conn
    finally:
        conn.rollback()
        conn.close()


def test_upsert_ecfr_source_inserts_new(real_conn):
    sid = upsert_ecfr_source(
        real_conn,
        cfr_title=36,
        cfr_part="800",
        effective_date=None,
        filename="title-36_part-800.xml",
        bytes_=b"<DIV5/>",
    )
    real_conn.commit()
    assert sid

    with real_conn.cursor() as cur:
        cur.execute("SELECT source_type, content_type, cfr_title FROM regulatory_sources WHERE id=%s", (sid,))
        row = cur.fetchone()
    assert row == ("ecfr", "application/xml", 36)


def test_upsert_ecfr_source_returns_same_id_on_reingest(real_conn):
    sid1 = upsert_ecfr_source(
        real_conn, cfr_title=36, cfr_part="800", effective_date=None,
        filename="a.xml", bytes_=b"<DIV5 v=1/>",
    )
    real_conn.commit()
    sid2 = upsert_ecfr_source(
        real_conn, cfr_title=36, cfr_part="800", effective_date=None,
        filename="a.xml", bytes_=b"<DIV5 v=2/>",
    )
    real_conn.commit()
    assert sid1 == sid2

    with real_conn.cursor() as cur:
        cur.execute("SELECT bytes FROM regulatory_sources WHERE id=%s", (sid1,))
        (blob,) = cur.fetchone()
    assert blob.tobytes() == b"<DIV5 v=2/>"


def test_upsert_ecfr_source_different_date_is_different_row(real_conn):
    sid1 = upsert_ecfr_source(
        real_conn, cfr_title=36, cfr_part="800", effective_date=None,
        filename="current.xml", bytes_=b"<DIV5/>",
    )
    real_conn.commit()
    sid2 = upsert_ecfr_source(
        real_conn, cfr_title=36, cfr_part="800", effective_date=date(2020, 1, 1),
        filename="snap.xml", bytes_=b"<DIV5 snap/>",
    )
    real_conn.commit()
    assert sid1 != sid2


def test_ingest_ecfr_source_writes_audit_log(real_conn, monkeypatch):
    from services import ecfr_ingest

    xml = b"<DIV5 N='800' TYPE='PART'><HEAD>Test</HEAD></DIV5>"

    def fake_fetch(*, title, part, date, client, correlation_id=None):
        return xml
    def fake_resolve(*, title, client, correlation_id=None):
        return "2025-10-01"
    def fake_ingest_sync(conn, *, source_id, embedding_provider, correlation_id=None):
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE regulatory_sources SET status='ready', chunk_count=5 WHERE id=%s",
                (source_id,),
            )
        conn.commit()

    monkeypatch.setattr(ecfr_ingest, "fetch_ecfr_xml", fake_fetch)
    monkeypatch.setattr(ecfr_ingest, "resolve_current_date", fake_resolve)
    monkeypatch.setattr(ecfr_ingest, "ingest_source_sync", fake_ingest_sync)

    class _NullEmbed:
        dim = 8
        def embed(self, t): return [0.0] * self.dim
        def embed_batch(self, ts): return [self.embed(t) for t in ts]

    sid = ecfr_ingest.ingest_ecfr_source(
        real_conn,
        title=36, part="800", date="current",
        embedding_provider=_NullEmbed(),
        correlation_id="cid999",
        trigger="cli",
    )
    assert sid

    with real_conn.cursor() as cur:
        cur.execute(
            "SELECT status, trigger, source_type, cfr_title, cfr_part "
            "FROM regulatory_ingest_log WHERE correlation_id=%s "
            "ORDER BY ts ASC",
            ("cid999",),
        )
        rows = cur.fetchall()
    assert len(rows) == 2  # one "started", one "ready"
    assert rows[0][0] == "started"
    assert rows[1][0] == "ready"
    assert all(r[1] == "cli" for r in rows)


def test_ingest_ecfr_source_audit_reflects_pipeline_failure(real_conn, monkeypatch):
    """If ingest_source_sync marks source 'failed', audit row must say 'failed' too."""
    from services import ecfr_ingest

    xml = b"<DIV5 N='800' TYPE='PART'><HEAD>Test</HEAD></DIV5>"

    def fake_fetch(*, title, part, date, client, correlation_id=None):
        return xml
    def fake_resolve(*, title, client, correlation_id=None):
        return "2025-10-01"
    def fake_ingest_sync(conn, *, source_id, embedding_provider, correlation_id=None):
        # Simulate the real pipeline's behavior: swallow exception, mark row failed.
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE regulatory_sources SET status='failed', "
                "status_message='fake parse error' WHERE id=%s",
                (source_id,),
            )
        conn.commit()

    monkeypatch.setattr(ecfr_ingest, "fetch_ecfr_xml", fake_fetch)
    monkeypatch.setattr(ecfr_ingest, "resolve_current_date", fake_resolve)
    monkeypatch.setattr(ecfr_ingest, "ingest_source_sync", fake_ingest_sync)

    class _NullEmbed:
        dim = 8
        def embed(self, t): return [0.0] * self.dim
        def embed_batch(self, ts): return [self.embed(t) for t in ts]

    sid = ecfr_ingest.ingest_ecfr_source(
        real_conn,
        title=36, part="800", date="current",
        embedding_provider=_NullEmbed(),
        correlation_id="cid-fail",
        trigger="cli",
    )
    assert sid

    with real_conn.cursor() as cur:
        cur.execute(
            "SELECT status, error_message FROM regulatory_ingest_log "
            "WHERE correlation_id=%s ORDER BY ts ASC",
            ("cid-fail",),
        )
        rows = cur.fetchall()
    assert len(rows) == 2
    assert rows[0][0] == "started"
    assert rows[1][0] == "failed"
    assert rows[1][1] == "fake parse error"

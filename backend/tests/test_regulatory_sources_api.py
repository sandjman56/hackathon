"""FastAPI endpoint tests for /api/regulations/sources.

Uses TestClient. The startup lifespan creates real providers, so we
override the embedding_provider on app.state with a stub before each
test.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parent.parent
SEED_PDF = BACKEND_DIR / "NEPA-40CFR1500_1508.pdf"


@pytest.fixture
def client(stub_embedder, monkeypatch):
    # Stub the embedding provider so lifespan doesn't need a real API key
    from llm import provider_factory
    monkeypatch.setattr(provider_factory, "get_embedding_provider",
                        lambda: stub_embedder)

    class _StubLLM:
        provider_name = "stub-llm"
        def complete(self, *a, **k): return "[]"
        def embed(self, text): return stub_embedder.embed(text)

    monkeypatch.setattr(provider_factory, "get_llm_provider",
                        lambda: _StubLLM())

    from main import app
    with TestClient(app) as c:
        yield c


def test_list_sources_empty_or_seed(client):
    r = client.get("/api/regulations/sources")
    assert r.status_code == 200
    assert "sources" in r.json()
    # bytes never appears in the listing
    for s in r.json()["sources"]:
        assert "bytes" not in s


def test_upload_pdf_returns_202(client):
    if not SEED_PDF.exists():
        pytest.skip("seed PDF not present")
    raw = SEED_PDF.read_bytes()
    r = client.post(
        "/api/regulations/sources",
        files={"file": ("seed.pdf", raw, "application/pdf")},
        data={"is_current": "false"},
    )
    assert r.status_code in (200, 202)
    body = r.json()
    assert body["filename"] == "seed.pdf" or body["sha256"] == hashlib.sha256(raw).hexdigest()


def test_upload_dedupes_by_sha(client):
    if not SEED_PDF.exists():
        pytest.skip("seed PDF not present")
    raw = SEED_PDF.read_bytes()
    r1 = client.post(
        "/api/regulations/sources",
        files={"file": ("a.pdf", raw, "application/pdf")},
    )
    r2 = client.post(
        "/api/regulations/sources",
        files={"file": ("b.pdf", raw, "application/pdf")},
    )
    assert r1.json()["id"] == r2.json()["id"]


def test_upload_rejects_non_pdf(client):
    r = client.post(
        "/api/regulations/sources",
        files={"file": ("x.txt", b"hello", "text/plain")},
    )
    assert r.status_code == 400


def test_get_single_source(client):
    if not SEED_PDF.exists():
        pytest.skip("seed PDF not present")
    raw = SEED_PDF.read_bytes()
    r = client.post(
        "/api/regulations/sources",
        files={"file": ("seed.pdf", raw, "application/pdf")},
    )
    src_id = r.json()["id"]
    r2 = client.get(f"/api/regulations/sources/{src_id}")
    assert r2.status_code == 200
    body = r2.json()
    assert "chunks_embedded" in body
    assert "chunks_total" in body
    assert "bytes" not in body


def test_delete_source(client):
    if not SEED_PDF.exists():
        pytest.skip("seed PDF not present")
    raw = SEED_PDF.read_bytes()
    src_id = client.post(
        "/api/regulations/sources",
        files={"file": ("seed.pdf", raw, "application/pdf")},
    ).json()["id"]
    r = client.delete(f"/api/regulations/sources/{src_id}")
    assert r.status_code == 200
    assert "deleted_chunks" in r.json()
    # And it's gone from the list
    listed = client.get("/api/regulations/sources").json()["sources"]
    assert all(s["id"] != src_id for s in listed)

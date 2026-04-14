"""POST /api/regulations/sources/ecfr — request validation + flow."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    import main

    # Intercept the orchestrator so the test doesn't hit eCFR or the embedder.
    captured = {}
    def fake_ingest_ecfr_source(conn, **kwargs):
        captured.update(kwargs)
        return "sid-abc"
    monkeypatch.setattr(main, "ingest_ecfr_source", fake_ingest_ecfr_source)

    class _StubEmbed:
        dim = 8
        provider_name = "stub-embed"
        def embed(self, t): return [0.0] * self.dim
        def embed_batch(self, ts): return [self.embed(t) for t in ts]
    monkeypatch.setattr(main, "get_embedding_provider", lambda: _StubEmbed())

    with TestClient(main.app) as c:
        yield c, captured


def test_post_ecfr_valid_request(client):
    c, captured = client
    resp = c.post(
        "/api/regulations/sources/ecfr",
        json={"title": 36, "part": "800"},
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["correlation_id"]
    assert body["status"] == "pending"
    # BackgroundTasks run after response in TestClient; poll assertion
    # lives in the end-to-end test, not here.


def test_post_ecfr_rejects_bad_title(client):
    c, _ = client
    resp = c.post("/api/regulations/sources/ecfr", json={"title": 99, "part": "800"})
    assert resp.status_code == 422


def test_post_ecfr_rejects_bad_date(client):
    c, _ = client
    resp = c.post(
        "/api/regulations/sources/ecfr",
        json={"title": 36, "part": "800", "date": "yesterday"},
    )
    assert resp.status_code == 422


def test_post_ecfr_accepts_current_and_iso_date(client):
    c, captured = client
    for d in ("current", "2024-06-15"):
        resp = c.post(
            "/api/regulations/sources/ecfr",
            json={"title": 36, "part": "800", "date": d},
        )
        assert resp.status_code == 202, (d, resp.text)
        assert captured["date"] == d

import time
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from tests.fixtures.eis.build_sample import build_sample_eis_bytes


@pytest.fixture
def client():
    """Build a fresh TestClient with a stub embedding provider.

    Must monkeypatch the embedding provider factory before main.py is
    imported — lifespan creates the provider eagerly.
    """
    import importlib
    import sys

    if "main" in sys.modules:
        del sys.modules["main"]

    import llm.provider_factory as pf

    class _Stub:
        provider_name = "stub"

        def embed(self, text):
            h = abs(hash(text)) % 1000
            return [(h + i) / 1000.0 for i in range(8)]

    pf_orig = pf.get_embedding_provider
    pf.get_embedding_provider = lambda: _Stub()
    try:
        main = importlib.import_module("main")
        with TestClient(main.app) as c:
            yield c
    finally:
        pf.get_embedding_provider = pf_orig


@pytest.fixture
def project_id(client):
    r = client.post("/api/projects", json={"name": "Test Project", "coordinates": "0,0", "description": ""})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _wait_ready(client, eid, timeout=15):
    for _ in range(timeout * 2):
        r = client.get(f"/api/evaluations/{eid}")
        assert r.status_code == 200
        if r.json()["status"] in ("ready", "failed"):
            return r.json()
        time.sleep(0.5)
    raise AssertionError("evaluation did not finish in time")


def test_upload_and_ingest_happy(client, project_id):
    pdf = build_sample_eis_bytes()
    r = client.post(
        "/api/evaluations",
        files={"file": ("sample.pdf", BytesIO(pdf), "application/pdf")},
        data={"project_id": project_id},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] in ("pending", "embedding", "ready")

    final = _wait_ready(client, body["id"])
    assert final["status"] == "ready", final
    assert final["chunks_total"] > 0

    chunks = client.get(f"/api/evaluations/{body['id']}/chunks").json()
    assert chunks["total"] == final["chunks_total"]
    assert len(chunks["chunks"]) > 0
    first = chunks["chunks"][0]
    assert "chunk_label" in first
    assert "breadcrumb" in first

    search = client.post(
        f"/api/evaluations/{body['id']}/search",
        json={"query": "water resources", "top_k": 3},
    ).json()
    assert len(search["results"]) > 0
    assert "similarity" in search["results"][0]


def test_reingest_endpoint(client, project_id):
    pdf = build_sample_eis_bytes()
    r = client.post("/api/evaluations",
                    files={"file": ("r.pdf", BytesIO(pdf), "application/pdf")},
                    data={"project_id": project_id})
    eid = r.json()["id"]
    _wait_ready(client, eid)

    rr = client.post(f"/api/evaluations/{eid}/reingest")
    assert rr.status_code == 202
    final = _wait_ready(client, eid)
    assert final["status"] == "ready"


def test_duplicate_upload_returns_existing(client, project_id):
    pdf = build_sample_eis_bytes()
    r1 = client.post("/api/evaluations",
                     files={"file": ("d.pdf", BytesIO(pdf), "application/pdf")},
                     data={"project_id": project_id})
    r2 = client.post("/api/evaluations",
                     files={"file": ("d.pdf", BytesIO(pdf), "application/pdf")},
                     data={"project_id": project_id})
    assert r1.json()["id"] == r2.json()["id"]


def test_delete_cascade(client, project_id):
    pdf = build_sample_eis_bytes()
    r = client.post("/api/evaluations",
                    files={"file": ("del.pdf", BytesIO(pdf), "application/pdf")},
                    data={"project_id": project_id})
    eid = r.json()["id"]
    _wait_ready(client, eid)

    d = client.delete(f"/api/evaluations/{eid}")
    assert d.status_code == 204
    c = client.get(f"/api/evaluations/{eid}")
    assert c.status_code == 404

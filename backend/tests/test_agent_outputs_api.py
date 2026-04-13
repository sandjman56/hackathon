"""API tests for /api/projects/{id}/outputs endpoints."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(stub_embedder, monkeypatch):
    import main
    monkeypatch.setattr(main, "get_embedding_provider", lambda: stub_embedder)
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def saved_project(client):
    """Create a project and return its data."""
    r = client.post("/api/projects", json={
        "name": "Test Solar Farm",
        "coordinates": "40.4406, -79.9959",
        "description": "A 5 MW solar installation",
    })
    assert r.status_code == 201
    return r.json()


AGENT_NAMES = [
    "project_parser", "environmental_data", "regulatory_screening",
    "impact_analysis", "report_synthesis",
]

SAMPLE_OUTPUTS = {
    "agent_outputs": {
        "project_parser": {"project_type": "solar farm", "scale": "5 MW"},
        "environmental_data": {"usfws_species": {"count": 0}},
        "regulatory_screening": [{"name": "CWA 404", "jurisdiction": "Federal"}],
        "impact_analysis": {"actions": ["clearing"], "cells": []},
        "report_synthesis": {"reports": [{"document_type": "EA", "sections": []}]},
    },
    "agent_costs": {
        "project_parser": {
            "model": "gemini-2.5-flash",
            "input_tokens": 120,
            "output_tokens": 450,
            "cost_usd": 0.00034,
        },
        "environmental_data": None,
        "regulatory_screening": {
            "model": "claude-haiku-4-5",
            "input_tokens": 200,
            "output_tokens": 600,
            "cost_usd": 0.00051,
        },
        "impact_analysis": {
            "model": "gemini-2.5-flash",
            "input_tokens": 500,
            "output_tokens": 1200,
            "cost_usd": 0.0012,
        },
        "report_synthesis": {
            "model": "gemini-2.5-flash",
            "input_tokens": 800,
            "output_tokens": 2000,
            "cost_usd": 0.002,
        },
    },
}


def test_save_outputs_success(client, saved_project):
    r = client.post(
        f"/api/projects/{saved_project['id']}/outputs",
        json=SAMPLE_OUTPUTS,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["saved"] is True
    assert body["project_id"] == saved_project["id"]


def test_save_outputs_project_not_found(client):
    r = client.post("/api/projects/99999/outputs", json=SAMPLE_OUTPUTS)
    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()


def test_save_outputs_overwrites(client, saved_project):
    """Second save for the same project overwrites the first."""
    pid = saved_project["id"]
    client.post(f"/api/projects/{pid}/outputs", json=SAMPLE_OUTPUTS)

    updated = {
        "agent_outputs": {
            **SAMPLE_OUTPUTS["agent_outputs"],
            "project_parser": {"project_type": "wind farm", "scale": "10 MW"},
        },
        "agent_costs": SAMPLE_OUTPUTS["agent_costs"],
    }
    r = client.post(f"/api/projects/{pid}/outputs", json=updated)
    assert r.status_code == 200

    # Load and verify overwrite
    r2 = client.get(f"/api/projects/{pid}/outputs")
    assert r2.json()["agent_outputs"]["project_parser"]["project_type"] == "wind farm"

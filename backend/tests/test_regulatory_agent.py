"""Tests for the non-stub RegulatoryScreeningAgent."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from db.regulatory_sources import init_regulatory_sources_table
from rag.regulatory.store import init_regulatory_table


class _NoCloseConn:
    """Wrapper that no-ops .close() so the fixture conn survives agent teardown."""
    def __init__(self, c):
        self._c = c

    def __getattr__(self, name):
        return getattr(self._c, name)

    def close(self):
        pass


@pytest.fixture
def initialized(db_conn, stub_embedder):
    init_regulatory_sources_table(db_conn)
    init_regulatory_table(db_conn, embedding_dim=stub_embedder.dim)
    return db_conn, stub_embedder


def _seed_chunk(conn, source_id="src-1"):
    cur = conn.cursor()
    vec = "[" + ",".join("0.1" for _ in range(8)) + "]"
    cur.execute(
        """
        INSERT INTO regulatory_chunks (embedding, content, breadcrumb, metadata)
        VALUES (%s::vector, %s, %s, %s::jsonb);
        """,
        (vec, "When to prepare an EA per 40 CFR 1501.3.",
         "40 CFR > Part 1501 > §1501.3",
         json.dumps({
             "source_id": source_id,
             "citation": "40 CFR §1501.3",
             "chunk_index": 0,
             "subsection": None,
             "is_current": True,
         })),
    )
    conn.commit()


def test_agent_returns_regs_when_corpus_present(initialized, monkeypatch):
    conn, embedder = initialized
    _seed_chunk(conn)

    fake_llm = MagicMock()
    fake_llm.provider_name = "fake"
    fake_llm.complete.return_value = json.dumps([{
        "name": "NEPA Environmental Assessment",
        "jurisdiction": "Federal",
        "description": "Triggered by 40 CFR 1501.3.",
        "citation": "40 CFR §1501.3",
    }])

    # Patch _get_connection so the agent uses our test conn
    from agents import regulatory_screening as agent_mod
    monkeypatch.setattr(agent_mod, "_get_connection", lambda: _NoCloseConn(conn))

    from agents.regulatory_screening import RegulatoryScreeningAgent
    agent = RegulatoryScreeningAgent(fake_llm, embedder)
    state = {
        "parsed_project": {"project_type": "highway widening", "scale": "5 mi"},
        "coordinates": "40.0,-79.0",
        "environmental_data": {
            "fema_flood_zones": {"in_sfha": True},
            "usfws_species": {"count": 2},
            "nwi_wetlands": {"count": 3},
            "usda_farmland": {"is_prime": False},
        },
    }
    out = agent.run(state)
    assert isinstance(out["regulations"], list)
    assert len(out["regulations"]) == 1
    assert out["regulations"][0]["citation"] == "40 CFR §1501.3"


def test_agent_empty_corpus_returns_empty(initialized, monkeypatch):
    conn, embedder = initialized
    fake_llm = MagicMock()
    fake_llm.provider_name = "fake"

    from agents import regulatory_screening as agent_mod
    monkeypatch.setattr(agent_mod, "_get_connection", lambda: _NoCloseConn(conn))

    from agents.regulatory_screening import RegulatoryScreeningAgent
    agent = RegulatoryScreeningAgent(fake_llm, embedder)
    out = agent.run({
        "parsed_project": {},
        "coordinates": "0,0",
        "environmental_data": {},
    })
    assert out["regulations"] == []
    fake_llm.complete.assert_not_called()


def test_agent_invalid_llm_json_returns_empty(initialized, monkeypatch):
    conn, embedder = initialized
    _seed_chunk(conn)

    fake_llm = MagicMock()
    fake_llm.provider_name = "fake"
    fake_llm.complete.return_value = "not valid json at all"

    from agents import regulatory_screening as agent_mod
    monkeypatch.setattr(agent_mod, "_get_connection", lambda: _NoCloseConn(conn))

    from agents.regulatory_screening import RegulatoryScreeningAgent
    agent = RegulatoryScreeningAgent(fake_llm, embedder)
    out = agent.run({
        "parsed_project": {"type": "x"},
        "coordinates": "0,0",
        "environmental_data": {},
    })
    assert out["regulations"] == []

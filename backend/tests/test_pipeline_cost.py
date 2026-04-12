"""Integration tests for pipeline cost emission logic.

Uses fake agent classes to avoid real LLM/API calls while testing
the pipeline's cost-tracking SSE events end-to-end.
"""
import json
import sys
import os
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Pre-mock heavy dependencies that pipeline.py pulls in transitively
# (llama_index is not installed in the local test environment).
for _mod in (
    "llama_index", "llama_index.vector_stores",
    "llama_index.vector_stores.postgres",
):
    sys.modules.setdefault(_mod, MagicMock())

from llm.base import LLMResult


# ── Fake agents ──────────────────────────────────────────────────────────

class _FakeProjectParser:
    def __init__(self, llm):
        self.llm = llm

    def run(self, state):
        result = self.llm.complete("test")
        state["parsed_project"] = {"project_type": "test", "scale": "1MW", "location": "here"}
        state.setdefault("_usage", {})["project_parser"] = {
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "model": result.model,
        }
        return state


class _FakeEnvData:
    def __init__(self):
        pass

    def run(self, state):
        state["environmental_data"] = {"fema_flood_zones": {"in_sfha": False}}
        return state


class _FakeRegScreening:
    def __init__(self, llm, embedding_provider):
        self.llm = llm

    def run(self, state):
        result = self.llm.complete("test")
        state["regulations"] = []
        state.setdefault("_usage", {})["regulatory_screening"] = {
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "model": result.model,
        }
        return state


class _FakeImpact:
    def __init__(self):
        pass

    def run(self, state):
        state["impact_matrix"] = []
        return state


class _FakeReport:
    def __init__(self):
        pass

    def run(self, state):
        state["report"] = ""
        return state


# ── Helpers ──────────────────────────────────────────────────────────────

FAKE_REGISTRY = [
    ("project_parser", _FakeProjectParser),
    ("environmental_data", _FakeEnvData),
    ("regulatory_screening", _FakeRegScreening),
    ("impact_analysis", _FakeImpact),
    ("report_synthesis", _FakeReport),
]


def _parse_sse(raw_events: list[str]) -> list[tuple[str, dict]]:
    """Parse SSE event strings into (event_type, data) tuples."""
    result = []
    for event_str in raw_events:
        event_type = ""
        data_str = ""
        for line in event_str.strip().split("\n"):
            if line.startswith("event: "):
                event_type = line[7:]
            elif line.startswith("data: "):
                data_str = line[6:]
        if data_str:
            try:
                result.append((event_type, json.loads(data_str)))
            except json.JSONDecodeError:
                pass
    return result


def _make_mock_llm(input_tokens=100, output_tokens=50, model="gemini-2.5-flash"):
    llm = MagicMock()
    llm.provider_name = "mock"
    llm.complete.return_value = LLMResult(
        text="test", input_tokens=input_tokens, output_tokens=output_tokens, model=model,
    )
    return llm


def _run_pipeline(models=None):
    """Run stream_eia_pipeline with FAKE_REGISTRY and return parsed SSE events."""
    mock_llm = _make_mock_llm()
    mock_embedder = MagicMock()
    mock_embedder.provider_name = "mock"

    with patch("pipeline.AGENT_REGISTRY", FAKE_REGISTRY), \
         patch("pipeline.get_llm_for_model", return_value=mock_llm):
        from pipeline import stream_eia_pipeline
        events = list(stream_eia_pipeline(
            project_name="Test",
            coordinates="40.0,-79.0",
            description="Test project",
            models=models or {},
            embedding_provider=mock_embedder,
        ))
    return _parse_sse(events)


# ── Tests ────────────────────────────────────────────────────────────────

def test_emits_one_agent_cost_per_agent():
    parsed = _run_pipeline()
    cost_events = [(t, d) for t, d in parsed if t == "agent_cost"]
    assert len(cost_events) == 5, f"Expected 5 agent_cost events, got {len(cost_events)}"


def test_llm_agents_have_nonzero_cost():
    parsed = _run_pipeline()
    cost_events = {d["agent"]: d for t, d in parsed if t == "agent_cost"}
    pp = cost_events["project_parser"]
    assert pp["input_tokens"] == 100
    assert pp["output_tokens"] == 50
    assert pp["cost_usd"] > 0


def test_non_llm_agents_have_zero_cost():
    parsed = _run_pipeline()
    cost_events = {d["agent"]: d for t, d in parsed if t == "agent_cost"}
    for agent in ("environmental_data", "impact_analysis", "report_synthesis"):
        assert cost_events[agent]["input_tokens"] == 0
        assert cost_events[agent]["output_tokens"] == 0
        assert cost_events[agent]["cost_usd"] == 0.0


def test_cost_after_complete():
    parsed = _run_pipeline()
    for agent_key in ("project_parser", "regulatory_screening"):
        complete_idx = next(
            i for i, (t, d) in enumerate(parsed)
            if t == "agent_complete" and d.get("agent") == agent_key
        )
        cost_idx = next(
            i for i, (t, d) in enumerate(parsed)
            if t == "agent_cost" and d.get("agent") == agent_key
        )
        assert cost_idx > complete_idx, \
            f"agent_cost must come after agent_complete for {agent_key}"


def test_missing_api_key_emits_pipeline_error():
    from llm.provider_factory import MissingAPIKeyError

    mock_embedder = MagicMock()
    mock_embedder.provider_name = "mock"

    def raise_missing(model_id):
        raise MissingAPIKeyError(f"KEY not set for {model_id}")

    with patch("pipeline.AGENT_REGISTRY", FAKE_REGISTRY), \
         patch("pipeline.get_llm_for_model", side_effect=raise_missing):
        from pipeline import stream_eia_pipeline
        events = list(stream_eia_pipeline(
            project_name="Test",
            coordinates="40.0,-79.0",
            description="Test",
            models={},
            embedding_provider=mock_embedder,
        ))

    parsed = _parse_sse(events)
    error_events = [(t, d) for t, d in parsed if t == "pipeline_error"]
    assert len(error_events) == 1
    assert "MissingAPIKeyError" in error_events[0][1]["type"]

    cost_events = [(t, d) for t, d in parsed if t == "agent_cost"]
    assert len(cost_events) == 0, "No agent_cost events when pre-flight fails"

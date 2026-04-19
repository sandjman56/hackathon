import json
import logging
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from typing import TypedDict

from langgraph.graph import StateGraph, START, END

from llm.base import LLMProvider
from llm.provider_factory import get_llm_for_model, MissingAPIKeyError, UnknownModelError
from llm.pricing import cost_usd
from agents.project_parser import ProjectParserAgent
from agents.environmental_data import EnvironmentalDataAgent
from agents.regulatory_screening import RegulatoryScreeningAgent
from agents.impact_analysis import ImpactAnalysisAgent
from agents.report_synthesis import ReportSynthesisAgent

logger = logging.getLogger("eia.pipeline")

# ── Cancellation ──────────────────────────────────────────────────────────────

_cancel_flag = threading.Event()


def cancel_pipeline():
    """Signal the currently-running pipeline to stop after the current agent."""
    _cancel_flag.set()


# ── SSE log buffer ────────────────────────────────────────────────────────────

class _SSELogBuffer(logging.Handler):
    """Captures eia.* log records into a thread-safe list for SSE emission."""

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self._records: list[dict] = []
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord):
        with self._lock:
            self._records.append({
                "ts": record.created,
                "level": record.levelname,
                "logger": record.name,
                "msg": self.format(record),
            })

    def flush_events(self) -> list[dict]:
        with self._lock:
            events = list(self._records)
            self._records.clear()
        return events


# ── State schema ──────────────────────────────────────────────────────────────

class ImpactDetermination(TypedDict):
    significance: str   # "significant" | "moderate" | "minimal" | "none"
    confidence: float   # 0.0 – 1.0
    reasoning: str      # why this determination was made
    mitigation: list    # applicable: "avoidance", "minimization", "compensatory"
    needs_review: bool  # True when confidence < 0.6


class ImpactCell(TypedDict):
    action: str         # project action/component (column)
    category: str       # environmental resource category (row)
    framework: str      # regulatory framework governing this evaluation
    determination: ImpactDetermination


class RAGFallback(TypedDict):
    action: str
    category: str
    query: str
    reason: str


class ImpactMatrixOutput(TypedDict):
    actions: list       # distinct project actions (column headers)
    categories: list    # distinct resource categories (row headers)
    cells: list         # list of ImpactCell dicts
    rag_fallbacks: list # list of RAGFallback dicts (empty for v1)


class Regulation(TypedDict):
    name: str
    description: str
    jurisdiction: str


class EIAPipelineState(TypedDict):
    # Input fields
    project_name: str
    coordinates: str
    description: str
    project_id: int | None  # saved project; scopes regulatory RAG to assigned sources

    # Pipeline tracking
    pipeline_status: dict  # agent_key -> "pending"|"running"|"complete"|"error"
    errors: dict

    # Agent outputs
    parsed_project: dict
    environmental_data: dict
    regulations: list[Regulation]
    impact_matrix: dict  # ImpactMatrixOutput
    report: str


# ── Agent registry ────────────────────────────────────────────────────────────

AGENT_REGISTRY = [
    ("project_parser", ProjectParserAgent),
    ("environmental_data", EnvironmentalDataAgent),
    ("regulatory_screening", RegulatoryScreeningAgent),
    ("impact_analysis", ImpactAnalysisAgent),
    ("report_synthesis", ReportSynthesisAgent),
]

AGENT_STEPS = {
    "project_parser": [
        {"name": "parse_description", "label": "Parsing project description"},
        {"name": "extract_metadata", "label": "Extracting project metadata"},
        {"name": "geocode_coordinates", "label": "Validating coordinates"},
    ],
    "environmental_data": [
        {"name": "query_usfws", "label": "Querying USFWS IPaC (endangered species)"},
        {"name": "query_nwi", "label": "Querying National Wetlands Inventory"},
        {"name": "query_fema", "label": "Querying FEMA flood hazards"},
        {"name": "query_farmland", "label": "Querying USDA farmland data"},
        {"name": "query_ejscreen", "label": "Querying EPA EJScreen"},
    ],
    "regulatory_screening": [
        {"name": "embed_query", "label": "Embedding project context"},
        {"name": "retrieve_regulations", "label": "Retrieving NEPA regulations (RAG)"},
        {"name": "screen_applicability", "label": "Screening regulatory applicability"},
    ],
    "impact_analysis": [
        {"name": "build_context", "label": "Building impact context from upstream data"},
        {"name": "evaluate_determinations", "label": "Evaluating impact determinations (LLM)"},
        {"name": "validate_matrix", "label": "Validating matrix and flagging low confidence"},
    ],
    "report_synthesis": [
        {"name": "compile_findings", "label": "Compiling findings"},
        {"name": "generate_report", "label": "Generating EIA report"},
        {"name": "format_output", "label": "Formatting final output"},
    ],
}

AGENT_LABELS = {
    "project_parser": "Project Parser",
    "environmental_data": "Environmental Data",
    "regulatory_screening": "Regulatory Screening",
    "impact_analysis": "Impact Analysis",
    "report_synthesis": "Report Synthesis",
}

AGENT_OUTPUT_KEYS = {
    "project_parser": "parsed_project",
    "environmental_data": "environmental_data",
    "regulatory_screening": "regulations",
    "impact_analysis": "impact_matrix",
    "report_synthesis": "report",
}

DEFAULT_MODELS: dict[str, str] = {
    "project_parser":       "gemini-2.5-flash",
    "environmental_data":   "gemini-2.5-flash",   # not used (non-LLM agent)
    "regulatory_screening": "claude-haiku-4-5-20251001",
    "impact_analysis":      "gemini-2.5-flash",
    "report_synthesis":     "gemini-2.5-flash",
}

NON_LLM_AGENTS = frozenset({
    "environmental_data",
})


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _make_agent_node(agent_key: str, agent_class, resolved_llms: dict, embedding_provider: LLMProvider):
    """Create a LangGraph node function wrapping an agent's .run() call."""
    if agent_key in NON_LLM_AGENTS:
        agent = agent_class()
    elif agent_key == "regulatory_screening":
        agent = agent_class(resolved_llms[agent_key], embedding_provider)
    else:
        agent = agent_class(resolved_llms[agent_key])

    def node_fn(state: EIAPipelineState) -> dict:
        logger.info("[GRAPH] Entering node: %s", agent_key)
        status = dict(state.get("pipeline_status", {}))
        status[agent_key] = "running"

        try:
            updated_state = agent.run(dict(state))
            status[agent_key] = "complete"
            logger.info("[GRAPH] Node %s → complete", agent_key)

            result = {"pipeline_status": status}
            for k, v in updated_state.items():
                if k != "pipeline_status" and (k not in state or state[k] != v):
                    result[k] = v
            return result

        except Exception as exc:
            logger.error("[GRAPH] Node %s → ERROR: %s", agent_key, exc, exc_info=True)
            status[agent_key] = "error"
            errors = dict(state.get("errors", {}))
            errors[agent_key] = str(exc)
            return {"pipeline_status": status, "errors": errors}

    return node_fn


def build_pipeline(resolved_llms: dict[str, LLMProvider], embedding_provider: LLMProvider):
    """Construct and compile the EIA LangGraph pipeline."""
    graph = StateGraph(EIAPipelineState)
    for agent_key, agent_class in AGENT_REGISTRY:
        graph.add_node(agent_key, _make_agent_node(agent_key, agent_class, resolved_llms, embedding_provider))
    prev = START
    for agent_key, _ in AGENT_REGISTRY:
        graph.add_edge(prev, agent_key)
        prev = agent_key
    graph.add_edge(prev, END)
    return graph.compile()


def run_eia_pipeline(
    project_name: str,
    coordinates: str,
    description: str,
    models: dict[str, str],
    embedding_provider: LLMProvider,
) -> dict:
    resolved_llms = {}
    for agent_key, _ in AGENT_REGISTRY:
        if agent_key not in NON_LLM_AGENTS:
            model_id = models.get(agent_key) or DEFAULT_MODELS[agent_key]
            resolved_llms[agent_key] = get_llm_for_model(model_id)
    compiled = build_pipeline(resolved_llms, embedding_provider)
    initial_state: EIAPipelineState = {
        "project_name": project_name,
        "coordinates": coordinates,
        "description": description,
        "pipeline_status": {key: "pending" for key, _ in AGENT_REGISTRY},
        "parsed_project": {},
        "environmental_data": {},
        "regulations": [],
        "impact_matrix": {},
        "report": "",
        "errors": {},
    }
    final_state = compiled.invoke(initial_state)
    return {
        "project_name": final_state["project_name"],
        "coordinates": final_state["coordinates"],
        "description": final_state["description"],
        "pipeline_status": final_state["pipeline_status"],
        "impact_matrix": final_state.get("impact_matrix", {}),
        "regulations": final_state.get("regulations", []),
    }


# ── Streaming pipeline ────────────────────────────────────────────────────────

def stream_eia_pipeline(
    project_name: str,
    coordinates: str,
    description: str,
    models: dict[str, str],
    embedding_provider: LLMProvider,
    project_id: int | None = None,
):
    """Execute the EIA pipeline as a generator yielding SSE events.

    Emits agent/step progress events interleaved with buffered log events so
    the frontend Brain Scanner can display real-time observability data.
    """
    # Print-based panic log: guaranteed stdout even if logging config is broken.
    print(
        f"[PIPELINE] stream_eia_pipeline entered — "
        f"project={project_name!r} models={models}",
        flush=True, file=sys.stderr,
    )

    _cancel_flag.clear()

    # Attach SSE log buffer to the eia logger hierarchy for this run
    log_buffer = _SSELogBuffer()
    eia_root = logging.getLogger("eia")
    eia_root.addHandler(log_buffer)

    # Pre-flight: resolve all LLM agents upfront so we fail fast
    merged_models = {k: models.get(k) or DEFAULT_MODELS[k] for k, _ in AGENT_REGISTRY}
    resolved_llms: dict[str, LLMProvider] = {}
    try:
        for agent_key, _ in AGENT_REGISTRY:
            if agent_key not in NON_LLM_AGENTS:
                resolved_llms[agent_key] = get_llm_for_model(merged_models[agent_key])
    except (MissingAPIKeyError, UnknownModelError) as exc:
        logger.error("[PIPELINE] Pre-flight validation failed: %s", exc)
        yield _sse_event("pipeline_error", {
            "msg": str(exc),
            "type": type(exc).__name__,
        })
        eia_root.removeHandler(log_buffer)
        return

    pipeline_status = {key: "pending" for key, _ in AGENT_REGISTRY}
    agent_steps = {key: [] for key, _ in AGENT_REGISTRY}
    errors = {}

    state = {
        "project_name": project_name,
        "coordinates": coordinates,
        "description": description,
        "project_id": project_id,
        "pipeline_status": pipeline_status,
        "parsed_project": {},
        "environmental_data": {},
        "regulations": [],
        "impact_matrix": {},
        "report": "",
        "errors": errors,
    }

    def _flush_logs():
        """Yield all buffered log records as SSE log events."""
        for record in log_buffer.flush_events():
            yield _sse_event("log", record)

    try:
        logger.info("[PIPELINE] Starting EIA pipeline — project: %r", project_name)
        logger.info("[PIPELINE] Coordinates: %s", coordinates)
        logger.info("[PIPELINE] Models: %s", merged_models)
        logger.info("[GRAPH] Compiled graph: %d nodes → %s",
                    len(AGENT_REGISTRY),
                    " → ".join(k for k, _ in AGENT_REGISTRY))

        yield _sse_event("pipeline_start", {
            "pipeline_status": dict(pipeline_status),
            "agent_steps": {k: list(v) for k, v in agent_steps.items()},
            "started_at": datetime.now(timezone.utc).isoformat(),
        })
        yield from _flush_logs()

        for agent_key, agent_class in AGENT_REGISTRY:

            # ── Cancellation check ────────────────────────────────────────────
            if _cancel_flag.is_set():
                logger.warning("[PIPELINE] Cancelled by user before node: %s", agent_key)
                yield from _flush_logs()
                yield _sse_event("cancelled", {
                    "msg": "Pipeline interrupted by user (/q)",
                    "stopped_before": agent_key,
                    "pipeline_status": dict(pipeline_status),
                })
                return

            if agent_key in NON_LLM_AGENTS:
                agent = agent_class()
            elif agent_key == "regulatory_screening":
                agent = agent_class(resolved_llms[agent_key], embedding_provider)
            else:
                agent = agent_class(resolved_llms[agent_key])
            steps = AGENT_STEPS.get(agent_key, [])

            # ── Agent start ───────────────────────────────────────────────────
            pipeline_status[agent_key] = "running"
            agent_steps[agent_key] = [
                {"name": s["name"], "label": s["label"], "status": "pending"}
                for s in steps
            ]

            logger.info("[GRAPH] → Activating node: %s (%s)",
                        agent_key, AGENT_LABELS[agent_key])
            logger.info("[GRAPH] State keys entering node: %s", list(state.keys()))

            yield _sse_event("agent_start", {
                "agent": agent_key,
                "pipeline_status": dict(pipeline_status),
                "steps": agent_steps[agent_key],
            })
            yield from _flush_logs()

            _agent_start = time.time()
            try:
                for i, step in enumerate(steps):
                    agent_steps[agent_key][i]["status"] = "running"
                    yield _sse_event("agent_step", {
                        "agent": agent_key,
                        "step": step["name"],
                        "label": step["label"],
                        "status": "running",
                        "steps": agent_steps[agent_key],
                    })
                    yield from _flush_logs()

                    # All real work happens on the last step
                    if i == len(steps) - 1:
                        logger.info("[GRAPH] Invoking %s.run()", agent_class.__name__)
                        state = agent.run(dict(state))
                        logger.info("[GRAPH] %s.run() returned — flushing logs",
                                    agent_class.__name__)
                        yield from _flush_logs()

                    agent_steps[agent_key][i]["status"] = "complete"
                    yield _sse_event("agent_step", {
                        "agent": agent_key,
                        "step": step["name"],
                        "label": step["label"],
                        "status": "complete",
                        "steps": agent_steps[agent_key],
                    })

                _agent_duration_ms = int((time.time() - _agent_start) * 1000)
                pipeline_status[agent_key] = "complete"
                state["pipeline_status"] = dict(pipeline_status)

                logger.info("[GRAPH] ← Node %s complete", agent_key)
                yield from _flush_logs()

                output_key = AGENT_OUTPUT_KEYS.get(agent_key)
                agent_output = state.get(output_key) if output_key else None

                yield _sse_event("agent_complete", {
                    "agent": agent_key,
                    "duration_ms": _agent_duration_ms,
                    "pipeline_status": dict(pipeline_status),
                    "steps": agent_steps[agent_key],
                    "output": agent_output,
                })

                # Emit agent_cost event
                usage = state.get("_usage", {}).get(agent_key, {})
                agent_model = merged_models[agent_key]
                agent_cost_usd = cost_usd(
                    agent_model,
                    usage.get("input_tokens", 0),
                    usage.get("output_tokens", 0),
                )
                yield _sse_event("agent_cost", {
                    "agent": agent_key,
                    "model": agent_model,
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                    "cost_usd": agent_cost_usd,
                })

            except Exception as exc:
                logger.error("[GRAPH] Node %s raised: %s", agent_key, exc, exc_info=True)
                for step_state in agent_steps[agent_key]:
                    if step_state["status"] != "complete":
                        step_state["status"] = "error"

                pipeline_status[agent_key] = "error"
                errors[agent_key] = str(exc)
                state["pipeline_status"] = dict(pipeline_status)
                state["errors"] = dict(errors)

                yield from _flush_logs()
                yield _sse_event("agent_error", {
                    "agent": agent_key,
                    "error": str(exc),
                    "pipeline_status": dict(pipeline_status),
                    "steps": agent_steps[agent_key],
                })

                # Emit zero-cost event on error
                agent_model = merged_models[agent_key]
                yield _sse_event("agent_cost", {
                    "agent": agent_key,
                    "model": agent_model,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cost_usd": 0.0,
                })

        logger.info("[PIPELINE] All nodes complete — emitting result")
        yield from _flush_logs()

        yield _sse_event("result", {
            "project_name": state["project_name"],
            "coordinates": state["coordinates"],
            "description": state["description"],
            "pipeline_status": dict(pipeline_status),
            "impact_matrix": state.get("impact_matrix", {}),
            "regulations": state.get("regulations", []),
            "report": state.get("report", {}),
            "errors": errors if errors else None,
        })

    except Exception as exc:
        # Catch anything the per-agent handlers missed (e.g. setup failures,
        # import errors, unexpected exceptions in the orchestration layer).
        print(
            f"[PIPELINE] UNHANDLED EXCEPTION: {type(exc).__name__}: {exc}",
            flush=True, file=sys.stderr,
        )
        traceback.print_exc(file=sys.stderr)
        logger.error("[PIPELINE] Unhandled exception in generator: %s", exc, exc_info=True)
        yield _sse_event("pipeline_error", {
            "msg": str(exc),
            "type": type(exc).__name__,
            "pipeline_status": dict(pipeline_status),
        })

    finally:
        eia_root.removeHandler(log_buffer)
        print("[PIPELINE] stream_eia_pipeline exiting", flush=True, file=sys.stderr)

import json
import logging
import re
import time
import uuid

from db.vector_store import _get_connection
from llm.base import LLMProvider
from rag.regulatory.store import search_regulations

logger = logging.getLogger("eia.agents.regulatory_screening")

_TOP_K = 8

_SYSTEM = """\
You are a NEPA regulatory compliance assistant. Your job is to identify \
specific permits, approvals, and consultations that a project must obtain \
based on its characteristics and the regulatory excerpts provided.

You MUST respond with ONLY a valid JSON array. No markdown, no explanation, \
no code fences — just the raw JSON array.

Each item in the array must have exactly these four fields:
{
  "name": "<permit or approval name, e.g. 'Clean Water Act Section 404 Permit', 'ESA Section 7 Consultation'>",
  "jurisdiction": "<'Federal', 'State', or 'Local'>",
  "description": "<1-2 sentences: why this specific project triggers this requirement>",
  "citation": "<formal citation, e.g. '33 CFR §328.3', '50 CFR §402'>"
}

Rules:
- List PERMITS and APPROVALS the project must obtain, not NEPA process steps.
- Do NOT list "Environmental Assessment", "Finding of No Significant Impact", \
"Record of Decision", "Major Federal Action", or "Limitations on Actions During \
NEPA Process" as separate regulations — these are steps within NEPA review, not \
independent permits.
- You MAY list "NEPA Environmental Impact Statement" or "NEPA Environmental \
Assessment" as a single entry if the project triggers NEPA review, but only once.
- Do NOT copy breadcrumb paths, chunk headers, or [DEFINITION] tags into any field.
- Do NOT invent citations. Only cite regulations referenced in the provided excerpts.\
"""


class RegulatoryScreeningAgent:
    """Real RAG: embed project context, cosine-search regulatory_chunks,
    ask the LLM to pick applicable regulations from the retrieved snippets."""

    def __init__(self, llm: LLMProvider, embedding_provider: LLMProvider):
        self.llm = llm
        self.embedding_provider = embedding_provider

    def run(self, state: dict) -> dict:
        cid = uuid.uuid4().hex[:8]
        log = lambda m, *a: logger.info(f"[regulatory:{cid}] " + m, *a)
        warn = lambda m, *a: logger.warning(f"[regulatory:{cid}] " + m, *a)

        log("starting")
        query_text = self._build_query_text(state)
        log("query_text built: %d chars", len(query_text))

        t0 = time.time()
        query_vec = self.embedding_provider.embed(query_text)
        log("embedded query in %.2fs dim=%d",
            time.time() - t0, len(query_vec))

        conn = _get_connection()
        try:
            hits = search_regulations(
                conn, query_vec, top_k=_TOP_K,
                filters={"is_current": True},
            )
        finally:
            try:
                conn.close()
            except Exception:
                pass
        log("retrieved %d chunks", len(hits))

        if not hits:
            warn("empty corpus or zero hits — returning []")
            state["regulations"] = []
            return state

        sims = [h.get("similarity", 0.0) for h in hits]
        log("similarity range %.2f-%.2f", min(sims), max(sims))

        prompt = self._build_prompt(state, hits)
        log("LLM call begin")
        t0 = time.time()
        raw = self.llm.complete(prompt, system=_SYSTEM)
        log("LLM returned in %.2fs (%d chars)", time.time() - t0, len(raw or ""))

        regs = self._parse_llm_json(raw)
        log("parsed %d regulations", len(regs))
        state["regulations"] = regs
        return state

    # --- helpers --------------------------------------------------------

    def _build_query_text(self, state: dict) -> str:
        parsed = state.get("parsed_project") or {}
        env = state.get("environmental_data") or {}
        fema = env.get("fema_flood_zones") or {}
        species = env.get("usfws_species") or {}
        wetlands = env.get("nwi_wetlands") or {}
        farmland = env.get("usda_farmland") or {}

        parts = [
            f"Project type: {parsed.get('project_type', 'unknown')}",
            f"Scale: {parsed.get('scale', 'unknown')}",
            f"Coordinates: {state.get('coordinates', 'unknown')}",
            f"In SFHA: {fema.get('in_sfha', False)}",
            f"T&E species count: {species.get('count', 0)}",
            f"Wetland features: {wetlands.get('count', 0)}",
            f"Prime farmland: {farmland.get('is_prime', False)}",
        ]
        return " | ".join(parts)

    def _build_prompt(self, state: dict, hits: list[dict]) -> str:
        parsed = state.get("parsed_project") or {}
        env = state.get("environmental_data") or {}
        excerpt_lines = []
        for i, h in enumerate(hits, 1):
            meta = h.get("metadata") or {}
            excerpt_lines.append(
                f"[{i}] (cite: {meta.get('citation', '?')}, "
                f"sim: {h.get('similarity', 0):.2f})\n"
                f"    {h.get('content', '').strip()}"
            )
        excerpts = "\n\n".join(excerpt_lines)
        return f"""\
Project:
  type: {parsed.get('project_type', 'unknown')}
  scale: {parsed.get('scale', 'unknown')}
  coordinates: {state.get('coordinates', 'unknown')}
  flags: in_sfha={env.get('fema_flood_zones', {}).get('in_sfha', False)}, \
species_count={env.get('usfws_species', {}).get('count', 0)}, \
wetlands={env.get('nwi_wetlands', {}).get('count', 0)}, \
prime_farmland={env.get('usda_farmland', {}).get('is_prime', False)}

Regulatory excerpts (top {len(hits)} by relevance):
{excerpts}

Identify the permits, approvals, and consultations this project requires. Return JSON only."""

    def _parse_llm_json(self, raw: str) -> list[dict]:
        if not raw:
            return []
        # Try to find a JSON array in the output (LLMs sometimes wrap in prose).
        m = re.search(r"\[[\s\S]*\]", raw)
        candidate = m.group(0) if m else raw
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            logger.debug("LLM returned unparseable JSON: %r", raw[:500])
            return []
        if not isinstance(data, list):
            return []
        out = []
        for item in data:
            if not isinstance(item, dict):
                continue
            out.append({
                "name": str(item.get("name", "")),
                "jurisdiction": str(item.get("jurisdiction", "")),
                "description": str(item.get("description", "")),
                "citation": str(item.get("citation", "")),
            })
        return out

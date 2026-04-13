import json
import logging
import re

from llm.base import LLMProvider

logger = logging.getLogger("eia.agents.impact_analysis")

CONFIDENCE_REVIEW_THRESHOLD = 0.6

SIGNIFICANCE_LEVELS = ("significant", "moderate", "minimal", "none")

MITIGATION_CATEGORIES = ("avoidance", "minimization", "compensatory")

_SYSTEM = """\
You are an environmental impact analysis specialist. Your job is to evaluate \
how specific project actions affect environmental resource categories under \
applicable regulatory frameworks.

You MUST respond with ONLY a valid JSON object. No markdown, no explanation, \
no code fences — just the raw JSON.

The JSON object must have this structure:
{
  "cells": [
    {
      "action": "<project action>",
      "category": "<environmental resource category>",
      "framework": "<regulatory framework name>",
      "determination": {
        "significance": "<significant | moderate | minimal | none>",
        "confidence": <0.0 to 1.0>,
        "reasoning": "<1-2 sentences: what data supports this determination>",
        "mitigation": ["<avoidance | minimization | compensatory>"]
      }
    }
  ]
}

Significance scale:
- "significant": Direct, substantial, or irreversible impact that triggers \
major regulatory review or mitigation requirements.
- "moderate": Measurable impact that requires standard mitigation or minor \
permits but is manageable.
- "minimal": Detectable but minor impact requiring only routine best practices.
- "none": No meaningful impact from this action on this resource.

Confidence scoring rules:
- 0.85–1.0: Environmental data API returned specific quantified data AND the \
regulation description includes explicit thresholds.
- 0.65–0.84: Data available from APIs but regulatory threshold is a judgment \
call (no explicit numeric threshold in the regulation description).
- 0.45–0.64: Only partial data (some APIs errored or returned empty) or the \
regulation is tangentially related.
- 0.25–0.44: No direct data; determination relies on general domain knowledge \
about this project type.
- 0.0–0.24: Pure extrapolation; no supporting data or regulatory context.

Mitigation — include ONLY categories that genuinely apply:
- "avoidance": The impact could be avoided by project design changes.
- "minimization": The impact can be reduced through construction practices or \
operational controls.
- "compensatory": The impact must be offset (e.g., wetland mitigation banking, \
habitat conservation easements).

Rules:
- Evaluate EVERY combination of action × category × applicable framework.
- Skip combinations where a framework clearly does not govern a category \
(e.g., Clean Water Act does not govern air quality).
- If environmental data for a category is missing or errored, you may still \
evaluate but set confidence ≤ 0.4 and note the data gap in reasoning.
- Do NOT invent environmental data. Only reference data provided in the input.\
"""


class ImpactAnalysisAgent:
    """Cross-references project actions against environmental resources using
    regulatory framework criteria to produce a 2D impact matrix with per-cell
    determinations, confidence scores, and mitigation flags."""

    def __init__(self, llm: LLMProvider):
        self.llm = llm

    def run(self, state: dict) -> dict:
        logger.info("[ImpactAnalysis] Starting — provider: %s",
                    self.llm.provider_name)

        parsed = state.get("parsed_project") or {}
        env = state.get("environmental_data") or {}
        regs = state.get("regulations") or []

        actions = parsed.get("actions") or []
        if not actions:
            actions = self._infer_actions(parsed)
            logger.info("[ImpactAnalysis] No actions from parser; inferred: %s",
                        actions)

        categories = self._identify_categories(env)
        logger.info("[ImpactAnalysis] Actions (%d): %s", len(actions), actions)
        logger.info("[ImpactAnalysis] Categories (%d): %s",
                    len(categories), categories)
        logger.info("[ImpactAnalysis] Regulations (%d): %s",
                    len(regs), [r.get("name") for r in regs])

        prompt = self._build_prompt(parsed, env, regs, actions, categories)
        logger.info("[ImpactAnalysis] Prompt built: %d chars", len(prompt))

        llm_result = self.llm.complete(prompt, system=_SYSTEM)
        raw = llm_result.text
        logger.info("[ImpactAnalysis] LLM returned %d chars in model=%s "
                    "(input=%d output=%d)",
                    len(raw or ""), llm_result.model,
                    llm_result.input_tokens, llm_result.output_tokens)

        cells = self._parse_cells(raw)
        cells = self._flag_reviews(cells)

        logger.info("[ImpactAnalysis] Parsed %d cells", len(cells))
        review_count = sum(
            1 for c in cells
            if c.get("determination", {}).get("needs_review")
        )
        if review_count:
            logger.warning("[ImpactAnalysis] %d cells flagged for human review "
                           "(confidence < %.1f)",
                           review_count, CONFIDENCE_REVIEW_THRESHOLD)

        state.setdefault("_usage", {})["impact_analysis"] = {
            "input_tokens": llm_result.input_tokens,
            "output_tokens": llm_result.output_tokens,
            "model": llm_result.model,
        }

        state["impact_matrix"] = {
            "actions": actions,
            "categories": categories,
            "cells": cells,
            "rag_fallbacks": [],
        }

        logger.info("[ImpactAnalysis] Node complete — %d actions × %d categories "
                    "= %d cells", len(actions), len(categories), len(cells))
        return state

    # ── Helpers ────────────────────────────────────────────────────────────

    def _infer_actions(self, parsed: dict) -> list[str]:
        """Fallback: derive generic actions from project type if parser
        didn't extract them."""
        project_type = parsed.get("project_type", "unknown")
        return [
            f"{project_type} — site preparation",
            f"{project_type} — construction",
            f"{project_type} — operation",
        ]

    def _identify_categories(self, env: dict) -> list[str]:
        """Build the list of environmental resource categories based on
        which data sources have data."""
        categories = []
        if env.get("usfws_species"):
            categories.append("endangered_species")
        if env.get("nwi_wetlands"):
            categories.append("wetlands")
        if env.get("fema_flood_zones"):
            categories.append("floodplain")
        if env.get("usda_farmland"):
            categories.append("prime_farmland")
        if env.get("ejscreen"):
            categories.append("environmental_justice")
        # Always include these — LLM can reason about them from project type
        categories.extend(["air_quality", "noise", "traffic"])
        return categories

    def _build_prompt(self, parsed: dict, env: dict, regs: list,
                      actions: list, categories: list) -> str:
        env_summary = self._summarize_env(env)
        regs_text = self._format_regulations(regs)

        return f"""\
PROJECT:
  type: {parsed.get('project_type', 'unknown')}
  scale: {parsed.get('scale', 'unknown')}
  location: {parsed.get('location', 'unknown')}

PROJECT ACTIONS (evaluate each as a column):
{chr(10).join(f"  - {a}" for a in actions)}

ENVIRONMENTAL DATA (from federal APIs):
{env_summary}

APPLICABLE REGULATIONS (from regulatory screening):
{regs_text}

ENVIRONMENTAL CATEGORIES TO EVALUATE (rows):
{chr(10).join(f"  - {c}" for c in categories)}

For each (action × category × applicable framework) combination, produce a \
determination with significance, confidence, reasoning, and mitigation. \
Return JSON only."""

    def _summarize_env(self, env: dict) -> str:
        parts = []

        species = env.get("usfws_species", {})
        if species:
            names = [s.get("name", "?") for s in species.get("species", [])]
            parts.append(
                f"  Endangered species: {species.get('count', 0)} listed — "
                f"{', '.join(names[:5])}"
            )

        wetlands = env.get("nwi_wetlands", {})
        if wetlands:
            types = [w.get("type", "?") for w in wetlands.get("wetlands", [])]
            parts.append(
                f"  Wetlands: {wetlands.get('count', 0)} features — "
                f"{', '.join(types[:5])}"
            )

        fema = env.get("fema_flood_zones", {})
        if fema:
            zones = [z.get("flood_zone", "?")
                     for z in fema.get("flood_zones", [])]
            parts.append(
                f"  Flood zones: in_sfha={fema.get('in_sfha', False)} — "
                f"zones: {', '.join(zones) or 'none'}"
            )

        farmland = env.get("usda_farmland", {})
        if farmland:
            parts.append(
                f"  Farmland: class={farmland.get('farmland_class', '?')} "
                f"is_prime={farmland.get('is_prime', False)}"
            )

        ej = env.get("ejscreen", {})
        if ej:
            parts.append(
                f"  EJ Screen: minority_pct={ej.get('minority_pct', '?')} "
                f"low_income_pct={ej.get('low_income_pct', '?')} "
                f"pm25_pct={ej.get('percentile_pm25', '?')}"
            )

        errors = env.get("errors", {})
        if errors:
            parts.append(
                f"  DATA GAPS: {', '.join(errors.keys())} APIs returned errors"
            )

        return "\n".join(parts) if parts else "  No environmental data available"

    def _format_regulations(self, regs: list) -> str:
        if not regs:
            return "  No regulations identified by screening agent"
        lines = []
        for i, r in enumerate(regs, 1):
            lines.append(
                f"  [{i}] {r.get('name', '?')} ({r.get('jurisdiction', '?')})\n"
                f"      Citation: {r.get('citation', '?')}\n"
                f"      Why triggered: {r.get('description', '?')}"
            )
        return "\n".join(lines)

    def _parse_cells(self, raw: str) -> list[dict]:
        """Extract cells array from LLM JSON response."""
        if not raw:
            logger.warning("[ImpactAnalysis] Empty LLM response")
            return []

        # Strip markdown fences if present
        clean = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()

        # Try parsing as object with "cells" key first
        try:
            data = json.loads(clean)
        except json.JSONDecodeError:
            # Try to find JSON object in the output
            m = re.search(r"\{[\s\S]*\}", clean)
            if not m:
                logger.warning("[ImpactAnalysis] No JSON object found in response")
                return []
            try:
                data = json.loads(m.group(0))
            except json.JSONDecodeError:
                logger.warning("[ImpactAnalysis] Failed to parse extracted JSON")
                return []

        if isinstance(data, dict):
            cells_raw = data.get("cells", [])
        elif isinstance(data, list):
            cells_raw = data
        else:
            return []

        cells = []
        for item in cells_raw:
            if not isinstance(item, dict):
                continue
            det = item.get("determination") or {}
            sig = str(det.get("significance", "none")).lower()
            if sig not in SIGNIFICANCE_LEVELS:
                sig = "none"
            conf = det.get("confidence", 0.5)
            if not isinstance(conf, (int, float)):
                conf = 0.5
            conf = max(0.0, min(1.0, float(conf)))
            raw_mit = det.get("mitigation") or []
            if not isinstance(raw_mit, list):
                raw_mit = []
            mitigation = [
                str(m) for m in raw_mit
                if str(m).lower() in MITIGATION_CATEGORIES
            ]
            cells.append({
                "action": str(item.get("action", "")),
                "category": str(item.get("category", "")),
                "framework": str(item.get("framework", "")),
                "determination": {
                    "significance": sig,
                    "confidence": round(conf, 2),
                    "reasoning": str(det.get("reasoning", "")),
                    "mitigation": mitigation,
                    "needs_review": False,  # set in _flag_reviews
                },
            })
        return cells

    def _flag_reviews(self, cells: list[dict]) -> list[dict]:
        """Mark cells with confidence below threshold for human review."""
        for cell in cells:
            det = cell.get("determination", {})
            if det.get("confidence", 0) < CONFIDENCE_REVIEW_THRESHOLD:
                det["needs_review"] = True
        return cells

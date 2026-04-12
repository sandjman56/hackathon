import json
import logging
import re

from llm.base import LLMProvider

logger = logging.getLogger("eia.agents.project_parser")

_SYSTEM = (
    "You are an environmental impact assessment assistant. "
    "Extract structured project metadata from the user's input and return ONLY a JSON object. "
    "No markdown, no explanation — just the raw JSON."
)

_PROMPT_TEMPLATE = """\
Project name: {project_name}
Coordinates: {coordinates}
Description: {description}

Extract the following fields and return them as a JSON object:
- project_type  (string): the category of project, e.g. "solar farm", "highway expansion", "warehouse", "pipeline", etc.
- scale         (string): size or scope, e.g. "5 MW", "12 miles", "200,000 sq ft", "unknown"
- location      (string): human-readable place name inferred from the description or coordinates

Return exactly this structure:
{{"project_type": "...", "scale": "...", "location": "..."}}
"""


class ProjectParserAgent:
    """Extracts structured project metadata from a natural language description."""

    def __init__(self, llm: LLMProvider):
        self.llm = llm

    def run(self, state: dict) -> dict:
        project_name = state.get("project_name", "")
        coordinates = state.get("coordinates", "")
        description = state.get("description", "")

        logger.info("[ProjectParser] Starting — provider: %s", self.llm.provider_name)
        logger.info("[ProjectParser] project_name=%r  coordinates=%r  desc_len=%d",
                    project_name, coordinates, len(description))

        prompt = _PROMPT_TEMPLATE.format(
            project_name=project_name,
            coordinates=coordinates,
            description=description,
        )

        llm_result = None
        try:
            llm_result = self.llm.complete(prompt, system=_SYSTEM)
            raw = llm_result.text
            logger.info("[ProjectParser] LLM response: %s", raw[:300])

            # Strip markdown code fences if present
            clean = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
            parsed = json.loads(clean)

            # Normalise to expected keys with safe defaults
            result = {
                "project_type": str(parsed.get("project_type", "unknown")),
                "scale":        str(parsed.get("scale", "unknown")),
                "location":     str(parsed.get("location", coordinates or "unknown")),
            }
            logger.info("[ProjectParser] Parsed: %s", result)

        except (json.JSONDecodeError, Exception) as exc:
            logger.warning("[ProjectParser] Extraction failed (%s), using fallback", exc)
            result = {
                "project_type": "unknown",
                "scale": "unknown",
                "location": coordinates or "unknown",
            }

        if llm_result:
            state.setdefault("_usage", {})["project_parser"] = {
                "input_tokens": llm_result.input_tokens,
                "output_tokens": llm_result.output_tokens,
                "model": llm_result.model,
            }

        state["parsed_project"] = result
        logger.info("[ProjectParser] Complete")
        return state

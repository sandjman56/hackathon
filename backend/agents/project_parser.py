import logging

from llm.base import LLMProvider

logger = logging.getLogger("eia.agents.project_parser")


class ProjectParserAgent:
    """Extracts structured project metadata (name, type, location, coordinates)
    from a natural language project description using the configured LLM."""

    def __init__(self, llm: LLMProvider):
        self.llm = llm

    def run(self, state: dict) -> dict:
        desc = state.get("description", "")
        logger.info("[ProjectParser] Starting — LLM provider: %s", self.llm.provider_name)
        logger.info("[ProjectParser] Inputs: project_name=%r  coordinates=%r",
                    state.get("project_name"), state.get("coordinates"))
        logger.info("[ProjectParser] Description: %d chars received", len(desc))
        logger.info("[ProjectParser] Task: extract project_type, scale, location, "
                    "permits_required via structured LLM call")
        logger.info("[ProjectParser] Invoking %s for structured extraction...",
                    self.llm.provider_name)
        logger.warning("[ProjectParser] STUB — LLM structured extraction not yet "
                       "implemented; returning empty parsed_project")
        logger.info("[ProjectParser] parsed_project set to {} (placeholder)")
        state["parsed_project"] = {}
        logger.info("[ProjectParser] Node complete")
        return state

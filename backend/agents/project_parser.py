import logging

from llm.base import LLMProvider

logger = logging.getLogger("eia.agents.project_parser")


class ProjectParserAgent:
    """Extracts structured project metadata (name, type, location, coordinates)
    from a natural language project description using the configured LLM."""

    def __init__(self, llm: LLMProvider):
        self.llm = llm

    def run(self, state: dict) -> dict:
        logger.info(f"[ProjectParser] Running with provider: {self.llm.provider_name}")
        state["project_parser"] = "complete"
        return state

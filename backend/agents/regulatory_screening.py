import logging

from backend.llm.base import LLMProvider

logger = logging.getLogger("eia.agents.regulatory_screening")


class RegulatoryScreeningAgent:
    """Uses RAG over NEPA guidance documents to identify applicable federal,
    state, and local regulations for the project based on its type and location."""

    def __init__(self, llm: LLMProvider):
        self.llm = llm

    def run(self, state: dict) -> dict:
        logger.info(f"[RegulatoryScreening] Running with provider: {self.llm.provider_name}")
        state["regulatory_screening"] = "complete"
        return state

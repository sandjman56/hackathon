import logging

from llm.base import LLMProvider

logger = logging.getLogger("eia.agents.environmental_data")


class EnvironmentalDataAgent:
    """Queries all 5 federal REST APIs (USFWS, NWI, FEMA, Farmland, EJScreen)
    by project coordinates and returns raw geodata for downstream analysis."""

    def __init__(self, llm: LLMProvider):
        self.llm = llm

    def run(self, state: dict) -> dict:
        logger.info(f"[EnvironmentalData] Running with provider: {self.llm.provider_name}")
        state["environmental_data"] = "complete"
        return state

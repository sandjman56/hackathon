import logging

from backend.llm.base import LLMProvider

logger = logging.getLogger("eia.agents.impact_analysis")


class ImpactAnalysisAgent:
    """Reasons over collected geodata and regulatory context to populate a
    significance matrix across environmental impact categories (wetlands,
    endangered species, floodplains, farmland, environmental justice, etc.)."""

    def __init__(self, llm: LLMProvider):
        self.llm = llm

    def run(self, state: dict) -> dict:
        logger.info(f"[ImpactAnalysis] Running with provider: {self.llm.provider_name}")
        state["impact_analysis"] = "complete"
        return state

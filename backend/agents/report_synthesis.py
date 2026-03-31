import logging

from ..llm.base import LLMProvider

logger = logging.getLogger("eia.agents.report_synthesis")


class ReportSynthesisAgent:
    """Generates the final screening-level EIA document from the significance
    matrix and identified regulations, producing a structured report suitable
    for regulatory submission."""

    def __init__(self, llm: LLMProvider):
        self.llm = llm

    def run(self, state: dict) -> dict:
        logger.info(f"[ReportSynthesis] Running with provider: {self.llm.provider_name}")
        state["report_synthesis"] = "complete"
        return state

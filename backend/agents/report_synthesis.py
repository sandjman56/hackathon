import logging

from llm.base import LLMProvider

logger = logging.getLogger("eia.agents.report_synthesis")


class ReportSynthesisAgent:
    """Generates the final screening-level EIA document from the significance
    matrix and identified regulations, producing a structured report suitable
    for regulatory submission."""

    def __init__(self, llm: LLMProvider):
        self.llm = llm

    def run(self, state: dict) -> dict:
        logger.info("[ReportSynthesis] Starting — LLM provider: %s", self.llm.provider_name)

        matrix = state.get("impact_matrix", [])
        regs = state.get("regulations", [])
        env = state.get("environmental_data", {})

        logger.info("[ReportSynthesis] Compiling findings from all pipeline nodes:")
        logger.info("[ReportSynthesis]   impact_matrix rows: %d", len(matrix))
        logger.info("[ReportSynthesis]   regulations identified: %d", len(regs))
        logger.info("[ReportSynthesis]   environmental APIs queried: %d",
                    len([k for k in env if k not in ("query_location", "errors")]))

        errors = env.get("errors", {}) if env else {}
        if errors:
            logger.warning("[ReportSynthesis] %d API error(s) in environmental data: %s",
                           len(errors), list(errors.keys()))

        logger.info("[ReportSynthesis] Report sections to generate: "
                    "Executive Summary, Project Description, Environmental Setting, "
                    "Impact Analysis, Mitigation Measures, Regulatory Compliance, "
                    "Conclusions")
        logger.info("[ReportSynthesis] Invoking %s for narrative generation...",
                    self.llm.provider_name)
        logger.warning("[ReportSynthesis] STUB — LLM report generation not yet implemented; "
                       "report set to empty string")

        state["report"] = ""
        logger.info("[ReportSynthesis] Node complete")
        return state

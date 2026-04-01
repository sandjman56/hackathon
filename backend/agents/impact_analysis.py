import logging

from llm.base import LLMProvider

logger = logging.getLogger("eia.agents.impact_analysis")


class ImpactAnalysisAgent:
    """Reasons over collected geodata and regulatory context to populate a
    significance matrix across environmental impact categories (wetlands,
    endangered species, floodplains, farmland, environmental justice, etc.)."""

    def __init__(self, llm: LLMProvider):
        self.llm = llm

    def run(self, state: dict) -> dict:
        logger.info("[ImpactAnalysis] Starting — LLM provider: %s", self.llm.provider_name)

        env = state.get("environmental_data", {})
        regs = state.get("regulations", [])
        logger.info("[ImpactAnalysis] Pipeline inputs received:")
        logger.info("[ImpactAnalysis]   environmental_data keys: %s", list(env.keys()))
        logger.info("[ImpactAnalysis]   regulations count: %d", len(regs))

        # Summarise key environmental findings going into the matrix
        if env:
            fema = env.get("fema_flood_zones", {})
            if fema:
                zones = [z.get("flood_zone") for z in fema.get("flood_zones", [])]
                logger.info("[ImpactAnalysis] FEMA input — in_sfha: %s  zones: %s",
                            fema.get("in_sfha"), zones or ["none"])

            species = env.get("usfws_species", {})
            if species:
                logger.info("[ImpactAnalysis] USFWS input — %d T&E species",
                            species.get("count", 0))
                listed = [s["name"] for s in species.get("species", [])[:3]]
                if listed:
                    logger.info("[ImpactAnalysis] T&E species (top 3): %s",
                                ", ".join(listed))

            wetlands = env.get("nwi_wetlands", {})
            if wetlands:
                logger.info("[ImpactAnalysis] NWI input — %d wetland features",
                            wetlands.get("count", 0))

            farmland = env.get("usda_farmland", {})
            if farmland:
                logger.info("[ImpactAnalysis] USDA input — class: %r  prime: %s",
                            farmland.get("farmland_class"), farmland.get("is_prime"))

            ej = env.get("ejscreen", {})
            if ej:
                logger.info("[ImpactAnalysis] EJScreen input — EJ index: %s  "
                            "PM2.5 pct: %s  minority: %s",
                            ej.get("ej_index"), ej.get("percentile_pm25"),
                            ej.get("minority_pct"))
        else:
            logger.warning("[ImpactAnalysis] No environmental data available — "
                           "impact matrix will be empty")

        logger.info("[ImpactAnalysis] Impact categories to score: wetlands, "
                    "endangered_species, floodplain, prime_farmland, "
                    "environmental_justice, air_quality, noise, traffic")
        logger.info("[ImpactAnalysis] Significance scale: significant / moderate / "
                    "minimal / none")
        logger.info("[ImpactAnalysis] Invoking %s for LLM-driven matrix scoring...",
                    self.llm.provider_name)
        logger.warning("[ImpactAnalysis] STUB — LLM impact scoring not yet implemented; "
                       "impact_matrix set to []")

        state["impact_matrix"] = []
        logger.info("[ImpactAnalysis] Node complete")
        return state

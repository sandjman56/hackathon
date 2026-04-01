import logging

from llm.base import LLMProvider

logger = logging.getLogger("eia.agents.regulatory_screening")


class RegulatoryScreeningAgent:
    """Uses RAG over NEPA guidance documents to identify applicable federal,
    state, and local regulations for the project based on its type and location."""

    def __init__(self, llm: LLMProvider):
        self.llm = llm

    def run(self, state: dict) -> dict:
        logger.info("[RegulatoryScreening] Starting — LLM provider: %s", self.llm.provider_name)

        parsed = state.get("parsed_project", {})
        project_type = parsed.get("type", "unknown")
        coords = state.get("coordinates", "")
        logger.info("[RegulatoryScreening] Project type: %s  |  Coordinates: %s",
                    project_type, coords)

        env = state.get("environmental_data", {})
        if env:
            in_sfha = env.get("fema_flood_zones", {}).get("in_sfha", False)
            species_count = env.get("usfws_species", {}).get("count", 0)
            wetlands_count = env.get("nwi_wetlands", {}).get("count", 0)
            is_prime = env.get("usda_farmland", {}).get("is_prime", False)
            logger.info("[RegulatoryScreening] Environmental flags — "
                        "SFHA: %s  |  T&E species: %d  |  Wetlands: %d  |  Prime farmland: %s",
                        in_sfha, species_count, wetlands_count, is_prime)
            logger.info("[RegulatoryScreening] Determining applicable statutes: "
                        "NEPA, ESA, CWA §404, Farmland Protection Policy Act, EO 11988...")
        else:
            logger.warning("[RegulatoryScreening] No environmental data in state — "
                           "skipping environmental flag analysis")

        logger.info("[RegulatoryScreening] Embedding project context for RAG query...")
        logger.info("[RegulatoryScreening] Querying NEPA regulation vector store...")
        logger.warning("[RegulatoryScreening] STUB — RAG not yet implemented; "
                       "no regulations retrieved")
        logger.info("[RegulatoryScreening] regulations set to []")
        state["regulations"] = []
        logger.info("[RegulatoryScreening] Node complete")
        return state

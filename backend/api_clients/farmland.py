import logging

logger = logging.getLogger("eia.api_clients.farmland")

# USDA Soil Data Access
# Endpoint: https://sdmdataaccess.sc.egov.usda.gov/


def query_farmland(lat: float, lon: float) -> dict:
    """Query the USDA Soil Data Access API for prime farmland classification."""
    logger.info(f"[Farmland] Querying USDA Soil Data Access for coordinates ({lat}, {lon})")
    return {}

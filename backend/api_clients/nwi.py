import logging

logger = logging.getLogger("eia.api_clients.nwi")

# National Wetlands Inventory WMS
# Endpoint: https://www.fws.gov/wetlands/data/web-map-service.html


def query_nwi(lat: float, lon: float) -> dict:
    """Query the National Wetlands Inventory for wetland data at the given coordinates."""
    logger.info(f"[NWI] Querying National Wetlands Inventory for coordinates ({lat}, {lon})")
    return {}

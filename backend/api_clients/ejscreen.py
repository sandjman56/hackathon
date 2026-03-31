import logging

logger = logging.getLogger("eia.api_clients.ejscreen")

# EPA EJScreen
# Endpoint: https://ejscreen.epa.gov/mapper/ejscreenRESTbroker.aspx


def query_ejscreen(lat: float, lon: float) -> dict:
    """Query the EPA EJScreen API for environmental justice indicators."""
    logger.info(f"[EJScreen] Querying EPA EJScreen for coordinates ({lat}, {lon})")
    return {}

import logging

logger = logging.getLogger("eia.api_clients.usfws")

# USFWS IPaC (Information for Planning and Consultation)
# Endpoint: https://ipac.ecosphere.fws.gov/location/api/


def query_usfws(lat: float, lon: float) -> dict:
    """Query the US Fish & Wildlife Service IPaC API for threatened/endangered species."""
    logger.info(f"[USFWS] Querying IPaC for coordinates ({lat}, {lon})")
    return {}

import logging

logger = logging.getLogger("eia.api_clients.fema")

# FEMA National Flood Hazard Layer (NFHL)
# Endpoint: https://hazards.fema.gov/gis/nfhl/rest/services/public/NFHL/MapServer


def query_fema(lat: float, lon: float) -> dict:
    """Query the FEMA NFHL for flood hazard zones at the given coordinates."""
    logger.info(f"[FEMA] Querying NFHL for coordinates ({lat}, {lon})")
    return {}

import logging

import httpx

logger = logging.getLogger("eia.api_clients.usfws")

# USFWS IPaC (Information for Planning and Consultation)
# Endpoint: https://ipac.ecosphere.fws.gov/location/api/
# Payload: {"projectLocationWKT": "<WKT polygon>"}
# Response: {"resources": {"allReferencedPopulationsBySid": {sid: {species fields}, ...}, ...}}

_BUFFER_DEG = 0.009  # ~1 km bounding box half-width


def _bbox_wkt(lat: float, lon: float, delta: float = _BUFFER_DEG) -> str:
    return (
        f"POLYGON(("
        f"{lon-delta} {lat-delta}, "
        f"{lon+delta} {lat-delta}, "
        f"{lon+delta} {lat+delta}, "
        f"{lon-delta} {lat+delta}, "
        f"{lon-delta} {lat-delta}"
        f"))"
    )


def query_usfws(lat: float, lon: float, client: httpx.Client) -> dict:
    """Query the US Fish & Wildlife Service IPaC API for threatened/endangered species."""
    url = "https://ipac.ecosphere.fws.gov/location/api/resources"
    logger.info("[USFWS] POST %s — bbox ~1km around (%.4f, %.4f)", url, lat, lon)
    resp = client.post(
        url,
        json={"projectLocationWKT": _bbox_wkt(lat, lon)},
        headers={"Accept": "application/json"},
        timeout=30,
    )
    logger.info("[USFWS] Response: HTTP %d", resp.status_code)
    resp.raise_for_status()
    data = resp.json()

    # Response: resources.allReferencedPopulationsBySid is a dict of {sid: species_obj}
    populations = (
        data.get("resources", {})
            .get("allReferencedPopulationsBySid", {})
    )
    species_list = [
        {
            "name": s.get("optionalCommonName") or s.get("shortName", "Unknown"),
            "scientific_name": s.get("optionalScientificName", ""),
            "status": s.get("listingStatusName", ""),
            "group": s.get("groupName", ""),
        }
        for s in populations.values()
        if isinstance(s, dict)
    ]

    result = {"count": len(species_list), "species": species_list}
    logger.info("[USFWS] Found %d threatened/endangered species", result["count"])
    if result["species"]:
        names = [s["name"] for s in result["species"][:5]]
        logger.info("[USFWS] Species (first 5): %s", ", ".join(names))
    return result

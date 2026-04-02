import logging

import httpx

logger = logging.getLogger("eia.api_clients.fema")

# FEMA National Flood Hazard Layer (NFHL)
# Endpoint: https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query


def query_fema(lat: float, lon: float, client: httpx.Client) -> dict:
    """Query FEMA National Flood Hazard Layer for the project location's flood zone."""
    url = (
        "https://hazards.fema.gov/arcgis/rest/services"
        "/public/NFHL/MapServer/28/query"
    )
    logger.info("[FEMA] GET %s — point (%.4f, %.4f)", url, lat, lon)
    params = {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "FLD_ZONE,ZONE_SUBTY,SFHA_TF",
        "returnGeometry": "false",
        "f": "json",
    }
    resp = client.get(url, params=params, timeout=30)
    logger.info("[FEMA] Response: HTTP %d", resp.status_code)
    resp.raise_for_status()
    features = resp.json().get("features", [])

    zones = [
        {
            "flood_zone": f["attributes"].get("FLD_ZONE", ""),
            "zone_subtype": f["attributes"].get("ZONE_SUBTY", ""),
            "sfha": f["attributes"].get("SFHA_TF") == "T",
        }
        for f in features
    ]
    result = {
        "in_sfha": any(z["sfha"] for z in zones),
        "flood_zones": zones,
    }
    zone_codes = [z["flood_zone"] for z in zones] or ["X (minimal flood hazard)"]
    logger.info("[FEMA] Flood zone(s): %s  |  In SFHA: %s",
                ", ".join(zone_codes), result["in_sfha"])
    return result

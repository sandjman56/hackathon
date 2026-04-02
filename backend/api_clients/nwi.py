import logging

import httpx

logger = logging.getLogger("eia.api_clients.nwi")

# USFWS National Wetlands Inventory
# Endpoint: https://fwspublicservices.wim.usgs.gov/wetlandsmapservice/rest/services/Wetlands/MapServer/0/query


def query_nwi(lat: float, lon: float, client: httpx.Client) -> dict:
    """Query the National Wetlands Inventory within 1 km of the project location."""
    url = (
        "https://fwspublicservices.wim.usgs.gov"
        "/wetlandsmapservice/rest/services/Wetlands/MapServer/0/query"
    )
    logger.info("[NWI] GET %s — 1000m radius from (%.4f, %.4f)", url, lat, lon)
    params = {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "distance": 1000,
        "units": "esriSRUnit_Meter",
        "outFields": "ATTRIBUTE,WETLAND_TYPE,ACRES",
        "returnGeometry": "false",
        "f": "json",
    }
    resp = client.get(url, params=params, timeout=30)
    logger.info("[NWI] Response: HTTP %d", resp.status_code)
    resp.raise_for_status()
    features = resp.json().get("features", [])

    result = {
        "count": len(features),
        "wetlands": [
            {
                "type": f["attributes"].get("WETLAND_TYPE", ""),
                "attribute": f["attributes"].get("ATTRIBUTE", ""),
                "acres": f["attributes"].get("ACRES"),
            }
            for f in features
        ],
    }
    logger.info("[NWI] Found %d wetland features within 1km", result["count"])
    if result["wetlands"]:
        types = list({w["type"] for w in result["wetlands"]})
        logger.info("[NWI] Wetland types: %s", ", ".join(types))
    return result

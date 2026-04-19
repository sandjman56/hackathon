import logging
import time

import httpx

logger = logging.getLogger("eia.api_clients.fema")

# FEMA National Flood Hazard Layer (NFHL)
# Endpoint: https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query

_FEMA_URL = (
    "https://hazards.fema.gov/arcgis/rest/services"
    "/public/NFHL/MapServer/28/query"
)

_MAX_RETRIES = 2
_RETRY_DELAY = 1.5  # seconds


def query_fema(lat: float, lon: float, client: httpx.Client) -> dict:
    """Query FEMA National Flood Hazard Layer for the project location's flood zone."""
    logger.info("[FEMA] GET %s — point (%.4f, %.4f)", _FEMA_URL, lat, lon)
    params = {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "FLD_ZONE,ZONE_SUBTY,SFHA_TF",
        "returnGeometry": "false",
        "f": "json",
    }

    last_exc: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 2):  # 1 initial + N retries
        try:
            resp = client.get(_FEMA_URL, params=params, timeout=30)
            logger.info("[FEMA] Response: HTTP %d (attempt %d)", resp.status_code, attempt)
            resp.raise_for_status()
            body = resp.json()
            break
        except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
            last_exc = exc
            if attempt <= _MAX_RETRIES:
                logger.warning("[FEMA] Attempt %d failed (%s), retrying in %.1fs…",
                               attempt, type(exc).__name__, _RETRY_DELAY)
                time.sleep(_RETRY_DELAY)
            continue
    else:
        raise last_exc  # type: ignore[misc]

    # ArcGIS returns HTTP 200 with an error body on bad queries
    if "error" in body:
        err = body["error"]
        raise RuntimeError(
            f"FEMA ArcGIS error {err.get('code')}: {err.get('message', 'unknown')}"
        )

    features = body.get("features", [])

    zones = [
        {
            "flood_zone": f.get("attributes", {}).get("FLD_ZONE", ""),
            "zone_subtype": f.get("attributes", {}).get("ZONE_SUBTY", ""),
            "sfha": f.get("attributes", {}).get("SFHA_TF") == "T",
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

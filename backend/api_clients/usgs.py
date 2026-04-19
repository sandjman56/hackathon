import logging

import httpx

logger = logging.getLogger("eia.api_clients.usgs")

_SEISMIC_URL = "https://earthquake.usgs.gov/ws/designmaps/asce7-22.json"
_ELEVATION_URL = "https://epqs.nationalmap.gov/v1/json"


def query_usgs(lat: float, lon: float, client: httpx.Client) -> dict:
    """Query USGS for seismic design values (ASCE 7-22) and site elevation."""
    logger.info("[USGS] Querying seismic design values for (%.4f, %.4f)", lat, lon)
    seismic_resp = client.get(_SEISMIC_URL, params={
        "latitude": lat,
        "longitude": lon,
        "riskCategory": "II",
        "siteClass": "D",
        "title": "EIA",
    }, timeout=30)
    logger.info("[USGS] Seismic response: HTTP %d", seismic_resp.status_code)
    seismic_resp.raise_for_status()
    seismic_data = seismic_resp.json().get("response", {}).get("data", {})

    logger.info("[USGS] Querying elevation for (%.4f, %.4f)", lat, lon)
    elev_resp = client.get(_ELEVATION_URL, params={
        "x": lon,
        "y": lat,
        "wkid": "4326",
    }, timeout=30)
    logger.info("[USGS] Elevation response: HTTP %d", elev_resp.status_code)
    elev_resp.raise_for_status()
    elevation_m = elev_resp.json().get("value")

    sdc = seismic_data.get("sdc")
    pgam = seismic_data.get("pgam")
    ss = seismic_data.get("ss")
    s1 = seismic_data.get("s1")

    result = {
        "source": "USGS ASCE 7-22 Design Maps + EPQS",
        "seismic_design_category": sdc,
        "peak_ground_accel_g": pgam,
        "spectral_accel_short_g": ss,
        "spectral_accel_1s_g": s1,
        "elevation_m": float(elevation_m) if elevation_m is not None else None,
    }
    logger.info(
        "[USGS] SDC=%s  PGA=%.3fg  Elevation=%.1fm",
        sdc, pgam or 0, float(elevation_m) if elevation_m else 0,
    )
    return result

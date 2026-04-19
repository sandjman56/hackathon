import logging
import statistics

import httpx

logger = logging.getLogger("eia.api_clients.noaa")

_POINTS_URL = "https://api.weather.gov/points/{lat},{lon}"
_GRIDPOINTS_URL = "https://api.weather.gov/gridpoints/{wfo}/{x},{y}"


def _mean_values(prop: dict) -> float | None:
    """Return mean of non-null values from a NOAA gridpoint property object."""
    vals = [v["value"] for v in prop.get("values", []) if v.get("value") is not None]
    return round(statistics.mean(vals), 2) if vals else None


def query_noaa(lat: float, lon: float, client: httpx.Client) -> dict:
    """Query NOAA Weather API for climate and atmospheric dispersion conditions."""
    points_url = _POINTS_URL.format(lat=lat, lon=lon)
    logger.info("[NOAA] GET %s", points_url)
    pts_resp = client.get(points_url, timeout=30, headers={"User-Agent": "EIA-Agent/1.0"})
    logger.info("[NOAA] Points response: HTTP %d", pts_resp.status_code)
    pts_resp.raise_for_status()

    props = pts_resp.json().get("properties", {})
    wfo = props.get("gridId")
    gx = props.get("gridX")
    gy = props.get("gridY")
    if not all([wfo, gx is not None, gy is not None]):
        raise ValueError(f"NOAA points endpoint returned incomplete grid data: {props}")

    grid_url = _GRIDPOINTS_URL.format(wfo=wfo, x=gx, y=gy)
    logger.info("[NOAA] GET %s", grid_url)
    grid_resp = client.get(grid_url, timeout=30, headers={"User-Agent": "EIA-Agent/1.0"})
    logger.info("[NOAA] Gridpoints response: HTTP %d", grid_resp.status_code)
    grid_resp.raise_for_status()

    gprops = grid_resp.json().get("properties", {})

    mixing_height_m = _mean_values(gprops.get("mixingHeight", {}))
    wind_speed_kmh = _mean_values(gprops.get("windSpeed", {}))
    wind_gust_kmh = _mean_values(gprops.get("windGust", {}))
    precip_mm = _mean_values(gprops.get("quantitativePrecipitation", {}))
    dispersion_index = _mean_values(gprops.get("dispersionIndex", {}))
    transport_wind_kmh = _mean_values(gprops.get("transportWindSpeed", {}))

    result = {
        "source": "NOAA api.weather.gov gridpoints",
        "grid_wfo": wfo,
        "mixing_height_m": mixing_height_m,
        "wind_speed_kmh": wind_speed_kmh,
        "wind_gust_kmh": wind_gust_kmh,
        "transport_wind_kmh": transport_wind_kmh,
        "dispersion_index": dispersion_index,
        "precip_mm_per_period": precip_mm,
    }
    logger.info(
        "[NOAA] WFO=%s  MixingHeight=%.0fm  Wind=%.1f km/h  DispersionIdx=%s",
        wfo,
        mixing_height_m or 0,
        wind_speed_kmh or 0,
        dispersion_index,
    )
    return result

import logging

import httpx

from api_clients.usfws import query_usfws
from api_clients.nwi import query_nwi
from api_clients.fema import query_fema
from api_clients.farmland import query_farmland
from api_clients.ejscreen import query_ejscreen
from api_clients.usgs import query_usgs
from api_clients.noaa import query_noaa
from api_clients.aqs import query_aqs

logger = logging.getLogger("eia.agents.environmental_data")


def _parse_coordinates(coord_str: str) -> tuple[float, float]:
    """Parse 'lat, lon' or 'lat lon' into (lat, lon) floats."""
    parts = coord_str.replace(",", " ").split()
    if len(parts) != 2:
        raise ValueError(f"Cannot parse coordinates: {coord_str!r}")
    return float(parts[0]), float(parts[1])


_API_CALLS = [
    ("usfws_species", query_usfws),
    ("nwi_wetlands", query_nwi),
    ("fema_flood_zones", query_fema),
    ("usda_farmland", query_farmland),
    ("ejscreen", query_ejscreen),
    ("usgs_seismic", query_usgs),
    ("noaa_climate", query_noaa),
    ("epa_aqs", query_aqs),
]


class EnvironmentalDataAgent:
    """Queries all 5 federal REST APIs (USFWS, NWI, FEMA, Farmland, EJScreen)
    by project coordinates and returns raw geodata for downstream analysis."""

    def __init__(self):
        pass

    def run(self, state: dict) -> dict:
        coordinates = state.get("coordinates", "")
        lat, lon = _parse_coordinates(coordinates)

        logger.info("[EnvironmentalData] Starting — querying 8 federal APIs")
        logger.info("[EnvironmentalData] Location: lat=%.6f  lon=%.6f", lat, lon)
        logger.info("[EnvironmentalData] APIs: USFWS IPaC, NWI, FEMA NFHL, "
                    "USDA SSURGO, Census ACS (EJ), USGS Seismic, NOAA Climate, EPA AQS")

        results: dict = {
            "query_location": {"lat": lat, "lon": lon},
            "errors": {},
        }

        with httpx.Client() as client:
            for key, fn in _API_CALLS:
                try:
                    results[key] = fn(lat, lon, client)
                    logger.info("[EnvironmentalData] ✓ %s", key)
                except httpx.TimeoutException as exc:
                    logger.warning(
                        "[EnvironmentalData] ✗ %s — TIMEOUT after 30s: %s",
                        key, exc,
                    )
                    results[key] = {}
                    results["errors"][key] = f"Timeout: {exc}"
                except httpx.HTTPStatusError as exc:
                    logger.warning(
                        "[EnvironmentalData] ✗ %s — HTTP %d from %s: %s",
                        key, exc.response.status_code,
                        exc.request.url.host, exc.response.text[:300],
                    )
                    results[key] = {}
                    results["errors"][key] = (
                        f"HTTP {exc.response.status_code}: "
                        f"{exc.response.text[:200]}"
                    )
                except Exception as exc:
                    logger.warning(
                        "[EnvironmentalData] ✗ %s — %s: %s",
                        key, type(exc).__name__, exc,
                    )
                    results[key] = {}
                    results["errors"][key] = f"{type(exc).__name__}: {exc}"

        n_ok = sum(1 for k in results if k not in ("query_location", "errors") and results[k])
        n_err = len(results["errors"])
        logger.info("[EnvironmentalData] Complete — %d/%d APIs succeeded",
                    n_ok, len(_API_CALLS))
        if n_err:
            logger.warning("[EnvironmentalData] Failed APIs: %s",
                           list(results["errors"].keys()))
            for api_key, err_msg in results["errors"].items():
                logger.warning("[EnvironmentalData]   %s → %s", api_key, err_msg)

        state["environmental_data"] = results
        return state

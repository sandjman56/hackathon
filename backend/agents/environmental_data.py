import logging

import httpx

from llm.base import LLMProvider

logger = logging.getLogger("eia.agents.environmental_data")

_BUFFER_DEG = 0.009  # ~1 km bounding box half-width


def _parse_coordinates(coord_str: str) -> tuple[float, float]:
    """Parse 'lat, lon' or 'lat lon' into (lat, lon) floats."""
    parts = coord_str.replace(",", " ").split()
    if len(parts) != 2:
        raise ValueError(f"Cannot parse coordinates: {coord_str!r}")
    return float(parts[0]), float(parts[1])


def _bbox_polygon(lat: float, lon: float, delta: float = _BUFFER_DEG) -> list:
    """Return a GeoJSON coordinate ring for a square bounding box around a point."""
    return [[
        [lon - delta, lat - delta],
        [lon + delta, lat - delta],
        [lon + delta, lat + delta],
        [lon - delta, lat + delta],
        [lon - delta, lat - delta],
    ]]


def _query_usfws(lat: float, lon: float, client: httpx.Client) -> dict:
    """Query USFWS IPaC for threatened and endangered species near the project location."""
    url = "https://ipac.ecosphere.fws.gov/location/api/resources"
    logger.info("[USFWS] POST %s — bbox ~1km around (%.4f, %.4f)", url, lat, lon)
    payload = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": _bbox_polygon(lat, lon),
            },
            "properties": {},
        }]
    }
    resp = client.post(url, json=payload, timeout=30)
    logger.info("[USFWS] Response: HTTP %d", resp.status_code)
    resp.raise_for_status()
    data = resp.json()

    # /resources returns a list of resource objects, each with a "species" list
    species_list = []
    if isinstance(data, list):
        for resource in data:
            species_list.extend(resource.get("species", []))
    elif isinstance(data, dict):
        for resource in data.get("resources", []):
            species_list.extend(resource.get("species", []))
        if not species_list:
            species_list = data.get("species", data.get("items", []))

    result = {
        "count": len(species_list),
        "species": [
            {
                "name": s.get("commonName") or s.get("name", "Unknown"),
                "scientific_name": s.get("scientificName", ""),
                "status": s.get("listingStatus") or s.get("status", ""),
                "group": s.get("taxonGroup") or s.get("type", ""),
            }
            for s in species_list
        ],
    }
    logger.info("[USFWS] Found %d threatened/endangered species", result["count"])
    if result["species"]:
        names = [s["name"] for s in result["species"][:5]]
        logger.info("[USFWS] Species (first 5): %s", ", ".join(names))
    return result


def _query_nwi(lat: float, lon: float, client: httpx.Client) -> dict:
    """Query USFWS National Wetlands Inventory within 1 km of the project location."""
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


def _query_fema(lat: float, lon: float, client: httpx.Client) -> dict:
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


def _query_usda_farmland(lat: float, lon: float, client: httpx.Client) -> dict:
    """Query USDA NRCS SSURGO (Soil Data Access) for prime farmland classification."""
    url = "https://SDMDataAccess.sc.egov.usda.gov/Tabular/post.rest"
    logger.info("[USDA] POST %s — SSURGO farmland query at (%.4f, %.4f)", url, lat, lon)
    query = (
        f"SELECT mu.muname, c.farmlndcl "
        f"FROM mapunit mu "
        f"INNER JOIN component c ON mu.mukey = c.mukey "
        f"INNER JOIN SDA_Get_Mukey_from_intersection_with_WktWgs84("
        f"'POINT({lon} {lat})') AS i ON mu.mukey = i.mukey "
        f"WHERE c.majcompflag = 'Yes' "
        f"ORDER BY c.comppct_r DESC"
    )
    resp = client.post(
        url,
        data={"query": query, "format": "json+columnname"},
        timeout=30,
    )
    logger.info("[USDA] Response: HTTP %d", resp.status_code)
    resp.raise_for_status()
    rows = resp.json().get("Table", [])

    if len(rows) > 1:
        headers = rows[0]
        records = [dict(zip(headers, row)) for row in rows[1:]]
        farmland_class = records[0].get("farmlndcl", "Not prime farmland")
        map_unit = records[0].get("muname", "")
    else:
        farmland_class = "Not determined"
        map_unit = ""

    result = {
        "farmland_class": farmland_class,
        "map_unit": map_unit,
        "is_prime": "prime farmland" in (farmland_class or "").lower(),
    }
    logger.info("[USDA] Map unit: %r  |  Farmland class: %r  |  Prime: %s",
                map_unit, farmland_class, result["is_prime"])
    return result


def _query_census_ej(lat: float, lon: float, client: httpx.Client) -> dict:
    """Query Census ACS 5-year estimates for environmental justice demographic indicators.

    Replaces EPA EJScreen (taken offline Feb 2025). Two-step:
      1. Census Geocoder — resolve (lat, lon) to state/county/tract FIPS
      2. ACS 5-year — pull poverty and race/ethnicity variables for that tract
    """
    # Step 1: geocode to census tract
    geo_url = "https://geocoding.geo.census.gov/geocoder/geographies/coordinates"
    logger.info("[Census] GET %s — resolving tract for (%.4f, %.4f)", geo_url, lat, lon)
    geo_resp = client.get(geo_url, params={
        "x": lon,
        "y": lat,
        "benchmark": "Public_AR_Current",
        "vintage": "Current_Current",
        "format": "json",
    }, timeout=30)
    logger.info("[Census] Geocoder response: HTTP %d", geo_resp.status_code)
    geo_resp.raise_for_status()

    tracts = (
        geo_resp.json()
        .get("result", {})
        .get("geographies", {})
        .get("Census Tracts", [])
    )
    if not tracts:
        raise ValueError("Census geocoder returned no tract for coordinates")

    state = tracts[0]["STATE"]
    county = tracts[0]["COUNTY"]
    tract = tracts[0]["TRACT"]
    logger.info("[Census] Tract: state=%s county=%s tract=%s", state, county, tract)

    # Step 2: ACS 5-year demographic variables
    # B03002: race/ethnicity — total vs white-alone non-Hispanic (for minority %)
    # B17001: poverty status — total vs below poverty level (for low-income %)
    acs_vars = [
        "B03002_001E",  # race/ethnicity universe total
        "B03002_003E",  # white alone, not Hispanic or Latino
        "B17001_001E",  # poverty universe total
        "B17001_002E",  # income below poverty level
    ]
    acs_url = "https://api.census.gov/data/2023/acs/acs5"
    logger.info("[Census] GET %s — tract %s%s%s", acs_url, state, county, tract)
    acs_resp = client.get(acs_url, params={
        "get": ",".join(acs_vars),
        "for": f"tract:{tract}",
        "in": f"state:{state} county:{county}",
    }, timeout=30)
    logger.info("[Census] ACS response: HTTP %d", acs_resp.status_code)
    acs_resp.raise_for_status()

    rows = acs_resp.json()
    vals = dict(zip(rows[0], rows[1]))

    race_total = int(vals.get("B03002_001E") or 0)
    white_nh = int(vals.get("B03002_003E") or 0)
    poverty_total = int(vals.get("B17001_001E") or 0)
    below_poverty = int(vals.get("B17001_002E") or 0)

    minority_pct = round((race_total - white_nh) / race_total, 4) if race_total > 0 else None
    low_income_pct = round(below_poverty / poverty_total, 4) if poverty_total > 0 else None

    result = {
        "source": "Census ACS 5-year (2023)",
        "census_tract": f"{state}{county}{tract}",
        "minority_pct": minority_pct,
        "low_income_pct": low_income_pct,
        # EJScreen air/hazard percentiles are unavailable (EPA service offline Feb 2025)
        "percentile_pm25": None,
        "percentile_ozone": None,
        "percentile_lead_paint": None,
        "percentile_superfund": None,
        "percentile_wastewater": None,
        "ej_index": None,
    }
    logger.info(
        "[Census] Tract %s — minority: %.1f%%  low-income: %.1f%%",
        result["census_tract"],
        (minority_pct or 0) * 100,
        (low_income_pct or 0) * 100,
    )
    return result


_API_CALLS = [
    ("usfws_species", _query_usfws),
    ("nwi_wetlands", _query_nwi),
    ("fema_flood_zones", _query_fema),
    ("usda_farmland", _query_usda_farmland),
    ("ejscreen", _query_census_ej),
]


class EnvironmentalDataAgent:
    """Queries all 5 federal REST APIs (USFWS, NWI, FEMA, Farmland, EJScreen)
    by project coordinates and returns raw geodata for downstream analysis."""

    def __init__(self, llm: LLMProvider):
        self.llm = llm

    def run(self, state: dict) -> dict:
        coordinates = state.get("coordinates", "")
        lat, lon = _parse_coordinates(coordinates)

        logger.info("[EnvironmentalData] Starting — querying 5 federal APIs")
        logger.info("[EnvironmentalData] Location: lat=%.6f  lon=%.6f", lat, lon)
        logger.info("[EnvironmentalData] APIs: USFWS IPaC, NWI, FEMA NFHL, "
                    "USDA SSURGO, Census ACS (EJ demographics)")

        results: dict = {
            "query_location": {"lat": lat, "lon": lon},
            "errors": {},
        }

        with httpx.Client() as client:
            for key, fn in _API_CALLS:
                try:
                    results[key] = fn(lat, lon, client)
                    logger.info("[EnvironmentalData] ✓ %s", key)
                except Exception as exc:
                    logger.warning("[EnvironmentalData] ✗ %s — %s: %s",
                                   key, type(exc).__name__, exc)
                    results[key] = {}
                    results["errors"][key] = str(exc)

        n_ok = sum(1 for k in results if k not in ("query_location", "errors") and results[k])
        n_err = len(results["errors"])
        logger.info("[EnvironmentalData] Complete — %d/%d APIs succeeded",
                    n_ok, len(_API_CALLS))
        if n_err:
            logger.warning("[EnvironmentalData] Failed APIs: %s",
                           list(results["errors"].keys()))

        state["environmental_data"] = results
        return state

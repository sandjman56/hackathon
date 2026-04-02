import logging

import httpx

logger = logging.getLogger("eia.api_clients.ejscreen")

# EPA EJScreen replacement: Census ACS 5-year estimates
# EPA EJScreen was taken offline Feb 2025; demographic EJ indicators now come from Census ACS.
# Step 1: Census Geocoder — resolve (lat, lon) to state/county/tract FIPS
# Step 2: ACS 5-year — pull poverty and race/ethnicity variables for that tract


def query_ejscreen(lat: float, lon: float, client: httpx.Client) -> dict:
    """Query Census ACS 5-year estimates for environmental justice demographic indicators."""
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

import logging

import httpx

logger = logging.getLogger("eia.api_clients.farmland")

# USDA NRCS Soil Data Access (SSURGO)
# Endpoint: https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest
# Note: SSURGO component table no longer includes 'farmlndcl' column.
# Land capability class (nirrcapcl) is used as the farmland quality indicator:
#   Class I / II  → Prime Farmland
#   Class III     → Farmland of Statewide Importance
#   Class IV–VIII → Not prime farmland

_CAPABILITY_CLASS_LABELS = {
    "1": "Prime Farmland",
    "2": "Prime Farmland",
    "3": "Farmland of Statewide Importance",
}


def query_farmland(lat: float, lon: float, client: httpx.Client) -> dict:
    """Query USDA NRCS SSURGO (Soil Data Access) for land capability class."""
    url = "https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest"
    logger.info("[USDA] POST %s — SSURGO farmland query at (%.4f, %.4f)", url, lat, lon)
    query = (
        f"SELECT mu.muname, c.compname, c.nirrcapcl, c.comppct_r "
        f"FROM mapunit mu "
        f"INNER JOIN component c ON mu.mukey = c.mukey "
        f"INNER JOIN SDA_Get_Mukey_from_intersection_with_WktWgs84("
        f"'POINT({lon} {lat})') AS i ON mu.mukey = i.mukey "
        f"WHERE c.majcompflag = 'Yes' "
        f"ORDER BY c.comppct_r DESC"
    )
    resp = client.post(
        url,
        json={"query": query, "format": "json+columnname"},
        timeout=30,
    )
    logger.info("[USDA] Response: HTTP %d", resp.status_code)
    resp.raise_for_status()
    rows = resp.json().get("Table", [])

    if len(rows) > 1:
        headers = rows[0]
        records = [dict(zip(headers, row)) for row in rows[1:]]
        cap_class = records[0].get("nirrcapcl") or ""
        map_unit = records[0].get("muname", "")
        comp_name = records[0].get("compname", "")
        farmland_class = _CAPABILITY_CLASS_LABELS.get(str(cap_class).strip(), "Not prime farmland")
    else:
        cap_class = ""
        map_unit = ""
        comp_name = ""
        farmland_class = "Not determined"

    result = {
        "farmland_class": farmland_class,
        "capability_class": cap_class,
        "map_unit": map_unit,
        "component": comp_name,
        "is_prime": farmland_class == "Prime Farmland",
    }
    logger.info("[USDA] Map unit: %r  |  Cap class: %r  |  Farmland: %r  |  Prime: %s",
                map_unit, cap_class, farmland_class, result["is_prime"])
    return result

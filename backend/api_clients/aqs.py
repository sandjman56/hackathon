import logging
import statistics
from datetime import date, timedelta

import httpx

logger = logging.getLogger("eia.api_clients.aqs")

_AQS_URL = "https://aqs.epa.gov/data/api/dailyData/byBox"

# Demo credentials — register at https://aqs.epa.gov/data/api/signup for production
_AQS_EMAIL = "test@aqs.api"
_AQS_KEY = "test"

# Parameters: PM2.5 (88101) and Ozone (44201)
_PARAMS = [("88101", "pm25"), ("44201", "ozone")]
_BOX_DEGREES = 0.3
_LOOKBACK_DAYS = 90


def query_aqs(lat: float, lon: float, client: httpx.Client) -> dict:
    """Query EPA AQS for 90-day baseline PM2.5 and ozone readings near the project site."""
    end = date.today() - timedelta(days=1)  # yesterday (AQS lags by ~1 day)
    start = end - timedelta(days=_LOOKBACK_DAYS)

    bbox = {
        "minlat": lat - _BOX_DEGREES,
        "maxlat": lat + _BOX_DEGREES,
        "minlon": lon - _BOX_DEGREES,
        "maxlon": lon + _BOX_DEGREES,
    }

    baseline: dict = {
        "source": "EPA AQS (Air Quality System)",
        "period_days": _LOOKBACK_DAYS,
        "bdate": start.strftime("%Y%m%d"),
        "edate": end.strftime("%Y%m%d"),
    }

    for param_code, label in _PARAMS:
        logger.info("[AQS] Querying %s (%s) — %s to %s", label, param_code,
                    start, end)
        resp = client.get(_AQS_URL, params={
            "email": _AQS_EMAIL,
            "key": _AQS_KEY,
            "param": param_code,
            "bdate": start.strftime("%Y%m%d"),
            "edate": end.strftime("%Y%m%d"),
            **bbox,
        }, timeout=60)
        logger.info("[AQS] %s response: HTTP %d", label, resp.status_code)
        resp.raise_for_status()

        body = resp.json()
        if body.get("Header", [{}])[0].get("status") == "Failed":
            msg = body["Header"][0].get("error", "unknown error")
            raise RuntimeError(f"AQS API error for {label}: {msg}")

        records = body.get("Data", [])
        means = [
            r["arithmetic_mean"]
            for r in records
            if r.get("arithmetic_mean") is not None and r.get("validity_indicator") == "Y"
        ]
        aqis = [r["aqi"] for r in records if r.get("aqi") is not None]

        baseline[f"{label}_mean"] = round(statistics.mean(means), 2) if means else None
        baseline[f"{label}_max"] = round(max(means), 2) if means else None
        baseline[f"{label}_aqi_mean"] = round(statistics.mean(aqis), 1) if aqis else None
        baseline[f"{label}_sample_count"] = len(means)
        logger.info("[AQS] %s — mean=%.2f  max=%.2f  n=%d",
                    label,
                    baseline[f"{label}_mean"] or 0,
                    baseline[f"{label}_max"] or 0,
                    len(means))

    return baseline

"""
EIA Data Fetcher — Energy Markets Dashboard
Fetches live weekly petroleum data from EIA Open API v2
"""

import os
import json
import time
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("EIA_API_KEY", "DEMO_KEY")
BASE    = "https://api.eia.gov/v2"
CACHE   = {}

# ── Series definitions ──────────────────────────────────────────────────────
SERIES = {
    "cushing_stocks":     ("WCSSTUS1", "Cushing crude stocks",      "mmbbls"),
    "total_crude_stocks": ("WCRSTUS1", "Total US crude stocks",     "mmbbls"),
    "gasoline_stocks":    ("WGTSTUS1", "US gasoline stocks",        "mmbbls"),
    "distillate_stocks":  ("WDISTUS1", "US distillate stocks",      "mmbbls"),
    "crude_production":   ("WCRFPUS2", "US crude production",       "mbd"),
    "refinery_util":      ("WCRRIUS2", "Refinery utilisation",      "%"),
    "gasoline_demand":    ("WGFUPUS2", "Gasoline implied demand",   "mbd"),
    "distillate_demand":  ("WDITUUS2", "Distillate implied demand", "mbd"),
    "crude_exports":      ("WCREXUS2", "Crude exports",             "mbd"),
    "crude_imports":      ("WCRIMUS2", "Crude imports",             "mbd"),
}

# ── 5-year seasonal averages (approximate baselines) ────────────────────────
FIVE_YR_AVG = {
    "cushing_stocks":     430,
    "total_crude_stocks": 450,
    "gasoline_stocks":    235,
    "distillate_stocks":  120,
    "crude_production":   12.9,
    "refinery_util":      90.0,
}

# ── Mock data for offline testing ────────────────────────────────────────────
MOCK_DATA = {
    "cushing_stocks":     {"value": 422.1, "prev": 435.2, "unit": "mmbbls"},
    "total_crude_stocks": {"value": 441.5, "prev": 447.0, "unit": "mmbbls"},
    "gasoline_stocks":    {"value": 228.4, "prev": 231.1, "unit": "mmbbls"},
    "distillate_stocks":  {"value": 112.7, "prev": 115.3, "unit": "mmbbls"},
    "crude_production":   {"value": 13.2,  "prev": 13.1,  "unit": "mbd"},
    "refinery_util":      {"value": 91.4,  "prev": 90.8,  "unit": "%"},
    "gasoline_demand":    {"value": 8.9,   "prev": 8.7,   "unit": "mbd"},
    "distillate_demand":  {"value": 3.8,   "prev": 4.0,   "unit": "mbd"},
    "crude_exports":      {"value": 4.2,   "prev": 3.9,   "unit": "mbd"},
    "crude_imports":      {"value": 6.1,   "prev": 6.3,   "unit": "mbd"},
}


def fetch_series(series_id: str, retries: int = 3) -> list:
    """Fetch last 2 data points for a series with retry + backoff."""
    url = f"{BASE}/petroleum/supply/weekly/wpsup"
    params = {
        "api_key": API_KEY,
        "frequency": "weekly",
        "data[0]": "value",
        "facets[series][]": series_id,
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "length": 2,
        "offset": 0,
    }
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=10)
            r.raise_for_status()
            return r.json().get("response", {}).get("data", [])
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                print(f"  Failed to fetch {series_id}: {e}")
                return []


def fetch_all(mock: bool = False) -> dict:
    """
    Fetch all series. Returns dict of:
    { key: { value, prev, unit, period, wow, vs_5yr } }
    """
    # Check cache (1 hour TTL)
    cache_key = "eia_all"
    now = datetime.now(timezone.utc).timestamp()
    if cache_key in CACHE and now - CACHE[cache_key]["ts"] < 3600:
        return CACHE[cache_key]["data"]

    raw = MOCK_DATA if mock else {}

    if not mock:
        for key, (sid, label, unit) in SERIES.items():
            rows = fetch_series(sid)
            if len(rows) >= 2:
                raw[key] = {
                    "value":  float(rows[0].get("value", 0)),
                    "prev":   float(rows[1].get("value", 0)),
                    "unit":   unit,
                    "period": rows[0].get("period", ""),
                }
            elif len(rows) == 1:
                raw[key] = {
                    "value":  float(rows[0].get("value", 0)),
                    "prev":   None,
                    "unit":   unit,
                    "period": rows[0].get("period", ""),
                }
            else:
                raw[key] = {"value": None, "prev": None, "unit": unit, "period": ""}

    # Compute derived metrics
    result = {}
    for key, data in raw.items():
        v, p = data.get("value"), data.get("prev")
        wow   = round(v - p, 3) if v is not None and p is not None else None
        vs5yr = round(v - FIVE_YR_AVG[key], 2) if key in FIVE_YR_AVG and v is not None else None
        result[key] = {**data, "wow": wow, "vs_5yr_avg": vs5yr}

    # Days of forward demand cover
    total  = sum(result[k]["value"] or 0 for k in ["total_crude_stocks","gasoline_stocks","distillate_stocks"])
    demand = sum(result[k]["value"] or 0 for k in ["gasoline_demand","distillate_demand"])
    result["days_cover"] = round(total / demand, 1) if demand else None

    # Net supply balance
    prod = result.get("crude_production", {}).get("value") or 0
    imp  = result.get("crude_imports",    {}).get("value") or 0
    exp  = result.get("crude_exports",    {}).get("value") or 0
    result["net_supply_mbd"] = round(prod + imp - exp, 2)

    # Composite bull/bear score
    score = 0
    if result.get("cushing_stocks", {}).get("wow") is not None:
        score += -1 if result["cushing_stocks"]["wow"] < -1 else (1 if result["cushing_stocks"]["wow"] > 1 else 0)
    for key in ["cushing_stocks", "total_crude_stocks", "distillate_stocks"]:
        dev = result.get(key, {}).get("vs_5yr_avg")
        if dev is not None:
            score += 1 if dev < 0 else -1
    dc = result.get("days_cover")
    if dc:
        score += 2 if dc < 54 else (-2 if dc > 62 else 0)
    result["composite_score"] = score
    result["composite_signal"] = "BULLISH" if score >= 2 else ("BEARISH" if score <= -2 else "NEUTRAL")

    # Cache result
    CACHE[cache_key] = {"ts": now, "data": result}

    # Save raw to file
    os.makedirs("backend/data", exist_ok=True)
    with open("backend/data/eia_latest.json", "w") as f:
        json.dump(result, f, indent=2, default=str)

    return result


if __name__ == "__main__":
    import sys
    mock = "--mock" in sys.argv
    print(f"Fetching EIA data {'(mock)' if mock else '(live)'}...")
    data = fetch_all(mock=mock)
    print(f"\nComposite signal: {data['composite_signal']} ({data['composite_score']:+d})")
    print(f"Days of cover:    {data['days_cover']}d")
    print(f"Cushing WoW:      {data['cushing_stocks']['wow']:+.1f} mmbbls")
    print(f"Net supply:       {data['net_supply_mbd']} mbd")

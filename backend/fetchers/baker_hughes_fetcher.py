"""
Baker Hughes US Rig Count Fetcher
Source: FRED series OILRIGS (weekly, Friday release ~1PM EST)
Signal: Leading indicator for US shale production with 4-6 month lag
  > 600 rigs → shale growing 300-500 kbd/yr
  400-600    → roughly flat (treadmill)
  < 350      → production declining within 6 months
"""

import os, json, requests
from datetime import datetime, timezone

FRED_API_KEY = os.getenv("FRED_API_KEY", "1d73bedd4f0c41fe197581d267892389")
OUTPUT_PATH  = os.path.join(os.path.dirname(__file__), "../data/rig_count_latest.json")

SERIES = {
    "oil_rigs":   "OILRIGS",   # Baker Hughes oil-directed rig count
    "gas_rigs":   "GASRIGS",   # Gas rigs (context)
    "total_rigs": "RIGSTOTUS", # Total US rigs
}

THRESHOLDS = {
    "growing":  600,
    "flat_hi":  600,
    "flat_lo":  350,
    "declining": 350,
}


def fetch_series(series_id: str, limit: int = 10) -> list[dict]:
    """Fetch recent observations from FRED."""
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id":       series_id,
        "api_key":         FRED_API_KEY,
        "file_type":       "json",
        "sort_order":      "desc",
        "limit":           limit,
        "observation_start": "2020-01-01",
    }
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    obs = r.json().get("observations", [])
    # Filter out missing values
    return [o for o in obs if o["value"] not in (".", "")]


def signal_from_count(count: float) -> dict:
    """Derive directional signal from rig count level."""
    if count > THRESHOLDS["growing"]:
        return {"label": "GROWING", "direction": "bullish",
                "note": "Shale production likely growing 300-500 kbd in 4-6 months"}
    elif count > THRESHOLDS["flat_lo"]:
        return {"label": "FLAT",    "direction": "neutral",
                "note": "Shale on treadmill — flat production expected"}
    else:
        return {"label": "DECLINING", "direction": "bearish",
                "note": "Production decline likely within 6 months"}


def fetch_rig_count() -> dict:
    results = {}
    for key, series_id in SERIES.items():
        try:
            obs = fetch_series(series_id, limit=52)  # ~1 year of weekly data
            if not obs:
                results[key] = {"error": "no data"}
                continue

            latest     = obs[0]
            prev_week  = obs[1] if len(obs) > 1 else None
            prev_year  = obs[51] if len(obs) > 51 else None

            current_val = float(latest["value"])
            wow = round(current_val - float(prev_week["value"]), 0) if prev_week else None
            yoy = round(current_val - float(prev_year["value"]), 0) if prev_year else None

            results[key] = {
                "value":       current_val,
                "date":        latest["date"],
                "wow_change":  wow,
                "yoy_change":  yoy,
                "history_52w": [
                    {"date": o["date"], "value": float(o["value"])}
                    for o in reversed(obs)
                ],
            }
        except Exception as e:
            results[key] = {"error": str(e)}

    # Derive signal from oil rig count (the key one)
    oil_data = results.get("oil_rigs", {})
    signal   = {}
    if "value" in oil_data:
        signal = signal_from_count(oil_data["value"])
        signal["production_lag_months"] = "4-6"
        signal["wow_change"] = oil_data.get("wow_change")
        signal["yoy_change"] = oil_data.get("yoy_change")

    output = {
        "fetched_at":   datetime.now(timezone.utc).isoformat(),
        "source":       "FRED / Baker Hughes via St. Louis Fed",
        "series":       results,
        "signal":       signal,
        "thresholds":   THRESHOLDS,
        "notes": {
            "lag":       "4-6 month lag from rig count change to production change",
            "efficiency":"Fewer rigs needed per barrel vs 2014 (efficiency gains)",
            "peak":      "1,609 rigs Oct 2014 | low: 172 rigs Aug 2020",
            "current_range": "~480-520 rigs (2024 baseline)",
        }
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    print(f"[rig_count] Oil rigs: {oil_data.get('value')} | "
          f"WoW: {oil_data.get('wow_change'):+.0f} | "
          f"Signal: {signal.get('label')}")
    return output


if __name__ == "__main__":
    if not FRED_API_KEY:
        raise EnvironmentError("FRED_API_KEY not set")
    fetch_rig_count()
def run():
    fetch_rig_count()

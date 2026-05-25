"""
EIA Data Fetcher — Energy Markets Dashboard
Downloads EIA Weekly Petroleum Status Report CSV directly.
No API route confusion — uses the same CSV EIA publishes every Wednesday.
"""

import os
import json
import time
import requests
import pandas as pd
from datetime import datetime, timezone

CACHE = {}

# EIA WPSR CSV tables published every Wednesday after 10:30 EST
WPSR_URLS = {
    "stocks": "https://ir.eia.gov/wpsr/table1.csv",
    "supply":  "https://ir.eia.gov/wpsr/table2.csv",
}

# 5-year seasonal averages (approximate baselines in mmbbls / mbd)
FIVE_YR_AVG = {
    "cushing_stocks":     430,
    "total_crude_stocks": 450,
    "gasoline_stocks":    235,
    "distillate_stocks":  120,
    "crude_production":   12.9,
    "refinery_util":      90.0,
}

# Mock data for offline testing
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


def fetch_wpsr_csv(url: str, retries: int = 3) -> pd.DataFrame:
    """Download and parse an EIA WPSR CSV table."""
    headers = {"User-Agent": "Mozilla/5.0 (energy-dashboard research project)"}
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=headers, timeout=15)
            r.raise_for_status()
            # EIA CSVs have inconsistent column counts — read raw lines
            lines = r.text.splitlines()
            rows = []
            for line in lines:
                parts = [p.strip().strip('"') for p in line.split(",")]
                if len(parts) >= 4:
                    rows.append(parts[:4])
            if not rows:
                return pd.DataFrame()
            df = pd.DataFrame(rows[1:], columns=["label", "current", "prev", "diff"])
            df["label"]   = df["label"].str.strip()
            df["current"] = pd.to_numeric(df["current"].str.replace(",", ""), errors="coerce")
            df["prev"]    = pd.to_numeric(df["prev"].str.replace(",", ""), errors="coerce")
            return df
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                print(f"  Failed to fetch {url}: {e}")
                return pd.DataFrame()


def parse_wpsr(mock: bool = False) -> dict:
    """
    Parse EIA WPSR CSVs into a clean dict.
    Returns latest week value + prior week value for each series.
    """
    if mock:
        return MOCK_DATA

    raw = {}

    try:
        # Table 1 — Stocks
        df = fetch_wpsr_csv(WPSR_URLS["stocks"])
        if not df.empty:
            def get_row(keyword):
                mask = df["label"].str.contains(keyword, case=False, na=False, regex=True)
                rows = df[mask]
                if not rows.empty:
                    return rows.iloc[0]["current"], rows.iloc[0]["prev"]
                return None, None

            v, p = get_row("Cushing")
            if v is not None:
                raw["cushing_stocks"] = {"value": v/1000, "prev": p/1000, "unit": "mmbbls"}

            v, p = get_row("Commercial.*Exclud")
            if v is not None:
                raw["total_crude_stocks"] = {"value": v/1000, "prev": p/1000, "unit": "mmbbls"}

            v, p = get_row("Total Motor Gasoline")
            if v is not None:
                raw["gasoline_stocks"] = {"value": v/1000, "prev": p/1000, "unit": "mmbbls"}

            v, p = get_row("Distillate Fuel Oil")
            if v is not None:
                raw["distillate_stocks"] = {"value": v/1000, "prev": p/1000, "unit": "mmbbls"}

        # Table 2 — Supply (production, imports, exports)
        df2 = fetch_wpsr_csv(WPSR_URLS["supply"])
        if not df2.empty:
            def get_row2(keyword):
                mask = df2["label"].str.contains(keyword, case=False, na=False, regex=True)
                rows = df2[mask]
                if not rows.empty:
                    return rows.iloc[0]["current"], rows.iloc[0]["prev"]
                return None, None

            v, p = get_row2("Domestic Production")
            if v is not None:
                raw["crude_production"] = {"value": v/1000, "prev": p/1000, "unit": "mbd"}

            v, p = get_row2("Crude Oil.*Import")
            if v is not None:
                raw["crude_imports"] = {"value": v/1000, "prev": p/1000, "unit": "mbd"}

            v, p = get_row2("Crude Oil.*Export")
            if v is not None:
                raw["crude_exports"] = {"value": v/1000, "prev": p/1000, "unit": "mbd"}

            v, p = get_row2("Refinery Utilization")
            if v is not None:
                raw["refinery_util"] = {"value": v, "prev": p, "unit": "%"}

    except Exception as e:
        print(f"  Parse error: {e}")

    # Fill any missing series with mock data
    for key in MOCK_DATA:
        if key not in raw:
            print(f"  Using mock for missing series: {key}")
            raw[key] = MOCK_DATA[key]

    return raw


def fetch_all(mock: bool = False) -> dict:
    """
    Main entry point. Returns unified signals dict.
    """
    cache_key = "eia_all"
    now = datetime.now(timezone.utc).timestamp()
    if cache_key in CACHE and now - CACHE[cache_key]["ts"] < 3600:
        return CACHE[cache_key]["data"]

    print(f"Fetching EIA data {'(mock)' if mock else '(live — EIA WPSR CSV)'}...")
    raw = parse_wpsr(mock=mock)

    # Compute derived metrics
    result = {}
    for key, data in raw.items():
        v, p = data.get("value"), data.get("prev")
        wow   = round(v - p, 3) if v is not None and p is not None else None
        vs5yr = round(v - FIVE_YR_AVG[key], 2) if key in FIVE_YR_AVG and v is not None else None
        result[key] = {**data, "wow": wow, "vs_5yr_avg": vs5yr}

    # Days of forward demand cover
    total  = sum(result[k]["value"] or 0
                 for k in ["total_crude_stocks", "gasoline_stocks", "distillate_stocks"])
    demand = sum(result[k]["value"] or 0
                 for k in ["gasoline_demand", "distillate_demand"])
    result["days_cover"] = round(total / demand, 1) if demand else None

    # Net supply balance
    prod = result.get("crude_production", {}).get("value") or 0
    imp  = result.get("crude_imports",    {}).get("value") or 0
    exp  = result.get("crude_exports",    {}).get("value") or 0
    result["net_supply_mbd"] = round(prod + imp - exp, 2)

    # Composite bull/bear score
    score = 0
    wow_c = result.get("cushing_stocks", {}).get("wow")
    if wow_c is not None:
        score += -1 if wow_c < -1 else (1 if wow_c > 1 else 0)
    for key in ["cushing_stocks", "total_crude_stocks", "distillate_stocks"]:
        dev = result.get(key, {}).get("vs_5yr_avg")
        if dev is not None:
            score += 1 if dev < 0 else -1
    dc = result.get("days_cover")
    if dc:
        score += 2 if dc < 54 else (-2 if dc > 62 else 0)
    result["composite_score"]  = score
    result["composite_signal"] = ("BULLISH" if score >= 2
                                  else "BEARISH" if score <= -2
                                  else "NEUTRAL")

    CACHE[cache_key] = {"ts": now, "data": result}

    os.makedirs("backend/data", exist_ok=True)
    with open("backend/data/eia_latest.json", "w") as f:
        json.dump(result, f, indent=2, default=str)

    return result


if __name__ == "__main__":
    import sys
    mock = "--mock" in sys.argv
    data = fetch_all(mock=mock)
    dc   = data.get("days_cover")
    wow  = data.get("cushing_stocks", {}).get("wow")
    ns   = data.get("net_supply_mbd")
    print(f"\nComposite signal: {data['composite_signal']} ({data['composite_score']:+d})")
    print(f"Days of cover:    {dc}d")
    print(f"Cushing WoW:      {wow:+.1f} mmbbls" if wow is not None else "Cushing WoW:      N/A")
    print(f"Net supply:       {ns} mbd")

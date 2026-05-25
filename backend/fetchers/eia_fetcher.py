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
from io import StringIO
from datetime import datetime, timezone

CACHE = {}

# EIA WPSR CSV tables published every Wednesday after 10:30 EST
WPSR_URLS = {
    "stocks": "https://www.eia.gov/petroleum/supply/weekly/csv/table1.csv",
    "supply":  "https://www.eia.gov/petroleum/supply/weekly/csv/table2.csv",
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
            # EIA CSVs have a few header rows to skip
            df = pd.read_csv(StringIO(r.text), skiprows=4, header=0)
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
            # EIA table 1 columns: Description, Current Week, Week Ago, Year Ago
            # Row names contain the series labels
            df.columns = [str(c).strip() for c in df.columns]
            df.iloc[:, 0] = df.iloc[:, 0].astype(str).str.strip()

            def get_row(keyword):
                mask = df.iloc[:, 0].str.contains(keyword, case=False, na=False)
                rows = df[mask]
                return rows.iloc[0] if not rows.empty else None

            # Cushing crude stocks (million barrels)
            row = get_row("Cushing")
            if row is not None:
                raw["cushing_stocks"] = {
                    "value": float(str(row.iloc[1]).replace(",", "")) / 1000,
                    "prev":  float(str(row.iloc[2]).replace(",", "")) / 1000,
                    "unit":  "mmbbls"
                }

            # Total commercial crude stocks
            row = get_row("Commercial.*Excluding SPR")
            if row is None:
                row = get_row("Crude Oil.*Excluding")
            if row is not None:
                raw["total_crude_stocks"] = {
                    "value": float(str(row.iloc[1]).replace(",", "")) / 1000,
                    "prev":  float(str(row.iloc[2]).replace(",", "")) / 1000,
                    "unit":  "mmbbls"
                }

            # Gasoline stocks
            row = get_row("Total Motor Gasoline")
            if row is not None:
                raw["gasoline_stocks"] = {
                    "value": float(str(row.iloc[1]).replace(",", "")) / 1000,
                    "prev":  float(str(row.iloc[2]).replace(",", "")) / 1000,
                    "unit":  "mmbbls"
                }

            # Distillate stocks
            row = get_row("Distillate Fuel Oil")
            if row is not None:
                raw["distillate_stocks"] = {
                    "value": float(str(row.iloc[1]).replace(",", "")) / 1000,
                    "prev":  float(str(row.iloc[2]).replace(",", "")) / 1000,
                    "unit":  "mmbbls"
                }

        # Table 2 — Supply (production, imports, exports)
        df2 = fetch_wpsr_csv(WPSR_URLS["supply"])
        if not df2.empty:
            df2.columns = [str(c).strip() for c in df2.columns]
            df2.iloc[:, 0] = df2.iloc[:, 0].astype(str).str.strip()

            def get_row2(keyword):
                mask = df2.iloc[:, 0].str.contains(keyword, case=False, na=False)
                rows = df2[mask]
                return rows.iloc[0] if not rows.empty else None

            # Crude production (mbd)
            row = get_row2("Domestic Production")
            if row is not None:
                raw["crude_production"] = {
                    "value": float(str(row.iloc[1]).replace(",", "")) / 1000,
                    "prev":  float(str(row.iloc[2]).replace(",", "")) / 1000,
                    "unit":  "mbd"
                }

            # Crude imports
            row = get_row2("Total Crude Oil.*Import")
            if row is None:
                row = get_row2("Crude Oil Import")
            if row is not None:
                raw["crude_imports"] = {
                    "value": float(str(row.iloc[1]).replace(",", "")) / 1000,
                    "prev":  float(str(row.iloc[2]).replace(",", "")) / 1000,
                    "unit":  "mbd"
                }

            # Crude exports
            row = get_row2("Crude Oil.*Export")
            if row is not None:
                raw["crude_exports"] = {
                    "value": float(str(row.iloc[1]).replace(",", "")) / 1000,
                    "prev":  float(str(row.iloc[2]).replace(",", "")) / 1000,
                    "unit":  "mbd"
                }

            # Refinery utilisation
            row = get_row2("Refinery Utilization")
            if row is not None:
                raw["refinery_util"] = {
                    "value": float(str(row.iloc[1]).replace(",", "")),
                    "prev":  float(str(row.iloc[2]).replace(",", "")),
                    "unit":  "%"
                }

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

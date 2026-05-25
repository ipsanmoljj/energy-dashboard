"""
EIA Data Fetcher — Energy Markets Dashboard
Downloads EIA Weekly Petroleum Status Report CSVs directly.
Published every Wednesday after 10:30 AM EST.
"""

import os
import json
import time
import requests
import re
import pandas as pd
from datetime import datetime, timezone

CACHE = {}

WPSR_URLS = {
    "stocks":  "https://ir.eia.gov/wpsr/table1.csv",
    "regions": "https://ir.eia.gov/wpsr/table4.csv",
}

FIVE_YR_AVG = {
    "cushing_stocks":     27.0,
    "total_crude_stocks": 450.0,
    "gasoline_stocks":    235.0,
    "distillate_stocks":  120.0,
    "crude_production":   13.2,
    "refinery_util":      90.0,
}

MOCK_DATA = {
    "cushing_stocks":     {"value": 25.8,  "prev": 27.4,  "unit": "mmbbls"},
    "total_crude_stocks": {"value": 445.0, "prev": 452.9, "unit": "mmbbls"},
    "gasoline_stocks":    {"value": 214.2, "prev": 215.7, "unit": "mmbbls"},
    "distillate_stocks":  {"value": 102.9, "prev": 102.5, "unit": "mmbbls"},
    "crude_production":   {"value": 13.7,  "prev": 13.7,  "unit": "mbd"},
    "refinery_util":      {"value": 91.4,  "prev": 90.8,  "unit": "%"},
    "gasoline_demand":    {"value": 8.9,   "prev": 8.7,   "unit": "mbd"},
    "distillate_demand":  {"value": 3.8,   "prev": 4.0,   "unit": "mbd"},
    "crude_exports":      {"value": 4.2,   "prev": 3.9,   "unit": "mbd"},
    "crude_imports":      {"value": 6.1,   "prev": 6.3,   "unit": "mbd"},
}


def fetch_csv(url: str, retries: int = 3) -> pd.DataFrame:
    """Fetch EIA CSV and parse into label/current/prev columns."""
    headers = {"User-Agent": "Mozilla/5.0 (energy-dashboard)"}
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=headers, timeout=15)
            r.raise_for_status()
            rows = []
            for line in r.text.splitlines():
                parts = [p.strip().strip('"') for p in line.split(",")]
                if len(parts) >= 3:
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


def get_val(df: pd.DataFrame, keyword: str):
    """Return (current, prev) for first row matching keyword."""
    mask = df["label"].str.contains(keyword, case=False, na=False, regex=True)
    rows = df[mask]
    if not rows.empty:
        return rows.iloc[0]["current"], rows.iloc[0]["prev"]
    return None, None


def parse_wpsr(mock: bool = False) -> dict:
    if mock:
        return MOCK_DATA

    raw = {}
    headers = {"User-Agent": "Mozilla/5.0 (energy-dashboard)"}

    # ── Table 1: stocks + supply/demand ─────────────────────────────────────
    try:
        r = requests.get(WPSR_URLS["stocks"], headers=headers, timeout=15)
        r.raise_for_status()
        lines = r.text.splitlines()

        # Section A: single label (stocks) — before STUB_2
        # Section B: two labels (supply) — after STUB_2
        section_a = []
        section_b = []
        in_b = False
        for line in lines:
            if "STUB_2" in line:
                in_b = True
                continue
            parts = [p.strip().strip('"') for p in line.split(",")]
            if in_b:
                if len(parts) >= 4:
                    section_b.append(parts)
            else:
                if len(parts) >= 3:
                    section_a.append(parts)

        # Section A — stocks already in million barrels
        def find_a(keyword):
            for row in section_a:
                if re.search(keyword, row[0], re.IGNORECASE):
                    try:
                        return float(row[1].replace(",", "")), float(row[2].replace(",", ""))
                    except Exception:
                        pass
            return None, None

        v, p = find_a("Commercial.*Exclud")
        if v is not None:
            raw["total_crude_stocks"] = {"value": v, "prev": p, "unit": "mmbbls"}

        v, p = find_a("Total Motor Gasoline")
        if v is not None:
            raw["gasoline_stocks"] = {"value": v, "prev": p, "unit": "mmbbls"}

        v, p = find_a("Distillate Fuel Oil")
        if v is not None:
            raw["distillate_stocks"] = {"value": v, "prev": p, "unit": "mmbbls"}

        # Section B — supply in kbd, divide by 1000 for mbd
        def find_b(keyword):
            for row in section_b:
                label = row[1] if len(row) > 1 else ""
                if re.search(keyword, label, re.IGNORECASE):
                    try:
                        return float(row[2].replace(",", "")), float(row[3].replace(",", ""))
                    except Exception:
                        pass
            return None, None

        v, p = find_b(r"\(1\).*Domestic Production")
        if v is not None:
            raw["crude_production"] = {"value": round(v/1000, 3), "prev": round(p/1000, 3), "unit": "mbd"}

        v, p = find_b(r"\(8\).*Imports$")
        if v is not None:
            raw["crude_imports"] = {"value": round(v/1000, 3), "prev": round(p/1000, 3), "unit": "mbd"}

        v, p = find_b(r"\(12\).*Exports")
        if v is not None:
            raw["crude_exports"] = {"value": round(v/1000, 3), "prev": round(p/1000, 3), "unit": "mbd"}

        # Scan all lines for refinery util + product supplied
        def scan_all(keyword):
            for line in lines:
                if re.search(keyword, line, re.IGNORECASE):
                    parts = [p.strip().strip('"') for p in line.split(",")]
                    nums = []
                    for part in parts:
                        try:
                            nums.append(float(part.replace(",", "")))
                        except Exception:
                            pass
                        if len(nums) == 2:
                            break
                    if len(nums) == 2:
                        return nums[0], nums[1]
            return None, None

        v, p = scan_all("Utilization Rate")
        if v is not None:
            raw["refinery_util"] = {"value": v, "prev": p, "unit": "%"}

        v, p = scan_all(r"\(31\).*Finished Motor Gasoline")
        if v is not None:
            raw["gasoline_demand"] = {"value": round(v/1000, 3), "prev": round(p/1000, 3), "unit": "mbd"}

        v, p = scan_all(r"\(33\).*Distillate")
        if v is not None:
            raw["distillate_demand"] = {"value": round(v/1000, 3), "prev": round(p/1000, 3), "unit": "mbd"}

    except Exception as e:
        print(f"  Table1 parse error: {e}")

    # ── Table 4: regional stocks — Cushing ──────────────────────────────────
    try:
        df4 = fetch_csv(WPSR_URLS["regions"])
        if not df4.empty:
            v, p = get_val(df4, "^Cushing$")
            if v is not None:
                raw["cushing_stocks"] = {"value": v, "prev": p, "unit": "mmbbls"}
    except Exception as e:
        print(f"  Table4 parse error: {e}")

    # Fill missing with mock
    for key in MOCK_DATA:
        if key not in raw:
            print(f"  Using mock for missing series: {key}")
            raw[key] = MOCK_DATA[key]

    return raw
    
def fetch_all(mock: bool = False) -> dict:
    cache_key = "eia_all"
    now = datetime.now(timezone.utc).timestamp()
    if cache_key in CACHE and now - CACHE[cache_key]["ts"] < 3600:
        return CACHE[cache_key]["data"]

    print(f"Fetching EIA data {'(mock)' if mock else '(live — EIA WPSR CSV)'}...")
    raw = parse_wpsr(mock=mock)

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

    # Net supply
    prod = result.get("crude_production", {}).get("value") or 0
    imp  = result.get("crude_imports",    {}).get("value") or 0
    exp  = result.get("crude_exports",    {}).get("value") or 0
    result["net_supply_mbd"] = round(prod + imp - exp, 2)

    # Composite score
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
    print(f"\nKey live values:")
    for k in ["cushing_stocks","total_crude_stocks","gasoline_stocks",
              "distillate_stocks","crude_production","refinery_util"]:
        v = data.get(k, {}).get("value")
        u = data.get(k, {}).get("unit")
        w = data.get(k, {}).get("wow")
        print(f"  {k:<22} {v} {u}  (WoW: {w:+.3f})" if w is not None else f"  {k:<22} {v} {u}")

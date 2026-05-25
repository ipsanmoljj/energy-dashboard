"""
EIA Data Fetcher — Energy Markets Dashboard
Downloads EIA Weekly Petroleum Status Report CSVs directly.
Published every Wednesday after 10:30 AM EST at ir.eia.gov/wpsr/
"""

import os
import re
import json
import time
import requests
import pandas as pd
from datetime import datetime, timezone

CACHE = {}

WPSR_URLS = {
    "table1":  "https://ir.eia.gov/wpsr/table1.csv",
    "table2":  "https://ir.eia.gov/wpsr/table2.csv",
    "table4":  "https://ir.eia.gov/wpsr/table4.csv",
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
    "refinery_util":      {"value": 91.6,  "prev": 91.7,  "unit": "%"},
    "gasoline_demand":    {"value": 8.767, "prev": 8.754, "unit": "mbd"},
    "distillate_demand":  {"value": 3.552, "prev": 3.428, "unit": "mbd"},
    "crude_exports":      {"value": 5.604, "prev": 5.492, "unit": "mbd"},
    "crude_imports":      {"value": 6.016, "prev": 5.901, "unit": "mbd"},
}


def fetch_raw_lines(url: str, retries: int = 3) -> list:
    headers = {"User-Agent": "Mozilla/5.0 (energy-dashboard)"}
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=headers, timeout=15)
            r.raise_for_status()
            return r.text.splitlines()
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                print(f"  Failed to fetch {url}: {e}")
                return []


def parse_quoted_line(line: str) -> list:
    """
    Split a quoted CSV line correctly.
    Splits on '","' so numbers like "13,702" stay intact inside quotes.
    Strips leading/trailing quotes from the whole line first.
    """
    line = line.strip()
    if line.startswith('"'):
        line = line[1:]
    if line.endswith('"'):
        line = line[:-1]
    return [p.strip() for p in line.split('","')]


def to_float(s: str):
    try:
        return float(s.replace(",", "").strip())
    except Exception:
        return None


def find_in_lines(lines: list, keyword: str, col_current: int, col_prev: int):
    """
    Search lines for keyword regex, return (current, prev) from specified columns.
    Uses parse_quoted_line so comma-in-numbers are handled correctly.
    """
    for line in lines:
        if re.search(keyword, line, re.IGNORECASE):
            parts = parse_quoted_line(line)
            if len(parts) > max(col_current, col_prev):
                v = to_float(parts[col_current])
                p = to_float(parts[col_prev])
                if v is not None and p is not None:
                    return v, p
    return None, None


def parse_wpsr(mock: bool = False) -> dict:
    if mock:
        return MOCK_DATA

    raw = {}

    # ── TABLE 1 ─────────────────────────────────────────────────────────────
    lines1 = fetch_raw_lines(WPSR_URLS["table1"])
    if lines1:
        section_a, section_b = [], []
        in_b = False
        for line in lines1:
            if "STUB_2" in line:
                in_b = True
                continue
            if in_b:
                section_b.append(line)
            else:
                section_a.append(line)

        # Section A — stocks (mmbbls, no conversion needed)
        # col0=label, col1=current, col2=prev
        v, p = find_in_lines(section_a, "Commercial.*Exclud", 1, 2)
        if v: raw["total_crude_stocks"] = {"value": v, "prev": p, "unit": "mmbbls"}

        v, p = find_in_lines(section_a, "Total Motor Gasoline", 1, 2)
        if v: raw["gasoline_stocks"] = {"value": v, "prev": p, "unit": "mmbbls"}

        v, p = find_in_lines(section_a, "Distillate Fuel Oil", 1, 2)
        if v: raw["distillate_stocks"] = {"value": v, "prev": p, "unit": "mmbbls"}

        # Section B — supply (kbd → mbd, divide by 1000)
        # col0=category, col1=label, col2=current, col3=prev
        v, p = find_in_lines(section_b, r"\(1\).*Domestic Production", 2, 3)
        if v: raw["crude_production"] = {"value": round(v/1000, 3), "prev": round(p/1000, 3), "unit": "mbd"}

        v, p = find_in_lines(section_b, r"\(8\).*Imports", 2, 3)
        if v: raw["crude_imports"] = {"value": round(v/1000, 3), "prev": round(p/1000, 3), "unit": "mbd"}

        v, p = find_in_lines(section_b, r"\(12\).*Exports", 2, 3)
        if v: raw["crude_exports"] = {"value": round(v/1000, 3), "prev": round(p/1000, 3), "unit": "mbd"}

        v, p = find_in_lines(section_b, r"\(31\).*Finished Motor Gasoline", 2, 3)
        if v: raw["gasoline_demand"] = {"value": round(v/1000, 3), "prev": round(p/1000, 3), "unit": "mbd"}

        v, p = find_in_lines(section_b, r"\(33\).*Distillate Fuel Oil", 2, 3)
        if v: raw["distillate_demand"] = {"value": round(v/1000, 3), "prev": round(p/1000, 3), "unit": "mbd"}

    # ── TABLE 2: refinery utilization ───────────────────────────────────────
    # col0=category, col1=label, col2=current, col3=prev
    lines2 = fetch_raw_lines(WPSR_URLS["table2"])
    if lines2:
        v, p = find_in_lines(lines2, "Percent Utilization", 2, 3)
        if v: raw["refinery_util"] = {"value": v, "prev": p, "unit": "%"}

    # ── TABLE 4: Cushing stocks ──────────────────────────────────────────────
    # col0=label, col1=current, col2=prev
    lines4 = fetch_raw_lines(WPSR_URLS["table4"])
    if lines4:
        v, p = find_in_lines(lines4, r"Cushing", 1, 2)
        if v: raw["cushing_stocks"] = {"value": v, "prev": p, "unit": "mmbbls"}

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

    total  = sum(result[k]["value"] or 0
                 for k in ["total_crude_stocks", "gasoline_stocks", "distillate_stocks"])
    demand = sum(result[k]["value"] or 0
                 for k in ["gasoline_demand", "distillate_demand"])
    result["days_cover"] = round(total / demand, 1) if demand else None

    prod = result.get("crude_production", {}).get("value") or 0
    imp  = result.get("crude_imports",    {}).get("value") or 0
    exp  = result.get("crude_exports",    {}).get("value") or 0
    result["net_supply_mbd"] = round(prod + imp - exp, 2)

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

    dc  = data.get("days_cover")
    wow = data.get("cushing_stocks", {}).get("wow")
    ns  = data.get("net_supply_mbd")

    print(f"\nComposite signal: {data['composite_signal']} ({data['composite_score']:+d})")
    print(f"Days of cover:    {dc}d")
    print(f"Cushing WoW:      {wow:+.3f} mmbbls" if wow is not None else "Cushing WoW: N/A")
    print(f"Net supply:       {ns} mbd")
    print(f"\nAll series:")
    for k in ["cushing_stocks", "total_crude_stocks", "gasoline_stocks",
              "distillate_stocks", "crude_production", "refinery_util",
              "gasoline_demand", "distillate_demand", "crude_imports", "crude_exports"]:
        d = data.get(k, {})
        v = d.get("value")
        u = d.get("unit", "")
        w = d.get("wow")
        s = d.get("vs_5yr_avg")
        wow_s = f"WoW:{w:+.3f}" if w is not None else "WoW:N/A"
        v5_s  = f"vs5yr:{s:+.2f}" if s is not None else ""
        print(f"  {k:<24} {str(v):<10} {u:<8} {wow_s}  {v5_s}")

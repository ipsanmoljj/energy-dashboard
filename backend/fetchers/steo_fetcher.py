"""
steo_fetcher.py
----------------
Fetches EIA Short-Term Energy Outlook (STEO) global supply/demand balance data.

STEO is published ~2nd week of each month and is a SEPARATE data source from the
weekly WPSR (handled by eia_fetcher.py). Treat as monthly, not weekly, cadence.

Series fetched (all monthly, million barrels/day unless noted):
  PAPR_WORLD   - World petroleum & other liquids production
  PATC_WORLD   - World petroleum & other liquids consumption
  PAPR_OPEC    - OPEC petroleum & other liquids production
  PAPR_NONOPEC - Non-OPEC petroleum & other liquids production
  PASC_OPEC    - OPEC spare capacity (if available under this ID; verified at runtime)
  COPR_OPEC    - "Call on OPEC" if EIA publishes it directly under this series id

Because EIA sometimes renames/retires STEO series IDs between report vintages,
this fetcher is defensive: each series is fetched independently, failures are
logged per-series (not fatal), and the output JSON marks any missing series as
INSUFFICIENT_DATA rather than fabricating a number. This follows the same
principle already used elsewhere in the dashboard (Brent/WTI independence rule).

Output: backend/data/steo_latest.json
History: backend/data/steo_history.json  (append-only, one row per fetch run)

IMPORTANT EIA API QUIRK (established pattern from eia_fetcher.py / seasonality_fetcher.py):
  Always request sort direction=desc, then re-sort ascending in Python.
  asc returns OLDEST data first and truncates recent history under the row limit.

Usage:
  python backend/fetchers/steo_fetcher.py
"""

import os
import json
import time
from pathlib import Path
from datetime import datetime, timezone

import requests

ROOT = Path(__file__).resolve().parent.parent   # backend/
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

LATEST_PATH = DATA_DIR / "steo_latest.json"
HISTORY_PATH = DATA_DIR / "steo_history.json"

EIA_API_KEY = os.environ.get("EIA_API_KEY")
BASE_URL = "https://api.eia.gov/v2/steo/data/"

SERIES = {
    "PAPR_WORLD":   "World production",
    "PATC_WORLD":   "World consumption",
    "PAPR_OPEC":    "OPEC production",
    "PAPR_NONOPEC": "Non-OPEC production",
    "PASC_OPEC":    "OPEC spare capacity",
    "COPR_OPEC":    "Call on OPEC (EIA-published)",
}

REQUEST_TIMEOUT = 30
RETRY_COUNT = 2
RETRY_SLEEP = 3


def _fetch_series(series_id: str) -> list:
    if not EIA_API_KEY:
        print(f"  [{series_id}] SKIPPED — EIA_API_KEY not set in environment")
        return []

    params = {
        "api_key": EIA_API_KEY,
        "frequency": "monthly",
        "data[0]": "value",
        "facets[seriesId][]": series_id,
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "length": 60,
    }

    last_err = None
    for attempt in range(1, RETRY_COUNT + 2):
        try:
            resp = requests.get(BASE_URL, params=params, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 404:
                print(f"  [{series_id}] 404 — series ID not valid in current STEO vintage")
                return []
            resp.raise_for_status()
            payload = resp.json()
            rows = payload.get("response", {}).get("data", [])
            if not rows:
                print(f"  [{series_id}] returned 0 rows")
                return []

            out = []
            for r in rows:
                try:
                    out.append({
                        "period": r["period"],
                        "value": float(r["value"]),
                    })
                except (KeyError, TypeError, ValueError):
                    continue

            out.sort(key=lambda x: x["period"])
            print(f"  [{series_id}] OK — {len(out)} monthly points, latest={out[-1]['period']}")
            return out

        except requests.exceptions.RequestException as e:
            last_err = e
            if attempt <= RETRY_COUNT:
                print(f"  [{series_id}] attempt {attempt} failed ({e}); retrying in {RETRY_SLEEP}s")
                time.sleep(RETRY_SLEEP)
            else:
                print(f"  [{series_id}] FAILED after {RETRY_COUNT + 1} attempts: {last_err}")
                return []

    return []


def _pct_change(curr, prev):
    if prev == 0 or prev is None:
        return None
    return round((curr - prev) / abs(prev) * 100, 2)


def build_balance(series_data: dict) -> dict:
    world_prod = series_data.get("PAPR_WORLD", [])
    world_cons = series_data.get("PATC_WORLD", [])
    opec_prod = series_data.get("PAPR_OPEC", [])
    nonopec_prod = series_data.get("PAPR_NONOPEC", [])
    spare_cap = series_data.get("PASC_OPEC", [])
    call_published = series_data.get("COPR_OPEC", [])

    def latest(series):
        return series[-1] if series else None

    def prior_month(series):
        return series[-2] if len(series) >= 2 else None

    wp_latest, wc_latest = latest(world_prod), latest(world_cons)
    wp_prior, wc_prior = prior_month(world_prod), prior_month(world_cons)

    result = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "report_period_latest": None,
        "world_production_mbd": None,
        "world_consumption_mbd": None,
        "global_balance_mbd": None,
        "global_balance_signal": "INSUFFICIENT_DATA",
        "production_mom_change_mbd": None,
        "consumption_mom_change_mbd": None,
        "production_mom_pct": None,
        "consumption_mom_pct": None,
        "call_on_opec_mbd": None,
        "call_on_opec_method": None,
        "opec_actual_production_mbd": None,
        "opec_vs_call_mbd": None,
        "opec_balance_signal": "INSUFFICIENT_DATA",
        "spare_capacity_mbd": None,
        "revision_note": None,
    }

    if wp_latest and wc_latest:
        result["report_period_latest"] = wp_latest["period"]
        result["world_production_mbd"] = wp_latest["value"]
        result["world_consumption_mbd"] = wc_latest["value"]
        balance = round(wp_latest["value"] - wc_latest["value"], 3)
        result["global_balance_mbd"] = balance
        if balance > 0.15:
            result["global_balance_signal"] = "BUILD (oversupplied) — bearish"
        elif balance < -0.15:
            result["global_balance_signal"] = "DRAW (undersupplied) — bullish"
        else:
            result["global_balance_signal"] = "BALANCED — neutral"

    if wp_latest and wp_prior:
        result["production_mom_change_mbd"] = round(wp_latest["value"] - wp_prior["value"], 3)
        result["production_mom_pct"] = _pct_change(wp_latest["value"], wp_prior["value"])
    if wc_latest and wc_prior:
        result["consumption_mom_change_mbd"] = round(wc_latest["value"] - wc_prior["value"], 3)
        result["consumption_mom_pct"] = _pct_change(wc_latest["value"], wc_prior["value"])

    call_val = None
    if call_published:
        cp_latest = latest(call_published)
        call_val = cp_latest["value"]
        result["call_on_opec_method"] = "eia_published"
    elif wc_latest and nonopec_prod:
        np_latest = latest(nonopec_prod)
        if np_latest["period"] == wc_latest["period"]:
            call_val = round(wc_latest["value"] - np_latest["value"], 3)
            result["call_on_opec_method"] = "derived (world consumption - non-OPEC production)"

    if call_val is not None:
        result["call_on_opec_mbd"] = call_val
        if opec_prod:
            op_latest = latest(opec_prod)
            result["opec_actual_production_mbd"] = op_latest["value"]
            gap = round(op_latest["value"] - call_val, 3)
            result["opec_vs_call_mbd"] = gap
            if gap > 0.15:
                result["opec_balance_signal"] = "OPEC overproducing vs call — bearish"
            elif gap < -0.15:
                result["opec_balance_signal"] = "OPEC underproducing vs call — bullish"
            else:
                result["opec_balance_signal"] = "OPEC near call — neutral"

    if spare_cap:
        result["spare_capacity_mbd"] = latest(spare_cap)["value"]

    result["revision_note"] = (
        "Direction shown is month-over-month change in the latest STEO read. "
        "True 'revision' (this month's STEO restating a PRIOR period's number) "
        "requires storing each month's full vintage and diffing — see steo_history.json "
        "accumulation; revision tracking improves after 2+ months of history collected."
    )

    return result


def main():
    print(f"STEO fetcher starting — {datetime.now(timezone.utc).isoformat()}")

    series_data = {}
    for sid in SERIES:
        print(f"Fetching {sid} ({SERIES[sid]})...")
        series_data[sid] = _fetch_series(sid)

    balance = build_balance(series_data)

    balance["series_available"] = {
        sid: (len(series_data[sid]) > 0) for sid in SERIES
    }
    balance["series_labels"] = SERIES

    LATEST_PATH.write_text(json.dumps(balance, indent=2))
    print(f"Wrote {LATEST_PATH}")

    history = []
    if HISTORY_PATH.exists():
        try:
            history = json.loads(HISTORY_PATH.read_text())
        except json.JSONDecodeError:
            history = []

    today_str = datetime.now(timezone.utc).date().isoformat()
    history = [h for h in history if h.get("_fetch_date") != today_str]
    snapshot = dict(balance)
    snapshot["_fetch_date"] = today_str
    history.append(snapshot)
    HISTORY_PATH.write_text(json.dumps(history, indent=2))
    print(f"Appended snapshot to {HISTORY_PATH} ({len(history)} total snapshots)")

    print("STEO fetcher done.")

    print("\n--- Summary ---")
    print(f"Latest period:       {balance['report_period_latest']}")
    print(f"World production:    {balance['world_production_mbd']} mbd")
    print(f"World consumption:   {balance['world_consumption_mbd']} mbd")
    print(f"Global balance:      {balance['global_balance_mbd']} mbd  [{balance['global_balance_signal']}]")
    print(f"Call on OPEC:        {balance['call_on_opec_mbd']} mbd  (method: {balance['call_on_opec_method']})")
    print(f"OPEC actual prod:    {balance['opec_actual_production_mbd']} mbd")
    print(f"OPEC vs call:        {balance['opec_vs_call_mbd']} mbd  [{balance['opec_balance_signal']}]")
    print(f"Spare capacity:      {balance['spare_capacity_mbd']} mbd")


if __name__ == "__main__":
    main()
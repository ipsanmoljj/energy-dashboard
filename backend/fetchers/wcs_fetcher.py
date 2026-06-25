"""
backend/fetchers/wcs_fetcher.py
--------------------------------
Fetches live WTI, WCS prices and WTI-WCS differential from:
  https://api.economicdata.alberta.ca/data?table=OilPrices

Source: Government of Alberta Economic Dashboard
Frequency: Monthly (latest ~1-2 month lag)
History: From 1986

Writes: backend/data/wcs_latest.json

Also updates quality_spreads_latest.json and quality_spreads_history.json
with live WTI-WCS differential instead of fixed differential.
Backfills 36 months of history into quality_spreads_history.json on first run.
"""

from __future__ import annotations
import json
import logging
import requests
from datetime import datetime, timezone
from pathlib import Path

BASE     = Path(__file__).resolve().parents[1]
DATA_DIR = BASE / "data"
OUT      = DATA_DIR / "wcs_latest.json"

API_URL  = "https://api.economicdata.alberta.ca/data"
HEADERS  = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("wcs_fetcher")


def fetch_alberta_oil() -> list:
    """Fetch full OilPrices table from Alberta Economic Dashboard API."""
    try:
        r = requests.get(API_URL, params={"table": "OilPrices"},
                         headers=HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
        log.info("Fetched %d rows from Alberta API", len(data))
        return data
    except Exception as e:
        log.error("Failed to fetch Alberta oil data: %s", e)
        return []


def parse_series(data: list) -> dict:
    """Parse into WTI, WCS, Differential time series."""
    wti_series  = {}
    wcs_series  = {}
    diff_series = {}

    for row in data:
        date  = row.get("Date", "")[:10]  # YYYY-MM-DD
        rtype = row.get("Type ", "").strip()
        val   = row.get("Value")

        if val is None:
            continue

        if rtype == "WTI":
            wti_series[date] = round(float(val), 2)
        elif rtype == "WCS":
            wcs_series[date] = round(float(val), 2)
        elif rtype == "Differential":
            diff_series[date] = round(float(val), 2)

    return {"wti": wti_series, "wcs": wcs_series, "differential": diff_series}


def get_latest(series: dict) -> tuple:
    """Get latest non-null value and its date."""
    if not series:
        return None, None
    for date in sorted(series.keys(), reverse=True):
        val = series[date]
        if val is not None:
            return val, date
    return None, None


def compute_signal(differential: float | None) -> dict:
    """Signal logic for WTI-WCS differential."""
    if differential is None:
        return {"signal": "NO_DATA", "strength": 0, "interpretation": "No data"}

    if differential > 20:
        signal, strength = "BULLISH", 3
        interp = f"WTI-WCS at ${differential:.1f}/bbl — Alberta pipeline severely constrained, wide discount"
    elif differential > 15:
        signal, strength = "BULLISH", 2
        interp = f"WTI-WCS at ${differential:.1f}/bbl — Canadian heavy crude discounted, above historical avg"
    elif differential > 10:
        signal, strength = "NEUTRAL", 1
        interp = f"WTI-WCS at ${differential:.1f}/bbl — Normal range post-TMX expansion"
    elif differential > 5:
        signal, strength = "BEARISH", 1
        interp = f"WTI-WCS at ${differential:.1f}/bbl — Narrow discount, pipeline capacity ample"
    else:
        signal, strength = "BEARISH", 2
        interp = f"WTI-WCS at ${differential:.1f}/bbl — Very narrow, heavy crude competitive with light"

    return {"signal": signal, "strength": strength, "interpretation": interp}


def build_history(series: dict, n: int = 36) -> list:
    """Build last N months of history for charting."""
    history = []
    wti  = series["wti"]
    wcs  = series["wcs"]
    diff = series["differential"]

    all_dates = sorted(set(list(wti.keys()) + list(wcs.keys()) + list(diff.keys())))
    for date in all_dates[-n:]:
        w = wti.get(date)
        c = wcs.get(date)
        d = diff.get(date)
        if d is None and w and c:
            d = round(w - c, 2)
        history.append({
            "date":         date[:7],  # YYYY-MM
            "wti":          w,
            "wcs":          c,
            "differential": d,
        })
    return history


def update_quality_spreads(wcs_val: float, wcs_date: str, wti_val: float):
    """Update WTI-WCS in quality_spreads_latest.json with live data."""
    qs_path = DATA_DIR / "quality_spreads_latest.json"
    if not qs_path.exists():
        return
    try:
        qs = json.loads(qs_path.read_text())
        spread_val = round(wti_val - wcs_val, 2) if wti_val and wcs_val else None

        if "spreads" in qs and "wti_wcs" in qs["spreads"]:
            qs["spreads"]["wti_wcs"]["value"] = spread_val
            qs["spreads"]["wti_wcs"]["long_leg"]["price"]  = wti_val
            qs["spreads"]["wti_wcs"]["short_leg"]["price"] = wcs_val
            qs["spreads"]["wti_wcs"]["data_source"] = f"Alberta Govt API (period: {wcs_date[:7]})"

        for s in qs.get("spreads_list", []):
            if s["id"] == "wti_wcs":
                s["value"] = spread_val
                s["long_leg"]["price"]  = wti_val
                s["short_leg"]["price"] = wcs_val
        for s in qs.get("chartable", []):
            if s["id"] == "wti_wcs":
                s["value"] = spread_val
                s["long_leg"]["price"]  = wti_val
                s["short_leg"]["price"] = wcs_val

        qs_path.write_text(json.dumps(qs, indent=2))
        log.info("Updated quality_spreads_latest.json WTI-WCS: $%.2f", spread_val or 0)
    except Exception as e:
        log.warning("Could not update quality_spreads_latest: %s", e)


def backfill_quality_spread_history(history: list):
    """Backfill quality_spreads_history.json with 36 months of WCS historical data."""
    hist_path = DATA_DIR / "quality_spreads_history.json"

    # Load existing history
    existing = []
    if hist_path.exists():
        try:
            existing = json.loads(hist_path.read_text())
        except:
            existing = []

    existing_dates = {e["date"] for e in existing}

    added, updated = 0, 0
    for h in history:
        # Alberta history uses YYYY-MM, convert to YYYY-MM-01
        date = h["date"] + "-01" if len(h["date"]) == 7 else h["date"]
        diff = h.get("differential")
        if diff is None:
            continue

        if date not in existing_dates:
            existing.append({
                "date":      date,
                "timestamp": date + "T00:00:00Z",
                "wti_wcs":   diff,
            })
            existing_dates.add(date)
            added += 1
        else:
            # Update existing entry with live Alberta WCS data
            for entry in existing:
                if entry["date"] == date:
                    entry["wti_wcs"] = diff
                    updated += 1
                    break

    existing = sorted(existing, key=lambda x: x["date"])[-365:]
    hist_path.write_text(json.dumps(existing, indent=2))
    log.info("WCS history backfill: %d added, %d updated → quality_spreads_history.json (%d total)",
             added, updated, len(existing))


def run():
    log.info("=" * 60)
    log.info("WCS FETCHER — Alberta Economic Dashboard API")
    log.info("=" * 60)

    raw = fetch_alberta_oil()
    if not raw:
        return {}

    series = parse_series(raw)

    wcs_val,  wcs_date  = get_latest(series["wcs"])
    wti_val,  wti_date  = get_latest(series["wti"])
    diff_val, diff_date = get_latest(series["differential"])

    if diff_val is None and wcs_val and wti_val:
        diff_val = round(wti_val - wcs_val, 2)

    signal  = compute_signal(diff_val)
    history = build_history(series, n=36)

    log.info("Latest WCS:           $%.2f/bbl (%s)", wcs_val or 0, wcs_date or "—")
    log.info("Latest WTI (Alberta): $%.2f/bbl (%s)", wti_val or 0, wti_date or "—")
    log.info("WTI-WCS Differential: $%.2f/bbl (%s)", diff_val or 0, diff_date or "—")
    log.info("Signal: %s", signal["signal"])

    output = {
        "fetched_at":     datetime.now(timezone.utc).isoformat(),
        "source":         "Alberta Economic Dashboard — api.economicdata.alberta.ca",
        "note":           "Monthly data, ~1-2 month lag. Official Government of Alberta source.",
        "latest": {
            "wcs":          {"value": wcs_val,  "date": wcs_date},
            "wti":          {"value": wti_val,  "date": wti_date},
            "differential": {"value": diff_val, "date": diff_date},
        },
        "signal":         signal,
        "history":        history,
        "history_months": len(history),
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(output, f, indent=2)
    log.info("Saved → %s", OUT)

    # Update quality spreads with live WCS data
    if wcs_val and wti_val:
        update_quality_spreads(wcs_val, wcs_date, wti_val)
        backfill_quality_spread_history(history)

    log.info("=" * 60)
    return output


if __name__ == "__main__":
    run()

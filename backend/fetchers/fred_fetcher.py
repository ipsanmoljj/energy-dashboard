"""
fred_fetcher.py
---------------
Fetches macro indicators from the FRED (Federal Reserve Economic Data) API.
Saves to backend/data/fred_latest.json

Series fetched:
  DTWEXBGS  → DXY (Broad Dollar Index, trade-weighted)
  SOFR      → Secured Overnight Financing Rate
  DFF       → Daily Federal Funds Rate
  DGS10     → 10-Year Treasury Constant Maturity Rate

Usage:
  python backend/fetchers/fred_fetcher.py

Requirements:
  pip install requests

FRED API key: free at https://fred.stlouisfed.org/docs/api/api_key.html
Set via environment variable:  FRED_API_KEY=your_key
Or hardcode below (not recommended for production).
"""

import os
import json
import logging
import requests
from datetime import datetime, timedelta
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────────

FRED_API_KEY = os.getenv("FRED_API_KEY", "1d73bedd4f0c41fe197581d267892389")  # free at fred.stlouisfed.org
BASE_URL     = "https://api.stlouisfed.org/fred/series/observations"
OUTPUT_PATH  = Path(__file__).resolve().parents[1] / "data" / "fred_latest.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Series definitions ───────────────────────────────────────────────────────
# Each entry: series_id → dashboard signal key + description + signal logic

FRED_SERIES = {
    "DTWEXBGS": {
        "key":         "dxy_broad",
        "label":       "DXY Broad Dollar Index (trade-weighted)",
        "unit":        "index",
        "signal_note": "Strong USD → bearish oil (USD-priced crude more expensive for non-USD buyers). "
                       "Weak USD → bullish oil. Watch DXY direction vs Brent M1-M2 divergence.",
        "bullish_if":  "falling",   # falling dollar = bullish crude
        "bearish_if":  "rising",
    },
    "SOFR": {
        "key":         "sofr",
        "label":       "SOFR (Secured Overnight Financing Rate)",
        "unit":        "percent",
        "signal_note": "Higher SOFR → higher cost of carry for oil storage (financing leg of contango). "
                       "Compresses profitable contango window. Key input to storage economics model.",
        "bullish_if":  "falling",
        "bearish_if":  "rising",
    },
    "DFF": {
        "key":         "fed_funds",
        "label":       "Effective Federal Funds Rate",
        "unit":        "percent",
        "signal_note": "FEDFUNDS sets the macro rate environment. "
                       "Rate cuts → weaker USD → bullish crude. Rate hikes → USD strength → bearish.",
        "bullish_if":  "falling",
        "bearish_if":  "rising",
    },
    "DGS10": {
        "key":         "us_10y_yield",
        "label":       "10-Year Treasury Yield",
        "unit":        "percent",
        "signal_note": "Rising 10Y → higher discount rates → risk assets (incl. oil) under pressure. "
                       "Also drives USD strength. Watch for divergence with oil when both spike.",
        "bullish_if":  "falling",
        "bearish_if":  "rising",
    },
}

# ── Helpers ──────────────────────────────────────────────────────────────────

def fetch_series(series_id: str, n_obs: int = 30) -> list[dict]:
    """
    Fetch the last n_obs observations for a FRED series.
    Returns list of {date, value} dicts, sorted descending.
    """
    start_date = (datetime.today() - timedelta(days=n_obs * 2)).strftime("%Y-%m-%d")

    params = {
        "series_id":   series_id,
        "api_key":     FRED_API_KEY,
        "file_type":   "json",
        "sort_order":  "desc",
        "limit":       n_obs,
        "observation_start": start_date,
    }

    try:
        r = requests.get(BASE_URL, params=params, timeout=10)
        r.raise_for_status()
    except requests.RequestException as exc:
        log.error("FRED request failed for %s: %s", series_id, exc)
        return []

    raw = r.json().get("observations", [])
    out = []
    for obs in raw:
        val_str = obs.get("value", ".")
        if val_str == ".":
            continue
        try:
            out.append({"date": obs["date"], "value": float(val_str)})
        except ValueError:
            continue

    return out  # already desc by FRED sort


def compute_change(observations: list[dict]) -> dict:
    """
    Given desc-sorted observations, compute WoW and MoM changes.
    Returns dict with latest, prev_day, wow, mom and their pct changes.
    """
    if not observations:
        return {}

    latest    = observations[0]["value"]
    latest_dt = observations[0]["date"]

    # day-over-day (most recent vs previous available observation)
    dod = round(latest - observations[1]["value"], 4) if len(observations) > 1 else None

    # week-over-week: find obs closest to 5 trading days ago
    wow = None
    for obs in observations[1:]:
        delta = (datetime.strptime(latest_dt, "%Y-%m-%d") -
                 datetime.strptime(obs["date"], "%Y-%m-%d")).days
        if delta >= 5:
            wow = round(latest - obs["value"], 4)
            break

    # month-over-month: find obs closest to 21 trading days ago
    mom = None
    for obs in observations[1:]:
        delta = (datetime.strptime(latest_dt, "%Y-%m-%d") -
                 datetime.strptime(obs["date"], "%Y-%m-%d")).days
        if delta >= 21:
            mom = round(latest - obs["value"], 4)
            break

    return {
        "latest_date": latest_dt,
        "latest":      round(latest, 4),
        "dod":         dod,
        "wow":         wow,
        "mom":         mom,
    }


def derive_signal(series_cfg: dict, changes: dict) -> str:
    """
    Emit a simple directional signal based on WoW change direction.
    Returns 'BULLISH', 'BEARISH', or 'NEUTRAL' for crude oil.
    """
    if not changes or changes.get("wow") is None:
        return "NEUTRAL"

    wow = changes["wow"]
    if wow < -0.05:   # falling
        return "BULLISH" if series_cfg["bullish_if"] == "falling" else "BEARISH"
    elif wow > 0.05:  # rising
        return "BULLISH" if series_cfg["bullish_if"] == "rising" else "BEARISH"
    return "NEUTRAL"


# ── Storage carry cost model ─────────────────────────────────────────────────

def compute_storage_carry(sofr: float | None) -> dict:
    """
    Compute the full carry cost of oil storage given current SOFR.

    Components (per barrel per month):
      1. Financing:  (SOFR + 50bp spread) × crude_price / 12
      2. Tank lease:  $0.30–0.60/bbl/month   (use midpoint $0.45)
      3. Insurance:   $0.05/bbl/month
    Total = financing + 0.50

    Reference crude price comes from WTI estimate (fallback $78 if unavailable).
    """
    if sofr is None:
        return {}

    CRUDE_PRICE_FALLBACK = 78.0   # update from futures_fetcher output
    SPREAD_BP            = 0.50   # credit spread above SOFR
    TANK_LEASE           = 0.45   # $/bbl/month (midpoint)
    INSURANCE            = 0.05   # $/bbl/month

    rate = (sofr + SPREAD_BP) / 100
    financing_monthly = rate * CRUDE_PRICE_FALLBACK / 12

    total_monthly = round(financing_monthly + TANK_LEASE + INSURANCE, 3)
    total_11mo    = round(total_monthly * 11, 2)   # M1-M12 contango required

    return {
        "sofr_used_pct":         round(sofr, 4),
        "financing_per_bbl_mo":  round(financing_monthly, 3),
        "tank_lease_per_bbl_mo": TANK_LEASE,
        "insurance_per_bbl_mo":  INSURANCE,
        "total_carry_per_bbl_mo": total_monthly,
        "m1_m12_contango_needed": total_11mo,
        "note": (
            f"Contango > ${total_11mo}/bbl for M1-M12 = floating storage profitable. "
            f"Contango < ${total_monthly:.2f}/bbl/mo = storage uneconomic → draws."
        ),
    }


# ── Main ─────────────────────────────────────────────────────────────────────

def run() -> dict:
    log.info("Starting FRED fetch — %d series", len(FRED_SERIES))

    output = {
        "fetcher":    "fred_fetcher",
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "source":     "Federal Reserve Bank of St. Louis (FRED)",
        "series":     {},
        "derived":    {},
    }

    sofr_latest = None

    for series_id, cfg in FRED_SERIES.items():
        log.info("Fetching %s (%s)", series_id, cfg["label"])
        observations = fetch_series(series_id, n_obs=30)

        if not observations:
            log.warning("No data returned for %s", series_id)
            output["series"][cfg["key"]] = {"error": "no_data", "series_id": series_id}
            continue

        changes = compute_change(observations)
        signal  = derive_signal(cfg, changes)

        output["series"][cfg["key"]] = {
            "series_id":   series_id,
            "label":       cfg["label"],
            "unit":        cfg["unit"],
            "signal_note": cfg["signal_note"],
            "crude_signal": signal,
            **changes,
            "history_30d": observations[:30],
        }

        log.info(
            "  %s latest=%.4f | wow=%s | crude_signal=%s",
            series_id,
            changes.get("latest", 0),
            changes.get("wow"),
            signal,
        )

        if series_id == "SOFR":
            sofr_latest = changes.get("latest")

    # ── Derived: storage carry cost ──────────────────────────────────────────
    output["derived"]["storage_carry"] = compute_storage_carry(sofr_latest)

    # ── Derived: macro composite signal ─────────────────────────────────────
    signals = [
        output["series"].get(cfg["key"], {}).get("crude_signal", "NEUTRAL")
        for cfg in FRED_SERIES.values()
    ]
    bullish = signals.count("BULLISH")
    bearish = signals.count("BEARISH")

    output["derived"]["macro_composite"] = {
        "bullish_count": bullish,
        "bearish_count": bearish,
        "neutral_count": signals.count("NEUTRAL"),
        "composite_signal": (
            "BULLISH" if bullish > bearish + 1
            else "BEARISH" if bearish > bullish + 1
            else "MIXED"
        ),
        "note": (
            "Macro composite: DXY + SOFR + FEDFUNDS + DGS10 directional signals. "
            "BULLISH = falling rates/USD environment. "
            "BEARISH = rising rates/USD environment. "
            "MIXED = conflicting signals — watch physical fundamentals (Cushing draw, OECD stocks) "
            "to determine whether macro headwind or tailwind dominates."
        ),
    }

    # ── Save ────────────────────────────────────────────────────────────────
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    log.info("Saved → %s", OUTPUT_PATH)
    log.info(
        "Macro composite: %s (B=%d, Br=%d, N=%d)",
        output["derived"]["macro_composite"]["composite_signal"],
        bullish, bearish, signals.count("NEUTRAL"),
    )

    return output


if __name__ == "__main__":
    run()

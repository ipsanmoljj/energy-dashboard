"""
backend/fetchers/quality_spreads_fetcher.py
--------------------------------------------
Fetches crude quality spread data from EIA Open Data API v2.
Computes: Brent-Maya, LLS-Mars, WTI-WTS, Brent-Urals, WTI-WCS, Naphtha-Gasoil

All series are monthly with ~60-day lag — good for structural spread analysis.

Writes: backend/data/quality_spreads_latest.json

Usage:
  python backend/fetchers/quality_spreads_fetcher.py
  set EIA_API_KEY=jIklUoLif3sC7L0wgwKTRK4njU9rv5eG4ePRc5QR  (Windows CMD)
  export EIA_API_KEY=jIklUoLif3sC7L0wgwKTRK4njU9rv5eG4ePRc5QR  (Linux/Mac)
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE    = Path(__file__).resolve().parents[1]
OUT     = BASE / "data" / "quality_spreads_latest.json"
API_KEY = os.environ.get("EIA_API_KEY", "jIklUoLif3sC7L0wgwKTRK4njU9rv5eG4ePRc5QR")
BASE_URL = "https://api.eia.gov/v2/petroleum/pri/spt/data/"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("quality_spreads")

# ── EIA series definitions ────────────────────────────────────────────────────
# Format: (series_id, label, unit, conversion_factor)
# conversion_factor: 1.0 for $/bbl, 42.0 for $/gal→$/bbl

SERIES = {
    # Light sweet benchmarks
    "brent":   ("RBRTE",          "Brent Crude (ICE)",              "$/bbl", 1.0),
    "wti":     ("RWTC",           "WTI Crude (Cushing)",            "$/bbl", 1.0),
    "lls":     ("EER_EPLLPA_PF4_Y35LA_DPG", "Light Louisiana Sweet","$/bbl", 1.0),

    # Heavy/sour grades
    "maya":    ("IMF2810004",     "Maya Crude (FOB US Gulf)",       "$/bbl", 1.0),
    "mars":    ("EER_EPMRR_PF4_Y35LA_DPG",  "Mars Sour (US Gulf)", "$/bbl", 1.0),
    "wts":     ("EER_EPCRWTS_PF4_Y35TX_DPG","West Texas Sour",     "$/bbl", 1.0),
    "wcs":     ("PSWCRS",         "Western Canadian Select",        "$/bbl", 1.0),
    "urals":   ("PURRS",          "Urals (NW Europe)",              "$/bbl", 1.0),

    # Products for naphtha-gasoil spread
    "naphtha": ("EER_EPNX_PF4_RGC_DPG",    "Naphtha (US Gulf)",   "$/gal", 42.0),
    "gasoil":  ("EER_EPD2F_PF4_RGC_DPG",   "Gasoil (US Gulf)",    "$/gal", 42.0),
}

# ── Spread definitions ────────────────────────────────────────────────────────
SPREADS = [
    {
        "id":       "brent_maya",
        "label":    "Brent – Maya (Light-Heavy)",
        "long":     "brent",
        "short":    "maya",
        "category": "light_heavy",
        "note":     "Measures light sweet premium over heavy sour. Wide = complex refinery advantage.",
        "bull_threshold":  8.0,   # $/bbl — historically wide
        "bear_threshold":  3.0,   # $/bbl — historically narrow
    },
    {
        "id":       "lls_mars",
        "label":    "LLS – Mars (Light-Heavy US Gulf)",
        "long":     "lls",
        "short":    "mars",
        "category": "light_heavy",
        "note":     "US Gulf light-heavy differential. Key for US Gulf refinery margin analysis.",
        "bull_threshold":  6.0,
        "bear_threshold":  2.0,
    },
    {
        "id":       "wti_wts",
        "label":    "WTI – West Texas Sour (Sweet-Sour)",
        "long":     "wti",
        "short":    "wts",
        "category": "sweet_sour",
        "note":     "Regional sweet-sour spread at Midland. Reflects Permian Basin crude quality mix.",
        "bull_threshold":  4.0,
        "bear_threshold":  1.0,
    },
    {
        "id":       "brent_urals",
        "label":    "Brent – Urals (Sweet-Sour / Sanctions)",
        "long":     "brent",
        "short":    "urals",
        "category": "sweet_sour",
        "note":     "Post-2022 sanctions premium. Wide = Russia forced to discount. Key geopolitical signal.",
        "bull_threshold": 10.0,
        "bear_threshold":  2.0,
    },
    {
        "id":       "wti_wcs",
        "label":    "WTI – WCS (Heavy Sour / Canadian)",
        "long":     "wti",
        "short":    "wcs",
        "category": "light_heavy",
        "note":     "Canadian heavy sour discount. Driven by Alberta pipeline capacity constraints.",
        "bull_threshold": 20.0,
        "bear_threshold": 10.0,
    },
    {
        "id":       "naphtha_gasoil",
        "label":    "Naphtha – Gasoil (Product Spread)",
        "long":     "naphtha",
        "short":    "gasoil",
        "category": "product",
        "note":     "Refinery configuration signal. Negative = gasoil premium (diesel tight). Positive = naphtha tight.",
        "bull_threshold":  2.0,   # naphtha premium (petrochem demand strong)
        "bear_threshold": -5.0,   # gasoil premium (diesel tight, bearish for naphtha crackers)
    },
]


def fetch_series(series_id: str, label: str, multiplier: float = 1.0) -> dict:
    """Fetch latest monthly value for an EIA series."""
    if not API_KEY:
        log.error("EIA_API_KEY not set")
        return {}

    params = {
        "api_key":  API_KEY,
        "frequency": "monthly",
        "data[0]":  "value",
        "facets[series][]": series_id,
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "length": 6,   # last 6 months for MoM calc
        "offset": 0,
    }

    try:
        r = requests.get(BASE_URL, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()

        rows = data.get("response", {}).get("data", [])
        if not rows:
            log.warning("  %s (%s): no data returned", label, series_id)
            return {}

        # Sort by period descending (already sorted by API)
        latest = rows[0]
        prev   = rows[1] if len(rows) > 1 else None

        val  = float(latest["value"]) * multiplier if latest.get("value") else None
        prev_val = float(prev["value"]) * multiplier if prev and prev.get("value") else None
        mom  = round(val - prev_val, 3) if val and prev_val else None

        log.info("  %-8s %s: $%.2f/bbl (%s)", series_id, label, val or 0, latest.get("period",""))
        return {
            "series_id": series_id,
            "label":     label,
            "value":     round(val, 3) if val else None,
            "prev":      round(prev_val, 3) if prev_val else None,
            "mom":       mom,
            "period":    latest.get("period"),
            "unit":      "$/bbl",
        }

    except requests.HTTPError as e:
        log.error("  %s: HTTP %s — %s", series_id, e.response.status_code, e.response.text[:100])
        return {}
    except Exception as e:
        log.error("  %s: %s", series_id, e)
        return {}


def compute_spread(prices: dict, spread_cfg: dict) -> dict:
    """Compute a spread from two price series."""
    long_id  = spread_cfg["long"]
    short_id = spread_cfg["short"]

    long_val  = prices.get(long_id,  {}).get("value")
    short_val = prices.get(short_id, {}).get("value")
    long_prev  = prices.get(long_id,  {}).get("prev")
    short_prev = prices.get(short_id, {}).get("prev")

    value = round(long_val - short_val, 3) if long_val and short_val else None
    prev  = round(long_prev - short_prev, 3) if long_prev and short_prev else None
    mom   = round(value - prev, 3) if value is not None and prev is not None else None

    # Signal logic
    bull_t = spread_cfg["bull_threshold"]
    bear_t = spread_cfg["bear_threshold"]

    if value is None:
        signal, strength = "NO_DATA", 0
    elif value >= bull_t:
        signal  = "BULLISH"
        strength = min(3, 1 + int((value - bull_t) / bull_t * 2))
    elif value <= bear_t:
        signal  = "BEARISH"
        strength = min(3, 1 + int((bear_t - value) / abs(bear_t) * 2))
    else:
        signal, strength = "NEUTRAL", 1

    # Naphtha-gasoil is inverted (negative = gasoil premium = bearish for naphtha)
    if spread_cfg["id"] == "naphtha_gasoil" and value is not None:
        if value < bear_t:
            signal  = "BEARISH"   # gasoil premium = diesel tight, no petrochem demand
            strength = 2
        elif value > bull_t:
            signal  = "BULLISH"   # naphtha premium = petrochem demand strong
            strength = 2
        else:
            signal, strength = "NEUTRAL", 1

    period_long  = prices.get(long_id,  {}).get("period", "")
    period_short = prices.get(short_id, {}).get("period", "")

    return {
        "id":          spread_cfg["id"],
        "label":       spread_cfg["label"],
        "category":    spread_cfg["category"],
        "value":       value,
        "prev":        prev,
        "mom":         mom,
        "unit":        "$/bbl",
        "signal":      signal,
        "strength":    strength,
        "long_leg":    {"id": long_id,  "value": long_val,  "period": period_long},
        "short_leg":   {"id": short_id, "value": short_val, "period": period_short},
        "bull_threshold": bull_t,
        "bear_threshold": bear_t,
        "note":        spread_cfg["note"],
        "interpretation": _interpret(spread_cfg["id"], value, signal),
    }


def _interpret(spread_id: str, value, signal: str) -> str:
    """Human-readable interpretation of spread level."""
    if value is None:
        return "No data available"

    interp = {
        "brent_maya": (
            f"Brent-Maya light-heavy differential at ${value:.2f}/bbl. "
            + ("Wide spread — complex refineries earn strong upgrading margin over simple refineries." if signal == "BULLISH"
               else "Narrow spread — heavy crude relatively expensive; coker margins compressed." if signal == "BEARISH"
               else "Normal range — refinery configuration advantage moderate.")
        ),
        "lls_mars": (
            f"LLS-Mars US Gulf differential at ${value:.2f}/bbl. "
            + ("Wide — US Gulf light crude commands large premium; Mars sour buyers benefit." if signal == "BULLISH"
               else "Narrow — heavy sour crude relatively bid; complex refinery margin under pressure." if signal == "BEARISH"
               else "Normal range for US Gulf quality spread.")
        ),
        "wti_wts": (
            f"WTI-WTS sweet-sour spread at ${value:.2f}/bbl. "
            + ("Wide — Permian light sweet commanding premium over sour barrels." if signal == "BULLISH"
               else "Narrow — sour crude competitive with sweet in Midland basin." if signal == "BEARISH"
               else "Normal Permian sweet-sour differential.")
        ),
        "brent_urals": (
            f"Brent-Urals spread at ${value:.2f}/bbl. "
            + ("Wide — Russia accepting deep discount; sanctions effective, Western buyers paying premium." if signal == "BULLISH"
               else "Narrow — Russian discount compressed; sanctions leaking or demand strong from India/China." if signal == "BEARISH"
               else "Moderate Russia discount — sanctions partially effective.")
        ),
        "wti_wcs": (
            f"WTI-WCS Canadian differential at ${value:.2f}/bbl. "
            + ("Wide — Alberta pipeline constraints severe; Canadian heavy deeply discounted." if signal == "BULLISH"
               else "Narrow — Trans Mountain or other pipeline capacity relieving Alberta congestion." if signal == "BEARISH"
               else "Normal WTI-WCS range — pipeline capacity adequate.")
        ),
        "naphtha_gasoil": (
            f"Naphtha-Gasoil product spread at ${value:.2f}/bbl. "
            + ("Naphtha premium — petrochemical demand strong, crackers running hard." if signal == "BULLISH"
               else "Gasoil premium — diesel tight, distillate demand outpacing naphtha/petrochem." if signal == "BEARISH"
               else "Balanced product slate — no strong directional signal.")
        ),
    }
    return interp.get(spread_id, f"Spread at ${value:.2f}/bbl — {signal}")


def composite_score(spreads: list) -> dict:
    """Aggregate quality spread signals into composite."""
    score, count = 0.0, 0
    components = []

    weights = {
        "light_heavy": 0.30,
        "sweet_sour":  0.40,
        "product":     0.30,
    }

    for s in spreads:
        if s["signal"] == "NO_DATA":
            continue
        cat_w = weights.get(s["category"], 0.25)
        pts   = {"BULLISH": 1, "NEUTRAL": 0, "BEARISH": -1}.get(s["signal"], 0)
        score += pts * s["strength"] * cat_w
        count += 1
        components.append({
            "id":      s["id"],
            "label":   s["label"],
            "signal":  s["signal"],
            "value":   s["value"],
        })

    norm = round(max(-10, min(10, score * 3)), 2) if count > 0 else 0
    overall = "BULLISH" if norm >= 2 else ("BEARISH" if norm <= -2 else "NEUTRAL")

    return {
        "score":          norm,
        "overall_signal": overall,
        "components":     components,
        "interpretation": (
            "Quality spreads wide — complex refinery advantage elevated; heavy sour crude discounted" if norm >= 3 else
            "Quality spreads compressed — heavy crude relatively expensive; simple refinery squeezed" if norm <= -3 else
            "Quality spreads in normal range — refinery configuration advantage moderate"
        ),
    }


def run():
    log.info("=" * 60)
    log.info("QUALITY SPREADS FETCHER — EIA Open Data API")
    log.info("=" * 60)

    if not API_KEY:
        log.error("EIA_API_KEY not set. Set it with: set EIA_API_KEY=your_key (Windows)")
        return {}

    # ── Fetch all price series ────────────────────────────────────────────────
    prices = {}
    for key, (series_id, label, unit, mult) in SERIES.items():
        log.info("Fetching: %s (%s)", label, series_id)
        prices[key] = fetch_series(series_id, label, mult)
        time.sleep(0.3)   # rate limit courtesy

    # ── Compute all spreads ───────────────────────────────────────────────────
    log.info("─" * 60)
    log.info("Computing spreads...")
    spreads = []
    for cfg in SPREADS:
        s = compute_spread(prices, cfg)
        spreads.append(s)
        val_str = f"${s['value']:.2f}/bbl" if s["value"] is not None else "NO_DATA"
        log.info("  %-30s %s  [%s]", s["label"], val_str, s["signal"])

    # ── Composite ─────────────────────────────────────────────────────────────
    comp = composite_score(spreads)

    output = {
        "fetched_at":   datetime.now(timezone.utc).isoformat(),
        "fetcher":      "quality_spreads_fetcher",
        "note":         "Monthly EIA data — ~60 day lag. Use for structural trend analysis.",
        "prices":       prices,
        "spreads":      {s["id"]: s for s in spreads},
        "spreads_list": spreads,
        "composite":    comp,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(output, f, indent=2)

    log.info("─" * 60)
    log.info("Composite: %s (score=%+.2f)", comp["overall_signal"], comp["score"])
    log.info("Saved → %s", OUT)
    log.info("=" * 60)

    return output


if __name__ == "__main__":
    run()

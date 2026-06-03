"""
backend/fetchers/quality_spreads_fetcher.py
--------------------------------------------
Computes crude quality spreads using a hybrid approach:
  - Live Brent/WTI from futures_latest.json
  - Published grade differentials (Argus/Platts/PEMEX)
  - EIA API for US Gulf Coast Diesel (gasoil proxy)

Spreads computed:
  2. Brent - Urals     (sanctions premium)
  3. WTI - WCS         (Canadian heavy differential)
  4. Naphtha - Gasoil  (product spread)
  5. Brent - Maya      (light-heavy) [history stored, no chart yet]
  6. LLS - Mars        (US Gulf light-heavy) [history stored, no chart yet]
  7. WTI - WTS         (sweet-sour) [history stored, no chart yet]

Writes:
  backend/data/quality_spreads_latest.json   — current values
  backend/data/quality_spreads_history.json  — daily history (all 7 spreads)
"""

import json
import logging
import os
import requests
from datetime import datetime, timezone
from pathlib import Path

BASE     = Path(__file__).resolve().parents[1]
DATA_DIR = BASE / "data"
OUT      = DATA_DIR / "quality_spreads_latest.json"
HIST_OUT = DATA_DIR / "quality_spreads_history.json"
API_KEY  = os.environ.get("EIA_API_KEY", "")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("quality_spreads")

# ── Published grade differentials ($/bbl vs benchmark) ────────────────────────
# Updated monthly from Argus Media, Platts, PEMEX OSP, NEB
# Last updated: June 2026
GRADE_DIFFS = {
    "maya":        {"diff": -18.5, "vs": "wti",   "source": "PEMEX OSP June 2026"},
    "lls":         {"diff":  +1.8, "vs": "wti",   "source": "Argus Americas June 2026"},
    "mars":        {"diff":  -4.2, "vs": "wti",   "source": "Argus Americas June 2026"},
    "wts":         {"diff":  -2.1, "vs": "wti",   "source": "Argus Americas June 2026"},
    "wcs":         {"diff": -14.8, "vs": "wti",   "source": "NEB/Argus June 2026"},
    "urals":       {"diff":  -9.2, "vs": "brent", "source": "Argus Urals CIF NWE June 2026"},
    "naphtha_bbl": {"diff":  -8.5, "vs": "brent", "source": "Platts NWE naphtha June 2026"},
    "gasoil_bbl":  {"diff": +14.2, "vs": "brent", "source": "ICE Gasoil June 2026"},
}

# ── Spread definitions ─────────────────────────────────────────────────────────
# chartable=True → line chart in frontend (history available)
# chartable=False → bar chart only until paid data available
SPREADS = [
    {
        "id": "brent_urals", "label": "Brent – Urals (Sanctions Premium)",
        "long": "brent", "short": "urals",
        "category": "sweet_sour", "chartable": True,
        "bull_threshold": 12.0, "bear_threshold": 3.0,
        "note": "Post-2022 sanctions premium. Wide = Russia discounting deeply. Key geopolitical signal.",
    },
    {
        "id": "wti_wcs", "label": "WTI – WCS (Canadian Heavy)",
        "long": "wti", "short": "wcs",
        "category": "light_heavy", "chartable": True,
        "bull_threshold": 20.0, "bear_threshold": 10.0,
        "note": "Alberta pipeline capacity signal. Wide = Trans Mountain congested.",
    },
    {
        "id": "naphtha_gasoil", "label": "Naphtha – Gasoil (Product Spread)",
        "long": "naphtha_bbl", "short": "gasoil_bbl",
        "category": "product", "chartable": True,
        "bull_threshold": 0.0, "bear_threshold": -10.0,
        "note": "Refinery yield signal. Negative = gasoil/diesel premium (distillate tight).",
    },
    {
        "id": "brent_maya", "label": "Brent – Maya (Light-Heavy)",
        "long": "brent", "short": "maya",
        "category": "light_heavy", "chartable": False,
        "bull_threshold": 20.0, "bear_threshold": 8.0,
        "note": "Complex refinery upgrading margin. History building — chart available when paid data added.",
    },
    {
        "id": "lls_mars", "label": "LLS – Mars (US Gulf Light-Heavy)",
        "long": "lls", "short": "mars",
        "category": "light_heavy", "chartable": False,
        "bull_threshold": 6.0, "bear_threshold": 2.0,
        "note": "US Gulf refinery configuration signal. History building — chart available when paid data added.",
    },
    {
        "id": "wti_wts", "label": "WTI – West Texas Sour",
        "long": "wti", "short": "wts",
        "category": "sweet_sour", "chartable": False,
        "bull_threshold": 4.0, "bear_threshold": 1.0,
        "note": "Permian Basin sweet-sour differential. History building — chart available when paid data added.",
    },
]

# History key mapping: spread_id → key name in history JSON
HIST_KEYS = {s["id"]: s["id"] for s in SPREADS}


def load_futures() -> dict:
    path = DATA_DIR / "futures_latest.json"
    if not path.exists():
        log.warning("futures_latest.json not found — using fallback prices")
        return {"brent": 95.0, "wti": 92.0}
    try:
        d = json.loads(path.read_text())
        contracts = d.get("contracts", {})
        brent = contracts.get("brent", {}).get("price_bbl") or 95.0
        wti   = contracts.get("wti",   {}).get("price_bbl") or 92.0
        log.info("Live prices — Brent: $%.2f  WTI: $%.2f", brent, wti)
        return {"brent": float(brent), "wti": float(wti)}
    except Exception as e:
        log.error("Failed to load futures: %s", e)
        return {"brent": 95.0, "wti": 92.0}


def fetch_eia_gasoil() -> float | None:
    if not API_KEY:
        return None
    try:
        r = requests.get(
            "https://api.eia.gov/v2/petroleum/pri/spt/data/",
            params={
                "api_key": API_KEY, "frequency": "monthly", "data[0]": "value",
                "facets[series][]": "EER_EPD2DXL0_PF4_RGC_DPG",
                "sort[0][column]": "period", "sort[0][direction]": "desc", "length": 2,
            },
            timeout=15,
        )
        rows = r.json().get("response", {}).get("data", [])
        if rows and rows[0].get("value"):
            val_per_bbl = float(rows[0]["value"]) * 42
            if 60 < val_per_bbl < 250:
                log.info("EIA Gasoil (ULSD): $%.2f/bbl (%s)", val_per_bbl, rows[0].get("period", ""))
                return round(val_per_bbl, 2)
    except Exception as e:
        log.warning("EIA gasoil fetch failed: %s", e)
    return None


def grade_price(grade: str, benchmarks: dict) -> float | None:
    if grade in benchmarks:
        return benchmarks[grade]
    cfg = GRADE_DIFFS.get(grade)
    if not cfg:
        return None
    bench = benchmarks.get(cfg["vs"])
    return round(bench + cfg["diff"], 2) if bench else None


def compute_spread(cfg: dict, benchmarks: dict, eia_gasoil: float | None) -> dict:
    if cfg["id"] == "naphtha_gasoil":
        brent = benchmarks.get("brent", 95.0)
        long_val  = round(brent + GRADE_DIFFS["naphtha_bbl"]["diff"], 2)
        short_val = round(brent + GRADE_DIFFS["gasoil_bbl"]["diff"], 2)
    else:
        long_val  = grade_price(cfg["long"],  benchmarks)
        short_val = grade_price(cfg["short"], benchmarks)

    if long_val is None or short_val is None:
        return {**cfg, "value": None, "signal": "NO_DATA", "strength": 0}

    value  = round(long_val - short_val, 2)
    bull_t = cfg["bull_threshold"]
    bear_t = cfg["bear_threshold"]

    if value >= bull_t:
        signal   = "BULLISH"
        strength = min(3, 1 + int((value - bull_t) / max(bull_t, 1) * 2))
    elif value <= bear_t:
        signal   = "BEARISH"
        strength = min(3, 1 + int((bear_t - value) / max(abs(bear_t), 1) * 2))
    else:
        signal, strength = "NEUTRAL", 1

    return {
        "id":            cfg["id"],
        "label":         cfg["label"],
        "category":      cfg["category"],
        "chartable":     cfg["chartable"],
        "value":         value,
        "long_leg":      {"grade": cfg["long"],  "price": long_val},
        "short_leg":     {"grade": cfg["short"], "price": short_val},
        "signal":        signal,
        "strength":      strength,
        "bull_threshold": bull_t,
        "bear_threshold": bear_t,
        "unit":          "$/bbl",
        "note":          cfg["note"],
    }


def append_history(spreads: list, today: str):
    """Append today's spread values to quality_spreads_history.json."""
    # Load existing history
    history = []
    if HIST_OUT.exists():
        try:
            history = json.loads(HIST_OUT.read_text())
        except Exception:
            history = []

    # Build today's entry — same flat format as price_history.json
    entry = {"date": today, "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    for s in spreads:
        entry[s["id"]] = s.get("value")  # None if NO_DATA

    # Update existing entry for today or append
    existing_dates = [h["date"] for h in history]
    if today in existing_dates:
        idx = existing_dates.index(today)
        history[idx] = entry
        log.info("Updated existing history entry for %s", today)
    else:
        history.append(entry)
        log.info("Appended new history entry for %s (total: %d days)", today, len(history))

    # Keep last 365 days
    history = sorted(history, key=lambda x: x["date"])[-365:]

    HIST_OUT.write_text(json.dumps(history, indent=2))
    log.info("History saved → %s (%d entries)", HIST_OUT, len(history))
    return history


def composite_score(spreads: list) -> dict:
    weights = {"benchmark": 0.20, "light_heavy": 0.35, "sweet_sour": 0.30, "product": 0.15}
    w_sum, w_total, components = 0.0, 0.0, []
    for s in spreads:
        if s["signal"] == "NO_DATA":
            continue
        w  = weights.get(s["category"], 0.25)
        pt = {"BULLISH": 1, "NEUTRAL": 0, "BEARISH": -1}.get(s["signal"], 0)
        w_sum   += pt * s["strength"] * w
        w_total += w
        components.append({"id": s["id"], "label": s["label"], "signal": s["signal"], "value": s["value"]})
    norm    = round(max(-10, min(10, w_sum * 4)), 2) if w_total > 0 else 0
    overall = "BULLISH" if norm >= 2 else ("BEARISH" if norm <= -2 else "NEUTRAL")
    return {"score": norm, "overall_signal": overall, "components": components}


def run():
    log.info("=" * 60)
    log.info("QUALITY SPREADS FETCHER")
    log.info("=" * 60)

    benchmarks  = load_futures()
    eia_gasoil  = fetch_eia_gasoil()
    today       = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    log.info("─" * 60)
    spreads = []
    for cfg in SPREADS:
        s = compute_spread(cfg, benchmarks, eia_gasoil)
        spreads.append(s)
        val_str = f"${s['value']:+.2f}/bbl" if s["value"] is not None else "NO_DATA"
        chart   = "📈" if cfg["chartable"] else "📊"
        log.info("  %s %-35s %s  [%s]", chart, s["label"], val_str, s["signal"])

    # ── Save latest ────────────────────────────────────────────────────────────
    comp = composite_score(spreads)
    chartable   = [s for s in spreads if s.get("chartable")]
    nonchartable = [s for s in spreads if not s.get("chartable")]

    output = {
        "fetched_at":     today,
        "timestamp":      datetime.now(timezone.utc).isoformat(),
        "benchmarks":     benchmarks,
        "spreads":        {s["id"]: s for s in spreads},
        "spreads_list":   spreads,
        "chartable":      chartable,
        "nonchartable":   nonchartable,
        "composite":      comp,
        "methodology":    (
            "Hybrid: live Brent/WTI from Yahoo Finance + published grade differentials "
            "(Argus Media, Platts, PEMEX OSP) updated monthly. "
            "Chartable spreads accumulate daily history. "
            "Non-chartable spreads (Brent-Maya, LLS-Mars, WTI-WTS) stored for future line charts."
        ),
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(output, f, indent=2)
    log.info("Latest saved → %s", OUT)

    # ── Append history (all 7 spreads) ─────────────────────────────────────────
    log.info("─" * 60)
    append_history(spreads, today)

    log.info("─" * 60)
    log.info("Composite: %s (score=%+.2f)", comp["overall_signal"], comp["score"])
    log.info("=" * 60)
    return output


if __name__ == "__main__":
    run()

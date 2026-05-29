"""
nci_composite.py
----------------
Day 6 — NCI Composite Signal Engine

Combines ALL signal layers into one final composite score:

  Layer 1 — Inventory (Day 4):   NCI inventory score (-10 to +10)
  Layer 2 — Crack Spreads (Day 5): NCI crack score (-10 to +10)
  Layer 3 — Macro (FRED):         DXY + rates signal
  Layer 4 — Weather/Demand:       HDD/CDD demand signal
  Layer 5 — Positioning (CFTC):   Speculative crowding signal
  Layer 6 — GIE Gas Storage:      EU gas → distillate demand

Final output: COMPOSITE NCI SCORE (-10 to +10)

Score interpretation:
  +7 to +10  = STRONG BUY signal — multiple layers converging bullish
  +4 to +6   = BUY — majority of signals bullish
  +1 to +3   = MILD BUY — slight bullish edge
  -1 to +1   = NEUTRAL — signals mixed or flat
  -2 to -4   = MILD SELL — slight bearish edge
  -4 to -6   = SELL — majority bearish
  -7 to -10  = STRONG SELL — multiple layers converging bearish

Saves to: backend/data/nci_composite.json

Usage:
  python backend/nci_composite.py              # compute from cached signals
  python backend/nci_composite.py --full       # re-run all engines first
"""

import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime, date
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────

ROOT        = Path(__file__).resolve().parent
DATA_DIR    = ROOT / "data"
OUTPUT_PATH = DATA_DIR / "nci_composite.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Layer weights ──────────────────────────────────────────────────────────────
# How much each signal layer contributes to the final score.
# Inventory and crack spreads are the most direct price drivers.
# Macro, weather, positioning are secondary/confirming signals.

LAYER_WEIGHTS = {
    "inventory":   0.30,   # Days cover, Cushing, 5yr deviation — most direct
    "crack":       0.22,   # Refinery margins — crude demand signal
    "macro":       0.13,   # DXY, rates — financial backdrop
    "demand":      0.10,   # Weather HDD/CDD demand signal
    "positioning": 0.10,   # CFTC — sentiment/crowding
    "gie":         0.05,   # EU gas storage
    "news":        0.10,   # News sentiment — breaking events, geo risk
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_json(filename: str) -> dict:
    path = DATA_DIR / filename
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}

def safe(data, *keys, default=None):
    val = data
    for k in keys:
        val = val.get(k, default) if isinstance(val, dict) else default
    return val

# ── Layer signal extractors ───────────────────────────────────────────────────

def get_inventory_signal() -> dict:
    """Extract NCI inventory score from inventory_signals.json"""
    data  = load_json("inventory_signals.json")
    score = safe(data, "nci_inventory", "score")
    label = safe(data, "nci_inventory", "label", default="UNKNOWN")

    if score is None:
        return {"score": 0, "label": "NO_DATA", "available": False, "details": {}, "contribution": 0}

    # Key details to surface
    details = {
        "days_cover":          safe(data, "days_cover", "current"),
        "cushing_mmbbls":      safe(data, "stocks", "cushing_mmbbls"),
        "cushing_util_pct":    safe(data, "stocks", "cushing_util_pct"),
        "distillate_vs_5yr":   safe(data, "vs_5yr", "distillate", "deviation_pct"),
        "gasoline_vs_5yr":     safe(data, "vs_5yr", "gasoline",   "deviation_pct"),
        "crude_wow_surprise":  safe(data, "wow_changes", "total_crude", "surprise"),
        "refinery_util":       safe(data, "production_flows", "refinery_util_pct"),
    }

    return {
        "score":     score,
        "label":     label,
        "available": True,
        "details":   details,
        "weight":    LAYER_WEIGHTS["inventory"],
        "contribution": round(score * LAYER_WEIGHTS["inventory"], 3),
    }


def get_crack_signal() -> dict:
    """Extract NCI crack score from crack_signals.json"""
    data  = load_json("crack_signals.json")
    score = safe(data, "nci_crack", "score")
    label = safe(data, "nci_crack", "label", default="UNKNOWN")

    if score is None:
        return {"score": 0, "label": "NO_DATA", "available": False, "details": {}, "contribution": 0}

    details = {
        "crack_321_bbl":      safe(data, "spreads", "crack_321",      "value_bbl"),
        "gasoline_crack_bbl": safe(data, "spreads", "gasoline_crack", "value_bbl"),
        "ho_crack_bbl":       safe(data, "spreads", "ho_crack",       "value_bbl"),
        "brent_wti_bbl":      safe(data, "spreads", "brent_wti",      "value_bbl"),
        "brent_wti_alert":    safe(data, "spreads", "brent_wti",      "alert"),
        "curve_shape":        safe(data, "forward_curve", "estimated_shape"),
        "season_phase":       safe(data, "seasonal", "phase"),
    }

    return {
        "score":        score,
        "label":        label,
        "available":    True,
        "details":      details,
        "weight":       LAYER_WEIGHTS["crack"],
        "contribution": round(score * LAYER_WEIGHTS["crack"], 3),
    }


def get_macro_signal() -> dict:
    """
    Extract macro signal from fred_latest.json.
    Convert macro composite (BULLISH/BEARISH/MIXED) to -10/+10 scale.
    """
    data      = load_json("fred_latest.json")
    composite = safe(data, "derived", "macro_composite", "composite_signal", default="MIXED")
    dxy       = safe(data, "series", "dxy_broad",    "latest")
    sofr      = safe(data, "series", "sofr",         "latest")
    dgs10     = safe(data, "series", "us_10y_yield", "latest")
    fedfunds  = safe(data, "series", "fed_funds",    "latest")
    carry     = safe(data, "derived", "storage_carry", "total_carry_per_bbl_mo")

    if not dxy:
        return {"score": 0, "label": "NO_DATA", "available": False, "details": {}, "contribution": 0}

    # Build macro score from individual series
    score = 0

    # DXY: higher dollar = bearish oil
    dxy_wow = safe(data, "series", "dxy_broad", "wow")
    if dxy_wow is not None:
        if dxy_wow < -0.5:   score += 3   # dollar falling = bullish
        elif dxy_wow < -0.1: score += 1
        elif dxy_wow > 0.5:  score -= 3   # dollar rising = bearish
        elif dxy_wow > 0.1:  score -= 1

    # 10Y yield: falling yields = easier financial conditions = bullish
    dgs10_wow = safe(data, "series", "us_10y_yield", "wow")
    if dgs10_wow is not None:
        if dgs10_wow < -0.1:  score += 2
        elif dgs10_wow > 0.1: score -= 2

    # SOFR: higher = more expensive storage = bearish for inventory builds
    if sofr:
        if sofr < 3.0:   score += 1   # low rates = cheap storage, but bullish overall
        elif sofr > 5.0: score -= 1   # high rates = expensive carry

    # Clamp to -10/+10
    score = max(-10, min(10, score))

    details = {
        "dxy":        dxy,
        "sofr_pct":   sofr,
        "dgs10_pct":  dgs10,
        "fedfunds_pct": fedfunds,
        "carry_cost_per_bbl_mo": carry,
        "composite":  composite,
        "dxy_wow":    dxy_wow,
    }

    label = "BULLISH" if score > 1 else "BEARISH" if score < -1 else "NEUTRAL"

    return {
        "score":        score,
        "label":        label,
        "available":    True,
        "details":      details,
        "weight":       LAYER_WEIGHTS["macro"],
        "contribution": round(score * LAYER_WEIGHTS["macro"], 3),
    }


def get_demand_signal() -> dict:
    """
    Extract weather/demand signal from weather_latest.json.
    Convert BULLISH/NEUTRAL signal to -10/+10 scale.
    """
    data    = load_json("weather_latest.json")
    signal  = safe(data, "composite", "signal", default="NEUTRAL")
    hdd_wtd = safe(data, "composite", "weighted_hdd_7d")
    cdd_wtd = safe(data, "composite", "weighted_cdd_7d")

    if hdd_wtd is None and cdd_wtd is None:
        return {"score": 0, "label": "NO_DATA", "available": False, "details": {}, "contribution": 0}

    # Convert to score based on magnitude
    score = 0
    if cdd_wtd:
        if cdd_wtd > 50:   score += 5    # extreme cooling = strong power demand
        elif cdd_wtd > 30: score += 3
        elif cdd_wtd > 15: score += 1
    if hdd_wtd:
        if hdd_wtd > 40:   score += 5    # extreme heating = strong HO demand
        elif hdd_wtd > 25: score += 3
        elif hdd_wtd > 10: score += 1

    score = max(-10, min(10, score))

    # Key locations
    dubai_cdd = safe(data, "locations", "dubai",    "cdd_7d_forecast")
    tokyo_cdd = safe(data, "locations", "tokyo",    "cdd_7d_forecast")
    ny_hdd    = safe(data, "locations", "new_york", "hdd_7d_forecast")
    london_hdd= safe(data, "locations", "london",   "hdd_7d_forecast")

    details = {
        "weighted_hdd_7d": hdd_wtd,
        "weighted_cdd_7d": cdd_wtd,
        "dubai_cdd_7d":    dubai_cdd,
        "tokyo_cdd_7d":    tokyo_cdd,
        "ny_hdd_7d":       ny_hdd,
        "london_hdd_7d":   london_hdd,
        "composite":       signal,
    }

    return {
        "score":        score,
        "label":        signal,
        "available":    True,
        "details":      details,
        "weight":       LAYER_WEIGHTS["demand"],
        "contribution": round(score * LAYER_WEIGHTS["demand"], 3),
    }


def get_gie_signal() -> dict:
    """Extract EU gas storage signal from gie_latest.json."""
    data    = load_json("gie_latest.json")
    signal  = safe(data, "composite", "signal", default="NEUTRAL")
    score_r = safe(data, "composite", "score",  default=0)

    # GIE score comes in as -1 to +1 range, scale to -10/+10
    score = round(score_r * 10, 1)
    score = max(-10, min(10, score))

    details = {
        "composite": signal,
        "germany_fill":     safe(data, "regions", "germany",     "fill_pct"),
        "france_fill":      safe(data, "regions", "france",      "fill_pct"),
        "netherlands_fill": safe(data, "regions", "netherlands", "fill_pct"),
        "italy_fill":       safe(data, "regions", "italy",       "fill_pct"),
        "season":           safe(data, "season"),
    }

    return {
        "score":        score,
        "label":        signal,
        "available":    True,
        "details":      details,
        "weight":       LAYER_WEIGHTS["gie"],
        "contribution": round(score * LAYER_WEIGHTS["gie"], 3),
    }


def get_news_signal() -> dict:
    """Extract news score from news_signals.json."""
    data  = load_json("news_signals.json")
    ns    = data.get("news_score", {})
    score = ns.get("score")
    label = ns.get("label", "UNKNOWN")

    if score is None:
        return {"score": 0, "label": "NO_DATA", "available": False,
                "details": {}, "contribution": 0}

    details = {
        "bullish_count":  data.get("summary", {}).get("bullish_count"),
        "bearish_count":  data.get("summary", {}).get("bearish_count"),
        "geo_alerts":     data.get("summary", {}).get("geo_alerts"),
        "total_relevant": data.get("summary", {}).get("oil_relevant"),
        "top_bullish":    data.get("top_bullish",  [{}])[0].get("headline", "") if data.get("top_bullish")  else "",
        "top_bearish":    data.get("top_bearish",  [{}])[0].get("headline", "") if data.get("top_bearish")  else "",
    }

    return {
        "score":        score,
        "label":        label,
        "available":    True,
        "details":      details,
        "weight":       LAYER_WEIGHTS["news"],
        "contribution": round(score * LAYER_WEIGHTS["news"], 3),
    }


def get_positioning_signal() -> dict:
    """
    Extract CFTC positioning signal from cftc_latest.json.
    Crowded longs = mean-reversion risk (contrarian bearish).
    Crowded shorts = squeeze risk (contrarian bullish).
    Building longs = trend-following bullish.
    """
    data     = load_json("cftc_latest.json")
    composite= safe(data, "composite", "signal", default="NEUTRAL")
    crowded_l= safe(data, "composite", "crowded_longs",  default=[])
    crowded_s= safe(data, "composite", "crowded_shorts", default=[])

    # RBOB positioning (most current signal)
    rbob_pct = safe(data, "contracts", "rbob",        "net_pct_of_oi")
    wti_pct  = safe(data, "contracts", "wti",         "net_pct_of_oi")
    brent_pct= safe(data, "contracts", "brent",       "net_pct_of_oi")
    ng_signal= safe(data, "contracts", "natural_gas", "signal")

    if rbob_pct is None and wti_pct is None:
        return {"score": 0, "label": "NO_DATA", "available": False, "details": {}, "contribution": 0}

    # Score based on net positioning across crude contracts
    score = 0
    for pct in [rbob_pct, wti_pct, brent_pct]:
        if pct is None: continue
        if pct > 25:    score -= 3   # crowded long = mean-reversion risk
        elif pct > 10:  score += 2   # building longs = trend bullish
        elif pct < -15: score += 3   # crowded short = squeeze risk
        elif pct < -5:  score -= 2   # building shorts = trend bearish

    # Crowded positions are contrarian signals — dampen if extreme
    if crowded_l:
        score -= 2   # crowded longs across contracts = mean-reversion risk
    if crowded_s:
        score += 2   # crowded shorts = short squeeze potential

    score = max(-10, min(10, score))

    details = {
        "composite":    composite,
        "rbob_net_pct": rbob_pct,
        "wti_net_pct":  wti_pct,
        "brent_net_pct":brent_pct,
        "ng_signal":    ng_signal,
        "crowded_longs": crowded_l,
        "crowded_shorts": crowded_s,
    }

    label = "BULLISH" if score > 1 else "BEARISH" if score < -1 else "NEUTRAL"

    return {
        "score":        score,
        "label":        label,
        "available":    True,
        "details":      details,
        "weight":       LAYER_WEIGHTS["positioning"],
        "contribution": round(score * LAYER_WEIGHTS["positioning"], 3),
    }

# ── Main ──────────────────────────────────────────────────────────────────────

def compute_composite() -> dict:
    log.info("=" * 60)
    log.info("COMPOSITE SIGNAL SCORER — combining all signal layers")
    log.info("=" * 60)

    # Extract all layers
    layers = {
        "inventory":   get_inventory_signal(),
        "crack":       get_crack_signal(),
        "macro":       get_macro_signal(),
        "demand":      get_demand_signal(),
        "gie":         get_gie_signal(),
        "positioning": get_positioning_signal(),
        "news":        get_news_signal(),
    }

    # Log each layer
    log.info("")
    log.info("LAYER SCORES (weighted contributions)")
    log.info("─" * 60)
    total_weight = 0
    weighted_sum = 0

    for name, layer in layers.items():
        status = "✓" if layer["available"] else "✗"
        weight = LAYER_WEIGHTS[name]
        score  = layer["score"]
        contrib= round(score * weight, 3)

        log.info("  %s  %-12s  score=%+.1f  weight=%.0f%%  contrib=%+.2f",
                 status, name.upper(), score, weight * 100, contrib)

        if layer["available"]:
            weighted_sum += contrib
            total_weight += weight

    # Normalise: if some layers unavailable, scale up available ones
    if total_weight > 0 and total_weight < 1.0:
        weighted_sum = weighted_sum / total_weight

    # Final composite on -10/+10 scale
    composite_score = round(max(-10, min(10, weighted_sum * 10)), 2)

    # Signal label
    if composite_score >= 7:      label = "STRONG_BUY"
    elif composite_score >= 4:    label = "BUY"
    elif composite_score >= 1:    label = "MILD_BUY"
    elif composite_score >= -1:   label = "NEUTRAL"
    elif composite_score >= -4:   label = "MILD_SELL"
    elif composite_score >= -7:   label = "SELL"
    else:                         label = "STRONG_SELL"

    direction = (
        "BULLISH" if composite_score >= 1
        else "BEARISH" if composite_score <= -1
        else "NEUTRAL"
    )

    # Count bullish vs bearish layers
    bullish_layers = [n for n, l in layers.items() if l["score"] > 1]
    bearish_layers = [n for n, l in layers.items() if l["score"] < -1]
    neutral_layers = [n for n, l in layers.items() if -1 <= l["score"] <= 1]

    # Key alerts
    alerts = []
    bwti_alert = safe(layers["crack"], "details", "brent_wti_alert")
    if bwti_alert:
        alerts.append(bwti_alert)
    if layers["positioning"]["details"].get("crowded_longs"):
        alerts.append(f"CROWDED LONGS in: {layers['positioning']['details']['crowded_longs']} — mean-reversion risk")
    if safe(layers["inventory"], "details", "days_cover") and \
       safe(layers["inventory"], "details", "days_cover") < 54:
        alerts.append(f"CRITICAL: Days of cover below 54-day threshold — historically $90+ Brent")

    # Build output
    output = {
        "engine":          "nci_composite",
        "computed_at":     datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "date":            date.today().isoformat(),

        # Final signal
        "composite": {
            "score":          composite_score,
            "label":          label,
            "direction":      direction,
            "scale":          "Composite Signal Score (-10 to +10)",
            "interpretation": (
                f"Composite NCI {composite_score:+.1f} ({label}): "
                + {
                    "STRONG_BUY":  "Multiple signal layers converging bullish. High-conviction long setup.",
                    "BUY":         "Majority of signals bullish. Physical tightness confirmed by fundamentals.",
                    "MILD_BUY":    "Slight bullish edge. Monitor for confirmation from macro/positioning.",
                    "NEUTRAL":     "Signals mixed. No strong directional bias. Wait for catalyst.",
                    "MILD_SELL":   "Slight bearish edge. Monitor inventory builds and crack compression.",
                    "SELL":        "Majority bearish. Physical oversupply building. Risk of price decline.",
                    "STRONG_SELL": "Multiple layers converging bearish. High-conviction short setup.",
                }.get(label, "")
            ),
        },

        # Layer breakdown
        "layers": {
            name: {
                "score":        layer["score"],
                "label":        layer["label"],
                "weight_pct":   round(LAYER_WEIGHTS[name] * 100, 0),
                "contribution": layer["contribution"],
                "available":    layer["available"],
                "details":      layer["details"],
            }
            for name, layer in layers.items()
        },

        # Summary counts
        "signal_summary": {
            "bullish_layers": bullish_layers,
            "bearish_layers": bearish_layers,
            "neutral_layers": neutral_layers,
            "bullish_count":  len(bullish_layers),
            "bearish_count":  len(bearish_layers),
            "neutral_count":  len(neutral_layers),
        },

        # Alerts
        "alerts": alerts,

        # Weight table (for transparency)
        "weights_used": LAYER_WEIGHTS,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    # Final summary
    log.info("─" * 60)
    log.info("COMPOSITE SIGNAL SCORE:  %+.1f / 10  [%s]", composite_score, label)
    log.info("Direction:            %s", direction)
    log.info("Bullish layers (%d):  %s", len(bullish_layers), bullish_layers or "none")
    log.info("Bearish layers (%d):  %s", len(bearish_layers), bearish_layers or "none")
    log.info("Neutral layers (%d):  %s", len(neutral_layers), neutral_layers or "none")
    for alert in alerts:
        log.warning("⚠  %s", alert)
    log.info("Saved → %s", OUTPUT_PATH)
    log.info("=" * 60)

    return output


def run(full_refresh: bool = False) -> dict:
    if full_refresh:
        log.info("Running full refresh — executing all engines...")
        for script in ["backend/inventory_signals.py", "backend/crack_spread_engine.py",
                   "backend/fetchers/news_fetcher.py"]:
            subprocess.run([sys.executable, str(ROOT.parent / script)], check=False)

    return compute_composite()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NCI Composite Signal Engine")
    parser.add_argument("--full", action="store_true",
                        help="Re-run inventory and crack engines before compositing")
    args = parser.parse_args()
    run(full_refresh=args.full)

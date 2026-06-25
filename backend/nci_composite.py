"""
nci_composite.py
----------------
Day 6 — NCI Composite Signal Engine

Combines ALL signal layers into one final composite score:

  Layer 1 — Inventory (Day 4):      NCI inventory score (-10 to +10)
  Layer 2 — Crack Spreads (Day 5):  NCI crack score (-10 to +10)
  Layer 3 — Price Momentum (NEW):   5-week Brent trend vs rolling avg
  Layer 4 — Macro (FRED):           DXY + rates signal
  Layer 5 — Weather/Demand:         HDD/CDD demand signal
  Layer 6 — Positioning (CFTC):     Speculative crowding signal
  Layer 7 — GIE Gas Storage:        EU gas → distillate demand
  Layer 8 — News:                   News sentiment — breaking events, geo risk

Final output: COMPOSITE SIGNAL SCORE (-10 to +10)

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

from __future__ import annotations
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
# Rebalanced to include price momentum layer.
# Inventory + crack remain the primary fundamental drivers.
# Price momentum added at 15% — enough to pull a STRONG_BUY to BUY
# when price has been trending down for 5 weeks, without dominating.

LAYER_WEIGHTS = {
    "inventory":   0.230,  # Days cover, Cushing, 5yr deviation — most direct
    "crack":       0.180,  # Refinery margins — crude demand signal
    "momentum":    0.135,  # 5-week Brent price trend vs rolling avg
    "macro":       0.115,  # DXY, rates — financial backdrop
    "positioning": 0.090,  # CFTC — sentiment/crowding
    "news":        0.070,  # News sentiment — breaking events, geo risk
    "demand":      0.080,  # Weather HDD/CDD demand signal
    "steo":        0.055,  # EIA STEO monthly global balance overlay (NEW)
    "gie":         0.045,  # EU gas storage
}
# Sum = 1.000 exactly (verified). Previous version summed to 1.05 — a pre-existing
# bug that silently inflated the composite by ~5% whenever all 8 layers were
# available, since the total_weight<1.0 normalization check never triggered.
# Relative ranking between layers is unchanged from before; only the absolute
# scale was corrected and STEO was added.

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
    """Extract inventory score from inventory_signals.json.

    File structure: d["composite"]["score"] + d["composite"]["overall_signal"]
    Individual signals live under d["signals"][key].
    """
    data  = load_json("inventory_signals.json")

    # Correct key path: composite.score / composite.overall_signal
    score = safe(data, "composite", "score")
    label = safe(data, "composite", "overall_signal", default="UNKNOWN")

    if score is None:
        return {"score": 0, "label": "NO_DATA", "available": False, "details": {}, "contribution": 0}

    # Pull individual signal details from d["signals"]
    sigs = data.get("signals", {})
    details = {
        "days_cover":       safe(sigs, "days_cover",         "value"),
        "cushing_signal":   safe(sigs, "cushing_stocks",     "signal"),
        "gasoline_signal":  safe(sigs, "gasoline_stocks",    "signal"),
        "distillate_signal":safe(sigs, "distillate_stocks",  "signal"),
        "refinery_util":    safe(sigs, "refinery_util",      "value"),
        "gie_signal":       safe(sigs, "gie_storage",        "signal"),
        "components":       data.get("composite", {}).get("components", []),
    }

    return {
        "score":        score,
        "label":        label,
        "available":    True,
        "details":      details,
        "weight":       LAYER_WEIGHTS["inventory"],
        "contribution": round(score * LAYER_WEIGHTS["inventory"], 3),
    }


def get_crack_signal() -> dict:
    """Extract crack score from crack_signals.json"""
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


def get_momentum_signal() -> dict:
    """
    5-week price momentum layer — averaged across Brent AND WTI.

    Using both benchmarks avoids over-relying on one. When Brent and WTI
    diverge (Cushing bottleneck, North Sea disruption), the divergence itself
    is a signal captured separately in the crack/spread layers — here we want
    the broad flat-price trend, so averaging removes single-benchmark noise.

    Scoring bands (% deviation from 5-week avg, applied to the Brent+WTI avg):
      > +8%   = +8
      +4..8%  = +5
      +2..4%  = +3
      +1..2%  = +1
      -1..+1% = 0
      -2..-1% = -1
      -4..-2% = -3
      -8..-4% = -5
      < -8%   = -8

    Capped at ±8: price trend should confirm fundamentals, not override them.
    """
    history = load_json("price_history.json")

    if not isinstance(history, list) or len(history) < 10:
        return {
            "score": 0, "label": "NO_DATA", "available": False,
            "details": {"reason": "insufficient history"},
            "weight": LAYER_WEIGHTS["momentum"], "contribution": 0,
        }

    # Sort oldest→newest, keep rows that have at least Brent
    rows = sorted(
        [r for r in history if isinstance(r.get("brent"), (int, float))],
        key=lambda r: r.get("date", ""),
    )

    if len(rows) < 10:
        return {
            "score": 0, "label": "NO_DATA", "available": False,
            "details": {"reason": "insufficient data points"},
            "weight": LAYER_WEIGHTS["momentum"], "contribution": 0,
        }

    def _price_avg(row):
        """Return Brent+WTI average if both available, else Brent alone."""
        b = row.get("brent")
        w = row.get("wti")
        if isinstance(b, (int, float)) and isinstance(w, (int, float)):
            return (b + w) / 2
        return b if isinstance(b, (int, float)) else None

    today_row    = rows[-1]
    today_price  = _price_avg(today_row)
    today_brent  = today_row.get("brent")
    today_wti    = today_row.get("wti")
    today_date   = today_row.get("date", "unknown")

    if today_price is None:
        return {
            "score": 0, "label": "NO_DATA", "available": False,
            "details": {"reason": "no price in latest row"},
            "weight": LAYER_WEIGHTS["momentum"], "contribution": 0,
        }

    # 5-week avg (up to 35 days), excluding today
    lookback_rows = rows[:-1][-35:]
    if len(lookback_rows) < 5:
        return {
            "score": 0, "label": "NO_DATA", "available": False,
            "details": {"reason": f"only {len(lookback_rows)} history rows before today"},
            "weight": LAYER_WEIGHTS["momentum"], "contribution": 0,
        }

    avgs_5w  = [_price_avg(r) for r in lookback_rows if _price_avg(r) is not None]
    avg_5w   = sum(avgs_5w) / len(avgs_5w)
    dev_pct  = ((today_price - avg_5w) / avg_5w) * 100

    # 5-day avg for context (used in divergence flag + DivergenceFlag UI)
    last5_rows = rows[:-1][-5:]
    avgs_5d    = [_price_avg(r) for r in last5_rows if _price_avg(r) is not None]
    avg_5d     = sum(avgs_5d) / len(avgs_5d) if len(avgs_5d) >= 3 else None
    dev_5d_pct = ((today_price - avg_5d) / avg_5d * 100) if avg_5d else None

    # Individual Brent / WTI deviations (for display in DivergenceFlag)
    brent_5w_rows = [r["brent"] for r in lookback_rows if isinstance(r.get("brent"), (int, float))]
    wti_5w_rows   = [r["wti"]   for r in lookback_rows if isinstance(r.get("wti"),   (int, float))]
    avg_5w_brent  = sum(brent_5w_rows) / len(brent_5w_rows) if brent_5w_rows else None
    avg_5w_wti    = sum(wti_5w_rows)   / len(wti_5w_rows)   if wti_5w_rows   else None
    dev_brent_5w  = ((today_brent - avg_5w_brent) / avg_5w_brent * 100) if avg_5w_brent and today_brent else None
    dev_wti_5w    = ((today_wti   - avg_5w_wti)   / avg_5w_wti   * 100) if avg_5w_wti   and today_wti   else None

    # Score mapping
    if dev_pct > 8:       score =  8
    elif dev_pct > 4:     score =  5
    elif dev_pct > 2:     score =  3
    elif dev_pct > 1:     score =  1
    elif dev_pct > -1:    score =  0
    elif dev_pct > -2:    score = -1
    elif dev_pct > -4:    score = -3
    elif dev_pct > -8:    score = -5
    else:                 score = -8

    label = (
        "UPTREND"         if score >= 3
        else "MILD_UPTREND"   if score == 1
        else "FLAT"           if score == 0
        else "MILD_DOWNTREND" if score == -1
        else "DOWNTREND"      if score <= -3
        else "NEUTRAL"
    )

    details = {
        "today_brent":        round(today_brent, 2) if today_brent else None,
        "today_wti":          round(today_wti,   2) if today_wti   else None,
        "today_avg":          round(today_price, 2),
        "today_date":         today_date,
        "avg_5w":             round(avg_5w, 2),
        "avg_5d":             round(avg_5d, 2) if avg_5d else None,
        "dev_from_5w_pct":    round(dev_pct, 2),
        "dev_from_5d_pct":    round(dev_5d_pct, 2) if dev_5d_pct is not None else None,
        "dev_brent_5w_pct":   round(dev_brent_5w, 2) if dev_brent_5w is not None else None,
        "dev_wti_5w_pct":     round(dev_wti_5w,   2) if dev_wti_5w   is not None else None,
        "avg_5w_brent":       round(avg_5w_brent, 2) if avg_5w_brent else None,
        "avg_5w_wti":         round(avg_5w_wti,   2) if avg_5w_wti   else None,
        "lookback_days_used": len(lookback_rows),
        "trend_direction":    "UP" if dev_pct > 1 else "DOWN" if dev_pct < -1 else "FLAT",
        "benchmark_note":     "Brent+WTI averaged" if today_wti else "Brent only (WTI unavailable)",
    }

    log.info(
        "  MOMENTUM  Brent=$%.2f WTI=$%.2f avg=$%.2f  5w_avg=$%.2f  dev=%+.1f%%  score=%+d  [%s]",
        today_brent or 0, today_wti or 0, today_price,
        avg_5w, dev_pct, score, label,
    )

    return {
        "score":        score,
        "label":        label,
        "available":    True,
        "details":      details,
        "weight":       LAYER_WEIGHTS["momentum"],
        "contribution": round(score * LAYER_WEIGHTS["momentum"], 3),
    }


def get_macro_signal() -> dict:
    """
    Extract macro signal from fred_latest.json.
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

    score = 0

    dxy_wow = safe(data, "series", "dxy_broad", "wow")
    if dxy_wow is not None:
        if dxy_wow < -0.5:   score += 3
        elif dxy_wow < -0.1: score += 1
        elif dxy_wow > 0.5:  score -= 3
        elif dxy_wow > 0.1:  score -= 1

    dgs10_wow = safe(data, "series", "us_10y_yield", "wow")
    if dgs10_wow is not None:
        if dgs10_wow < -0.1:  score += 2
        elif dgs10_wow > 0.1: score -= 2

    if sofr:
        if sofr < 3.0:   score += 1
        elif sofr > 5.0: score -= 1

    score = max(-10, min(10, score))

    details = {
        "dxy":                   dxy,
        "sofr_pct":              sofr,
        "dgs10_pct":             dgs10,
        "fedfunds_pct":          fedfunds,
        "carry_cost_per_bbl_mo": carry,
        "composite":             composite,
        "dxy_wow":               dxy_wow,
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
    """Extract weather/demand signal from weather_latest.json."""
    data    = load_json("weather_latest.json")
    signal  = safe(data, "composite", "signal", default="NEUTRAL")
    hdd_wtd = safe(data, "composite", "weighted_hdd_7d")
    cdd_wtd = safe(data, "composite", "weighted_cdd_7d")

    if hdd_wtd is None and cdd_wtd is None:
        return {"score": 0, "label": "NO_DATA", "available": False, "details": {}, "contribution": 0}

    score = 0
    if cdd_wtd:
        if cdd_wtd > 50:   score += 5
        elif cdd_wtd > 30: score += 3
        elif cdd_wtd > 15: score += 1
    if hdd_wtd:
        if hdd_wtd > 40:   score += 5
        elif hdd_wtd > 25: score += 3
        elif hdd_wtd > 10: score += 1

    score = max(-10, min(10, score))

    details = {
        "weighted_hdd_7d": hdd_wtd,
        "weighted_cdd_7d": cdd_wtd,
        "dubai_cdd_7d":    safe(data, "locations", "dubai",    "cdd_7d_forecast"),
        "tokyo_cdd_7d":    safe(data, "locations", "tokyo",    "cdd_7d_forecast"),
        "ny_hdd_7d":       safe(data, "locations", "new_york", "hdd_7d_forecast"),
        "london_hdd_7d":   safe(data, "locations", "london",   "hdd_7d_forecast"),
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

    score = round(score_r * 10, 1)
    score = max(-10, min(10, score))

    details = {
        "composite":        signal,
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


def get_steo_signal() -> dict:
    """
    Layer 9 — EIA STEO monthly global supply/demand balance.
    Bullish when global balance shows a draw (consumption > production);
    bearish on a build. Slow-moving — updates ~monthly, not weekly.
    """
    data = load_json("steo_latest.json")
    balance = data.get("global_balance_mbd") if data else None

    if balance is None:
        return {"score": 0, "label": "NO_DATA", "available": False,
                "details": {}, "contribution": 0}

    # -10/+10 scale: a 2.0 mbd draw maps to +10 (full bullish), a 2.0 mbd build to -10.
    # 2.0 mbd is a wide global balance move outside crisis periods; clamp protects
    # against runaway scores during genuine supply shocks (e.g. Hormuz-type events).
    score = max(-10, min(10, round(-balance / 2.0 * 10, 2)))
    label = data.get("global_balance_signal", "UNKNOWN")

    details = {
        "report_period":      data.get("report_period_latest"),
        "world_production":   data.get("world_production_mbd"),
        "world_consumption":  data.get("world_consumption_mbd"),
        "call_on_opec_mbd":   data.get("call_on_opec_mbd"),
        "opec_actual_mbd":    data.get("opec_actual_production_mbd"),
        "opec_vs_call_mbd":   data.get("opec_vs_call_mbd"),
        "opec_balance_signal":data.get("opec_balance_signal"),
        "spare_capacity_mbd": data.get("spare_capacity_mbd"),
    }

    log.info("  STEO  balance=%+.2f mbd  call_on_opec=%s  opec_vs_call=%s  [%s]",
              balance, data.get("call_on_opec_mbd"), data.get("opec_vs_call_mbd"), label)

    return {
        "score":        score,
        "label":        label,
        "available":    True,
        "details":      details,
        "weight":       LAYER_WEIGHTS["steo"],
        "contribution": round(score * LAYER_WEIGHTS["steo"], 3),
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
    """Extract CFTC positioning signal from cftc_latest.json."""
    data      = load_json("cftc_latest.json")
    composite = safe(data, "composite", "signal", default="NEUTRAL")
    crowded_l = safe(data, "composite", "crowded_longs",  default=[])
    crowded_s = safe(data, "composite", "crowded_shorts", default=[])

    rbob_pct  = safe(data, "contracts", "rbob",        "net_pct_of_oi")
    wti_pct   = safe(data, "contracts", "wti",         "net_pct_of_oi")
    brent_pct = safe(data, "contracts", "brent",       "net_pct_of_oi")
    ng_signal = safe(data, "contracts", "natural_gas", "signal")

    if rbob_pct is None and wti_pct is None:
        return {"score": 0, "label": "NO_DATA", "available": False, "details": {}, "contribution": 0}

    score = 0
    for pct in [rbob_pct, wti_pct, brent_pct]:
        if pct is None: continue
        if pct > 25:    score -= 3
        elif pct > 10:  score += 2
        elif pct < -15: score += 3
        elif pct < -5:  score -= 2

    if crowded_l: score -= 2
    if crowded_s: score += 2

    score = max(-10, min(10, score))

    details = {
        "composite":      composite,
        "rbob_net_pct":   rbob_pct,
        "wti_net_pct":    wti_pct,
        "brent_net_pct":  brent_pct,
        "ng_signal":      ng_signal,
        "crowded_longs":  crowded_l,
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


# ── Divergence detector ───────────────────────────────────────────────────────

def detect_divergence(composite_score: float, momentum_layer: dict) -> dict | None:
    """
    Returns a divergence flag when composite direction and price trend disagree.

    Divergence = composite says BUY/STRONG_BUY but price is in DOWNTREND, or
                 composite says SELL/STRONG_SELL but price is in UPTREND.

    This is analytically meaningful: fundamentals are leading (or lagging) price.
    """
    mom_details   = momentum_layer.get("details", {})
    trend_dir     = mom_details.get("trend_direction", "FLAT")
    dev_5w        = mom_details.get("dev_from_5w_pct")
    dev_5d        = mom_details.get("dev_from_5d_pct")
    avg_5w        = mom_details.get("avg_5w")
    today_brent   = mom_details.get("today_brent")

    if dev_5w is None:
        return None

    composite_bull = composite_score >= 4     # BUY or above
    composite_bear = composite_score <= -4    # SELL or below
    price_down     = dev_5w < -3              # >3% below 5w avg = clear downtrend
    price_up       = dev_5w >  3              # >3% above 5w avg = clear uptrend

    if composite_bull and price_down:
        severity = "STRONG" if composite_score >= 7 and dev_5w < -6 else "MODERATE"
        return {
            "type":     "BULL_FUNDAMENTAL_BEAR_PRICE",
            "severity": severity,
            "message":  (
                f"Fundamentals bullish ({composite_score:+.1f}) "
                f"but Brent {dev_5w:+.1f}% below 5-week avg (${avg_5w:.1f}). "
                f"Watch for price confirmation or fundamental deterioration."
            ),
            "composite_score": composite_score,
            "dev_5w_pct":      round(dev_5w, 2),
            "dev_5d_pct":      round(dev_5d, 2) if dev_5d is not None else None,
            "today_brent":     today_brent,
            "avg_5w":          avg_5w,
        }

    if composite_bear and price_up:
        severity = "STRONG" if composite_score <= -7 and dev_5w > 6 else "MODERATE"
        return {
            "type":     "BEAR_FUNDAMENTAL_BULL_PRICE",
            "severity": severity,
            "message":  (
                f"Fundamentals bearish ({composite_score:+.1f}) "
                f"but Brent {dev_5w:+.1f}% above 5-week avg (${avg_5w:.1f}). "
                f"Price rally may not be supported by fundamentals."
            ),
            "composite_score": composite_score,
            "dev_5w_pct":      round(dev_5w, 2),
            "dev_5d_pct":      round(dev_5d, 2) if dev_5d is not None else None,
            "today_brent":     today_brent,
            "avg_5w":          avg_5w,
        }

    return None


# ── Main ──────────────────────────────────────────────────────────────────────

def compute_composite() -> dict:
    log.info("=" * 60)
    log.info("COMPOSITE SIGNAL SCORER — combining all signal layers")
    log.info("=" * 60)

    layers = {
        "inventory":   get_inventory_signal(),
        "crack":       get_crack_signal(),
        "momentum":    get_momentum_signal(),       
        "macro":       get_macro_signal(),
        "demand":      get_demand_signal(),
        "gie":         get_gie_signal(),
        "positioning": get_positioning_signal(),
        "news":        get_news_signal(),
        "steo":        get_steo_signal(),       # NEW  
    }

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

    # Normalise if some layers unavailable
    if total_weight > 0 and total_weight < 1.0:
        weighted_sum = weighted_sum / total_weight

    # weighted_sum is already on the -10/+10 scale (each layer scores -10→+10,
    # multiplied by weights that sum to 1.0). Do NOT multiply by 10 again.
    composite_score = round(max(-10, min(10, weighted_sum)), 2)

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

    bullish_layers = [n for n, l in layers.items() if l["score"] > 1]
    bearish_layers = [n for n, l in layers.items() if l["score"] < -1]
    neutral_layers = [n for n, l in layers.items() if -1 <= l["score"] <= 1]

    # Divergence check
    divergence = detect_divergence(composite_score, layers["momentum"])

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
    if divergence:
        alerts.append(f"DIVERGENCE ({divergence['severity']}): {divergence['message']}")

    output = {
        "engine":      "nci_composite",
        "computed_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "date":        date.today().isoformat(),

        "composite": {
            "score":          composite_score,
            "label":          label,
            "direction":      direction,
            "scale":          "Composite Signal Score (-10 to +10)",
            "interpretation": (
                f"Composite {composite_score:+.1f} ({label}): "
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
            # Expose momentum context directly on composite for frontend use
            "momentum": {
                "today_brent":     layers["momentum"]["details"].get("today_brent"),
                "avg_5w":          layers["momentum"]["details"].get("avg_5w"),
                "avg_5d":          layers["momentum"]["details"].get("avg_5d"),
                "dev_from_5w_pct": layers["momentum"]["details"].get("dev_from_5w_pct"),
                "dev_from_5d_pct": layers["momentum"]["details"].get("dev_from_5d_pct"),
                "trend_direction": layers["momentum"]["details"].get("trend_direction"),
                "label":           layers["momentum"]["label"],
            },
            "divergence": divergence,
            "reasons": alerts,
        },

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

        "signal_summary": {
            "bullish_layers": bullish_layers,
            "bearish_layers": bearish_layers,
            "neutral_layers": neutral_layers,
            "bullish_count":  len(bullish_layers),
            "bearish_count":  len(bearish_layers),
            "neutral_count":  len(neutral_layers),
        },

        "alerts":       alerts,
        "weights_used": LAYER_WEIGHTS,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    log.info("─" * 60)
    log.info("COMPOSITE SIGNAL SCORE:  %+.1f / 10  [%s]", composite_score, label)
    log.info("Direction:               %s", direction)
    log.info("Bullish layers (%d):     %s", len(bullish_layers), bullish_layers or "none")
    log.info("Bearish layers (%d):     %s", len(bearish_layers), bearish_layers or "none")
    log.info("Neutral  layers (%d):    %s", len(neutral_layers), neutral_layers or "none")
    mom = layers["momentum"]["details"]
    if mom.get("avg_5w"):
        log.info(
            "Momentum:                Brent $%.2f  5w_avg $%.2f  dev %+.1f%%  [%s]",
            mom.get("today_brent", 0), mom.get("avg_5w", 0),
            mom.get("dev_from_5w_pct", 0), layers["momentum"]["label"],
        )
    if divergence:
        log.warning("⚠  DIVERGENCE (%s): %s", divergence["severity"], divergence["message"])
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
    parser = argparse.ArgumentParser(description="Composite Signal Engine")
    parser.add_argument("--full", action="store_true",
                        help="Re-run inventory and crack engines before compositing")
    args = parser.parse_args()
    run(full_refresh=args.full)

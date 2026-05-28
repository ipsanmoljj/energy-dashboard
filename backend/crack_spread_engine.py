"""
crack_spread_engine.py
----------------------
Day 5 — Crack Spread & Forward Curve Signal Engine

Reads futures prices (futures_latest.json) and EIA refinery data
and computes:

  1. 3-2-1 Crack Spread       — gross US refinery margin ($/bbl)
  2. Gasoline Crack            — RBOB vs WTI ($/bbl)
  3. HO-RBOB Spread            — diesel premium over gasoline
  4. Brent-WTI Spread          — US export/import signal
  5. Forward Curve Shape       — contango vs backwardation signal
  6. Seasonal Crack Context    — where we are in the crack cycle
  7. NCI Crack Score           — -10 to +10 contribution to composite

Key thresholds (from OilMacroTrading book):
  3-2-1 crack > $20/bbl  → product demand outpacing crude → BULLISH crude
  3-2-1 crack < $12/bbl  → margins compressed → runs cut → BEARISH crude
  Brent-WTI > $8/bbl     → US export bottleneck or North Sea disruption
  Brent-WTI < $2/bbl     → US exports flooding market

Saves to: backend/data/crack_signals.json

Usage:
  python backend/crack_spread_engine.py            # uses cached futures data
  python backend/crack_spread_engine.py --refresh  # re-fetches futures first
"""

import argparse
import json
import logging
import sys
from datetime import datetime, date
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────

ROOT         = Path(__file__).resolve().parent
DATA_DIR     = ROOT / "data"
FUTURES_PATH = DATA_DIR / "futures_latest.json"
EIA_PATH     = DATA_DIR / "eia_latest.json"
OUTPUT_PATH  = DATA_DIR / "crack_signals.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Historical crack spread averages ($/bbl) ──────────────────────────────────
# Source: EIA, CME historical data 2019-2024 seasonal averages
# Used to compute deviation from seasonal norm

CRACK_321_5YR_AVG = {
    1: 18.5, 2: 19.2, 3: 22.1, 4: 24.3, 5: 25.8,  6: 26.4,
    7: 25.1, 8: 23.8, 9: 21.4, 10: 19.6, 11: 18.2, 12: 17.8,
}

GASOLINE_CRACK_5YR_AVG = {
    1: 14.2, 2: 16.8, 3: 21.4, 4: 24.6, 5: 26.2, 6: 27.1,
    7: 25.8, 8: 23.2, 9: 19.8, 10: 15.4, 11: 13.6, 12: 13.1,
}

HO_CRACK_5YR_AVG = {
    1: 28.4, 2: 27.1, 3: 24.8, 4: 22.3, 5: 21.4, 6: 20.8,
    7: 20.2, 8: 21.6, 9: 23.4, 10: 26.8, 11: 29.2, 12: 30.1,
}

BRENT_WTI_5YR_AVG = {
    1: 4.2, 2: 4.5, 3: 4.8, 4: 4.6, 5: 4.3, 6: 4.1,
    7: 3.9, 8: 3.8, 9: 3.9, 10: 4.0, 11: 4.2, 12: 4.3,
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception as e:
        log.warning("Could not load %s: %s", path.name, e)
        return {}

def safe(data, *keys, default=None):
    val = data
    for k in keys:
        val = val.get(k, default) if isinstance(val, dict) else default
    return val

def deviation(current, avg):
    if current is None or avg is None: return None
    return round(current - avg, 2)

def deviation_pct(current, avg):
    if current is None or avg is None or avg == 0: return None
    return round((current - avg) / avg * 100, 2)

# ── Crack spread calculations ─────────────────────────────────────────────────

def compute_321_crack(wti, rbob_bbl, ho_bbl):
    """
    3-2-1 crack spread: [(2×RBOB + 1×HO) - (3×WTI)] / 3
    All inputs in $/bbl. RBOB and HO must be converted from $/gal first (×42).
    Returns None if any input missing.
    """
    if None in (wti, rbob_bbl, ho_bbl):
        return None
    return round(((2 * rbob_bbl) + (1 * ho_bbl) - (3 * wti)) / 3, 2)

def compute_gasoline_crack(rbob_bbl, wti):
    """RBOB crack: RBOB - WTI ($/bbl)"""
    if None in (rbob_bbl, wti): return None
    return round(rbob_bbl - wti, 2)

def compute_ho_crack(ho_bbl, brent):
    """HO/gasoil crack: HO - Brent ($/bbl) — European-style"""
    if None in (ho_bbl, brent): return None
    return round(ho_bbl - brent, 2)

def compute_ho_rbob_spread(ho_bbl, rbob_bbl):
    """Diesel premium over gasoline: HO - RBOB ($/bbl)"""
    if None in (ho_bbl, rbob_bbl): return None
    return round(ho_bbl - rbob_bbl, 2)

# ── Scoring functions (-5 to +5) ──────────────────────────────────────────────

def score_crack_321(crack):
    """
    3-2-1 crack score.
    Wide crack → product demand > crude supply → refiners run harder → crude demand UP → BULLISH
    Narrow crack → margins compressed → runs cut → crude demand DOWN → BEARISH

    Thresholds from OilMacroTrading book:
      > $25/bbl = very wide (strong product demand)
      > $20/bbl = wide (bullish crude demand signal)
      $12-20    = normal range
      < $12/bbl = compressed (bearish)
      < $8/bbl  = very compressed (runs being cut)
    """
    if crack is None: return 0
    if crack > 30:    return 5
    elif crack > 25:  return 4
    elif crack > 20:  return 2
    elif crack > 15:  return 1
    elif crack > 12:  return 0
    elif crack > 8:   return -2
    elif crack > 5:   return -3
    else:             return -5

def score_gasoline_crack(crack, month):
    """
    Gasoline crack score with seasonal context.
    Feb-May: driving season build = higher threshold for bullish
    Jun-Sep: peak driving season
    Oct-Jan: shoulder/winter = lower baseline
    """
    if crack is None: return 0
    # Seasonal adjustment
    if month in {2, 3, 4, 5}:       # spring build season
        thresholds = (28, 22, 16, 10, 6)
    elif month in {6, 7, 8, 9}:     # peak driving
        thresholds = (30, 24, 18, 12, 8)
    else:                            # shoulder/winter
        thresholds = (22, 16, 12, 8, 4)

    t5, t4, t2, tn2, tn4 = thresholds
    if crack > t5:   return 5
    elif crack > t4: return 4
    elif crack > t2: return 2
    elif crack > 0:  return 1
    elif crack > tn2:return -2
    elif crack > tn4:return -4
    else:            return -5

def score_brent_wti(spread):
    """
    Brent-WTI spread score.
    Signal thresholds from OilMacroTrading book:
      > $8   = ALERT: US export bottleneck OR North Sea disruption
      $2-8   = normal range
      < $2   = US exports flooding market
    """
    if spread is None: return 0
    if spread > 10:   return -2   # extreme = North Sea disruption = Brent overpriced
    elif spread > 8:  return -1   # US bottleneck warning
    elif spread > 4:  return 0    # normal upper range
    elif spread > 2:  return 1    # US exports healthy
    elif spread > 0:  return 2    # tight Brent-WTI = US supply competitive
    else:             return -1   # inverted = unusual

def score_seasonal_crack_position(crack_321, month):
    """
    How does the current crack compare to seasonal 5yr average?
    Above seasonal norm = strong product demand = bullish crude.
    """
    avg = CRACK_321_5YR_AVG.get(month)
    if crack_321 is None or avg is None: return 0
    dev = crack_321 - avg
    if dev > 10:    return 3
    elif dev > 5:   return 2
    elif dev > 1:   return 1
    elif dev > -1:  return 0
    elif dev > -5:  return -1
    elif dev > -10: return -2
    else:           return -3

def score_ho_rbob_spread(spread, month):
    """
    HO-RBOB spread: diesel premium over gasoline.
    Wide in winter (Oct-Mar) = normal.
    Wide in summer (Apr-Sep) = diesel surprisingly tight = BULLISH.
    """
    if spread is None: return 0
    is_winter = month in {10, 11, 12, 1, 2, 3}

    if is_winter:
        # In winter, wide HO-RBOB is normal — only very wide is bullish
        if spread > 20:   return 2
        elif spread > 10: return 0
        elif spread < 0:  return -2
        else:             return 0
    else:
        # In summer, wide HO-RBOB = diesel surprisingly tight vs gasoline
        if spread > 15:   return 3
        elif spread > 8:  return 1
        elif spread < 0:  return -1
        else:             return 0

# ── Seasonal context ──────────────────────────────────────────────────────────

def get_seasonal_context(month):
    """Return the crack spread seasonal context for the current month."""
    contexts = {
        1:  {"phase": "WINTER_SHOULDER",  "dominant_product": "heating_oil", "note": "Low gasoline demand. Heating oil key. Crack spreads seasonally low."},
        2:  {"phase": "PRE_DRIVE_BUILD",  "dominant_product": "gasoline",    "note": "Refiners rebuilding gasoline stock ahead of summer. RBOB crack seasonally rising."},
        3:  {"phase": "SPRING_TURNAROUND","dominant_product": "gasoline",    "note": "Refinery maintenance reduces runs. Product tight. Crack spreads historically peak Feb-May."},
        4:  {"phase": "SPRING_TURNAROUND","dominant_product": "gasoline",    "note": "Turnarounds ending. Long RBOB crack vs WTI most reliable seasonal trade."},
        5:  {"phase": "DRIVING_SEASON",   "dominant_product": "gasoline",    "note": "Memorial Day marks US driving season start. Peak gasoline demand incoming."},
        6:  {"phase": "PEAK_DRIVING",     "dominant_product": "gasoline",    "note": "Peak US driving + EM A/C power demand. Highest crack spread month historically."},
        7:  {"phase": "PEAK_DRIVING",     "dominant_product": "gasoline",    "note": "July 4th + summer peak. Gasoline demand at annual high."},
        8:  {"phase": "LATE_SUMMER",      "dominant_product": "gasoline",    "note": "Driving season easing. Watch for crack softening late August."},
        9:  {"phase": "AUTUMN_TURN",      "dominant_product": "distillate",  "note": "Driving season ends. Refinery fall turnarounds. Diesel/heating oil season begins."},
        10: {"phase": "WINTER_BUILD",     "dominant_product": "heating_oil", "note": "Heating oil demand builds. Oct-Nov = most reliable window for long HO crack."},
        11: {"phase": "WINTER_PEAK",      "dominant_product": "heating_oil", "note": "Peak heating oil demand risk. Distillate stocks critical. Watch EIA Thursday."},
        12: {"phase": "WINTER_PEAK",      "dominant_product": "heating_oil", "note": "Winter peak. Low seasonal gasoline demand. Distillate dominates crack."},
    }
    return contexts.get(month, {"phase": "UNKNOWN", "dominant_product": "crude", "note": ""})

# ── Forward curve shape signal ─────────────────────────────────────────────────

def compute_curve_signal(brent_price, brent_wti_spread, refinery_util, cushing_util_pct):
    """
    Infer forward curve shape from available spot data.
    Without full futures strip, we use proxy signals:
      - Brent-WTI spread direction
      - Refinery utilisation
      - Cushing utilisation
      - Storage carry cost (from FRED SOFR)

    Returns estimated curve shape and confidence.
    """
    signals = []
    score   = 0

    # High refinery util = strong prompt demand = backwardation signal
    if refinery_util:
        if refinery_util > 92:
            signals.append("High refinery util (>92%) → physical demand strong → backwardation pressure")
            score += 2
        elif refinery_util > 88:
            signals.append("Normal refinery util → balanced curve")
            score += 0
        else:
            signals.append("Low refinery util (<88%) → demand weak → contango pressure")
            score -= 1

    # Low Cushing = tight prompt supply = backwardation
    if cushing_util_pct:
        if cushing_util_pct < 35:
            signals.append(f"Cushing only {cushing_util_pct:.0f}% full → tight prompt crude → backwardation")
            score += 2
        elif cushing_util_pct > 70:
            signals.append(f"Cushing {cushing_util_pct:.0f}% full → ample storage → contango pressure")
            score -= 2

    # Brent-WTI spread: narrow = US competitive = balanced/backwardated
    if brent_wti_spread is not None:
        if 2 < brent_wti_spread < 6:
            signals.append("Normal Brent-WTI spread → US exports flowing → balanced")
            score += 0
        elif brent_wti_spread > 8:
            signals.append("Wide Brent-WTI → US export bottleneck → local oversupply signal")
            score -= 1

    if score >= 3:
        shape = "BACKWARDATION"
        note  = "Physical market signals point to prompt tightness. M1-M2 likely in backwardation."
    elif score >= 1:
        shape = "MILD_BACKWARDATION"
        note  = "Modest physical tightness. Curve likely slightly backwardated."
    elif score <= -2:
        shape = "CONTANGO"
        note  = "Storage building signals. Curve likely in contango."
    else:
        shape = "FLAT"
        note  = "Balanced physical market. Curve near flat."

    return {
        "estimated_shape": shape,
        "score":           score,
        "signals":         signals,
        "note":            note,
        "storage_economic": score <= -1,
        "context": (
            "Full curve shape requires M1-M12 strip data (Day 9 FastAPI will add this). "
            "Current estimate based on Cushing util, refinery runs, and Brent-WTI spread."
        ),
    }

# ── Main ──────────────────────────────────────────────────────────────────────

def compute_crack_signals() -> dict:
    futures = load_json(FUTURES_PATH)
    eia     = load_json(EIA_PATH)
    month   = date.today().month

    # ── Extract futures prices ────────────────────────────────────────────────
    brent    = safe(futures, "contracts", "brent",       "price_bbl")
    wti      = safe(futures, "contracts", "wti",         "price_bbl")
    rbob_bbl = safe(futures, "contracts", "rbob",        "price_bbl")
    ho_bbl   = safe(futures, "contracts", "heating_oil", "price_bbl")
    ice_gasoil_bbl = safe(futures, "contracts", "ice_gasoil", "price_bbl")

    # ── Extract EIA data ──────────────────────────────────────────────────────
    refinery_util  = safe(eia, "refinery_util",  "value")
    cushing        = safe(eia, "cushing_stocks",  "value")
    cushing_util   = round(cushing / 76.0 * 100, 1) if cushing else None
    gasoline_dem   = safe(eia, "gasoline_demand", "value")
    distillate_dem = safe(eia, "distillate_demand","value")

    log.info("─" * 60)
    log.info("CRACK SPREAD ENGINE — input prices")
    log.info("  Brent:    %s $/bbl", f"{brent:.2f}" if brent else "N/A")
    log.info("  WTI:      %s $/bbl", f"{wti:.2f}"   if wti   else "N/A")
    log.info("  RBOB:     %s $/bbl", f"{rbob_bbl:.2f}" if rbob_bbl else "N/A")
    log.info("  HO/ULSD:  %s $/bbl", f"{ho_bbl:.2f}" if ho_bbl else "N/A")
    log.info("  ICE GO:   %s $/bbl",   f"{ice_gasoil_bbl:.2f}" if ice_gasoil_bbl else "N/A")
    log.info("─" * 60)

    # ── Compute spreads ───────────────────────────────────────────────────────
    crack_321      = compute_321_crack(wti, rbob_bbl, ho_bbl)
    gasoline_crack = compute_gasoline_crack(rbob_bbl, wti)
    ho_crack       = compute_ho_crack(ho_bbl, brent)
    ho_rbob_spread = compute_ho_rbob_spread(ho_bbl, rbob_bbl)
    # ICE Gasoil crack (European diesel) — also check derived from futures_fetcher
    gasoil_crack_direct = safe(futures, "derived", "gasoil_crack", "value_bbl")
    gasoil_crack   = gasoil_crack_direct or compute_ho_crack(ice_gasoil_bbl, brent)

    brent_wti      = safe(futures, "derived", "brent_wti_spread", "value_bbl")
    if brent_wti is None and brent and wti:
        brent_wti = round(brent - wti, 2)

    # ── 5yr seasonal averages ─────────────────────────────────────────────────
    crack_5yr    = CRACK_321_5YR_AVG.get(month)
    gas_crack_5yr= GASOLINE_CRACK_5YR_AVG.get(month)
    ho_crack_5yr = HO_CRACK_5YR_AVG.get(month)
    bwti_5yr     = BRENT_WTI_5YR_AVG.get(month)

    # ── Individual scores ─────────────────────────────────────────────────────
    s_crack_321   = score_crack_321(crack_321)
    s_gas_crack   = score_gasoline_crack(gasoline_crack, month)
    s_brent_wti   = score_brent_wti(brent_wti)
    s_seasonal    = score_seasonal_crack_position(crack_321, month)
    s_ho_rbob     = score_ho_rbob_spread(ho_rbob_spread, month)

    log.info("CRACK SPREAD SCORES")
    log.info("  3-2-1 crack:      %+d  (%s $/bbl vs 5yr %s)",
             s_crack_321,
             f"{crack_321:.1f}" if crack_321 else "N/A",
             f"{crack_5yr:.1f}" if crack_5yr else "N/A")
    log.info("  Gasoline crack:   %+d  (%s $/bbl vs 5yr %s)",
             s_gas_crack,
             f"{gasoline_crack:.1f}" if gasoline_crack else "N/A",
             f"{gas_crack_5yr:.1f}" if gas_crack_5yr else "N/A")
    log.info("  Brent-WTI:        %+d  (%s $/bbl vs 5yr %s)",
             s_brent_wti,
             f"{brent_wti:.1f}" if brent_wti else "N/A",
             f"{bwti_5yr:.1f}" if bwti_5yr else "N/A")
    log.info("  Seasonal position:%+d  (crack vs seasonal norm)",  s_seasonal)
    log.info("  HO-RBOB spread:   %+d  (%s $/bbl)",
             s_ho_rbob,
             f"{ho_rbob_spread:.1f}" if ho_rbob_spread else "N/A")

    # ── Weighted composite ────────────────────────────────────────────────────
    # 3-2-1 crack gets highest weight — most direct crude demand signal
    # Seasonal position matters — are we above or below where we should be?
    raw_score = (
        s_crack_321  * 3.0 +
        s_gas_crack  * 2.0 +
        s_seasonal   * 2.0 +
        s_brent_wti  * 1.5 +
        s_ho_rbob    * 1.5
    )
    max_possible = 3.0*5 + 2.0*5 + 2.0*3 + 1.5*2 + 1.5*3
    nci_crack    = round(max(-10, min(10, raw_score / max_possible * 10)), 2)

    if nci_crack >= 6:      crack_label = "CRACKS_VERY_WIDE"
    elif nci_crack >= 3:    crack_label = "CRACKS_WIDE"
    elif nci_crack >= 1:    crack_label = "CRACKS_NORMAL_HIGH"
    elif nci_crack >= -1:   crack_label = "CRACKS_BALANCED"
    elif nci_crack >= -3:   crack_label = "CRACKS_COMPRESSED"
    elif nci_crack >= -6:   crack_label = "CRACKS_NARROW"
    else:                   crack_label = "CRACKS_VERY_NARROW"

    crude_direction = (
        "BULLISH" if nci_crack >= 2
        else "BEARISH" if nci_crack <= -2
        else "NEUTRAL"
    )

    # ── Curve shape ───────────────────────────────────────────────────────────
    curve = compute_curve_signal(brent, brent_wti, refinery_util, cushing_util)

    # ── Seasonal context ──────────────────────────────────────────────────────
    seasonal = get_seasonal_context(month)

    # ── Brent-WTI alert ──────────────────────────────────────────────────────
    bwti_alert = None
    if brent_wti is not None:
        if brent_wti > 8:
            bwti_alert = f"ALERT: Brent-WTI ${brent_wti:.2f} > $8 — US export bottleneck OR North Sea disruption"
        elif brent_wti < 2:
            bwti_alert = f"ALERT: Brent-WTI ${brent_wti:.2f} < $2 — US exports flooding Atlantic market"

    # ── Build output ──────────────────────────────────────────────────────────
    output = {
        "engine":       "crack_spread_engine",
        "computed_at":  datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "month":        month,

        # Raw prices used
        "prices": {
            "brent_bbl":   brent,
            "wti_bbl":     wti,
            "rbob_bbl":    rbob_bbl,
            "ho_bbl":      ho_bbl,
            "ng_mmbtu":    ng,
        },

        # Crack spreads
        "spreads": {
            "crack_321": {
                "value_bbl":      crack_321,
                "five_yr_avg":    crack_5yr,
                "deviation":      deviation(crack_321, crack_5yr),
                "deviation_pct":  deviation_pct(crack_321, crack_5yr),
                "signal":         "BULLISH" if crack_321 and crack_321 > 20 else
                                  "BEARISH" if crack_321 and crack_321 < 12 else "NEUTRAL",
                "note": (
                    f"3-2-1 crack ${crack_321:.1f}/bbl: "
                    + ("Wide — product demand outpacing crude. Refiners incentivised to run harder → crude demand grows."
                       if crack_321 and crack_321 > 20
                       else "Compressed — margins tight. Risk of run cuts → crude demand softens."
                       if crack_321 and crack_321 < 12
                       else "Normal range.")
                    if crack_321 else "Insufficient data (HO price unavailable)"
                ),
            },
            "gasoline_crack": {
                "value_bbl":     gasoline_crack,
                "five_yr_avg":   gas_crack_5yr,
                "deviation":     deviation(gasoline_crack, gas_crack_5yr),
                "deviation_pct": deviation_pct(gasoline_crack, gas_crack_5yr),
                "signal":        "BULLISH" if gasoline_crack and gasoline_crack > 22 else
                                 "BEARISH" if gasoline_crack and gasoline_crack < 10 else "NEUTRAL",
            },
            "gasoil_crack_ice": {
                "value_bbl":     gasoil_crack,
                "five_yr_avg":   ho_crack_5yr,
                "deviation":     deviation(gasoil_crack, ho_crack_5yr),
                "signal":        "BULLISH" if gasoil_crack and gasoil_crack > 25 else
                                 "BEARISH" if gasoil_crack and gasoil_crack < 10 else "NEUTRAL",
                "note": (
                    f"ICE Gasoil crack ${gasoil_crack:.1f}/bbl"
                    if gasoil_crack else "Insufficient data (BG=F unavailable)"
                ),
            },
            "ho_crack": {
                "value_bbl":     ho_crack,
                "five_yr_avg":   ho_crack_5yr,
                "deviation":     deviation(ho_crack, ho_crack_5yr),
                "signal":        "BULLISH" if ho_crack and ho_crack > 25 else
                                 "BEARISH" if ho_crack and ho_crack < 10 else "NEUTRAL",
            },
            "ho_rbob_spread": {
                "value_bbl":  ho_rbob_spread,
                "signal":     "DIESEL_TIGHT" if ho_rbob_spread and ho_rbob_spread > 15 else
                              "GASOLINE_TIGHT" if ho_rbob_spread and ho_rbob_spread < 0 else "NORMAL",
                "note": (
                    "Diesel significantly outperforming gasoline — industrial/logistics demand dominant"
                    if ho_rbob_spread and ho_rbob_spread > 15
                    else "Gasoline outperforming diesel — driving season pressure"
                    if ho_rbob_spread and ho_rbob_spread < 0
                    else "Normal diesel/gasoline premium"
                ) if ho_rbob_spread else "Insufficient data",
            },
            "brent_wti": {
                "value_bbl":    brent_wti,
                "five_yr_avg":  bwti_5yr,
                "deviation":    deviation(brent_wti, bwti_5yr),
                "signal":       "ALERT_HIGH" if brent_wti and brent_wti > 8 else
                                "ALERT_LOW"  if brent_wti and brent_wti < 2 else "NORMAL",
                "alert":        bwti_alert,
                "note": (
                    f"Brent-WTI ${brent_wti:.2f}/bbl: "
                    + ("US export bottleneck or North Sea disruption" if brent_wti and brent_wti > 8
                       else "US exports flooding market" if brent_wti and brent_wti < 2
                       else "Normal range — US exports flowing, North Sea intact")
                ) if brent_wti else "Insufficient data",
            },
        },

        # Component scores
        "component_scores": {
            "crack_321_score":    s_crack_321,
            "gasoline_crack_score": s_gas_crack,
            "seasonal_position":  s_seasonal,
            "brent_wti_score":    s_brent_wti,
            "ho_rbob_score":      s_ho_rbob,
            "raw_weighted_sum":   round(raw_score, 2),
        },

        # NCI crack score
        "nci_crack": {
            "score":           nci_crack,
            "label":           crack_label,
            "crude_direction": crude_direction,
            "scale":           "-10 (very narrow cracks) to +10 (very wide cracks)",
            "interpretation":  (
                f"NCI Crack {nci_crack:+.1f} ({crack_label}): "
                + {
                    "CRACKS_VERY_WIDE":   "Exceptional refinery margins. Refiners running flat out. Strong crude demand pull.",
                    "CRACKS_WIDE":        "Above-average margins. Refiners incentivised to maximize runs. Bullish crude.",
                    "CRACKS_NORMAL_HIGH": "Margins slightly above seasonal norm. Mild bullish crude demand signal.",
                    "CRACKS_BALANCED":    "Margins near seasonal average. Neutral crude demand signal.",
                    "CRACKS_COMPRESSED":  "Below-average margins. Risk of run cuts. Mild bearish crude demand.",
                    "CRACKS_NARROW":      "Margins compressed. Refiners cutting runs. Bearish crude demand.",
                    "CRACKS_VERY_NARROW": "Margins very low. Significant run cuts likely. Bearish crude demand.",
                }.get(crack_label, "")
            ),
        },

        # Forward curve
        "forward_curve": curve,

        # Seasonal context
        "seasonal": {
            **seasonal,
            "month": month,
            "is_driving_season":  month in {5, 6, 7, 8, 9},
            "is_heating_season":  month in {10, 11, 12, 1, 2, 3},
            "crack_peak_window":  month in {3, 4, 5},
            "typical_5yr_crack":  crack_5yr,
        },

        # Refinery context from EIA
        "refinery": {
            "utilisation_pct":     refinery_util,
            "gasoline_demand_mbd": gasoline_dem,
            "distillate_demand_mbd": distillate_dem,
            "cushing_util_pct":    cushing_util,
        },
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    log.info("─" * 60)
    log.info("NCI CRACK SCORE:   %+.1f / 10  [%s]", nci_crack, crack_label)
    log.info("Crude direction:   %s", crude_direction)
    log.info("3-2-1 crack:       %s $/bbl", f"{crack_321:.1f}" if crack_321 else "N/A (HO missing)")
    log.info("Gasoline crack:    %s $/bbl", f"{gasoline_crack:.1f}" if gasoline_crack else "N/A")
    log.info("Brent-WTI:         %s $/bbl  [%s]",
             f"{brent_wti:.2f}" if brent_wti else "N/A",
             "NORMAL" if brent_wti and 2 <= brent_wti <= 8 else "ALERT" if brent_wti else "N/A")
    log.info("Curve shape:       %s", curve["estimated_shape"])
    log.info("Season:            %s (%s)", seasonal["phase"], seasonal["dominant_product"])
    if bwti_alert:
        log.warning(bwti_alert)
    log.info("Saved → %s", OUTPUT_PATH)
    log.info("─" * 60)

    return output


def run(refresh: bool = False) -> dict:
    if refresh:
        log.info("Refreshing futures data...")
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "futures_fetcher",
            Path(__file__).parent / "fetchers" / "futures_fetcher.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if hasattr(mod, "run"):
            mod.run()

    return compute_crack_signals()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Crack Spread Engine")
    parser.add_argument("--refresh", action="store_true",
                        help="Re-fetch futures prices before computing")
    args = parser.parse_args()
    run(refresh=args.refresh)

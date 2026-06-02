"""
backend/signals/crack_signals.py
----------------------------------
Reads:  backend/data/crack_signals.json   (existing crack_spread_engine output)
        backend/data/futures_latest.json
Writes: backend/data/crack_signal_layer.json

Day 5: crack spread signal layer + forward curve shape + Brent-WTI spread signal.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
OUT  = DATA / "crack_signal_layer.json"


# ── thresholds ($/bbl) ────────────────────────────────────────────────────────
CRACK_321_BULL   = 20.0   # wide = product demand outpacing crude
CRACK_321_BEAR   = 10.0
GASOIL_BULL      = 25.0   # ICE gasoil crack (European diesel tightness)
GASOIL_BEAR      = 12.0
GASOLINE_BULL    = 18.0
GASOLINE_BEAR    =  8.0
HO_BULL          = 22.0   # heating oil / ULSD crack
HO_BEAR          = 10.0

# Brent-WTI spread signals ($/bbl)
BRENT_WTI_BOTTLENECK = 8.0    # above → US export bottleneck or North Sea disruption
BRENT_WTI_SURPLUS    = 2.0    # below → US exports flooding Atlantic

# Forward curve shape (M1-M2 spread, $/bbl)
BACKWARDATION_STRONG =  1.0   # strong physical tightness
BACKWARDATION_MILD   =  0.20
CONTANGO_MILD        = -0.30
CONTANGO_STRONG      = -1.50

# Seasonal crack context (months)
GASOLINE_SEASON = list(range(2, 6))   # Feb–May: long gasoline crack season
GASOIL_SEASON   = [10, 11, 12, 1, 2]  # Oct–Feb: heating/gasoil season


# ── helpers ───────────────────────────────────────────────────────────────────

def _load(path):
    p = Path(path)
    if not p.exists():
        return {}
    with open(p) as f:
        return json.load(f)

def _f(v):
    try:    return float(v)
    except: return None

def _sig(bull, bear):
    if bull:  return "BULLISH"
    if bear:  return "BEARISH"
    return "NEUTRAL"

def _pts(signal, strength):
    return {"BULLISH": 1, "NEUTRAL": 0, "BEARISH": -1}.get(signal, 0) * strength

def _sth(val, bull_thresh, bear_thresh):
    """Strength based on how far above/below threshold."""
    if val is None:
        return 1
    if val > bull_thresh:
        overshoot = (val - bull_thresh) / bull_thresh
        return 3 if overshoot > 0.3 else 2
    if val < bear_thresh:
        return 2 if (bear_thresh - val) > 3 else 1
    return 1


# ── crack spread signals ──────────────────────────────────────────────────────

def sig_crack_321(crack_data):
    val = _f(crack_data.get("crack_321", {}).get("value_bbl") or
             crack_data.get("crack_321"))
    month = datetime.now(timezone.utc).month

    bull = (val or 0) > CRACK_321_BULL
    bear = (val or 0) < CRACK_321_BEAR
    sig  = _sig(bull, bear)
    sth  = _sth(val, CRACK_321_BULL, CRACK_321_BEAR)

    return {
        "id": "crack_321", "label": "3-2-1 Crack Spread (US)",
        "value": round(val, 2) if val is not None else None,
        "unit": "$/bbl",
        "bull_threshold": CRACK_321_BULL,
        "bear_threshold": CRACK_321_BEAR,
        "signal": sig, "strength": sth, "weight": 0.25,
        "score": _pts(sig, sth),
        "note": (f"3-2-1 crack at ${val:.2f}/bbl"
                 + (" — product demand tight, crude demand rising" if bull else
                    " — margins compressed, runs may slow" if bear else " — normal range")
                 if val is not None else "No data"),
    }


def sig_gasoil_crack(crack_data):
    # Try multiple key paths from crack_signals.json
    val = (_f(crack_data.get("gasoil_crack", {}).get("value_bbl")) or
           _f(crack_data.get("gasoil_crack")) or
           _f(crack_data.get("ice_gasoil_crack")))

    month  = datetime.now(timezone.utc).month
    season = month in GASOIL_SEASON

    # Gasoil season → lower threshold needed to trigger bullish
    bull_t = GASOIL_BULL * (0.85 if season else 1.0)
    bull   = (val or 0) > bull_t
    bear   = (val or 0) < GASOIL_BEAR
    sig    = _sig(bull, bear)
    sth    = _sth(val, bull_t, GASOIL_BEAR)
    if season and sig == "BULLISH":
        sth = min(3, sth + 1)

    return {
        "id": "gasoil_crack", "label": "ICE Gasoil Crack (European Diesel)",
        "value": round(val, 2) if val is not None else None,
        "unit": "$/bbl",
        "gasoil_season": season,
        "signal": sig, "strength": sth, "weight": 0.20,
        "score": _pts(sig, sth),
        "note": (f"Gasoil crack ${val:.2f}/bbl"
                 + (" — European diesel/heating oil tight" if bull else "")
                 + (" [heating season]" if season else "")
                 if val is not None else "No data"),
    }


def sig_gasoline_crack(crack_data):
    val = (_f(crack_data.get("gasoline_crack", {}).get("value_bbl")) or
           _f(crack_data.get("gasoline_crack")))

    month  = datetime.now(timezone.utc).month
    season = month in GASOLINE_SEASON   # Feb–May driving season build

    bull_t = GASOLINE_BULL * (0.85 if season else 1.0)
    bull   = (val or 0) > bull_t
    bear   = (val or 0) < GASOLINE_BEAR
    sig    = _sig(bull, bear)
    sth    = _sth(val, bull_t, GASOLINE_BEAR)
    if season and sig == "BULLISH":
        sth = min(3, sth + 1)

    return {
        "id": "gasoline_crack", "label": "Gasoline Crack (RBOB vs WTI)",
        "value": round(val, 2) if val is not None else None,
        "unit": "$/bbl",
        "driving_season_build": season,
        "signal": sig, "strength": sth, "weight": 0.15,
        "score": _pts(sig, sth),
        "note": (f"Gasoline crack ${val:.2f}/bbl"
                 + (" — seasonal long gasoline crack window" if season else "")
                 if val is not None else "No data"),
    }


def sig_ho_crack(crack_data):
    val = (_f(crack_data.get("ho_crack", {}).get("value_bbl")) or
           _f(crack_data.get("ho_crack")))

    bull = (val or 0) > HO_BULL
    bear = (val or 0) < HO_BEAR
    sig  = _sig(bull, bear)
    sth  = _sth(val, HO_BULL, HO_BEAR)

    return {
        "id": "ho_crack", "label": "Heating Oil / ULSD Crack",
        "value": round(val, 2) if val is not None else None,
        "unit": "$/bbl",
        "signal": sig, "strength": sth, "weight": 0.10,
        "score": _pts(sig, sth),
        "note": (f"HO/ULSD crack ${val:.2f}/bbl"
                 if val is not None else "No data"),
    }


# ── forward curve shape ───────────────────────────────────────────────────────

def sig_curve_shape(futures):
    """
    M1-M2 Brent spread from futures_latest.json.
    Positive = backwardation (bullish), negative = contango (bearish).
    """
    # Try to get M1 and M2 from futures data
    brent = futures.get("contracts", {}).get("brent", {})

    m1 = _f(brent.get("price") or brent.get("latest"))
    # M2 proxy: if history has 2+ entries, use yesterday's close as rough M2
    # In production this would come from calendar spread data
    # For now use the m1_m2_spread if pre-calculated, else flag as unavailable
    spread = _f(futures.get("derived", {}).get("brent_m1_m2") or
                futures.get("brent_m1_m2_spread"))

    if spread is None:
        return {
            "id": "curve_shape", "label": "Brent M1–M2 Spread (Curve Shape)",
            "value": None, "unit": "$/bbl",
            "signal": "NEUTRAL", "strength": 1, "weight": 0.15,
            "score": 0,
            "note": "M1-M2 spread not yet calculated — add to futures_fetcher",
            "structure": "UNKNOWN",
        }

    if spread >= BACKWARDATION_STRONG:
        structure = "STRONG BACKWARDATION"
        sig, sth  = "BULLISH", 3
    elif spread >= BACKWARDATION_MILD:
        structure = "MILD BACKWARDATION"
        sig, sth  = "BULLISH", 1
    elif spread <= CONTANGO_STRONG:
        structure = "DEEP CONTANGO"
        sig, sth  = "BEARISH", 3
    elif spread <= CONTANGO_MILD:
        structure = "MILD CONTANGO"
        sig, sth  = "BEARISH", 1
    else:
        structure = "FLAT"
        sig, sth  = "NEUTRAL", 1

    return {
        "id": "curve_shape", "label": "Brent M1–M2 Spread (Curve Shape)",
        "value": round(spread, 3), "unit": "$/bbl",
        "structure": structure,
        "signal": sig, "strength": sth, "weight": 0.15,
        "score": _pts(sig, sth),
        "thresholds": {
            "strong_backwardation": BACKWARDATION_STRONG,
            "mild_backwardation":   BACKWARDATION_MILD,
            "mild_contango":        CONTANGO_MILD,
            "strong_contango":      CONTANGO_STRONG,
        },
        "note": (f"Brent M1-M2 = {spread:+.3f} $/bbl → {structure}"
                 + (" — physical urgency, tight prompt market" if "BACKWARDATION" in structure else
                    " — paper concern, storage incentivised" if "CONTANGO" in structure else "")),
    }


# ── Brent-WTI spread signal ───────────────────────────────────────────────────

def sig_brent_wti(crack_data, futures):
    val = (_f(crack_data.get("brent_wti", {}).get("value_bbl")) or
           _f(crack_data.get("brent_wti")) or
           _f(futures.get("derived", {}).get("brent_wti")))

    if val is None:
        # Try computing from individual prices
        brent = _f(futures.get("contracts", {}).get("brent", {}).get("price"))
        wti   = _f(futures.get("contracts", {}).get("wti",   {}).get("price"))
        if brent and wti:
            val = brent - wti

    bottleneck = (val or 0) > BRENT_WTI_BOTTLENECK
    surplus    = (val or 0) < BRENT_WTI_SURPLUS

    if bottleneck:
        sig, sth = "BEARISH", 2   # bearish for WTI specifically; US landlocked
        note = (f"Brent-WTI = ${val:.2f} — US export bottleneck or North Sea supply disruption")
    elif surplus:
        sig, sth = "BEARISH", 1
        note = (f"Brent-WTI = ${val:.2f} — US exports flooding Atlantic basin")
    else:
        sig, sth = "NEUTRAL", 1
        note = (f"Brent-WTI = ${val:.2f} — normal range $2–8")

    return {
        "id": "brent_wti_spread", "label": "Brent–WTI Spread",
        "value": round(val, 2) if val is not None else None,
        "unit": "$/bbl",
        "bottleneck_flag": bottleneck,
        "surplus_flag": surplus,
        "signal": sig, "strength": sth, "weight": 0.15,
        "score": _pts(sig, sth),
        "interpretation": (
            "BOTTLENECK: US cannot export freely OR North Sea supply disruption" if bottleneck else
            "SURPLUS: US crude flooding Atlantic market" if surplus else
            "NORMAL: $2–8 range, no structural dislocation"
        ),
        "note": note if val is not None else "No Brent or WTI price available",
    }


# ── composite ─────────────────────────────────────────────────────────────────

def composite(signals):
    w_sum, w_total, components = 0.0, 0.0, []
    for s in signals:
        w = s.get("weight", 0.0)
        if w <= 0:
            continue
        sc = s.get("score", 0.0)
        w_sum   += sc * w
        w_total += w
        components.append({"id": s["id"], "label": s.get("label", ""),
                           "signal": s.get("signal", "NEUTRAL"),
                           "score": sc, "weight": w})

    max_pos = 3 * w_total if w_total > 0 else 1
    norm    = max(-10.0, min(10.0, round((w_sum / max_pos) * 10, 2)))
    overall = "BULLISH" if norm >= 3 else ("BEARISH" if norm <= -3 else "NEUTRAL")

    interp = (
        "Very wide cracks + backwardation — product market acutely tight, crude demand surging" if norm >= 7 else
        "Bullish refining backdrop — cracks wide, curve supporting physical tightness" if norm >= 3 else
        "Mildly bullish — cracks above average, mild curve support" if norm >= 1 else
        "Very compressed cracks + deep contango — oversupply, runs may be cut" if norm <= -7 else
        "Bearish refining backdrop — cracks compressed, curve in contango" if norm <= -3 else
        "Mildly bearish — margins under pressure" if norm <= -1 else
        "Neutral — crack spreads in normal range, curve flat"
    )

    return {"score": norm, "overall_signal": overall,
            "interpretation": interp, "components": components}


# ── main ──────────────────────────────────────────────────────────────────────

def run():
    crack_data = _load(DATA / "crack_signals.json")
    futures    = _load(DATA / "futures_latest.json")

    signals = [
        sig_crack_321(crack_data),
        sig_gasoil_crack(crack_data),
        sig_gasoline_crack(crack_data),
        sig_ho_crack(crack_data),
        sig_curve_shape(futures),
        sig_brent_wti(crack_data, futures),
    ]

    comp   = composite(signals)
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "signals":      {s["id"]: s for s in signals},
        "composite":    comp,
    }

    DATA.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(output, f, indent=2)

    print(f"[crack_signals] score={comp['score']:+.2f}  {comp['overall_signal']}")
    for s in signals:
        print(f"  {s['id']:25s} {s.get('signal','?'):8s}  {s.get('note','')}")

    return output


if __name__ == "__main__":
    run()

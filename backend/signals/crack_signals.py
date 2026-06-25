"""
backend/signals/crack_signals.py
----------------------------------
Reads:  backend/data/crack_signals.json   (crack_spread_engine output)
        backend/data/futures_latest.json
Writes: backend/data/crack_signal_layer.json

Adapted to actual crack_signals.json structure from crack_spread_engine.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
OUT  = DATA / "crack_signal_layer.json"

# ── thresholds ────────────────────────────────────────────────────────────────
CRACK_321_BULL   = 20.0
CRACK_321_BEAR   = 10.0
GASOLINE_BULL    = 18.0
GASOLINE_BEAR    =  8.0
HO_RBOB_BULL     = 20.0
HO_RBOB_BEAR     =  8.0
BRENT_WTI_BOTTLENECK = 8.0
BRENT_WTI_SURPLUS    = 2.0
GASOLINE_SEASON  = [2, 3, 4, 5]    # Feb–May
GASOIL_SEASON    = [10, 11, 12, 1, 2]


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


def sig_crack_321(crack):
    # crack_signals.json → component_scores.crack_321_score (0–10 scale)
    # and prices.brent_bbl, prices.wti_bbl, prices.rbob_bbl, prices.ho_bbl
    prices = crack.get("prices", {})
    brent  = _f(prices.get("brent_bbl"))
    wti    = _f(prices.get("wti_bbl"))
    rbob   = _f(prices.get("rbob_bbl"))
    ho     = _f(prices.get("ho_bbl"))

    # Compute 3-2-1 from prices if available
    val = None
    if wti and rbob and ho:
        val = round((2 * rbob + ho - 3 * wti) / 3, 2)

    # Fallback: use nci_crack score scaled to $/bbl proxy
    if val is None:
        nci_score = _f(crack.get("nci_crack", {}).get("score"))
        if nci_score is not None:
            val = round(nci_score * 2.5, 2)  # rough proxy: score 10 ≈ $25/bbl

    bull = (val or 0) > CRACK_321_BULL
    bear = (val or 0) < CRACK_321_BEAR
    sig  = _sig(bull, bear)
    sth  = 3 if (val or 0) > 25 else 2 if bull else 1

    return {
        "id": "crack_321", "label": "3-2-1 Crack Spread (US)",
        "value": val, "unit": "$/bbl",
        "signal": sig, "strength": sth, "weight": 0.25,
        "score": _pts(sig, sth),
        "note": (f"3-2-1 crack ${val:.2f}/bbl"
                 + (" — product demand tight, crude demand rising" if bull else
                    " — margins compressed" if bear else " — normal range")
                 if val is not None else "Insufficient price data for 3-2-1"),
    }


def sig_gasoline_crack(crack):
    prices = crack.get("prices", {})
    rbob   = _f(prices.get("rbob_bbl"))
    brent  = _f(prices.get("brent_bbl"))
    wti    = _f(prices.get("wti_bbl"))

    val = None
    if rbob and wti:
        val = round(rbob - wti, 2)
    elif rbob and brent:
        val = round(rbob - brent, 2)

    month  = datetime.now(timezone.utc).month
    season = month in GASOLINE_SEASON

    bull_t = GASOLINE_BULL * (0.85 if season else 1.0)
    bull   = (val or 0) > bull_t
    bear   = (val or 0) < GASOLINE_BEAR
    sig    = _sig(bull, bear)
    sth    = min(3, (2 if bull else 1) + (1 if season and bull else 0))

    return {
        "id": "gasoline_crack", "label": "Gasoline Crack (RBOB vs WTI)",
        "value": val, "unit": "$/bbl",
        "driving_season_build": season,
        "signal": sig, "strength": sth, "weight": 0.15,
        "score": _pts(sig, sth),
        "note": (f"Gasoline crack ${val:.2f}/bbl"
                 + (" — seasonal long gasoline crack window" if season else "")
                 if val is not None else "RBOB or WTI price unavailable"),
    }


def sig_ho_rbob(crack):
    prices = crack.get("prices", {})
    ho     = _f(prices.get("ho_bbl"))
    rbob   = _f(prices.get("rbob_bbl"))

    val  = round(ho - rbob, 2) if (ho and rbob) else None
    bull = (val or 0) > HO_RBOB_BULL
    bear = (val or 0) < HO_RBOB_BEAR
    sig  = _sig(bull, bear)
    sth  = 2 if bull else 1

    month  = datetime.now(timezone.utc).month
    season = month in GASOIL_SEASON

    return {
        "id": "ho_rbob_spread", "label": "HO–RBOB Spread (Diesel Premium)",
        "value": val, "unit": "$/bbl",
        "heating_season": season,
        "signal": sig, "strength": sth, "weight": 0.15,
        "score": _pts(sig, sth),
        "note": (f"HO-RBOB spread ${val:.2f}/bbl"
                 + (" — diesel commanding large premium over gasoline" if bull else "")
                 + (" [heating season]" if season else "")
                 if val is not None else "HO or RBOB price unavailable"),
    }


def sig_curve_shape(crack):
    # Use crack_signals.json forward_curve section
    fwd     = crack.get("forward_curve", {})
    shape   = fwd.get("estimated_shape", "UNKNOWN")
    storage = fwd.get("storage_economic", False)
    score_v = _f(fwd.get("score"))

    if shape == "BACKWARDATION":
        sig, sth = "BULLISH", (3 if (score_v or 0) >= 4 else 2)
        note = "Curve in backwardation — physical urgency, prompt market tight"
    elif shape == "CONTANGO":
        sig, sth = "BEARISH", (3 if storage else 2)
        note = "Curve in contango — storage incentivised, paper market concern"
    elif shape == "FLAT":
        sig, sth = "NEUTRAL", 1
        note = "Curve flat — balanced market, no strong directional signal"
    else:
        sig, sth = "NEUTRAL", 1
        note = "Curve shape unknown — M1-M2 strip data needed"

    return {
        "id": "curve_shape", "label": "Forward Curve Shape",
        "value": shape, "unit": "structure",
        "storage_economic": storage,
        "signal": sig, "strength": sth, "weight": 0.20,
        "score": _pts(sig, sth),
        "note": note,
    }


def sig_brent_wti(crack):
    prices = crack.get("prices", {})
    brent  = _f(prices.get("brent_bbl"))
    wti    = _f(prices.get("wti_bbl"))
    val    = round(brent - wti, 2) if (brent and wti) else None

    bottleneck = (val or 0) > BRENT_WTI_BOTTLENECK
    surplus    = (val or 0) < BRENT_WTI_SURPLUS

    if val is None:
        sig, sth = "NEUTRAL", 1
        note = "Brent or WTI price unavailable"
        interp = "No price data"
    elif bottleneck:
        sig, sth = "BEARISH", 2
        note = f"Brent-WTI ${val:.2f} — US export bottleneck or North Sea disruption"
        interp = "BOTTLENECK: US cannot export freely OR North Sea disruption"
    elif surplus:
        sig, sth = "BEARISH", 1
        note = f"Brent-WTI ${val:.2f} — US exports flooding Atlantic"
        interp = "SURPLUS: US crude flooding Atlantic market"
    else:
        sig, sth = "NEUTRAL", 1
        note = f"Brent-WTI ${val:.2f} — normal range $2–8"
        interp = "NORMAL: $2–8 range, no structural dislocation"

    return {
        "id": "brent_wti_spread", "label": "Brent–WTI Spread",
        "value": val, "unit": "$/bbl",
        "bottleneck_flag": bottleneck,
        "surplus_flag": surplus,
        "interpretation": interp if val is not None else "No price data",
        "signal": sig, "strength": sth, "weight": 0.25,
        "score": _pts(sig, sth),
        "note": note if val is not None else "Brent or WTI price unavailable",
    }


def composite(signals):
    w_sum, w_total, components = 0.0, 0.0, []
    for s in signals:
        w = s.get("weight", 0.0)
        if w <= 0:
            continue
        sc = s.get("score", 0.0)
        w_sum   += sc * w
        w_total += w
        components.append({
            "id": s["id"], "label": s.get("label", ""),
            "signal": s.get("signal", "NEUTRAL"),
            "score": sc, "weight": w,
        })

    max_pos = 3 * w_total if w_total > 0 else 1
    norm    = max(-10.0, min(10.0, round((w_sum / max_pos) * 10, 2)))
    overall = "BULLISH" if norm >= 3 else ("BEARISH" if norm <= -3 else "NEUTRAL")

    interp = (
        "Very wide cracks + backwardation — product market acutely tight" if norm >= 7 else
        "Bullish refining backdrop — cracks wide, curve supporting tightness" if norm >= 3 else
        "Mildly bullish — cracks above average" if norm >= 1 else
        "Very compressed cracks + deep contango — oversupply" if norm <= -7 else
        "Bearish refining backdrop — cracks compressed, curve in contango" if norm <= -3 else
        "Mildly bearish — margins under pressure" if norm <= -1 else
        "Neutral — crack spreads in normal range"
    )

    return {
        "score": norm, "overall_signal": overall,
        "interpretation": interp, "components": components,
    }


def run():
    crack   = _load(DATA / "crack_signals.json")
    futures = _load(DATA / "futures_latest.json")

    signals = [
        sig_crack_321(crack),
        sig_gasoline_crack(crack),
        sig_ho_rbob(crack),
        sig_curve_shape(crack),
        sig_brent_wti(crack),
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

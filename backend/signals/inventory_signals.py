"""
backend/signals/inventory_signals.py
--------------------------------------
Reads:  backend/data/eia_latest.json   (flat structure — direct top-level keys)
        backend/data/gie_latest.json
Writes: backend/data/inventory_signals.json

EIA JSON structure (actual):
  d["cushing_stocks"]     → {"value": 23.0, "wow": -2.8, "vs_5yr_avg": -3.98, ...}
  d["total_crude_stocks"] → {"value": 441.7, "wow": -3.3, "vs_5yr_avg": -8.31, ...}
  d["gasoline_stocks"]    → {"value": 211.6, "wow": -2.6, "vs_5yr_avg": -23.4, ...}
  d["distillate_stocks"]  → {"value": 100.8, "wow": -2.1, "vs_5yr_avg": -19.2, ...}
  d["crude_production"]   → {"value": 13.71, "wow": 0.013, ...}
  d["refinery_util"]      → {"value": 94.5,  "wow": 2.9,  "vs_5yr_avg": 4.5, ...}
  d["days_cover"]         → 57.1  (plain float, not a dict)
"""

import json
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
OUT  = DATA / "inventory_signals.json"

# ── thresholds ────────────────────────────────────────────────────────────────
DAYS_COVER_CRITICAL = 54.0
DAYS_COVER_NORMAL   = 58.0
PROD_HIGH           = 13.5
UTIL_HIGH           = 92.0
UTIL_LOW            = 85.0


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

def _sth(dev, lo=5, hi=15):
    a = abs(dev or 0)
    return 3 if a >= hi else 2 if a >= lo else 1


# ── individual signals ────────────────────────────────────────────────────────

def sig_cushing(eia):
    s   = eia.get("cushing_stocks", {})
    val = _f(s.get("value"))
    wow = _f(s.get("wow"))
    dev = _f(s.get("vs_5yr_avg"))   # already computed deviation in mmbbls

    # Bullish: drawing (wow < 0) AND below 5yr avg (dev < 0)
    bull = (wow or 0) < -1.0 and (dev or 0) < 0
    bear = (wow or 0) >  1.0 and (dev or 0) > 0
    sig  = _sig(bull, bear)
    sth  = _sth(dev)

    return {
        "id": "cushing_stocks", "label": "Cushing Crude Stocks",
        "value": val, "unit": "mmbbls",
        "wow": wow, "dev_5yr": dev,
        "signal": sig, "strength": sth, "weight": 0.20,
        "score": _pts(sig, sth),
        "note": (f"Cushing {abs(wow):.1f} mmbbls {'draw' if (wow or 0)<0 else 'build'} WoW; "
                 f"{abs(dev):.1f} mmbbls {'below' if (dev or 0)<0 else 'above'} 5yr avg"
                 if val is not None else "No data"),
    }


def sig_total_crude(eia):
    s   = eia.get("total_crude_stocks", {})
    val = _f(s.get("value"))
    wow = _f(s.get("wow"))
    dev = _f(s.get("vs_5yr_avg"))

    bull = (dev or 0) < -20
    bear = (dev or 0) >  20
    sig  = _sig(bull, bear)
    sth  = _sth(dev, lo=5, hi=20)

    return {
        "id": "total_crude_stocks", "label": "Total US Crude Stocks",
        "value": val, "unit": "mmbbls",
        "wow": wow, "dev_5yr": dev,
        "signal": sig, "strength": sth, "weight": 0.15,
        "score": _pts(sig, sth),
        "note": (f"Total crude {abs(dev):.1f} mmbbls {'below' if (dev or 0)<0 else 'above'} 5yr avg"
                 if val is not None else "No data"),
    }


def sig_gasoline(eia):
    s   = eia.get("gasoline_stocks", {})
    val = _f(s.get("value"))
    wow = _f(s.get("wow"))
    dev = _f(s.get("vs_5yr_avg"))

    month   = datetime.now(timezone.utc).month
    driving = 4 <= month <= 9

    bull = (dev or 0) < -15 or (driving and (dev or 0) < -8)
    bear = (dev or 0) >  15
    sig  = _sig(bull, bear)
    sth  = _sth(dev, lo=8, hi=20)

    return {
        "id": "gasoline_stocks", "label": "US Gasoline Stocks",
        "value": val, "unit": "mmbbls",
        "wow": wow, "dev_5yr": dev,
        "driving_season": driving,
        "signal": sig, "strength": sth, "weight": 0.15,
        "score": _pts(sig, sth),
        "note": (f"Gasoline {abs(dev):.1f} mmbbls {'below' if (dev or 0)<0 else 'above'} 5yr avg"
                 + (" — driving season active" if driving else "")
                 if val is not None else "No data"),
    }


def sig_distillate(eia):
    s   = eia.get("distillate_stocks", {})
    val = _f(s.get("value"))
    wow = _f(s.get("wow"))
    dev = _f(s.get("vs_5yr_avg"))

    month   = datetime.now(timezone.utc).month
    heating = month >= 10 or month <= 2

    bull = (dev or 0) < (-10 * (1.5 if heating else 1.0))
    bear = (dev or 0) >  10
    sig  = _sig(bull, bear)
    sth  = min(3, _sth(dev, lo=8, hi=20) + (1 if heating and sig == "BULLISH" else 0))

    return {
        "id": "distillate_stocks", "label": "US Distillate Stocks",
        "value": val, "unit": "mmbbls",
        "wow": wow, "dev_5yr": dev,
        "heating_season": heating,
        "signal": sig, "strength": sth, "weight": 0.15,
        "score": _pts(sig, sth),
        "note": (f"Distillates {abs(dev):.1f} mmbbls {'below' if (dev or 0)<0 else 'above'} 5yr avg"
                 + (" — HEATING SEASON" if heating else "")
                 if val is not None else "No data"),
    }


def sig_production(eia):
    s   = eia.get("crude_production", {})
    val = _f(s.get("value"))
    wow = _f(s.get("wow"))

    bear = (val or 0) > PROD_HIGH and (wow or 0) > 0.05
    bull = (val or 0) < 12.0
    sig  = _sig(bull, bear)
    sth  = 2 if (wow is not None and abs(wow) > 0.1) else 1

    return {
        "id": "crude_production", "label": "US Crude Production",
        "value": val, "unit": "mbd",
        "wow": wow,
        "signal": sig, "strength": sth, "weight": 0.10,
        "score": _pts(sig, sth),
        "note": (f"US output {val:.2f} mbd, {'+' if (wow or 0)>=0 else ''}{wow:.3f} mbd WoW"
                 if val is not None and wow is not None else "No data"),
    }


def sig_refinery_util(eia):
    s   = eia.get("refinery_util", {})
    val = _f(s.get("value"))
    wow = _f(s.get("wow"))

    bull = (val or 0) > UTIL_HIGH
    bear = (val or 0) < UTIL_LOW
    sig  = _sig(bull, bear)
    sth  = 2 if (val or 0) > 94 else 1

    return {
        "id": "refinery_util", "label": "US Refinery Utilisation",
        "value": val, "unit": "%",
        "wow": wow,
        "signal": sig, "strength": sth, "weight": 0.10,
        "score": _pts(sig, sth),
        "note": (f"Refinery runs at {val:.1f}%"
                 + (" — running hot, strong crude pull" if bull else
                    " — runs soft, crude demand weak" if bear else "")
                 if val is not None else "No data"),
    }


def sig_days_cover(eia):
    # days_cover is a plain float in the EIA JSON, already computed
    days = _f(eia.get("days_cover"))

    bull = (days or 99) < DAYS_COVER_CRITICAL
    bear = (days or 0)  > DAYS_COVER_NORMAL + 5
    sig  = _sig(bull, bear)
    sth  = 3 if bull else (2 if bear else 1)

    return {
        "id": "days_cover", "label": "Days of Forward Demand Cover",
        "value": days, "unit": "days",
        "critical_threshold": DAYS_COVER_CRITICAL,
        "normal_range": [DAYS_COVER_CRITICAL, DAYS_COVER_NORMAL],
        "signal": sig, "strength": sth, "weight": 0.15,
        "score": _pts(sig, sth),
        "note": (f"{days:.1f} days cover"
                 + (" — CRITICAL LOW: historically $90+ Brent" if bull else
                    " — above normal, bearish" if bear else " — normal range")
                 if days is not None else "No data"),
    }


def sig_gie(gie):
    if not gie:
        return {
            "id": "gie_storage", "label": "EU Gas Storage (GIE)",
            "signal": "NEUTRAL", "strength": 1, "score": 0,
            "weight": 0.0, "note": "GIE data unavailable",
        }

    # Use composite signal directly — already computed by gie_fetcher
    comp     = gie.get("composite", {})
    comp_sig = comp.get("signal", "NEUTRAL")   # "BULLISH" | "BEARISH" | "NEUTRAL"
    score_v  = _f(comp.get("score"))           # 0.0–1.0

    # Get Germany fill % as reference value to display
    regions  = gie.get("regions", {})
    de       = regions.get("germany") or regions.get("DE") or regions.get("de") or {}
    fill_pct = _f(de.get("fill_pct"))

    sig = comp_sig if comp_sig in ("BULLISH", "BEARISH", "NEUTRAL") else "NEUTRAL"
    sth = 2 if (score_v or 0) > 0.6 else 1

    return {
        "id": "gie_storage", "label": "EU Gas Storage Fill",
        "value": fill_pct, "unit": "%",
        "composite_signal": comp_sig,
        "composite_score": score_v,
        "signal": sig, "strength": sth, "weight": 0.0,
        "score": _pts(sig, sth),
        "note": (f"EU gas storage: Germany {fill_pct:.1f}% full — {comp_sig}"
                 + (f" (score {score_v:.2f})" if score_v is not None else "")
                 if fill_pct is not None
                 else f"EU gas composite: {comp_sig}"),
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
        components.append({
            "id": s["id"], "label": s.get("label", s["id"]),
            "signal": s.get("signal", "NEUTRAL"),
            "score": sc, "weight": w,
        })

    max_pos = 3 * w_total if w_total > 0 else 1
    norm    = max(-10.0, min(10.0, round((w_sum / max_pos) * 10, 2)))
    overall = "BULLISH" if norm >= 3 else ("BEARISH" if norm <= -3 else "NEUTRAL")

    interp = (
        "Very strong bullish signal — physical market acutely tight" if norm >= 7 else
        "Bullish inventory backdrop — stocks drawing, demand support evident" if norm >= 3 else
        "Mildly bullish — stocks modestly below average" if norm >= 1 else
        "Very strong bearish signal — inventories building sharply" if norm <= -7 else
        "Bearish inventory backdrop — builds accelerating, supply ample" if norm <= -3 else
        "Mildly bearish — stocks modestly above average" if norm <= -1 else
        "Neutral — inventories near seasonal norms"
    )

    return {
        "score": norm, "overall_signal": overall,
        "interpretation": interp, "components": components,
    }


# ── main ──────────────────────────────────────────────────────────────────────

def run():
    eia = _load(DATA / "eia_latest.json")
    gie = _load(DATA / "gie_latest.json")

    signals = [
        sig_cushing(eia),
        sig_total_crude(eia),
        sig_gasoline(eia),
        sig_distillate(eia),
        sig_production(eia),
        sig_refinery_util(eia),
        sig_days_cover(eia),
        sig_gie(gie),
    ]

    comp   = composite(signals)
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "signals":      {s["id"]: s for s in signals},
        "composite":    comp,
        "meta": {
            "days_cover_critical": DAYS_COVER_CRITICAL,
            "days_cover_normal":   DAYS_COVER_NORMAL,
        },
    }

    DATA.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(output, f, indent=2)

    print(f"[inventory_signals] score={comp['score']:+.2f}  {comp['overall_signal']}")
    for s in signals:
        print(f"  {s['id']:30s} {s.get('signal','?'):8s}  {s.get('note','')}")

    return output


if __name__ == "__main__":
    run()

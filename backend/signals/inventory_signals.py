"""
backend/signals/inventory_signals.py
-------------------------------------
Reads:  backend/data/eia_latest.json
        backend/data/gie_latest.json
Writes: backend/data/inventory_signals.json

Produces per-series BULLISH/BEARISH/NEUTRAL signals + weighted composite
score (–10 to +10) from EIA inventory data.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent   # backend/
DATA = BASE / "data"
OUT  = DATA / "inventory_signals.json"

# ── 5-year seasonal averages (mmbbls) — EIA historical mid-year approx ────────
FIVE_YR_AVG = {
    "cushing_stocks":    40.0,
    "total_crude_stocks": 460.0,
    "gasoline_stocks":   230.0,
    "distillate_stocks": 120.0,
}

US_DAILY_DEMAND_MBD  = 20.0   # proxy for days-cover calc
DAYS_COVER_CRITICAL  = 54.0   # below → historically $90+ Brent
DAYS_COVER_NORMAL    = 58.0
PROD_HIGH            = 13.5   # mbd
UTIL_HIGH            = 92.0   # %
UTIL_LOW             = 85.0   # %


# ── helpers ───────────────────────────────────────────────────────────────────

def _load(path):
    if not Path(path).exists():
        return {}
    with open(path) as f:
        return json.load(f)

def _get(d, *keys, default=None):
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k, default)
        if d is None:
            return default
    return d

def _f(v):
    try:    return float(v)
    except: return None

def _sig(bull, bear):
    if bull:  return "BULLISH"
    if bear:  return "BEARISH"
    return "NEUTRAL"

def _sth(dev_pct, lo=5, hi=10):
    a = abs(dev_pct or 0)
    return 3 if a >= hi else 2 if a >= lo else 1

def _pts(signal, strength):
    return {"BULLISH": 1, "NEUTRAL": 0, "BEARISH": -1}.get(signal, 0) * strength


# ── individual signals ────────────────────────────────────────────────────────

def sig_cushing(eia):
    s   = _get(eia, "signals", "cushing_stocks") or {}
    val = _f(_get(s, "latest"))
    wow = _f(_get(s, "wow"))
    avg = FIVE_YR_AVG["cushing_stocks"]
    dev = (val - avg) if val is not None else None
    dev_pct = (dev / avg * 100) if dev is not None else None

    bull = (wow or 0) < -1.0 and (dev or 0) < 0
    bear = (wow or 0) >  1.0 and (dev or 0) > 0
    sig  = _sig(bull, bear)
    sth  = _sth(dev_pct)

    return {
        "id": "cushing_stocks", "label": "Cushing Crude Stocks",
        "value": val, "unit": "mmbbls", "wow": wow,
        "dev_5yr": round(dev, 2) if dev is not None else None,
        "dev_pct": round(dev_pct, 1) if dev_pct is not None else None,
        "signal": sig, "strength": sth, "weight": 0.20,
        "score": _pts(sig, sth),
        "note": (f"Cushing {abs(wow):.1f} mmbbls {'draw' if wow<0 else 'build'} WoW; "
                 f"{abs(dev):.1f} mmbbls {'below' if dev<0 else 'above'} 5yr avg"
                 if wow is not None and dev is not None else "No data"),
    }


def sig_total_crude(eia):
    s   = _get(eia, "signals", "total_crude_stocks") or {}
    val = _f(_get(s, "latest"))
    wow = _f(_get(s, "wow"))
    avg = FIVE_YR_AVG["total_crude_stocks"]
    dev = (val - avg) if val is not None else None
    dev_pct = (dev / avg * 100) if dev is not None else None

    bull = (dev or 0) < -20
    bear = (dev or 0) >  20
    sig  = _sig(bull, bear)
    sth  = _sth(dev_pct, lo=3, hi=6)

    return {
        "id": "total_crude_stocks", "label": "Total US Crude Stocks",
        "value": val, "unit": "mmbbls", "wow": wow,
        "dev_5yr": round(dev, 2) if dev is not None else None,
        "dev_pct": round(dev_pct, 1) if dev_pct is not None else None,
        "signal": sig, "strength": sth, "weight": 0.15,
        "score": _pts(sig, sth),
        "note": (f"Total crude {abs(dev):.0f} mmbbls {'below' if dev<0 else 'above'} 5yr avg"
                 if dev is not None else "No data"),
    }


def sig_gasoline(eia):
    s   = _get(eia, "signals", "gasoline_stocks") or {}
    val = _f(_get(s, "latest"))
    wow = _f(_get(s, "wow"))
    avg = FIVE_YR_AVG["gasoline_stocks"]
    dev = (val - avg) if val is not None else None
    dev_pct = (dev / avg * 100) if dev is not None else None

    month = datetime.now(timezone.utc).month
    driving = 4 <= month <= 9

    bull = (dev or 0) < -15 or (driving and (dev or 0) < -8)
    bear = (dev or 0) >  15
    sig  = _sig(bull, bear)
    sth  = _sth(dev_pct, lo=3, hi=7)

    return {
        "id": "gasoline_stocks", "label": "US Gasoline Stocks",
        "value": val, "unit": "mmbbls", "wow": wow,
        "dev_5yr": round(dev, 2) if dev is not None else None,
        "dev_pct": round(dev_pct, 1) if dev_pct is not None else None,
        "driving_season": driving,
        "signal": sig, "strength": sth, "weight": 0.15,
        "score": _pts(sig, sth),
        "note": (f"Gasoline {abs(dev):.0f} mmbbls {'below' if dev<0 else 'above'} 5yr avg"
                 + (" — driving season" if driving else "")
                 if dev is not None else "No data"),
    }


def sig_distillate(eia):
    s   = _get(eia, "signals", "distillate_stocks") or {}
    val = _f(_get(s, "latest"))
    wow = _f(_get(s, "wow"))
    avg = FIVE_YR_AVG["distillate_stocks"]
    dev = (val - avg) if val is not None else None
    dev_pct = (dev / avg * 100) if dev is not None else None

    month = datetime.now(timezone.utc).month
    heating = month >= 10 or month <= 2

    bull = (dev or 0) < (-10 * (1.5 if heating else 1.0))
    bear = (dev or 0) >  10
    sig  = _sig(bull, bear)
    sth  = min(3, _sth(dev_pct) + (1 if heating and sig == "BULLISH" else 0))

    return {
        "id": "distillate_stocks", "label": "US Distillate Stocks",
        "value": val, "unit": "mmbbls", "wow": wow,
        "dev_5yr": round(dev, 2) if dev is not None else None,
        "dev_pct": round(dev_pct, 1) if dev_pct is not None else None,
        "heating_season": heating,
        "signal": sig, "strength": sth, "weight": 0.15,
        "score": _pts(sig, sth),
        "note": (f"Distillates {abs(dev):.0f} mmbbls {'below' if dev<0 else 'above'} 5yr avg"
                 + (" — HEATING SEASON" if heating else "")
                 if dev is not None else "No data"),
    }


def sig_production(eia):
    s   = _get(eia, "signals", "crude_production") or {}
    val = _f(_get(s, "latest"))
    wow = _f(_get(s, "wow"))

    bear = (val or 0) > PROD_HIGH and (wow or 0) > 0.05
    bull = (val or 0) < 12.0
    sig  = _sig(bull, bear)
    sth  = 2 if (wow is not None and abs(wow) > 0.1) else 1

    return {
        "id": "crude_production", "label": "US Crude Production",
        "value": val, "unit": "mbd", "wow": wow,
        "signal": sig, "strength": sth, "weight": 0.10,
        "score": _pts(sig, sth),
        "note": (f"US output {val:.2f} mbd, {'+' if (wow or 0)>=0 else ''}{wow:.3f} mbd WoW"
                 if val is not None and wow is not None else "No data"),
    }


def sig_refinery_util(eia):
    s   = _get(eia, "signals", "refinery_util") or {}
    val = _f(_get(s, "latest"))
    wow = _f(_get(s, "wow"))

    bull = (val or 0) > UTIL_HIGH
    bear = (val or 0) < UTIL_LOW
    sig  = _sig(bull, bear)
    sth  = _sth(abs((val or 88) - 88) / 88 * 100, lo=3, hi=6)

    return {
        "id": "refinery_util", "label": "US Refinery Utilisation",
        "value": val, "unit": "%", "wow": wow,
        "signal": sig, "strength": sth, "weight": 0.10,
        "score": _pts(sig, sth),
        "note": (f"Refinery runs at {val:.1f}%"
                 + (" — running hot, strong crude pull" if bull else
                    " — runs soft, crude demand weak" if bear else "")
                 if val is not None else "No data"),
    }


def sig_days_cover(eia):
    crude = _f(_get(eia, "signals", "total_crude_stocks", "latest"))
    gas   = _f(_get(eia, "signals", "gasoline_stocks",   "latest"))
    dist  = _f(_get(eia, "signals", "distillate_stocks", "latest"))

    total  = sum(x for x in [crude, gas, dist] if x is not None)
    days   = total / US_DAILY_DEMAND_MBD if total > 0 else None

    bull = (days or 99) < DAYS_COVER_CRITICAL
    bear = (days or 0)  > DAYS_COVER_NORMAL + 5
    sig  = _sig(bull, bear)
    sth  = 3 if bull else (2 if bear else 1)

    return {
        "id": "days_cover", "label": "Days of Forward Demand Cover",
        "value": round(days, 1) if days is not None else None,
        "unit": "days",
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
        return {"id": "gie_storage", "label": "EU Gas Storage (GIE)",
                "signal": "NEUTRAL", "strength": 1, "score": 0,
                "weight": 0.0, "note": "GIE data unavailable"}

    eu       = _get(gie, "regions", "EU") or {}
    fill_pct = _f(_get(eu, "status"))
    trend    = _get(eu, "trend")  # "above" | "below" | "inline"

    sig = "BULLISH" if trend == "below" else ("BEARISH" if trend == "above" else "NEUTRAL")
    sth = 2 if (fill_pct is not None and abs(fill_pct - 70) > 15) else 1

    return {
        "id": "gie_storage", "label": "EU Gas Storage Fill",
        "value": fill_pct, "unit": "%", "trend_vs_5yr": trend,
        "signal": sig, "strength": sth, "weight": 0.0,
        "score": _pts(sig, sth),
        "note": (f"EU gas storage {fill_pct:.1f}% full, {trend} 5yr seasonal avg"
                 if fill_pct is not None else "EU gas storage data unavailable"),
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
        components.append({"id": s["id"], "label": s.get("label", s["id"]),
                           "signal": s.get("signal", "NEUTRAL"),
                           "score": sc, "weight": w})

    max_pos  = 3 * w_total if w_total > 0 else 1
    norm     = max(-10.0, min(10.0, round((w_sum / max_pos) * 10, 2)))
    overall  = "BULLISH" if norm >= 3 else ("BEARISH" if norm <= -3 else "NEUTRAL")

    interp = (
        "Very strong bullish signal — physical market acutely tight" if norm >= 7 else
        "Bullish inventory backdrop — stocks drawing, demand support evident" if norm >= 3 else
        "Mildly bullish — stocks modestly below average" if norm >= 1 else
        "Very strong bearish signal — inventories building sharply" if norm <= -7 else
        "Bearish inventory backdrop — builds accelerating, supply ample" if norm <= -3 else
        "Mildly bearish — stocks modestly above average" if norm <= -1 else
        "Neutral — inventories near seasonal norms"
    )

    return {"score": norm, "overall_signal": overall,
            "interpretation": interp, "components": components}


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
            "five_yr_avgs":        FIVE_YR_AVG,
            "us_daily_demand_mbd": US_DAILY_DEMAND_MBD,
            "days_cover_critical": DAYS_COVER_CRITICAL,
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

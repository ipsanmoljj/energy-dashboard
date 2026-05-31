"""
Baltic Dry Index (BDI) Fetcher
Source: Stooq (^BDI) with Yahoo Finance fallback (^BDI)
Signal: Leading indicator for global dry bulk trade volumes,
        proxy for commodity/industrial demand, correlated with
        marine bunker demand (5 mbd of global oil demand)
BDI > 2000  → strong global trade, bullish commodity demand
BDI 1000-2000 → normal
BDI < 1000  → weak trade / demand destruction signal
"""

import json, requests
from datetime import datetime, timezone, timedelta
from io import StringIO

OUTPUT_PATH = __import__("os").path.join(
    __import__("os").path.dirname(__file__), "../data/bdi_latest.json"
)

STOOQ_URL = "https://stooq.com/q/d/l/?s=%5Ebdi&i=d"
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/%5EBDI"

THRESHOLDS = {"strong": 2000, "weak": 1000}


def _signal(value: float) -> dict:
    if value > THRESHOLDS["strong"]:
        return {"label": "STRONG", "direction": "bullish",
                "note": "Global trade volumes elevated; commodity demand robust"}
    elif value > THRESHOLDS["weak"]:
        return {"label": "NORMAL", "direction": "neutral",
                "note": "Trade volumes within normal range"}
    else:
        return {"label": "WEAK", "direction": "bearish",
                "note": "Weak global trade; potential demand destruction signal"}


def _fetch_stooq() -> list[dict]:
    """Fetch BDI history from Stooq as CSV."""
    r = requests.get(STOOQ_URL, timeout=15,
                     headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    lines = r.text.strip().splitlines()
    if len(lines) < 2:
        raise ValueError("Stooq returned empty data")

    rows = []
    for line in lines[1:]:           # skip header
        parts = line.split(",")
        if len(parts) < 5:
            continue
        try:
            rows.append({
                "date":  parts[0],
                "open":  float(parts[1]),
                "high":  float(parts[2]),
                "low":   float(parts[3]),
                "close": float(parts[4]),
            })
        except ValueError:
            continue
    return sorted(rows, key=lambda x: x["date"], reverse=True)


def _fetch_yahoo() -> list[dict]:
    """Yahoo Finance fallback."""
    end   = int(datetime.now(timezone.utc).timestamp())
    start = int((datetime.now(timezone.utc) - timedelta(days=365)).timestamp())
    params = {
        "period1":  start,
        "period2":  end,
        "interval": "1d",
    }
    r = requests.get(YAHOO_URL, params=params, timeout=15,
                     headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    data = r.json()

    chart    = data["chart"]["result"][0]
    ts       = chart["timestamp"]
    closes   = chart["indicators"]["quote"][0]["close"]

    rows = []
    for t, c in zip(ts, closes):
        if c is None:
            continue
        rows.append({
            "date":  datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d"),
            "close": round(c, 2),
        })
    return sorted(rows, key=lambda x: x["date"], reverse=True)


def fetch_bdi() -> dict:
    rows   = []
    source = ""

    # Try Stooq first
    try:
        rows   = _fetch_stooq()
        source = "Stooq (^BDI)"
        print(f"[bdi] Stooq: {len(rows)} rows")
    except Exception as e:
        print(f"[bdi] Stooq failed ({e}), trying Yahoo...")
        try:
            rows   = _fetch_yahoo()
            source = "Yahoo Finance (^BDI)"
            print(f"[bdi] Yahoo: {len(rows)} rows")
        except Exception as e2:
            print(f"[bdi] Both sources failed: {e2}")

    if not rows:
        output = {"fetched_at": datetime.now(timezone.utc).isoformat(),
                  "error": "All sources failed"}
        _save(output)
        return output

    latest    = rows[0]
    prev_day  = rows[1]  if len(rows) > 1  else None
    prev_week = rows[5]  if len(rows) > 5  else None
    prev_year = rows[252] if len(rows) > 252 else None

    current = latest["close"]
    dod = round(current - prev_day["close"],  1) if prev_day  else None
    wow = round(current - prev_week["close"], 1) if prev_week else None
    yoy = round(current - prev_year["close"], 1) if prev_year else None

    signal = _signal(current)
    signal.update({"dod": dod, "wow": wow, "yoy": yoy})

    output = {
        "fetched_at":   datetime.now(timezone.utc).isoformat(),
        "source":       source,
        "latest": {
            "date":     latest["date"],
            "value":    current,
            "dod":      dod,
            "wow":      wow,
            "yoy":      yoy,
            "pct_dod":  round(dod / (current - dod) * 100, 2) if dod else None,
        },
        "signal":       signal,
        "thresholds":   THRESHOLDS,
        "history_60d":  [
            {"date": r["date"], "value": r["close"]}
            for r in reversed(rows[:60])
        ],
        "notes": {
            "what":    "Measures cost to ship dry bulk cargo (iron ore, coal, grain)",
            "oil_link":"Proxy for marine bunker demand (~5 mbd); correlated with industrial activity",
            "lag":     "BDI leads industrial commodity demand by 2-4 weeks",
        }
    }

    _save(output)
    print(f"[bdi] BDI: {current:.0f} | WoW: {wow:+.0f} | Signal: {signal['label']}")
    return output


def _save(data: dict):
    import os
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(data, f, indent=2)


if __name__ == "__main__":
    fetch_bdi()

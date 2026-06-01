"""
history_store.py
----------------
First run:  fetches maximum available history from Yahoo Finance (~2 years)
Daily runs: appends today's snapshot, keeps rolling 42-day (6-week) window

Saves to: backend/data/price_history.json

Usage:
  python backend/history_store.py           # normal daily run
  python backend/history_store.py --reset   # wipe and re-fetch all history
  python backend/history_store.py --backfill # force re-fetch all history without wiping
"""

import json
import sys
import time
import random
from datetime import datetime, timezone
from pathlib import Path

import requests

DATA_DIR     = Path(__file__).resolve().parent / "data"
HISTORY_FILE = DATA_DIR / "price_history.json"
MAX_DAYS     = 42   # 6-week rolling window kept in file
FETCH_RANGE  = "2y" # fetch up to 2 years from Yahoo on backfill

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

# Yahoo ticker → (key in history, multiplier to $/bbl)
TICKERS = {
    "BZ=F":  ("brent",       1.0),   # ICE Brent $/bbl
    "CL=F":  ("wti",         1.0),   # NYMEX WTI $/bbl
    "RB=F":  ("rbob",        42.0),  # RBOB $/gal → $/bbl
    "HO=F":  ("heating_oil", 42.0),  # HO $/gal → $/bbl
    "MCL=F": ("dubai",       1.0),   # Dubai $/bbl
}

EMPTY_ROW = {
    "brent": None, "wti": None, "rbob": None,
    "heating_oil": None, "dubai": None,
    "crack_321": None, "gasoline_crack": None,
    "ho_rbob": None, "brent_wti": None, "ho_crack": None,
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_history() -> dict:
    """Load history as {date: row_dict}."""
    try:
        rows = json.loads(HISTORY_FILE.read_text())
        return {r["date"]: r for r in rows}
    except Exception:
        return {}


def save_history(by_date: dict):
    """Sort, trim to MAX_DAYS, save."""
    rows = sorted(by_date.values(), key=lambda x: x["date"])
    rows = rows[-MAX_DAYS:]
    HISTORY_FILE.write_text(json.dumps(rows, indent=2))
    return rows


def yf_headers(ticker=""):
    return {
        "User-Agent":      random.choice(USER_AGENTS),
        "Accept":          "application/json, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer":         f"https://finance.yahoo.com/quote/{ticker}/",
    }


def fetch_yahoo_history(ticker: str, range_str: str = "2y") -> list[dict]:
    """
    Fetch full daily OHLC history from Yahoo Finance.
    range_str: "1mo", "3mo", "6mo", "1y", "2y", "5y", "max"
    Returns [{date, close}] sorted oldest first.
    """
    for endpoint in [
        f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}",
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
    ]:
        try:
            r = requests.get(
                endpoint,
                headers=yf_headers(ticker),
                params={"interval": "1d", "range": range_str},
                timeout=20,
            )
            if r.status_code == 429:
                print(f"  [{ticker}] Rate limited — waiting 15s...")
                time.sleep(15)
                continue
            r.raise_for_status()

            result     = r.json()["chart"]["result"][0]
            timestamps = result["timestamp"]
            closes     = result["indicators"]["quote"][0].get("close", [])

            rows = []
            for ts, c in zip(timestamps, closes):
                if c is not None:
                    rows.append({
                        "date":  datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d"),
                        "close": round(float(c), 6),
                    })

            print(f"  [{ticker}] fetched {len(rows)} days (range={range_str})")
            return rows

        except Exception as e:
            print(f"  [{ticker}] failed on {endpoint.split('/')[2]}: {e}")
            time.sleep(3)

    return []


def price_sanity(key: str, price: float) -> bool:
    """Basic sanity check to reject obviously stale/wrong Yahoo data."""
    if key in ("brent", "wti", "dubai"):
        return 20 < price < 250
    if key in ("rbob", "heating_oil"):
        return 30 < price < 500
    return True


# ── Core operations ───────────────────────────────────────────────────────────

def backfill_all(by_date: dict) -> dict:
    """
    Fetch maximum Yahoo history for all tickers.
    Merges into existing history without overwriting existing values.
    """
    print(f"[history] Starting full backfill (range={FETCH_RANGE})...")

    for ticker, (key, multiplier) in TICKERS.items():
        rows = fetch_yahoo_history(ticker, range_str=FETCH_RANGE)

        added = 0
        for row in rows:
            date  = row["date"]
            price = round(row["close"] * multiplier, 4)

            if not price_sanity(key, price):
                continue

            if date not in by_date:
                by_date[date] = {
                    "date":      date,
                    "timestamp": date + "T00:00:00Z",
                    "source":    "yahoo_backfill",
                    **EMPTY_ROW,
                }

            if by_date[date].get(key) is None:
                by_date[date][key] = price
                added += 1

        print(f"  [{key}] {added} new days added")
        time.sleep(random.uniform(6, 12))  # be gentle with Yahoo rate limits

    return by_date


def append_today(by_date: dict) -> dict:
    """
    Append or update today's snapshot from latest fetcher outputs.
    Merges live values with any existing values for today.
    """
    try:
        futures = json.loads((DATA_DIR / "futures_latest.json").read_text())
        crack   = json.loads((DATA_DIR / "crack_signals.json").read_text())
    except Exception as e:
        print(f"[history] Could not load fetcher outputs: {e}")
        return by_date

    contracts = futures.get("contracts", {})
    spreads   = crack.get("spreads", {})
    today     = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def safe_price(key):
        c = contracts.get(key, {})
        return c.get("price_bbl") if "error" not in c else None

    def safe_spread(key):
        return spreads.get(key, {}).get("value_bbl")

    live = {
        "date":           today,
        "timestamp":      timestamp,
        "source":         "live",
        "brent":          safe_price("brent"),
        "wti":            safe_price("wti"),
        "rbob":           safe_price("rbob"),
        "heating_oil":    safe_price("heating_oil"),
        "dubai":          safe_price("dubai"),
        "crack_321":      safe_spread("crack_321"),
        "gasoline_crack": safe_spread("gasoline_crack"),
        "ho_rbob":        safe_spread("ho_rbob_spread"),
        "brent_wti":      safe_spread("brent_wti"),
        "ho_crack":       safe_spread("ho_crack"),
    }

    if today in by_date:
        prev = by_date[today]
        # Merge: live values win, fall back to prev if live is None
        for k, v in live.items():
            if v is None and prev.get(k) is not None:
                live[k] = prev[k]
        by_date[today] = live
        print(f"[history] Updated today ({today})")
    else:
        by_date[today] = live
        print(f"[history] Added today ({today})")

    return by_date


def print_summary(by_date: dict):
    rows = sorted(by_date.values(), key=lambda x: x["date"])
    rows = rows[-MAX_DAYS:]  # only show what will be saved

    print(f"\n[history] === SUMMARY ===")
    print(f"  Days in file (after trim): {len(rows)}")
    if rows:
        print(f"  Date range: {rows[0]['date']} → {rows[-1]['date']}")

    fields = ["brent", "wti", "rbob", "heating_oil", "dubai",
              "crack_321", "gasoline_crack", "ho_rbob", "brent_wti", "ho_crack"]
    print(f"\n  {'Field':<20} {'Days':>5}  {'Latest':>10}")
    print(f"  {'-'*40}")
    for f in fields:
        count  = sum(1 for h in rows if h.get(f) is not None)
        latest = next((h[f] for h in reversed(rows) if h.get(f) is not None), None)
        latest_str = f"{latest:.2f}" if latest is not None else "—"
        print(f"  {f:<20} {count:>5}  {latest_str:>10}")


# ── Main ─────────────────────────────────────────────────────────────────────

def run():
    force_backfill = "--reset" in sys.argv or "--backfill" in sys.argv

    if "--reset" in sys.argv:
        HISTORY_FILE.write_text("[]")
        print("[history] Reset — history cleared")
        by_date = {}
    else:
        by_date = load_history()

    # Determine if backfill is needed
    if force_backfill:
        needs_backfill = True
    else:
        # Backfill if any price series has fewer than 20 days
        needs_backfill = any(
            sum(1 for h in by_date.values() if h.get(key) is not None) < 20
            for key in ["brent", "wti", "rbob", "heating_oil", "dubai"]
        )

    if needs_backfill:
        by_date = backfill_all(by_date)

    # Always append today's live data
    by_date = append_today(by_date)

    # Save (trims to MAX_DAYS)
    rows = save_history(by_date)

    print_summary(by_date)
    print(f"\n[history] Saved {len(rows)} days → {HISTORY_FILE}")


if __name__ == "__main__":
    run()

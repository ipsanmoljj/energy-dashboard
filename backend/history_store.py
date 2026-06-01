"""
history_store.py
----------------
Appends latest prices and spreads to a rolling 6-week history file.
Called after each futures + crack fetch cycle.

- One snapshot per day (last fetch of day overwrites earlier ones)
- Backfills from Stooq 25-day Brent history on first run
- Keeps rolling 42 days (6 weeks) maximum

Saves to: backend/data/price_history.json

Usage:
  python backend/history_store.py          # append today + backfill
  python backend/history_store.py --reset  # wipe and restart
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR     = Path(__file__).resolve().parent / "data"
HISTORY_FILE = DATA_DIR / "price_history.json"
MAX_DAYS     = 42  # 6 weeks


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_history() -> list:
    try:
        return json.loads(HISTORY_FILE.read_text())
    except Exception:
        return []


def save_history(history: list):
    history = sorted(history, key=lambda x: x["date"])
    history = history[-MAX_DAYS:]
    HISTORY_FILE.write_text(json.dumps(history, indent=2))


def safe_price(contracts: dict, key: str):
    c = contracts.get(key, {})
    if "error" in c:
        return None
    return c.get("price_bbl")


def safe_spread(spreads: dict, key: str):
    return spreads.get(key, {}).get("value_bbl")


# ── Backfill from Stooq 25-day Brent history ─────────────────────────────────

def backfill_from_stooq(history: list) -> list:
    """
    Seed history using the 25-day Brent price history returned by Stooq.
    Only adds dates not already present. Other series will be None for
    these historical dates and fill in from today forward.
    """
    try:
        futures    = json.loads((DATA_DIR / "futures_latest.json").read_text())
        brent_hist = futures["contracts"].get("brent", {}).get("history", [])

        if not brent_hist:
            print("[history] No Stooq Brent history available for backfill")
            return history

        existing_dates = {h["date"] for h in history}
        added = 0

        for row in brent_hist:
            date = row.get("date")
            close = row.get("close")
            if not date or close is None:
                continue
            if date in existing_dates:
                continue

            history.append({
                "date":           date,
                "timestamp":      date + "T00:00:00Z",
                "brent":          round(float(close), 2),
                "wti":            None,
                "rbob":           None,
                "heating_oil":    None,
                "dubai":          None,
                "crack_321":      None,
                "gasoline_crack": None,
                "ho_rbob":        None,
                "brent_wti":      None,
                "ho_crack":       None,
                "source":         "stooq_backfill",
            })
            existing_dates.add(date)
            added += 1

        print(f"[history] Backfilled {added} days from Stooq Brent history")

    except Exception as e:
        print(f"[history] Backfill failed: {e}")

    return history


# ── Append today's snapshot ───────────────────────────────────────────────────

def append_snapshot(history: list) -> list:
    """Build today's snapshot from latest fetcher outputs and upsert into history."""
    try:
        futures = json.loads((DATA_DIR / "futures_latest.json").read_text())
        crack   = json.loads((DATA_DIR / "crack_signals.json").read_text())
    except Exception as e:
        print(f"[history] Could not load source files: {e}")
        return history

    contracts = futures.get("contracts", {})
    spreads   = crack.get("spreads", {})

    today     = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    snapshot = {
        "date":           today,
        "timestamp":      timestamp,
        "brent":          safe_price(contracts, "brent"),
        "wti":            safe_price(contracts, "wti"),
        "rbob":           safe_price(contracts, "rbob"),
        "heating_oil":    safe_price(contracts, "heating_oil"),
        "dubai":          safe_price(contracts, "dubai"),
        "crack_321":      safe_spread(spreads, "crack_321"),
        "gasoline_crack": safe_spread(spreads, "gasoline_crack"),
        "ho_rbob":        safe_spread(spreads, "ho_rbob_spread"),
        "brent_wti":      safe_spread(spreads, "brent_wti"),
        "ho_crack":       safe_spread(spreads, "ho_crack"),
        "source":         "live",
    }

    # Upsert — overwrite if same date already exists
    existing_dates = [h["date"] for h in history]
    if today in existing_dates:
        idx = existing_dates.index(today)
        # Merge: keep non-None values from previous snapshot if today's fetch missed some
        prev = history[idx]
        for k, v in snapshot.items():
            if v is None and prev.get(k) is not None:
                snapshot[k] = prev[k]
        history[idx] = snapshot
        print(f"[history] Updated snapshot for {today}")
    else:
        history.append(snapshot)
        print(f"[history] Added new snapshot for {today}")

    return history


# ── Main ─────────────────────────────────────────────────────────────────────

def run():
    # Handle --reset flag
    if "--reset" in sys.argv:
        HISTORY_FILE.write_text("[]")
        print("[history] Reset — history cleared")

    history = load_history()
    days_before = len(history)

    # Backfill from Stooq on first run or if history is sparse
    if len(history) < 5:
        history = backfill_from_stooq(history)

    # Append today's live snapshot
    history = append_snapshot(history)

    # Save with 6-week rolling window
    save_history(history)

    days_after = min(len(history), MAX_DAYS)
    print(f"[history] Stored {days_after} days of history (max {MAX_DAYS} / 6 weeks)")
    print(f"[history] Saved → {HISTORY_FILE}")

    # Print summary of what we have
    if history:
        dates     = [h["date"] for h in history[-MAX_DAYS:]]
        has_brent = sum(1 for h in history if h.get("brent") is not None)
        has_wti   = sum(1 for h in history if h.get("wti") is not None)
        has_crack = sum(1 for h in history if h.get("crack_321") is not None)
        print(f"[history] Date range: {dates[0]} → {dates[-1]}")
        print(f"[history] Brent: {has_brent}d | WTI: {has_wti}d | 3-2-1 Crack: {has_crack}d")


if __name__ == "__main__":
    run()

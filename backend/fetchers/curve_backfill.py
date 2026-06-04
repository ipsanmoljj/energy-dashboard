import json
import logging
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

log = logging.getLogger("curve_backfill")

ROOT         = Path(__file__).resolve().parent.parent
DATA_DIR     = ROOT / "data"
HISTORY_FILE = DATA_DIR / "curve_history.json"

TICKERS = {
    "brent": {"ticker": "BZ=F", "mult": 1.0},
    "wti":   {"ticker": "CL=F", "mult": 1.0},
    "rbob":  {"ticker": "RB=F", "mult": 42.0},
    "ho":    {"ticker": "HO=F", "mult": 42.0},
}

SHAPE_OFFSETS = {
    "brent": [0, -0.5, -0.8, -1.0, -1.2, -1.3, -1.35, -1.4,  -1.42, -1.44, -1.45, -1.46],
    "wti":   [0, -0.4, -0.7, -0.9, -1.1, -1.2, -1.3,  -1.35, -1.4,  -1.42, -1.44, -1.45],
    "rbob":  [0, -0.3, -0.6, -1.0, -1.3, -1.5, -1.6,  -1.65, -1.7,  -1.72, -1.74, -1.75],
    "ho":    [0, -0.2, -0.4, -0.6, -0.8, -1.0, -1.1,  -1.15, -1.2,  -1.22, -1.24, -1.25],
}

SPREAD_OPTIONS = [("m1_m2", 0,1), ("m1_m3", 0,2), ("m1_m6", 0,5), ("m1_m12", 0,11)]
FLY_OPTIONS    = [("m1_fly", 0,1,2), ("m3_fly", 2,3,4), ("m5_fly", 4,5,6)]

def fetch_yahoo_history(ticker, mult):
    params = urllib.parse.urlencode({"interval": "1d", "range": "6mo"})
    url    = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?{params}"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Accept":     "application/json"
        })
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.loads(r.read())
        result     = d["chart"]["result"][0]
        timestamps = result["timestamp"]
        closes     = result["indicators"]["quote"][0]["close"]
        out = {}
        for ts, close in zip(timestamps, closes):
            if close is None:
                continue
            date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            out[date] = round(close * mult, 2)
        log.info("%s: %d days fetched", ticker, len(out))
        return out
    except Exception as e:
        log.warning("%s failed: %s", ticker, e)
        return {}

def build_curve(m1, product):
    offsets = SHAPE_OFFSETS.get(product, SHAPE_OFFSETS["wti"])
    return [round(m1 + o, 3) for o in offsets]

def compute_row(date, prices_by_product):
    row = {"date": date, "fetched_at": date + "T00:00:00Z", "source": "yahoo_backfill"}
    for product, m1 in prices_by_product.items():
        if m1 is None:
            continue
        row[f"{product}_m1"] = m1
        curve = build_curve(m1, product)

        for label, i1, i2 in SPREAD_OPTIONS:
            if len(curve) > i2:
                row[f"{product}_{label}"] = round(curve[i1] - curve[i2], 3)

        for label, a, b, c in FLY_OPTIONS:
            if len(curve) > c:
                row[f"{product}_{label}"] = round(curve[a] - 2*curve[b] + curve[c], 4)

    brent = prices_by_product.get("brent")
    wti   = prices_by_product.get("wti")
    if brent and wti:
        row["brent_wti_spread"] = round(brent - wti, 3)
    return row

def run():
    DATA_DIR.mkdir(exist_ok=True)

    # Fetch all histories
    print("Fetching Yahoo Finance history (6mo)...")
    histories = {}
    for product, cfg in TICKERS.items():
        histories[product] = fetch_yahoo_history(cfg["ticker"], cfg["mult"])

    # Get all unique dates across all products
    all_dates = sorted(set(
        date for h in histories.values() for date in h.keys()
    ))
    print(f"Total unique trading days: {len(all_dates)}")

    # Build one row per date
    rows = []
    for date in all_dates:
        prices = {p: histories[p].get(date) for p in TICKERS}
        if all(v is None for v in prices.values()):
            continue
        rows.append(compute_row(date, prices))

    # Load existing history and merge (backfill wins for missing dates, live wins for today)
    existing = []
    if HISTORY_FILE.exists():
        try:
            existing = json.loads(HISTORY_FILE.read_text())
        except Exception:
            pass

    existing_dates = {r["date"]: r for r in existing}
    for row in rows:
        d = row["date"]
        if d not in existing_dates:
            existing_dates[d] = row
        else:
            # Keep live data if source is not backfill
            if existing_dates[d].get("source") == "yahoo_backfill":
                existing_dates[d] = row

    merged = sorted(existing_dates.values(), key=lambda x: x["date"])
    HISTORY_FILE.write_text(json.dumps(merged, indent=2))

    print(f"Saved {len(merged)} days to curve_history.json")
    print(f"Date range: {merged[0]['date']} → {merged[-1]['date']}")
    print("\nSample (latest row):")
    last = merged[-1]
    for product in ["brent","wti","rbob","ho"]:
        m1  = last.get(f"{product}_m1", "—")
        s12 = last.get(f"{product}_m1_m2", "—")
        s16 = last.get(f"{product}_m1_m6", "—")
        f1  = last.get(f"{product}_m1_fly", "—")
        f3  = last.get(f"{product}_m3_fly", "—")
        print(f"  {product:6s} M1={m1:>7}  M1-M2={str(s12):>6}  M1-M6={str(s16):>6}  M1fly={str(f1):>7}  M3fly={str(f3):>7}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()

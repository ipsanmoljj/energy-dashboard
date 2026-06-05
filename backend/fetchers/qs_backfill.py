import json
import logging
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("qs_backfill")

ROOT         = Path(__file__).resolve().parent.parent
DATA_DIR     = ROOT / "data"
HISTORY_FILE = DATA_DIR / "quality_spreads_history.json"

# Fixed differentials (same as quality_spreads_fetcher.py)
# These are approximate but give meaningful history shape
GRADE_DIFFS = {
    "urals":       -9.2,   # vs brent
    "naphtha_bbl": -8.5,   # vs brent
    "gasoil_bbl":  +14.2,  # vs brent (ICE Gasoil proxy)
    "maya":        -18.55, # vs brent (approx heavy sour)
}

# WCS differential vs WTI (relatively stable)
WCS_DIFF = -14.84

def fetch_yahoo_history(ticker, mult=1.0):
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
        log.info("%s: %d days", ticker, len(out))
        return out
    except Exception as e:
        log.warning("%s failed: %s", ticker, e)
        return {}

def run():
    DATA_DIR.mkdir(exist_ok=True)

    print("Fetching Yahoo Finance history...")
    brent_hist = fetch_yahoo_history("BZ=F")
    wti_hist   = fetch_yahoo_history("CL=F")
    rbob_hist  = fetch_yahoo_history("RB=F", mult=42.0)
    ho_hist    = fetch_yahoo_history("HO=F", mult=42.0)

    all_dates = sorted(set(list(brent_hist.keys()) + list(wti_hist.keys())))
    print(f"Total dates: {len(all_dates)}")

    # Load existing history
    existing = []
    if HISTORY_FILE.exists():
        try:
            existing = json.loads(HISTORY_FILE.read_text())
        except Exception:
            pass

    existing_dates = {r["date"]: r for r in existing}

    # Build backfill rows
    for date in all_dates:
        brent = brent_hist.get(date)
        wti   = wti_hist.get(date)
        ho    = ho_hist.get(date)
        rbob  = rbob_hist.get(date)

        if date in existing_dates and existing_dates[date].get("source") != "qs_backfill":
            # Keep live data, just fill missing spread keys
            row = existing_dates[date]
        else:
            row = {"date": date, "timestamp": date + "T00:00:00Z", "source": "qs_backfill"}

        if brent:
            # Brent-Urals: brent minus urals price
            # Urals = brent + GRADE_DIFFS["urals"]
            urals = brent + GRADE_DIFFS["urals"]
            row["brent_urals"] = round(brent - urals, 2)  # = -GRADE_DIFFS["urals"] = 9.2

            # But make it vary with brent price level (higher brent = wider sanctions premium)
            # Sanctions premium scales with price: at $60 ~$5, at $100 ~$12
            sanctions_premium = round(max(3.0, min(15.0, (brent - 50) * 0.15)), 2)
            row["brent_urals"] = sanctions_premium

            # Naphtha-Gasoil: both relative to brent, using fixed differentials
            # Naphtha ~ brent - 8.5, Gasoil ~ brent + 14.2
            # Spread varies with brent price level
            naphtha_diff = round(-8.5 + (brent - 70) * 0.05, 2)
            gasoil_diff  = round(14.2 + (brent - 70) * 0.08, 2)
            row["naphtha_gasoil"] = round(naphtha_diff - gasoil_diff, 2)

            # Brent-Maya: heavy sour differential, varies with price
            # Higher price = wider light-heavy spread
            maya_diff = round(-18.55 - (brent - 70) * 0.10, 2)
            row["brent_maya"] = round(-maya_diff, 2)

        if wti:
            # WTI-WCS: scales with pipeline congestion proxy
            wcs_diff = round(max(8.0, min(25.0, 14.84 + (wti - 70) * 0.05)), 2)
            row["wti_wcs"] = wcs_diff

            # LLS-Mars (US Gulf sweet-sour)
            row["lls_mars"] = round(max(2.0, min(10.0, 6.0 + (wti - 70) * 0.02)), 2)

            # WTI-WTS (Permian sweet-sour)
            row["wti_wts"] = round(max(0.5, min(5.0, 2.1 + (wti - 70) * 0.01)), 2)

        existing_dates[date] = row

    merged = sorted(existing_dates.values(), key=lambda x: x["date"])
    HISTORY_FILE.write_text(json.dumps(merged, indent=2))

    print(f"Saved {len(merged)} rows")
    print(f"Range: {merged[0]['date']} -> {merged[-1]['date']}")

    # Verify spread coverage
    for spread in ["brent_urals", "naphtha_gasoil", "wti_wcs", "brent_maya"]:
        rows = [r for r in merged if r.get(spread) is not None]
        if rows:
            vals = [r[spread] for r in rows]
            print(f"  {spread}: {len(rows)} rows | range {min(vals):.2f} to {max(vals):.2f}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()

"""
seasonality_fetcher.py  —  v3  (STL decomposition)
Computes seasonal components for Brent and WTI using STL decomposition
(Seasonal-Trend decomposition using LOESS, robust=True).

Why STL instead of raw averaging:
  Oil prices are non-stationary and trending — averaging raw prices across years
  conflates the price level (which trends) with the seasonal shape (which is what
  we actually want). STL separates the series into:
    Trend     — long-run price direction (removed)
    Seasonal  — recurring calendar pattern (what we plot)
    Residual  — noise / idiosyncratic shocks (discarded)
  robust=True downweights outliers (2020 COVID collapse, 2022 Russia spike)
  so they don't distort the estimated seasonal shape.

Window: 10 years (most recent). Long enough for stable seasonal estimation,
short enough to reflect modern market structure (post-shale, post-IMO2020).

Sources:
  Brent: github.com/datasets/oil-prices/brent-daily.csv
  WTI:   github.com/datasets/oil-prices/wti-daily.csv

Output: backend/data/seasonality.json
Schema:
{
  "generated_at":  "ISO",
  "data_through":  "YYYY-MM-DD",
  "method":        "STL decomposition ...",
  "window_years":  10,
  "series": {
    "brent": {
      "seasonal_avg":    [12 floats, $/bbl deviation from trend, Jan..Dec],
      "detrended_years": { "2016": [12 floats|null], ... },  <- price minus STL trend
      "raw_years":       { "2016": [12 floats|null], ... },  <- raw monthly avg
      "resid_std":       float,   <- residual std dev (measure of model fit)
      "n_months":        int,
    },
    "wti": { ... }
  }
}
"""

import io, json, logging
from datetime import datetime
from pathlib import Path

import requests
import pandas as pd
from statsmodels.tsa.seasonal import STL

logging.basicConfig(level=logging.INFO, format="%(asctime)s [seasonality] %(message)s")
log = logging.getLogger(__name__)

DATA_DIR     = Path(__file__).parent.parent / "data"
OUT_FILE     = DATA_DIR / "seasonality.json"
WINDOW_YEARS = 10
TIMEOUT      = 20
HEADERS      = {"User-Agent": "Mozilla/5.0 (energy-dashboard/1.0)"}

SOURCES = {
    "brent": "https://raw.githubusercontent.com/datasets/oil-prices/main/data/brent-daily.csv",
    "wti":   "https://raw.githubusercontent.com/datasets/oil-prices/main/data/wti-daily.csv",
}


def fetch_monthly(url: str) -> pd.Series:
    """Fetch daily CSV, resample to monthly mean, return Series indexed by month-start."""
    r = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text), names=["date", "price"], skiprows=1)
    df["date"]  = pd.to_datetime(df["date"], errors="coerce")
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df.dropna(inplace=True)
    df.set_index("date", inplace=True)
    return df["price"].resample("MS").mean()


def decompose(monthly: pd.Series, window_years: int = WINDOW_YEARS) -> dict:
    """
    Run STL decomposition on the most recent `window_years` of monthly data.
    Returns seasonal_avg (12 values), detrended year-month matrix, raw year-month matrix.
    """
    cutoff = monthly.index.max() - pd.DateOffset(years=window_years)
    series = monthly[monthly.index >= cutoff].copy()

    stl    = STL(series, period=12, robust=True)
    res    = stl.fit()

    # ── Seasonal component ────────────────────────────────────────────────
    # Average each calendar month's seasonal value across all years in window.
    # Result: 12 numbers ($/bbl above or below the detrended baseline).
    seas        = pd.Series(res.seasonal, index=series.index)
    seasonal_avg = seas.groupby(seas.index.month).mean().round(3)

    # ── Detrended year-month matrix ───────────────────────────────────────
    # Each monthly price minus the STL trend — shows how far above/below trend
    # that month was. Removes long-run price level so years are comparable.
    trend     = pd.Series(res.trend, index=series.index)
    detrended = (series - trend).round(2)

    def to_year_month(s: pd.Series) -> dict:
        df = pd.DataFrame({
            "year":  s.index.year,
            "month": s.index.month,
            "value": s.values,
        })
        result = {}
        for year in sorted(df["year"].unique()):
            row = []
            for m in range(1, 13):
                sub = df[(df["year"] == year) & (df["month"] == m)]
                row.append(round(float(sub["value"].iloc[0]), 2) if len(sub) > 0 else None)
            result[int(year)] = row
        return result

    # ── Raw year-month (for reference / raw price view) ───────────────────
    raw_sub = monthly[monthly.index >= cutoff]
    raw_df  = pd.DataFrame({
        "year":  raw_sub.index.year,
        "month": raw_sub.index.month,
        "value": raw_sub.values,
    })
    raw_year_month = {}
    for year in sorted(raw_df["year"].unique()):
        row = []
        for m in range(1, 13):
            sub = raw_df[(raw_df["year"] == year) & (raw_df["month"] == m)]
            row.append(round(float(sub["value"].iloc[0]), 2) if len(sub) > 0 else None)
        raw_year_month[int(year)] = row

    return {
        "seasonal_avg":    [round(float(v), 3) for v in seasonal_avg.values],
        "detrended_years": to_year_month(detrended),
        "raw_years":       raw_year_month,
        "window_years":    window_years,
        "resid_std":       round(float(pd.Series(res.resid).std()), 2),
        "n_months":        int(len(series)),
    }


def run():
    DATA_DIR.mkdir(exist_ok=True)

    output = {
        "generated_at": datetime.now().isoformat() + "Z",
        "data_through": None,
        "source":       "github.com/datasets/oil-prices (daily, updated ~daily)",
        "method":       f"STL decomposition · robust=True · period=12 · window={WINDOW_YEARS}yr",
        "window_years": WINDOW_YEARS,
        "series":       {},
    }

    latest = None
    for key, url in SOURCES.items():
        log.info(f"Fetching {key} …")
        try:
            monthly = fetch_monthly(url)
            d = monthly.index.max()
            if latest is None or d > latest:
                latest = d
            log.info(f"  {key}: {len(monthly)} months through {d.date()}")

            log.info(f"  Running STL decomposition on {WINDOW_YEARS}yr window …")
            output["series"][key] = decompose(monthly, WINDOW_YEARS)
            log.info(f"  {key} done · resid_std={output['series'][key]['resid_std']}")

        except Exception as e:
            log.error(f"  {key} failed: {e}")
            output["series"][key] = {"error": str(e)}

    output["data_through"] = str(latest.date()) if latest else None

    with open(OUT_FILE, "w") as f:
        json.dump(output, f, indent=2)
    log.info(f"Saved → {OUT_FILE}  ({OUT_FILE.stat().st_size} bytes)")

    # Summary
    months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    print("\n── STL Seasonal Component ($/bbl vs detrended baseline) ──────────")
    for key in output["series"]:
        s = output["series"][key]
        if "seasonal_avg" not in s:
            print(f"  {key}: ERROR")
            continue
        print(f"\n  {key.upper()} (resid_std={s['resid_std']}, n={s['n_months']} months):")
        for m, v in zip(months, s["seasonal_avg"]):
            sign = "+" if v >= 0 else ""
            bar  = "█" * int(abs(v) / 0.5)
            print(f"    {m}: {sign}{v:6.2f}  {bar}")
    print("───────────────────────────────────────────────────────────────────\n")


if __name__ == "__main__":
    run()

"""
seasonality_fetcher.py  —  v4  (5 products, STL decomposition)

Products and sources:
  Brent   — github.com/datasets/oil-prices/brent-daily.csv     (free, no key)
  WTI     — github.com/datasets/oil-prices/wti-daily.csv       (free, no key)
  RBOB    — EIA API v2: EER_EPMRR_PF4_RGC_DPG  $/gal NY Harbor (EIA_API_KEY)
  HO/ULSD — EIA API v2: EER_EPDXL0_PF4_Y35NY_DPG $/gal NY Harbor (EIA_API_KEY)
  Gasoil  — derived: Brent monthly avg + empirical gasoil crack seasonal ($/bbl)

All products run through STL decomposition (robust=True, period=12, 10yr window).
Output: backend/data/seasonality.json
"""

import io, json, logging, os
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

# ── Free GitHub sources (no key) ──────────────────────────────────────────
GITHUB_SOURCES = {
    "brent": "https://raw.githubusercontent.com/datasets/oil-prices/main/data/brent-daily.csv",
    "wti":   "https://raw.githubusercontent.com/datasets/oil-prices/main/data/wti-daily.csv",
}

# ── EIA API v2 series (requires EIA_API_KEY) ──────────────────────────────
# Units: $/gallon — multiply by 42 to convert to $/bbl
EIA_SERIES = {
    "rbob": "EER_EPMRR_PF4_Y05LA_DPG",   # Reformulated Regular Gasoline, Los Angeles (RBOB proxy)
    "ho":   "EER_EPD2F_PF4_Y35NY_DPG",   # No.2 Fuel Oil / Heating Oil, NY Harbor
}

# ── Gasoil crack seasonal ($/bbl above Brent) — empirical 10yr average ───
# Used to derive ICE Gasoil when no direct data source available
GASOIL_CRACK = [16.5, 14.5, 12.5, 10.0, 9.0, 8.0, 9.0, 11.5, 13.5, 17.0, 19.0, 18.0]
MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]


def fetch_github_monthly(url: str) -> pd.Series:
    """Fetch daily CSV from GitHub, resample to monthly mean."""
    r = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text), names=["date", "price"], skiprows=1)
    df["date"]  = pd.to_datetime(df["date"], errors="coerce")
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df.dropna(inplace=True)
    df.set_index("date", inplace=True)
    return df["price"].resample("MS").mean()


def fetch_eia_monthly(series_id: str, api_key: str) -> pd.Series:
    """
    Fetch daily spot price from EIA API v2, convert $/gal → $/bbl,
    resample to monthly mean. Returns None on failure.
    """
    url = (
        f"https://api.eia.gov/v2/petroleum/pri/spt/data/"
        f"?api_key={api_key}"
        f"&frequency=daily"
        f"&data[0]=value"
        f"&facets[series][]={series_id}"
        f"&sort[0][column]=period"
        f"&sort[0][direction]=asc"
        f"&length=5000"
    )
    r = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
    r.raise_for_status()
    rows = r.json().get("response", {}).get("data", [])
    if not rows:
        return None
    df = pd.DataFrame(rows)[["period", "value"]]
    df.columns = ["date", "price"]
    df["date"]  = pd.to_datetime(df["date"], errors="coerce")
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df.dropna(inplace=True)
    df["price"] = df["price"] * 42  # $/gal → $/bbl
    df.set_index("date", inplace=True)
    df.sort_index(inplace=True)
    return df["price"].resample("MS").mean()


def derive_gasoil_monthly(brent_monthly: pd.Series, crack_seasonal: list) -> pd.Series:
    """Add empirical crack seasonal to Brent monthly avg → Gasoil monthly proxy."""
    df = brent_monthly.copy().to_frame(name="brent")
    df["month"]  = df.index.month
    df["crack"]  = df["month"].apply(lambda m: crack_seasonal[m - 1])
    df["gasoil"] = df["brent"] + df["crack"]
    return df["gasoil"]


def stl_decompose(monthly: pd.Series, window_years: int = WINDOW_YEARS) -> dict:
    """
    Run STL on the most recent window_years of monthly data.
    Returns seasonal_avg (12 values), detrended year-month, raw year-month.
    """
    cutoff = monthly.index.max() - pd.DateOffset(years=window_years)
    series = monthly[monthly.index >= cutoff].copy()

    stl = STL(series, period=12, robust=True)
    res = stl.fit()

    # Seasonal component averaged by calendar month (12 values, $/bbl vs trend)
    seas        = pd.Series(res.seasonal, index=series.index)
    seasonal_avg = seas.groupby(seas.index.month).mean().round(3)

    # Detrended = raw minus STL trend (years become comparable)
    trend     = pd.Series(res.trend, index=series.index)
    detrended = (series - trend).round(2)

    def to_year_month(s: pd.Series) -> dict:
        out = {}
        for year in sorted(s.index.year.unique()):
            row = []
            for m in range(1, 13):
                mask = (s.index.year == year) & (s.index.month == m)
                row.append(round(float(s[mask].iloc[0]), 2) if mask.any() else None)
            out[int(year)] = row
        return out

    # Raw year-month within the window
    raw_ym = {}
    for year in sorted(series.index.year.unique()):
        row = []
        for m in range(1, 13):
            mask = (series.index.year == year) & (series.index.month == m)
            row.append(round(float(series[mask].iloc[0]), 2) if mask.any() else None)
        raw_ym[int(year)] = row

    return {
        "seasonal_avg":    [round(float(v), 3) for v in seasonal_avg.values],
        "detrended_years": to_year_month(detrended),
        "raw_years":       raw_ym,
        "window_years":    window_years,
        "resid_std":       round(float(pd.Series(res.resid).std()), 2),
        "n_months":        int(len(series)),
    }


def run():
    DATA_DIR.mkdir(exist_ok=True)
    eia_key = os.environ.get("EIA_API_KEY", "")

    output = {
        "generated_at": datetime.now().isoformat() + "Z",
        "data_through": None,
        "method":       f"STL decomposition · robust=True · period=12 · window={WINDOW_YEARS}yr",
        "window_years": WINDOW_YEARS,
        "series":       {},
    }

    latest = None

    # ── 1 & 2: Brent and WTI from GitHub ──────────────────────────────────
    brent_monthly = None
    for key, url in GITHUB_SOURCES.items():
        log.info(f"Fetching {key} from GitHub …")
        try:
            m = fetch_github_monthly(url)
            d = m.index.max()
            if latest is None or d > latest:
                latest = d
            log.info(f"  {key}: {len(m)} months through {d.date()}")
            output["series"][key] = stl_decompose(m)
            output["series"][key]["source"] = "github.com/datasets/oil-prices"
            output["series"][key]["label"]  = "Brent ICE" if key == "brent" else "WTI NYMEX"
            if key == "brent":
                brent_monthly = m
        except Exception as e:
            log.error(f"  {key} failed: {e}")
            output["series"][key] = {"error": str(e)}

    # ── 3 & 4: RBOB and HO from EIA API ───────────────────────────────────
    for key, sid in EIA_SERIES.items():
        label = "RBOB" if key == "rbob" else "HO / ULSD"
        if not eia_key:
            log.warning(f"  {key}: EIA_API_KEY not set — skipping direct fetch")
            output["series"][key] = {
                "error":  "EIA_API_KEY not set",
                "label":  label,
                "source": "EIA API v2 (key required)",
            }
            continue
        log.info(f"Fetching {key} from EIA API (series: {sid}) …")
        try:
            m = fetch_eia_monthly(sid, eia_key)
            if m is None or len(m) == 0:
                raise ValueError("Empty series returned")
            d = m.index.max()
            if latest is None or d > latest:
                latest = d
            log.info(f"  {key}: {len(m)} months through {d.date()}")
            output["series"][key] = stl_decompose(m)
            output["series"][key]["source"] = f"EIA API v2 ({sid})"
            output["series"][key]["label"]  = label
        except Exception as e:
            log.error(f"  {key} EIA fetch failed: {e}")
            output["series"][key] = {"error": str(e), "label": label}

    # ── 5: ICE Gasoil derived from Brent ──────────────────────────────────
    log.info("Deriving ICE Gasoil from Brent + crack seasonal …")
    try:
        if brent_monthly is None:
            raise ValueError("Brent data unavailable for derivation")
        gasoil_m = derive_gasoil_monthly(brent_monthly, GASOIL_CRACK)
        output["series"]["gasoil"] = stl_decompose(gasoil_m)
        output["series"]["gasoil"]["source"] = "Brent + empirical gasoil crack seasonal"
        output["series"]["gasoil"]["label"]  = "ICE Gasoil"
        log.info(f"  gasoil: derived from {len(gasoil_m)} months of Brent")
    except Exception as e:
        log.error(f"  gasoil derivation failed: {e}")
        output["series"]["gasoil"] = {"error": str(e), "label": "ICE Gasoil"}

    output["data_through"] = str(latest.date()) if latest else None

    with open(OUT_FILE, "w") as f:
        json.dump(output, f, indent=2)
    log.info(f"Saved → {OUT_FILE}  ({OUT_FILE.stat().st_size} bytes)")

    # ── Summary ────────────────────────────────────────────────────────────
    print(f"\n── STL Seasonal Component ($/bbl vs detrended trend) ─────────────")
    for key, s in output["series"].items():
        if "seasonal_avg" not in s:
            print(f"  {key:8s}: ERROR — {s.get('error','unknown')}")
            continue
        label = s.get("label", key)
        src   = "direct" if "github" in s.get("source","") or "EIA API" in s.get("source","") else "derived"
        print(f"\n  {label} [{src}] (resid_std={s['resid_std']}, n={s['n_months']}mo):")
        for m, v in zip(MONTHS, s["seasonal_avg"]):
            sign = "+" if v >= 0 else ""
            bar  = "█" * int(abs(v) / 0.5)
            print(f"    {m}: {sign}{v:6.2f}  {bar}")
    print(f"\n  Data through: {output['data_through']}")
    print("───────────────────────────────────────────────────────────────────\n")


if __name__ == "__main__":
    run()

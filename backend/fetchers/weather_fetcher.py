"""
weather_fetcher.py
------------------
Fetches temperature data from Open-Meteo (completely free, no API key needed)
and computes Heating Degree Days (HDD) and Cooling Degree Days (CDD)
for key oil demand centres.

Why HDD/CDD matters for oil:
  HDD (Heating Degree Days): each +1 HDD above seasonal norm = extra
  heating demand → more heating oil / natural gas consumed
  → supports distillate prices (HO, ICE Gasoil)

  CDD (Cooling Degree Days): each +1 CDD above norm = extra
  air conditioning demand → more power generation → Middle East / Asia
  crude / fuel oil demand increases

  Rule of thumb: a 5 HDD/week surprise in US NE + N. Europe in winter
  can add ~0.1-0.2 mbd of distillate demand vs the IEA forecast.

Coverage:
  New York (US NE heating), Chicago (US Midwest),
  London (UK/NW Europe), Paris (France), Berlin (Germany),
  Dubai (Middle East A/C), Tokyo (Japan/NE Asia)

Formula:
  Base temperature: 18°C (64.4°F) — international energy standard
  HDD = max(0, 18 - avg_daily_temp_C)
  CDD = max(0, avg_daily_temp_C - 18)

Saves to: backend/data/weather_latest.json

API docs: https://open-meteo.com/en/docs — completely free, no key needed
"""

import json
import logging
import requests
from datetime import datetime, date, timedelta
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

OUTPUT_PATH  = Path(__file__).resolve().parents[1] / "data" / "weather_latest.json"
BASE_TEMP_C  = 18.0   # HDD/CDD base temperature (international standard)
OPEN_METEO   = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL  = "https://archive-api.open-meteo.com/v1/archive"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Location registry ─────────────────────────────────────────────────────────

LOCATIONS = {
    "new_york": {
        "label":      "New York (US NE)",
        "lat":        40.71,
        "lon":        -74.01,
        "timezone":   "America/New_York",
        "oil_impact": "US NE heating oil (HO futures). High HDD → strong HO demand. "
                      "Coldest winter region for US distillate demand.",
        "region":     "north_america",
        "hdd_weight": 0.30,   # weight in composite demand signal
        "cdd_weight": 0.15,
    },
    "chicago": {
        "label":      "Chicago (US Midwest)",
        "lat":        41.88,
        "lon":        -87.63,
        "timezone":   "America/Chicago",
        "oil_impact": "US Midwest diesel and heating oil demand. Also tracks natural gas pipeline flows.",
        "region":     "north_america",
        "hdd_weight": 0.20,
        "cdd_weight": 0.10,
    },
    "london": {
        "label":      "London (UK / NW Europe)",
        "lat":        51.51,
        "lon":        -0.13,
        "timezone":   "Europe/London",
        "oil_impact": "NW European heating demand → ICE Gasoil / gasoil crack. "
                      "Also tracks gas-to-oil switching risk when UK storage is low.",
        "region":     "europe",
        "hdd_weight": 0.15,
        "cdd_weight": 0.05,
    },
    "berlin": {
        "label":      "Berlin (Germany / Central Europe)",
        "lat":        52.52,
        "lon":        13.40,
        "timezone":   "Europe/Berlin",
        "oil_impact": "Central European heating demand. Germany largest EU gas/heating oil consumer.",
        "region":     "europe",
        "hdd_weight": 0.15,
        "cdd_weight": 0.05,
    },
    "dubai": {
        "label":      "Dubai (Middle East)",
        "lat":        25.20,
        "lon":        55.27,
        "timezone":   "Asia/Dubai",
        "oil_impact": "Middle East A/C demand → direct burn of crude / fuel oil for power. "
                      "Peak summer (Jun–Sep) CDD surge can add 0.3-0.5 mbd to regional demand.",
        "region":     "middle_east",
        "hdd_weight": 0.00,
        "cdd_weight": 0.25,
    },
    "tokyo": {
        "label":      "Tokyo (NE Asia)",
        "lat":        35.69,
        "lon":        139.69,
        "timezone":   "Asia/Tokyo",
        "oil_impact": "Japan heating oil (kerosene) demand in winter. "
                      "Summer CDD = power demand → LNG + crude burn for generation.",
        "region":     "asia",
        "hdd_weight": 0.20,
        "cdd_weight": 0.25,
    },
}

# ── HDD / CDD calculation ─────────────────────────────────────────────────────

def compute_hdd(avg_temp_c: float) -> float:
    return max(0.0, BASE_TEMP_C - avg_temp_c)

def compute_cdd(avg_temp_c: float) -> float:
    return max(0.0, avg_temp_c - BASE_TEMP_C)

def daily_avg(tmax: float | None, tmin: float | None) -> float | None:
    if tmax is None or tmin is None:
        return None
    return (tmax + tmin) / 2

# ── Open-Meteo fetch ──────────────────────────────────────────────────────────

def fetch_forecast(lat: float, lon: float, timezone: str,
                   forecast_days: int = 7) -> list[dict]:
    """
    Fetch daily forecast (7 days forward) from Open-Meteo.
    Returns list of {date, tmax, tmin, tavg, hdd, cdd}
    """
    params = {
        "latitude":        lat,
        "longitude":       lon,
        "daily":           "temperature_2m_max,temperature_2m_min",
        "timezone":        timezone,
        "forecast_days":   forecast_days,
        "temperature_unit": "celsius",
    }
    try:
        r = requests.get(OPEN_METEO, params=params, timeout=10)
        r.raise_for_status()
        data  = r.json()
        daily = data.get("daily", {})
        dates = daily.get("time", [])
        tmaxs = daily.get("temperature_2m_max", [])
        tmins = daily.get("temperature_2m_min", [])

        result = []
        for d, hi, lo in zip(dates, tmaxs, tmins):
            avg = daily_avg(hi, lo)
            result.append({
                "date":   d,
                "tmax_c": round(hi, 1) if hi is not None else None,
                "tmin_c": round(lo, 1) if lo is not None else None,
                "tavg_c": round(avg, 1) if avg is not None else None,
                "hdd":    round(compute_hdd(avg), 2) if avg is not None else None,
                "cdd":    round(compute_cdd(avg), 2) if avg is not None else None,
            })
        return result
    except Exception as exc:
        log.error("Open-Meteo forecast failed (%s, %s): %s", lat, lon, exc)
        return []


def fetch_historical(lat: float, lon: float, timezone: str,
                     days_back: int = 14) -> list[dict]:
    """
    Fetch historical daily data from Open-Meteo archive endpoint.
    Returns list of {date, tmax, tmin, tavg, hdd, cdd} — past n days.
    """
    end_dt   = date.today() - timedelta(days=2)  # archive lags ~2 days
    start_dt = end_dt - timedelta(days=days_back)

    params = {
        "latitude":         lat,
        "longitude":        lon,
        "start_date":       start_dt.strftime("%Y-%m-%d"),
        "end_date":         end_dt.strftime("%Y-%m-%d"),
        "daily":            "temperature_2m_max,temperature_2m_min",
        "timezone":         timezone,
        "temperature_unit": "celsius",
    }
    try:
        r = requests.get(ARCHIVE_URL, params=params, timeout=10)
        r.raise_for_status()
        data  = r.json()
        daily = data.get("daily", {})
        dates = daily.get("time", [])
        tmaxs = daily.get("temperature_2m_max", [])
        tmins = daily.get("temperature_2m_min", [])

        result = []
        for d, hi, lo in zip(dates, tmaxs, tmins):
            avg = daily_avg(hi, lo)
            result.append({
                "date":   d,
                "tmax_c": round(hi, 1) if hi is not None else None,
                "tmin_c": round(lo, 1) if lo is not None else None,
                "tavg_c": round(avg, 1) if avg is not None else None,
                "hdd":    round(compute_hdd(avg), 2) if avg is not None else None,
                "cdd":    round(compute_cdd(avg), 2) if avg is not None else None,
            })
        return sorted(result, key=lambda x: x["date"], reverse=True)
    except Exception as exc:
        log.error("Open-Meteo archive failed (%s, %s): %s", lat, lon, exc)
        return []


# ── Aggregates ────────────────────────────────────────────────────────────────

def week_sum(records: list[dict], field: str) -> float | None:
    """Sum field over first 7 records (forecast week)."""
    vals = [r[field] for r in records[:7] if r.get(field) is not None]
    return round(sum(vals), 2) if vals else None

def week_avg(records: list[dict], field: str) -> float | None:
    vals = [r[field] for r in records[:7] if r.get(field) is not None]
    return round(sum(vals) / len(vals), 2) if vals else None

def demand_signal(hdd_week: float | None, cdd_week: float | None,
                  hdd_weight: float, cdd_weight: float) -> str:
    """
    Convert weekly HDD/CDD totals into a crude oil demand signal.

    Thresholds (per location per week):
      HDD > 30 = significant heating demand
      HDD > 50 = strong heating demand
      CDD > 25 = significant cooling demand
      CDD > 40 = strong cooling demand
    """
    heat_score = (hdd_week or 0) * hdd_weight
    cool_score = (cdd_week or 0) * cdd_weight

    total = heat_score + cool_score
    if total > 15:
        return "BULLISH"
    elif total > 7:
        return "MILD_BULLISH"
    return "NEUTRAL"

# ── Main ──────────────────────────────────────────────────────────────────────

def run() -> dict:
    log.info("Starting weather fetch — %d locations", len(LOCATIONS))

    output = {
        "fetcher":         "weather_fetcher",
        "fetched_at":      datetime.utcnow().isoformat() + "Z",
        "source":          "Open-Meteo (https://open-meteo.com) — free, no key",
        "base_temp_c":     BASE_TEMP_C,
        "hdd_note":        "HDD = max(0, 18°C - avg_daily_temp). Each HDD-day = 1°C below 18°C base.",
        "cdd_note":        "CDD = max(0, avg_daily_temp - 18°C). Each CDD-day = 1°C above 18°C base.",
        "locations":       {},
        "composite":       {},
    }

    composite_score   = 0.0
    total_hdd_weight  = sum(loc["hdd_weight"] for loc in LOCATIONS.values())
    total_cdd_weight  = sum(loc["cdd_weight"] for loc in LOCATIONS.values())
    global_hdd_7d     = 0.0
    global_cdd_7d     = 0.0
    signal_notes      = []

    for loc_key, cfg in LOCATIONS.items():
        log.info("Fetching weather: %s (%.2f, %.2f)", cfg["label"], cfg["lat"], cfg["lon"])

        forecast  = fetch_forecast(cfg["lat"], cfg["lon"], cfg["timezone"])
        history   = fetch_historical(cfg["lat"], cfg["lon"], cfg["timezone"], days_back=14)

        if not forecast:
            log.warning("  No forecast data for %s", cfg["label"])
            output["locations"][loc_key] = {"error": "no_data", "label": cfg["label"]}
            continue

        hdd_7d = week_sum(forecast, "hdd")
        cdd_7d = week_sum(forecast, "cdd")
        tavg_7d = week_avg(forecast, "tavg_c")
        signal  = demand_signal(hdd_7d, cdd_7d, cfg["hdd_weight"], cfg["cdd_weight"])

        # Vs historical 14-day avg for anomaly detection
        hist_hdd_avg = None
        hist_cdd_avg = None
        if history:
            hist_hdds = [r["hdd"] for r in history if r.get("hdd") is not None]
            hist_cdds = [r["cdd"] for r in history if r.get("cdd") is not None]
            hist_hdd_avg = round(sum(hist_hdds) / len(hist_hdds), 2) if hist_hdds else None
            hist_cdd_avg = round(sum(hist_cdds) / len(hist_cdds), 2) if hist_cdds else None

        # Anomaly: is forecast materially warmer/colder than recent history?
        anomaly = "NORMAL"
        anomaly_detail = ""
        if hist_hdd_avg is not None and hdd_7d is not None:
            daily_fcast_hdd = (hdd_7d / 7)
            if daily_fcast_hdd > hist_hdd_avg * 1.4:
                anomaly = "COLDER_THAN_RECENT"
                anomaly_detail = f"Forecast HDD/day {daily_fcast_hdd:.1f} vs recent avg {hist_hdd_avg:.1f} — significantly colder"
            elif daily_fcast_hdd < hist_hdd_avg * 0.6 and hist_hdd_avg > 2:
                anomaly = "WARMER_THAN_RECENT"
                anomaly_detail = f"Forecast HDD/day {daily_fcast_hdd:.1f} vs recent avg {hist_hdd_avg:.1f} — significantly warmer"

        output["locations"][loc_key] = {
            "label":           cfg["label"],
            "region":          cfg["region"],
            "oil_impact":      cfg["oil_impact"],
            "hdd_7d_forecast": hdd_7d,
            "cdd_7d_forecast": cdd_7d,
            "tavg_7d_c":       tavg_7d,
            "hist_hdd_avg_14d": hist_hdd_avg,
            "hist_cdd_avg_14d": hist_cdd_avg,
            "anomaly":         anomaly,
            "anomaly_detail":  anomaly_detail,
            "demand_signal":   signal,
            "forecast_7d":     forecast,
            "history_14d":     history,
        }

        log.info(
            "  %s: HDD_7d=%.1f CDD_7d=%.1f tavg=%.1f°C → %s%s",
            cfg["label"],
            hdd_7d or 0,
            cdd_7d or 0,
            tavg_7d or 0,
            signal,
            f" [{anomaly}]" if anomaly != "NORMAL" else "",
        )

        # Global weighted aggregates
        global_hdd_7d += (hdd_7d or 0) * cfg["hdd_weight"]
        global_cdd_7d += (cdd_7d or 0) * cfg["cdd_weight"]

        if signal in ("BULLISH", "MILD_BULLISH"):
            signal_notes.append(f"{cfg['label']}: {signal} (HDD={hdd_7d:.0f}, CDD={cdd_7d:.0f})")

    # ── Global composite ──────────────────────────────────────────────────────
    norm_hdd = global_hdd_7d / total_hdd_weight if total_hdd_weight else 0
    norm_cdd = global_cdd_7d / total_cdd_weight if total_cdd_weight else 0

    if norm_hdd > 30 or norm_cdd > 25:
        composite_signal = "BULLISH"
        composite_note   = f"Significant weather-driven demand: weighted HDD={norm_hdd:.1f}, CDD={norm_cdd:.1f} per week."
    elif norm_hdd > 15 or norm_cdd > 12:
        composite_signal = "MILD_BULLISH"
        composite_note   = f"Moderate weather-driven demand: weighted HDD={norm_hdd:.1f}, CDD={norm_cdd:.1f} per week."
    else:
        composite_signal = "NEUTRAL"
        composite_note   = f"Weather demand near seasonal norm: weighted HDD={norm_hdd:.1f}, CDD={norm_cdd:.1f} per week."

    output["composite"] = {
        "signal":              composite_signal,
        "weighted_hdd_7d":    round(norm_hdd, 2),
        "weighted_cdd_7d":    round(norm_cdd, 2),
        "demand_impact_note": composite_note,
        "bullish_locations":  signal_notes,
        "oil_market_context": (
            "Rule of thumb: +5 HDD/week surprise above seasonal norm in "
            "US NE + N. Europe can add ~0.1-0.2 mbd distillate demand vs IEA forecast. "
            "Dubai CDD peak in Jun-Sep can add 0.3-0.5 mbd crude/fuel oil for power."
        ),
    }

    # ── Save ──────────────────────────────────────────────────────────────────
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    log.info("Saved → %s", OUTPUT_PATH)
    log.info(
        "Weather composite: %s | HDD_wtd=%.1f CDD_wtd=%.1f",
        composite_signal, norm_hdd, norm_cdd,
    )

    return output


if __name__ == "__main__":
    run()

"""
gie_fetcher.py
--------------
Fetches European natural gas storage data from GIE AGSI+.
Free API — register at https://agsi.gie.eu to get a key (takes ~1 min).

Why it matters for oil:
  - When European gas storage is LOW → power sector switches to oil/diesel
    for generation → oil demand boost (especially heating oil / gasoil)
  - When storage is HIGH → gas-to-oil switching pressure absent → bearish
    for distillates
  - Storage fill % vs 5-year seasonal average is the key signal
  - Published daily; critical signal Oct–Mar (heating season)

Coverage:
  EU aggregate, Germany, France, Italy, Netherlands, UK

Saves to: backend/data/gie_latest.json

API docs: https://agsi.gie.eu/api-docs
Register:  https://agsi.gie.eu (free, instant)
Set env:   GIE_API_KEY=your_key
"""

import os
import json
import logging
import requests
from datetime import datetime, date, timedelta
from pathlib import Path

# ── Config ───────────────────────────────────────────────────────────────────

GIE_API_KEY = os.getenv("GIE_API_KEY", "YOUR_GIE_KEY_HERE")
BASE_URL    = "https://agsi.gie.eu/api"
OUTPUT_PATH = Path(__file__).resolve().parents[1] / "data" / "gie_latest.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Country / region registry ─────────────────────────────────────────────────
# Each entry: API country code → metadata for dashboard display

REGIONS = {
    "europe": {
        "key":          "eu_aggregate",
        "label":        "EU Aggregate",
        "weight":       1.0,    # primary signal
        "signal_note":  "EU gas storage is the primary heating oil demand signal for European winter.",
    },
    "de": {
        "key":          "germany",
        "label":        "Germany",
        "weight":       0.3,
        "signal_note":  "Germany = largest EU gas market; Rehden storage hub is key.",
    },
    "fr": {
        "key":          "france",
        "label":        "France",
        "weight":       0.2,
        "signal_note":  "France heating season peaks Dec-Feb; nuclear outages can spike gas/oil demand.",
    },
    "it": {
        "key":          "italy",
        "label":        "Italy",
        "weight":       0.2,
        "signal_note":  "Italy heavily dependent on gas; Stogit storage critical.",
    },
    "nl": {
        "key":          "netherlands",
        "label":        "Netherlands",
        "weight":       0.15,
        "signal_note":  "Netherlands (TTF hub country); Bergermeer storage tracks TTF closely.",
    },
    "gb": {
        "key":          "uk",
        "label":        "United Kingdom",
        "weight":       0.15,
        "signal_note":  "UK storage very thin vs consumption; high sensitivity to supply shocks.",
    },
}

# ── Fetch ─────────────────────────────────────────────────────────────────────

def fetch_region(country_code: str, n_days: int = 30) -> list[dict]:
    """
    Fetch n_days of storage data for a given country.
    Returns list of daily records: {date, full, trend, inject, withdraw, ...}
    """
    end_date   = date.today()
    start_date = end_date - timedelta(days=n_days + 10)  # buffer for weekends

    params = {
        "country": country_code,
        "from":    start_date.strftime("%Y-%m-%d"),
        "till":    end_date.strftime("%Y-%m-%d"),
        "size":    n_days,
        "page":    1,
    }
    headers = {
        "x-key":       GIE_API_KEY,
        "User-Agent":  "EnergyDashboard/1.0",
        "Accept":      "application/json",
    }

    try:
        r = requests.get(BASE_URL, params=params, headers=headers, timeout=12)
        r.raise_for_status()
        data = r.json()
        return data.get("data", [])
    except requests.RequestException as exc:
        log.error("GIE fetch failed for %s: %s", country_code, exc)
        return []

# ── Signal logic ──────────────────────────────────────────────────────────────

def compute_fill_signal(fill_pct: float | None, five_yr_avg: float | None) -> dict:
    """
    Determine crude oil / distillate demand signal from gas storage fill %.

    Signal logic:
      fill > 90%           → BEARISH  (storage full, no emergency demand)
      fill < 50%           → BULLISH  (low storage → heating oil demand risk)
      deviation < -5pp     → BULLISH  (below seasonal norm)
      deviation > +5pp     → BEARISH  (above seasonal norm)
      else                 → NEUTRAL
    """
    if fill_pct is None:
        return {"signal": "NEUTRAL", "note": "no data"}

    deviation = round(fill_pct - five_yr_avg, 2) if five_yr_avg is not None else None

    if fill_pct > 90:
        signal = "BEARISH"
        note   = f"Storage {fill_pct:.1f}% full — nearly at capacity. Injection season closing. No emergency oil switching demand."
    elif fill_pct < 50:
        signal = "BULLISH"
        note   = f"Storage {fill_pct:.1f}% — critically low. Heating oil / gasoil demand uplift risk for winter."
    elif deviation is not None and deviation < -5:
        signal = "BULLISH"
        note   = f"Storage {fill_pct:.1f}% — {abs(deviation):.1f}pp below 5-year average. Structural shortfall vs seasonal norm → distillate demand support."
    elif deviation is not None and deviation > 5:
        signal = "BEARISH"
        note   = f"Storage {fill_pct:.1f}% — {deviation:.1f}pp above 5-year average. Ample buffer → no oil switching demand."
    else:
        signal = "NEUTRAL"
        dev_str = f"{deviation:+.1f}pp" if deviation is not None else "5yr avg unavailable"
        note   = f"Storage {fill_pct:.1f}% — within normal seasonal range ({dev_str})."

    return {
        "signal":        signal,
        "fill_pct":      fill_pct,
        "five_yr_avg":   five_yr_avg,
        "deviation_pp":  deviation,
        "note":          note,
    }


def is_injection_season() -> bool:
    """Apr–Sep = injection season; Oct–Mar = withdrawal season."""
    return date.today().month in {4, 5, 6, 7, 8, 9}


def injection_rate_signal(inject: float | None, withdraw: float | None,
                           trend: float | None) -> str:
    """
    Classify current flow direction vs season.
    inject/withdraw in TWh/day from GIE API.
    """
    season = "injection" if is_injection_season() else "withdrawal"

    if inject is None and withdraw is None:
        return f"no flow data ({season} season)"

    net = (inject or 0) - (withdraw or 0)
    direction = "injecting" if net > 0 else "withdrawing"

    if season == "injection" and net < 0:
        return f"ALERT: withdrawing ({abs(net):.1f} TWh/d) in injection season — unusually high demand"
    elif season == "withdrawal" and net > 0:
        return f"NOTE: injecting ({net:.1f} TWh/d) in withdrawal season — very mild weather or oversupply"
    else:
        return f"{direction} {abs(net):.1f} TWh/d — normal for {season} season"

# ── Parse daily record ────────────────────────────────────────────────────────

def parse_record(rec: dict) -> dict:
    """
    Parse a single GIE daily record into clean typed fields.
    GIE API returns strings for numeric fields — handle gracefully.
    Field names vary slightly between API versions — check multiple names.
    """
    def safe_float(val):
        try:
            return float(val) if val not in (None, "", "N/A", "-") else None
        except (ValueError, TypeError):
            return None

    # fill_pct: GIE uses 'full' as a percentage (e.g. "29.83")
    fill_pct = safe_float(rec.get("full") or rec.get("fillLevel") or rec.get("fill"))

    # 5-year average: try multiple field names GIE has used across versions
    five_yr = safe_float(
        rec.get("fiveYearAverage")
        or rec.get("5yrAvg")
        or rec.get("avgFull")
        or rec.get("trend")   # some endpoints put avg in trend
    )
    # If five_yr_avg still 0.0 treat as missing
    if five_yr == 0.0:
        five_yr = None

    return {
        "date":         rec.get("gasDayStartedOn") or rec.get("date") or rec.get("gasDay"),
        "full_twh":     safe_float(rec.get("gasInStorage") or rec.get("full_twh")),
        "trend_twh":    safe_float(rec.get("trend")),
        "inject_twh":   safe_float(rec.get("injection") or rec.get("inject")),
        "withdraw_twh": safe_float(rec.get("withdrawal") or rec.get("withdraw")),
        "working_gas_volume_twh": safe_float(rec.get("workingGasVolume") or rec.get("capacity")),
        "fill_pct":     fill_pct,
        "five_yr_avg":  five_yr,
        "info":         rec.get("info") or rec.get("status", ""),
        "_raw":         rec,   # keep raw so we can debug field names if needed
    }

# ── Main ──────────────────────────────────────────────────────────────────────

def run() -> dict:
    log.info("Starting GIE AGSI+ fetch — %d regions", len(REGIONS))

    output = {
        "fetcher":       "gie_fetcher",
        "fetched_at":    datetime.utcnow().isoformat() + "Z",
        "source":        "GIE AGSI+ (https://agsi.gie.eu)",
        "season":        "injection" if is_injection_season() else "withdrawal",
        "regions":       {},
        "composite":     {},
    }

    weighted_signal_score = 0.0
    total_weight          = 0.0
    signal_reasons        = []

    for code, cfg in REGIONS.items():
        log.info("Fetching GIE: %s (%s)", cfg["label"], code)
        records = fetch_region(code, n_days=30)

        if not records:
            log.warning("  No data for %s", code)
            output["regions"][cfg["key"]] = {"error": "no_data", "label": cfg["label"]}
            continue

        # Log raw field names on first run so we can verify parsing
        log.debug("  Raw fields from GIE for %s: %s", code, list(records[0].keys()))

        # Parse most recent + history
        parsed   = [parse_record(r) for r in records]
        latest   = parsed[0]
        prev     = parsed[1] if len(parsed) > 1 else {}

        fill_pct    = latest.get("fill_pct")
        five_yr_avg = latest.get("five_yr_avg")
        inject      = latest.get("inject_twh")
        withdraw    = latest.get("withdraw_twh")
        trend       = latest.get("trend_twh")

        # WoW fill change
        wow_fill = None
        for rec in parsed[1:]:
            if rec.get("date") and latest.get("date"):
                days_back = (
                    datetime.strptime(latest["date"], "%Y-%m-%d") -
                    datetime.strptime(rec["date"], "%Y-%m-%d")
                ).days
                if days_back >= 7 and rec.get("fill_pct") is not None:
                    wow_fill = round(fill_pct - rec["fill_pct"], 2) if fill_pct else None
                    break

        signal_data   = compute_fill_signal(fill_pct, five_yr_avg)
        flow_signal   = injection_rate_signal(inject, withdraw, trend)

        output["regions"][cfg["key"]] = {
            "label":        cfg["label"],
            "country_code": code,
            "signal_note":  cfg["signal_note"],
            "latest_date":  latest.get("date"),
            "fill_pct":     fill_pct,
            "five_yr_avg":  five_yr_avg,
            "deviation_pp": signal_data.get("deviation_pp"),
            "inject_twh":   inject,
            "withdraw_twh": withdraw,
            "wow_fill_pp":  wow_fill,
            "flow_signal":  flow_signal,
            "crude_signal": signal_data["signal"],
            "signal_note_detail": signal_data["note"],
            "history_30d":  parsed[:30],
        }

        log.info(
            "  %s: fill=%.1f%% | 5yr=%.1f%% | dev=%+.1f | signal=%s",
            cfg["label"],
            fill_pct or 0,
            five_yr_avg or 0,
            signal_data.get("deviation_pp") or 0,
            signal_data["signal"],
        )

        # Weighted composite
        score_map = {"BULLISH": 1, "NEUTRAL": 0, "BEARISH": -1}
        weighted_signal_score += score_map.get(signal_data["signal"], 0) * cfg["weight"]
        total_weight          += cfg["weight"]
        if signal_data["signal"] != "NEUTRAL":
            signal_reasons.append(f"{cfg['label']}: {signal_data['signal']}")

    # ── Composite ─────────────────────────────────────────────────────────────
    if total_weight > 0:
        composite_score = weighted_signal_score / total_weight
        composite_label = (
            "BULLISH" if composite_score > 0.2
            else "BEARISH" if composite_score < -0.2
            else "NEUTRAL"
        )
    else:
        composite_score = 0
        composite_label = "NEUTRAL"

    output["composite"] = {
        "score":              round(composite_score, 3),
        "signal":             composite_label,
        "crude_oil_impact":   (
            "European gas storage below seasonal norm → heating oil/gasoil demand uplift"
            if composite_label == "BULLISH"
            else "European gas storage above seasonal norm → no oil switching demand"
            if composite_label == "BEARISH"
            else "European gas storage within seasonal norms → neutral oil demand impact"
        ),
        "reasons":            signal_reasons,
        "season":             output["season"],
        "oil_market_context": (
            "Gas-to-oil switching adds ~0.3-0.8 mbd to European distillate demand "
            "in cold winters when storage is critically low (<50%). "
            "The signal is strongest Oct-Mar. In injection season (Apr-Sep), "
            "low storage is a warning for the following winter."
        ),
    }

    # ── Save ──────────────────────────────────────────────────────────────────
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    log.info("Saved → %s", OUTPUT_PATH)
    log.info(
        "GIE composite: %s (score=%.2f) | %s",
        composite_label, composite_score,
        " | ".join(signal_reasons) or "all neutral",
    )

    return output


if __name__ == "__main__":
    run()

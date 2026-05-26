"""
gie_fetcher.py
--------------
Fetches European natural gas storage data from GIE AGSI+.
Free API — register at https://agsi.gie.eu to get a key (takes ~1 min).

Why it matters for oil:
  - When European gas storage is LOW → power sector switches to oil/diesel
    for generation → oil demand boost (especially heating oil / gasoil)
  - Storage fill % vs seasonal norms is the key signal
  - Published daily; critical signal Oct–Mar (heating season)

Coverage: Germany, France, Italy, Netherlands + EU via aggregate endpoint

Saves to: backend/data/gie_latest.json

API: https://agsi.gie.eu  (register free for key)
Set env: GIE_API_KEY=your_key
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

# ── Country registry ──────────────────────────────────────────────────────────
# UK removed: left AGSI+ post-Brexit (no data)
# EU aggregate: tried separately via /api?type=EU endpoint

REGIONS = {
    "de": {
        "key":          "germany",
        "label":        "Germany",
        "weight":       0.30,
        "signal_note":  "Germany = largest EU gas market; Rehden storage hub is key.",
    },
    "fr": {
        "key":          "france",
        "label":        "France",
        "weight":       0.25,
        "signal_note":  "France heating season peaks Dec-Feb; nuclear outages can spike gas/oil demand.",
    },
    "it": {
        "key":          "italy",
        "label":        "Italy",
        "weight":       0.25,
        "signal_note":  "Italy heavily dependent on gas; Stogit storage critical.",
    },
    "nl": {
        "key":          "netherlands",
        "label":        "Netherlands",
        "weight":       0.20,
        "signal_note":  "Netherlands (TTF hub country); Bergermeer storage tracks TTF closely.",
    },
}

# ── Fetch ─────────────────────────────────────────────────────────────────────

def fetch_region(country_code: str, n_days: int = 30) -> list[dict]:
    """Fetch n_days of storage data for a country. Returns list of daily records."""
    end_date   = date.today()
    start_date = end_date - timedelta(days=n_days + 10)

    params = {
        "country": country_code,
        "from":    start_date.strftime("%Y-%m-%d"),
        "till":    end_date.strftime("%Y-%m-%d"),
        "size":    n_days,
        "page":    1,
    }
    headers = {
        "x-key":      GIE_API_KEY,
        "User-Agent": "EnergyDashboard/1.0",
        "Accept":     "application/json",
    }

    try:
        r = requests.get(BASE_URL, params=params, headers=headers, timeout=12)
        r.raise_for_status()
        data = r.json()
        return data.get("data", [])
    except requests.RequestException as exc:
        log.error("GIE fetch failed for %s: %s", country_code, exc)
        return []


def fetch_eu_aggregate() -> list[dict]:
    """
    Fetch EU aggregate storage data.
    GIE uses 'type=EU' or 'country=eu' — try both.
    """
    headers = {
        "x-key":      GIE_API_KEY,
        "User-Agent": "EnergyDashboard/1.0",
        "Accept":     "application/json",
    }
    end_date   = date.today()
    start_date = end_date - timedelta(days=40)

    for code in ["eu", "EU", "europe", "Europa"]:
        params = {
            "country": code,
            "from":    start_date.strftime("%Y-%m-%d"),
            "till":    end_date.strftime("%Y-%m-%d"),
            "size":    30,
            "page":    1,
        }
        try:
            r = requests.get(BASE_URL, params=params, headers=headers, timeout=12)
            if r.status_code == 200:
                data = r.json().get("data", [])
                if data:
                    log.info("  EU aggregate found using code: %s", code)
                    return data
        except Exception:
            continue

    return []

# ── Signal logic ──────────────────────────────────────────────────────────────

def compute_fill_signal(fill_pct: float | None, five_yr_avg: float | None) -> dict:
    """
    Derive crude oil / distillate demand signal from gas storage fill %.

    Without 5yr avg (most GIE country endpoints don't provide it),
    we use absolute fill level thresholds:
      fill < 30%  → BULLISH  (critically low — highest demand risk)
      fill < 50%  → BULLISH  (low storage)
      fill 50–80% → NEUTRAL
      fill > 80%  → BEARISH  (well stocked)
      fill > 90%  → BEARISH  (nearly full)

    If 5yr avg is available, deviation adjusts the signal.
    """
    if fill_pct is None:
        return {"signal": "NEUTRAL", "note": "no data"}

    deviation = round(fill_pct - five_yr_avg, 2) if five_yr_avg is not None else None

    # Priority: deviation from avg if available, else absolute level
    if five_yr_avg is not None and deviation is not None:
        if fill_pct < 50 or deviation < -5:
            signal = "BULLISH"
            note   = f"Fill {fill_pct:.1f}% — {abs(deviation):.1f}pp below 5yr avg ({five_yr_avg:.1f}%). Distillate demand support."
        elif fill_pct > 80 or deviation > 5:
            signal = "BEARISH"
            note   = f"Fill {fill_pct:.1f}% — {deviation:.1f}pp above 5yr avg ({five_yr_avg:.1f}%). No oil switching demand."
        else:
            dev_str = f"{deviation:+.1f}pp vs 5yr avg"
            signal = "NEUTRAL"
            note   = f"Fill {fill_pct:.1f}% — within normal range ({dev_str})."
    else:
        # No 5yr avg available — use absolute thresholds
        if fill_pct < 30:
            signal = "BULLISH"
            note   = f"Fill {fill_pct:.1f}% — critically low. High heating oil / gasoil demand risk."
        elif fill_pct < 50:
            signal = "BULLISH"
            note   = f"Fill {fill_pct:.1f}% — below 50%. Elevated distillate demand risk for winter."
        elif fill_pct > 90:
            signal = "BEARISH"
            note   = f"Fill {fill_pct:.1f}% — nearly full. No emergency oil switching demand."
        elif fill_pct > 80:
            signal = "BEARISH"
            note   = f"Fill {fill_pct:.1f}% — well stocked. Gas-to-oil switching pressure absent."
        else:
            signal = "NEUTRAL"
            note   = f"Fill {fill_pct:.1f}% — mid-range (50–80%). Neutral oil demand impact."

    return {
        "signal":       signal,
        "fill_pct":     fill_pct,
        "five_yr_avg":  five_yr_avg,
        "deviation_pp": deviation,
        "note":         note,
    }


def is_injection_season() -> bool:
    """Apr–Sep = injection; Oct–Mar = withdrawal."""
    return date.today().month in {4, 5, 6, 7, 8, 9}


def flow_direction(inject, withdraw) -> str:
    """Return human-readable flow description."""
    if inject is None and withdraw is None:
        return "flow data unavailable"
    net = (inject or 0) - (withdraw or 0)
    season = "injection" if is_injection_season() else "withdrawal"
    direction = "injecting" if net > 0 else "withdrawing"
    rate = abs(net)
    if is_injection_season() and net < 0:
        return f"ALERT: withdrawing {rate:.1f} TWh/d in injection season"
    return f"{direction} {rate:.1f} TWh/d ({season} season)"

# ── Parse daily record ────────────────────────────────────────────────────────

def parse_record(rec: dict) -> dict:
    """
    Parse a GIE daily record into clean typed fields.

    GIE AGSI+ API fields (confirmed):
      full       → fill percentage (e.g. "29.83")
      trend      → PREVIOUS DAY fill % (NOT 5-year avg — misleading name)
      injection  → TWh injected that day
      withdrawal → TWh withdrawn that day
      gasInStorage → absolute volume in storage (TWh)
      gasDayStartedOn → date string
      fiveYearAverage → only present in some aggregate endpoints
    """
    def safe_float(val):
        try:
            v = float(val) if val not in (None, "", "N/A", "-", "n/a") else None
            return None if v == 0.0 and val != 0 else v
        except (ValueError, TypeError):
            return None

    fill_pct = safe_float(rec.get("full") or rec.get("fillLevel") or rec.get("fill"))

    # 5yr avg: only provided in some GIE endpoints, not country-level
    five_yr = safe_float(rec.get("fiveYearAverage") or rec.get("5yrAvg"))
    if five_yr is not None and five_yr < 5:
        five_yr = None  # reject values that are clearly wrong (< 5% is not a valid 5yr avg)

    return {
        "date":          rec.get("gasDayStartedOn") or rec.get("date") or rec.get("gasDay"),
        "fill_pct":      fill_pct,
        "prev_fill_pct": safe_float(rec.get("trend")),   # GIE 'trend' = prev day fill
        "inject_twh":    safe_float(rec.get("injection") or rec.get("inject")),
        "withdraw_twh":  safe_float(rec.get("withdrawal") or rec.get("withdraw")),
        "gas_in_storage_twh": safe_float(rec.get("gasInStorage")),
        "five_yr_avg":   five_yr,
        "info":          rec.get("info") or rec.get("status", ""),
    }

# ── Main ──────────────────────────────────────────────────────────────────────

def run() -> dict:
    log.info("Starting GIE AGSI+ fetch — %d country regions + EU aggregate", len(REGIONS))

    output = {
        "fetcher":    "gie_fetcher",
        "fetched_at": datetime.now(datetime.timezone.utc if hasattr(datetime, 'timezone') else None).isoformat() + "Z"
                      if False else datetime.utcnow().isoformat() + "Z",
        "source":     "GIE AGSI+ (https://agsi.gie.eu)",
        "season":     "injection" if is_injection_season() else "withdrawal",
        "note":       "5yr average not provided by GIE country endpoints; using absolute fill thresholds.",
        "regions":    {},
        "composite":  {},
    }

    # Fix for deprecation warning
    output["fetched_at"] = datetime.utcnow().isoformat() + "Z"

    weighted_score = 0.0
    total_weight   = 0.0
    signal_reasons = []

    # ── EU Aggregate (try first) ──────────────────────────────────────────────
    log.info("Fetching GIE: EU Aggregate")
    eu_records = fetch_eu_aggregate()
    if eu_records:
        parsed   = [parse_record(r) for r in eu_records]
        latest   = parsed[0]
        fill_pct = latest.get("fill_pct")
        five_yr  = latest.get("five_yr_avg")
        sig      = compute_fill_signal(fill_pct, five_yr)
        inject   = latest.get("inject_twh")
        withdraw = latest.get("withdraw_twh")

        output["regions"]["eu_aggregate"] = {
            "label":         "EU Aggregate",
            "latest_date":   latest.get("date"),
            "fill_pct":      fill_pct,
            "five_yr_avg":   five_yr,
            "deviation_pp":  sig.get("deviation_pp"),
            "inject_twh":    inject,
            "withdraw_twh":  withdraw,
            "flow_direction": flow_direction(inject, withdraw),
            "crude_signal":  sig["signal"],
            "signal_detail": sig["note"],
            "history_30d":   parsed[:30],
        }
        log.info("  EU Aggregate: fill=%.1f%% | signal=%s", fill_pct or 0, sig["signal"])
        weighted_score += {"BULLISH": 1, "NEUTRAL": 0, "BEARISH": -1}.get(sig["signal"], 0) * 0.40
        total_weight   += 0.40
        if sig["signal"] != "NEUTRAL":
            signal_reasons.append(f"EU: {sig['signal']} ({fill_pct:.1f}%)")
    else:
        log.warning("  EU aggregate: no data returned (may need valid GIE API key)")
        output["regions"]["eu_aggregate"] = {"error": "no_data", "label": "EU Aggregate"}

    # ── Country regions ───────────────────────────────────────────────────────
    for code, cfg in REGIONS.items():
        log.info("Fetching GIE: %s (%s)", cfg["label"], code)
        records = fetch_region(code, n_days=30)

        if not records:
            log.warning("  No data for %s", code)
            output["regions"][cfg["key"]] = {"error": "no_data", "label": cfg["label"]}
            continue

        parsed   = [parse_record(r) for r in records]
        latest   = parsed[0]

        # Debug: log actual field names returned by GIE on first country
        if code == "de":
            log.info("  GIE raw fields for DE: %s", list(records[0].keys()))

        fill_pct = latest.get("fill_pct")
        five_yr  = latest.get("five_yr_avg")
        inject   = latest.get("inject_twh")
        withdraw = latest.get("withdraw_twh")

        # WoW fill change
        wow_fill = None
        for rec in parsed[1:]:
            if rec.get("date") and latest.get("date"):
                try:
                    days_back = (
                        datetime.strptime(latest["date"], "%Y-%m-%d") -
                        datetime.strptime(rec["date"], "%Y-%m-%d")
                    ).days
                    if days_back >= 7 and rec.get("fill_pct") is not None and fill_pct is not None:
                        wow_fill = round(fill_pct - rec["fill_pct"], 2)
                        break
                except ValueError:
                    continue

        sig = compute_fill_signal(fill_pct, five_yr)

        output["regions"][cfg["key"]] = {
            "label":         cfg["label"],
            "country_code":  code,
            "signal_note":   cfg["signal_note"],
            "latest_date":   latest.get("date"),
            "fill_pct":      fill_pct,
            "five_yr_avg":   five_yr,
            "deviation_pp":  sig.get("deviation_pp"),
            "inject_twh":    inject,
            "withdraw_twh":  withdraw,
            "wow_fill_pp":   wow_fill,
            "flow_direction": flow_direction(inject, withdraw),
            "crude_signal":  sig["signal"],
            "signal_detail": sig["note"],
            "history_30d":   parsed[:30],
        }

        log.info(
            "  %s: fill=%.1f%% | 5yr=%s | signal=%s",
            cfg["label"],
            fill_pct or 0,
            f"{five_yr:.1f}%" if five_yr else "N/A",
            sig["signal"],
        )

        score_map = {"BULLISH": 1, "NEUTRAL": 0, "BEARISH": -1}
        weighted_score += score_map.get(sig["signal"], 0) * cfg["weight"]
        total_weight   += cfg["weight"]
        if sig["signal"] != "NEUTRAL":
            signal_reasons.append(f"{cfg['label']}: {sig['signal']} ({fill_pct:.1f}%)")

    # ── Composite ─────────────────────────────────────────────────────────────
    if total_weight > 0:
        norm_score = weighted_score / total_weight
        composite  = "BULLISH" if norm_score > 0.2 else "BEARISH" if norm_score < -0.2 else "NEUTRAL"
    else:
        norm_score = 0
        composite  = "NEUTRAL"

    output["composite"] = {
        "signal":             composite,
        "score":              round(norm_score, 3),
        "reasons":            signal_reasons,
        "season":             output["season"],
        "crude_oil_impact":   (
            "Low EU gas storage → heating oil/gasoil demand uplift (especially Oct–Mar)"
            if composite == "BULLISH"
            else "Ample EU gas storage → no oil switching demand"
            if composite == "BEARISH"
            else "EU gas storage neutral → no strong oil demand signal"
        ),
        "oil_market_context": (
            "Gas-to-oil switching adds ~0.3–0.8 mbd to European distillate demand "
            "when storage is critically low (<30%). Signal strongest Oct–Mar."
        ),
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    log.info("Saved → %s", OUTPUT_PATH)
    log.info("GIE composite: %s (score=%.2f) | %s",
             composite, norm_score, " | ".join(signal_reasons) or "all neutral")

    return output


if __name__ == "__main__":
    run()

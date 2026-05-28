"""
inventory_signals.py
--------------------
Day 4 — Inventory Signal Engine

AUTO-REFRESH: Running this file automatically re-fetches all live data
from every source before computing signals. One command does everything.

Fetchers run in order:
  1. eia_fetcher.py       → crude stocks, production, refinery util
  2. fred_fetcher.py      → DXY, SOFR, rates (storage carry cost)
  3. futures_fetcher.py   → Brent, WTI, crack spreads
  4. gie_fetcher.py       → EU gas storage
  5. weather_fetcher.py   → HDD/CDD demand signals
  6. cftc_fetcher.py      → speculative positioning

Then computes:
  - Days of forward demand cover
  - 5-year seasonal deviation
  - WoW surprise vs consensus
  - Cushing tightness score
  - Distillate winter risk
  - Composite NCI Inventory Score (-10 to +10)

Saves to: backend/data/inventory_signals.json

Usage:
  python backend/inventory_signals.py            # refresh all + compute
  python backend/inventory_signals.py --no-fetch # skip fetch, use cached data
"""

import argparse
import importlib.util
import json
import logging
import sys
import time
from datetime import datetime, date
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────

ROOT        = Path(__file__).resolve().parent          # backend/
DATA_DIR    = ROOT / "data"
FETCHER_DIR = ROOT / "fetchers"
EIA_PATH    = DATA_DIR / "eia_latest.json"
OUTPUT_PATH = DATA_DIR / "inventory_signals.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Fetcher run order ─────────────────────────────────────────────────────────
# Each entry: (fetcher_id, module_name, why_needed)

FETCHERS_TO_RUN = [
    ("eia",     "eia_fetcher",     "crude/gasoline/distillate stocks, production, refinery util"),
    ("fred",    "fred_fetcher",    "DXY, SOFR, rates → storage carry cost model"),
    ("futures", "futures_fetcher", "Brent, WTI, crack spreads, Brent-WTI spread"),
    ("gie",     "gie_fetcher",     "EU gas storage → distillate demand signal"),
    ("weather", "weather_fetcher", "HDD/CDD → heating/cooling demand"),
    ("cftc",    "cftc_fetcher",    "speculative positioning → crowding risk"),
]

# ── 5-Year Seasonal Averages ──────────────────────────────────────────────────
# Source: EIA historical data (2020-2024 avg) by (month, half-month)

CUSHING_5YR_AVG = {
    (1,1):26.5,(1,2):27.0,(2,1):28.5,(2,2):30.0,(3,1):32.0,(3,2):33.5,
    (4,1):34.5,(4,2):35.0,(5,1):33.5,(5,2):32.0,(6,1):29.5,(6,2):28.0,
    (7,1):27.0,(7,2):27.5,(8,1):28.0,(8,2):27.5,(9,1):27.0,(9,2):26.5,
    (10,1):26.5,(10,2):27.0,(11,1):28.5,(11,2):29.5,(12,1):30.5,(12,2):28.0,
}

TOTAL_CRUDE_5YR_AVG = {
    (1,1):430,(1,2):432,(2,1):435,(2,2):436,(3,1):438,(3,2):440,
    (4,1):442,(4,2):441,(5,1):438,(5,2):434,(6,1):430,(6,2):428,
    (7,1):426,(7,2):427,(8,1):428,(8,2):427,(9,1):425,(9,2):424,
    (10,1):426,(10,2):428,(11,1):432,(11,2):434,(12,1):432,(12,2):428,
}

GASOLINE_5YR_AVG = {
    (1,1):240,(1,2):242,(2,1):244,(2,2):243,(3,1):240,(3,2):237,
    (4,1):234,(4,2):232,(5,1):230,(5,2):228,(6,1):226,(6,2):225,
    (7,1):224,(7,2):225,(8,1):226,(8,2):225,(9,1):224,(9,2):222,
    (10,1):220,(10,2):219,(11,1):220,(11,2):222,(12,1):232,(12,2):238,
}

DISTILLATE_5YR_AVG = {
    (1,1):128,(1,2):126,(2,1):122,(2,2):120,(3,1):119,(3,2):120,
    (4,1):122,(4,2):124,(5,1):125,(5,2):126,(6,1):128,(6,2):130,
    (7,1):132,(7,2):134,(8,1):134,(8,2):133,(9,1):130,(9,2):127,
    (10,1):122,(10,2):118,(11,1):114,(11,2):113,(12,1):116,(12,2):120,
}

US_DEMAND_5YR_AVG_MBD = {
    1:19.8,2:19.6,3:20.0,4:20.2,5:20.5,6:21.0,
    7:21.2,8:21.0,9:20.5,10:20.2,11:20.0,12:20.3,
}

CUSHING_CAPACITY_MMBBLS = 76.0

DEFAULT_CONSENSUS = {
    "crude_wow_expected":     -1.0,
    "gasoline_wow_expected":   0.5,
    "distillate_wow_expected": 0.3,
    "cushing_wow_expected":   -0.5,
}

# ── Auto-refresh: run all fetchers ────────────────────────────────────────────

def load_module(module_name: str):
    """Dynamically load a fetcher module from the fetchers/ directory."""
    path = FETCHER_DIR / f"{module_name}.py"
    if not path.exists():
        return None
    spec   = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def refresh_all_sources() -> dict[str, str]:
    """
    Run every fetcher in order. Returns {fetcher_id: 'ok'/'failed'/'missing'}.
    Each fetcher writes its own JSON to backend/data/.
    """
    log.info("=" * 60)
    log.info("AUTO-REFRESH — fetching live data from all sources")
    log.info("=" * 60)

    results = {}

    for fid, module_name, reason in FETCHERS_TO_RUN:
        log.info("▶  %s  (%s)", module_name, reason)
        t0     = time.time()
        module = load_module(module_name)

        if module is None:
            log.warning("   ⚠  Not found: %s — skipping", module_name)
            results[fid] = "missing"
            continue

        if not hasattr(module, "run"):
            log.error("   ✗  No run() in %s — skipping", module_name)
            results[fid] = "missing"
            continue

        try:
            module.run()
            elapsed       = time.time() - t0
            results[fid]  = "ok"
            log.info("   ✓  Done in %.1fs", elapsed)
        except Exception as exc:
            log.error("   ✗  Failed: %s", exc)
            results[fid] = "failed"

        time.sleep(0.5)   # brief pause between fetchers

    ok      = sum(1 for v in results.values() if v == "ok")
    failed  = sum(1 for v in results.values() if v == "failed")
    missing = sum(1 for v in results.values() if v == "missing")

    log.info("=" * 60)
    log.info("Refresh complete: %d ok  %d failed  %d missing", ok, failed, missing)
    log.info("=" * 60)

    return results

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_season_key(dt: date = None) -> tuple:
    if dt is None:
        dt = date.today()
    return (dt.month, 1 if dt.day <= 15 else 2)


def safe(data: dict, *keys, default=None):
    val = data
    for k in keys:
        val = val.get(k, default) if isinstance(val, dict) else default
    return val


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception as e:
        log.warning("Could not load %s: %s", path.name, e)
        return {}

# ── Scoring functions ─────────────────────────────────────────────────────────

def score_days_cover(days):
    if days is None: return 0
    if days < 45:    return 5
    elif days < 50:  return 3
    elif days < 54:  return 1
    elif days < 58:  return 0
    elif days < 62:  return -1
    elif days < 66:  return -3
    else:            return -5

def score_5yr_deviation(current, avg):
    if current is None or avg is None or avg == 0: return 0
    dev = (current - avg) / avg * 100
    if dev < -10:   return 5
    elif dev < -5:  return 3
    elif dev < -2:  return 1
    elif dev < 2:   return 0
    elif dev < 5:   return -1
    elif dev < 10:  return -3
    else:           return -5

def score_cushing(cushing, five_yr, capacity=CUSHING_CAPACITY_MMBBLS):
    if cushing is None: return 0
    util = cushing / capacity * 100
    if util > 85:   return -5
    dev  = (cushing - five_yr) if five_yr else 0
    bonus = 1 if util < 30 else 0
    if dev < -8:    base = 5
    elif dev < -4:  base = 3
    elif dev < -1:  base = 1
    elif dev < 1:   base = 0
    elif dev < 4:   base = -1
    elif dev < 8:   base = -3
    else:           base = -5
    return max(-5, min(5, base + bonus))

def score_wow_surprise(actual, consensus=-1.0):
    if actual is None: return 0
    surprise = consensus - actual
    if surprise > 4:     return 3
    elif surprise > 2:   return 2
    elif surprise > 0.5: return 1
    elif surprise > -0.5:return 0
    elif surprise > -2:  return -1
    elif surprise > -4:  return -2
    else:                return -3

def score_distillate_risk(distillate, five_yr):
    if distillate is None or five_yr is None: return 0
    dev   = (distillate - five_yr) / five_yr * 100
    mult  = 1.5 if date.today().month in {10,11,12,1,2,3} else 1.0
    if dev < -10:   base = 5
    elif dev < -5:  base = 3
    elif dev < -2:  base = 1
    elif dev < 2:   base = 0
    elif dev < 5:   base = -1
    elif dev < 10:  base = -3
    else:           base = -5
    return max(-5, min(5, int(base * mult)))

def score_refinery_util(util):
    if util is None: return 0
    if util > 95:    return 2
    elif util > 91:  return 1
    elif util > 87:  return 0
    elif util > 83:  return -1
    elif util > 78:  return -2
    else:            return -3

def compute_days_cover(total_crude, gasoline, distillate, demand_mbd):
    if None in (total_crude, gasoline, distillate, demand_mbd) or demand_mbd == 0:
        return None
    return round((total_crude + gasoline + distillate + 160.0) / demand_mbd, 1)

def compute_trend(series, value_key, n_weeks=4):
    if not series or len(series) < 2:
        return {"direction": "UNKNOWN", "slope_per_week": None, "consistent": False}
    vals = [float(o[value_key]) for o in series[:n_weeks] if o.get(value_key) is not None]
    if len(vals) < 2:
        return {"direction": "UNKNOWN", "slope_per_week": None, "consistent": False}
    slope = (vals[0] - vals[-1]) / (len(vals) - 1)
    diffs = [vals[i] - vals[i+1] for i in range(len(vals)-1)]
    return {
        "direction":      "DRAWING" if slope < 0 else "BUILDING",
        "slope_per_week": round(slope, 3),
        "consistent":     all(d < 0 for d in diffs) or all(d > 0 for d in diffs),
        "n_weeks":        len(vals),
    }

# ── Main ──────────────────────────────────────────────────────────────────────

def compute_signals(fetch_results: dict = None) -> dict:
    """Compute inventory signals from cached JSON files."""

    eia   = load_json(EIA_PATH)
    sigs  = eia  # EIA fetcher writes data at top level, no "signals" wrapper
    sk    = get_season_key()
    month = date.today().month

    # Raw values from EIA
    cushing        = safe(sigs, "cushing_stocks",    "value_mmbbls")
    total_crude    = safe(sigs, "total_crude_stocks","value_mmbbls")
    gasoline       = safe(sigs, "gasoline_stocks",   "value_mmbbls")
    distillate     = safe(sigs, "distillate_stocks", "value_mmbbls")
    refinery_util  = safe(sigs, "refinery_util",     "value")
    gasoline_dem   = safe(sigs, "gasoline_demand",   "value_mbd")
    distillate_dem = safe(sigs, "distillate_demand", "value_mbd")
    crude_imports  = safe(sigs, "crude_imports",     "value_mbd")
    crude_exports  = safe(sigs, "crude_exports",     "value_mbd")
    crude_prod     = safe(sigs, "crude_production",  "value_mbd")
    cushing_wow    = safe(sigs, "cushing_stocks",    "wow_change")
    crude_wow      = safe(sigs, "total_crude_stocks","wow_change")
    gasoline_wow   = safe(sigs, "gasoline_stocks",   "wow_change")
    distillate_wow = safe(sigs, "distillate_stocks", "wow_change")

    # 5yr averages
    cushing_5yr    = CUSHING_5YR_AVG.get(sk)
    crude_5yr      = TOTAL_CRUDE_5YR_AVG.get(sk)
    gasoline_5yr   = GASOLINE_5YR_AVG.get(sk)
    distillate_5yr = DISTILLATE_5YR_AVG.get(sk)
    demand_5yr     = US_DEMAND_5YR_AVG_MBD.get(month, 20.2)

    implied_demand = round(gasoline_dem + distillate_dem + 8.8, 2) if (gasoline_dem and distillate_dem) else None
    demand_for_cover = implied_demand or demand_5yr

    days_cover     = compute_days_cover(total_crude, gasoline, distillate, demand_for_cover)
    days_cover_5yr = compute_days_cover(crude_5yr, gasoline_5yr, distillate_5yr, demand_5yr)

    def dev(c, a):
        return round(c - a, 2) if (c and a) else None
    def dev_pct(c, a):
        return round((c - a) / a * 100, 2) if (c and a and a != 0) else None

    # Trends
    cushing_trend    = compute_trend(safe(sigs,"cushing_stocks","series") or [],    "value_mmbbls")
    crude_trend      = compute_trend(safe(sigs,"total_crude_stocks","series") or [], "value_mmbbls")
    gasoline_trend   = compute_trend(safe(sigs,"gasoline_stocks","series") or [],   "value_mmbbls")
    distillate_trend = compute_trend(safe(sigs,"distillate_stocks","series") or [],  "value_mmbbls")

    # Scores
    s_days_cover   = score_days_cover(days_cover)
    s_crude_5yr    = score_5yr_deviation(total_crude, crude_5yr)
    s_gasoline_5yr = score_5yr_deviation(gasoline, gasoline_5yr)
    s_dist_5yr     = score_5yr_deviation(distillate, distillate_5yr)
    s_cushing      = score_cushing(cushing, cushing_5yr)
    s_crude_wow    = score_wow_surprise(crude_wow, DEFAULT_CONSENSUS["crude_wow_expected"])
    s_dist_risk    = score_distillate_risk(distillate, distillate_5yr)
    s_refutil      = score_refinery_util(refinery_util)

    log.info("─" * 60)
    log.info("INVENTORY SIGNAL SCORES")
    log.info("─" * 60)
    log.info("  Days of cover:       %+d  (%.1f days vs 5yr %.1f)",  s_days_cover,   days_cover or 0, days_cover_5yr or 0)
    log.info("  Total crude vs 5yr:  %+d  (%.1f vs 5yr %.1f mmbbls)",s_crude_5yr,    total_crude or 0, crude_5yr or 0)
    log.info("  Gasoline vs 5yr:     %+d  (%.1f vs 5yr %.1f mmbbls)",s_gasoline_5yr, gasoline or 0, gasoline_5yr or 0)
    log.info("  Distillate vs 5yr:   %+d  (%.1f vs 5yr %.1f mmbbls)",s_dist_5yr,     distillate or 0, distillate_5yr or 0)
    log.info("  Cushing score:       %+d  (%.1f vs 5yr %.1f mmbbls)",s_cushing,      cushing or 0, cushing_5yr or 0)
    log.info("  WoW surprise:        %+d  (actual=%.1f vs exp=%.1f)", s_crude_wow,    crude_wow or 0, DEFAULT_CONSENSUS["crude_wow_expected"])
    log.info("  Distillate risk:     %+d", s_dist_risk)
    log.info("  Refinery util:       %+d  (%.1f%%)", s_refutil, refinery_util or 0)

    raw_score = (
        s_days_cover   * 2.0 +
        s_cushing      * 2.0 +
        s_crude_5yr    * 1.5 +
        s_crude_wow    * 1.5 +
        s_dist_risk    * 1.0 +
        s_gasoline_5yr * 0.5 +
        s_dist_5yr     * 0.5 +
        s_refutil      * 0.5
    )
    max_possible = 2.0*5 + 2.0*5 + 1.5*5 + 1.5*3 + 1.0*5 + 0.5*5 + 0.5*5 + 0.5*2
    nci_score    = round(max(-10, min(10, raw_score / max_possible * 10)), 2)

    label = (
        "CRITICALLY_TIGHT" if nci_score >= 8  else
        "TIGHT"            if nci_score >= 5  else
        "MILD_TIGHT"       if nci_score >= 2  else
        "BALANCED"         if nci_score >= -1 else
        "MILD_LOOSE"       if nci_score >= -4 else
        "LOOSE"            if nci_score >= -7 else
        "CRITICALLY_LOOSE"
    )
    crude_direction = "BULLISH" if nci_score >= 2 else "BEARISH" if nci_score <= -2 else "NEUTRAL"

    output = {
        "engine":        "inventory_signals",
        "computed_at":   datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "eia_source":    eia.get("fetched_at", "unknown"),
        "fetch_results": fetch_results or {},
        "season_key":    f"month={sk[0]} half={sk[1]}",
        "stocks": {
            "cushing_mmbbls":          cushing,
            "total_crude_mmbbls":      total_crude,
            "gasoline_mmbbls":         gasoline,
            "distillate_mmbbls":       distillate,
            "cushing_capacity_mmbbls": CUSHING_CAPACITY_MMBBLS,
            "cushing_util_pct":        round(cushing / CUSHING_CAPACITY_MMBBLS * 100, 1) if cushing else None,
        },
        "vs_5yr": {
            "cushing":     {"current": cushing,     "five_yr_avg": cushing_5yr,    "deviation_mmbbls": dev(cushing, cushing_5yr),       "deviation_pct": dev_pct(cushing, cushing_5yr)},
            "total_crude": {"current": total_crude, "five_yr_avg": crude_5yr,      "deviation_mmbbls": dev(total_crude, crude_5yr),     "deviation_pct": dev_pct(total_crude, crude_5yr)},
            "gasoline":    {"current": gasoline,    "five_yr_avg": gasoline_5yr,   "deviation_mmbbls": dev(gasoline, gasoline_5yr),     "deviation_pct": dev_pct(gasoline, gasoline_5yr)},
            "distillate":  {"current": distillate,  "five_yr_avg": distillate_5yr, "deviation_mmbbls": dev(distillate, distillate_5yr), "deviation_pct": dev_pct(distillate, distillate_5yr)},
        },
        "days_cover": {
            "current":        days_cover,
            "five_yr_avg":    days_cover_5yr,
            "deviation_days": round(days_cover - days_cover_5yr, 1) if (days_cover and days_cover_5yr) else None,
            "implied_demand_mbd": demand_for_cover,
            "critical_threshold": 54,
        },
        "wow_changes": {
            "cushing":     {"actual": cushing_wow,    "consensus": DEFAULT_CONSENSUS["cushing_wow_expected"],    "surprise": round(DEFAULT_CONSENSUS["cushing_wow_expected"]    - (cushing_wow or 0), 2)},
            "total_crude": {"actual": crude_wow,      "consensus": DEFAULT_CONSENSUS["crude_wow_expected"],      "surprise": round(DEFAULT_CONSENSUS["crude_wow_expected"]      - (crude_wow or 0), 2)},
            "gasoline":    {"actual": gasoline_wow,   "consensus": DEFAULT_CONSENSUS["gasoline_wow_expected"],   "surprise": round(DEFAULT_CONSENSUS["gasoline_wow_expected"]   - (gasoline_wow or 0), 2)},
            "distillate":  {"actual": distillate_wow, "consensus": DEFAULT_CONSENSUS["distillate_wow_expected"], "surprise": round(DEFAULT_CONSENSUS["distillate_wow_expected"] - (distillate_wow or 0), 2)},
        },
        "trends": {
            "cushing":     cushing_trend,
            "total_crude": crude_trend,
            "gasoline":    gasoline_trend,
            "distillate":  distillate_trend,
        },
        "production_flows": {
            "crude_production_mbd":  crude_prod,
            "refinery_util_pct":     refinery_util,
            "crude_imports_mbd":     crude_imports,
            "crude_exports_mbd":     crude_exports,
            "net_imports_mbd":       round((crude_imports or 0) - (crude_exports or 0), 2),
            "implied_demand_mbd":    implied_demand,
            "gasoline_demand_mbd":   gasoline_dem,
            "distillate_demand_mbd": distillate_dem,
        },
        "component_scores": {
            "days_cover_score":     s_days_cover,
            "cushing_score":        s_cushing,
            "crude_5yr_score":      s_crude_5yr,
            "wow_surprise_score":   s_crude_wow,
            "distillate_risk":      s_dist_risk,
            "gasoline_5yr_score":   s_gasoline_5yr,
            "distillate_5yr_score": s_dist_5yr,
            "refinery_util_score":  s_refutil,
            "raw_weighted_sum":     round(raw_score, 2),
        },
        "nci_inventory": {
            "score":           nci_score,
            "label":           label,
            "crude_direction": crude_direction,
            "scale":           "-10 (critically loose) to +10 (critically tight)",
            "interpretation":  f"NCI {nci_score:+.1f} ({label}): " + {
                "CRITICALLY_TIGHT":  "Extreme inventory deficit. $5-15/bbl risk premium expected.",
                "TIGHT":             "Below seasonal norms. Supportive of higher prices.",
                "MILD_TIGHT":        "Slightly below seasonal norms. Mild bullish bias.",
                "BALANCED":          "Near seasonal average. Macro/geo drives price.",
                "MILD_LOOSE":        "Slightly above seasonal norms. Mild bearish bias.",
                "LOOSE":             "Above seasonal norms. Bearish. OPEC+ cut risk elevated.",
                "CRITICALLY_LOOSE":  "Severe surplus. Strong downward price pressure.",
            }.get(label, ""),
        },
        "seasonal_context": {
            "month":                date.today().month,
            "is_injection_season":  date.today().month in {4,5,6,7,8,9},
            "is_winter":            date.today().month in {10,11,12,1,2,3},
            "distillate_risk_elevated": date.today().month in {10,11,12,1,2,3},
        },
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    log.info("─" * 60)
    log.info("NCI INVENTORY SCORE:  %+.1f / 10  [%s]", nci_score, label)
    log.info("Crude direction:      %s", crude_direction)
    log.info("Days of cover:        %.1f days  (5yr: %.1f  |  critical: 54)",
             days_cover or 0, days_cover_5yr or 0)
    log.info("Cushing:              %.1f mmbbls  (%.1f%% capacity  |  %s vs 5yr)",
             cushing or 0,
             (cushing / CUSHING_CAPACITY_MMBBLS * 100) if cushing else 0,
             f"{dev(cushing, cushing_5yr):+.1f}" if cushing else "N/A")
    log.info("Saved → %s", OUTPUT_PATH)
    log.info("─" * 60)

    return output


def run(skip_fetch: bool = False) -> dict:
    fetch_results = {}

    if skip_fetch:
        log.info("Skipping fetch — using cached data")
    else:
        fetch_results = refresh_all_sources()

    return compute_signals(fetch_results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inventory Signal Engine")
    parser.add_argument("--no-fetch", action="store_true",
                        help="Skip data refresh and use cached JSON files")
    args = parser.parse_args()
    run(skip_fetch=args.no_fetch)

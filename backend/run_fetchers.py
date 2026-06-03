"""
run_fetchers.py
---------------
Master orchestrator — runs all fetchers in sequence and writes a merged
signals file used by the FastAPI backend.

Usage:
  python backend/run_fetchers.py                    # run all
  python backend/run_fetchers.py --fetcher eia      # run one
  python backend/run_fetchers.py --dry-run          # show plan, no fetch
"""

import argparse
import importlib.util
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT        = Path(__file__).resolve().parent
DATA_DIR    = ROOT / "data"
FETCHER_DIR = ROOT / "fetchers"
MERGED_OUT  = DATA_DIR / "signals_merged.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("orchestrator")

FETCHER_REGISTRY = [
    {"id": "eia",       "module": "eia_fetcher",           "output": "eia_latest.json",       "label": "EIA Weekly Petroleum (inventory + production)",         "priority": 1},
    {"id": "fred",      "module": "fred_fetcher",          "output": "fred_latest.json",      "label": "FRED Macro Indicators (DXY, SOFR, FEDFUNDS, DGS10)",    "priority": 2},
    {"id": "futures",   "module": "futures_fetcher",       "output": "futures_latest.json",   "label": "Energy Futures Prices (Brent, WTI, RBOB, HO, NG)",      "priority": 3},
    {"id": "gie",       "module": "gie_fetcher",           "output": "gie_latest.json",       "label": "GIE AGSI+ European Gas Storage",                        "priority": 4},
    {"id": "weather",   "module": "weather_fetcher",       "output": "weather_latest.json",   "label": "Open-Meteo HDD/CDD Demand Signals",                     "priority": 5},
    {"id": "cftc",      "module": "cftc_fetcher",          "output": "cftc_latest.json",      "label": "CFTC Commitments of Traders (speculative positioning)",  "priority": 6},
    {"id": "sentiment", "module": "news_fetcher",          "output": "sentiment_latest.json", "label": "News Sentiment + Geopolitical Risk Scorer",              "priority": 7},
    {"id": "rig_count", "module": "baker_hughes_fetcher",  "output": "rig_count_latest.json", "label": "Baker Hughes Rig Count (US shale leading indicator)",    "priority": 8},
    {"id": "bdi",       "module": "bdi_fetcher",           "output": "bdi_latest.json",       "label": "Baltic Dry Index (global trade / bunker demand proxy)",  "priority": 9},
    {"id": "financialjuice", "module":   "financialjuice_fetcher", "output": "financialjuice_latest.json", "label": "FinancialJuice Headlines (Apify)",         "priority": 10},
    {
    "id":       "quality_spreads",
    "module":   "quality_spreads_fetcher",
    "output":   "quality_spreads_latest.json",
    "label":    "Quality Spreads (Brent-Maya, LLS-Mars, WTI-WCS, Brent-Urals, Naphtha-Gasoil)",
    "priority": 11,},
    {
    "id":       "duc",
    "module":   "duc_fetcher",
    "output":   "duc_latest.json",
    "label":    "EIA DUC Wells + Regional Rig Count (DPR)",
    "priority": 12,},
    {
    "id":       "wcs",
    "module":   "wcs_fetcher",
    "output":   "wcs_latest.json",
    "label":    "WCS Price + WTI-WCS Differential (Alberta Govt API)",
    "priority": 4,},
    ]


def load_fetcher_module(module_name):
    module_path = FETCHER_DIR / f"{module_name}.py"
    if not module_path.exists():
        return None
    spec   = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def merge_signals(data_dir):
    merged = {
        "merged_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources":   {},
        "signals":   {"supply": {}, "demand": {}, "macro": {}, "prices": {}, "derived": {}},
        "composite": {},
    }

    eia_path = data_dir / "eia_latest.json"
    if eia_path.exists():
        eia = json.loads(eia_path.read_text())
        merged["sources"]["eia"] = eia.get("fetched_at")
        merged["signals"]["supply"]["cushing_stocks_mmbbls"]  = eia.get("signals", {}).get("cushing_stocks",    {}).get("value_mmbbls")
        merged["signals"]["supply"]["refinery_util_pct"]      = eia.get("signals", {}).get("refinery_util",     {}).get("value")
        merged["signals"]["supply"]["crude_production_mbd"]   = eia.get("signals", {}).get("crude_production",  {}).get("value_mbd")
        merged["signals"]["demand"]["gasoline_demand_mbd"]    = eia.get("signals", {}).get("gasoline_demand",   {}).get("value_mbd")
        merged["signals"]["demand"]["distillate_demand_mbd"]  = eia.get("signals", {}).get("distillate_demand", {}).get("value_mbd")

    fred_path = data_dir / "fred_latest.json"
    if fred_path.exists():
        fred   = json.loads(fred_path.read_text())
        series = fred.get("series", {})
        merged["sources"]["fred"]                          = fred.get("fetched_at")
        merged["signals"]["macro"]["dxy"]                  = series.get("dxy_broad",    {}).get("latest")
        merged["signals"]["macro"]["sofr"]                 = series.get("sofr",         {}).get("latest")
        merged["signals"]["macro"]["fedfunds"]             = series.get("fed_funds",    {}).get("latest")
        merged["signals"]["macro"]["dgs10"]                = series.get("us_10y_yield", {}).get("latest")
        merged["signals"]["macro"]["composite"]            = fred.get("derived", {}).get("macro_composite", {}).get("composite_signal")
        merged["signals"]["macro"]["storage_carry_monthly"]= fred.get("derived", {}).get("storage_carry",   {}).get("total_carry_per_bbl_mo")

    fut_path = data_dir / "futures_latest.json"
    if fut_path.exists():
        fut       = json.loads(fut_path.read_text())
        contracts = fut.get("contracts", {})
        derived   = fut.get("derived",   {})
        merged["sources"]["futures"]                        = fut.get("fetched_at")
        merged["signals"]["prices"]["brent_bbl"]            = contracts.get("brent",       {}).get("price_bbl")
        merged["signals"]["prices"]["wti_bbl"]              = contracts.get("wti",         {}).get("price_bbl")
        merged["signals"]["prices"]["rbob_bbl"]             = contracts.get("rbob",        {}).get("price_bbl")
        merged["signals"]["prices"]["ho_bbl"]               = contracts.get("heating_oil", {}).get("price_bbl")
        merged["signals"]["prices"]["ng_mmbtu"]             = contracts.get("henry_hub",   {}).get("raw_price")
        merged["signals"]["derived"]["crack_321_bbl"]       = derived.get("crack_321",        {}).get("value_bbl")
        merged["signals"]["derived"]["crack_321_signal"]    = derived.get("crack_321",        {}).get("signal")
        merged["signals"]["derived"]["brent_wti_bbl"]       = derived.get("brent_wti_spread", {}).get("value_bbl")
        merged["signals"]["derived"]["brent_wti_signal"]    = derived.get("brent_wti_spread", {}).get("signal")
        merged["signals"]["derived"]["ho_rbob_bbl"]         = derived.get("ho_rbob_spread",   {}).get("value_bbl")

    rig_path = data_dir / "rig_count_latest.json"
    if rig_path.exists():
        rig = json.loads(rig_path.read_text())
        merged["sources"]["rig_count"]                      = rig.get("fetched_at")
        merged["signals"]["supply"]["oil_rigs"]             = rig.get("series", {}).get("oil_rigs", {}).get("value")
        merged["signals"]["supply"]["oil_rigs_wow"]         = rig.get("series", {}).get("oil_rigs", {}).get("wow_change")
        merged["signals"]["supply"]["oil_rigs_signal"]      = rig.get("signal", {}).get("label")
        merged["signals"]["supply"]["oil_rigs_direction"]   = rig.get("signal", {}).get("direction")

    bdi_path = data_dir / "bdi_latest.json"
    if bdi_path.exists():
        bdi = json.loads(bdi_path.read_text())
        merged["sources"]["bdi"]                     = bdi.get("fetched_at")
        merged["signals"]["demand"]["bdi_value"]     = bdi.get("latest", {}).get("value")
        merged["signals"]["demand"]["bdi_wow"]       = bdi.get("latest", {}).get("wow")
        merged["signals"]["demand"]["bdi_signal"]    = bdi.get("signal", {}).get("label")
        merged["signals"]["demand"]["bdi_direction"] = bdi.get("signal", {}).get("direction")

    score, reasons = 0, []
    macro_sig = merged["signals"]["macro"].get("composite")
    if macro_sig == "BULLISH":
        score += 1; reasons.append("Macro tailwind (falling USD/rates)")
    elif macro_sig == "BEARISH":
        score -= 1; reasons.append("Macro headwind (rising USD/rates)")

    crack_sig = merged["signals"]["derived"].get("crack_321_signal")
    if crack_sig == "BULLISH":
        score += 1; reasons.append("Wide 3-2-1 crack → product demand pulling crude")
    elif crack_sig == "BEARISH":
        score -= 1; reasons.append("Compressed crack → refinery runs may fall")

    rig_sig = merged["signals"]["supply"].get("oil_rigs_direction")
    if rig_sig == "bullish":
        score += 0.5; reasons.append("Rig count falling → supply decline in 4-6 months")
    elif rig_sig == "bearish":
        score -= 0.5; reasons.append("Rig count rising → supply growth in 4-6 months")

    merged["composite"] = {
        "score":   round(score, 1),
        "label":   "BULLISH" if score > 0.5 else "BEARISH" if score < -0.5 else "NEUTRAL",
        "reasons": reasons,
    }
    return merged


def run_fetcher(entry, dry_run=False):
    if dry_run:
        log.info("  [DRY RUN] Would run: %s", entry["label"])
        return True

    log.info("▶ Running: %s", entry["label"])
    t0     = time.time()
    module = load_fetcher_module(entry["module"])

    if module is None:
        log.warning("  ⚠  Module not found: %s — skipping", entry["module"])
        return False
    if not hasattr(module, "run"):
        log.error("  ✗  Module %s has no run() function", entry["module"])
        return False

    try:
        module.run()
        log.info("  ✓  Done in %.1fs → %s", time.time() - t0, entry["output"])
        return True
    except Exception as exc:
        log.error("  ✗  Failed: %s", exc, exc_info=True)
        return False


def run_signal_layer():
    """Run inventory + crack signal layers after all fetchers complete."""
    sys.path.insert(0, str(ROOT))
    log.info("─" * 60)
    log.info("Signal Layer")
    log.info("─" * 60)

    try:
        from signals.inventory_signals import run as inv_run
        log.info("▶ inventory_signals")
        inv_run()
        log.info("  ✓ inventory_signals done")
    except Exception as e:
        log.error("  ✗ inventory_signals: %s", e)

    try:
        from signals.crack_signals import run as crack_run
        log.info("▶ crack_signals")
        crack_run()
        log.info("  ✓ crack_signals done")
    except Exception as e:
        log.error("  ✗ crack_signals: %s", e)


def main():
    parser = argparse.ArgumentParser(description="Energy Dashboard — Fetcher Orchestrator")
    parser.add_argument("--fetcher",  default="all",       help="Fetcher ID to run (or 'all')")
    parser.add_argument("--dry-run",  action="store_true", help="Show plan without running")
    parser.add_argument("--no-merge", action="store_true", help="Skip signal merge step")
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if args.fetcher == "all":
        to_run = FETCHER_REGISTRY
    else:
        to_run = [e for e in FETCHER_REGISTRY if e["id"] == args.fetcher]
        if not to_run:
            log.error("Unknown fetcher: %s. Options: %s", args.fetcher, [e["id"] for e in FETCHER_REGISTRY])
            sys.exit(1)

    log.info("═" * 60)
    log.info("ENERGY DASHBOARD — FETCHER ORCHESTRATOR")
    log.info("Run at: %s UTC", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    log.info("Fetchers queued: %d", len(to_run))
    log.info("═" * 60)

    # 1. Run fetchers
    results = {}
    for entry in sorted(to_run, key=lambda x: x["priority"]):
        ok = run_fetcher(entry, dry_run=args.dry_run)
        results[entry["id"]] = "ok" if ok else "failed"

    # 2. Signal layer (runs AFTER fetchers so data is fresh)
    if not args.dry_run:
        run_signal_layer()

    # 3. Merge all signals → signals_merged.json
    if not args.dry_run and not args.no_merge:
        log.info("─" * 60)
        log.info("Merging signals → %s", MERGED_OUT)
        try:
            merged = merge_signals(DATA_DIR)
            MERGED_OUT.write_text(json.dumps(merged, indent=2))
            comp = merged["composite"]
            log.info("Composite: %s (score=%.1f) | %s",
                     comp["label"], comp["score"],
                     " · ".join(comp["reasons"]) or "no signals")
        except Exception as exc:
            log.error("Merge failed: %s", exc, exc_info=True)

    # 4. Final report
    log.info("═" * 60)
    log.info("RESULTS")
    for fid, status in results.items():
        icon = "✓" if status == "ok" else "✗"
        log.info("  %s  %-12s  %s", icon, fid, status)
    log.info("═" * 60)

    sys.exit(0 if all(s == "ok" for s in results.values()) else 1)


if __name__ == "__main__":
    main()

"""
run_fetchers.py
---------------
Master orchestrator — runs all fetchers in sequence and writes a merged
signals file used by the FastAPI backend.

Run order (matches pipeline dependency):
  1. eia_fetcher.py       → backend/data/eia_latest.json
  2. fred_fetcher.py      → backend/data/fred_latest.json
  3. futures_fetcher.py   → backend/data/futures_latest.json
  (Days 3+ fetchers auto-detected and included when present)

Output:
  backend/data/signals_merged.json  ← FastAPI reads this file

Usage:
  python backend/run_fetchers.py                    # run all
  python backend/run_fetchers.py --fetcher eia      # run one
  python backend/run_fetchers.py --dry-run          # show plan, no fetch

Scheduling (Windows Task Scheduler):
  - EIA / futures: every 30 min during market hours
  - FRED: every 4 hours
  - Full run: 07:00 ET daily
"""

import argparse
import importlib.util
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────

ROOT        = Path(__file__).resolve().parent          # backend/
DATA_DIR    = ROOT / "data"
FETCHER_DIR = ROOT / "fetchers"
MERGED_OUT  = DATA_DIR / "signals_merged.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("orchestrator")

# ── Fetcher registry ─────────────────────────────────────────────────────────
# Order matters: EIA first (inventory tightness), then macro (FRED), then prices (futures)

FETCHER_REGISTRY = [
    {
        "id":       "eia",
        "module":   "eia_fetcher",
        "output":   "eia_latest.json",
        "label":    "EIA Weekly Petroleum (inventory + production)",
        "priority": 1,
    },
    {
        "id":       "fred",
        "module":   "fred_fetcher",
        "output":   "fred_latest.json",
        "label":    "FRED Macro Indicators (DXY, SOFR, FEDFUNDS, DGS10)",
        "priority": 2,
    },
    {
        "id":       "futures",
        "module":   "futures_fetcher",
        "output":   "futures_latest.json",
        "label":    "Energy Futures Prices (Brent, WTI, RBOB, HO, NG)",
        "priority": 3,
    },
    # Day 3+ — auto-included when file exists
    {
        "id":       "gie",
        "module":   "gie_fetcher",
        "output":   "gie_latest.json",
        "label":    "GIE AGSI+ European Gas Storage",
        "priority": 4,
    },
    {
        "id":       "weather",
        "module":   "weather_fetcher",
        "output":   "weather_latest.json",
        "label":    "Open-Meteo HDD/CDD Demand Signals",
        "priority": 5,
    },
    {
        "id":       "cftc",
        "module":   "cftc_fetcher",
        "output":   "cftc_latest.json",
        "label":    "CFTC Commitments of Traders (speculative positioning)",
        "priority": 6,
    },
    {
        "id":       "sentiment",
        "module":   "sentiment_fetcher",
        "output":   "sentiment_latest.json",
        "label":    "News Sentiment + Geopolitical Risk Scorer",
        "priority": 7,
    },
]


# ── Dynamic module loader ─────────────────────────────────────────────────────

def load_fetcher_module(module_name: str):
    """Dynamically load a fetcher module from the fetchers/ directory."""
    module_path = FETCHER_DIR / f"{module_name}.py"
    if not module_path.exists():
        return None

    spec   = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


# ── Signal merger ─────────────────────────────────────────────────────────────

def merge_signals(data_dir: Path) -> dict:
    """
    Load all *_latest.json files and extract top-level signals into one dict.
    Used by FastAPI to serve the frontend without reading multiple files.
    """
    merged = {
        "merged_at": datetime.utcnow().isoformat() + "Z",
        "sources":   {},
        "signals":   {
            "supply":     {},
            "demand":     {},
            "macro":      {},
            "prices":     {},
            "derived":    {},
        },
        "composite": {},
    }

    # EIA signals
    eia_path = data_dir / "eia_latest.json"
    if eia_path.exists():
        eia = json.loads(eia_path.read_text())
        merged["sources"]["eia"]   = eia.get("fetched_at")
        merged["signals"]["supply"]["cushing_stocks_mmbbls"] = (
            eia.get("signals", {}).get("cushing_stocks", {}).get("value_mmbbls")
        )
        merged["signals"]["supply"]["refinery_util_pct"] = (
            eia.get("signals", {}).get("refinery_util", {}).get("value")
        )
        merged["signals"]["supply"]["crude_production_mbd"] = (
            eia.get("signals", {}).get("crude_production", {}).get("value_mbd")
        )
        merged["signals"]["demand"]["gasoline_demand_mbd"] = (
            eia.get("signals", {}).get("gasoline_demand", {}).get("value_mbd")
        )
        merged["signals"]["demand"]["distillate_demand_mbd"] = (
            eia.get("signals", {}).get("distillate_demand", {}).get("value_mbd")
        )

    # FRED macro signals
    fred_path = data_dir / "fred_latest.json"
    if fred_path.exists():
        fred = json.loads(fred_path.read_text())
        merged["sources"]["fred"] = fred.get("fetched_at")
        series = fred.get("series", {})
        merged["signals"]["macro"]["dxy"]       = series.get("dxy_broad", {}).get("latest")
        merged["signals"]["macro"]["sofr"]      = series.get("sofr", {}).get("latest")
        merged["signals"]["macro"]["fedfunds"]  = series.get("fed_funds", {}).get("latest")
        merged["signals"]["macro"]["dgs10"]     = series.get("us_10y_yield", {}).get("latest")
        merged["signals"]["macro"]["composite"] = (
            fred.get("derived", {}).get("macro_composite", {}).get("composite_signal")
        )
        merged["signals"]["macro"]["storage_carry_monthly"] = (
            fred.get("derived", {}).get("storage_carry", {}).get("total_carry_per_bbl_mo")
        )

    # Futures prices + spreads
    fut_path = data_dir / "futures_latest.json"
    if fut_path.exists():
        fut = json.loads(fut_path.read_text())
        merged["sources"]["futures"] = fut.get("fetched_at")
        contracts = fut.get("contracts", {})
        merged["signals"]["prices"]["brent_bbl"]   = contracts.get("brent", {}).get("price_bbl")
        merged["signals"]["prices"]["wti_bbl"]     = contracts.get("wti", {}).get("price_bbl")
        merged["signals"]["prices"]["rbob_bbl"]    = contracts.get("rbob", {}).get("price_bbl")
        merged["signals"]["prices"]["ho_bbl"]      = contracts.get("heating_oil", {}).get("price_bbl")
        merged["signals"]["prices"]["ng_mmbtu"]    = contracts.get("henry_hub", {}).get("raw_price")

        derived = fut.get("derived", {})
        merged["signals"]["derived"]["crack_321_bbl"]    = derived.get("crack_321", {}).get("value_bbl")
        merged["signals"]["derived"]["crack_321_signal"] = derived.get("crack_321", {}).get("signal")
        merged["signals"]["derived"]["brent_wti_bbl"]    = derived.get("brent_wti_spread", {}).get("value_bbl")
        merged["signals"]["derived"]["brent_wti_signal"] = derived.get("brent_wti_spread", {}).get("signal")
        merged["signals"]["derived"]["ho_rbob_bbl"]      = derived.get("ho_rbob_spread", {}).get("value_bbl")

    # ── Composite score ───────────────────────────────────────────────────────
    # Simple weighted scorecard: +1 bullish / -1 bearish / 0 neutral per signal
    score = 0
    reasons = []

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

    bwti_sig = merged["signals"]["derived"].get("brent_wti_signal")
    if bwti_sig == "ALERT":
        spread = merged["signals"]["derived"].get("brent_wti_bbl", 0) or 0
        if spread > 8:
            score -= 0.5; reasons.append("Brent-WTI > $8: US export bottleneck")
        else:
            score += 0.5; reasons.append("Brent-WTI < $2: US exports flooding")

    merged["composite"] = {
        "score":   round(score, 1),
        "label":   "BULLISH" if score > 0.5 else "BEARISH" if score < -0.5 else "NEUTRAL",
        "reasons": reasons,
        "note":    (
            "Composite score built from macro + crack + spread signals. "
            "Add inventory tightness (EIA Cushing draw/build) and "
            "CFTC positioning (Day 6) for full 10-point NCI signal."
        ),
    }

    return merged


# ── Runner ────────────────────────────────────────────────────────────────────

def run_fetcher(entry: dict, dry_run: bool = False) -> bool:
    """Run one fetcher. Returns True on success."""
    fid   = entry["id"]
    label = entry["label"]

    if dry_run:
        log.info("  [DRY RUN] Would run: %s", label)
        return True

    log.info("▶ Running: %s", label)
    t0 = time.time()

    module = load_fetcher_module(entry["module"])
    if module is None:
        log.warning("  ⚠  Module not found: %s — skipping", entry["module"])
        return False

    if not hasattr(module, "run"):
        log.error("  ✗  Module %s has no run() function", entry["module"])
        return False

    try:
        module.run()
        elapsed = time.time() - t0
        log.info("  ✓  Done in %.1fs → %s", elapsed, entry["output"])
        return True
    except Exception as exc:
        log.error("  ✗  Failed: %s", exc, exc_info=True)
        return False


def main():
    parser = argparse.ArgumentParser(description="Energy Dashboard — Fetcher Orchestrator")
    parser.add_argument("--fetcher",  default="all",  help="Fetcher ID to run (or 'all')")
    parser.add_argument("--dry-run",  action="store_true", help="Show plan without running")
    parser.add_argument("--no-merge", action="store_true", help="Skip signal merge step")
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Filter registry
    if args.fetcher == "all":
        to_run = FETCHER_REGISTRY
    else:
        to_run = [e for e in FETCHER_REGISTRY if e["id"] == args.fetcher]
        if not to_run:
            log.error("Unknown fetcher ID: %s. Options: %s",
                      args.fetcher, [e["id"] for e in FETCHER_REGISTRY])
            sys.exit(1)

    log.info("═" * 60)
    log.info("ENERGY DASHBOARD — FETCHER ORCHESTRATOR")
    log.info("Run at: %s UTC", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))
    log.info("Fetchers queued: %d", len(to_run))
    log.info("═" * 60)

    results = {}
    for entry in sorted(to_run, key=lambda x: x["priority"]):
        ok = run_fetcher(entry, dry_run=args.dry_run)
        results[entry["id"]] = "ok" if ok else "failed"

    # Signal merge
    if not args.dry_run and not args.no_merge:
        log.info("─" * 60)
        log.info("Merging signals → %s", MERGED_OUT)
        try:
            merged = merge_signals(DATA_DIR)
            MERGED_OUT.write_text(json.dumps(merged, indent=2))
            comp = merged["composite"]
            log.info(
                "Composite: %s (score=%.1f) | %s",
                comp["label"], comp["score"],
                " · ".join(comp["reasons"]) or "no signals",
            )
        except Exception as exc:
            log.error("Merge failed: %s", exc, exc_info=True)

    # Final report
    log.info("═" * 60)
    log.info("RESULTS")
    for fid, status in results.items():
        icon = "✓" if status == "ok" else "✗"
        log.info("  %s  %-12s  %s", icon, fid, status)
    log.info("═" * 60)

    failed = sum(1 for s in results.values() if s == "failed")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()

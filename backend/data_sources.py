"""
data_sources.py
---------------
Single file that shows the status of every data source in the dashboard.
Reads the cached JSON files (no live API calls) and prints a clean summary.

Usage:
  python backend/data_sources.py            # show all sources
  python backend/data_sources.py --json     # output as JSON
  python backend/data_sources.py --refresh  # re-run all fetchers then show status

Data sources covered:
  Day 1  → EIA Weekly Petroleum (eia_latest.json)
  Day 2  → FRED Macro (fred_latest.json)
  Day 2  → Energy Futures / Yahoo Finance (futures_latest.json)
  Day 3  → GIE AGSI+ European Gas Storage (gie_latest.json)
  Day 3  → Open-Meteo Weather / HDD/CDD (weather_latest.json)
  Day 3  → CFTC Commitments of Traders (cftc_latest.json)
  Day 4+ → Inventory Signal Engine (signals_merged.json)
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"

# ── Source registry ───────────────────────────────────────────────────────────

SOURCES = [
    # ── SUPPLY SIDE ──────────────────────────────────────────────────────────
    {
        "id":          "eia",
        "label":       "EIA Weekly Petroleum Status Report",
        "file":        "eia_latest.json",
        "category":    "SUPPLY",
        "api":         "ir.eia.gov/wpsr/ (free, no key)",
        "frequency":   "Weekly — Wednesday 10:30 ET",
        "day_built":   1,
        "key_signals": [
            ("cushing_stocks",    "signals.cushing_stocks.value_mmbbls",   "mmbbls", "Cushing storage"),
            ("refinery_util",     "signals.refinery_util.value",           "%",      "Refinery utilisation"),
            ("crude_production",  "signals.crude_production.value_mbd",    "mbd",    "US crude production"),
            ("gasoline_stocks",   "signals.gasoline_stocks.value_mmbbls",  "mmbbls", "Gasoline stocks"),
            ("distillate_stocks", "signals.distillate_stocks.value_mmbbls","mmbbls", "Distillate stocks"),
            ("crude_imports",     "signals.crude_imports.value_mbd",       "mbd",    "Crude imports"),
            ("crude_exports",     "signals.crude_exports.value_mbd",       "mbd",    "Crude exports"),
            ("gasoline_demand",   "signals.gasoline_demand.value_mbd",     "mbd",    "Gasoline demand"),
            ("distillate_demand", "signals.distillate_demand.value_mbd",   "mbd",    "Distillate demand"),
            ("total_crude_stocks","signals.total_crude_stocks.value_mmbbls","mmbbls","Total crude stocks"),
        ],
    },
    # ── MACRO ─────────────────────────────────────────────────────────────────
    {
        "id":          "fred",
        "label":       "FRED Macro Indicators",
        "file":        "fred_latest.json",
        "category":    "MACRO",
        "api":         "api.stlouisfed.org (free key — fred.stlouisfed.org)",
        "frequency":   "Daily (some weekly)",
        "day_built":   2,
        "key_signals": [
            ("dxy",        "series.dxy_broad.latest",      "index", "DXY Dollar Index"),
            ("sofr",       "series.sofr.latest",           "%",     "SOFR rate"),
            ("fedfunds",   "series.fed_funds.latest",      "%",     "Fed Funds rate"),
            ("dgs10",      "series.us_10y_yield.latest",   "%",     "10Y Treasury yield"),
            ("carry_cost", "derived.storage_carry.total_carry_per_bbl_mo", "$/bbl/mo", "Storage carry cost"),
        ],
    },
    # ── PRICES ───────────────────────────────────────────────────────────────
    {
        "id":          "futures",
        "label":       "Energy Futures Prices (Yahoo Finance)",
        "file":        "futures_latest.json",
        "category":    "PRICES",
        "api":         "query1.finance.yahoo.com (free, delayed ~15min)",
        "frequency":   "Real-time (delayed)",
        "day_built":   2,
        "key_signals": [
            ("brent",     "contracts.brent.price_bbl",           "$/bbl", "Brent crude"),
            ("wti",       "contracts.wti.price_bbl",             "$/bbl", "WTI crude"),
            ("rbob",      "contracts.rbob.price_bbl",            "$/bbl", "RBOB gasoline"),
            ("ho",        "contracts.heating_oil.price_bbl",     "$/bbl", "Heating oil / ULSD"),
            ("ng",        "contracts.henry_hub.raw_price",       "$/mmBTU","Henry Hub gas"),
            ("crack_321", "derived.crack_321.value_bbl",         "$/bbl", "3-2-1 crack spread"),
            ("brent_wti", "derived.brent_wti_spread.value_bbl",  "$/bbl", "Brent-WTI spread"),
            ("ho_rbob",   "derived.ho_rbob_spread.value_bbl",    "$/bbl", "HO-RBOB spread"),
        ],
    },
    # ── GAS STORAGE ──────────────────────────────────────────────────────────
    {
        "id":          "gie",
        "label":       "GIE AGSI+ European Gas Storage",
        "file":        "gie_latest.json",
        "category":    "DEMAND",
        "api":         "agsi.gie.eu (free key — register at agsi.gie.eu)",
        "frequency":   "Daily",
        "day_built":   3,
        "key_signals": [
            ("de_fill",  "regions.germany.fill_pct",     "%", "Germany fill %"),
            ("fr_fill",  "regions.france.fill_pct",      "%", "France fill %"),
            ("it_fill",  "regions.italy.fill_pct",       "%", "Italy fill %"),
            ("nl_fill",  "regions.netherlands.fill_pct", "%", "Netherlands fill %"),
            ("signal",   "composite.signal",             "",  "EU gas composite signal"),
        ],
    },
    # ── WEATHER ──────────────────────────────────────────────────────────────
    {
        "id":          "weather",
        "label":       "Open-Meteo HDD/CDD Weather Demand",
        "file":        "weather_latest.json",
        "category":    "DEMAND",
        "api":         "api.open-meteo.com (completely free, no key needed)",
        "frequency":   "Daily (7-day forecast + 14-day history)",
        "day_built":   3,
        "key_signals": [
            ("ny_hdd",     "locations.new_york.hdd_7d_forecast",   "HDD", "New York 7d HDD"),
            ("dubai_cdd",  "locations.dubai.cdd_7d_forecast",      "CDD", "Dubai 7d CDD"),
            ("tokyo_cdd",  "locations.tokyo.cdd_7d_forecast",      "CDD", "Tokyo 7d CDD"),
            ("london_hdd", "locations.london.hdd_7d_forecast",     "HDD", "London 7d HDD"),
            ("signal",     "composite.signal",                     "",    "Weather composite signal"),
        ],
    },
    # ── CFTC POSITIONING ─────────────────────────────────────────────────────
    {
        "id":          "cftc",
        "label":       "CFTC Commitments of Traders",
        "file":        "cftc_latest.json",
        "category":    "SENTIMENT",
        "api":         "publicreporting.cftc.gov (completely free, no key needed)",
        "frequency":   "Weekly — Friday 3:30 PM ET (Tuesday positions)",
        "day_built":   3,
        "key_signals": [
            ("wti_net",   "contracts.wti.mm_net_lots",          "lots", "WTI MM net lots"),
            ("rbob_net",  "contracts.rbob.mm_net_lots",         "lots", "RBOB MM net lots"),
            ("rbob_pct",  "contracts.rbob.net_pct_of_oi",       "% OI", "RBOB net % of OI"),
            ("ng_net",    "contracts.natural_gas.mm_net_lots",  "lots", "NG MM net lots"),
            ("ng_signal", "contracts.natural_gas.signal",       "",     "NG positioning signal"),
            ("composite", "composite.signal",                   "",     "CFTC composite signal"),
        ],
    },
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def deep_get(data: dict, path: str):
    """Get a nested value using dot notation. Returns None if missing."""
    keys = path.split(".")
    val  = data
    for k in keys:
        if isinstance(val, dict):
            val = val.get(k)
        else:
            return None
    return val


def load_json(filepath: Path) -> dict | None:
    try:
        return json.loads(filepath.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def format_value(val) -> str:
    if val is None:
        return "—"
    if isinstance(val, float):
        return f"{val:,.2f}"
    if isinstance(val, int):
        return f"{val:,}"
    return str(val)


def signal_colour(signal: str) -> str:
    """Return a text prefix to visually indicate signal direction."""
    s = str(signal).upper()
    if s in ("BULLISH", "MILD_BULLISH"):
        return "▲"
    if s in ("BEARISH", "MILD_BEARISH"):
        return "▼"
    if s in ("CROWDED_LONG", "CROWDED_SHORT", "ALERT"):
        return "⚠"
    return "●"


def time_since(fetched_at: str) -> str:
    """Return human-readable time since last fetch."""
    if not fetched_at:
        return "unknown"
    try:
        # Handle both ISO format with Z and without
        fetched_at = fetched_at.replace("Z", "").strip()
        dt = datetime.fromisoformat(fetched_at)
        delta = datetime.utcnow() - dt
        hours = int(delta.total_seconds() // 3600)
        mins  = int((delta.total_seconds() % 3600) // 60)
        if hours > 48:
            return f"{hours // 24}d ago"
        if hours > 0:
            return f"{hours}h {mins}m ago"
        return f"{mins}m ago"
    except Exception:
        return fetched_at[:16]

# ── Main display ──────────────────────────────────────────────────────────────

def show_all(output_json: bool = False) -> dict:
    """Load all cached data files and display status."""

    results = {}
    categories = {}

    for src in SOURCES:
        filepath = DATA_DIR / src["file"]
        data     = load_json(filepath)

        if data is None:
            status      = "NOT_FETCHED"
            fetched_ago = "never"
            signals     = {}
        else:
            status      = "OK"
            fetched_ago = time_since(data.get("fetched_at", ""))
            signals     = {
                sig_key: deep_get(data, path)
                for sig_key, path, unit, label in src["key_signals"]
            }

        results[src["id"]] = {
            "label":       src["label"],
            "category":    src["category"],
            "status":      status,
            "fetched_ago": fetched_ago,
            "api":         src["api"],
            "frequency":   src["frequency"],
            "day_built":   src["day_built"],
            "signals":     signals,
        }

        cat = src["category"]
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(src["id"])

    if output_json:
        print(json.dumps(results, indent=2, default=str))
        return results

    # ── Pretty print ──────────────────────────────────────────────────────────
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    print()
    print("═" * 70)
    print(f"  ENERGY DASHBOARD — DATA SOURCES STATUS")
    print(f"  As of: {now}")
    print("═" * 70)

    cat_order = ["SUPPLY", "PRICES", "MACRO", "DEMAND", "SENTIMENT"]
    cat_icons = {
        "SUPPLY":    "🛢  SUPPLY SIDE",
        "PRICES":    "📈  MARKET PRICES",
        "MACRO":     "🏦  MACRO INDICATORS",
        "DEMAND":    "⚡  DEMAND SIGNALS",
        "SENTIMENT": "📊  MARKET SENTIMENT",
    }

    for cat in cat_order:
        if cat not in categories:
            continue
        print()
        print(f"  {cat_icons.get(cat, cat)}")
        print(f"  {'─' * 66}")

        for src_id in categories[cat]:
            src_cfg = next(s for s in SOURCES if s["id"] == src_id)
            res     = results[src_id]
            status  = res["status"]
            icon    = "✓" if status == "OK" else "✗"

            print(f"  {icon}  {res['label']}")
            print(f"     API:       {res['api']}")
            print(f"     Frequency: {res['frequency']}")
            print(f"     Last run:  {res['fetched_ago']}")

            if status == "OK":
                print(f"     Signals:")
                for sig_key, path, unit, label in src_cfg["key_signals"]:
                    val = res["signals"].get(sig_key)
                    formatted = format_value(val)
                    # Add signal arrow for signal fields
                    prefix = signal_colour(val) + " " if sig_key in ("signal", "composite", "ng_signal") else "  "
                    unit_str = f" {unit}" if unit else ""
                    print(f"       {prefix}{label:<30s} {formatted}{unit_str}")
            else:
                print(f"     ⚠  Not fetched yet — run: python backend/fetchers/{src_cfg['file'].replace('_latest.json','_fetcher.py')}")

            print()

    # ── Summary scorecard ─────────────────────────────────────────────────────
    ok_count   = sum(1 for r in results.values() if r["status"] == "OK")
    fail_count = len(results) - ok_count

    print("═" * 70)
    print(f"  SUMMARY: {ok_count}/{len(results)} sources active", end="")
    if fail_count:
        print(f"  |  {fail_count} not yet fetched", end="")
    print()

    # Collect all signals for composite
    all_signals = []
    for res in results.values():
        for k, v in res.get("signals", {}).items():
            if k in ("signal", "composite") and v:
                all_signals.append(str(v).upper())

    bullish = all_signals.count("BULLISH") + all_signals.count("MILD_BULLISH")
    bearish = all_signals.count("BEARISH") + all_signals.count("MILD_BEARISH")
    neutral = len(all_signals) - bullish - bearish

    print(f"  SIGNALS:  ▲ Bullish={bullish}  ▼ Bearish={bearish}  ● Neutral={neutral}")
    overall = "BULLISH" if bullish > bearish + 1 else "BEARISH" if bearish > bullish + 1 else "MIXED"
    print(f"  OVERALL COMPOSITE: {signal_colour(overall)} {overall}")
    print("═" * 70)
    print()

    return results


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Energy Dashboard — Data Sources Status")
    parser.add_argument("--json",    action="store_true", help="Output as JSON")
    parser.add_argument("--refresh", action="store_true", help="Re-run all fetchers first")
    args = parser.parse_args()

    if args.refresh:
        print("Refreshing all data sources...")
        import subprocess
        subprocess.run(
            [sys.executable, str(Path(__file__).parent / "run_fetchers.py")],
            check=False,
        )
        print()

    show_all(output_json=args.json)


if __name__ == "__main__":
    main()

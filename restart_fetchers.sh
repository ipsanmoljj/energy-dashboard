#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Energy Signal — Re-run all fetchers only (no restart of services)
# Useful mid-session when you want fresh data without restarting everything
# Run from repo root: bash restart_fetchers.sh
# ─────────────────────────────────────────────────────────────────────────────

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"

CYAN="\033[36m"
GREEN="\033[32m"
YELLOW="\033[33m"
RESET="\033[0m"

log()  { echo -e "${CYAN}[$(date '+%H:%M:%S')]${RESET} $1"; }
ok()   { echo -e "${GREEN}[$(date '+%H:%M:%S')] ✓${RESET} $1"; }
warn() { echo -e "${YELLOW}[$(date '+%H:%M:%S')] ⚠${RESET} $1"; }

FETCHERS=(
    "fetchers/eia_fetcher.py"
    "fetchers/fred_fetcher.py"
    "fetchers/futures_fetcher.py"
    "fetchers/baker_hughes_fetcher.py"
    "fetchers/quality_spreads_fetcher.py"
    "fetchers/wcs_fetcher.py"
    "fetchers/news_fetcher.py"
    "crack_spread_engine.py"
    "nci_composite.py"
)

log "Re-running all fetchers..."
for f in "${FETCHERS[@]}"; do
    path="$BACKEND/$f"
    if [ -f "$path" ]; then
        log "  $f ..."
        python "$path" 2>/dev/null && ok "  $f" || warn "  $f failed"
    fi
done
ok "All fetchers done. APScheduler will pick up the fresh data on next cycle."

#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Energy Signal — Full Startup Script
# Run from repo root: bash start.sh
#
# On Railway (PORT env var is set), skip the dev loop and run uvicorn directly.
if [ -n "$PORT" ]; then
    cd "$(dirname "$0")/backend"
    exec python -m uvicorn api:app --host 0.0.0.0 --port "$PORT"
fi
#
# What this does:
#   1. Pulls latest code from git
#   2. Re-runs all fetchers (backend/data/ is gitignored — must re-run each session)
#   3. Starts uvicorn backend on port 8000 (background)
#   4. Starts Vite frontend on port 5173 (background)
#   5. Runs a keepalive loop in the foreground — keeps the Codespace awake
#      and lets you see live heartbeats so you know both services are up
#
# Ports: make sure 8000 and 5173 are set to PUBLIC in the Codespaces Ports tab
# ─────────────────────────────────────────────────────────────────────────────

set -e   # exit on first error during setup phase

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
BACKEND_URL="http://localhost:8000"
FRONTEND_URL="http://localhost:5173"
PING_INTERVAL=240   # seconds between keepalive pings (4 min)

GREEN="\033[32m"
YELLOW="\033[33m"
RED="\033[31m"
CYAN="\033[36m"
RESET="\033[0m"

log()  { echo -e "${CYAN}[$(date '+%H:%M:%S')]${RESET} $1"; }
ok()   { echo -e "${GREEN}[$(date '+%H:%M:%S')] ✓${RESET} $1"; }
warn() { echo -e "${YELLOW}[$(date '+%H:%M:%S')] ⚠${RESET} $1"; }
err()  { echo -e "${RED}[$(date '+%H:%M:%S')] ✗${RESET} $1"; }

# ── 1. Git pull ───────────────────────────────────────────────────────────────
log "Pulling latest code..."
git -C "$ROOT" pull --ff-only 2>/dev/null && ok "git pull done" || warn "git pull skipped (local changes or already up to date)"

# ── 2. Fetchers ───────────────────────────────────────────────────────────────
log "Re-running fetchers (backend/data/ resets each session)..."

FETCHERS=(
    "fetchers/eia_fetcher.py"
    "fetchers/fred_fetcher.py"
    "fetchers/futures_fetcher.py"
    "fetchers/baker_hughes_fetcher.py"
    "fetchers/quality_spreads_fetcher.py"
    "fetchers/wcs_fetcher.py"
    "fetchers/news_fetcher.py"
    "fetchers/seasonality_fetcher.py"
    "crack_spread_engine.py"
    "nci_composite.py"
)

for f in "${FETCHERS[@]}"; do
    path="$BACKEND/$f"
    if [ -f "$path" ]; then
        log "  Running $f ..."
        python "$path" 2>/dev/null && ok "  $f done" || warn "  $f failed (continuing)"
    else
        warn "  $f not found — skipping"
    fi
done

# ── 3. Backend — uvicorn ─────────────────────────────────────────────────────
log "Starting backend (uvicorn port 8000)..."
pkill -f "uvicorn api:app" 2>/dev/null || true   # kill any stale instance
sleep 1

cd "$BACKEND"
python -m uvicorn api:app --reload --port 8000 --host 0.0.0.0 \
    >> "$ROOT/logs/backend.log" 2>&1 &
BACKEND_PID=$!
cd "$ROOT"

# Wait up to 15s for backend to come up
log "Waiting for backend..."
for i in $(seq 1 15); do
    sleep 1
    code=$(curl -s -o /dev/null -w "%{http_code}" "$BACKEND_URL/health" 2>/dev/null)
    if [ "$code" = "200" ]; then
        ok "Backend up (PID $BACKEND_PID) → $BACKEND_URL"
        break
    fi
    if [ "$i" = "15" ]; then
        err "Backend did not respond after 15s — check logs/backend.log"
    fi
done

# ── 4. Frontend — Vite ───────────────────────────────────────────────────────
log "Starting frontend (Vite port 5173)..."
pkill -f "vite" 2>/dev/null || true
sleep 1

mkdir -p "$ROOT/logs"
cd "$FRONTEND"
npm run dev -- --host 0.0.0.0 \
    >> "$ROOT/logs/frontend.log" 2>&1 &
FRONTEND_PID=$!
cd "$ROOT"

# Wait up to 20s for Vite to come up
log "Waiting for frontend..."
for i in $(seq 1 20); do
    sleep 1
    code=$(curl -s -o /dev/null -w "%{http_code}" "$FRONTEND_URL" 2>/dev/null)
    if [ "$code" = "200" ] || [ "$code" = "304" ]; then
        ok "Frontend up (PID $FRONTEND_PID) → $FRONTEND_URL"
        break
    fi
    if [ "$i" = "20" ]; then
        warn "Frontend not yet responding — it may still be building. Check logs/frontend.log"
    fi
done

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "${GREEN}  ⚡ ENERGY SIGNAL — RUNNING${RESET}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo -e "  Backend   →  ${CYAN}$BACKEND_URL${RESET}  (PID $BACKEND_PID)"
echo -e "  Frontend  →  ${CYAN}$FRONTEND_URL${RESET}  (PID $FRONTEND_PID)"
echo -e "  Logs      →  ${CYAN}$ROOT/logs/${RESET}"
echo ""
echo -e "  ${YELLOW}Remember: set ports 8000 and 5173 to PUBLIC in the Ports tab${RESET}"
echo -e "  ${YELLOW}Ctrl+C stops the keepalive loop — backend and frontend keep running${RESET}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}"
echo ""

# ── 5. Keepalive loop — foreground, keeps terminal (and Codespace) active ────
log "Keepalive loop starting (pings every ${PING_INTERVAL}s) — Ctrl+C to stop"
echo ""

while true; do
    ts=$(date '+%H:%M:%S')

    # Ping backend
    be_code=$(curl -s -o /dev/null -w "%{http_code}" "$BACKEND_URL/health" 2>/dev/null)
    be_status=$( [ "$be_code" = "200" ] && echo -e "${GREEN}✓ $be_code${RESET}" || echo -e "${RED}✗ $be_code${RESET}" )

    # Ping frontend
    fe_code=$(curl -s -o /dev/null -w "%{http_code}" "$FRONTEND_URL" 2>/dev/null)
    fe_status=$( [ "$fe_code" = "200" ] || [ "$fe_code" = "304" ] && echo -e "${GREEN}✓ $fe_code${RESET}" || echo -e "${RED}✗ $fe_code${RESET}" )

    echo -e "${CYAN}[$ts]${RESET} backend $be_status  frontend $fe_status"
    sleep $PING_INTERVAL
done

#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Energy Signal — Stop all services
# Run: bash stop.sh
# ─────────────────────────────────────────────────────────────────────────────

GREEN="\033[32m"
YELLOW="\033[33m"
RESET="\033[0m"

echo -e "${YELLOW}Stopping Energy Signal services...${RESET}"

pkill -f "uvicorn api:app" 2>/dev/null && echo -e "${GREEN}✓ Backend stopped${RESET}" || echo "  Backend was not running"
pkill -f "vite"            2>/dev/null && echo -e "${GREEN}✓ Frontend stopped${RESET}" || echo "  Frontend was not running"
pkill -f "keepalive"       2>/dev/null && true   # clean up any standalone keepalive scripts

echo -e "${GREEN}Done.${RESET}"

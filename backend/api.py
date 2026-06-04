"""
api.py — FastAPI server + APScheduler
Serves all signal data to React frontend.
Auto-refreshes: futures/crack/composite every 5min, EIA/inventory every 30min,
                fred/gie/weather every hour, cftc every Friday 4pm ET.

Start: python -m uvicorn api:app --reload --port 8000
"""

import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.background import BackgroundScheduler

ROOT     = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"

# ── Signal layer imports ───────────────────────────────────────────────────────
sys.path.insert(0, str(ROOT))
from signals.inventory_signals import run as run_inventory_signals
from signals.crack_signals      import run as run_crack_signals

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger(__name__)

app = FastAPI(title="Energy Markets Dashboard API", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

def load(filename):
    try:
        return json.loads((DATA_DIR / filename).read_text())
    except Exception:
        return {"error": f"{filename} not found"}

def run_script(rel_path, label):
    try:
        log.info("Scheduler ▶ %s", label)
        r = subprocess.run([sys.executable, str(ROOT / rel_path)],
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            log.warning("  %s error: %s", label, r.stderr[-150:])
        else:
            log.info("  %s ✓", label)
    except Exception as e:
        log.error("  %s failed: %s", label, e)

# ── Scheduled jobs ────────────────────────────────────────────────────────────

def job_prices():
    """Futures → Crack → Composite → History → Crack signal layer (every 5 min)"""
    run_script("fetchers/futures_fetcher.py", "futures")
    run_script("crack_spread_engine.py",      "crack")
    run_script("nci_composite.py",            "composite")
    run_script("history_store.py",            "history")
    try:
        run_crack_signals()
    except Exception as e:
        log.warning("crack_signals layer error: %s", e)

def job_inventory():
    """EIA inventory signals (every 30 min)"""
    run_script("fetchers/eia_fetcher.py", "eia")
    run_script("fetchers/wcs_fetcher.py", "wcs")
    try:
        run_inventory_signals()
    except Exception as e:
        log.warning("inventory_signals layer error: %s", e)

def job_fred():
    run_script("fetchers/fred_fetcher.py", "fred")

def job_gie():
    run_script("fetchers/gie_fetcher.py", "gie")

def job_weather():
    run_script("fetchers/weather_fetcher.py", "weather")

def job_news():
    run_script("fetchers/news_fetcher.py", "news_sentiment")

def job_cftc():
    run_script("fetchers/cftc_fetcher.py", "cftc")

scheduler = BackgroundScheduler()
scheduler.add_job(job_prices,    "interval", minutes=5,  id="prices",    max_instances=1)
scheduler.add_job(job_inventory, "interval", minutes=30, id="inventory", max_instances=1)
scheduler.add_job(job_fred,      "interval", hours=1,    id="fred",      max_instances=1)
scheduler.add_job(job_gie,       "interval", hours=1,    id="gie",       max_instances=1)
scheduler.add_job(job_weather,   "interval", hours=1,    id="weather",   max_instances=1)
scheduler.add_job(job_news,      "interval", minutes=15, id="news",      max_instances=1)
scheduler.add_job(job_cftc,      "cron",     day_of_week="fri", hour=16,
                  minute=5, id="cftc", max_instances=1, timezone="America/New_York")

@app.on_event("startup")
def startup():
    scheduler.start()
    log.info("Scheduler started — running initial fetch...")
    job_prices()
    job_inventory()
    log.info("API ready → http://localhost:8000")

@app.on_event("shutdown")
def shutdown():
    scheduler.shutdown()

# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/api/composite")
def composite():        return load("nci_composite.json")

@app.get("/api/inventory")
def inventory():        return load("inventory_signals.json")

@app.get("/api/crack")
def crack():            return load("crack_signals.json")

@app.get("/api/futures")
def futures():          return load("futures_latest.json")

@app.get("/api/fred")
def fred():             return load("fred_latest.json")

@app.get("/api/gie")
def gie():              return load("gie_latest.json")

@app.get("/api/weather")
def weather():          return load("weather_latest.json")

@app.get("/api/news")
def news():             return load("news_signals.json")

@app.get("/api/cftc")
def cftc():             return load("cftc_latest.json")

@app.get("/api/eia")
def eia():              return load("eia_latest.json")

@app.get("/api/rig-count")
def rig_count():        return load("rig_count_latest.json")

@app.get("/api/history")
def history():          return load("price_history.json")
  
@app.get("/api/quality-spreads")
def quality_spreads(): return load("quality_spreads_latest.json")

@app.get("/api/financialjuice")
def financialjuice(): return load("financialjuice_latest.json")
  
@app.get("/api/quality-spreads-history")
def quality_spreads_history(): return load("quality_spreads_history.json")

@app.get("/api/duc")
def duc(): return load("duc_latest.json")

@app.get("/api/wcs")
def wcs(): return load("wcs_latest.json")

# ── Signal layer endpoints (Day 4 + 5) ───────────────────────────────────────

@app.get("/api/curve-history")
async def get_curve_history():
    p = DATA_DIR / "curve_history.json"
    if not p.exists():
        return []
    return json.loads(p.read_text())

@app.get("/api/curve")
async def get_curve():
    p = DATA_DIR / "curve_latest.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail="Run curve_fetcher.py first")
    return json.loads(p.read_text())

@app.get("/api/geo-score")
async def get_geo_score():
    p = DATA_DIR / "geo_score_latest.json"
    if not p.exists():
        import sys, os
        sys.path.insert(0, os.path.dirname(__file__))
        from geo_scorer import run as geo_run
        return geo_run()
    return json.loads(p.read_text())

@app.get("/api/inventory-signals")
def get_inventory_signals():
    path = DATA_DIR / "inventory_signals.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return run_inventory_signals()

@app.get("/api/crack-signals")
def get_crack_signals():
    path = DATA_DIR / "crack_signal_layer.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return run_crack_signals()

@app.get("/api/signals-summary")
def get_signals_summary():
    """Single endpoint — both signal layer composites for the frontend."""
    inv   = json.loads((DATA_DIR / "inventory_signals.json").read_text()) \
            if (DATA_DIR / "inventory_signals.json").exists() else {}
    crack = json.loads((DATA_DIR / "crack_signal_layer.json").read_text()) \
            if (DATA_DIR / "crack_signal_layer.json").exists() else {}
    return {
        "inventory":          inv.get("composite", {}),
        "crack":              crack.get("composite", {}),
        "inventory_signals":  inv.get("signals", {}),
        "crack_signals":      crack.get("signals", {}),
        "generated_at":       inv.get("generated_at", ""),
    }

# ── Aggregate + status ────────────────────────────────────────────────────────

@app.get("/api/all")
def all_data():
    return {
        "composite":  load("nci_composite.json"),
        "inventory":  load("inventory_signals.json"),
        "crack":      load("crack_signals.json"),
        "futures":    load("futures_latest.json"),
        "fred":       load("fred_latest.json"),
        "gie":        load("gie_latest.json"),
        "weather":    load("weather_latest.json"),
        "cftc":       load("cftc_latest.json"),
        "news":       load("news_signals.json"),
        "server_time": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

@app.get("/api/status")
def status():
    files = {}
    for f in ["nci_composite.json", "inventory_signals.json", "crack_signals.json",
              "crack_signal_layer.json", "futures_latest.json", "fred_latest.json",
              "gie_latest.json", "weather_latest.json", "cftc_latest.json"]:
        p = DATA_DIR / f
        files[f] = {
            "exists":   p.exists(),
            "modified": datetime.fromtimestamp(p.stat().st_mtime).strftime("%H:%M:%S")
                        if p.exists() else None,
        }
    return {
        "status":      "running",
        "server_time": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "jobs":        [{"id": j.id, "next_run": str(j.next_run_time)}
                        for j in scheduler.get_jobs()],
        "files":       files,
    }

@app.get("/")
def root():
    return {"message": "Energy Markets Dashboard API", "docs": "/docs"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=False)

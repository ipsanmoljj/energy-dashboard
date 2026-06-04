cat > /workspaces/energy-dashboard/backend/geo_scorer.py << 'PYEOF'
"""
geo_scorer.py — Geopolitical Risk Scorer
=========================================
Implements the 3-dimension scoring framework from the dashboard design:

  1. SUPPLY AT RISK (mbd)        Weight: 40%
  2. GLOBAL SPARE CAPACITY (mbd) Weight: 40%
  3. DURATION UNCERTAINTY        Weight: 20%

Total composite score → implied price risk premium:
  2–4 pts  = $2–5/bbl
  5–6 pts  = $5–10/bbl
  8–9 pts  = $15–25/bbl
  10 pts   = $25–50/bbl

Events are stored in backend/data/geo_events.json (manually curated)
and auto-supplemented by signals from news_fetcher.py geo_alerts.

Output: backend/data/geo_score_latest.json
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger("geo_scorer")

ROOT      = Path(__file__).resolve().parent
DATA_DIR  = ROOT / "data"
OUT_FILE  = DATA_DIR / "geo_score_latest.json"
EVENTS_FILE = DATA_DIR / "geo_events.json"

# ── Scoring tables (from framework doc) ──────────────────────────────────────

def score_supply_at_risk(mbd: float) -> int:
    """Supply at risk in mbd → 2–10 pts (weight 40%)"""
    if mbd < 0.5:  return 2
    if mbd < 1.0:  return 4
    if mbd < 2.0:  return 6
    if mbd < 4.0:  return 8
    return 10

def score_spare_capacity(mbd: float) -> int:
    """Global spare capacity in mbd → 2–10 pts (weight 40%)"""
    if mbd > 4.0:  return 2   # cushioned
    if mbd > 2.0:  return 5   # moderate risk
    if mbd > 1.0:  return 8   # vulnerable
    return 10                  # critical

def score_duration(category: str) -> int:
    """Duration uncertainty → 2–10 pts (weight 20%)"""
    mapping = {
        "days_weeks":    2,
        "weeks_months":  5,
        "multi_year":    8,
        "structural":    10,
    }
    return mapping.get(category, 5)

def composite_score(supply_pts, capacity_pts, duration_pts) -> float:
    return round(supply_pts * 0.4 + capacity_pts * 0.4 + duration_pts * 0.2, 2)

def implied_premium(score: float) -> dict:
    if score <= 4:
        return {"low": 2,  "high": 5,  "label": "LOW",      "color": "NEUTRAL"}
    if score <= 6:
        return {"low": 5,  "high": 10, "label": "MODERATE",  "color": "NEUTRAL"}
    if score <= 9:
        return {"low": 15, "high": 25, "label": "ELEVATED",  "color": "BEARISH"}
    return     {"low": 25, "high": 50, "label": "CRITICAL",  "color": "BEARISH"}

def risk_signal(score: float) -> str:
    if score <= 3:  return "LOW_RISK"
    if score <= 5:  return "MODERATE_RISK"
    if score <= 7:  return "ELEVATED_RISK"
    if score <= 9:  return "HIGH_RISK"
    return "CRITICAL_RISK"

# ── Default seed events ───────────────────────────────────────────────────────
# These are the baseline events always present; curated from historical framework.
# Edit geo_events.json to add/remove/update live events.

DEFAULT_EVENTS = [
    {
        "id":           "houthi_red_sea",
        "name":         "Houthi Red Sea Campaign",
        "region":       "Middle East / Red Sea",
        "chokepoint":   "Bab el-Mandeb",
        "supply_at_risk_mbd": 1.5,
        "duration":     "multi_year",
        "active":       True,
        "notes":        "Rerouting via Cape adds 10–15 days; freight +200-400%",
        "start_date":   "2023-11-01",
    },
    {
        "id":           "russia_ukraine",
        "name":         "Russia–Ukraine War",
        "region":       "Eastern Europe",
        "chokepoint":   "Baltic / Black Sea / Bosphorus",
        "supply_at_risk_mbd": 1.0,
        "duration":     "multi_year",
        "active":       True,
        "notes":        "Russian barrels rerouted to India/China; EU embargo active",
        "start_date":   "2022-02-24",
    },
    {
        "id":           "iran_sanctions",
        "name":         "Iran Nuclear Sanctions",
        "region":       "Persian Gulf",
        "chokepoint":   "Strait of Hormuz",
        "supply_at_risk_mbd": 0.8,
        "duration":     "structural",
        "active":       True,
        "notes":        "Iranian exports ~3.2mbd despite sanctions; China absorbing",
        "start_date":   "2018-05-01",
    },
    {
        "id":           "libya_instability",
        "name":         "Libya Field Disruptions",
        "region":       "North Africa",
        "chokepoint":   None,
        "supply_at_risk_mbd": 0.4,
        "duration":     "weeks_months",
        "active":       True,
        "notes":        "Rival faction control of terminals; chronic 0.3–0.6 mbd risk",
        "start_date":   "2024-01-01",
    },
    {
        "id":           "nigeria_militant",
        "name":         "Nigeria Niger Delta Disruptions",
        "region":       "West Africa",
        "chokepoint":   None,
        "supply_at_risk_mbd": 0.3,
        "duration":     "structural",
        "active":       True,
        "notes":        "Pipeline vandalism; force majeure declarations periodic",
        "start_date":   "2022-01-01",
    },
]

CHOKEPOINT_DATA = {
    "Strait of Hormuz":   {"flow_mbd": 17.0, "bypass_mbd": 3.5,  "risk_level": "CRITICAL"},
    "Bab el-Mandeb":      {"flow_mbd":  4.5, "bypass_mbd": None, "risk_level": "HIGH"},
    "Suez Canal":         {"flow_mbd":  5.5, "bypass_mbd": 1.5,  "risk_level": "HIGH"},
    "Strait of Malacca":  {"flow_mbd": 16.0, "bypass_mbd": None, "risk_level": "MODERATE"},
    "Bosphorus":          {"flow_mbd":  2.5, "bypass_mbd": None, "risk_level": "MODERATE"},
    "Danish Straits":     {"flow_mbd":  2.0, "bypass_mbd": None, "risk_level": "MODERATE"},
    "Cape of Good Hope":  {"flow_mbd":  0.0, "bypass_mbd": None, "risk_level": "LOW"},
}

# ── Spare capacity (read from EIA/OPEC data if available, else use estimate) ─

def get_spare_capacity(data_dir: Path) -> float:
    """Try to read spare capacity from existing data files; fallback to estimate."""
    # Try futures/composite data for any spare_capacity field
    for fname in ["futures_latest.json", "eia_latest.json", "signals_merged.json"]:
        fp = data_dir / fname
        if fp.exists():
            try:
                d = json.loads(fp.read_text())
                # Look for spare capacity in nested structure
                sc = (d.get("spare_capacity") or
                      d.get("opec", {}).get("spare_capacity") or
                      d.get("meta", {}).get("spare_capacity"))
                if sc and isinstance(sc, (int, float)):
                    return float(sc)
            except Exception:
                pass
    # Current estimate (mid-2025): ~4.5 mbd OPEC+ spare capacity
    return 4.5

# ── Load / save events ────────────────────────────────────────────────────────

def load_events(data_dir: Path) -> list:
    """Load events from geo_events.json; seed with defaults if missing."""
    fp = data_dir / "geo_events.json"
    if not fp.exists():
        fp.write_text(json.dumps(DEFAULT_EVENTS, indent=2))
        log.info("Seeded geo_events.json with %d default events", len(DEFAULT_EVENTS))
    try:
        events = json.loads(fp.read_text())
        # Merge any defaults not yet in the file (by id)
        existing_ids = {e["id"] for e in events}
        for d in DEFAULT_EVENTS:
            if d["id"] not in existing_ids:
                events.append(d)
                log.info("Added missing default event: %s", d["id"])
        return events
    except Exception as e:
        log.warning("Could not load geo_events.json: %s — using defaults", e)
        return DEFAULT_EVENTS

# ── News geo alerts integration ───────────────────────────────────────────────

def load_news_geo_alerts(data_dir: Path) -> list:
    """Pull geo_alerts from news_fetcher output to supplement scored events."""
    alerts = []
    for fname in ["news_latest.json", "signals_merged.json"]:
        fp = data_dir / fname
        if not fp.exists():
            continue
        try:
            d = json.loads(fp.read_text())
            raw = (d.get("geo_alerts") or
                   d.get("news", {}).get("geo_alerts") or
                   d.get("summary", {}).get("geo_alerts") or [])
            if isinstance(raw, list):
                alerts.extend(raw)
            elif isinstance(raw, int):
                pass  # it's a count, not a list — skip
        except Exception:
            pass
    return alerts

# ── Core scorer ───────────────────────────────────────────────────────────────

def score_event(event: dict, spare_capacity_mbd: float) -> dict:
    """Score a single geopolitical event."""
    supply_pts   = score_supply_at_risk(event.get("supply_at_risk_mbd", 0))
    capacity_pts = score_spare_capacity(spare_capacity_mbd)
    duration_pts = score_duration(event.get("duration", "weeks_months"))
    comp         = composite_score(supply_pts, capacity_pts, duration_pts)
    premium      = implied_premium(comp)
    signal       = risk_signal(comp)

    return {
        "id":              event.get("id"),
        "name":            event.get("name"),
        "region":          event.get("region"),
        "chokepoint":      event.get("chokepoint"),
        "supply_at_risk_mbd": event.get("supply_at_risk_mbd", 0),
        "duration":        event.get("duration"),
        "notes":           event.get("notes", ""),
        "start_date":      event.get("start_date"),
        "active":          event.get("active", True),
        "scoring": {
            "supply_pts":    supply_pts,
            "capacity_pts":  capacity_pts,
            "duration_pts":  duration_pts,
            "composite":     comp,
        },
        "implied_premium": premium,
        "signal":          signal,
    }

def aggregate_score(scored_events: list) -> dict:
    """
    Aggregate all active event scores into a single composite geo risk score.
    Method: take the max score (dominant event) + 20% of sum of remaining events.
    This avoids double-counting while capturing multi-event environment.
    """
    if not scored_events:
        return {"composite": 0.0, "signal": "NO_EVENTS", "label": "No active events"}

    scores = [e["scoring"]["composite"] for e in scored_events]
    scores_sorted = sorted(scores, reverse=True)
    dominant = scores_sorted[0]
    remaining = scores_sorted[1:]
    aggregate = round(dominant + 0.2 * sum(remaining), 2)
    aggregate = min(aggregate, 10.0)  # cap at 10

    return {
        "composite":       aggregate,
        "dominant_score":  dominant,
        "event_count":     len(scored_events),
        "signal":          risk_signal(aggregate),
        "label":           implied_premium(aggregate)["label"],
        "implied_premium": implied_premium(aggregate),
        # Map to -10/+10 for composite integration:
        # Geo risk is always bearish-leaning (supply disruption = bullish price, bearish supply)
        # Score of 10 = +5 on composite (strong bullish price signal from disruption)
        "composite_signal_score": round((aggregate / 10) * 5, 2),
    }

# ── Main run ──────────────────────────────────────────────────────────────────

def run():
    DATA_DIR.mkdir(exist_ok=True)
    spare_cap     = get_spare_capacity(DATA_DIR)
    events        = load_events(DATA_DIR)
    active_events = [e for e in events if e.get("active", True)]
    news_alerts   = load_news_geo_alerts(DATA_DIR)

    scored = [score_event(e, spare_cap) for e in active_events]
    scored.sort(key=lambda x: x["scoring"]["composite"], reverse=True)

    agg = aggregate_score(scored)

    # Chokepoint reference table with active event flags
    active_chokepoints = {e.get("chokepoint") for e in active_events if e.get("chokepoint")}
    chokepoints = []
    for name, data in CHOKEPOINT_DATA.items():
        chokepoints.append({
            "name":          name,
            "flow_mbd":      data["flow_mbd"],
            "bypass_mbd":    data["bypass_mbd"],
            "risk_level":    data["risk_level"],
            "active_threat": name in active_chokepoints,
        })

    output = {
        "fetcher":      "geo_scorer",
        "fetched_at":   datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "spare_capacity_used_mbd": spare_cap,
        "aggregate":    agg,
        "active_events": scored,
        "all_event_count": len(events),
        "active_event_count": len(active_events),
        "news_geo_alerts": len(news_alerts),
        "chokepoints":  chokepoints,
        "scoring_legend": {
            "supply_weight":   0.40,
            "capacity_weight": 0.40,
            "duration_weight": 0.20,
            "score_range":     "0–10",
            "composite_signal_range": "0–+5 (bullish price pressure from disruption)",
        },
    }

    OUT_FILE.write_text(json.dumps(output, indent=2))
    log.info("Geo score: %.2f [%s] — %d active events | spare cap %.1f mbd",
             agg["composite"], agg["signal"], len(active_events), spare_cap)
    return output

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")
    run()
PYEOF

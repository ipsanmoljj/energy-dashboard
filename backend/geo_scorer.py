import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("geo_scorer")

ROOT        = Path(__file__).resolve().parent
DATA_DIR    = ROOT / "data"
OUT_FILE    = DATA_DIR / "geo_score_latest.json"

def score_supply_at_risk(mbd):
    if mbd < 0.5:  return 2
    if mbd < 1.0:  return 4
    if mbd < 2.0:  return 6
    if mbd < 4.0:  return 8
    return 10

def score_spare_capacity(mbd):
    if mbd > 4.0:  return 2
    if mbd > 2.0:  return 5
    if mbd > 1.0:  return 8
    return 10

def score_duration(category):
    return {"days_weeks":2,"weeks_months":5,"multi_year":8,"structural":10}.get(category,5)

def composite_score(s,c,d):
    return round(s*0.4 + c*0.4 + d*0.2, 2)

def implied_premium(score):
    if score<=4:  return {"low":2, "high":5,  "label":"LOW",      "color":"NEUTRAL"}
    if score<=6:  return {"low":5, "high":10, "label":"MODERATE", "color":"NEUTRAL"}
    if score<=9:  return {"low":15,"high":25, "label":"ELEVATED", "color":"BEARISH"}
    return             {"low":25,"high":50, "label":"CRITICAL", "color":"BEARISH"}

def risk_signal(score):
    if score<=3:  return "LOW_RISK"
    if score<=5:  return "MODERATE_RISK"
    if score<=7:  return "ELEVATED_RISK"
    if score<=9:  return "HIGH_RISK"
    return "CRITICAL_RISK"

DEFAULT_EVENTS = [
    {"id":"houthi_red_sea","name":"Houthi Red Sea Campaign","region":"Middle East / Red Sea","chokepoint":"Bab el-Mandeb","supply_at_risk_mbd":1.5,"duration":"multi_year","active":True,"notes":"Rerouting via Cape adds 10-15 days; freight +200-400%","start_date":"2023-11-01"},
    {"id":"russia_ukraine","name":"Russia-Ukraine War","region":"Eastern Europe","chokepoint":"Baltic / Black Sea / Bosphorus","supply_at_risk_mbd":1.0,"duration":"multi_year","active":True,"notes":"Russian barrels rerouted to India/China; EU embargo active","start_date":"2022-02-24"},
    {"id":"iran_sanctions","name":"Iran Nuclear Sanctions","region":"Persian Gulf","chokepoint":"Strait of Hormuz","supply_at_risk_mbd":0.8,"duration":"structural","active":True,"notes":"Iranian exports ~3.2mbd despite sanctions; China absorbing","start_date":"2018-05-01"},
    {"id":"libya_instability","name":"Libya Field Disruptions","region":"North Africa","chokepoint":None,"supply_at_risk_mbd":0.4,"duration":"weeks_months","active":True,"notes":"Rival faction control of terminals; chronic 0.3-0.6 mbd risk","start_date":"2024-01-01"},
    {"id":"nigeria_militant","name":"Nigeria Niger Delta Disruptions","region":"West Africa","chokepoint":None,"supply_at_risk_mbd":0.3,"duration":"structural","active":True,"notes":"Pipeline vandalism; force majeure declarations periodic","start_date":"2022-01-01"},
]

CHOKEPOINT_DATA = {
    "Strait of Hormuz":  {"flow_mbd":17.0,"bypass_mbd":3.5, "risk_level":"CRITICAL"},
    "Bab el-Mandeb":     {"flow_mbd":4.5, "bypass_mbd":None,"risk_level":"HIGH"},
    "Suez Canal":        {"flow_mbd":5.5, "bypass_mbd":1.5, "risk_level":"HIGH"},
    "Strait of Malacca": {"flow_mbd":16.0,"bypass_mbd":None,"risk_level":"MODERATE"},
    "Bosphorus":         {"flow_mbd":2.5, "bypass_mbd":None,"risk_level":"MODERATE"},
    "Danish Straits":    {"flow_mbd":2.0, "bypass_mbd":None,"risk_level":"MODERATE"},
    "Cape of Good Hope": {"flow_mbd":0.0, "bypass_mbd":None,"risk_level":"LOW"},
}

def get_spare_capacity(data_dir):
    for fname in ["futures_latest.json","eia_latest.json","signals_merged.json"]:
        fp = data_dir / fname
        if fp.exists():
            try:
                d = json.loads(fp.read_text())
                sc = d.get("spare_capacity") or d.get("opec",{}).get("spare_capacity")
                if sc and isinstance(sc,(int,float)): return float(sc)
            except: pass
    return 4.5

def load_events(data_dir):
    fp = data_dir / "geo_events.json"
    if not fp.exists():
        fp.write_text(json.dumps(DEFAULT_EVENTS,indent=2))
    try:
        events = json.loads(fp.read_text())
        existing_ids = {e["id"] for e in events}
        for d in DEFAULT_EVENTS:
            if d["id"] not in existing_ids:
                events.append(d)
        return events
    except:
        return DEFAULT_EVENTS

def load_news_geo_alerts(data_dir):
    alerts = []
    for fname in ["news_latest.json","signals_merged.json"]:
        fp = data_dir / fname
        if not fp.exists(): continue
        try:
            d = json.loads(fp.read_text())
            raw = d.get("geo_alerts") or d.get("news",{}).get("geo_alerts") or []
            if isinstance(raw,list): alerts.extend(raw)
        except: pass
    return alerts

def score_event(event, spare_capacity_mbd):
    s = score_supply_at_risk(event.get("supply_at_risk_mbd",0))
    c = score_spare_capacity(spare_capacity_mbd)
    d = score_duration(event.get("duration","weeks_months"))
    comp = composite_score(s,c,d)
    return {
        "id":event.get("id"),"name":event.get("name"),"region":event.get("region"),
        "chokepoint":event.get("chokepoint"),"supply_at_risk_mbd":event.get("supply_at_risk_mbd",0),
        "duration":event.get("duration"),"notes":event.get("notes",""),
        "start_date":event.get("start_date"),"active":event.get("active",True),
        "scoring":{"supply_pts":s,"capacity_pts":c,"duration_pts":d,"composite":comp},
        "implied_premium":implied_premium(comp),"signal":risk_signal(comp),
    }

def aggregate_score(scored_events):
    if not scored_events:
        return {"composite":0.0,"signal":"NO_EVENTS","label":"No active events","composite_signal_score":0.0,"implied_premium":{"low":0,"high":0,"label":"NONE","color":"NEUTRAL"}}
    scores = sorted([e["scoring"]["composite"] for e in scored_events],reverse=True)
    agg = min(round(scores[0] + 0.2*sum(scores[1:]),2), 10.0)
    return {
        "composite":agg,"dominant_score":scores[0],"event_count":len(scored_events),
        "signal":risk_signal(agg),"label":implied_premium(agg)["label"],
        "implied_premium":implied_premium(agg),
        "composite_signal_score":round((agg/10)*5,2),
    }

def run():
    DATA_DIR.mkdir(exist_ok=True)
    spare_cap = get_spare_capacity(DATA_DIR)
    events    = load_events(DATA_DIR)
    active    = [e for e in events if e.get("active",True)]
    alerts    = load_news_geo_alerts(DATA_DIR)
    scored    = sorted([score_event(e,spare_cap) for e in active],key=lambda x:x["scoring"]["composite"],reverse=True)
    agg       = aggregate_score(scored)
    active_chokepoints = {e.get("chokepoint") for e in active if e.get("chokepoint")}
    chokepoints = [{"name":n,"flow_mbd":d["flow_mbd"],"bypass_mbd":d["bypass_mbd"],"risk_level":d["risk_level"],"active_threat":n in active_chokepoints} for n,d in CHOKEPOINT_DATA.items()]
    output = {
        "fetcher":"geo_scorer",
        "fetched_at":datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "spare_capacity_used_mbd":spare_cap,"aggregate":agg,
        "active_events":scored,"all_event_count":len(events),
        "active_event_count":len(active),"news_geo_alerts":len(alerts),
        "chokepoints":chokepoints,
    }
    OUT_FILE.write_text(json.dumps(output,indent=2))
    print("Geo score: {} [{}] — {} active events | spare cap {} mbd".format(agg['composite'], agg['signal'], len(active), spare_cap))
    return output

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()

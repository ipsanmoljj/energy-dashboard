"""
news_fetcher.py
---------------
Day 7 — Oil Market News Sentiment Pipeline

Architecture:
  Layer 1 → RSS fetch from 4 sources (FinancialJuice, OilPrice, EIA, Reuters)
  Layer 2 → Relevance filter (350+ oil-specific terms)
  Layer 3 → Causal classification (which NCI layer does this affect?)
  Layer 4 → Sentiment scoring (LM financial dictionary + oil-specific overrides)
  Layer 5 → Geopolitical risk scorer (from OilMacroTrading book framework)
  Layer 6 → News score (-10 to +10) with time decay

Saves to: backend/data/news_signals.json

Usage:
  python backend/fetchers/news_fetcher.py
  python backend/fetchers/news_fetcher.py --hours 8   # look back 8 hours
"""

import argparse
import json
import logging
import ssl
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import feedparser
import pysentiment2 as ps

# ── Config ────────────────────────────────────────────────────────────────────

OUTPUT_PATH = Path(__file__).resolve().parents[1] / "data" / "news_signals.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── RSS Sources ───────────────────────────────────────────────────────────────

RSS_SOURCES = [
    {
        "name":     "FinancialJuice",
        "url": "https://www.financialjuice.com/feed.axd?category=oil",
        "priority": 4,   # highest — fastest breaking news
        "note":     "Real-time squawk headlines for day traders",
    },
    {
        "name":     "OilPrice.com",
        "url":      "https://oilprice.com/rss/main",
        "priority": 3,
        "note":     "Pure oil/energy news and analysis",
    },
    {
        "name":     "EIA Today in Energy",
        "url":      "https://www.eia.gov/rss/todayinenergy.xml",
        "priority": 3,
        "note":     "Official EIA data releases and analysis",
    },
    {
        "name":     "Reuters Commodities",
        "url": "https://feeds.reuters.com/reuters/energy",
        "priority": 2,
        "note":     "Professional energy/commodities coverage",
    },
]

# ── Relevance Filter (350+ terms) ─────────────────────────────────────────────

OIL_TERMS = {
    # Crude benchmarks & grades
    "crude","brent","wti","dubai","oman","urals","espo",
    "bonny light","forties","oseberg","ekofisk","troll",
    "arab light","arab heavy","arab medium","basrah",
    "kirkuk","forcados","qua iboe","cabinda","tengiz",
    "western canadian select","wcs","dilbit","syncrude",
    "mars","maya","merey","iranian heavy","iranian light",
    "murban","upper zakum","das blend",

    # Organizations & institutions
    "opec","opec+","oecd","eia","iea","jmmc","jodi",
    "saudi aramco","aramco","adnoc","nioc","pdvsa",
    "pemex","inoc","somo","knpc","qatarenergy",
    "rosneft","gazprom","lukoil","equinor","exxonmobil",
    "exxon","shell","bp","chevron","totalenergies","total",
    "eni","repsol","petrobras","cnooc","sinopec","cnpc",
    "slb","schlumberger","halliburton","baker hughes",
    "irgc","cpc","druzhba","iea omr","opec momr",

    # Countries & regions (as producers)
    "saudi arabia","saudi","russia","iran","iraq","uae",
    "kuwait","venezuela","nigeria","libya","algeria",
    "angola","kazakhstan","azerbaijan","norway","canada",
    "permian","eagle ford","bakken","north sea","gulf of mexico",
    "persian gulf","arabian gulf","west africa","north africa",
    "middle east","caspian","arctic",

    # Chokepoints & logistics
    "hormuz","strait of hormuz","suez","suez canal","sumed",
    "bab el-mandeb","malacca","bosphorus","panama canal",
    "cape of good hope","red sea","black sea","baltic",
    "druzhba pipeline","keystone","trans mountain",
    "colonial pipeline","seaway","cactus","epic pipeline",

    # Storage & inventory
    "cushing","ara","amsterdam","rotterdam","antwerp",
    "fujairah","singapore","inventory","inventories",
    "stockpile","stocks","storage","spr",
    "strategic petroleum reserve","strategic reserve",
    "floating storage","onshore storage","tank levels",
    "days cover","forward cover","draw","drawdown",
    "build","inventory build","stock build",
    "inventory draw","stock draw","deficit","surplus",
    "above consensus","below consensus","beat forecast",
    "miss forecast","surprise draw","surprise build",
    "5-year average","five year average","seasonal average",

    # Supply & production
    "production","output","supply","upstream",
    "rig count","drilled","completion",
    "duc wells","drilled uncompleted","fid",
    "final investment decision","capex","capital expenditure",
    "decline rate","depletion","plateau",
    "shale","tight oil","fracking","hydraulic fracturing",
    "deepwater","offshore","onshore","oil sands",
    "spare capacity","swing producer","quota",
    "production cut","output cut","voluntary cut",
    "production increase","output hike","ramp up",
    "curtailment","shut-in","force majeure",
    "outage","disruption","supply disruption",
    "pipeline outage","refinery outage","field outage",
    "tanker attack","pipeline attack","infrastructure attack",

    # Refining & products
    "refinery","refining","downstream","crack spread",
    "3-2-1 crack","refinery margin","gross margin",
    "refinery utilisation","refinery utilization","throughput",
    "turnaround","maintenance","planned outage",
    "nelson complexity","hydrocracker","fcc",
    "fluid catalytic cracker","coker","hydrotreater",
    "gasoline","petrol","rbob","mogas",
    "diesel","gasoil","ulsd","heating oil",
    "jet fuel","kerosene","aviation fuel",
    "naphtha","fuel oil","hsfo","vlsfo","bunker",
    "imo 2020","sulphur cap","low sulphur",
    "product export","product import","product ban",

    # Demand
    "demand","consumption","imports","exports",
    "chinese demand","china imports","china spr",
    "indian demand","india imports",
    "emerging market demand","em demand",
    "road transport","trucking","aviation demand",
    "marine bunkers","bunkering",
    "petrochemical","naphtha cracker","ethylene",
    "ev displacement","electric vehicle","bev",
    "demand destruction","demand weakness","demand recovery",
    "driving season","heating season","cooling season",
    "hdd","cdd","heating degree","cooling degree",

    # Pricing & benchmarks
    "oil price","crude price","energy price",
    "dated brent","platts","argus","ice brent",
    "nymex wti","price cap","official selling price","osp",
    "backwardation","contango","time spread",
    "forward curve","futures curve",
    "brent-wti spread","light-heavy spread",
    "sweet-sour spread","quality differential",
    "price rally","price surge","price spike",
    "price decline","price fall","price crash",
    "price collapse","selloff","sell-off",

    # Freight & tankers
    "tanker","vlcc","suezmax","aframax","panamax",
    "worldscale","freight rate","td3c","baltic exchange",
    "clarksons","fearnleys","shipping","vessel",
    "shadow fleet","dark fleet","sanctioned tanker",
    "seized tanker","tanker seizure",
    "kpler","vortexa","ais tracking",

    # Geopolitical & sanctions
    "sanctions","embargo","export ban","import ban",
    "secondary sanctions","g7",
    "war","conflict","attack","strike",
    "houthi","iran nuclear","jcpoa",
    "ukraine","russia ukraine","nato",
    "ceasefire","escalation","de-escalation",
    "geopolitical","geopolitical risk","risk premium",
    "seized","blockade","maritime security",

    # Macro & financial
    "dollar","dxy","usd","dollar index",
    "fed","federal reserve","interest rate","sofr",
    "inflation","cpi","ppi","gdp",
    "recession","slowdown","contraction",
    "china gdp","china pmi","manufacturing pmi",
    "global growth","demand outlook",
    "cftc","speculative position","managed money",
    "net long","net short","short covering",

    # Data releases
    "weekly petroleum","petroleum status report",
    "steo","short-term energy outlook",
    "oil market report","omr","momr",
    "drilling productivity report",
    "api report","api data","api inventory",
    "eia report","eia data","eia inventory",
    "iea report","opec report",
    "cot report","commitment of traders",
    "jodi data","euroilstock",

    # Market signals
    "bullish","bearish","rally","selloff",
    "risk premium","war premium","geopolitical premium",
    "oversold","overbought","breakout","breakdown",
}

# ── Oil-specific sentiment overrides ──────────────────────────────────────────
# LM dictionary misses many oil-specific directional terms
# These override or supplement LM scores with domain knowledge

OIL_OVERRIDES = {
    # Strongly BULLISH supply signals
    "supply disruption":   +3.0,
    "force majeure":       +3.0,
    "pipeline attack":     +3.0,
    "refinery fire":       +3.0,
    "field outage":        +2.5,
    "production cut":      +2.5,
    "output cut":          +2.5,
    "voluntary cut":       +2.5,
    "surprise cut":        +3.0,
    "blockade":            +3.0,
    "seizure":             +2.5,
    "seized":              +2.5,
    "sanctions tightened": +2.5,
    "disruption":          +2.0,
    "outage":              +2.0,
    "cut":                 +1.5,
    "drawdown":            +2.0,
    "draw":                +1.5,
    "below 5-year":        +2.0,
    "below average":       +1.5,
    "below consensus":     +2.0,
    "surprise draw":       +3.0,
    "deficit":             +2.0,
    "tightening":          +1.5,
    "record imports":      +2.0,
    "above consensus":     +1.5,
    "spare capacity low":  +2.5,
    "geopolitical risk":   +1.5,
    "risk premium":        +1.0,
    "backwardation":       +1.5,

    # Strongly BEARISH supply signals
    "inventory build":     -2.5,
    "stock build":         -2.5,
    "surprise build":      -3.0,
    "above consensus":     -1.5,  # when used with builds
    "surplus":             -2.5,
    "glut":                -3.0,
    "oversupply":          -2.5,
    "production increase": -1.5,
    "output hike":         -1.5,
    "ramp up":             -1.0,
    "production rise":     -1.5,
    "spare capacity":      -1.0,  # when spare cap mentioned as ample
    "contango":            -1.5,
    "contango deepens":    -2.5,
    "demand destruction":  -2.5,
    "demand weakness":     -2.0,
    "demand falls":        -2.0,
    "recession":           -2.5,
    "slowdown":            -1.5,
    "ev displacement":     -1.0,
    "floating storage":    -2.0,  # rising floating storage = bearish
    "build":               -1.5,
}

# ── Causal signal taxonomy ────────────────────────────────────────────────────
# Map headlines to which NCI layer they affect

SIGNAL_TAXONOMY = {
    "opec": {
        "keywords": [
            "opec","quota","voluntary cut","compliance","jmmc",
            "saudi output","opec meeting","production decision",
            "opec+ agrees","call on opec","aramco osp"
        ],
        "nci_layer": "inventory",
        "weight":    4,
        "note":      "OPEC decisions most direct supply signal",
    },
    "supply": {
        "keywords": [
            "outage","disruption","force majeure","shut-in",
            "pipeline attack","refinery fire","field outage",
            "production cut","supply disruption","offline"
        ],
        "nci_layer": "inventory",
        "weight":    3,
        "note":      "Physical supply disruptions",
    },
    "geopolitical": {
        "keywords": [
            "hormuz","sanctions","war","attack","seized",
            "conflict","houthi","iran","embargo","blockade",
            "irgc","red sea","maritime","military","strike",
            "ceasefire","escalation","chokepoint"
        ],
        "nci_layer": "geopolitical",
        "weight":    4,
        "note":      "Geopolitical risk premium signals",
    },
    "inventory": {
        "keywords": [
            "inventory","cushing","stockpile","draw","build",
            "eia report","api report","5-year","consensus",
            "oecd stocks","days cover","weekly petroleum",
            "crude stocks","gasoline stocks","distillate"
        ],
        "nci_layer": "inventory",
        "weight":    3,
        "note":      "Weekly EIA/API inventory data signals",
    },
    "demand": {
        "keywords": [
            "demand","imports","consumption","china crude",
            "india imports","aviation","petrochemical","ev",
            "recession","slowdown","gdp","driving season",
            "heating demand","cooling demand","hdd","cdd"
        ],
        "nci_layer": "demand",
        "weight":    2,
        "note":      "Demand-side signals",
    },
    "macro": {
        "keywords": [
            "dollar","dxy","fed rate","interest rate",
            "inflation","gdp","recession","cpi","sofr",
            "federal reserve","rate cut","rate hike"
        ],
        "nci_layer": "macro",
        "weight":    1,
        "note":      "Macro/financial backdrop signals",
    },
    "curve": {
        "keywords": [
            "backwardation","contango","time spread",
            "forward curve","m1-m2","curve structure",
            "prompt premium","deferred discount"
        ],
        "nci_layer": "crack",
        "weight":    2,
        "note":      "Forward curve structure signals",
    },
    "refining": {
        "keywords": [
            "crack spread","refinery margin","utilisation",
            "turnaround","throughput","gasoline demand",
            "diesel demand","product shortage","product tight"
        ],
        "nci_layer": "crack",
        "weight":    2,
        "note":      "Refinery/product market signals",
    },
    "freight": {
        "keywords": [
            "tanker rate","vlcc rate","suezmax","freight spike",
            "worldscale","td3c","shipping cost","rerouting",
            "cape of good hope","longer route"
        ],
        "nci_layer": "inventory",
        "weight":    2,
        "note":      "Freight/logistics cost signals",
    },
}

# ── Geopolitical risk scorer (from OilMacroTrading book) ─────────────────────

GEO_TRIGGER_TERMS = {
    "hormuz","seized","seizure","attack","blockade","irgc",
    "military strike","naval","houthi","red sea closure",
    "pipeline bombed","sanctions imposed","embargo declared",
    "war","conflict escalation","chokepoint closed"
}

def geo_risk_score(headline: str, spare_capacity_mbd: float = 3.5) -> dict | None:
    """
    Geopolitical Risk Score from OilMacroTrading book:
    Score = (supply_at_risk × 0.4) + (spare_cap_factor × 0.4) + (duration × 0.2)

    Outputs implied price risk premium $2-50/bbl
    """
    h = headline.lower()
    if not any(t in h for t in GEO_TRIGGER_TERMS):
        return None

    # Supply at risk — inferred from headline keywords
    if any(t in h for t in ["hormuz","red sea closure","major pipeline"]):
        supply_pts = 8   # 2-4 mbd at risk
    elif any(t in h for t in ["attack","seized","blockade","embargo"]):
        supply_pts = 6   # 1-2 mbd at risk
    elif any(t in h for t in ["sanctions","conflict","war"]):
        supply_pts = 5   # 0.5-1 mbd at risk
    else:
        supply_pts = 4

    # Spare capacity cushion — from live data
    if spare_capacity_mbd > 4:
        spare_pts = 2    # well cushioned
    elif spare_capacity_mbd > 2:
        spare_pts = 5    # moderate risk
    elif spare_capacity_mbd > 1:
        spare_pts = 8    # vulnerable
    else:
        spare_pts = 10   # critical

    # Duration uncertainty — inferred from language
    if any(t in h for t in ["ongoing","indefinite","permanent","structural"]):
        duration_pts = 8
    elif any(t in h for t in ["escalating","worsening","expanding"]):
        duration_pts = 7
    elif any(t in h for t in ["temporary","brief","limited"]):
        duration_pts = 3
    else:
        duration_pts = 5  # unknown = moderate

    composite = (supply_pts * 0.4) + (spare_pts * 0.4) + (duration_pts * 0.2)

    # Map score to price premium
    if composite < 4:   premium = 3
    elif composite < 5: premium = 5
    elif composite < 6: premium = 10
    elif composite < 7: premium = 15
    elif composite < 8: premium = 20
    elif composite < 9: premium = 30
    else:               premium = 50

    return {
        "composite_score":    round(composite, 1),
        "supply_pts":         supply_pts,
        "spare_cap_pts":      spare_pts,
        "duration_pts":       duration_pts,
        "implied_premium_bbl": premium,
        "spare_capacity_mbd": spare_capacity_mbd,
    }

# ── Sentiment scoring ──────────────────────────────────────────────────────────

_lm = None

def get_lm():
    global _lm
    if _lm is None:
        _lm = ps.LM()
    return _lm

def lm_polarity(headline: str) -> float:
    """Loughran-McDonald financial sentiment polarity (-1 to +1)"""
    try:
        lm = get_lm()
        tokens = lm.tokenize(headline)
        score  = lm.get_score(tokens)
        return float(score["Polarity"])
    except Exception:
        return 0.0

def override_score(headline: str) -> tuple[float, list[str]]:
    """Oil-specific override dictionary score and matched phrases"""
    h = headline.lower()
    total = 0.0
    matched = []
    for phrase, val in OIL_OVERRIDES.items():
        if phrase in h:
            total += val
            matched.append(phrase)
    return total, matched

def compute_direction(lm_pol: float, ov: float) -> tuple[str, float]:
    """
    Combine LM polarity and oil overrides into final direction + strength.
    LM polarity is in -1/+1 range so scale up by 3 to weight comparably.
    """
    combined = (lm_pol * 3.0) + ov
    if combined >= 2:   return "BULLISH", min(10.0, combined)
    elif combined <= -2: return "BEARISH", max(-10.0, combined)
    else:               return "NEUTRAL", combined

# ── Relevance & classification ────────────────────────────────────────────────

def is_relevant(headline: str) -> bool:
    h = headline.lower()
    return any(t in h for t in OIL_TERMS)

def classify(headline: str) -> list[dict]:
    h = headline.lower()
    matched = []
    for sig_type, cfg in SIGNAL_TAXONOMY.items():
        if any(kw in h for kw in cfg["keywords"]):
            matched.append({
                "type":      sig_type,
                "nci_layer": cfg["nci_layer"],
                "weight":    cfg["weight"],
            })
    matched.sort(key=lambda x: x["weight"], reverse=True)
    return matched

# ── RSS fetching ──────────────────────────────────────────────────────────────

def fetch_rss(source: dict, lookback_hours: int = 4) -> list[dict]:
    """
    Fetch RSS feed and return raw items within lookback window.
    """
    try:
        feed = feedparser.parse(
            source["url"],
            agent="Mozilla/5.0 EnergyDashboard/1.0 (oil market monitor)",
        )
        if feed.bozo and not feed.entries:
            log.warning("  %s: feed parse error — %s",
                        source["name"], feed.bozo_exception)
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        items  = []

        for entry in feed.entries:
            # Parse timestamp
            published = None
            for attr in ("published_parsed","updated_parsed"):
                t = getattr(entry, attr, None)
                if t:
                    try:
                        published = datetime(*t[:6], tzinfo=timezone.utc)
                        break
                    except Exception:
                        pass

            # If no timestamp, include anyway (FinancialJuice often omits)
            if published and published < cutoff:
                continue

            title   = getattr(entry, "title", "").strip()
            summary = getattr(entry, "summary", "").strip()
            link    = getattr(entry, "link", "")

            if not title:
                continue

            items.append({
                "title":     title,
                "summary":   summary[:300] if summary else "",
                "link":      link,
                "published": published.isoformat() if published else None,
                "source":    source["name"],
                "priority":  source["priority"],
            })

        log.info("  %s: %d items fetched", source["name"], len(items))
        return items

    except Exception as e:
        log.error("  %s: fetch failed — %s", source["name"], e)
        return []

# ── NCI News Score ────────────────────────────────────────────────────────────

def compute_news_score_score(headlines: list[dict],
                           decay_halflife_hours: float = 2.0) -> dict:
    """
    Aggregate scored headlines into one News score (-10 to +10).
    More recent headlines are weighted higher using exponential time decay.
    Only BULLISH and BEARISH headlines contribute — NEUTRAL excluded.
    """
    now = datetime.now(timezone.utc)
    weighted_sum = 0.0
    total_weight = 0.0
    contributors = []

    for h in headlines:
        if h["direction"] == "NEUTRAL":
            continue

        score = h["final_score"]

        # Time decay weight
        if h.get("published"):
            try:
                pub = datetime.fromisoformat(h["published"])
                age_hours = (now - pub).total_seconds() / 3600
                decay = 0.5 ** (age_hours / decay_halflife_hours)
            except Exception:
                decay = 0.5  # unknown age = half weight
        else:
            decay = 0.8  # no timestamp = near-present assumed

        # Signal type weight (higher weight = more market-moving)
        type_weight = h.get("signal_weight", 2)

        w = decay * type_weight
        weighted_sum += score * w
        total_weight += w

        contributors.append({
            "headline": h["headline"][:80],
            "direction": h["direction"],
            "score": round(score, 2),
            "decay": round(decay, 3),
        })

    if total_weight == 0:
        return {
            "score": 0.0, "label": "NO_DATA",
            "contributors": [], "count": 0,
        }

    raw = weighted_sum / total_weight
    nci = round(max(-10, min(10, raw * 2)), 2)  # scale to -10/+10

    if nci >= 6:    label = "STRONGLY_BULLISH"
    elif nci >= 3:  label = "BULLISH"
    elif nci >= 1:  label = "MILD_BULLISH"
    elif nci >= -1: label = "NEUTRAL"
    elif nci >= -3: label = "MILD_BEARISH"
    elif nci >= -6: label = "BEARISH"
    else:           label = "STRONGLY_BEARISH"

    return {
        "score":        nci,
        "label":        label,
        "raw_weighted": round(raw, 3),
        "contributors": sorted(contributors,
                               key=lambda x: abs(x["score"]),
                               reverse=True)[:10],
        "count":        len([h for h in headlines
                             if h["direction"] != "NEUTRAL"]),
    }

# ── Main ──────────────────────────────────────────────────────────────────────

def run(lookback_hours: int = 4,
        spare_capacity_mbd: float = 3.5) -> dict:

    log.info("=" * 60)
    log.info("NEWS SENTIMENT PIPELINE — lookback %dh", lookback_hours)
    log.info("=" * 60)

    # ── Step 1: Fetch all RSS sources ────────────────────────────────────────
    all_raw = []
    for source in RSS_SOURCES:
        log.info("Fetching: %s", source["name"])
        items = fetch_rss(source, lookback_hours)
        all_raw.extend(items)
        time.sleep(0.5)

    log.info("Total raw items: %d", len(all_raw))

    # ── Step 2: Deduplicate by title ─────────────────────────────────────────
    seen   = set()
    unique = []
    for item in all_raw:
        key = item["title"].lower()[:60]
        if key not in seen:
            seen.add(key)
            unique.append(item)

    log.info("After dedup: %d", len(unique))

    # ── Step 3: Relevance filter ─────────────────────────────────────────────
    relevant = [i for i in unique if is_relevant(i["title"])]
    filtered = len(unique) - len(relevant)
    log.info("Oil-relevant: %d (filtered %d non-oil)", len(relevant), filtered)

    # ── Step 4: Score each headline ──────────────────────────────────────────
    scored = []
    for item in relevant:
        title = item["title"]

        # Classify
        signals     = classify(title)
        sig_type    = signals[0]["type"]     if signals else "general"
        nci_layer   = signals[0]["nci_layer"] if signals else "macro"
        sig_weight  = signals[0]["weight"]    if signals else 1

        # Sentiment
        lm_pol              = lm_polarity(title)
        ov, ov_phrases      = override_score(title)
        direction, strength = compute_direction(lm_pol, ov)

        # Geo risk
        geo = geo_risk_score(title, spare_capacity_mbd)

        scored.append({
            "headline":       title,
            "summary":        item.get("summary", ""),
            "link":           item.get("link", ""),
            "source":         item["source"],
            "published":      item.get("published"),
            "relevant":       True,
            "signal_type":    sig_type,
            "nci_layer":      nci_layer,
            "signal_weight":  sig_weight,
            "direction":      direction,
            "final_score":    round(strength, 2),
            "lm_polarity":    round(lm_pol, 3),
            "override_score": round(ov, 2),
            "override_phrases": ov_phrases[:5],
            "geo_risk":       geo,
            "all_signals":    signals,
        })

    # ── Step 5: News score ───────────────────────────────────────────────
    news_score = compute_news_score_score(scored)

    # ── Step 6: Summary stats ────────────────────────────────────────────────
    bullish = [h for h in scored if h["direction"] == "BULLISH"]
    bearish = [h for h in scored if h["direction"] == "BEARISH"]
    neutral = [h for h in scored if h["direction"] == "NEUTRAL"]
    geo_alerts = [h for h in scored if h.get("geo_risk")]

    # Top signal per type
    by_type = {}
    for h in scored:
        t = h["signal_type"]
        if t not in by_type or abs(h["final_score"]) > abs(by_type[t]["final_score"]):
            by_type[t] = h

    output = {
        "fetcher":         "news_fetcher",
        "computed_at":     datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lookback_hours":  lookback_hours,
        "spare_cap_used":  spare_capacity_mbd,

        # NCI score
        "news_score": news_score,

        # Summary
        "summary": {
            "total_fetched":    len(all_raw),
            "after_dedup":      len(unique),
            "oil_relevant":     len(relevant),
            "bullish_count":    len(bullish),
            "bearish_count":    len(bearish),
            "neutral_count":    len(neutral),
            "geo_alerts":       len(geo_alerts),
            "sources_used":     list({h["source"] for h in scored}),
        },

        # Top headlines by direction
        "top_bullish": sorted(bullish, key=lambda x: x["final_score"],
                              reverse=True)[:5],
        "top_bearish": sorted(bearish, key=lambda x: x["final_score"])[:5],

        # Geo risk alerts
        "geo_risk_alerts": [
            {
                "headline": h["headline"],
                "source":   h["source"],
                "geo_risk": h["geo_risk"],
            }
            for h in geo_alerts
        ],

        # Top story per signal type
        "by_signal_type": by_type,

        # All scored headlines
        "all_headlines": scored,
    }

    # ── Save ─────────────────────────────────────────────────────────────────
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    # ── Summary log ──────────────────────────────────────────────────────────
    log.info("─" * 60)
    log.info("NEWS SCORE:  %+.1f / 10  [%s]",
             news_score["score"], news_score["label"])
    log.info("Headlines:  %d relevant | %d bullish | %d bearish | %d neutral",
             len(relevant), len(bullish), len(bearish), len(neutral))
    if geo_alerts:
        log.warning("GEO ALERTS (%d):", len(geo_alerts))
        for g in geo_alerts:
            log.warning("  ⚠ %s → $%d/bbl premium",
                        g["headline"][:60],
                        g["geo_risk"]["implied_premium_bbl"])
    log.info("Top bullish:")
    for h in output["top_bullish"][:3]:
        log.info("  [+%.1f] %s", h["final_score"], h["headline"][:65])
    log.info("Top bearish:")
    for h in output["top_bearish"][:3]:
        log.info("  [%.1f] %s", h["final_score"], h["headline"][:65])
    log.info("Saved → %s", OUTPUT_PATH)
    log.info("─" * 60)

    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Oil Market News Sentiment")
    parser.add_argument("--hours", type=int, default=4,
                        help="Lookback window in hours (default: 4)")
    parser.add_argument("--spare-cap", type=float, default=3.5,
                        help="Current global spare capacity mbd (default: 3.5)")
    args = parser.parse_args()
    run(lookback_hours=args.hours, spare_capacity_mbd=args.spare_cap)

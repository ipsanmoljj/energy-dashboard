"""
backend/fetchers/financialjuice_fetcher.py
-------------------------------------------
Fetches FinancialJuice headlines via Apify actor:
  akash9078/financialjuice-scraper

Writes: backend/data/financialjuice_latest.json

Structure:
  {
    "fetched_at": "...",
    "headlines": [
      {
        "title": "...",        # cleaned (removes "FinancialJuice: " prefix)
        "link": "...",         # full URL to article
        "pubDate": "...",      # ISO datetime
        "guid": "...",         # unique ID
        "oil_relevant": true,  # filtered for energy/macro relevance
        "sentiment": "BULLISH" | "BEARISH" | "NEUTRAL"
      }
    ],
    "oil_headlines": [...],    # only oil/energy relevant
    "total": 50,
    "oil_count": 12
  }

Add APIFY_TOKEN to your environment:
  export APIFY_TOKEN=ABCg8rYK6nmM6BOrlz84ZvFvclI2S12PADP3
Or hardcode it below (not recommended for git repos).
"""

import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

BASE      = Path(__file__).resolve().parent.parent
DATA_DIR  = BASE / "data"
OUT       = DATA_DIR / "financialjuice_latest.json"

APIFY_TOKEN  = os.environ.get("APIFY_TOKEN", "apify_api_ABCg8rYK6nmM6BOrlz84ZvFvclI2S12PADP3")   # set via env var
ACTOR_ID     = "akash9078~financialjuice-scraper"
APIFY_URL = f"https://api.apify.com/v2/acts/{ACTOR_ID}/run-sync-get-dataset-items?token={APIFY_TOKEN}"

# ── Oil/energy/macro keyword filter ──────────────────────────────────────────
OIL_KEYWORDS = [
    # crude / products
    "oil", "crude", "brent", "wti", "opec", "barrel", "petroleum",
    "gasoline", "diesel", "refin", "distillate", "naphtha", "gasoil",
    "fuel", "energy", "lng", "natural gas", "henry hub",
    # supply/demand
    "inventory", "stockpile", "eia", "iea", "supply", "demand",
    "production", "output", "barrel", "tanker", "pipeline",
    # macro / geo relevant to oil
    "fed", "dollar", "dxy", "inflation", "rate", "sanctions",
    "iran", "russia", "saudi", "opec", "venezuela", "iraq",
    "hormuz", "houthi", "red sea", "ukraine", "china demand",
    "recession", "gdp", "pmi",
    # shipping / freight
    "shipping", "freight", "vlcc", "suezmax", "baltic",
]

# ── Sentiment keywords ────────────────────────────────────────────────────────
BULLISH_WORDS = [
    "rises", "surge", "jump", "rally", "gain", "higher", "up",
    "strong", "bullish", "supply cut", "output cut", "draw",
    "tight", "deficit", "shortage", "disruption", "sanctions",
    "geopolit", "attack", "conflict", "war", "escalat",
]
BEARISH_WORDS = [
    "falls", "drop", "decline", "lower", "down", "weak", "bearish",
    "supply increase", "output rise", "build", "surplus", "glut",
    "recession", "demand weak", "slowdown", "ceasefire", "deal",
    "increase output", "raise output",
]


def _clean_title(title: str) -> str:
    """Remove 'FinancialJuice: ' prefix."""
    if title.startswith("FinancialJuice: "):
        return title[len("FinancialJuice: "):]
    return title


def _is_oil_relevant(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in OIL_KEYWORDS)


def _sentiment(title: str) -> str:
    t = title.lower()
    bull = sum(1 for w in BULLISH_WORDS if w in t)
    bear = sum(1 for w in BEARISH_WORDS if w in t)
    if bull > bear:   return "BULLISH"
    if bear > bull:   return "BEARISH"
    return "NEUTRAL"


def _time_ago(iso: str) -> str:
    """Human-readable time ago string."""
    try:
        dt  = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = int((now - dt).total_seconds())
        if diff < 60:    return f"{diff}s ago"
        if diff < 3600:  return f"{diff//60}m ago"
        if diff < 86400: return f"{diff//3600}h ago"
        return f"{diff//86400}d ago"
    except:
        return ""


def fetch() -> list:
    """Call Apify actor and return raw items."""
    if not APIFY_TOKEN:
        print("[financialjuice] No APIFY_TOKEN set — skipping")
        return []

    req = urllib.request.Request(
        APIFY_URL,
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"[financialjuice] HTTP {e.code}: {e.reason}")
        return []
    except Exception as e:
        print(f"[financialjuice] Error: {e}")
        return []


def run():
    print("[financialjuice] Fetching via Apify...")
    items = fetch()

    if not items:
        print("[financialjuice] No items returned")
        # Write empty but valid file so frontend doesn't error
        out = {
            "fetched_at":    datetime.now(timezone.utc).isoformat(),
            "headlines":     [],
            "oil_headlines": [],
            "total":         0,
            "oil_count":     0,
            "error":         "No data — check APIFY_TOKEN",
        }
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(OUT, "w") as f:
            json.dump(out, f, indent=2)
        return out

    headlines = []
    for item in items:
        title_raw = item.get("title", "")
        title     = _clean_title(title_raw)
        link      = item.get("link", "")
        pub_date  = item.get("isoDate") or item.get("pubDate", "")

        headlines.append({
            "title":        title,
            "link":         link,
            "pubDate":      pub_date,
            "time_ago":     _time_ago(pub_date),
            "guid":         item.get("guid", ""),
            "oil_relevant": _is_oil_relevant(title),
            "sentiment":    _sentiment(title),
        })

    oil_headlines = [h for h in headlines if h["oil_relevant"]]

    out = {
        "fetched_at":    datetime.now(timezone.utc).isoformat(),
        "headlines":     headlines,
        "oil_headlines": oil_headlines,
        "total":         len(headlines),
        "oil_count":     len(oil_headlines),
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(out, f, indent=2)

    print(f"[financialjuice] {len(headlines)} total | {len(oil_headlines)} oil-relevant")
    for h in oil_headlines[:5]:
        print(f"  [{h['sentiment']:7s}] {h['title'][:70]}")

    return out


if __name__ == "__main__":
    run()

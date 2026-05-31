"""
Baker Hughes Rig Count Fetcher
Source: AOGR.com (mirrors Baker Hughes weekly)
URL: https://www.aogr.com/web-exclusives/us-rig-count/2026

HTML structure (confirmed from live page):
  tc-tot-curr  → WoW change + total  e.g. "+4 562" or "-2 543" or "0 551"
  rc-oik       → WoW change + oil    e.g. "+4 (429)" or "-1 (410)" or "0 (409)"
  rc-tot-prev  → previous week total e.g. "563"

Stores rolling 10-week history. WoW comes directly from the page.
Signal uses both level (>600 / 350-600 / <350) and WoW direction (±5 threshold).
"""

import os, json, re, requests
from datetime import datetime, timezone, timedelta

OUTPUT_PATH   = os.path.join(os.path.dirname(__file__), "../data/rig_count_latest.json")
AOGR_URL      = "https://www.aogr.com/web-exclusives/us-rig-count/2026"
HEADERS       = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
THRESHOLDS    = {"growing": 600, "flat_lo": 350}
HISTORY_WEEKS = 10
WOW_THRESHOLD = 5


# ── Scraper ───────────────────────────────────────────────────────────────────

def _parse_wow_and_value(text: str):
    """
    Parse strings like:
      "+4 562"    → wow=+4, value=562
      "-2 543"    → wow=-2, value=543
      "0 551"     → wow=0,  value=551
      "+4 (429)"  → wow=+4, value=429   (oil rigs in parens)
      "0 (409)"   → wow=0,  value=409
    Returns (wow: int, value: int) or (None, None) on failure.
    """
    # Strip HTML tags first
    clean = re.sub(r'<[^>]+>', ' ', text).strip()
    clean = re.sub(r'\s+', ' ', clean)

    # Pattern: optional sign+digits (wow), then digits possibly in parens (value)
    m = re.match(r'([+-]?\d+)\s+\(?(\d+)\)?', clean)
    if m:
        return int(m.group(1)), int(m.group(2))

    # Pattern: just a value with no wow (shouldn't happen but safety)
    m2 = re.match(r'\(?(\d+)\)?', clean)
    if m2:
        return None, int(m2.group(1))

    return None, None


def _scrape_aogr() -> list[dict]:
    """
    Scrape AOGR page and extract weekly rig count rows.
    Returns list of dicts sorted oldest→newest.
    Each dict: {date, total_rigs, oil_rigs, wow_total, wow_oil}
    """
    r = requests.get(AOGR_URL, headers=HEADERS, timeout=20)
    r.raise_for_status()
    html = r.text

    # Extract all three span types in document order
    # Each week appears as a triplet: tc-tot-curr, rc-oik, rc-tot-prev
    tot_curr_spans = re.findall(
        r'class="[^"]*tc-tot-curr[^"]*">(.*?)</span>\s*</span>',
        html, re.DOTALL
    )
    oil_spans = re.findall(
        r'class="[^"]*rc-oik[^"]*">(.*?)</span>\s*</span>',
        html, re.DOTALL
    )
    prev_spans = re.findall(
        r'class="[^"]*rc-tot-prev[^"]*">(\d+)</span>',
        html
    )

    print(f"[rig_count] Found: {len(tot_curr_spans)} total-curr, "
          f"{len(oil_spans)} oil, {len(prev_spans)} prev-week spans")

    # Zip them into rows — they appear in the same order on the page
    rows = []
    n = min(len(tot_curr_spans), len(oil_spans), len(prev_spans))

    for i in range(n):
        wow_total, total = _parse_wow_and_value(tot_curr_spans[i])
        wow_oil,   oil   = _parse_wow_and_value(oil_spans[i])
        prev_total       = int(prev_spans[i]) if prev_spans[i].isdigit() else None

        if total is None or oil is None:
            continue

        # Assign approximate date: most recent row is index 0 on page
        # We assign dates going backwards from today in weekly steps
        # (AOGR shows newest first)
        weeks_ago = i
        approx_date = (datetime.now(timezone.utc) - timedelta(weeks=weeks_ago))
        # Round to nearest Friday (BH releases on Friday)
        days_to_friday = (4 - approx_date.weekday()) % 7
        if days_to_friday > 0:
            approx_date = approx_date - timedelta(days=(approx_date.weekday() - 4) % 7)
        iso_date = approx_date.strftime("%Y-%m-%d")

        rows.append({
            "date":        iso_date,
            "total_rigs":  total,
            "oil_rigs":    oil,
            "wow_total":   wow_total,
            "wow_oil":     wow_oil,
            "prev_total":  prev_total,
        })

    # Reverse so oldest→newest
    return list(reversed(rows))


# ── History manager ───────────────────────────────────────────────────────────

def _load_existing_history() -> list[dict]:
    if not os.path.exists(OUTPUT_PATH):
        return []
    try:
        with open(OUTPUT_PATH) as f:
            return json.load(f).get("history", [])
    except Exception:
        return []


def _merge_history(existing: list[dict], fresh: list[dict]) -> list[dict]:
    """Merge by date, fresh wins, keep latest HISTORY_WEEKS."""
    combined = {r["date"]: r for r in existing}
    for r in fresh:
        combined[r["date"]] = r
    sorted_rows = sorted(combined.values(), key=lambda x: x["date"])
    return sorted_rows[-HISTORY_WEEKS:]


# ── Signal ────────────────────────────────────────────────────────────────────

def _signal(history: list[dict]) -> dict:
    if not history:
        return {"label": "UNKNOWN", "direction": "neutral", "note": "No data"}

    latest   = history[-1]
    oil_rigs = latest.get("oil_rigs")
    wow      = latest.get("wow_oil")

    # Level
    if oil_rigs is None:
        level = "UNKNOWN"
    elif oil_rigs > THRESHOLDS["growing"]:
        level = "GROWING"
    elif oil_rigs > THRESHOLDS["flat_lo"]:
        level = "FLAT"
    else:
        level = "DECLINING"

    # Direction from WoW
    if wow is not None:
        if wow >= WOW_THRESHOLD:
            direction, trend = "bearish", f"rising +{wow} WoW → more supply in 4-6m"
        elif wow <= -WOW_THRESHOLD:
            direction, trend = "bullish", f"falling {wow} WoW → less supply in 4-6m"
        else:
            direction, trend = "neutral", f"flat ({wow:+d} WoW, within ±{WOW_THRESHOLD} noise)"
    else:
        direction = "bearish" if level == "GROWING" else \
                    "bullish" if level == "DECLINING" else "neutral"
        trend = "level-only (no WoW data)"

    # 4-week momentum
    four_week_trend = None
    if len(history) >= 4:
        old = history[-4].get("oil_rigs")
        if old and oil_rigs:
            chg = oil_rigs - old
            four_week_trend = f"{chg:+d} over 4 weeks"

    return {
        "label":           level,
        "direction":       direction,
        "trend":           trend,
        "four_week_trend": four_week_trend,
        "note": f"Oil rigs {level.lower()}, {trend}. Impact in 4-6 months.",
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def fetch_rig_count() -> dict:
    fresh, existing = [], _load_existing_history()

    try:
        fresh = _scrape_aogr()
        print(f"[rig_count] Scraped {len(fresh)} weeks from AOGR")
    except Exception as e:
        print(f"[rig_count] Scrape failed: {e}")

    history = _merge_history(existing, fresh) if fresh else existing[-HISTORY_WEEKS:]
    signal  = _signal(history)
    latest  = history[-1] if history else {}

    output = {
        "fetched_at":    datetime.now(timezone.utc).isoformat(),
        "source":        "AOGR.com (Baker Hughes weekly mirror)",
        "latest":        latest,
        "signal":        signal,
        "history":       history,
        "thresholds":    THRESHOLDS,
        "wow_threshold": WOW_THRESHOLD,
        "notes": {
            "release":       "Every Friday 1PM CT",
            "lag":           "4-6 month lag: rig change → production change",
            "wow_band":      f"±{WOW_THRESHOLD} rigs WoW treated as noise",
            "peak":          "1,609 rigs Oct 2014 | low: 172 rigs Aug 2020",
            "current_range": "~480-560 rigs (2025-2026 baseline)",
        },
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    oil     = latest.get("oil_rigs", "N/A")
    wow     = latest.get("wow_oil")
    wow_str = f"{wow:+d}" if wow is not None else "N/A"
    print(f"[rig_count] Oil: {oil} | WoW: {wow_str} | "
          f"Signal: {signal['label']} / {signal['direction']} | "
          f"4wk: {signal.get('four_week_trend', 'N/A')}")
    return output


def run():
    fetch_rig_count()


if __name__ == "__main__":
    fetch_rig_count()

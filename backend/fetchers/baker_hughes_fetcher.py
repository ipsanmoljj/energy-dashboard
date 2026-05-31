"""
Baker Hughes Rig Count Fetcher
Source: AOGR.com (mirrors Baker Hughes weekly) — scrapes 10-week history
  URL: https://www.aogr.com/web-exclusives/us-rig-count/2026

Stores a rolling 10-week history in rig_count_latest.json.
WoW change is computed from stored history, not guessed.

Released every Friday at 1PM CT. Data is free and public.

Signal logic:
  Level  — where the count sits (GROWING >600, FLAT 350-600, DECLINING <350)
  Direction — WoW trend (bullish if falling >=5, bearish if rising >=5, neutral otherwise)
"""

import os, json, re, requests
from datetime import datetime, timezone

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "../data/rig_count_latest.json")

AOGR_URL_2026 = "https://www.aogr.com/web-exclusives/us-rig-count/2026"
AOGR_URL_2025 = "https://www.aogr.com/web-exclusives/us-rig-count/2025"

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

THRESHOLDS   = {"growing": 600, "flat_lo": 350}
HISTORY_WEEKS = 10
WOW_THRESHOLD = 5   # minimum rig change to call a direction


# ── Scraper ───────────────────────────────────────────────────────────────────

def _scrape_aogr(url: str) -> list[dict]:
    """
    Scrape weekly rig count rows from AOGR page.
    Each row has: date, oil%, gas%, misc%, total, wow_change
    Returns list of dicts sorted oldest-first.
    """
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    html = r.text

    rows = []

    # AOGR table rows look like:
    # <tr><td>05/23/26</td><td>543</td><td>+2</td><td>...</td><td>75 / 23 / 2</td></tr>
    # We extract: date, total count, WoW change, oil/gas/misc ratio

    # Find all table rows containing rig data
    # Pattern: date like MM/DD/YY followed by 3-digit total
    row_pattern = re.compile(
        r'(\d{2}/\d{2}/\d{2})'          # date  MM/DD/YY
        r'[^<]*</td>\s*<td[^>]*>'        # close date cell, open next
        r'\s*(\d{3})\s*'                 # total rig count (3 digits)
        r'[^<]*</td>\s*<td[^>]*>'        # close total cell, open next
        r'\s*([+-]?\d+)\s*'              # WoW change
        r'[^<]*</td>.*?'                 # remaining cells
        r'(\d{2})\s*/\s*(\d{2})\s*/\s*(\d{1,2})',  # oil% / gas% / misc%
        re.DOTALL
    )

    for m in row_pattern.finditer(html):
        date_str  = m.group(1)   # MM/DD/YY
        total     = int(m.group(2))
        wow       = int(m.group(3))
        oil_pct   = int(m.group(4))
        gas_pct   = int(m.group(5))

        # Convert MM/DD/YY → YYYY-MM-DD
        try:
            dt = datetime.strptime(date_str, "%m/%d/%y")
            iso_date = dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

        oil_count = round(total * oil_pct / 100)
        gas_count = round(total * gas_pct / 100)

        rows.append({
            "date":       iso_date,
            "total_rigs": total,
            "oil_rigs":   oil_count,
            "gas_rigs":   gas_count,
            "wow_change": wow,         # BH's own WoW figure from the table
            "oil_pct":    oil_pct,
            "gas_pct":    gas_pct,
        })

    # Sort oldest → newest
    return sorted(rows, key=lambda x: x["date"])


def _scrape_with_fallback() -> list[dict]:
    """Try current year first, fall back to prior year if empty."""
    rows = []
    for url in [AOGR_URL_2026, AOGR_URL_2025]:
        try:
            rows = _scrape_aogr(url)
            if rows:
                print(f"[rig_count] Scraped {len(rows)} rows from {url}")
                break
        except Exception as e:
            print(f"[rig_count] Failed {url}: {e}")
    return rows


# ── History manager ───────────────────────────────────────────────────────────

def _load_existing_history() -> list[dict]:
    """Load previously stored history from JSON, or empty list."""
    if not os.path.exists(OUTPUT_PATH):
        return []
    try:
        with open(OUTPUT_PATH) as f:
            data = json.load(f)
        return data.get("history", [])
    except Exception:
        return []


def _merge_history(existing: list[dict], fresh: list[dict]) -> list[dict]:
    """
    Merge existing stored rows with freshly scraped rows.
    Deduplicate by date. Keep latest HISTORY_WEEKS weeks.
    Fresh data wins on conflict.
    """
    combined = {row["date"]: row for row in existing}
    for row in fresh:
        combined[row["date"]] = row   # fresh overwrites existing

    sorted_rows = sorted(combined.values(), key=lambda x: x["date"])
    return sorted_rows[-HISTORY_WEEKS:]   # keep latest N weeks


# ── Signal ────────────────────────────────────────────────────────────────────

def _signal(history: list[dict]) -> dict:
    if not history:
        return {"label": "UNKNOWN", "direction": "neutral", "note": "No data"}

    latest   = history[-1]
    oil_rigs = latest.get("oil_rigs")
    wow      = latest.get("wow_change")   # BH's own WoW from table

    # Level label
    if oil_rigs is None:
        level = "UNKNOWN"
    elif oil_rigs > THRESHOLDS["growing"]:
        level = "GROWING"
    elif oil_rigs > THRESHOLDS["flat_lo"]:
        level = "FLAT"
    else:
        level = "DECLINING"

    # Direction from WoW change
    if wow is not None:
        if wow >= WOW_THRESHOLD:
            direction = "bearish"    # rising rigs = more future supply
            trend = f"rising +{wow} WoW"
        elif wow <= -WOW_THRESHOLD:
            direction = "bullish"    # falling rigs = less future supply
            trend = f"falling {wow} WoW"
        else:
            direction = "neutral"
            trend = f"flat ({wow:+d} WoW, within ±{WOW_THRESHOLD} noise band)"
    else:
        direction = "bearish" if level == "GROWING" else \
                    "bullish" if level == "DECLINING" else "neutral"
        trend = "level-only signal (no WoW data)"

    # 4-week trend: is the count consistently rising or falling?
    four_week_trend = None
    if len(history) >= 4:
        four_weeks_ago = history[-4].get("oil_rigs")
        if four_weeks_ago and oil_rigs:
            four_week_change = oil_rigs - four_weeks_ago
            four_week_trend  = f"{four_week_change:+d} over 4 weeks"

    return {
        "label":            level,
        "direction":        direction,
        "trend":            trend,
        "four_week_trend":  four_week_trend,
        "note": (
            f"Oil rigs {level.lower()}, {trend}. "
            f"Production impact expected in 4-6 months."
        ),
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def fetch_rig_count() -> dict:
    # 1. Scrape fresh data
    fresh_rows = _scrape_with_fallback()

    # 2. Load existing history
    existing = _load_existing_history()

    # 3. Merge + keep rolling 10-week window
    if fresh_rows:
        history = _merge_history(existing, fresh_rows)
    elif existing:
        print("[rig_count] No fresh data — using stored history")
        history = existing[-HISTORY_WEEKS:]
    else:
        history = []

    # 4. Compute signal
    signal  = _signal(history)
    latest  = history[-1] if history else {}

    output = {
        "fetched_at":   datetime.now(timezone.utc).isoformat(),
        "source":       "AOGR.com (Baker Hughes weekly mirror)",
        "latest":       latest,
        "signal":       signal,
        "history":      history,          # rolling 10-week window
        "thresholds":   THRESHOLDS,
        "wow_threshold": WOW_THRESHOLD,
        "notes": {
            "release":        "Every Friday 1PM CT",
            "lag":            "4-6 month lag: rig change → production change",
            "wow_band":       f"±{WOW_THRESHOLD} rigs WoW treated as noise",
            "peak":           "1,609 rigs Oct 2014 | low: 172 rigs Aug 2020",
            "current_range":  "~480-550 rigs (2025-2026 baseline)",
        },
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    oil  = latest.get("oil_rigs", "N/A")
    wow  = latest.get("wow_change")
    wow_str = f"{wow:+d}" if wow is not None else "N/A"
    print(f"[rig_count] Oil: {oil} | WoW: {wow_str} | "
          f"Signal: {signal['label']} / {signal['direction']} | "
          f"4wk: {signal.get('four_week_trend', 'N/A')}")

    return output


def run():
    fetch_rig_count()


if __name__ == "__main__":
    fetch_rig_count()

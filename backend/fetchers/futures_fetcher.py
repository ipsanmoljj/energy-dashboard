"""
futures_fetchers.py
------------------
Fetches delayed futures prices for the 5 core energy contracts.
Primary:  Yahoo Finance (delayed ~15 min, free)
Fallback: Your Cloudflare Worker proxy (configured in config/settings.json)

Contracts:
  BZ=F   → ICE Brent Crude (front-month)
  CL=F   → NYMEX WTI Crude (front-month)
  RB=F   → NYMEX RBOB Gasoline
  HO=F   → NYMEX Heating Oil / ULSD
  BG=F   → ICE Gasoil (European diesel benchmark)

Derived outputs (saved alongside raw prices):
  - 3-2-1 crack spread  [(2×RBOB + 1×ULSD − 3×WTI) / 3]  $/bbl
  - Brent-WTI spread    (Brent − WTI)                       $/bbl
  - ICE Gasoil crack    (GO - Brent, European diesel margin)
  - All in $/bbl (unit-converted from $/gal for RBOB/HO)

Saves to: backend/data/futures_latest.json

Usage:
  python backend/fetchers/futures_fetcher.py
"""

import json
import logging
import time
import random
from datetime import datetime
from pathlib import Path

import requests

# ── Config ──────────────────────────────────────────────────────────────────

OUTPUT_PATH = Path(__file__).resolve().parents[1] / "data" / "futures_latest.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# Yahoo Finance endpoints (try multiple to avoid rate limits)
YF_ENDPOINTS = [
    "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
    "https://query2.finance.yahoo.com/v8/finance/chart/{ticker}",
]

YF_QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote"

# ── Stooq tickers (primary source — no rate limiting, no key needed) ──────────
# Stooq uses lowercase with dots: cl.f, bz.f etc.
# CSV endpoint: https://stooq.com/q/d/l/?s={ticker}&i=d
STOOQ_TICKERS = {
    "BZ=F": "bz.f",   # Brent
    "CL=F": "cl.f",   # WTI
    "RB=F": "rb.f",   # RBOB Gasoline
    "HO=F": "ho.f",   # Heating Oil / ULSD
    "NG=F": "ng.f",   # Natural Gas
    "BG=F": None,     # ICE Gasoil — not on Stooq, Yahoo only
}
STOOQ_BASE = "https://stooq.com/q/d/l/?s={ticker}&i=d"

# Polite headers — rotate between requests
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

# ── Contract definitions ─────────────────────────────────────────────────────

FUTURES = {
    "BZ=F": {
        "key":          "brent",
        "label":        "ICE Brent Crude (front-month)",
        "exchange":     "ICE Futures Europe",
        "unit":         "usd_per_bbl",
        "lot_size_bbl": 1000,
        "multiplier":   1.0,          # already $/bbl
        "benchmark":    True,
        "signal_note":  (
            "Global crude benchmark (~70% of internationally traded crude). "
            "Backwardation in M1-M2 = physical tightness. "
            "Contango > $1.5/bbl/mo = storage economic. Watch vs WTI for US export signal."
        ),
    },
    "CL=F": {
        "key":          "wti",
        "label":        "NYMEX WTI Crude (front-month)",
        "exchange":     "CME/NYMEX",
        "unit":         "usd_per_bbl",
        "lot_size_bbl": 1000,
        "multiplier":   1.0,
        "benchmark":    True,
        "signal_note":  (
            "US domestic crude benchmark. Physical delivery at Cushing, Oklahoma. "
            "WTI-Brent < $2/bbl → US exports flooding market. "
            "WTI-Brent > $8/bbl → US export bottleneck or North Sea disruption. "
            "EIA release Wed 10:30 ET = peak vol event."
        ),
    },
    "RB=F": {
        "key":          "rbob",
        "label":        "NYMEX RBOB Gasoline (front-month)",
        "exchange":     "CME/NYMEX",
        "unit":         "usd_per_gal",
        "lot_size_bbl": 1000,         # 42,000 gal = 1000 bbl
        "multiplier":   42.0,         # × 42 to convert $/gal → $/bbl
        "benchmark":    False,
        "signal_note":  (
            "US gasoline benchmark. Seasonal peak crack Feb–May (driving season build). "
            "Long RBOB crack vs WTI in Feb–Apr = most reliable seasonal energy trade. "
            "Summer/winter RVP spec change at Apr/Oct roll creates predictable discontinuity."
        ),
    },
    "HO=F": {
        "key":          "heating_oil",
        "label":        "NYMEX Heating Oil / ULSD (front-month)",
        "exchange":     "CME/NYMEX",
        "unit":         "usd_per_gal",
        "lot_size_bbl": 1000,
        "multiplier":   42.0,
        "benchmark":    False,
        "signal_note":  (
            "US distillate benchmark (ULSD 15ppm). Proxy for global diesel tightness. "
            "HO crack widens = diesel/heating oil supply tight; supports crude demand. "
            "HO-RBOB spread: wide diesel premium → industrial/commercial demand > driving demand."
        ),
    },
    "BG=F": {
        "key":          "ice_gasoil",
        "label":        "ICE Gasoil (front-month)",
        "exchange":     "ICE Futures Europe",
        "unit":         "usd_per_mt",
        "lot_size_bbl": 745,
        "multiplier":   0.1342,
        "benchmark":    False,
        "signal_note":  (
            "European diesel benchmark. Gasoil crack (GO - Brent) is the most actively "
            "traded crack spread in European hours. Reference price for jet fuel and "
            "heating oil in Europe. Key for transatlantic diesel arb (HO vs GO spread). "
            "Wide gasoil crack > $25/bbl = European diesel tight = bullish crude demand. "
            "Note: Yahoo Finance BG=F may return stale prices. "
            "If price < $500/MT, use HO=F as proxy (USD/gal x 42 x 6.29 for MT equiv)."
        ),
    },
    "NG=F": {
        "key":          "henry_hub",
        "label":        "NYMEX Henry Hub Natural Gas (front-month)",
        "exchange":     "CME/NYMEX",
        "unit":         "usd_per_mmbtu",
        "lot_size_bbl": None,
        "multiplier":   1.0,
        "benchmark":    False,
        "signal_note":  (
            "US gas benchmark. Kept as macro cross-commodity signal. "
            "WTI/HH ratio > 20x = gas cheap vs oil → power switching to gas → oil demand softens. "
            "Moved to macro layer — primary diesel signal now uses ICE Gasoil (BG=F)."
        ),
    },
}

# ── Yahoo Finance fetch ──────────────────────────────────────────────────────

def _yf_headers() -> dict:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://finance.yahoo.com/",
    }


def fetch_stooq(yahoo_ticker: str) -> dict | None:
    """
    Fetch latest price from Stooq CSV endpoint.
    Primary source — no rate limiting, no API key, completely free.

    Returns same dict format as fetch_single_chart for compatibility.
    CSV format: Date,Open,High,Low,Close,Volume (newest last)
    """
    stooq_ticker = STOOQ_TICKERS.get(yahoo_ticker)
    if not stooq_ticker:
        return None   # ticker not on Stooq (e.g. BG=F ICE Gasoil)

    url = STOOQ_BASE.format(ticker=stooq_ticker)
    try:
        r = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 EnergyDashboard/1.0"},
            timeout=10,
        )
        r.raise_for_status()
        lines = r.text.strip().splitlines()

        if len(lines) < 2:
            log.warning("  Stooq %s: empty response", stooq_ticker)
            return None

        # Header: Date,Open,High,Low,Close,Volume
        header = [h.strip() for h in lines[0].split(",")]
        latest = dict(zip(header, lines[-1].split(",")))
        prev   = dict(zip(header, lines[-2].split(","))) if len(lines) > 2 else {}

        price      = float(latest.get("Close", 0) or 0)
        prev_price = float(prev.get("Close", price) or price)

        if price == 0:
            log.warning("  Stooq %s: zero price returned", stooq_ticker)
            return None

        change     = round(price - prev_price, 4)
        change_pct = round(change / prev_price * 100, 3) if prev_price else None

        # Build 30-day history
        history = []
        for line in lines[1:]:
            parts = line.split(",")
            if len(parts) >= 5:
                try:
                    history.append({
                        "date":  parts[0].strip(),
                        "close": float(parts[4].strip()),
                    })
                except ValueError:
                    continue

        log.info("  Stooq %s (%s): $%.4f", yahoo_ticker, stooq_ticker, price)
        return {
            "price":        round(price, 4),
            "prev_close":   round(prev_price, 4),
            "change":       change,
            "change_pct":   change_pct,
            "high_52w":     None,
            "low_52w":      None,
            "history":      history,
            "market_state": "delayed",
            "source":       "stooq",
        }

    except Exception as exc:
        log.debug("  Stooq failed for %s: %s", stooq_ticker, exc)
        return None


def fetch_quote_batch(tickers: list[str]) -> dict[str, dict]:
    """
    Fetch multiple tickers in one Yahoo Finance v7 quote call.
    Returns {ticker: {price, change, changePct, previousClose, ...}}
    """
    symbols = ",".join(tickers)
    url     = f"{YF_QUOTE_URL}?symbols={symbols}"

    try:
        r = requests.get(url, headers=_yf_headers(), timeout=12)
        r.raise_for_status()
        results = r.json()["quoteResponse"]["result"]
        return {item["symbol"]: item for item in results}
    except Exception as exc:
        log.warning("Batch quote failed: %s — falling back to individual fetches", exc)
        return {}


def fetch_single_chart(ticker: str, days: int = 30) -> dict | None:
    """
    Fetch OHLCV history via Yahoo Finance v8. Retries 3x with delays on rate limits.
    """
    max_retries = 3

    for attempt in range(max_retries):
        for endpoint_tmpl in YF_ENDPOINTS:
            url    = endpoint_tmpl.format(ticker=ticker)
            params = {"interval": "1d", "range": f"{days}d"}
            try:
                r = requests.get(url, headers=_yf_headers(), params=params, timeout=15)

                # Handle rate limiting explicitly before raise_for_status
                if r.status_code in (429, 401):
                    wait = (attempt + 1) * 5
                    log.debug("  Rate limited (%d) %s — retry in %ds (attempt %d/%d)",
                              r.status_code, ticker, wait, attempt + 1, max_retries)
                    time.sleep(wait)
                    break   # break inner loop, retry outer

                r.raise_for_status()
                data   = r.json()
                result = data["chart"]["result"][0]
                meta   = result["meta"]

                price      = meta.get("regularMarketPrice") or meta.get("chartPreviousClose")
                prev_close = meta.get("chartPreviousClose") or meta.get("previousClose")
                change     = round(price - prev_close, 4) if price and prev_close else None
                change_pct = round(change / prev_close * 100, 3) if change and prev_close else None

                timestamps = result["timestamp"]
                closes     = result["indicators"]["quote"][0].get("close", [])
                history = [
                    {"date": datetime.fromtimestamp(ts).strftime("%Y-%m-%d"),
                     "close": round(c, 4) if c else None}
                    for ts, c in zip(timestamps, closes) if c is not None
                ]

                return {
                    "price":        round(price, 4) if price else None,
                    "prev_close":   round(prev_close, 4) if prev_close else None,
                    "change":       change,
                    "change_pct":   change_pct,
                    "high_52w":     meta.get("fiftyTwoWeekHigh"),
                    "low_52w":      meta.get("fiftyTwoWeekLow"),
                    "history":      list(reversed(history)),
                    "market_state": meta.get("marketState", "unknown"),
                }

            except Exception as exc:
                log.debug("Chart fetch failed %s for %s: %s", endpoint_tmpl, ticker, exc)
                time.sleep(1.0)
                continue

        if attempt < max_retries - 1:
            time.sleep(random.uniform(3, 6))  # pause between retries

    return None

# ── Unit conversion helpers ──────────────────────────────────────────────────

def to_bbl(price: float | None, multiplier: float) -> float | None:
    """Convert $/gal → $/bbl using multiplier (42 for RBOB/HO). Brent/WTI passthrough."""
    if price is None:
        return None
    return round(price * multiplier, 4)


# ── Fallback price estimation ────────────────────────────────────────────────

def estimate_missing_prices(contracts: dict) -> dict:
    """
    Only estimates RBOB from HO when unavailable.
    Brent and WTI are NOT estimated — they are separate benchmarks.
    Missing Brent/WTI shows as INSUFFICIENT_DATA on next run.
    """
    rbob = contracts.get("rbob", {}).get("price_bbl")
    ho   = contracts.get("heating_oil", {}).get("price_bbl")

    if rbob is None and ho is not None:
        est_rbob = round(ho * 0.875, 2)
        contracts["rbob"]["price_bbl"]     = est_rbob
        contracts["rbob"]["estimated"]     = True
        contracts["rbob"]["estimate_note"] = (
            f"Estimated from HO (${ho:.2f}/bbl) × 0.875 seasonal ratio — "
            f"Yahoo rate limited RBOB. Re-fetch in 30 min for real price."
        )
        log.info("  [ESTIMATE] RBOB $%.2f/bbl (HO proxy — temporary)", est_rbob)
    elif rbob is None:
        log.warning("  RBOB unavailable — no HO to estimate from. Showing INSUFFICIENT_DATA.")

    return contracts

# ── Derived spread calculations ──────────────────────────────────────────────

def compute_crack_321(wti_bbl: float | None, rbob_bbl: float | None,
                      ho_bbl: float | None) -> dict:
    """
    3-2-1 crack spread: [(2×RBOB + 1×ULSD) − (3×WTI)] / 3  (all in $/bbl)

    Signal thresholds (from OilMacroTrading book):
      > $20/bbl  → product demand outpaces crude; BULLISH crude demand
      $12-20     → normal refinery margin
      < $12      → compressed margins; runs may be cut; BEARISH crude demand
    """
    if None in (wti_bbl, rbob_bbl, ho_bbl):
        return {"value_bbl": None, "signal": "INSUFFICIENT_DATA"}

    value = round(((2 * rbob_bbl) + (1 * ho_bbl) - (3 * wti_bbl)) / 3, 2)

    if value > 20:
        signal = "BULLISH"
        note   = f"3-2-1 crack ${value:.2f}/bbl > $20: product demand outpaces crude supply → refiners incentivised to run harder → crude demand grows."
    elif value > 12:
        signal = "NEUTRAL"
        note   = f"3-2-1 crack ${value:.2f}/bbl ($12–$20): normal refinery margin range."
    else:
        signal = "BEARISH"
        note   = f"3-2-1 crack ${value:.2f}/bbl < $12: compressed margins → runs may be cut → crude demand softens."

    return {
        "value_bbl":  value,
        "components": {
            "wti_bbl":  wti_bbl,
            "rbob_bbl": rbob_bbl,
            "ho_bbl":   ho_bbl,
        },
        "formula": "[(2×RBOB + 1×HO) − (3×WTI)] / 3",
        "signal":  signal,
        "note":    note,
    }


def compute_brent_wti_spread(brent: float | None, wti: float | None) -> dict:
    """
    Brent-WTI spread: Brent − WTI ($/bbl)

    Signal thresholds (from OilMacroTrading book):
      > $8/bbl  → US export bottleneck OR North Sea disruption
      $2-8      → normal range
      < $2      → US exports flooding market (shale surplus reaching export terminals)
    """
    if None in (brent, wti):
        return {"value_bbl": None, "signal": "INSUFFICIENT_DATA"}

    value = round(brent - wti, 2)

    if value > 8:
        signal = "ALERT"
        note   = f"Brent-WTI ${value:.2f}/bbl > $8: US export bottleneck OR North Sea supply disruption. Watch Cushing stocks + BFOET cargo counts."
    elif value >= 2:
        signal = "NORMAL"
        note   = f"Brent-WTI ${value:.2f}/bbl: normal range ($2-$8). US exports flowing; North Sea supply intact."
    else:
        signal = "ALERT"
        note   = f"Brent-WTI ${value:.2f}/bbl < $2: US shale exports flooding Atlantic basin. Bearish for Brent relative to WTI."

    return {
        "value_bbl": value,
        "brent_bbl": brent,
        "wti_bbl":   wti,
        "signal":    signal,
        "note":      note,
    }


def compute_ho_rbob_spread(ho_bbl: float | None, rbob_bbl: float | None) -> dict:
    """
    HO-RBOB spread: Heating Oil − RBOB ($/bbl)
    Diesel premium over gasoline.

    Wide (> $15/bbl):  diesel tight vs gasoline → industrial/commercial demand dominant
    Normal ($5-$15):   balanced product slate
    Narrow/negative:   gasoline scarce vs diesel → driving season pressure
    """
    if None in (ho_bbl, rbob_bbl):
        return {"value_bbl": None, "signal": "INSUFFICIENT_DATA"}

    value = round(ho_bbl - rbob_bbl, 2)

    if value > 15:
        signal, note = "DIESEL_TIGHT", f"HO-RBOB ${value:.2f}/bbl: diesel significantly outperforming → industrial/logistics demand dominant. Check European gasoil crack alignment."
    elif value >= 5:
        signal, note = "NORMAL", f"HO-RBOB ${value:.2f}/bbl: normal diesel premium over gasoline."
    else:
        signal, note = "GASOLINE_TIGHT", f"HO-RBOB ${value:.2f}/bbl < $5: gasoline outperforming → driving season or refinery reconfiguration towards gasoline yield."

    return {
        "value_bbl": value,
        "ho_bbl":    ho_bbl,
        "rbob_bbl":  rbob_bbl,
        "signal":    signal,
        "note":      note,
    }


def compute_gas_oil_ratio(wti: float | None, ng: float | None) -> dict:
    """
    Crude-to-gas price ratio (WTI $/bbl ÷ HH $/mmBTU).
    Historical norm: ~10-15x. High ratio → gas cheap → power switching from oil/coal to gas.
    Low ratio → oil cheap relative to gas.

    Energy equivalence: 1 bbl crude ≈ 5.8 mmBTU
    Oil-equivalent gas price = NG × 5.8
    """
    if None in (wti, ng):
        return {"ratio": None, "signal": "INSUFFICIENT_DATA"}

    ratio            = round(wti / ng, 2) if ng else None
    oil_equiv_gas    = round(ng * 5.8, 2) if ng else None   # $/bbl equivalent

    if ratio is None:
        return {"ratio": None, "signal": "INSUFFICIENT_DATA"}

    if ratio > 20:
        signal = "GAS_CHEAP"
        note   = f"WTI/HH ratio {ratio}x (> 20x): gas very cheap vs oil → power sector switches to gas; gas demand rises; oil demand softens at margin."
    elif ratio >= 10:
        signal = "NORMAL"
        note   = f"WTI/HH ratio {ratio}x: normal range (10-20x). No strong cross-commodity switching pressure."
    else:
        signal = "OIL_CHEAP"
        note   = f"WTI/HH ratio {ratio}x (< 10x): oil cheap vs gas → oil demand supported; gas substitution less attractive."

    return {
        "ratio":         ratio,
        "wti_bbl":       wti,
        "ng_mmbtu":      ng,
        "oil_equiv_gas": oil_equiv_gas,
        "signal":        signal,
        "note":          note,
    }


# ── Main ─────────────────────────────────────────────────────────────────────

def run() -> dict:
    log.info("Starting futures fetch — %d contracts", len(FUTURES))

    output = {
        "fetcher":    "futures_fetcher",
        "fetched_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source":     "Stooq (primary) + Yahoo Finance fallback",
        "contracts":  {},
        "derived":    {},
    }

    prices_bbl: dict[str, float | None] = {}  # keyed by contract key, all $/bbl

    # ── Step 1: batch quote for current prices ───────────────────────────────
    tickers   = list(FUTURES.keys())
    batch     = fetch_quote_batch(tickers)

    for ticker, cfg in FUTURES.items():
        log.info("Processing %s (%s)", ticker, cfg["label"])

        # ── Fetch: Stooq FIRST (no rate limit), Yahoo as fallback ──────────────
        chart = fetch_stooq(ticker)   # try Stooq first — fast, free, no limits

        if chart is None:
            # Stooq miss (ticker not on Stooq e.g. BG=F) → try Yahoo batch
            if ticker in batch:
                b = batch[ticker]
                chart = {
                    "price":        b.get("regularMarketPrice"),
                    "prev_close":   b.get("regularMarketPreviousClose"),
                    "change":       b.get("regularMarketChange"),
                    "change_pct":   b.get("regularMarketChangePercent"),
                    "high_52w":     b.get("fiftyTwoWeekHigh"),
                    "low_52w":      b.get("fiftyTwoWeekLow"),
                    "history":      [],
                    "market_state": b.get("marketState", "unknown"),
                    "source":       "yahoo_batch",
                }
            else:
                # Last resort: Yahoo individual chart
                time.sleep(random.uniform(1.0, 2.0))
                chart = fetch_single_chart(ticker, days=30)

        if chart is None or chart.get("price") is None:
            log.error("  Could not fetch %s from Stooq or Yahoo", ticker)
            output["contracts"][cfg["key"]] = {
                "error": "fetch_failed",
                "ticker": ticker,
                "label": cfg["label"],
            }
            prices_bbl[cfg["key"]] = None
            continue

        raw_price  = chart["price"]
        prev_close = chart["prev_close"]
        change     = chart["change"]
        change_pct = chart["change_pct"]
        high_52w   = chart.get("high_52w")
        low_52w    = chart.get("low_52w")
        market_st  = chart.get("market_state", "unknown")
        history    = chart.get("history", [])

        # Unit-convert to $/bbl for spread maths
        price_bbl  = to_bbl(raw_price, cfg["multiplier"])
        prices_bbl[cfg["key"]] = price_bbl

        output["contracts"][cfg["key"]] = {
            "ticker":          ticker,
            "label":           cfg["label"],
            "exchange":        cfg["exchange"],
            "raw_price":       raw_price,
            "raw_unit":        cfg["unit"],
            "price_bbl":       price_bbl,
            "prev_close":      prev_close,
            "change":          change,
            "change_pct":      change_pct,
            "high_52w":        high_52w,
            "low_52w":         low_52w,
            "market_state":    market_st,
            "lot_size_bbl":    cfg["lot_size_bbl"],
            "signal_note":     cfg["signal_note"],
            "history":         history,
        }

        log.info(
            "  %s  raw=%.4f %s | $/bbl=%.2f | chg=%.2f%%",
            ticker,
            raw_price or 0,
            cfg["unit"],
            price_bbl or 0,
            change_pct or 0,
        )

        time.sleep(random.uniform(2.0, 4.0))   # longer pause to avoid Yahoo rate limits

    # ── Step 1b: estimate missing prices if Yahoo blocked some tickers ─────────
    output["contracts"] = estimate_missing_prices(output["contracts"])
    # Update prices_bbl dict with any newly estimated values
    for key in ["brent", "wti", "rbob", "heating_oil", "ice_gasoil"]:
        if output["contracts"].get(key, {}).get("price_bbl"):
            prices_bbl[key] = output["contracts"][key]["price_bbl"]

    # ── Step 2: derived spreads ──────────────────────────────────────────────
    log.info("Computing derived spreads...")

    output["derived"]["crack_321"] = compute_crack_321(
        prices_bbl.get("wti"),
        prices_bbl.get("rbob"),
        prices_bbl.get("heating_oil"),
    )

    output["derived"]["brent_wti_spread"] = compute_brent_wti_spread(
        prices_bbl.get("brent"),
        prices_bbl.get("wti"),
    )

    output["derived"]["ho_rbob_spread"] = compute_ho_rbob_spread(
        prices_bbl.get("heating_oil"),
        prices_bbl.get("rbob"),
    )

    # ICE Gasoil crack: gasoil_bbl - brent_bbl
    gasoil_bbl = prices_bbl.get("ice_gasoil")
    brent_bbl  = prices_bbl.get("brent")
    output["derived"]["gasoil_crack"] = {
        "value_bbl":  round(gasoil_bbl - brent_bbl, 2) if (gasoil_bbl and brent_bbl) else None,
        "gasoil_bbl": gasoil_bbl,
        "brent_bbl":  brent_bbl,
        "signal":     (
            "BULLISH" if gasoil_bbl and brent_bbl and (gasoil_bbl - brent_bbl) > 25
            else "BEARISH" if gasoil_bbl and brent_bbl and (gasoil_bbl - brent_bbl) < 10
            else "NEUTRAL"
        ),
        "note": (
            f"ICE Gasoil crack ${round(gasoil_bbl-brent_bbl,2):.1f}/bbl: "
            + ("Wide > $25 → European diesel tight → bullish crude demand"
               if gasoil_bbl and brent_bbl and (gasoil_bbl - brent_bbl) > 25
               else "Compressed < $10 → diesel margins weak"
               if gasoil_bbl and brent_bbl and (gasoil_bbl - brent_bbl) < 10
               else "Normal range")
        ) if (gasoil_bbl and brent_bbl) else "Insufficient data",
    }

    # ── Step 3: composite futures signal ────────────────────────────────────
    crack_sig  = output["derived"]["crack_321"].get("signal", "NEUTRAL")
    bwti_sig   = output["derived"]["brent_wti_spread"].get("signal", "NORMAL")

    # Brent 1-day change direction → crude price momentum
    brent_chg  = output["contracts"].get("brent", {}).get("change_pct")
    if brent_chg and brent_chg > 0.5:
        price_mom = "BULLISH"
    elif brent_chg and brent_chg < -0.5:
        price_mom = "BEARISH"
    else:
        price_mom = "NEUTRAL"

    output["derived"]["composite_signal"] = {
        "crack_321_signal":    crack_sig,
        "brent_wti_signal":    bwti_sig,
        "brent_price_momentum": price_mom,
        "interpretation": (
            f"Crack {crack_sig} | Brent-WTI {bwti_sig} | Brent momentum {price_mom}. "
            "Wide crack + backwardation = strongest bullish setup. "
            "Compressed crack + contango = bearish refinery/crude setup."
        ),
    }

    # ── Save ─────────────────────────────────────────────────────────────────
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    log.info("Saved → %s", OUTPUT_PATH)

    # ── Summary print ─────────────────────────────────────────────────────────
    log.info("─" * 60)
    log.info("FUTURES SUMMARY")
    log.info("─" * 60)
    for key, data in output["contracts"].items():
        if "error" in data:
            log.info("  %-14s  ERROR", key.upper())
        else:
            log.info(
                "  %-14s  raw=%-9s  $/bbl=%-8s  chg=%+.2f%%",
                key.upper(),
                f"{data.get('raw_price', 'N/A'):.4f}" if data.get("raw_price") else "N/A",
                f"{data.get('price_bbl', 'N/A'):.2f}" if data.get("price_bbl") else "N/A",
                data.get("change_pct") or 0,
            )
    log.info("")
    log.info("SPREADS")
    crack = output["derived"]["crack_321"]
    bwti  = output["derived"]["brent_wti_spread"]
    horbob = output["derived"]["ho_rbob_spread"]
    log.info(
        "  3-2-1 Crack:   $%.2f/bbl  [%s]",
        crack.get("value_bbl") or 0, crack.get("signal"),
    )
    log.info(
        "  Brent-WTI:     $%.2f/bbl  [%s]",
        bwti.get("value_bbl") or 0, bwti.get("signal"),
    )
    log.info(
        "  HO-RBOB:       $%.2f/bbl  [%s]",
        horbob.get("value_bbl") or 0, horbob.get("signal"),
    )
    log.info("─" * 60)

    return output


if __name__ == "__main__":
    run()

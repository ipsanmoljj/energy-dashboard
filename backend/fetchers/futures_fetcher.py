"""
futures_fetcher.py
------------------
Fetches delayed futures prices for the 4 core energy contracts + ICE Gasoil.
Primary:  Stooq (free, no rate limiting, no key needed)
Fallback: Yahoo Finance (delayed ~15 min, free)

Contracts:
  BZ=F   → ICE Brent Crude (front-month)
  CL=F   → NYMEX WTI Crude (front-month)
  RB=F   → NYMEX RBOB Gasoline
  HO=F   → NYMEX Heating Oil / ULSD
  BG=F   → ICE Gasoil (European diesel benchmark)

Derived outputs:
  - 3-2-1 crack spread  [(2×RBOB + 1×ULSD − 3×WTI) / 3]  $/bbl
  - Brent-WTI spread    (Brent − WTI)                       $/bbl
  - HO-RBOB spread      (diesel premium over gasoline)       $/bbl
  - ICE Gasoil crack    (GO − Brent, European diesel margin) $/bbl

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

# ── Config ───────────────────────────────────────────────────────────────────

OUTPUT_PATH = Path(__file__).resolve().parents[1] / "data" / "futures_latest.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

YF_ENDPOINTS = [
    "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
    "https://query2.finance.yahoo.com/v8/finance/chart/{ticker}",
]
YF_QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote"

# Stooq tickers — primary source, no rate limiting, no key needed
STOOQ_TICKERS = {
    "BZ=F": "bz.f",   # Brent
    "CL=F": "cl.f",   # WTI
    "RB=F": "rb.f",   # RBOB Gasoline
    "HO=F": "ho.f",   # Heating Oil / ULSD
    "BG=F": None,     # ICE Gasoil — not on Stooq
    "MCL=F": None
}
STOOQ_BASE = "https://stooq.com/q/d/l/?s={ticker}&i=d"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

# ── Contract definitions ──────────────────────────────────────────────────────

FUTURES = {
    "BZ=F": {
        "key":          "brent",
        "label":        "ICE Brent Crude (front-month)",
        "exchange":     "ICE Futures Europe",
        "unit":         "usd_per_bbl",
        "lot_size_bbl": 1000,
        "multiplier":   1.0,
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
            "WTI-Brent > $8/bbl → US export bottleneck or North Sea disruption."
        ),
    },
    "RB=F": {
        "key":          "rbob",
        "label":        "NYMEX RBOB Gasoline (front-month)",
        "exchange":     "CME/NYMEX",
        "unit":         "usd_per_gal",
        "lot_size_bbl": 1000,
        "multiplier":   42.0,
        "benchmark":    False,
        "signal_note":  (
            "US gasoline benchmark. Seasonal peak crack Feb-May (driving season build). "
            "Long RBOB crack vs WTI in Feb-Apr = most reliable seasonal energy trade."
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
            "HO crack widens = diesel supply tight = supports crude demand. "
            "HO-RBOB spread: wide diesel premium → industrial demand > driving demand."
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
            "heating oil in Europe. Wide gasoil crack > $25/bbl = European diesel tight. "
            "Note: Yahoo BG=F returns stale data — Barchart LFY00 to be added when API key available."
        ),
    },
  "MCL=F": {
    "key":          "dubai",
    "label":        "Dubai/Oman Crude (front-month)",
    "exchange":     "DME",
    "unit":         "usd_per_bbl",
    "lot_size_bbl": 1000,
    "multiplier":   1.0,
    "benchmark":    True,
    "signal_note":  (
        "Middle East sour crude benchmark. Reference for all Persian Gulf "
        "crude priced into Asia. Brent-Dubai spread = light-heavy quality "
        "premium and Atlantic-Pacific arbitrage signal."
    ),
},
}

# ── Fetch functions ───────────────────────────────────────────────────────────

def _yf_headers() -> dict:
    return {
        "User-Agent":      random.choice(USER_AGENTS),
        "Accept":          "application/json, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer":         "https://finance.yahoo.com/",
    }


def fetch_stooq(yahoo_ticker: str) -> dict | None:
    """
    Fetch latest price from Stooq CSV.
    Primary source — no rate limits, no API key, completely free.
    CSV format: Date,Open,High,Low,Close,Volume (newest last)
    """
    stooq_ticker = STOOQ_TICKERS.get(yahoo_ticker)
    if not stooq_ticker:
        return None

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

        header = [h.strip() for h in lines[0].split(",")]
        latest = dict(zip(header, lines[-1].split(",")))
        prev   = dict(zip(header, lines[-2].split(","))) if len(lines) > 2 else {}

        price      = float(latest.get("Close", 0) or 0)
        prev_price = float(prev.get("Close", price) or price)

        if price == 0:
            log.warning("  Stooq %s: zero price", stooq_ticker)
            return None

        change     = round(price - prev_price, 4)
        change_pct = round(change / prev_price * 100, 3) if prev_price else None

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

        log.info("  [Stooq] %s (%s): $%.4f", yahoo_ticker, stooq_ticker, price)
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
        log.debug("  Stooq failed %s: %s", stooq_ticker, exc)
        return None


def fetch_quote_batch(tickers: list[str]) -> dict[str, dict]:
    """Yahoo Finance batch quote — fallback when Stooq fails."""
    symbols = ",".join(tickers)
    try:
        r = requests.get(
            f"{YF_QUOTE_URL}?symbols={symbols}",
            headers=_yf_headers(),
            timeout=12,
        )
        r.raise_for_status()
        results = r.json()["quoteResponse"]["result"]
        return {item["symbol"]: item for item in results}
    except Exception as exc:
        log.warning("Batch quote failed: %s — falling back to individual fetches", exc)
        return {}


def fetch_single_chart(ticker: str, days: int = 30) -> dict | None:
    """Yahoo Finance individual chart — last resort. Retries 3x with delays."""
    max_retries = 3
    for attempt in range(max_retries):
        for endpoint_tmpl in YF_ENDPOINTS:
            url = endpoint_tmpl.format(ticker=ticker)
            try:
                r = requests.get(
                    url,
                    headers=_yf_headers(),
                    params={"interval": "1d", "range": f"{days}d"},
                    timeout=15,
                )
                if r.status_code in (429, 401):
                    wait = (attempt + 1) * 5
                    log.debug("  Rate limited %s — retry in %ds", ticker, wait)
                    time.sleep(wait)
                    break
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
                    "source":       "yahoo",
                }
            except Exception as exc:
                log.debug("  Yahoo chart failed %s: %s", ticker, exc)
                time.sleep(1.0)
                continue
        if attempt < max_retries - 1:
            time.sleep(random.uniform(3, 6))
    return None

# ── Unit conversion ───────────────────────────────────────────────────────────

def to_bbl(price: float | None, multiplier: float) -> float | None:
    if price is None:
        return None
    return round(price * multiplier, 4)

# ── Fallback price estimation ─────────────────────────────────────────────────

def estimate_missing_prices(contracts: dict) -> dict:
    """
    Only estimates RBOB from HO when unavailable.
    Brent and WTI are NOT estimated — they are separate benchmarks.
    A missing Brent-WTI spread is better than a fake one.
    Re-fetch in 30 min to get real prices.
    """
    rbob = contracts.get("rbob", {}).get("price_bbl")
    ho   = contracts.get("heating_oil", {}).get("price_bbl")

    if rbob is None and ho is not None:
        est_rbob = round(ho * 0.875, 2)
        contracts["rbob"]["price_bbl"]     = est_rbob
        contracts["rbob"]["estimated"]     = True
        contracts["rbob"]["estimate_note"] = (
            f"Estimated from HO (${ho:.2f}/bbl) x 0.875 seasonal ratio. "
            f"Yahoo rate limited RBOB. Re-fetch in 30 min for real price."
        )
        log.info("  [ESTIMATE] RBOB $%.2f/bbl (HO proxy — temporary)", est_rbob)
    elif rbob is None:
        log.warning("  RBOB unavailable — no HO to estimate from. INSUFFICIENT_DATA.")

    return contracts

# ── Derived spread calculations ───────────────────────────────────────────────

def compute_crack_321(wti_bbl, rbob_bbl, ho_bbl) -> dict:
    """
    3-2-1 crack: [(2xRBOB + 1xHO) - (3xWTI)] / 3  (all $/bbl)
    > $20 = BULLISH | $12-20 = NEUTRAL | < $12 = BEARISH
    """
    if None in (wti_bbl, rbob_bbl, ho_bbl):
        return {"value_bbl": None, "signal": "INSUFFICIENT_DATA"}
    value = round(((2 * rbob_bbl) + (1 * ho_bbl) - (3 * wti_bbl)) / 3, 2)
    if value > 20:
        signal = "BULLISH"
        note   = f"3-2-1 crack ${value:.2f}/bbl > $20: product demand outpaces crude → refiners run harder → crude demand grows."
    elif value > 12:
        signal = "NEUTRAL"
        note   = f"3-2-1 crack ${value:.2f}/bbl ($12-$20): normal refinery margin range."
    else:
        signal = "BEARISH"
        note   = f"3-2-1 crack ${value:.2f}/bbl < $12: compressed margins → run cuts risk → crude demand softens."
    return {
        "value_bbl":  value,
        "components": {"wti_bbl": wti_bbl, "rbob_bbl": rbob_bbl, "ho_bbl": ho_bbl},
        "formula":    "[(2xRBOB + 1xHO) - (3xWTI)] / 3",
        "signal":     signal,
        "note":       note,
    }


def compute_brent_wti_spread(brent, wti) -> dict:
    """
    Brent-WTI spread ($/bbl).
    > $8 = US export bottleneck or North Sea disruption
    $2-8 = normal
    < $2 = US exports flooding market
    """
    if None in (brent, wti):
        return {"value_bbl": None, "signal": "INSUFFICIENT_DATA"}
    value = round(brent - wti, 2)
    if value > 8:
        signal = "ALERT"
        note   = f"Brent-WTI ${value:.2f} > $8: US export bottleneck OR North Sea disruption."
    elif value >= 2:
        signal = "NORMAL"
        note   = f"Brent-WTI ${value:.2f}: normal range. US exports flowing."
    else:
        signal = "ALERT"
        note   = f"Brent-WTI ${value:.2f} < $2: US exports flooding Atlantic basin."
    return {"value_bbl": value, "brent_bbl": brent, "wti_bbl": wti, "signal": signal, "note": note}


def compute_ho_rbob_spread(ho_bbl, rbob_bbl) -> dict:
    """
    HO-RBOB spread ($/bbl) — diesel premium over gasoline.
    > $15 = DIESEL_TIGHT | $5-15 = NORMAL | < $5 = GASOLINE_TIGHT
    """
    if None in (ho_bbl, rbob_bbl):
        return {"value_bbl": None, "signal": "INSUFFICIENT_DATA"}
    value = round(ho_bbl - rbob_bbl, 2)
    if value > 15:
        signal, note = "DIESEL_TIGHT", f"HO-RBOB ${value:.2f}: diesel outperforming — industrial/logistics demand dominant."
    elif value >= 5:
        signal, note = "NORMAL", f"HO-RBOB ${value:.2f}: normal diesel premium over gasoline."
    else:
        signal, note = "GASOLINE_TIGHT", f"HO-RBOB ${value:.2f}: gasoline outperforming — driving season pressure."
    return {"value_bbl": value, "ho_bbl": ho_bbl, "rbob_bbl": rbob_bbl, "signal": signal, "note": note}

# ── Main ─────────────────────────────────────────────────────────────────────

def run() -> dict:
    log.info("Starting futures fetch — %d contracts", len(FUTURES))

    output = {
        "fetcher":    "futures_fetcher",
        "fetched_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source":     "Stooq (primary) + Yahoo Finance (fallback)",
        "contracts":  {},
        "derived":    {},
    }

    prices_bbl: dict[str, float | None] = {}
    tickers = list(FUTURES.keys())
    batch   = fetch_quote_batch(tickers)

    for ticker, cfg in FUTURES.items():
        log.info("Processing %s (%s)", ticker, cfg["label"])

        # 1. Stooq first — no rate limits
        chart = fetch_stooq(ticker)

        # 2. Yahoo batch fallback
        if chart is None and ticker in batch:
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

        # 3. Yahoo individual chart — last resort
        if chart is None or chart.get("price") is None:
            time.sleep(random.uniform(1.0, 2.0))
            chart = fetch_single_chart(ticker, days=30)

        if chart is None or chart.get("price") is None:
            log.error("  Could not fetch %s from Stooq or Yahoo", ticker)
            output["contracts"][cfg["key"]] = {
                "error": "fetch_failed", "ticker": ticker, "label": cfg["label"],
            }
            prices_bbl[cfg["key"]] = None
            continue

        raw_price = chart["price"]
        price_bbl = to_bbl(raw_price, cfg["multiplier"])

        # Sanity check BG=F — Yahoo returns stale ~$126/MT, real ~$600-900/MT
        # Real price should be > $50/bbl after conversion
        if cfg["key"] == "ice_gasoil" and price_bbl and price_bbl < 50:
            log.warning("  BG=F $%.2f/bbl too low (stale Yahoo data) — ignoring", price_bbl)
            output["contracts"][cfg["key"]] = {
                "error":    "stale_price",
                "ticker":   ticker,
                "label":    cfg["label"],
                "raw_price": raw_price,
                "note":     "Yahoo BG=F returns stale data. Barchart LFY00 to be added when API key available.",
            }
            prices_bbl[cfg["key"]] = None
            continue

        prices_bbl[cfg["key"]] = price_bbl

        output["contracts"][cfg["key"]] = {
            "ticker":       ticker,
            "label":        cfg["label"],
            "exchange":     cfg["exchange"],
            "raw_price":    raw_price,
            "raw_unit":     cfg["unit"],
            "price_bbl":    price_bbl,
            "prev_close":   chart.get("prev_close"),
            "change":       chart.get("change"),
            "change_pct":   chart.get("change_pct"),
            "high_52w":     chart.get("high_52w"),
            "low_52w":      chart.get("low_52w"),
            "market_state": chart.get("market_state", "unknown"),
            "lot_size_bbl": cfg["lot_size_bbl"],
            "signal_note":  cfg["signal_note"],
            "history":      chart.get("history", []),
            "source":       chart.get("source", "yahoo"),
        }

        log.info("  %s  raw=%.4f %s | $/bbl=%.2f | chg=%.2f%%",
                 ticker, raw_price or 0, cfg["unit"],
                 price_bbl or 0, chart.get("change_pct") or 0)

        time.sleep(random.uniform(1.5, 3.0))

    # ── Estimate missing prices ───────────────────────────────────────────────
    output["contracts"] = estimate_missing_prices(output["contracts"])
    for key in ["brent", "wti", "rbob", "heating_oil", "ice_gasoil"]:
        v = output["contracts"].get(key, {})
        if isinstance(v, dict) and v.get("price_bbl") and "error" not in v:
            prices_bbl[key] = v["price_bbl"]

    # ── Derived spreads ───────────────────────────────────────────────────────
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

    # ICE Gasoil crack
    gasoil_bbl = prices_bbl.get("ice_gasoil")
    brent_bbl  = prices_bbl.get("brent")
    output["derived"]["gasoil_crack"] = {
        "value_bbl": round(gasoil_bbl - brent_bbl, 2) if (gasoil_bbl and brent_bbl) else None,
        "signal":    (
            "BULLISH" if gasoil_bbl and brent_bbl and (gasoil_bbl - brent_bbl) > 25
            else "BEARISH" if gasoil_bbl and brent_bbl and (gasoil_bbl - brent_bbl) < 10
            else "NEUTRAL" if (gasoil_bbl and brent_bbl)
            else "INSUFFICIENT_DATA"
        ),
        "note": (
            f"ICE Gasoil crack ${round(gasoil_bbl - brent_bbl, 2):.1f}/bbl"
            if (gasoil_bbl and brent_bbl) else
            "Insufficient data — Barchart LFY00 to be added when API key available"
        ),
    }

    # Composite signal
    crack_sig = output["derived"]["crack_321"].get("signal", "NEUTRAL")
    bwti_sig  = output["derived"]["brent_wti_spread"].get("signal", "NORMAL")
    brent_chg = output["contracts"].get("brent", {}).get("change_pct")
    price_mom = (
        "BULLISH" if brent_chg and brent_chg > 0.5
        else "BEARISH" if brent_chg and brent_chg < -0.5
        else "NEUTRAL"
    )
    output["derived"]["composite_signal"] = {
        "crack_321_signal":     crack_sig,
        "brent_wti_signal":     bwti_sig,
        "brent_price_momentum": price_mom,
        "interpretation": (
            f"Crack {crack_sig} | Brent-WTI {bwti_sig} | Brent momentum {price_mom}. "
            "Wide crack + backwardation = strongest bullish setup."
        ),
    }

    # ── Save ──────────────────────────────────────────────────────────────────
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    # ── Summary ───────────────────────────────────────────────────────────────
    log.info("─" * 60)
    log.info("FUTURES SUMMARY")
    log.info("─" * 60)
    for key, data in output["contracts"].items():
        if "error" in data:
            log.info("  %-14s  ERROR (%s)", key.upper(), data.get("note", "fetch failed")[:50])
        else:
            log.info("  %-14s  raw=%-9s  $/bbl=%-8s  chg=%+.2f%%  [%s]",
                     key.upper(),
                     f"{data.get('raw_price', 0):.4f}" if data.get("raw_price") else "N/A",
                     f"{data.get('price_bbl', 0):.2f}"  if data.get("price_bbl")  else "N/A",
                     data.get("change_pct") or 0,
                     data.get("source", "?"))
    log.info("")
    log.info("SPREADS")
    for name, key in [
        ("3-2-1 Crack",  "crack_321"),
        ("Brent-WTI",    "brent_wti_spread"),
        ("HO-RBOB",      "ho_rbob_spread"),
    ]:
        d = output["derived"][key]
        log.info("  %-14s $%.2f/bbl  [%s]",
                 name + ":",
                 d.get("value_bbl") or 0,
                 d.get("signal", "N/A"))
    log.info("─" * 60)
    log.info("Saved → %s", OUTPUT_PATH)

    return output


if __name__ == "__main__":
    run()

"""
cftc_fetcher.py
---------------
Downloads CFTC Commitments of Traders (COT) report and extracts
speculative positioning for the 5 core energy futures contracts.

Free public data — no API key needed.
Published every Friday at 3:30 PM ET (covers Tuesday positions).
URL pattern: https://www.cftc.gov/dea/newcot/fut_disagg_txtonly_{YEAR}.zip

Why CFTC positioning matters:
  Managed Money net longs/shorts reveal how hedge funds and CTAs
  are positioned in energy markets. Extreme positioning = crowded trade.

  CROWDED LONG  → mean-reversion risk: any bad news triggers rapid unwind
                  → sharp sell-off even if fundamentals unchanged
  CROWDED SHORT  → short-squeeze risk: bullish catalyst = rapid covering
                  → sharp rally
  BUILDING LONGS → trend-following; confirms bullish fundamental view
  BUILDING SHORTS → confirms bearish fundamental view

  Key threshold (from oil macro analysis):
  Net managed money longs as % of open interest:
    > +25%  = CROWDED LONG
    +10–25% = BULLISH positioning
    -5–+10% = NEUTRAL
    -5–-15% = BEARISH positioning
    < -15%  = CROWDED SHORT

Contracts tracked:
  Brent (ICE), WTI (NYMEX), RBOB Gasoline, Heating Oil, Natural Gas

Saves to: backend/data/cftc_latest.json

CFTC COT data: https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm
"""

import io
import json
import logging
import zipfile
import requests
from datetime import datetime, date, timedelta
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

OUTPUT_PATH = Path(__file__).resolve().parents[1] / "data" / "cftc_latest.json"
# CFTC URL patterns (restructured ~2024):
CFTC_CURRENT_URL = "https://www.cftc.gov/dea/newcot/fut_disagg_txtonly.zip"
CFTC_HISTORY_URL = "https://www.cftc.gov/files/dea/history/fut_disagg_txtonly_{year}.zip"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Contract registry ─────────────────────────────────────────────────────────
# Map CFTC report "Market and Exchange Names" → dashboard key
# These strings must match what appears in the CFTC CSV exactly

CFTC_CONTRACTS = {
    "CRUDE OIL, LIGHT SWEET - NEW YORK MERCANTILE EXCHANGE": {
        "key":         "wti",
        "label":       "WTI Crude Oil (NYMEX)",
        "lot_bbl":     1000,
        "signal_note": "Primary US crude positioning. Most liquid energy futures by OI. "
                       "Crowded longs (>25% of OI) = mean-reversion risk on any bearish catalyst.",
    },
    "BRENT CRUDE OIL LAST DAY - ICE FUTURES EUROPE": {
        "key":         "brent",
        "label":       "Brent Crude (ICE Europe)",
        "lot_bbl":     1000,
        "signal_note": "Global crude benchmark positioning. Watch divergence vs WTI positioning "
                       "for Brent-WTI spread trades.",
    },
    "RBOB GASOLINE - NEW YORK MERCANTILE EXCHANGE": {
        "key":         "rbob",
        "label":       "RBOB Gasoline (NYMEX)",
        "lot_bbl":     1000,
        "signal_note": "Gasoline speculative positioning. Seasonal crowding in Feb-Apr "
                       "(driving season build). Watch for long unwinding in Aug-Sep.",
    },
    "NO. 2 HEATING OIL, NEW YORK HARBOR - NEW YORK MERCANTILE EXCHANGE": {
        "key":         "heating_oil",
        "label":       "Heating Oil / ULSD (NYMEX)",
        "lot_bbl":     1000,
        "signal_note": "Distillate positioning. Crowding often appears Oct-Nov "
                       "(winter heating season build). Divergence from RBOB = product slate signal.",
    },
    "NATURAL GAS - NEW YORK MERCANTILE EXCHANGE": {
        "key":         "natural_gas",
        "label":       "Natural Gas Henry Hub (NYMEX)",
        "lot_bbl":     None,   # gas in mmBTU
        "signal_note": "Gas speculative positioning. Extreme shorts = potential squeeze. "
                       "Watch vs temperature data (HDD/CDD) for weather-driven positioning.",
    },
}

# ── COT CSV column indices (Disaggregated COT format) ────────────────────────
# The CFTC disaggregated format has fixed column positions.
# We parse by header name for robustness.

COLUMNS_NEEDED = [
    "Market_and_Exchange_Names",
    "As_of_Date_In_Form_YYMMDD",
    "Open_Interest_All",
    "M_Money_Positions_Long_All",
    "M_Money_Positions_Short_All",
    "M_Money_Positions_Spread_All",
    "Prod_Merc_Positions_Long_All",
    "Prod_Merc_Positions_Short_All",
    "Swap_Positions_Long_All",
    "Swap__Positions_Short_All",
    "NonRept_Positions_Long_All",
    "NonRept_Positions_Short_All",
]

# ── Download + parse ──────────────────────────────────────────────────────────

def _fetch_zip(url: str) -> str | None:
    """Download a ZIP from url and return the first txt/csv file contents."""
    log.info("Trying CFTC URL: %s", url)
    try:
        r = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 EnergyDashboard/1.0"},
            timeout=45,
        )
        r.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            names = zf.namelist()
            log.info("  ZIP contents: %s", names)
            csv_name = next(
                (n for n in names if n.lower().endswith(".txt") or n.lower().endswith(".csv")),
                names[0] if names else None,
            )
            if not csv_name:
                log.error("  No CSV/TXT found in ZIP")
                return None
            return zf.read(csv_name).decode("latin-1")
    except requests.RequestException as exc:
        log.warning("  Failed: %s", exc)
        return None
    except zipfile.BadZipFile as exc:
        log.warning("  Bad ZIP: %s", exc)
        return None


def download_cot_csv(year: int) -> str | None:
    """
    Try multiple CFTC URL patterns to get disaggregated COT data.

    CFTC URL patterns (they change occasionally):
      1. Current-year rolling file (no year in name) — updated weekly
      2. Historical complete-year file under /files/dea/history/
      3. Legacy /newcot/ path with year
    """
    urls_to_try = [
        CFTC_CURRENT_URL,                                        # no year — always current
        CFTC_HISTORY_URL.format(year=year),                      # /files/dea/history/
        CFTC_HISTORY_URL.format(year=year - 1),                  # previous year fallback
        f"https://www.cftc.gov/dea/newcot/fut_disagg_txtonly_{year}.zip",   # old pattern
        f"https://www.cftc.gov/dea/newcot/fut_disagg_txtonly_{year-1}.zip", # old pattern prev yr
    ]

    for url in urls_to_try:
        result = _fetch_zip(url)
        if result:
            log.info("  Success with: %s", url)
            return result

    return None


def parse_cot_csv(csv_text: str) -> list[dict]:
    """
    Parse the CFTC disaggregated COT CSV.
    Returns list of all rows as dicts with column headers as keys.
    """
    lines  = csv_text.strip().splitlines()
    if not lines:
        return []

    # Header is the first line
    header = [col.strip().strip('"') for col in lines[0].split(",")]

    rows = []
    for line in lines[1:]:
        # Handle quoted fields with commas inside
        fields = []
        in_quote = False
        current  = []
        for char in line:
            if char == '"':
                in_quote = not in_quote
            elif char == ',' and not in_quote:
                fields.append("".join(current).strip().strip('"'))
                current = []
            else:
                current.append(char)
        fields.append("".join(current).strip().strip('"'))

        if len(fields) != len(header):
            continue

        rows.append(dict(zip(header, fields)))

    return rows


def extract_contract(rows: list[dict], market_name: str) -> list[dict]:
    """
    Filter rows for a specific market name and return most recent entries,
    sorted descending by date.
    """
    matches = [
        r for r in rows
        if r.get("Market_and_Exchange_Names", "").strip().upper() == market_name.upper()
    ]
    # Sort by date descending (YYMMDD format)
    matches.sort(key=lambda x: x.get("As_of_Date_In_Form_YYMMDD", ""), reverse=True)
    return matches


def safe_int(val: str | None) -> int | None:
    try:
        return int(val.replace(",", "")) if val else None
    except (ValueError, AttributeError):
        return None

# ── Signal computation ────────────────────────────────────────────────────────

def compute_positioning_signal(net_lots: int | None,
                                open_interest: int | None) -> dict:
    """
    Compute positioning signal from managed money net position.

    net_lots      = MM longs - MM shorts
    open_interest = total open interest (all participants)
    net_pct_of_oi = net_lots / open_interest × 100

    Thresholds:
      > +25%  → CROWDED_LONG  (mean-reversion risk)
      +10–25% → BULLISH
      -5–+10% → NEUTRAL
      -15–-5% → BEARISH
      < -15%  → CROWDED_SHORT (short-squeeze risk)
    """
    if net_lots is None or open_interest is None or open_interest == 0:
        return {"signal": "NEUTRAL", "net_pct_of_oi": None}

    net_pct = round(net_lots / open_interest * 100, 2)

    if net_pct > 25:
        signal = "CROWDED_LONG"
        note   = (
            f"Net long {net_pct:.1f}% of OI — crowded position. "
            "Mean-reversion risk: any bearish surprise triggers forced unwind. "
            "Do not chase this long; look for short entry on next catalyst."
        )
    elif net_pct > 10:
        signal = "BULLISH"
        note   = (
            f"Net long {net_pct:.1f}% of OI — managed money building long exposure. "
            "Trend-following confirmation of bullish fundamental view."
        )
    elif net_pct > -5:
        signal = "NEUTRAL"
        note   = f"Net {net_pct:+.1f}% of OI — balanced positioning. No strong speculative trend."
    elif net_pct > -15:
        signal = "BEARISH"
        note   = (
            f"Net short {abs(net_pct):.1f}% of OI — managed money building short exposure. "
            "Trend-following confirmation of bearish view."
        )
    else:
        signal = "CROWDED_SHORT"
        note   = (
            f"Net short {abs(net_pct):.1f}% of OI — crowded short. "
            "Short-squeeze risk: any bullish catalyst triggers rapid covering. "
            "Contrarian long opportunity if fundamentals improve."
        )

    return {
        "signal":       signal,
        "net_pct_of_oi": net_pct,
        "note":         note,
    }


def compute_weekly_change(current: dict, previous: dict | None) -> dict:
    """Compute week-over-week changes in positioning."""
    if previous is None:
        return {}

    def chg(key):
        c = safe_int(current.get(key))
        p = safe_int(previous.get(key))
        if c is None or p is None:
            return None
        return c - p

    return {
        "wow_net_lots":   chg("M_Money_Positions_Long_All") and (
            (safe_int(current.get("M_Money_Positions_Long_All")) or 0) -
            (safe_int(current.get("M_Money_Positions_Short_All")) or 0) -
            ((safe_int(previous.get("M_Money_Positions_Long_All")) or 0) -
             (safe_int(previous.get("M_Money_Positions_Short_All")) or 0))
        ),
        "wow_longs":      chg("M_Money_Positions_Long_All"),
        "wow_shorts":     chg("M_Money_Positions_Short_All"),
        "wow_direction":  (
            "ADDING_LONGS" if (chg("M_Money_Positions_Long_All") or 0) > 5000
            else "COVERING_SHORTS" if (chg("M_Money_Positions_Short_All") or 0) < -5000
            else "ADDING_SHORTS" if (chg("M_Money_Positions_Short_All") or 0) > 5000
            else "REDUCING_LONGS" if (chg("M_Money_Positions_Long_All") or 0) < -5000
            else "MIXED"
        ),
    }

# ── Main ──────────────────────────────────────────────────────────────────────

def run() -> dict:
    log.info("Starting CFTC COT fetch")

    output = {
        "fetcher":    "cftc_fetcher",
        "fetched_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source":     "CFTC Disaggregated Commitments of Traders (public)",
        "note":       "Data published Fridays 3:30 PM ET; covers Tuesday positions. ~3-day lag.",
        "contracts":  {},
        "composite":  {},
    }

    current_year = date.today().year
    csv_text     = download_cot_csv(current_year)

    if not csv_text:
        log.error("Could not download CFTC data")
        output["error"] = "download_failed"
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(json.dumps(output, indent=2))
        return output

    log.info("Parsing COT CSV (%d chars)", len(csv_text))
    all_rows = parse_cot_csv(csv_text)
    log.info("Total rows parsed: %d", len(all_rows))

    # ── Process each contract ─────────────────────────────────────────────────
    composite_scores = []

    for market_name, cfg in CFTC_CONTRACTS.items():
        log.info("Extracting: %s", cfg["label"])
        contract_rows = extract_contract(all_rows, market_name)

        if not contract_rows:
            log.warning("  No rows found for: %s", market_name)
            output["contracts"][cfg["key"]] = {
                "error": "not_found",
                "label": cfg["label"],
                "market_name_searched": market_name,
            }
            continue

        latest   = contract_rows[0]
        previous = contract_rows[1] if len(contract_rows) > 1 else None

        # Parse key fields
        oi           = safe_int(latest.get("Open_Interest_All"))
        mm_long      = safe_int(latest.get("M_Money_Positions_Long_All"))
        mm_short     = safe_int(latest.get("M_Money_Positions_Short_All"))
        mm_spread    = safe_int(latest.get("M_Money_Positions_Spread_All"))
        prod_long    = safe_int(latest.get("Prod_Merc_Positions_Long_All"))
        prod_short   = safe_int(latest.get("Prod_Merc_Positions_Short_All"))
        nonrep_long  = safe_int(latest.get("NonRept_Positions_Long_All"))
        nonrep_short = safe_int(latest.get("NonRept_Positions_Short_All"))

        net_lots = (
            ((mm_long or 0) - (mm_short or 0))
            if mm_long is not None and mm_short is not None
            else None
        )

        # Date parsing (YYMMDD → readable)
        raw_date = latest.get("As_of_Date_In_Form_YYMMDD", "")
        try:
            report_date = datetime.strptime(raw_date, "%y%m%d").strftime("%Y-%m-%d")
        except ValueError:
            report_date = raw_date

        signal_data = compute_positioning_signal(net_lots, oi)
        wow_data    = compute_weekly_change(latest, previous)

        output["contracts"][cfg["key"]] = {
            "label":           cfg["label"],
            "market_name":     market_name,
            "report_date":     report_date,
            "open_interest":   oi,
            "mm_longs":        mm_long,
            "mm_shorts":       mm_short,
            "mm_spread":       mm_spread,
            "mm_net_lots":     net_lots,
            "net_pct_of_oi":   signal_data.get("net_pct_of_oi"),
            "prod_longs":      prod_long,
            "prod_shorts":     prod_short,
            "nonrep_longs":    nonrep_long,
            "nonrep_shorts":   nonrep_short,
            "signal":          signal_data["signal"],
            "signal_note":     signal_data.get("note", ""),
            "oil_market_note": cfg["signal_note"],
            **wow_data,
        }

        log.info(
            "  %s: OI=%s | MM_net=%s lots | net_pct=%.1f%% | signal=%s | wow=%s",
            cfg["label"],
            f"{oi:,}" if oi else "N/A",
            f"{net_lots:,}" if net_lots else "N/A",
            signal_data.get("net_pct_of_oi") or 0,
            signal_data["signal"],
            wow_data.get("wow_direction", "N/A"),
        )

        score_map = {
            "CROWDED_LONG":  -0.5,   # contrarian bearish — mean-reversion risk
            "BULLISH":        1.0,
            "NEUTRAL":        0.0,
            "BEARISH":       -1.0,
            "CROWDED_SHORT":  0.5,   # contrarian bullish — squeeze risk
        }
        composite_scores.append(score_map.get(signal_data["signal"], 0))

    # ── Composite positioning signal ──────────────────────────────────────────
    if composite_scores:
        avg_score = sum(composite_scores) / len(composite_scores)
        composite_signal = (
            "BULLISH"        if avg_score > 0.4
            else "BEARISH"   if avg_score < -0.4
            else "NEUTRAL"
        )
    else:
        avg_score        = 0
        composite_signal = "NEUTRAL"

    crowded_longs  = [k for k, v in output["contracts"].items()
                      if isinstance(v, dict) and v.get("signal") == "CROWDED_LONG"]
    crowded_shorts = [k for k, v in output["contracts"].items()
                      if isinstance(v, dict) and v.get("signal") == "CROWDED_SHORT"]

    output["composite"] = {
        "signal":            composite_signal,
        "avg_score":         round(avg_score, 3),
        "crowded_longs":     crowded_longs,
        "crowded_shorts":    crowded_shorts,
        "crowding_risk_note": (
            f"CROWDED LONGS detected in: {', '.join(crowded_longs)}. Mean-reversion risk."
            if crowded_longs else
            f"CROWDED SHORTS detected in: {', '.join(crowded_shorts)}. Short-squeeze risk."
            if crowded_shorts else
            "No extreme crowding detected across energy contracts."
        ),
        "market_context": (
            "CFTC positioning is a sentiment/flow indicator, not a fundamental driver. "
            "Crowded positioning amplifies price moves — it does not cause them. "
            "Most powerful when combined with physical signals: "
            "Cushing draw + crowded long = unsustainable; "
            "Cushing draw + crowded short = short-squeeze setup."
        ),
    }

    # ── Save ──────────────────────────────────────────────────────────────────
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    log.info("Saved → %s", OUTPUT_PATH)
    log.info(
        "CFTC composite: %s | crowded_longs=%s | crowded_shorts=%s",
        composite_signal,
        crowded_longs or "none",
        crowded_shorts or "none",
    )

    return output


if __name__ == "__main__":
    run()

# Energy Signal — Energy Markets Intelligence Dashboard

A professional-grade, multi-source energy markets intelligence system built for oil trading desks. The dashboard aggregates causal signals across supply, demand, refining, macro, and geopolitical dimensions into a single composite directional score, with the analytical framework grounded in physical oil market fundamentals.

Built as part of a Futures First training project; analytical methodology drawn from *Oil Macro Trading — A Complete Grounding in the Global Oil Market*.

---

## What It Does

Energy Signal ingests live and scheduled data from over a dozen free APIs and scraped sources, runs them through a scored signal layer, and surfaces a composite directional indicator for Brent crude alongside supporting context across six analytical dimensions. The system is designed to answer three questions: **what is happening**, **why it is happening**, and **what is likely to happen next**.

---

## Architecture Overview

```
Data Sources (APIs, CSVs, scrape)
        │
        ▼
Fetcher Layer  ──────────────────────────────────────────────────────────────
  eia_fetcher.py          │  10 EIA WPSR series (tables 1, 2, 4)
  fred_fetcher.py         │  FRED: DXY, DFF, SOFR, DGS10
  futures_fetcher.py      │  Yahoo/Stooq: BZ=F, CL=F, RB=F, HO=F
  baker_hughes_fetcher.py │  AOGR.com rig count, 10-week rolling history
  wcs_fetcher.py          │  Alberta Economic Dashboard API (WCS/WTI to 1986)
  quality_spreads_fetcher │  Light-heavy, sweet-sour differentials
  duc_fetcher.py          │  EIA Drilling Productivity Report (DUC wells)
  news_fetcher.py         │  8 RSS sources with credibility weights + decay
  geo_scorer.py           │  Three-dimension geopolitical risk → $/bbl premium
        │
        ▼
Engine Layer  ───────────────────────────────────────────────────────────────
  crack_spread_engine.py  │  3-2-1, gasoline crack, HO-RBOB, Brent-WTI,
                          │  ICE Gasoil crack, forward curve shape
  nci_composite.py        │  Composite Index score (–10 to +10)
        │
        ▼
API Layer  ──────────────────────────────────────────────────────────────────
  api.py (FastAPI + APScheduler)
  • Futures / crack / composite    every 5 min
  • Inventory / EIA                every 30 min
  • FRED / GIE / weather           every hour
  • CFTC                           Fridays
        │
        ▼
Frontend (React + Vite + Tailwind)
  Six tabs: Overview · Prices · Spreads · Inventory · Macro · Sentiment
  Futures Curve tab with M1–M12 synthetic curve and calendar spreads
```

---

## Signal Architecture

The Composite Index aggregates eight signal layers, each scored on a –10 to +10 scale and weighted by their analytical priority in the physical oil market:

| Signal Layer | Weight | Primary Source |
|---|---|---|
| Inventory | 25% | EIA WPSR, GIE AGSI+, IEA OMR |
| Crack Spreads | 20% | NYMEX RBOB/HO vs WTI; ICE Gasoil vs Brent |
| Price Momentum | 15% | Yahoo Finance / Stooq futures |
| Macro | 13% | FRED: DXY, SOFR, DFF, DGS10 |
| Positioning | 10% | CFTC Commitments of Traders (weekly) |
| Demand | 9% | EIA implied demand, Open-Meteo HDD/CDD |
| News / Geopolitical | 8% | RSS + LM dictionary + oil-specific overrides |
| GIE Gas Storage | 5% | GIE AGSI+ European gas injection rates |

Inventory and crack spreads carry the highest weights because they are the most direct, observable indicators of physical supply-demand balance, as specified in the book's analytical framework. Momentum confirms rather than overrides fundamentals and is capped at ±8 to prevent it dominating the composite.

### Geopolitical Risk Scoring

News events are scored across three dimensions using the framework from *Oil Macro Trading* Chapter 10:

- **Supply at risk (mbd)** — 40% weight, scaled 2–10 pts
- **Global spare capacity buffer** — 40% weight, scaled 2–10 pts
- **Duration uncertainty** — 20% weight, scaled 2–10 pts

The composite score maps to an implied $/bbl risk premium (2–4 pts → $2–5/bbl through to 10 pts → $25–50/bbl). Geopolitical headlines that are bullish for supply risk (Iran, IRGC, Hormuz, Houthi) are corrected via oil-specific dictionary overrides, since the standard LM financial dictionary scores supply-disruption language as bearish.

---

## Dashboard Tabs

### Overview
- Composite Index gauge (–10 to +10) with signal layer breakdown
- `AlertBanner` (sticky, auto-updating): flags ≥2% and ≥4% price deviations vs 5-day rolling average
- `PriceMomentumBar` per commodity: live price, 5-day deviation (labelled *volatility*), 5-week deviation (labelled *trend*)
- Dual-average alert system covering both 5-day and 5-week windows

### Prices
- Live Brent, WTI, RBOB, HO/ULSD prices with source and data-delay labels
- Brent-WTI spread with signal interpretation: >$8/bbl flags US export bottleneck or North Sea disruption; <$2/bbl flags US exports flooding market
- ±1σ Recharts bands on all price series

### Spreads
- 3-2-1 crack spread: `[(2 × RBOB) + (1 × ULSD) − (3 × WTI)] / 3`
- Gasoline crack, HO-RBOB spread, Brent-WTI, ICE Gasoil crack (unit-converted $/bbl)
- WCS quality spread (Alberta heavy vs WTI light-sweet differential)
- Forward curve shape indicator: backwardation vs contango signal

### Futures Curve
- M1–M12 synthetic WTI curve with daily snapshots via `curve_history.py`
- Calendar spreads: M1-M2, M1-M3, M1-M6, M1-M12
- Butterfly spreads: M1/M3/M5
- 125-day history backfilled via `curve_backfill.py`
- Quality spreads history via `qs_backfill.py`

### Inventory
- EIA WPSR: crude stocks, Cushing, gasoline, distillates — WoW change vs Reuters/Bloomberg consensus
- Deviation from 5-year seasonal average (the IEA/OPEC benchmark tightness metric)
- Days of forward demand cover: `Total Commercial Stocks ÷ Daily Demand`
  - <54 days historically associated with $90+ Brent
- GIE AGSI+ European gas storage: injection rate vs 5-year seasonal average, binary above/below flags for major markets
- US SPR level (post-2022 release context)

### Macro
- FRED series: DXY (dollar index), DFF (Fed Funds), SOFR (storage financing cost), DGS10 (10-year yield)
- CFTC Commitments of Traders: managed money net positioning, extreme positioning flags
- TTF natural gas and EUA carbon price context

### Sentiment
- News sentiment score: 8 RSS sources with per-source credibility weights and decay half-lives
- Special handling for EIA WPSR Wednesday releases, OPEC meetings, IEA OMR publications
- Geopolitical risk premium in $/bbl with three-dimension scoring
- Signal divergence detection: composite vs price momentum

---

## Data Sources

### Free / Open APIs

| Source | Data | Update Frequency |
|---|---|---|
| EIA Open API (`ir.eia.gov/wpsr/`) | Crude stocks, Cushing, gasoline, distillates, production, refinery utilisation | Weekly (Wed 10:30 EST) |
| EIA Drilling Productivity Report | DUC well inventory by basin | Monthly |
| EIA STEO (`eia.gov/steo`) | Global supply/demand balance revisions | Monthly (2nd week) |
| FRED (`fred.stlouisfed.org`) | DXY, DFF, SOFR, DGS10 | Daily / as published |
| GIE AGSI+ | European gas storage injection and levels | Daily |
| CFTC | Commitments of Traders (managed money positioning) | Weekly (Fri) |
| Baker Hughes / AOGR.com | US oil rig count, 10-week rolling | Weekly (Fri) |
| Alberta Economic Dashboard | WCS/WTI differential history to 1986 | Weekly |
| Open-Meteo | HDD/CDD (5-year seasonal average, US NE + N. Europe) | Daily |
| Stooq (primary) / Yahoo Finance (fallback) | BZ=F, CL=F, RB=F, HO=F futures | ~15-min delay |

### Paid Data (Priority When Budget Allows)
- **Kpler / Vortexa** — tanker tracking, floating storage, crude flow origin-destination
- **Barchart (LFY00)** — ICE Gasoil live feed (current Yahoo data shows stale ~$124/MT vs ~$800/MT real; rejected by sanity-check threshold at $50/bbl equivalent)
- **Baltic Exchange / Clarksons / Fearnleys** — TD3C VLCC freight rates

---

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.14, FastAPI, APScheduler |
| Frontend | React, Vite, Tailwind CSS, Recharts |
| Proxy | Cloudflare Worker |
| Dev environment | GitHub Codespaces |
| Repo | `ipsanmoljj/energy-dashboard` |
| Local path | `C:\projects\energy-dashboard` |

---

## Getting Started

```bash
# In Codespaces — pull latest and run the full startup script
git pull
bash start.sh
```

`start.sh` starts the FastAPI backend, runs all fetchers in sequence, initialises the scheduler, and runs a keepalive ping loop to prevent Codespace hibernation.

Individual fetchers can be run manually:

```bash
python backend/fetchers/eia_fetcher.py
python backend/fetchers/fred_fetcher.py
python backend/fetchers/futures_fetcher.py
python backend/fetchers/baker_hughes_fetcher.py
python backend/fetchers/news_fetcher.py
```

Session management:

```bash
bash start.sh            # Start everything
bash stop.sh             # Graceful shutdown
bash restart_fetchers.sh # Restart fetchers only (keep API running)
```

---

## Repository Structure

```
energy-dashboard/
├── backend/
│   ├── api.py                      # FastAPI app + APScheduler
│   ├── fetchers/
│   │   ├── eia_fetcher.py
│   │   ├── fred_fetcher.py
│   │   ├── futures_fetcher.py
│   │   ├── baker_hughes_fetcher.py
│   │   ├── wcs_fetcher.py
│   │   ├── quality_spreads_fetcher.py
│   │   ├── duc_fetcher.py
│   │   └── news_fetcher.py
│   ├── engines/
│   │   ├── crack_spread_engine.py
│   │   ├── nci_composite.py
│   │   └── geo_scorer.py
│   ├── history/
│   │   ├── curve_backfill.py       # 125-day Yahoo Finance history
│   │   ├── curve_history.py        # Daily curve snapshots
│   │   └── qs_backfill.py          # Quality spreads history
│   └── data/                       # Runtime JSON outputs (gitignored)
├── frontend/
│   └── src/
│       ├── App.jsx
│       └── components/
│           ├── AlertBanner.jsx
│           ├── PriceMomentumBar.jsx
│           ├── CountdownDisplay.jsx
│           └── [tab components]
├── logs/
│   └── .gitkeep
├── start.sh
├── stop.sh
├── restart_fetchers.sh
└── README.md
```

Data files in `backend/data/` are gitignored and do not persist between Codespace sessions. Run `bash start.sh` at the start of each session to repopulate.

---

## Key Analytical Principles

**Brent and WTI are independent benchmarks.** Estimating one from the other destroys analytical value — the spread between them is itself the signal (Cushing inventory levels, US export capacity, North Sea disruptions). Only RBOB can be estimated from HO (both refined products, both NYH delivery). Where data is unavailable, the dashboard shows `INSUFFICIENT_DATA` rather than synthesising a proxy price.

**The Composite Index is not "NCI".** The Nelson Complexity Index (NCI) is a refinery complexity metric from the analytical framework. The dashboard's composite output is the "Composite Index." NCI refers only to the refinery-complexity-weighted signal layer inside the model.

**ICE Gasoil is labelled "ULSD" throughout.** Consistent with how the contract is referenced on a trading desk (the contract has been spec'd as ultra-low-sulphur diesel since 2013).

**5-year seasonal average, not 30-year normal.** Inventory deviations use the 5-year seasonal average as specified in the IEA/OPEC methodology — the standard tightness reference for OECD commercial stocks.

**Signal divergence is not a bug.** The Composite Index measures structural fundamental conditions. If Brent declines while fundamentals remain bullish, the divergence is real information — the price momentum layer was added specifically to capture this and prevent the composite from being a purely lagging fundamental indicator.

---

## Quantitative Framework

A separate R repository (`ipsanmoljj/futures-curves`) contains a regression-based signal weighting framework using minute-level WTI (CL) and Brent (LCO) futures data from January 2022 across M1–M14 contract months. The current composite weights are judgment-based; empirical validation via regression of weekly Brent price changes against each signal layer is the intended next step for weight calibration.

---

## Roadmap

- Replace synthetic M1–M4 WTI curve with EIA live series `RCLC1`–`RCLC4` via EIA v2 API
- Integrate EIA STEO monthly global supply/demand balance revisions as a dedicated signal (track revision direction month-over-month)
- ICE Gasoil live feed via Barchart LFY00 (pending API key)
- Apify Yahoo Finance connector for rate-limit bypass on futures fetches (`APIFY_TOKEN` already in environment)
- Empirical weight validation in `ipsanmoljj/futures-curves` R repo
- Deploy backend to Railway, frontend to Vercel

---

## Environment Variables

| Variable | Used By |
|---|---|
| `EIA_API_KEY` | `eia_fetcher.py` (prefix: `jIklUoLi`) |
| `APIFY_TOKEN` | Yahoo Finance rate-limit bypass (not yet implemented) |

---

*Analytical framework: Oil Macro Trading — A Complete Grounding in the Global Oil Market (Futures First internal training material)*

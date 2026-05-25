# Energy Markets Dashboard — Project Brief

## What we are building
A live energy markets decision-support dashboard that shows:
what is happening in oil/energy markets, why it is happening,
and what is likely to happen next.

## Tech stack
- Backend: Python 3.12 + FastAPI + APScheduler
- Frontend: React + Vite + Tailwind CSS
- Proxy: Cloudflare Worker (for CORS-blocked sources)
- Deploy: Backend on Railway, Frontend on Vercel
- Realtime: WebSocket from FastAPI to React

## Project structure
energy-dashboard/
├── backend/
│   ├── main.py              # FastAPI app
│   ├── fetchers/            # one file per data source
│   ├── signals/             # derived metrics + scoring
│   ├── sentiment/           # news pipeline
│   └── scheduler.py         # APScheduler triggers
├── frontend/
│   ├── src/
│   │   ├── panels/          # one component per dashboard panel
│   │   └── hooks/           # useWebSocket, useSignals etc
├── proxy/
│   └── worker.js            # Cloudflare Worker
└── CLAUDE.md

## Data sources

### Free APIs (direct, no proxy)
- EIA Open API: api.eia.gov/v2 — crude/Cushing stocks, gasoline,
  distillates, refinery util, crude production, implied demand,
  exports, STEO monthly, Dated Brent (RBRTE). Key: env EIA_API_KEY
- FRED API: api.stlouisfed.org/fred — DXY (DTWEXBGS), SOFR,
  Fed Funds (FEDFUNDS), CPI (CPIAUCSL), 10Y yield (DGS10),
  WTI (DCOILWTICO), Brent (DCOILBRENTEU). Key: env FRED_API_KEY
- GIE AGSI+: agsi.gie.eu/api — European gas storage by country,
  injection rate vs 5yr avg. No key needed.
- Open-Meteo: api.open-meteo.com — temperature for US NE + N.Europe,
  compute HDD/CDD. No key needed.
- GDELT: api.gdeltproject.org — geopolitical events, CAMEO codes
  173=sanctions, 190=military, 111=energy. No key needed.
- NewsAPI: newsapi.org — 100 req/day free. Key: env NEWS_API_KEY
  Query: "OPEC" OR "crude oil" OR "Hormuz" OR "sanctions" OR "Houthi"
- UN Comtrade: comtradeapi.un.org — China crude imports HS 2709.
  500 req/day free.
- aisstream.io: WebSocket AIS feed — filter vessel type 80-89 (tankers).
  Speed <0.5 knots + anchored >48h near crude hub = floating storage.
- Ember: ember-energy.org/api — EUA carbon price proxy.
- Stooq: stooq.com/q/d/l/?s=^bdi — Baltic Dry Index CSV. No key.
- TwelveData: twelvedata.com — TTF nat gas proxy. 800 req/day free.
  Key: env TWELVEDATA_API_KEY

### Proxy-required (via Cloudflare Worker)
- Yahoo Finance: BZ=F (Brent), CL=F (WTI), RB=F (RBOB), HO=F (ULSD),
  NG=F (Henry Hub), DX-Y.NYB (DXY). ~15min delay. CORS blocked.
- CFTC COT: cftc.gov/dea/newcot/ — managed money net long/short.
  Published Friday ~3:30 PM EST. CSV.
- Baker Hughes: rigcount.bakerhughes.com — weekly rig count by basin.
  Published Friday 1 PM EST. XLS.
- OPEC MOMR: opec.org — monthly PDF. Parse server-side.
- Ship & Bunker: shipandbunker.com — bunker prices, freight proxy.

### News feeds for sentiment
- AP Energy RSS: feeds.content.ap.org/rss/tag_energy.rss
- OilPrice.com RSS: oilprice.com/rss/main
- EIA RSS: eia.gov/rss/news.xml
- OPEC RSS: opec.org/opec_web/en/press_room/rss.htm
- IEA news: iea.org/news.xml
- NewsAPI keyword queries (see above)
- GDELT full-text with CAMEO filtering

## Signal layer

### Inventory signals
- WoW change for each series
- Deviation from 5yr seasonal average
- Days of forward demand cover = total_stocks_mmbbls / demand_mbd
  - <54 days = historically tight (bullish, associated with $90+ Brent)
  - 54-62 days = normal
  - >62 days = historically loose (bearish)
- Cushing surprise = actual WoW vs Reuters consensus estimate

### Crack spreads
- 3-2-1 crack = [(2 x RBOB) + (1 x ULSD) - (3 x WTI)] / 3
- ICE Gasoil crack = Gasoil($/MT) / 7.45 - Brent($/bbl)
- Brent-WTI spread: >$8 = US export bottleneck; <$2 = US exports flooding
- M1-M2 time spread: positive = backwardation (tight); negative = contango

### NCI Signal Layer (per crude grade)
- SHORT (1-8w): NCI-Weighted Util Divergence + crack spread by config
- MEDIUM (1-6m): NCI Capacity Change Rate + Quality Spread Mean Reversion
- LONG (6-24m): NCI Capacity Pipeline (FID) + Crude Grade Demand Forecast
- REGIME: NCI Fleet Composition Shift
- All signals → Composite NCI Score (-10 to +10) per crude grade

### Geopolitical risk scorer
Score = (supply_at_risk_score x 0.4) + (spare_capacity_score x 0.4)
        + (duration_score x 0.2)
Supply at risk: <0.5mbd=2, 0.5-1=4, 1-2=6, 2-4=8, >4=10
Spare capacity: >4mbd=2, 2-4=5, 1-2=8, <1=10
Duration: days-weeks=2, weeks-months=5, multi-year=8, permanent=10
Price premium: 2-4pts=$2-5/bbl, 5-6=$5-10, 8-9=$15-25, 10=$25-50

### Composite bull/bear score
Each signal votes +1 (bullish) / -1 (bearish) / 0 (neutral)
Aggregate across all modules → overall market direction signal

## Sentiment pipeline
1. Ingest: RSS feeds + NewsAPI + GDELT every 15 minutes
2. Triage: Custom energy dictionary (fast, zero latency)
   Bullish words: draw, cut, disruption, outage, Hormuz, tight, deficit
   Bearish words: build, surplus, compliance, rerouted, oversupply, weak
3. Score: FinBERT via HuggingFace for financial headlines
4. Deep score: Anthropic API (Claude) only for high-scoring geo events
5. Output: sentiment_score per article → directional vote → rolling 24h avg

## Key data events (scheduler triggers)
- Wednesday 10:30 EST: EIA Weekly Petroleum Status → refresh all inventory signals
- Friday 1:00 PM EST: Baker Hughes rig count → refresh upstream signals
- Friday 3:30 PM EST: CFTC COT → refresh positioning signals
- Monthly 2nd week: EIA STEO → refresh supply/demand balance
- Monthly ~5th: Saudi Aramco OSP → refresh quality spread signals
- Every 5 min: Yahoo Finance futures prices
- Every 15 min: News feeds + GDELT

## Reference file
backend/fetchers/eia_heartbeat.py — already built, use as pattern
for all other fetchers. Has mock mode (--mock flag) for offline dev.

## Build stages
Stage 1 (Days 1-3): Data fetchers for all sources
Stage 2 (Days 4-6): Signal layer + NCI scorer
Stage 3 (Days 7-8): Sentiment pipeline
Stage 4 (Days 9-10): FastAPI backend + scheduler + WebSocket
Stage 5 (Days 11-16): React frontend panels
Stage 6 (Days 17-18): Deploy to Railway + Vercel

## Environment variables needed
EIA_API_KEY=
FRED_API_KEY=
NEWS_API_KEY=
TWELVEDATA_API_KEY=
ANTHROPIC_API_KEY=

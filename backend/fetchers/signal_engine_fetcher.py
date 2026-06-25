"""
signal_engine_fetcher.py — bridges demsup's R-based daily trade signal engine
(R/signal_engine.R, "Layer A" per the backtesting handover doc) into the dashboard.

signal_engine.R is a deterministic, fully rule-based signal: it reads the regime
classifier's level_z_126 + regime label, applies a per-product threshold and a
volatility/regime gating cascade, and outputs BUY/SELL/FLAT for the most recent
non-warmup bar. It is NOT an ML model — there's no "predict" step beyond that
threshold check, so "live" here just means "today's row run through the same
gates as the validated historical backtest."

This fetcher calls the SAME plumber service as demsup_fetcher.py (port 8001),
hitting the /signal endpoint added alongside /regime:

    GET http://localhost:8001/signal?product_code=CL
    -> {
         "live": {
             "product": "CL", "date": "2026-06-17", "regime": "Deep-Backwardation",
             "m1m2": 1.23, "level_z": 2.41, "atr14": 0.087, "vol_gate_pass": true,
             "vol_gate": "none", "threshold": 1.00, "signal": "SELL", "unit": "$/bbl",
             "stop_dist": 0.2175, "hard_stop": 1.0125, "atr_multiplier": 2.5
         },
         "summary": {
             "product": "CL", "unit": "$/bbl", "n_trades": 310, "hit_pct": 57.4,
             "rr": 2.08, "ev_trade": 0.3322, "ev_be": -0.0342, "total_pnl": 102.9953,
             "max_dd": -20.9344, "vol_gate": "none"
         }
       }

IMPORTANT — query param is `product_code`, not `product`. The plumber endpoint
deliberately avoids naming it `product` because signal_summary.csv has a column
literally named `product`, and an R data.table filter like dt[product==product]
would silently always evaluate TRUE if the filter variable shared that name —
the same bug class the demsup backtesting handover doc flagged as having
already bitten intraday_signal_engine.R once. Don't rename this param to match
demsup_fetcher.py's /regime?product=CL convention; they're deliberately
different for that reason.

If the service is down, a product's regime fit is missing, or signal_engine.R
errors for any reason, this returns INSUFFICIENT_DATA for that product rather
than fabricating a signal — same principle used throughout this dashboard
(see Brent/WTI independence rule, demsup_fetcher.py).

A note on "trained on historical data, tested on 3-day data": this fetcher does
NOT re-run signal_engine.R's historical backtest or training/validation/test
split — that's already been done once (per the handover doc's train/val/test
discipline) and the result is what's being surfaced. This fetcher only reads
today's already-gated signal and the already-computed test-window performance
stats. It does not retrain, re-validate, or re-open the test window.
"""

import json
import logging
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("signal_engine_fetcher")

ROOT     = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUT_FILE = DATA_DIR / "signal_engine_latest.json"

DEMSUP_BASE_URL = os.environ.get("DEMSUP_BASE_URL", "http://localhost:8001")

# demsup product code -> dashboard product key (same mapping as demsup_fetcher.py,
# kept in sync deliberately — these two fetchers describe the same four products)
PRODUCT_MAP = {
    "CL":  "wti",
    "LCO": "brent",
    "HO":  "ho",
    "LGO": "lgo",
}


def _unwrap(v):
    """
    jsonlite wraps scalar values in length-1 arrays by default (confirmed via
    the real plumber /regime response — see demsup_fetcher.py). Applies the
    same defensive unwrap here since /signal uses the same serializer.
    """
    if isinstance(v, list):
        return v[0] if len(v) == 1 else v
    if isinstance(v, dict):
        return {k: _unwrap(vv) for k, vv in v.items()}
    return v


def fetch_signal(product_code, timeout=8):
    """Call demsup's plumber /signal endpoint for one product. Returns dict or None."""
    url = f"{DEMSUP_BASE_URL}/signal?product_code={product_code}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "energy-dashboard"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        data = _unwrap(data)
        if not data or "live" not in data or not data.get("live"):
            log.warning("signal_engine %s: malformed/empty response %s", product_code, data)
            return None
        return data
    except urllib.error.URLError as e:
        log.warning("signal_engine %s: service unreachable (%s) — is plumber running on :8001?", product_code, e)
        return None
    except Exception as e:
        log.warning("signal_engine %s failed: %s", product_code, e)
        return None


def run():
    DATA_DIR.mkdir(exist_ok=True)

    signals = {}
    for demsup_code, dash_key in PRODUCT_MAP.items():
        raw = fetch_signal(demsup_code)
        if raw is None:
            signals[dash_key] = {
                "status":       "INSUFFICIENT_DATA",
                "live":         None,
                "summary":      None,
                "note":         "signal engine service unreachable, or regime_labels CSV missing — start plumber API on :8001 and confirm classify_regimes() has run for this product",
            }
            continue

        signals[dash_key] = {
            "status":  "OK",
            "live":    raw.get("live"),
            "summary": raw.get("summary"),
        }
        live = raw.get("live") or {}
        log.info("signal %-4s -> %-6s regime=%-22s z=%s gate=%s",
                  demsup_code,
                  live.get("signal") or "—",
                  live.get("regime") or "—",
                  live.get("level_z"),
                  "PASS" if live.get("vol_gate_pass") else "BLOCKED")

    output = {
        "fetcher":    "signal_engine_fetcher",
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source":     "demsup R/signal_engine.R — Layer A daily M1M2 mean-reversion signal (level_z_126-based)",
        "note":       "Rule-based deterministic signal, not an ML model. 'live' reflects today's gated signal; 'summary' is the validated test-window backtest (Jul 2024-May 2026, opened once). See backtesting handover doc for train/validation/test discipline — do not treat repeated /signal polls as re-opening or re-validating the test window.",
        "signals":    signals,
    }

    OUT_FILE.write_text(json.dumps(output, indent=2))
    print("signal_engine fetcher done:")
    for k, v in signals.items():
        sig = (v.get("live") or {}).get("signal") if v["status"] == "OK" else "—"
        print(f"  {k:6s} {v['status']:16s} {sig}")
    return output


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
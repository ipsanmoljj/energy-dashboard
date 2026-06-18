"""
regime_history_fetcher.py — pulls the FULL historical daily regime classification
per product from demsup's plumber service, for the Futures Curve tab's regime
history timeline + z-score chart.

This is a different endpoint from demsup_fetcher.py's /regime (latest row only) —
it calls /regime-history, which returns one row per non-warmup trading day,
going back to whenever the warm-up period ends (~2021-09 for these four products,
189 bars excluded per classify_regimes()'s warmup logic).

Output shape, written to regime_history_latest.json:
{
  "fetched_at": "...",
  "products": {
    "wti":   { "status": "OK", "history": [...], "segments": [...] },
    "brent": { ... },
    "ho":    { ... },
    "lgo":   { ... }
  }
}

"history" is the raw daily series: [{date, regime_label, level_z_126, m1m2, ...}, ...]
"segments" is a derived, contiguous-block summary for the timeline strip:
  [{regime_label, start_date, end_date, n_days}, ...]
computed here in Python from the raw daily series (consecutive identical
regime_label values collapsed into one block) — NOT something demsup's R side
computes or returns; this is purely a frontend-rendering convenience derived
from the same data classify_regimes() already produced.
"""

import json
import logging
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("regime_history_fetcher")

ROOT     = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUT_FILE = DATA_DIR / "regime_history_latest.json"

DEMSUP_BASE_URL = "http://localhost:8001"

PRODUCT_MAP = {
    "CL":  "wti",
    "LCO": "brent",
    "HO":  "ho",
    "LGO": "lgo",
}


def _unwrap(v):
    """jsonlite wraps scalars in length-1 arrays — see demsup_fetcher.py."""
    if isinstance(v, list):
        if len(v) == 1:
            return _unwrap(v[0])
        return [_unwrap(x) for x in v]
    if isinstance(v, dict):
        return {k: _unwrap(vv) for k, vv in v.items()}
    return v


def _build_segments(history):
    """
    Collapse a daily regime_label series into contiguous blocks, for the
    timeline strip. Does NOT rely on the R side's regime_id directly — building
    it independently here from regime_label equality is more robust to regime_id
    meaning something slightly different than expected (e.g. if it's keyed to
    structural-break epochs rather than label changes within an epoch; safer
    to just collapse on the label itself, which is exactly what the timeline
    strip needs to show regardless of how regime_id is defined upstream).
    """
    segments = []
    for row in history:
        label = row.get("regime_label")
        date  = row.get("date")
        if not label or not date:
            continue
        if segments and segments[-1]["regime_label"] == label:
            segments[-1]["end_date"] = date
            segments[-1]["n_days"]  += 1
        else:
            segments.append({
                "regime_label": label,
                "start_date":   date,
                "end_date":     date,
                "n_days":       1,
            })
    return segments


def fetch_history(product_code, timeout=15):
    """Call demsup's plumber /regime-history endpoint for one product."""
    url = f"{DEMSUP_BASE_URL}/regime-history?product={product_code}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "energy-dashboard"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        data = _unwrap(data)
        if not data or "history" not in data or not isinstance(data.get("history"), list):
            log.warning("regime_history %s: malformed response", product_code)
            return None
        return data
    except urllib.error.URLError as e:
        log.warning("regime_history %s: service unreachable (%s)", product_code, e)
        return None
    except Exception as e:
        log.warning("regime_history %s failed: %s", product_code, e)
        return None


def run():
    DATA_DIR.mkdir(exist_ok=True)

    products = {}
    for demsup_code, dash_key in PRODUCT_MAP.items():
        raw = fetch_history(demsup_code)
        if raw is None:
            products[dash_key] = {
                "status":   "INSUFFICIENT_DATA",
                "history":  [],
                "segments": [],
                "note":     "regime history unavailable — check plumber /regime-history endpoint",
            }
            continue

        history  = raw.get("history") or []
        segments = _build_segments(history)
        products[dash_key] = {
            "status":   "OK",
            "history":  history,
            "segments": segments,
        }
        log.info("regime_history %-4s -> %d days, %d regime segments",
                  demsup_code, len(history), len(segments))

    output = {
        "fetcher":    "regime_history_fetcher",
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source":     "demsup regime classifier — full daily history per product (non-warmup days only)",
        "products":   products,
    }

    OUT_FILE.write_text(json.dumps(output, indent=2))
    print("regime_history fetcher done:")
    for k, v in products.items():
        n = len(v.get("history", []))
        print(f"  {k:6s} {v['status']:16s} {n} days, {len(v.get('segments', []))} segments")
    return output


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
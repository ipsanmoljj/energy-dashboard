"""
demsup_fetcher.py — bridges the demsup R regime-classification service into the dashboard.

demsup is a SEPARATE R project (github.com/ipsanmoljj/demsup) that runs Bai-Perron
structural break detection + Kalman filter + Markov switching + ARIMA consensus on
M1-M2 calendar spreads for CL/LCO/HO/LGO, producing an 11-label curve-structure regime
with a confidence score and a cross-product consensus scope. It is NOT ported into
Python — it stays in R because the regime labels have already been validated against
known market history, and a port risks silently diverging from that validation.

This fetcher expects demsup to expose itself as a tiny plumber API (see demsup/plumber.R,
to be added to that repo) with one endpoint:

    GET http://localhost:8001/regime?product=CL
    -> { "product": "CL", "date": "2026-06-17", "regime_label": "Deep-Backwardation",
         "confidence_score": 0.84, "level_z_126": -2.31, "consensus_scope": "GLOBAL" }

If that service isn't running, every product falls back to INSUFFICIENT_DATA rather
than guessing a regime — same principle as the Brent/WTI independence rule: never
fabricate a signal just because a number would look nicer than a gap.

Product mapping: demsup's CL/LCO/HO/LGO map onto the dashboard's wti/brent/ho/(no LGO
slot yet — LGO is ICE Gasoil, tracked here as "ULSD" already covers HO; LGO itself isn't
in the dashboard's four-product grid yet, so it's fetched and stored but not yet wired
to a frontend card).
"""

import json
import logging
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("demsup_fetcher")

ROOT     = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUT_FILE = DATA_DIR / "demsup_latest.json"

DEMSUP_BASE_URL = os.environ.get("DEMSUP_BASE_URL", "http://localhost:8001")

# demsup product code -> dashboard product key
PRODUCT_MAP = {
    "CL":  "wti",
    "LCO": "brent",
    "HO":  "ho",
    "LGO": "lgo",   # not yet on a frontend card; stored for future use
}

# demsup's 11-label taxonomy collapsed down to the dashboard's existing 5-state
# Curve Structure vocabulary, so the Overview composite gauge doesn't need to change.
# This is a many-to-one mapping, not a replacement — the full 11-label regime is
# still shown as the primary readout; this is only for backward-compat scoring.
REGIME_SIMPLIFY = {
    "Deep-Backwardation":          "STRONG_BACKWARDATION",
    "Mild-Backwardation":          "MILD_BACKWARDATION",
    "Easing-Backwardation":        "MILD_BACKWARDATION",
    "Transition-Tightening":       "MILD_BACKWARDATION",
    "Stable-Elevated":             "FLAT",
    "Flat":                        "FLAT",
    "Stable-Depressed":            "FLAT",
    "Transition-Loosening":        "MILD_CONTANGO",
    "Easing-Contango":             "MILD_CONTANGO",
    "Mild-Contango":               "MILD_CONTANGO",
    "Deep-Contango":               "DEEP_CONTANGO",
    "Warm-Up":                     None,  # not enough history yet — leave unmapped
}


def _unwrap(v):
    """
    jsonlite (R's JSON serializer) wraps scalar values in length-1 arrays by
    default — confirmed via the actual plumber response: regime_label comes
    back as ["Stable-Elevated"] not "Stable-Elevated". Unwrap defensively so
    downstream code gets plain scalars, not single-element lists.
    """
    if isinstance(v, list):
        return v[0] if len(v) == 1 else v
    return v


def fetch_regime(product_code, timeout=8):
    """Call demsup's plumber endpoint for one product. Returns dict or None."""
    url = f"{DEMSUP_BASE_URL}/regime?product={product_code}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "energy-dashboard"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        if not data or "regime_label" not in data:
            log.warning("demsup %s: malformed response %s", product_code, data)
            return None
        # Unwrap every field — jsonlite wraps scalars in length-1 lists.
        return {k: _unwrap(v) for k, v in data.items()}
    except urllib.error.URLError as e:
        log.warning("demsup %s: service unreachable (%s) — is plumber running on :8001?", product_code, e)
        return None
    except Exception as e:
        log.warning("demsup %s failed: %s", product_code, e)
        return None


def run():
    DATA_DIR.mkdir(exist_ok=True)

    regimes = {}
    for demsup_code, dash_key in PRODUCT_MAP.items():
        raw = fetch_regime(demsup_code)
        if raw is None:
            regimes[dash_key] = {
                "status":          "INSUFFICIENT_DATA",
                "regime_label":    None,
                "regime_simple":   None,
                "confidence_score": None,
                "level_z_126":     None,
                "consensus_scope": None,
                "note":            "demsup service unreachable — start plumber API on :8001",
            }
            continue

        label = raw.get("regime_label")
        regimes[dash_key] = {
            "status":           "OK",
            "regime_label":     label,
            "regime_simple":    REGIME_SIMPLIFY.get(label),
            "confidence_score": raw.get("confidence_score"),
            "level_z_126":      raw.get("level_z_126"),
            "consensus_scope":  raw.get("consensus_scope"),
            "date":             raw.get("date"),
        }
        log.info("demsup %-4s -> %-22s conf=%.2f scope=%s",
                  demsup_code, label or "—",
                  raw.get("confidence_score") or 0.0,
                  raw.get("consensus_scope") or "—")

    # Cross-product consensus already comes from demsup per-product (consensus_scope
    # field is the same value on every product for a given date), but compute a local
    # summary too in case products disagree on it due to staggered fetch timing.
    scopes = {v["consensus_scope"] for v in regimes.values() if v.get("consensus_scope")}
    overall_scope = scopes.pop() if len(scopes) == 1 else ("MIXED" if scopes else None)

    output = {
        "fetcher":         "demsup_fetcher",
        "fetched_at":      datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source":          "demsup (R) — Bai-Perron/Kalman/Markov/ARIMA consensus regime classifier",
        "note":            "11-label curve-structure regime, statistically validated against market history. Independent of this dashboard's own slope-threshold signal in curve_fetcher.py — shown alongside it, not replacing it.",
        "regimes":         regimes,
        "consensus_scope": overall_scope,
    }

    OUT_FILE.write_text(json.dumps(output, indent=2))
    print("demsup fetcher done:")
    for k, v in regimes.items():
        print(f"  {k:6s} {v['status']:16s} {v.get('regime_label') or '—'}")
    return output


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
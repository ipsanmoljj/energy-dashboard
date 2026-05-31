import { useState, useEffect, useCallback } from "react"

const API = "http://localhost:8000"

const TABS = [
  { id: "overview",  label: "Overview",  icon: "ti-layout-dashboard" },
  { id: "prices",    label: "Prices",    icon: "ti-chart-line" },
  { id: "spreads",   label: "Spreads",   icon: "ti-arrows-diff" },
  { id: "inventory", label: "Inventory", icon: "ti-building-warehouse" },
  { id: "macro",     label: "Macro",     icon: "ti-world" },
  { id: "sentiment", label: "Sentiment", icon: "ti-news" },
]

// ── Helpers ────────────────────────────────────────────────────────────────

function val(v, decimals = 2, suffix = "") {
  if (v == null || v === "" || isNaN(v)) return "—"
  return Number(v).toFixed(decimals) + suffix
}

function chgColor(v) {
  if (v == null) return "#9ca3af"
  return v > 0 ? "#22c55e" : v < 0 ? "#ef4444" : "#9ca3af"
}

function signalColor(label) {
  if (!label) return "#9ca3af"
  const l = label.toUpperCase()
  if (l.includes("BULL") || l.includes("STRONG") || l.includes("GROW")) return "#22c55e"
  if (l.includes("BEAR") || l.includes("WEAK")   || l.includes("DECL")) return "#ef4444"
  return "#f59e0b"
}

// ── Small reusable components ──────────────────────────────────────────────

function Card({ title, children, style = {} }) {
  return (
    <div style={{
      background: "#111827", border: "1px solid #1f2937",
      borderRadius: 12, padding: "14px 16px", marginBottom: 12, ...style
    }}>
      {title && (
        <div style={{
          fontSize: 11, fontWeight: 600, color: "#6b7280",
          letterSpacing: "0.1em", textTransform: "uppercase",
          marginBottom: 10
        }}>{title}</div>
      )}
      {children}
    </div>
  )
}

function MetricRow({ label, value, unit = "", signal, note }) {
  return (
    <div style={{
      display: "flex", alignItems: "center",
      justifyContent: "space-between",
      padding: "6px 0", borderBottom: "1px solid #1a2234"
    }}>
      <span style={{ fontSize: 12, color: "#9ca3af" }}>{label}</span>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {note && <span style={{ fontSize: 10, color: "#4b5563" }}>{note}</span>}
        {signal && (
          <span style={{
            fontSize: 10, fontWeight: 600,
            color: signalColor(signal),
            background: signalColor(signal) + "22",
            borderRadius: 4, padding: "1px 6px"
          }}>{signal}</span>
        )}
        <span style={{ fontSize: 13, fontWeight: 600, color: "#e5e7eb" }}>
          {value}{unit && <span style={{ fontSize: 10, color: "#6b7280", marginLeft: 2 }}>{unit}</span>}
        </span>
      </div>
    </div>
  )
}

function PriceCard({ label, price, unit, change, color = "#3b82f6" }) {
  const isPos = change > 0
  const isNeg = change < 0
  return (
    <div style={{
      background: "#1a2234", borderRadius: 10,
      border: `1px solid ${color}33`, padding: "12px 14px"
    }}>
      <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color, letterSpacing: "-0.5px" }}>
        {val(price)}
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 4 }}>
        <span style={{ fontSize: 10, color: "#4b5563" }}>{unit}</span>
        {change != null && (
          <span style={{ fontSize: 11, fontWeight: 600, color: chgColor(change) }}>
            {isPos ? "▲" : isNeg ? "▼" : "—"} {val(Math.abs(change))}%
          </span>
        )}
      </div>
    </div>
  )
}

// ── Composite Index gauge ────────────────────────────────────────────────────

function CompositeGauge({ score, label, reasons = [] }) {
  const clamped = Math.max(-10, Math.min(10, score ?? 0))
  const pct     = ((clamped + 10) / 20) * 100
  const color   = clamped > 0.5 ? "#22c55e" : clamped < -0.5 ? "#ef4444" : "#f59e0b"

  return (
    <div style={{ textAlign: "center", padding: "8px 0" }}>
      <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 6,
        letterSpacing: "0.1em", textTransform: "uppercase" }}>
        Composite Index Signal
      </div>
      <div style={{ fontSize: 48, fontWeight: 800, color, lineHeight: 1 }}>
        {score != null ? (clamped > 0 ? "+" : "") + clamped.toFixed(1) : "—"}
      </div>
      <div style={{
        fontSize: 13, fontWeight: 700, color,
        background: color + "22", borderRadius: 20,
        display: "inline-block", padding: "3px 14px", margin: "6px 0"
      }}>{label || "NEUTRAL"}</div>

      {/* Progress bar */}
      <div style={{
        height: 6, background: "#1f2937", borderRadius: 3,
        margin: "10px 0 6px", position: "relative", overflow: "hidden"
      }}>
        <div style={{
          position: "absolute", left: 0, top: 0, bottom: 0,
          width: pct + "%", background: color,
          borderRadius: 3, transition: "width 0.6s ease"
        }} />
        <div style={{
          position: "absolute", left: "50%", top: 0, bottom: 0,
          width: 1, background: "#374151"
        }} />
      </div>
      <div style={{ display: "flex", justifyContent: "space-between",
        fontSize: 9, color: "#4b5563" }}>
        <span>-10 BEARISH</span><span>NEUTRAL</span><span>BULLISH +10</span>
      </div>

      {/* Reason bullets */}
      {reasons.length > 0 && (
        <div style={{ marginTop: 10, textAlign: "left" }}>
          {reasons.map((r, i) => (
            <div key={i} style={{
              fontSize: 11, color: "#9ca3af", padding: "2px 0",
              borderLeft: "2px solid #1f2937", paddingLeft: 8, marginBottom: 3
            }}>· {r}</div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Tab: Overview ──────────────────────────────────────────────────────────

function TabOverview({ d }) {
  const comp = d?.composite || {}
  const fut  = d?.futures?.contracts || {}
  const inv  = d?.inventory || {}
  const mac  = d?.fred?.derived || {}

  const layers = [
    { label: "Macro",     score: mac?.macro_composite?.composite_signal === "BULLISH" ? 1 : mac?.macro_composite?.composite_signal === "BEARISH" ? -1 : 0 },
    { label: "Crack",     score: d?.crack?.signals?.crack_321?.signal === "BULLISH" ? 1 : d?.crack?.signals?.crack_321?.signal === "BEARISH" ? -1 : 0 },
    { label: "Inventory", score: inv?.signals?.cushing?.direction === "bullish" ? 1 : inv?.signals?.cushing?.direction === "bearish" ? -1 : 0 },
    { label: "Brent-WTI", score: 0 },
    { label: "Sentiment", score: d?.sentiment?.composite_score > 0 ? 0.5 : d?.sentiment?.composite_score < 0 ? -0.5 : 0 },
    { label: "Rig Count", score: d?.rig_count?.signal?.direction === "bullish" ? 0.5 : d?.rig_count?.signal?.direction === "bearish" ? -0.5 : 0 },
  ]

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
      <Card title="Composite Index">
        <CompositeGauge
          score={comp.score}
          label={comp.label}
          reasons={comp.reasons || []}
        />
      </Card>

      <Card title="Signal Layers">
        {layers.map((l, i) => {
          const col = l.score > 0 ? "#22c55e" : l.score < 0 ? "#ef4444" : "#f59e0b"
          const w   = Math.abs(l.score) * 100
          return (
            <div key={i} style={{ marginBottom: 8 }}>
              <div style={{ display: "flex", justifyContent: "space-between",
                fontSize: 12, marginBottom: 3 }}>
                <span style={{ color: "#9ca3af" }}>{l.label}</span>
                <span style={{ color: col, fontWeight: 600 }}>
                  {l.score > 0 ? "+" : ""}{l.score.toFixed(1)}
                </span>
              </div>
              <div style={{ height: 4, background: "#1f2937", borderRadius: 2, overflow: "hidden" }}>
                <div style={{ width: w + "%", height: "100%", background: col, borderRadius: 2 }} />
              </div>
            </div>
          )
        })}
      </Card>

      <Card title="Live Prices" style={{ gridColumn: "1 / -1" }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10 }}>
          <PriceCard label="Brent ICE"  price={fut?.brent?.price_bbl}       unit="$/bbl"   change={fut?.brent?.change_pct}       color="#3b82f6" />
          <PriceCard label="WTI NYMEX" price={fut?.wti?.price_bbl}         unit="$/bbl"   change={fut?.wti?.change_pct}         color="#60a5fa" />
          <PriceCard label="RBOB"      price={fut?.rbob?.price_bbl}        unit="$/bbl"   change={fut?.rbob?.change_pct}        color="#f59e0b" />
          <PriceCard label="Heating Oil" price={fut?.heating_oil?.price_bbl} unit="$/bbl" change={fut?.heating_oil?.change_pct} color="#f97316" />
        </div>
      </Card>
    </div>
  )
}

// ── Tab: Prices ────────────────────────────────────────────────────────────

function TabPrices({ d }) {
  const fut = d?.futures?.contracts || {}
  const der = d?.futures?.derived   || {}

  return (
    <>
      <Card title="Futures Prices">
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10 }}>
          <PriceCard label="Brent ICE"    price={fut?.brent?.price_bbl}        unit="$/bbl"    change={fut?.brent?.change_pct}        color="#3b82f6" />
          <PriceCard label="WTI NYMEX"   price={fut?.wti?.price_bbl}          unit="$/bbl"    change={fut?.wti?.change_pct}          color="#60a5fa" />
          <PriceCard label="RBOB"        price={fut?.rbob?.price_bbl}         unit="$/bbl"    change={fut?.rbob?.change_pct}         color="#f59e0b" />
          <PriceCard label="Heating Oil" price={fut?.heating_oil?.price_bbl}  unit="$/bbl"    change={fut?.heating_oil?.change_pct}  color="#f97316" />
          <PriceCard label="Henry Hub"   price={fut?.henry_hub?.raw_price}    unit="$/mmbtu"  change={fut?.henry_hub?.change_pct}    color="#a78bfa" />
          <PriceCard label="Dubai"       price={fut?.dubai?.price_bbl}        unit="$/bbl"    change={fut?.dubai?.change_pct}        color="#34d399" />
        </div>
      </Card>

      <Card title="Key Spreads">
        <MetricRow label="Brent – WTI"  value={val(der?.brent_wti_spread?.value_bbl)} unit="$/bbl" signal={der?.brent_wti_spread?.signal} note={der?.brent_wti_spread?.note} />
        <MetricRow label="3-2-1 Crack"  value={val(der?.crack_321?.value_bbl)}        unit="$/bbl" signal={der?.crack_321?.signal} />
        <MetricRow label="HO – RBOB"    value={val(der?.ho_rbob_spread?.value_bbl)}   unit="$/bbl" />
      </Card>
    </>
  )
}

// ── Tab: Spreads ───────────────────────────────────────────────────────────

function TabSpreads({ d }) {
  const cr  = d?.crack  || {}
  const fut = d?.futures?.derived || {}

  return (
    <>
      <Card title="Crack Spreads">
        <MetricRow label="3-2-1 Crack (US)"    value={val(cr?.signals?.crack_321?.value_bbl)}    unit="$/bbl" signal={cr?.signals?.crack_321?.signal} />
        <MetricRow label="Gasoline Crack"       value={val(cr?.signals?.gasoline_crack?.value_bbl)} unit="$/bbl" signal={cr?.signals?.gasoline_crack?.signal} />
        <MetricRow label="Distillate Crack"     value={val(cr?.signals?.distillate_crack?.value_bbl)} unit="$/bbl" signal={cr?.signals?.distillate_crack?.signal} />
        <MetricRow label="Brent – WTI Spread"  value={val(fut?.brent_wti_spread?.value_bbl)}     unit="$/bbl" signal={fut?.brent_wti_spread?.signal} />
        <MetricRow label="HO – RBOB Spread"    value={val(fut?.ho_rbob_spread?.value_bbl)}       unit="$/bbl" />
      </Card>

      <Card title="Spread Signals">
        <div style={{ fontSize: 12, color: "#6b7280", lineHeight: 1.8 }}>
          <div>• Brent-WTI &gt; $8 → US export bottleneck or North Sea disruption</div>
          <div>• Brent-WTI &lt; $2 → US exports flooding Atlantic basin</div>
          <div>• 3-2-1 Crack &gt; $20 → Product demand tight, crude demand bullish</div>
          <div>• 3-2-1 Crack &lt; $10 → Refinery margins compressed, runs may fall</div>
        </div>
      </Card>
    </>
  )
}

// ── Tab: Inventory ─────────────────────────────────────────────────────────

function TabInventory({ d }) {
  const inv = d?.inventory || {}
  const eia = d?.eia?.signals || {}

  return (
    <>
      <Card title="EIA Weekly Inventory">
        <MetricRow label="Cushing Stocks"      value={val(eia?.cushing_stocks?.value_mmbbls, 1)} unit="mmbbls" signal={eia?.cushing_stocks?.signal} />
        <MetricRow label="Total Crude Stocks"  value={val(eia?.total_crude_stocks?.value_mmbbls, 1)} unit="mmbbls" />
        <MetricRow label="Gasoline Stocks"     value={val(eia?.gasoline_stocks?.value_mmbbls, 1)}    unit="mmbbls" signal={eia?.gasoline_stocks?.signal} />
        <MetricRow label="Distillate Stocks"   value={val(eia?.distillate_stocks?.value_mmbbls, 1)}  unit="mmbbls" signal={eia?.distillate_stocks?.signal} />
        <MetricRow label="Crude Production"    value={val(eia?.crude_production?.value_mbd, 2)}      unit="mbd"    />
        <MetricRow label="Refinery Util"       value={val(eia?.refinery_util?.value, 1)}             unit="%"      />
      </Card>

      <Card title="Inventory Signals">
        <MetricRow label="Days of Cover"       value={val(inv?.days_cover, 1)}             unit="days"  signal={inv?.days_cover_signal} />
        <MetricRow label="5yr Deviation"       value={val(inv?.oecd_5yr_deviation, 1)}     unit="mmbbls" />
        <MetricRow label="Cushing WoW"         value={val(inv?.cushing_wow, 1)}            unit="mmbbls" signal={inv?.cushing_direction} />
      </Card>
    </>
  )
}

// ── Tab: Macro ─────────────────────────────────────────────────────────────

function TabMacro({ d }) {
  const fred = d?.fred?.series  || {}
  const gie  = d?.gie           || {}
  const wx   = d?.weather       || {}

  return (
    <>
      <Card title="Macro Indicators (FRED)">
        <MetricRow label="DXY (Broad Dollar)"  value={val(fred?.dxy_broad?.latest, 2)}   signal={fred?.dxy_broad?.signal} />
        <MetricRow label="SOFR"                value={val(fred?.sofr?.latest, 3)}        unit="%" />
        <MetricRow label="Fed Funds"           value={val(fred?.fed_funds?.latest, 2)}   unit="%" />
        <MetricRow label="US 10Y Yield"        value={val(fred?.us_10y_yield?.latest, 3)} unit="%" />
      </Card>

      <Card title="European Gas Storage (GIE AGSI+)">
        {gie?.countries ? Object.entries(gie.countries).slice(0, 5).map(([k, v]) => (
          <MetricRow key={k} label={k} value={val(v?.fill_pct, 1)} unit="% full"
            signal={v?.vs_5yr > 0 ? "ABOVE AVG" : "BELOW AVG"} />
        )) : <div style={{ color: "#4b5563", fontSize: 12 }}>No GIE data</div>}
      </Card>

      <Card title="Weather — HDD/CDD">
        {wx?.locations ? Object.entries(wx.locations).slice(0, 4).map(([k, v]) => (
          <MetricRow key={k} label={k}
            value={val(v?.hdd_7d, 1)} unit="HDD"
            note={`CDD: ${val(v?.cdd_7d, 1)}`} />
        )) : <div style={{ color: "#4b5563", fontSize: 12 }}>No weather data</div>}
      </Card>
    </>
  )
}

// ── Tab: Sentiment ─────────────────────────────────────────────────────────

function TabSentiment({ d }) {
  const news = d?.news      || {}
  const cftc = d?.cftc      || {}

  const headlines = news?.headlines || []
  const score     = news?.composite_score ?? null
  const scoreCol  = score > 0 ? "#22c55e" : score < 0 ? "#ef4444" : "#f59e0b"

  return (
    <>
      <Card title="News Sentiment">
        <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 12 }}>
          <div style={{ textAlign: "center" }}>
            <div style={{ fontSize: 32, fontWeight: 800, color: scoreCol }}>
              {score != null ? (score > 0 ? "+" : "") + score.toFixed(1) : "—"}
            </div>
            <div style={{ fontSize: 10, color: "#6b7280" }}>Composite</div>
          </div>
          <div>
            <MetricRow label="Bullish signals"  value={news?.bullish_count  ?? "—"} />
            <MetricRow label="Bearish signals"  value={news?.bearish_count  ?? "—"} />
            <MetricRow label="Geo alerts"       value={news?.geo_alerts     ?? "—"} />
          </div>
        </div>
        {headlines.slice(0, 8).map((h, i) => (
          <div key={i} style={{
            fontSize: 11, color: "#9ca3af", padding: "4px 0",
            borderBottom: "1px solid #1a2234",
            display: "flex", justifyContent: "space-between", gap: 8
          }}>
            <span style={{ flex: 1 }}>{h.title}</span>
            <span style={{ color: h.score > 0 ? "#22c55e" : h.score < 0 ? "#ef4444" : "#9ca3af",
              fontWeight: 600, whiteSpace: "nowrap" }}>
              {h.score != null ? (h.score > 0 ? "+" : "") + h.score.toFixed(1) : "—"}
            </span>
          </div>
        ))}
      </Card>

      <Card title="CFTC Positioning">
        {cftc?.contracts ? Object.entries(cftc.contracts).slice(0, 4).map(([k, v]) => (
          <MetricRow key={k} label={k}
            value={val(v?.net_long_pct, 1)} unit="% net long"
            signal={v?.signal} />
        )) : <div style={{ color: "#4b5563", fontSize: 12 }}>No CFTC data</div>}
      </Card>
    </>
  )
}

// ── Main App ───────────────────────────────────────────────────────────────

export default function App() {
  const [activeTab, setActiveTab]   = useState("overview")
  const [data,      setData]        = useState(null)
  const [loading,   setLoading]     = useState(true)
  const [lastUpdate,setLastUpdate]  = useState(null)
  const [countdown, setCountdown]   = useState(30)

  const fetchAll = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/all`)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      setData(await r.json())
      setLastUpdate(new Date())
      setCountdown(30)
    } catch (e) {
      console.error("Fetch error:", e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchAll()
    const d = setInterval(fetchAll, 30000)
    const c = setInterval(() => setCountdown(n => n > 0 ? n - 1 : 30), 1000)
    return () => { clearInterval(d); clearInterval(c) }
  }, [fetchAll])

  const comp     = data?.composite || {}
  const score    = comp.score ?? null
  const scoreCol = score > 0.5 ? "#22c55e" : score < -0.5 ? "#ef4444" : "#f59e0b"

  return (
    <div style={{
      background: "#0d1117", minHeight: "100vh",
      color: "#e5e7eb",
      fontFamily: "'Inter', 'Segoe UI', system-ui, sans-serif",
    }}>
      {/* Top bar */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "8px 20px", background: "#0a0f1a",
        borderBottom: "1px solid #0f1e30",
        position: "sticky", top: 0, zIndex: 100,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 15, fontWeight: 800, color: "#00d98b",
            letterSpacing: "0.05em" }}>⚡ ENERGY SIGNAL</span>
          <span style={{ color: "#1f2937" }}>|</span>
          <span style={{ width: 7, height: 7, borderRadius: "50%",
            background: loading ? "#f59e0b" : "#22c55e",
            display: "inline-block" }} />
          <span style={{ fontSize: 11, color: "#4b5563" }}>
            {loading ? "Loading..." : lastUpdate
              ? `Updated ${lastUpdate.toLocaleTimeString()}` : "Live"}
          </span>
          <span style={{ fontSize: 11, color: "#374151" }}>· Refresh in {countdown}s</span>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div style={{ textAlign: "right" }}>
            <div style={{ fontSize: 11, color: "#4b5563" }}>Composite Index</div>
            <div style={{ fontSize: 18, fontWeight: 800, color: scoreCol, lineHeight: 1 }}>
              {score != null ? (score > 0 ? "+" : "") + score.toFixed(1) : "—"}
              <span style={{ fontSize: 11, marginLeft: 6, fontWeight: 400 }}>
                {comp.label || ""}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Tab bar */}
      <div style={{
        display: "flex", gap: 2, padding: "0 20px",
        background: "#0a0f1a", borderBottom: "1px solid #0f1e30",
        overflowX: "auto",
      }}>
        {TABS.map(tab => (
          <button key={tab.id} onClick={() => setActiveTab(tab.id)}
            style={{
              background: "transparent", border: "none",
              padding: "10px 16px", cursor: "pointer", fontSize: 12,
              fontWeight: 600, borderBottom: activeTab === tab.id
                ? "2px solid #00d98b" : "2px solid transparent",
              color: activeTab === tab.id ? "#00d98b" : "#334155",
              letterSpacing: "0.12em", textTransform: "uppercase",
              transition: "all 0.15s", display: "flex",
              alignItems: "center", gap: 6 }}>
            <i className={`ti ${tab.icon}`}
              style={{ fontSize: 14 }} aria-hidden="true" />
            {tab.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div style={{ padding: "16px 22px", maxWidth: 1400, margin: "0 auto" }}>
        {loading ? (
          <div style={{ display: "flex", alignItems: "center",
            justifyContent: "center", height: 300, color: "#00d98b",
            fontFamily: "monospace", fontSize: 12, letterSpacing: "0.2em" }}>
            LOADING SIGNAL DATA...
          </div>
        ) : (
          <>
            {activeTab === "overview"  && <TabOverview  d={data} />}
            {activeTab === "prices"    && <TabPrices    d={data} />}
            {activeTab === "spreads"   && <TabSpreads   d={data} />}
            {activeTab === "inventory" && <TabInventory d={data} />}
            {activeTab === "macro"     && <TabMacro     d={data} />}
            {activeTab === "sentiment" && <TabSentiment d={data} />}
          </>
        )}
      </div>

      <div style={{ textAlign: "center", padding: "10px 0",
        color: "#1a2535", fontSize: 8, fontFamily: "monospace",
        borderTop: "1px solid #0f1e30" }}>
        EIA · YAHOO FINANCE · FRED · GIE AGSI+ · OPEN-METEO · CFTC
        {score >= 7 && " · ⚡ STRONG BUY ACTIVE"}
      </div>
    </div>
  )
}

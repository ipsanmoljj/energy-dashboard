import { useState, useEffect, useCallback, useRef } from "react"
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, Area, ComposedChart
} from "recharts"

const API = ""

const TABS = [
  { id: "overview",  label: "Overview" },
  { id: "prices",    label: "Prices" },
  { id: "spreads",   label: "Spreads" },
  { id: "inventory", label: "Inventory" },
  { id: "macro",     label: "Macro" },
  { id: "sentiment", label: "Sentiment" },
]

const ALERT_KEYS = [
  { key: "brent",       label: "Brent ICE",  color: "#3b82f6" },
  { key: "wti",         label: "WTI NYMEX",  color: "#60a5fa" },
  { key: "rbob",        label: "RBOB",       color: "#f59e0b" },
  { key: "heating_oil", label: "Heating Oil",color: "#f97316" },
  { key: "gasoil",      label: "ICE Gasoil", color: "#a78bfa" },
]
const WARN_PCT = 2
const CRIT_PCT = 4

function computeAlerts(hist, contracts) {
  if (!hist || hist.length < 4 || !contracts) return []
  const histForAvg = hist.slice(0, -1)
  const alerts = []
  for (const { key, label, color } of ALERT_KEYS) {
    const current = contracts[key]?.price_bbl ?? null
    if (current == null) continue
    const last5 = histForAvg.filter(h => h[key] != null).slice(-5)
    if (last5.length < 3) continue
    const avg5d  = last5.reduce((s, h) => s + h[key], 0) / last5.length
    const devPct = ((current - avg5d) / avg5d) * 100
    const absDev = Math.abs(devPct)
    if (absDev < WARN_PCT) continue
    alerts.push({
      key, label, color,
      current:  Math.round(current * 100) / 100,
      avg5d:    Math.round(avg5d * 100) / 100,
      devPct:   Math.round(devPct * 10) / 10,
      severity: absDev >= CRIT_PCT ? "critical" : "warning",
      isUp:     devPct > 0,
    })
  }
  return alerts.sort((a, b) => {
    if (a.severity !== b.severity) return a.severity === "critical" ? -1 : 1
    return Math.abs(b.devPct) - Math.abs(a.devPct)
  })
}

function AlertBanner({ alerts }) {
  if (!alerts || alerts.length === 0) return null
  const hasCrit = alerts.some(a => a.severity === "critical")
  return (
    <div style={{
      background: "#0d1117",
      borderBottom: `1px solid ${hasCrit ? "#ef444440" : "#f59e0b30"}`,
      padding: "5px 20px", display: "flex", alignItems: "center",
      gap: 6, overflowX: "auto", flexShrink: 0,
    }}>
      <span style={{
        fontSize: 9, fontWeight: 800, letterSpacing: "0.12em",
        color: hasCrit ? "#ef4444" : "#f59e0b",
        whiteSpace: "nowrap", marginRight: 4, flexShrink: 0,
      }}>
        {hasCrit ? "⚠" : "◉"} ALERTS
      </span>
      <span style={{ width: 1, height: 14, background: "#1a2535", flexShrink: 0 }} />
      {alerts.map(a => {
        const isCrit = a.severity === "critical"
        const border = isCrit ? "#ef444455" : "#f59e0b44"
        const bg     = isCrit ? "#ef444410" : "#f59e0b0d"
        const sevCol = isCrit ? "#ef4444"   : "#f59e0b"
        const dirCol = a.isUp ? "#ef4444"   : "#22c55e"
        const arrow  = a.isUp ? "▲" : "▼"
        return (
          <div key={a.key} style={{
            display: "flex", alignItems: "center", gap: 5,
            background: bg, border: `0.5px solid ${border}`,
            borderRadius: 5, padding: "3px 9px",
            whiteSpace: "nowrap", flexShrink: 0,
          }}>
            <span style={{ fontSize: 9, fontWeight: 800, color: sevCol }}>{isCrit ? "⚠" : "◉"}</span>
            <span style={{ fontSize: 11, fontWeight: 700, color: a.color }}>{a.label}</span>
            <span style={{ fontSize: 12, fontWeight: 800, color: "#e5e7eb" }}>${a.current}</span>
            <span style={{ fontSize: 11, fontWeight: 700, color: dirCol }}>{arrow}{a.devPct > 0 ? "+" : ""}{a.devPct}%</span>
            <span style={{ fontSize: 9, color: "#374151" }}>vs 5d ${a.avg5d}</span>
          </div>
        )
      })}
      <span style={{ fontSize: 9, color: "#1f2937", marginLeft: "auto", flexShrink: 0, whiteSpace: "nowrap" }}>
        updates every 30s
      </span>
    </div>
  )
}

function fmt(v, dp=2, fallback="—") {
  if (v == null || v === "" || isNaN(Number(v))) return fallback
  return Number(v).toFixed(dp)
}

function signalCol(s) {
  if (!s) return "#6b7280"
  const u = s.toUpperCase()
  if (u.includes("BULL") || u.includes("STRONG") || u.includes("GROW") || u.includes("ABOVE")) return "#22c55e"
  if (u.includes("BEAR") || u.includes("WEAK")   || u.includes("DECL") || u.includes("BELOW")) return "#ef4444"
  if (u.includes("INSUF") || u.includes("FAIL"))  return "#4b5563"
  return "#f59e0b"
}

function Badge({ label }) {
  if (!label || label === "—") return null
  const col = signalCol(label)
  return (
    <span style={{
      fontSize: 10, fontWeight: 700, color: col,
      background: col + "22", borderRadius: 4,
      padding: "1px 6px", whiteSpace: "nowrap",
    }}>{label}</span>
  )
}

function Row({ label, value, unit, signal, note, highlight }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", justifyContent: "space-between",
      padding: "7px 0", borderBottom: "1px solid #0f1e30",
      background: highlight ? "#0d2a1a" : "transparent",
    }}>
      <span style={{ fontSize: 12, color: "#9ca3af" }}>{label}</span>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {note && <span style={{ fontSize: 10, color: "#4b5563" }}>{note}</span>}
        {signal && <Badge label={signal} />}
        <span style={{ fontSize: 13, fontWeight: 600, color: "#e5e7eb", minWidth: 60, textAlign: "right" }}>
          {value}{unit && <span style={{ fontSize: 10, color: "#6b7280", marginLeft: 3 }}>{unit}</span>}
        </span>
      </div>
    </div>
  )
}

function Card({ title, children, style={} }) {
  return (
    <div style={{
      background: "#0d1117", border: "1px solid #1a2535",
      borderRadius: 10, padding: "14px 16px", ...style
    }}>
      {title && <div style={{
        fontSize: 10, fontWeight: 700, color: "#4b5563",
        letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 10,
      }}>{title}</div>}
      {children}
    </div>
  )
}

function PriceCard({ label, price, unit, change, color, error }) {
  const isPos = change > 0, isNeg = change < 0
  return (
    <div style={{
      background: "#0a1628", border: `1px solid ${color}30`,
      borderRadius: 10, padding: "14px 16px",
    }}>
      <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 6 }}>{label}</div>
      {error ? (
        <div style={{ fontSize: 12, color: "#374151", marginBottom: 4 }}>Feed unavailable</div>
      ) : (
        <div style={{ fontSize: 24, fontWeight: 800, color, letterSpacing: "-0.5px", lineHeight: 1 }}>
          {fmt(price)}
        </div>
      )}
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6 }}>
        <span style={{ fontSize: 10, color: "#374151" }}>{unit}</span>
        {!error && change != null && (
          <span style={{ fontSize: 11, fontWeight: 700,
            color: isPos ? "#22c55e" : isNeg ? "#ef4444" : "#6b7280" }}>
            {isPos ? "▲" : isNeg ? "▼" : "—"} {fmt(Math.abs(change))}%
          </span>
        )}
      </div>
    </div>
  )
}

function round2(v) { return Math.round(v * 100) / 100 }

function computeBand(history, key) {
  const vals = history.map(h => h[key]).filter(v => v != null)
  if (vals.length < 3) return { mean: null, upper: null, lower: null }
  const mean = vals.reduce((a, b) => a + b, 0) / vals.length
  const std  = Math.sqrt(vals.reduce((a, b) => a + (b - mean) ** 2, 0) / vals.length)
  return { mean: round2(mean), upper: round2(mean + std), lower: round2(mean - std) }
}

function prepChartData(history, key) {
  if (!history || history.length === 0) return []
  const band = computeBand(history, key)
  return history
    .filter(h => h[key] != null)
    .map(h => ({
      date:  h.date?.slice(5),
      value: h[key],
      mean:  band.mean,
      upper: band.upper,
      lower: band.lower,
      band:  band.upper != null ? [band.lower, band.upper] : null,
    }))
}

function SeriesChart({ title, data, color, unit="$/bbl", currentPrice, currentSignal }) {
  const hasData   = data && data.length > 0
  const hasBand   = hasData && data[0]?.band != null
  const latestVal = hasData ? data[data.length - 1]?.value : null

  const CustomTooltip = ({ active, payload, label }) => {
    if (!active || !payload?.length) return null
    const val = payload.find(p => p.name === "value")
    return (
      <div style={{
        background: "#0d1117", border: "1px solid #1a2535",
        borderRadius: 6, padding: "8px 12px", fontSize: 11,
      }}>
        <div style={{ color: "#6b7280", marginBottom: 4 }}>{label}</div>
        {val && <div style={{ color, fontWeight: 600 }}>{fmt(val.value)} {unit}</div>}
      </div>
    )
  }

  return (
    <Card style={{ marginBottom: 0 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
        <div>
          <div style={{ fontSize: 10, fontWeight: 700, color: "#4b5563",
            letterSpacing: "0.12em", textTransform: "uppercase" }}>{title}</div>
          {currentSignal && <div style={{ marginTop: 3 }}><Badge label={currentSignal} /></div>}
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 22, fontWeight: 800, color, lineHeight: 1 }}>
            {fmt(currentPrice ?? latestVal)}
          </div>
          <div style={{ fontSize: 10, color: "#374151" }}>{unit}</div>
        </div>
      </div>
      {!hasData ? (
        <div style={{ height: 120, display: "flex", alignItems: "center", justifyContent: "center",
          color: "#1f2937", fontSize: 10, fontFamily: "monospace" }}>
          NO HISTORY YET — BUILDING DATA...
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={140}>
          <ComposedChart data={data} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#0f1e30" />
            <XAxis dataKey="date" tick={{ fontSize: 9, fill: "#374151" }}
              tickLine={false} interval="preserveStartEnd" />
            <YAxis tick={{ fontSize: 9, fill: "#374151" }} tickLine={false}
              domain={["auto", "auto"]} width={50} tickFormatter={v => v.toFixed(0)} />
            <Tooltip content={<CustomTooltip />} />
            {hasBand && (
              <Area dataKey="band" stroke="none" fill={color}
                fillOpacity={0.07} name="band" legendType="none" />
            )}
            {hasBand && data[0]?.mean != null && (
              <ReferenceLine y={data[0].mean} stroke={color}
                strokeOpacity={0.35} strokeDasharray="4 4"
                label={{ value: `avg ${fmt(data[0].mean, 1)}`,
                  position: "insideTopRight", fontSize: 8, fill: color, opacity: 0.6 }} />
            )}
            <Line dataKey="value" stroke={color} strokeWidth={2}
              dot={false} activeDot={{ r: 3, fill: color }} name="value" />
          </ComposedChart>
        </ResponsiveContainer>
      )}
      {hasBand && (
        <div style={{ display: "flex", gap: 16, marginTop: 6, fontSize: 9, color: "#374151" }}>
          <span>5wk avg: <span style={{ color }}>{fmt(data[0]?.mean, 2)}</span></span>
          <span>+1σ: <span style={{ color: "#22c55e" }}>{fmt(data[0]?.upper, 2)}</span></span>
          <span>-1σ: <span style={{ color: "#ef4444" }}>{fmt(data[0]?.lower, 2)}</span></span>
          <span style={{ marginLeft: "auto" }}>{data.length}d</span>
        </div>
      )}
    </Card>
  )
}

function CompositeGauge({ score, label, reasons=[] }) {
  const s     = Math.max(-10, Math.min(10, score ?? 0))
  const pct   = ((s + 10) / 20) * 100
  const color = s > 0.5 ? "#22c55e" : s < -0.5 ? "#ef4444" : "#f59e0b"
  return (
    <div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 12 }}>
        <span style={{ fontSize: 48, fontWeight: 900, color, lineHeight: 1 }}>
          {score != null ? (s > 0 ? "+" : "") + s.toFixed(1) : "—"}
        </span>
        <span style={{
          fontSize: 13, fontWeight: 700, color,
          background: color + "22", borderRadius: 20, padding: "3px 12px",
        }}>{label || "NEUTRAL"}</span>
      </div>
      <div style={{ position: "relative", height: 6, background: "#1a2535", borderRadius: 3, marginBottom: 4 }}>
        <div style={{ position: "absolute", left: 0, top: 0, bottom: 0,
          width: pct + "%", background: color, borderRadius: 3, transition: "width 0.6s" }} />
        <div style={{ position: "absolute", left: "50%", top: 0, bottom: 0, width: 1, background: "#374151" }} />
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, color: "#374151", marginBottom: 12 }}>
        <span>-10 BEARISH</span><span>NEUTRAL</span><span>BULLISH +10</span>
      </div>
      {reasons.map((r,i) => (
        <div key={i} style={{ fontSize: 11, color: "#6b7280", padding: "2px 0 2px 8px",
          borderLeft: "2px solid #1a2535", marginBottom: 3 }}>· {r}</div>
      ))}
    </div>
  )
}

// ── Tabs ───────────────────────────────────────────────────────────────────

// FIX 2: TabOverview now reads from inv_signals + crack_signals
function TabOverview({ d }) {
  const comp      = d?.composite?.composite      || {}
  const eia       = d?.eia                       || {}
  const fut       = d?.futures?.contracts        || {}
  const layers_raw = d?.composite?.layers        || {}
  const invComp   = d?.inv_signals?.composite    || {}
  const crackComp = d?.crack_signals?.composite  || {}
  const invSigs   = d?.inv_signals?.signals      || {}
  const crackSigs = d?.crack_signals?.signals    || {}

  const layers = [
    {
      label:  "Inventory",
      score:  invComp.score != null ? invComp.score / 10 : (eia?.cushing_stocks?.vs_5yr_avg < 0 ? 0.5 : -0.5),
      label2: invComp.overall_signal || "NO_DATA",
    },
    {
      label:  "Crack",
      score:  crackComp.score != null ? crackComp.score / 10 : 0,
      label2: crackSigs.curve_shape?.structure || crackComp.overall_signal || "NO_DATA",
    },
    {
      label:  "Macro",
      score:  layers_raw.macro?.available ? (layers_raw.macro.score / 10) : 0,
      label2: layers_raw.macro?.label,
    },
    {
      label:  "Demand/Weather",
      score:  layers_raw.demand?.available ? (layers_raw.demand.score / 10) : 0,
      label2: layers_raw.demand?.label,
    },
    {
      label:  "EU Gas Storage",
      score:  invSigs.gie_storage?.signal === "BULLISH" ? 0.8
            : invSigs.gie_storage?.signal === "BEARISH" ? -0.8 : 0,
      label2: invSigs.gie_storage?.signal || "NO_DATA",
    },
    {
      label:  "Positioning",
      score:  layers_raw.positioning?.available ? (layers_raw.positioning.score / 10) : 0,
      label2: layers_raw.positioning?.label,
    },
    {
      label:  "News/Sentiment",
      score:  layers_raw.news?.available ? (layers_raw.news.score / 10) : 0,
      label2: layers_raw.news?.label,
    },
    {
      label:  "Rig Count",
      score:  d?.rig_count?.signal?.direction === "bullish" ? 0.5
            : d?.rig_count?.signal?.direction === "bearish" ? -0.5 : 0,
      label2: `${d?.rig_count?.signal?.label || "—"} ${d?.rig_count?.latest?.oil_rigs ? `(${d.rig_count.latest.oil_rigs})` : ""}`,
    },
  ]

  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
      <Card title="Composite Index">
        <CompositeGauge score={comp.score} label={comp.label} reasons={comp.reasons || []} />
      </Card>

      <Card title="Signal Layers">
        {layers.map((l,i) => {
          const col = l.score > 0 ? "#22c55e" : l.score < 0 ? "#ef4444" : "#374151"
          return (
            <div key={i} style={{ marginBottom: 10 }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 4 }}>
                <span style={{ color: "#9ca3af" }}>{l.label}
                  {l.label2 && <span style={{ color: "#374151", fontSize: 10, marginLeft: 6 }}>{l.label2}</span>}
                </span>
                <span style={{ color: col, fontWeight: 700 }}>{l.score > 0 ? "+" : ""}{l.score.toFixed(1)}</span>
              </div>
              <div style={{ height: 3, background: "#1a2535", borderRadius: 2 }}>
                <div style={{ width: Math.abs(l.score) * 100 + "%", height: "100%", background: col, borderRadius: 2 }} />
              </div>
            </div>
          )
        })}
      </Card>

      <Card title="Live Prices" style={{ gridColumn: "1 / -1" }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(5,1fr)", gap: 10 }}>
          <PriceCard label="Brent ICE"    price={fut.brent?.price_bbl}       unit="$/bbl" change={fut.brent?.change_pct}       color="#3b82f6" error={!!fut.brent?.error} />
          <PriceCard label="WTI NYMEX"   price={fut.wti?.price_bbl}         unit="$/bbl" change={fut.wti?.change_pct}         color="#60a5fa" error={!!fut.wti?.error} />
          <PriceCard label="RBOB"        price={fut.rbob?.price_bbl}        unit="$/bbl" change={fut.rbob?.change_pct}        color="#f59e0b" error={!!fut.rbob?.error} />
          <PriceCard label="Heating Oil" price={fut.heating_oil?.price_bbl} unit="$/bbl" change={fut.heating_oil?.change_pct} color="#f97316" error={!!fut.heating_oil?.error} />
          <PriceCard label="Dubai/Oman"  price={fut.dubai?.price_bbl}       unit="$/bbl" change={fut.dubai?.change_pct}       color="#a78bfa" error={!!fut.dubai?.error} />
        </div>
      </Card>

      <Card title="EIA Snapshot" style={{ gridColumn: "1 / -1" }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 0 }}>
          <Row label="Cushing Stocks"   value={fmt(eia.cushing_stocks?.value,1)}    unit="mmbbls" signal={eia.cushing_stocks?.vs_5yr_avg < 0 ? "BELOW 5YR" : "ABOVE 5YR"}   note={`WoW: ${fmt(eia.cushing_stocks?.wow,1)}`} />
          <Row label="Gasoline Stocks"  value={fmt(eia.gasoline_stocks?.value,1)}   unit="mmbbls" signal={eia.gasoline_stocks?.vs_5yr_avg < 0 ? "BELOW 5YR" : "ABOVE 5YR"}  note={`5yr: ${fmt(eia.gasoline_stocks?.vs_5yr_avg,1)}`} />
          <Row label="Distillate Stks"  value={fmt(eia.distillate_stocks?.value,1)} unit="mmbbls" signal={eia.distillate_stocks?.vs_5yr_avg < 0 ? "BELOW 5YR" : "ABOVE 5YR"} note={`5yr: ${fmt(eia.distillate_stocks?.vs_5yr_avg,1)}`} />
          <Row label="Crude Production" value={fmt(eia.crude_production?.value,2)}  unit="mbd"    note={`WoW: ${fmt(eia.crude_production?.wow,3)}`} />
          <Row label="Refinery Util"    value={fmt(eia.refinery_util?.value,1)}     unit="%"      signal={eia.refinery_util?.value > 90 ? "HIGH" : "NORMAL"} note={`WoW: ${fmt(eia.refinery_util?.wow,1)}`} />
          <Row label="Days of Cover"    value={fmt(eia.days_cover,1)}               unit="days"   signal={eia.days_cover < 54 ? "TIGHT" : eia.days_cover > 62 ? "AMPLE" : "NORMAL"} />
        </div>
      </Card>
    </div>
  )
}

function TabPrices({ d, history }) {
  const fut = d?.futures?.contracts || {}
  const der = d?.crack?.spreads     || {}
  return (
    <>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
        <SeriesChart title="Brent ICE"        data={prepChartData(history, "brent")}       color="#3b82f6" currentPrice={fut.brent?.price_bbl} />
        <SeriesChart title="WTI NYMEX"        data={prepChartData(history, "wti")}         color="#60a5fa" currentPrice={fut.wti?.price_bbl} />
        <SeriesChart title="RBOB Gasoline"    data={prepChartData(history, "rbob")}        color="#f59e0b" currentPrice={fut.rbob?.price_bbl} />
        <SeriesChart title="Heating Oil/ULSD" data={prepChartData(history, "heating_oil")} color="#f97316" currentPrice={fut.heating_oil?.price_bbl} />
        <SeriesChart title="Dubai / Oman"     data={prepChartData(history, "dubai")}       color="#a78bfa" currentPrice={fut.dubai?.price_bbl} />
      </div>
      <Card title="Key Spreads">
        <Row label="Brent – WTI"    value={fmt(der.brent_wti?.value_bbl)}      unit="$/bbl" signal={der.brent_wti?.signal}      note={der.brent_wti?.note} />
        <Row label="3-2-1 Crack"    value={fmt(der.crack_321?.value_bbl)}      unit="$/bbl" signal={der.crack_321?.signal} />
        <Row label="HO – RBOB"      value={fmt(der.ho_rbob_spread?.value_bbl)} unit="$/bbl" signal={der.ho_rbob_spread?.signal} />
        <Row label="Gasoline Crack" value={fmt(der.gasoline_crack?.value_bbl)} unit="$/bbl" signal={der.gasoline_crack?.signal} />
        <Row label="HO Crack"       value={fmt(der.ho_crack?.value_bbl)}       unit="$/bbl" signal={der.ho_crack?.signal} />
      </Card>
    </>
  )
}

function TabSpreads({ d, history }) {
  const der = d?.crack?.spreads || {}
  return (
    <>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
        <SeriesChart title="3-2-1 Crack Spread" data={prepChartData(history, "crack_321")}      color="#22c55e" currentPrice={der.crack_321?.value_bbl}     currentSignal={der.crack_321?.signal} />
        <SeriesChart title="Gasoline Crack"      data={prepChartData(history, "gasoline_crack")} color="#f59e0b" currentPrice={der.gasoline_crack?.value_bbl} currentSignal={der.gasoline_crack?.signal} />
        <SeriesChart title="HO – RBOB Spread"   data={prepChartData(history, "ho_rbob")}        color="#f97316" currentPrice={der.ho_rbob_spread?.value_bbl} currentSignal={der.ho_rbob_spread?.signal} />
        <SeriesChart title="Brent – WTI Spread" data={prepChartData(history, "brent_wti")}      color="#3b82f6" currentPrice={der.brent_wti?.value_bbl}      currentSignal={der.brent_wti?.signal} />
      </div>
      <Card title="Signal Reference">
        {[
          ["Brent-WTI > $8",    "US export bottleneck or North Sea disruption"],
          ["Brent-WTI < $2",    "US exports flooding Atlantic basin"],
          ["3-2-1 Crack > $20", "Product demand tight — crude demand bullish"],
          ["3-2-1 Crack < $10", "Margins compressed — refinery runs may fall"],
          ["Gasoil Crack > $25","European diesel/heating oil tightness"],
        ].map(([k,v],i) => (
          <div key={i} style={{ display:"flex", gap:8, padding:"5px 0", borderBottom:"1px solid #0f1e30", fontSize:11 }}>
            <span style={{ color:"#f59e0b", fontWeight:700, minWidth:150 }}>{k}</span>
            <span style={{ color:"#6b7280" }}>{v}</span>
          </div>
        ))}
      </Card>
    </>
  )
}

// FIX 3: TabInventory now shows signal layer composite at top
function TabInventory({ d }) {
  const eia     = d?.eia                       || {}
  const invSigs = d?.inv_signals?.signals      || {}
  const invComp = d?.inv_signals?.composite    || {}

  return (
    <>
      {/* Inventory signal composite */}
      {invComp.score != null && (
        <Card title="Inventory Signal Layer" style={{ marginBottom: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 8 }}>
            <span style={{
              fontSize: 32, fontWeight: 900, lineHeight: 1,
              color: invComp.score > 0 ? "#22c55e" : invComp.score < 0 ? "#ef4444" : "#f59e0b",
            }}>
              {invComp.score > 0 ? "+" : ""}{invComp.score.toFixed(2)}
            </span>
            <div>
              <Badge label={invComp.overall_signal} />
              <div style={{ fontSize: 11, color: "#6b7280", marginTop: 4 }}>
                {invComp.interpretation}
              </div>
            </div>
          </div>
          {invComp.components?.map((c, i) => (
            <div key={i} style={{
              display: "flex", justifyContent: "space-between", alignItems: "center",
              fontSize: 11, padding: "4px 0", borderBottom: "1px solid #0f1e30",
            }}>
              <span style={{ color: "#9ca3af" }}>{c.label}</span>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <Badge label={c.signal} />
                <span style={{
                  color: c.score > 0 ? "#22c55e" : c.score < 0 ? "#ef4444" : "#374151",
                  fontWeight: 700, fontFamily: "monospace", minWidth: 24, textAlign: "right",
                }}>
                  {c.score > 0 ? "+" : ""}{c.score}
                </span>
              </div>
            </div>
          ))}
        </Card>
      )}

      <Card title="EIA Weekly Inventory">
        <Row label="Cushing Stocks"       value={fmt(eia.cushing_stocks?.value,1)}      unit="mmbbls" signal={eia.cushing_stocks?.vs_5yr_avg < 0 ? "BELOW 5YR AVG" : "ABOVE 5YR AVG"}   note={`WoW ${fmt(eia.cushing_stocks?.wow,1)}`}      highlight={eia.cushing_stocks?.vs_5yr_avg < -10} />
        <Row label="Total Crude Stocks"   value={fmt(eia.total_crude_stocks?.value,1)}  unit="mmbbls" signal={eia.total_crude_stocks?.vs_5yr_avg < 0 ? "BELOW 5YR AVG" : "ABOVE 5YR AVG"} note={`WoW ${fmt(eia.total_crude_stocks?.wow,1)}`} />
        <Row label="Gasoline Stocks"      value={fmt(eia.gasoline_stocks?.value,1)}     unit="mmbbls" signal={eia.gasoline_stocks?.vs_5yr_avg < 0 ? "BELOW 5YR AVG" : "ABOVE 5YR AVG"}   note={`5yr dev ${fmt(eia.gasoline_stocks?.vs_5yr_avg,1)}`} />
        <Row label="Distillate Stocks"    value={fmt(eia.distillate_stocks?.value,1)}   unit="mmbbls" signal={eia.distillate_stocks?.vs_5yr_avg < 0 ? "BELOW 5YR AVG" : "ABOVE 5YR AVG"} note={`5yr dev ${fmt(eia.distillate_stocks?.vs_5yr_avg,1)}`} />
        <Row label="Crude Production"     value={fmt(eia.crude_production?.value,2)}    unit="mbd"    note={`WoW ${fmt(eia.crude_production?.wow,3)} mbd`} />
        <Row label="Refinery Utilisation" value={fmt(eia.refinery_util?.value,1)}       unit="%"      signal={eia.refinery_util?.value > 90 ? "HIGH" : "NORMAL"} note={`WoW ${fmt(eia.refinery_util?.wow,1)}pp`} />
      </Card>

      <Card title="Derived Signals" style={{ marginTop: 12 }}>
        <Row label="Days of Forward Cover" value={fmt(eia.days_cover,1)}               unit="days" signal={eia.days_cover < 54 ? "TIGHT <54" : eia.days_cover > 62 ? "AMPLE >62" : "NORMAL"} />
        <Row label="Net Supply"            value={fmt(eia.net_supply_mbd,2)}           unit="mbd" />
        <Row label="Crude Imports"         value={fmt(eia.crude_imports?.value,2)}     unit="mbd"  note={`WoW ${fmt(eia.crude_imports?.wow,2)}`} />
        <Row label="Crude Exports"         value={fmt(eia.crude_exports?.value,2)}     unit="mbd"  note={`WoW ${fmt(eia.crude_exports?.wow,2)}`} />
        <Row label="Gasoline Demand"       value={fmt(eia.gasoline_demand?.value,2)}   unit="mbd"  note={`WoW ${fmt(eia.gasoline_demand?.wow,2)}`} />
        <Row label="Distillate Demand"     value={fmt(eia.distillate_demand?.value,2)} unit="mbd"  note={`WoW ${fmt(eia.distillate_demand?.wow,2)}`} />
      </Card>
    </>
  )
}

function TabMacro({ d }) {
  const fred = d?.fred?.series  || {}
  const gie  = d?.gie           || {}
  const wx   = d?.weather       || {}
  const der  = d?.fred?.derived || {}
  return (
    <>
      <Card title="Macro Indicators (FRED)">
        <Row label="DXY Broad Dollar" value={fmt(fred.dxy_broad?.latest,2)}                              signal={fred.dxy_broad?.signal} note="USD strength → bearish oil" />
        <Row label="SOFR"             value={fmt(fred.sofr?.latest,3)}             unit="%"               note="Storage carry cost driver" />
        <Row label="Fed Funds Rate"   value={fmt(fred.fed_funds?.latest,2)}        unit="%" />
        <Row label="US 10Y Yield"     value={fmt(fred.us_10y_yield?.latest,3)}     unit="%" />
        <Row label="Storage Carry/mo" value={fmt(der.storage_carry?.total_carry_per_bbl_mo,2)} unit="$/bbl" note="Contango threshold for storage" />
        <Row label="Macro Signal"     value=""                                     signal={der.macro_composite?.composite_signal} />
      </Card>
      <Card title="European Gas Storage (GIE AGSI+)" style={{ marginTop: 12 }}>
        {gie.regions && Object.entries(gie.regions).filter(([k,v]) => !v.error).slice(0,6).map(([k,v]) => (
          <Row key={k} label={v.label || k} value={fmt(v.fill_pct, 1)} unit="% full" signal={v.crude_signal} note={v.wow_fill_pp != null ? `WoW: +${fmt(v.wow_fill_pp,2)}pp` : undefined} />
        ))}
        {(!gie.regions || Object.values(gie.regions).every(v => v.error)) &&
          <div style={{ color:"#374151", fontSize:12, padding:"8px 0" }}>GIE data not loaded</div>}
      </Card>
      <Card title="Weather Demand (HDD/CDD)" style={{ marginTop: 12 }}>
        {wx.locations
          ? Object.entries(wx.locations).slice(0,6).map(([k,v]) => (
            <Row key={k} label={v.label || k} value={fmt(v.hdd_7d_forecast, 1)} unit="HDD" signal={v.demand_signal} note={`CDD: ${fmt(v.cdd_7d_forecast, 1)}`} />
          ))
          : <div style={{ color:"#374151", fontSize:12, padding:"8px 0" }}>Weather data not loaded</div>
        }
      </Card>
    </>
  )
}

function TabSentiment({ d }) {
  const news      = d?.news              || {}
  const cftc      = d?.cftc             || {}
  const rig       = d?.rig_count?.signal || {}
  const headlines = news.all_headlines || news.headlines || news.articles || []
  const score     = news.news_score ?? news.composite_score ?? news.score ?? null
  const scoreCol  = score > 0 ? "#22c55e" : score < 0 ? "#ef4444" : "#f59e0b"
  const summary   = news.summary || {}
  return (
    <>
      <Card title="Rig Count Signal">
        <Row label="Oil-Directed Rigs" value={fmt(d?.rig_count?.latest?.oil_rigs,0)} unit="rigs" signal={rig.label} />
        <Row label="WoW Change"    value={fmt(d?.rig_count?.latest?.wow_oil,0)}  unit="rigs" />
        <Row label="5-Week Trend"  value={rig.five_week_trend || "—"} />
        <Row label="Current Rigs"  value={fmt(d?.rig_count?.latest?.oil_rigs,0)} unit="rigs"
             signal={rig.label} note={`Threshold: <350 declining, >600 growing`} />
        <Row label="Production Signal" value="" signal={rig.label} note={rig.note?.slice(0,60)} />
      </Card>
      <Card title="News Sentiment" style={{ marginTop: 12 }}>
        <div style={{ display:"flex", alignItems:"center", gap:20, marginBottom:12 }}>
          <div>
            <div style={{ fontSize:36, fontWeight:900, color:scoreCol, lineHeight:1 }}>
              {score != null ? (score > 0 ? "+" : "") + Number(score).toFixed(1) : "—"}
            </div>
            <div style={{ fontSize:10, color:"#4b5563" }}>Composite</div>
          </div>
          <div style={{ flex:1 }}>
            <Row label="Bullish signals" value={summary.bullish ?? news.bullish_count ?? "—"} />
            <Row label="Bearish signals" value={summary.bearish ?? news.bearish_count ?? "—"} />
            <Row label="Neutral"         value={summary.neutral ?? "—"} />
            <Row label="Geo alerts"      value={(news.geo_risk_alerts?.length ?? news.geo_alerts) ?? "—"} />
          </div>
        </div>
        {headlines.slice(0,8).map((h,i) => (
          <div key={i} style={{ display:"flex", justifyContent:"space-between", gap:8,
            fontSize:11, color:"#9ca3af", padding:"5px 0", borderBottom:"1px solid #0f1e30" }}>
            <span style={{ flex:1 }}>{h.title || h.headline}</span>
            <span style={{ color: h.score > 0 ? "#22c55e" : h.score < 0 ? "#ef4444" : "#6b7280", fontWeight:700, whiteSpace:"nowrap" }}>
              {h.score != null ? (h.score > 0 ? "+" : "") + Number(h.score).toFixed(1) : "—"}
            </span>
          </div>
        ))}
      </Card>
      <Card title="CFTC Positioning" style={{ marginTop: 12 }}>
        {cftc.contracts
          ? Object.entries(cftc.contracts).slice(0,5).map(([k,v]) => (
              <Row key={k}
                label={v?.label || k}
                value={fmt(v?.net_pct_of_oi, 1)}
                unit="% net long"
                signal={v?.signal}
                note={v?.mm_net_lots != null ? `${v.mm_net_lots > 0 ? "+" : ""}${v.mm_net_lots.toLocaleString()} lots` : undefined}
              />
            ))
          : <div style={{ color:"#374151", fontSize:12, padding:"8px 0" }}>CFTC data not loaded</div>
        }
      </Card>
    </>
  )
}

// ── Main App ───────────────────────────────────────────────────────────────
export default function App() {
  const [activeTab,  setActiveTab]  = useState("overview")
  const [data,       setData]       = useState(null)
  const [history,    setHistory]    = useState([])
  const [alerts,     setAlerts]     = useState([])
  const [loading,    setLoading]    = useState(true)
  const [lastUpdate, setLastUpdate] = useState(null)
  const [countdown,  setCountdown]  = useState(30)

  // FIX 1: fetchAll now includes inventory-signals and crack-signals
  const fetchAll = useCallback(async () => {
    try {
      const [all, eia, rig, crack, hist, invSig, crackSig] = await Promise.all([
        fetch(`${API}/api/all`).then(r => r.json()),
        fetch(`${API}/api/eia`).then(r => r.json()),
        fetch(`${API}/api/rig-count`).then(r => r.json()).catch(() => null),
        fetch(`${API}/api/crack`).then(r => r.json()).catch(() => null),
        fetch(`${API}/api/history`).then(r => r.json()).catch(() => []),
        fetch(`${API}/api/inventory-signals`).then(r => r.json()).catch(() => null),
        fetch(`${API}/api/crack-signals`).then(r => r.json()).catch(() => null),
      ])
      const merged  = { ...all, eia, rig_count: rig, crack, inv_signals: invSig, crack_signals: crackSig }
      const histArr = Array.isArray(hist) ? hist : []
      setData(merged)
      setHistory(histArr)
      setLastUpdate(new Date())
      setCountdown(30)
      setAlerts(computeAlerts(histArr, merged?.futures?.contracts))
    } catch(e) { console.error(e) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => {
    fetchAll()
    const d = setInterval(fetchAll, 30000)
    const c = setInterval(() => setCountdown(n => n > 0 ? n-1 : 30), 1000)
    return () => { clearInterval(d); clearInterval(c) }
  }, [fetchAll])

  const comp     = data?.composite?.composite || {}
  const score    = comp.score ?? null
  const scoreCol = score > 0.5 ? "#22c55e" : score < -0.5 ? "#ef4444" : "#f59e0b"
  const hasCrit  = alerts.some(a => a.severity === "critical")

  return (
    <div style={{ background:"#060d18", minHeight:"100vh", color:"#e5e7eb",
      fontFamily:"'Inter','Segoe UI',system-ui,sans-serif",
      display:"flex", flexDirection:"column" }}>

      <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between",
        padding:"8px 20px", background:"#0a0f1a",
        borderBottom:"1px solid #0f1e30", position:"sticky", top:0, zIndex:100 }}>
        <div style={{ display:"flex", alignItems:"center", gap:10 }}>
          <span style={{ fontSize:15, fontWeight:800, color:"#00d98b", letterSpacing:"0.05em" }}>
            ⚡ ENERGY SIGNAL
          </span>
          <span style={{ color:"#0f1e30" }}>|</span>
          <span style={{ width:7, height:7, borderRadius:"50%", display:"inline-block",
            background: loading ? "#f59e0b" : "#22c55e" }} />
          <span style={{ fontSize:11, color:"#4b5563" }}>
            {loading ? "Loading..." : lastUpdate ? `Updated ${lastUpdate.toLocaleTimeString()}` : "Live"}
          </span>
          <span style={{ fontSize:11, color:"#1f2937" }}>· Refresh in {countdown}s</span>
        </div>
        <div style={{ display:"flex", alignItems:"center", gap:6 }}>
          {alerts.length > 0 && (
            <span style={{
              fontSize:10, fontWeight:800,
              color: hasCrit ? "#ef4444" : "#f59e0b",
              background: hasCrit ? "#ef444418" : "#f59e0b18",
              border: `0.5px solid ${hasCrit ? "#ef444440" : "#f59e0b40"}`,
              borderRadius:10, padding:"2px 8px", marginRight:4,
            }}>
              {hasCrit ? "⚠" : "◉"} {alerts.length} ALERT{alerts.length > 1 ? "S" : ""}
            </span>
          )}
          <span style={{ fontSize:11, color:"#4b5563" }}>Composite</span>
          <span style={{ fontSize:16, fontWeight:800, color:scoreCol }}>
            {score != null ? (score > 0 ? "+" : "") + score.toFixed(1) : "—"}
          </span>
          <span style={{ fontSize:11, color:scoreCol,
            background: scoreCol + "22", borderRadius:10, padding:"1px 8px" }}>
            {comp.label || "—"}
          </span>
        </div>
      </div>

      <AlertBanner alerts={alerts} />

      <div style={{ display:"flex", gap:0, padding:"0 20px",
        background:"#0a0f1a", borderBottom:"1px solid #0f1e30", overflowX:"auto" }}>
        {TABS.map(t => (
          <button key={t.id} onClick={() => setActiveTab(t.id)} style={{
            background:"transparent", border:"none", padding:"10px 16px",
            cursor:"pointer", fontSize:12, fontWeight:600,
            borderBottom: activeTab === t.id ? "2px solid #00d98b" : "2px solid transparent",
            color: activeTab === t.id ? "#00d98b" : "#334155",
            letterSpacing:"0.1em", textTransform:"uppercase",
          }}>{t.label}</button>
        ))}
      </div>

      <div style={{ padding:"16px 20px", maxWidth:1400, margin:"0 auto", width:"100%" }}>
        {loading ? (
          <div style={{ display:"flex", alignItems:"center", justifyContent:"center",
            height:300, color:"#00d98b", fontFamily:"monospace", fontSize:12, letterSpacing:"0.2em" }}>
            LOADING SIGNAL DATA...
          </div>
        ) : (
          <>
            {activeTab === "overview"  && <TabOverview  d={data} />}
            {activeTab === "prices"    && <TabPrices    d={data} history={history} />}
            {activeTab === "spreads"   && <TabSpreads   d={data} history={history} />}
            {activeTab === "inventory" && <TabInventory d={data} />}
            {activeTab === "macro"     && <TabMacro     d={data} />}
            {activeTab === "sentiment" && <TabSentiment d={data} />}
          </>
        )}
      </div>

      <div style={{ textAlign:"center", padding:"10px 0", color:"#1a2535",
        fontSize:9, fontFamily:"monospace", borderTop:"1px solid #0f1e30" }}>
        EIA · YAHOO FINANCE · FRED · GIE AGSI+ · OPEN-METEO · CFTC · BAKER HUGHES
      </div>
    </div>
  )
}

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

// ── Alert config ──────────────────────────────────────────────────────────
const ALERT_KEYS = [
  { key: "brent",       label: "Brent ICE",        color: "#3b82f6" },
  { key: "wti",         label: "WTI NYMEX",         color: "#60a5fa" },
  { key: "rbob",        label: "RBOB",              color: "#f59e0b" },
  { key: "heating_oil", label: "Heating Oil/ULSD",  color: "#f97316" },
  // ICE Gasoil placeholder — will activate once feed available
  { key: "gasoil",      label: "ICE Gasoil",        color: "#a78bfa" },
]
const WARN_PCT  = 2   // yellow
const CRIT_PCT  = 4   // red
const TOAST_TTL = 8000 // ms before auto-dismiss

// ── Alert engine ──────────────────────────────────────────────────────────
function compute5dAvg(history, key) {
  if (!history || history.length === 0) return null
  const last5 = history
    .filter(h => h[key] != null)
    .slice(-5)
  if (last5.length < 3) return null
  return last5.reduce((s, h) => s + h[key], 0) / last5.length
}

function buildAlerts(history, currentPrices) {
  const alerts = []
  for (const { key, label, color } of ALERT_KEYS) {
    const current = currentPrices[key]
    if (current == null) continue
    const avg = compute5dAvg(history, key)
    if (avg == null) continue
    const devPct = ((current - avg) / avg) * 100
    const absDev = Math.abs(devPct)
    if (absDev < WARN_PCT) continue

    const isCrit  = absDiv => absDiv >= CRIT_PCT
    const isUp    = devPct > 0
    const severity = isCrit(absDev => absDev)(absDevVal => absDevVal >= CRIT_PCT)(absDevVal => absDevVal)

    // re-do cleanly
    let sev
    if (absDev >= CRIT_PCT) sev = "critical"
    else if (absDev >= WARN_PCT) sev = "warning"
    else continue

    alerts.push({
      id:       `${key}-${Date.now()}-${Math.random()}`,
      key,
      label,
      color,
      current:  Math.round(current * 100) / 100,
      avg5d:    Math.round(avg * 100) / 100,
      devPct:   Math.round(devPct * 10) / 10,
      severity,
      isUp,
    })
  }
  return alerts
}

// ── Toast component ───────────────────────────────────────────────────────
function ToastStack({ toasts, onDismiss }) {
  if (!toasts.length) return null
  return (
    <div style={{
      position: "fixed", top: 56, right: 16, zIndex: 999,
      display: "flex", flexDirection: "column", gap: 8,
      maxWidth: 340, pointerEvents: "none",
    }}>
      {toasts.map(t => {
        const isCrit = t.severity === "critical"
        const bg     = isCrit ? "#1a0a0a" : "#1a1400"
        const border = isCrit ? "#ef4444" : "#f59e0b"
        const badge  = isCrit ? "#ef4444" : "#f59e0b"
        const arrow  = t.isUp ? "▲" : "▼"
        const dirCol = t.isUp ? "#ef4444" : "#22c55e"
        return (
          <div key={t.id} style={{
            background: bg,
            border: `1px solid ${border}`,
            borderLeft: `4px solid ${border}`,
            borderRadius: 8,
            padding: "10px 14px",
            pointerEvents: "auto",
            display: "flex",
            flexDirection: "column",
            gap: 4,
            boxShadow: `0 4px 20px ${border}30`,
            animation: "slideIn 0.2s ease",
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{
                  fontSize: 9, fontWeight: 800, letterSpacing: "0.1em",
                  color: badge, background: badge + "22",
                  borderRadius: 3, padding: "1px 5px",
                }}>
                  {isCrit ? "⚠ CRITICAL" : "◉ WARNING"}
                </span>
                <span style={{ fontSize: 12, fontWeight: 700, color: t.color }}>
                  {t.label}
                </span>
              </div>
              <button onClick={() => onDismiss(t.id)} style={{
                background: "transparent", border: "none",
                color: "#4b5563", cursor: "pointer", fontSize: 14, lineHeight: 1,
                padding: "0 2px",
              }}>×</button>
            </div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
              <span style={{ fontSize: 20, fontWeight: 800, color: "#e5e7eb" }}>
                ${t.current}
              </span>
              <span style={{ fontSize: 13, fontWeight: 700, color: dirCol }}>
                {arrow} {t.devPct > 0 ? "+" : ""}{t.devPct}%
              </span>
              <span style={{ fontSize: 10, color: "#4b5563" }}>vs 5d avg</span>
            </div>
            <div style={{ fontSize: 10, color: "#4b5563" }}>
              5-day avg: <span style={{ color: "#9ca3af" }}>${t.avg5d}</span>
              &nbsp;·&nbsp;
              Deviation: <span style={{ color: badge }}>
                {Math.abs(t.devPct)}% {isCrit ? "(critical)" : "(warning)"}
              </span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ── Helpers ────────────────────────────────────────────────────────────────
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

// ── Chart helpers ──────────────────────────────────────────────────────────
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
              domain={["auto", "auto"]} width={50}
              tickFormatter={v => v.toFixed(0)} />
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

// ── Composite gauge ────────────────────────────────────────────────────────
function CompositeGauge({ score, label, reasons=[] }) {
  const s      = Math.max(-10, Math.min(10, score ?? 0))
  const pct    = ((s + 10) / 20) * 100
  const color  = s > 0.5 ? "#22c55e" : s < -0.5 ? "#ef4444" : "#f59e0b"
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
function TabOverview({ d }) {
  const comp       = d?.composite?.composite || {}
  const eia        = d?.eia                  || {}
  const fut        = d?.futures?.contracts   || {}
  const layers_raw = d?.composite?.layers    || {}

  const layers = [
    {
      label: "Inventory",
      score: layers_raw.inventory?.available
        ? (layers_raw.inventory.score / 10)
        : (eia?.cushing_stocks?.vs_5yr_avg < 0 ? 0.5 : -0.5),
      label2: layers_raw.inventory?.label,
    },
    {
      label: "Crack",
      score: layers_raw.crack?.available ? (layers_raw.crack.score / 10) : 0,
      label2: layers_raw.crack?.label,
    },
    {
      label: "Macro",
      score: layers_raw.macro?.available ? (layers_raw.macro.score / 10) : 0,
      label2: layers_raw.macro?.label,
    },
    {
      label: "Demand / Weather",
      score: layers_raw.demand?.available ? (layers_raw.demand.score / 10) : 0,
      label2: layers_raw.demand?.label,
    },
    {
      label: "EU Gas Storage",
      score: layers_raw.gie?.available ? (layers_raw.gie.score / 10) : 0,
      label2: layers_raw.gie?.label,
    },
    {
      label: "Positioning",
      score: layers_raw.positioning?.available ? (layers_raw.positioning.score / 10) : 0,
      label2: layers_raw.positioning?.label,
    },
    {
      label: "News / Sentiment",
      score: layers_raw.news?.available ? (layers_raw.news.score / 10) : 0,
      label2: layers_raw.news?.label,
    },
    {
      label: "Rig Count",
      score: d?.rig_count?.signal?.direction === "bullish" ? 0.5
        : d?.rig_count?.signal?.direction === "bearish" ? -0.5 : 0,
      label2: d?.rig_count?.signal?.label,
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
                <div style={{ width: Math.abs(l.score) * 100 + "%", height: "100%",
                  background: col, borderRadius: 2 }} />
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
          <Row label="Cushing Stocks"   value={fmt(eia.cushing_stocks?.value,1)}     unit="mmbbls" signal={eia.cushing_stocks?.vs_5yr_avg < 0 ? "BELOW 5YR" : "ABOVE 5YR"}   note={`WoW: ${fmt(eia.cushing_stocks?.wow,1)}`} />
          <Row label="Gasoline Stocks"  value={fmt(eia.gasoline_stocks?.value,1)}    unit="mmbbls" signal={eia.gasoline_stocks?.vs_5yr_avg < 0 ? "BELOW 5YR" : "ABOVE 5YR"}  note={`5yr: ${fmt(eia.gasoline_stocks?.vs_5yr_avg,1)}`} />
          <Row label="Distillate Stks"  value={fmt(eia.distillate_stocks?.value,1)}  unit="mmbbls" signal={eia.distillate_stocks?.vs_5yr_avg < 0 ? "BELOW 5YR" : "ABOVE 5YR"} note={`5yr: ${fmt(eia.distillate_stocks?.vs_5yr_avg,1)}`} />
          <Row label="Crude Production" value={fmt(eia.crude_production?.value,2)}   unit="mbd"    note={`WoW: ${fmt(eia.crude_production?.wow,3)}`} />
          <Row label="Refinery Util"    value={fmt(eia.refinery_util?.value,1)}      unit="%"      signal={eia.refinery_util?.value > 90 ? "HIGH" : "NORMAL"} note={`WoW: ${fmt(eia.refinery_util?.wow,1)}`} />
          <Row label="Days of Cover"    value={fmt(eia.days_cover,1)}                unit="days"   signal={eia.days_cover < 54 ? "TIGHT" : eia.days_cover > 62 ? "AMPLE" : "NORMAL"} />
        </div>
      </Card>
    </div>
  )
}

// ── Prices Tab ─────────────────────────────────────────────────────────────
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

// ── Spreads Tab ────────────────────────────────────────────────────────────
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
          <div key={i} style={{ display:"flex", gap:8, padding:"5px 0",
            borderBottom:"1px solid #0f1e30", fontSize:11 }}>
            <span style={{ color:"#f59e0b", fontWeight:700, minWidth:150 }}>{k}</span>
            <span style={{ color:"#6b7280" }}>{v}</span>
          </div>
        ))}
      </Card>
    </>
  )
}

function TabInventory({ d }) {
  const eia = d?.eia || {}
  return (
    <>
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
        <Row label="DXY Broad Dollar" value={fmt(fred.dxy_broad?.latest,2)}                      signal={fred.dxy_broad?.signal} note="USD strength → bearish oil" />
        <Row label="SOFR"             value={fmt(fred.sofr?.latest,3)}             unit="%"       note="Storage carry cost driver" />
        <Row label="Fed Funds Rate"   value={fmt(fred.fed_funds?.latest,2)}        unit="%"  />
        <Row label="US 10Y Yield"     value={fmt(fred.us_10y_yield?.latest,3)}     unit="%"  />
        <Row label="Storage Carry/mo" value={fmt(der.storage_carry?.total_carry_per_bbl_mo,2)} unit="$/bbl" note="Contango threshold for storage" />
        <Row label="Macro Signal"     value=""                                     signal={der.macro_composite?.composite_signal} />
      </Card>

      <Card title="European Gas Storage (GIE AGSI+)" style={{ marginTop: 12 }}>
        {gie.regions && Object.entries(gie.regions)
          .filter(([k,v]) => !v.error)
          .slice(0,6)
          .map(([k,v]) => (
            <Row key={k}
              label={v.label || k}
              value={fmt(v.fill_pct, 1)}
              unit="% full"
              signal={v.crude_signal}
              note={v.wow_fill_pp != null ? `WoW: +${fmt(v.wow_fill_pp,2)}pp` : undefined}
            />
          ))
        }
        {(!gie.regions || Object.values(gie.regions).every(v => v.error)) &&
          <div style={{ color:"#374151", fontSize:12, padding:"8px 0" }}>GIE data not loaded</div>
        }
      </Card>

      <Card title="Weather Demand (HDD/CDD)" style={{ marginTop: 12 }}>
        {wx.locations
          ? Object.entries(wx.locations).slice(0,6).map(([k,v]) => (
            <Row key={k}
              label={v.label || k}
              value={fmt(v.hdd_7d_forecast, 1)}
              unit="HDD"
              signal={v.demand_signal}
              note={`CDD: ${fmt(v.cdd_7d_forecast, 1)}`}
            />
          ))
          : <div style={{ color:"#374151", fontSize:12, padding:"8px 0" }}>Weather data not loaded</div>
        }
      </Card>
    </>
  )
}

function TabSentiment({ d }) {
  const news = d?.news           || {}
  const cftc = d?.cftc           || {}
  const rig  = d?.rig_count?.signal || {}

  const headlines = news.headlines || news.articles || []
  const score     = news.composite_score ?? news.score ?? null
  const scoreCol  = score > 0 ? "#22c55e" : score < 0 ? "#ef4444" : "#f59e0b"

  return (
    <>
      <Card title="Rig Count Signal">
        <Row label="Oil-Directed Rigs" value={fmt(d?.rig_count?.latest?.oil_rigs,0)} unit="rigs" signal={rig.label} />
        <Row label="WoW Change"        value={fmt(d?.rig_count?.latest?.wow_oil,0)}  unit="rigs" signal={rig.direction} />
        <Row label="5-Week Trend"      value={rig.five_week_trend || "—"} />
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
            <Row label="Bullish signals" value={news.bullish_count ?? "—"} />
            <Row label="Bearish signals" value={news.bearish_count ?? "—"} />
            <Row label="Geo alerts"      value={news.geo_alerts    ?? "—"} />
          </div>
        </div>
        {headlines.slice(0,8).map((h,i) => (
          <div key={i} style={{ display:"flex", justifyContent:"space-between", gap:8,
            fontSize:11, color:"#9ca3af", padding:"5px 0", borderBottom:"1px solid #0f1e30" }}>
            <span style={{ flex:1 }}>{h.title || h.headline}</span>
            <span style={{ color: h.score > 0 ? "#22c55e" : h.score < 0 ? "#ef4444" : "#6b7280",
              fontWeight:700, whiteSpace:"nowrap" }}>
              {h.score != null ? (h.score > 0 ? "+" : "") + Number(h.score).toFixed(1) : "—"}
            </span>
          </div>
        ))}
      </Card>

      <Card title="CFTC Positioning" style={{ marginTop: 12 }}>
        {cftc.contracts
          ? Object.entries(cftc.contracts).slice(0,5).map(([k,v]) => (
            <Row key={k} label={k} value={fmt(v?.net_long_pct,1)} unit="% net long" signal={v?.signal} />
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
  const [loading,    setLoading]    = useState(true)
  const [lastUpdate, setLastUpdate] = useState(null)
  const [countdown,  setCountdown]  = useState(30)
  const [toasts,     setToasts]     = useState([])
  const prevPricesRef               = useRef({})

  // ── Dismiss a toast by id ───────────────────────────────────────────────
  const dismissToast = useCallback((id) => {
    setToasts(prev => prev.filter(t => t.id !== id))
  }, [])

  // ── Fire alerts when history + prices are fresh ─────────────────────────
  const fireAlerts = useCallback((hist, contracts) => {
    if (!hist.length || !contracts) return

    const currentPrices = {
      brent:       contracts.brent?.price_bbl       ?? null,
      wti:         contracts.wti?.price_bbl         ?? null,
      rbob:        contracts.rbob?.price_bbl        ?? null,
      heating_oil: contracts.heating_oil?.price_bbl ?? null,
      gasoil:      contracts.gasoil?.price_bbl      ?? null,
    }

    // Skip if prices unchanged from last check
    const prev = prevPricesRef.current
    const changed = Object.entries(currentPrices).some(([k,v]) => v !== prev[k])
    if (!changed) return
    prevPricesRef.current = currentPrices

    // Use last 6 rows (5 historical + today) so avg is prior 5 days only
    const histForAvg = hist.slice(0, -1)  // exclude today from avg
    const newAlerts  = []

    for (const { key, label, color } of ALERT_KEYS) {
      const current = currentPrices[key]
      if (current == null) continue

      const last5 = histForAvg.filter(h => h[key] != null).slice(-5)
      if (last5.length < 3) continue

      const avg5d  = last5.reduce((s, h) => s + h[key], 0) / last5.length
      const devPct = ((current - avg5d) / avg5d) * 100
      const absDev = Math.abs(devPct)

      if (absDev < WARN_PCT) continue

      const severity = absDev >= CRIT_PCT ? "critical" : "warning"

      newAlerts.push({
        id:       `${key}-${Date.now()}-${Math.random().toString(36).slice(2)}`,
        key,
        label,
        color,
        current:  Math.round(current * 100) / 100,
        avg5d:    Math.round(avg5d * 100) / 100,
        devPct:   Math.round(devPct * 10) / 10,
        severity,
        isUp:     devPct > 0,
      })
    }

    if (newAlerts.length === 0) return

    setToasts(prev => {
      // Deduplicate by key — replace existing same-commodity toast
      const filtered = prev.filter(t => !newAlerts.find(a => a.key === t.key))
      return [...filtered, ...newAlerts]
    })

    // Auto-dismiss each toast after TTL
    newAlerts.forEach(alert => {
      setTimeout(() => dismissToast(alert.id), TOAST_TTL)
    })
  }, [dismissToast])

  const fetchAll = useCallback(async () => {
    try {
      const [all, eia, rig, crack, hist] = await Promise.all([
        fetch(`${API}/api/all`).then(r => r.json()),
        fetch(`${API}/api/eia`).then(r => r.json()),
        fetch(`${API}/api/rig-count`).then(r => r.json()).catch(() => null),
        fetch(`${API}/api/crack`).then(r => r.json()).catch(() => null),
        fetch(`${API}/api/history`).then(r => r.json()).catch(() => []),
      ])
      const merged = { ...all, eia, rig_count: rig, crack }
      setData(merged)
      const histArr = Array.isArray(hist) ? hist : []
      setHistory(histArr)
      setLastUpdate(new Date())
      setCountdown(30)

      // Fire alert check after data lands
      fireAlerts(histArr, merged?.futures?.contracts)
    } catch(e) { console.error(e) }
    finally { setLoading(false) }
  }, [fireAlerts])

  useEffect(() => {
    fetchAll()
    const d = setInterval(fetchAll, 30000)
    const c = setInterval(() => setCountdown(n => n > 0 ? n-1 : 30), 1000)
    return () => { clearInterval(d); clearInterval(c) }
  }, [fetchAll])

  const comp     = data?.composite?.composite || {}
  const score    = comp.score ?? null
  const scoreCol = score > 0.5 ? "#22c55e" : score < -0.5 ? "#ef4444" : "#f59e0b"

  return (
    <div style={{ background:"#060d18", minHeight:"100vh", color:"#e5e7eb",
      fontFamily:"'Inter','Segoe UI',system-ui,sans-serif" }}>

      {/* CSS for toast animation */}
      <style>{`
        @keyframes slideIn {
          from { opacity: 0; transform: translateX(40px); }
          to   { opacity: 1; transform: translateX(0); }
        }
      `}</style>

      {/* Toast stack */}
      <ToastStack toasts={toasts} onDismiss={dismissToast} />

      {/* Top bar */}
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
          {/* Alert count badge */}
          {toasts.length > 0 && (
            <span style={{
              fontSize:10, fontWeight:800,
              color: toasts.some(t => t.severity === "critical") ? "#ef4444" : "#f59e0b",
              background: toasts.some(t => t.severity === "critical") ? "#ef444422" : "#f59e0b22",
              borderRadius:10, padding:"2px 8px", marginRight:6,
              cursor:"pointer",
            }} onClick={() => setToasts([])}>
              ⚠ {toasts.length} ALERT{toasts.length > 1 ? "S" : ""} · CLEAR ALL
            </span>
          )}
          <span style={{ fontSize:11, color:"#4b5563" }}>Composite Index</span>
          <span style={{ fontSize:16, fontWeight:800, color:scoreCol }}>
            {score != null ? (score > 0 ? "+" : "") + score.toFixed(1) : "—"}
          </span>
          <span style={{ fontSize:11, color:scoreCol,
            background: scoreCol + "22", borderRadius:10, padding:"1px 8px" }}>
            {comp.label || "—"}
          </span>
        </div>
      </div>

      {/* Tab bar */}
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

      {/* Content */}
      <div style={{ padding:"16px 20px", maxWidth:1400, margin:"0 auto" }}>
        {loading ? (
          <div style={{ display:"flex", alignItems:"center", justifyContent:"center",
            height:300, color:"#00d98b", fontFamily:"monospace",
            fontSize:12, letterSpacing:"0.2em" }}>
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

      <div style={{ textAlign:"center", padding:"10px 0",
        color:"#1a2535", fontSize:9, fontFamily:"monospace",
        borderTop:"1px solid #0f1e30" }}>
        EIA · YAHOO FINANCE · FRED · GIE AGSI+ · OPEN-METEO · CFTC · BAKER HUGHES
      </div>
    </div>
  )
}

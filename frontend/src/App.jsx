import React, { useState, useEffect, useCallback, useRef } from "react"
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, Area, ComposedChart
} from "recharts"

const API = ""

const TABS = [
  { id: "overview",     label: "Overview" },
  { id: "prices",       label: "Prices" },
  { id: "spreads",      label: "Spreads" },
  { id: "curve",        label: "Futures Curve" },
  { id: "signal",       label: "Trade Signal" },
  { id: "seasonality",  label: "Seasonality" },
  { id: "inventory",    label: "Inventory" },
  { id: "macro",        label: "Macro" },
  { id: "sentiment",    label: "Sentiment" },
  { id: "geo",          label: "Geopolitical risk" },
]

const ALERT_KEYS = [
  { key: "brent",       label: "Brent ICE",  color: "#3b82f6" },
  { key: "wti",         label: "WTI NYMEX",  color: "#60a5fa" },
  { key: "rbob",        label: "RBOB",       color: "#f59e0b" },
  { key: "heating_oil", label: "Heating Oil",color: "#f97316" },
  { key: "gasoil",      label: "ULSD (EIA)", color: "#a78bfa" },
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
    const last5  = histForAvg.filter(h => h[key] != null).slice(-5)
    if (last5.length < 3) continue
    const avg5d  = last5.reduce((s, h) => s + h[key], 0) / last5.length
    const last35 = histForAvg.filter(h => h[key] != null).slice(-35)
    const avg5w  = last35.length >= 5
      ? last35.reduce((s, h) => s + h[key], 0) / last35.length
      : null
    const dev5d  = ((current - avg5d) / avg5d) * 100
    const dev5w  = avg5w != null ? ((current - avg5w) / avg5w) * 100 : null
    const absDev = Math.abs(dev5d)
    if (absDev < WARN_PCT) continue
    alerts.push({
      key, label, color,
      current:  Math.round(current * 100) / 100,
      avg5d:    Math.round(avg5d * 100) / 100,
      avg5w:    avg5w != null ? Math.round(avg5w * 100) / 100 : null,
      dev5d:    Math.round(dev5d * 10) / 10,
      dev5w:    dev5w != null ? Math.round(dev5w * 10) / 10 : null,
      severity: absDev >= CRIT_PCT ? "critical" : "warning",
      isUp5d:   dev5d > 0,
      trend5w:  dev5w != null ? (dev5w > 1 ? "up" : dev5w < -1 ? "down" : "flat") : null,
    })
  }
  return alerts.sort((a, b) => {
    if (a.severity !== b.severity) return a.severity === "critical" ? -1 : 1
    return Math.abs(b.dev5d) - Math.abs(a.dev5d)
  })
}

function AlertBanner({ alerts }) {
  if (!alerts || alerts.length === 0) return null
  const hasCrit = alerts.some(a => a.severity === "critical")
  return (
    <div style={{ background: "#0d1117", borderBottom: `1px solid ${hasCrit ? "#ef444440" : "#f59e0b30"}`,
      padding: "5px 20px", display: "flex", alignItems: "flex-start", gap: 6,
      overflowX: "auto", flexShrink: 0 }}>
      <span style={{ fontSize: 9, fontWeight: 800, letterSpacing: "0.12em",
        color: hasCrit ? "#ef4444" : "#f59e0b", whiteSpace: "nowrap",
        marginRight: 4, flexShrink: 0, paddingTop: 3 }}>
        {hasCrit ? "⚠" : "◉"} ALERTS
      </span>
      <span style={{ width: 1, minHeight: 28, background: "#1a2535", flexShrink: 0 }} />
      {alerts.map(a => {
        const isCrit   = a.severity === "critical"
        const border   = isCrit ? "#ef444455" : "#f59e0b44"
        const bg       = isCrit ? "#ef444410" : "#f59e0b0d"
        const sevCol   = isCrit ? "#ef4444"   : "#f59e0b"
        const dirCol5d = a.isUp5d ? "#ef4444" : "#22c55e"
        const arrow5d  = a.isUp5d ? "▲" : "▼"
        const trend5wCol   = a.trend5w === "up" ? "#ef4444" : a.trend5w === "down" ? "#22c55e" : "#6b7280"
        const trend5wArrow = a.trend5w === "up" ? "↑" : a.trend5w === "down" ? "↓" : "→"
        const trend5wLabel = a.trend5w === "up" ? "uptrend" : a.trend5w === "down" ? "downtrend" : "flat"
        return (
          <div key={a.key} style={{ display: "flex", flexDirection: "column", gap: 2,
            background: bg, border: `0.5px solid ${border}`, borderRadius: 6,
            padding: "4px 10px", whiteSpace: "nowrap", flexShrink: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
              <span style={{ fontSize: 9, fontWeight: 800, color: sevCol }}>{isCrit ? "⚠" : "◉"}</span>
              <span style={{ fontSize: 11, fontWeight: 700, color: a.color }}>{a.label}</span>
              <span style={{ fontSize: 12, fontWeight: 800, color: "#e5e7eb" }}>${a.current}</span>
              <span style={{ fontSize: 11, fontWeight: 700, color: dirCol5d }}>
                {arrow5d}{a.dev5d > 0 ? "+" : ""}{a.dev5d}%
              </span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 9, color: "#6b7280" }}>
                5d avg:<span style={{ color: "#9ca3af", marginLeft: 3 }}>${a.avg5d}</span>
              </span>
              {a.avg5w != null && <span style={{ fontSize: 9, color: "#1a2535" }}>|</span>}
              {a.avg5w != null && (
                <span style={{ fontSize: 9, color: "#6b7280" }}>
                  5w avg:<span style={{ color: "#9ca3af", marginLeft: 3 }}>${a.avg5w}</span>
                  <span style={{ color: trend5wCol, fontWeight: 700, marginLeft: 4 }}>
                    {trend5wArrow} {trend5wLabel}
                  </span>
                </span>
              )}
            </div>
          </div>
        )
      })}
      <span style={{ fontSize: 9, color: "#1f2937", marginLeft: "auto",
        flexShrink: 0, whiteSpace: "nowrap", paddingTop: 3 }}>updates every 30s</span>
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
    <span style={{ fontSize: 10, fontWeight: 700, color: col,
      background: col + "22", borderRadius: 4, padding: "1px 6px", whiteSpace: "nowrap" }}>
      {label}
    </span>
  )
}

function Row({ label, value, unit, signal, note, highlight }) {
  const col = signalCol(signal)
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2,
      padding: "7px 0", borderBottom: "1px solid #0f1e30",
      background: highlight ? "#0d2a1a" : "transparent" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span style={{ fontSize: 10, color: "#6b7280", textTransform: "uppercase", letterSpacing: "0.07em" }}>
          {label}
        </span>
        {note && <span style={{ fontSize: 9, color: "#374151", fontStyle: "italic" }}>{note}</span>}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 14, fontWeight: 700, color: "#e5e7eb", fontFamily: "monospace" }}>
          {value}
          {unit && <span style={{ fontSize: 10, color: "#6b7280", marginLeft: 3 }}>{unit}</span>}
        </span>
        {signal && <Badge label={signal} />}
      </div>
    </div>
  )
}

function Card({ title, children, style={} }) {
  return (
    <div style={{ background: "#0d1117", border: "1px solid #1a2535",
      borderRadius: 10, padding: "14px 16px", ...style }}>
      {title && <div style={{ fontSize: 10, fontWeight: 700, color: "#4b5563",
        letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 10 }}>{title}</div>}
      {children}
    </div>
  )
}

function PriceCard({ label, price, unit, change, color, error }) {
  const isPos = change > 0, isNeg = change < 0
  return (
    <div style={{ background: "#0a1628", border: `1px solid ${color}30`, borderRadius: 10, padding: "14px 16px" }}>
      <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 6 }}>{label}</div>
      {error ? (
        <div style={{ fontSize: 12, color: "#374151", marginBottom: 4 }}>Feed unavailable</div>
      ) : (
        <div style={{ fontSize: 24, fontWeight: 800, color, letterSpacing: "-0.5px", lineHeight: 1 }}>{fmt(price)}</div>
      )}
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6 }}>
        <span style={{ fontSize: 10, color: "#374151" }}>{unit}</span>
        {!error && change != null && (
          <span style={{ fontSize: 11, fontWeight: 700, color: isPos ? "#22c55e" : isNeg ? "#ef4444" : "#6b7280" }}>
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
  return history.filter(h => h[key] != null).map(h => ({
    date: h.date?.slice(5), value: h[key],
    mean: band.mean, upper: band.upper, lower: band.lower,
    band: band.upper != null ? [band.lower, band.upper] : null,
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
      <div style={{ background: "#0d1117", border: "1px solid #1a2535", borderRadius: 6, padding: "8px 12px", fontSize: 11 }}>
        <div style={{ color: "#6b7280", marginBottom: 4 }}>{label}</div>
        {val && <div style={{ color, fontWeight: 600 }}>{fmt(val.value)} {unit}</div>}
      </div>
    )
  }
  return (
    <Card style={{ marginBottom: 0 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
        <div>
          <div style={{ fontSize: 10, fontWeight: 700, color: "#4b5563", letterSpacing: "0.12em", textTransform: "uppercase" }}>{title}</div>
          {currentSignal && <div style={{ marginTop: 3 }}><Badge label={currentSignal} /></div>}
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 22, fontWeight: 800, color, lineHeight: 1 }}>{fmt(currentPrice ?? latestVal)}</div>
          <div style={{ fontSize: 10, color: "#374151" }}>{unit}</div>
        </div>
      </div>
      {!hasData ? (
        <div style={{ height: 120, display: "flex", alignItems: "center", justifyContent: "center",
          color: "#1f2937", fontSize: 10, fontFamily: "monospace" }}>NO HISTORY YET — BUILDING DATA...</div>
      ) : (
        <ResponsiveContainer width="100%" height={140}>
          <ComposedChart data={data} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#0f1e30" />
            <XAxis dataKey="date" tick={{ fontSize: 9, fill: "#374151" }} tickLine={false} interval="preserveStartEnd" />
            <YAxis tick={{ fontSize: 9, fill: "#374151" }} tickLine={false} domain={["auto", "auto"]} width={50} tickFormatter={v => v.toFixed(0)} />
            <Tooltip content={<CustomTooltip />} />
            {hasBand && <Area dataKey="band" stroke="none" fill={color} fillOpacity={0.07} name="band" legendType="none" />}
            {hasBand && data[0]?.mean != null && (
              <ReferenceLine y={data[0].mean} stroke={color} strokeOpacity={0.35} strokeDasharray="4 4"
                label={{ value: `avg ${fmt(data[0].mean, 1)}`, position: "insideTopRight", fontSize: 8, fill: color, opacity: 0.6 }} />
            )}
            <Line dataKey="value" stroke={color} strokeWidth={2} dot={false} activeDot={{ r: 3, fill: color }} name="value" />
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
        <span style={{ fontSize: 13, fontWeight: 700, color, background: color + "22", borderRadius: 20, padding: "3px 12px" }}>
          {label || "NEUTRAL"}
        </span>
      </div>
      <div style={{ position: "relative", height: 6, background: "#1a2535", borderRadius: 3, marginBottom: 4 }}>
        <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: pct + "%", background: color, borderRadius: 3, transition: "width 0.6s" }} />
        <div style={{ position: "absolute", left: "50%", top: 0, bottom: 0, width: 1, background: "#374151" }} />
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, color: "#374151", marginBottom: 12 }}>
        <span>-10 BEARISH</span><span>NEUTRAL</span><span>BULLISH +10</span>
      </div>
      {reasons.map((r,i) => (
        <div key={i} style={{ fontSize: 11, color: "#6b7280", padding: "2px 0 2px 8px", borderLeft: "2px solid #1a2535", marginBottom: 3 }}>· {r}</div>
      ))}
    </div>
  )
}

function DivergenceFlag({ divergence, momentum }) {
  if (!momentum) return null
  const { avg_5w, avg_5d, dev_from_5w_pct, dev_from_5d_pct, trend_direction, label: momLabel } = momentum
  const trendCol   = trend_direction === "UP" ? "#22c55e" : trend_direction === "DOWN" ? "#ef4444" : "#6b7280"
  const trendArrow = trend_direction === "UP" ? "↑" : trend_direction === "DOWN" ? "↓" : "→"
  const dev5wCol   = dev_from_5w_pct > 0 ? "#22c55e" : dev_from_5w_pct < 0 ? "#ef4444" : "#6b7280"
  const dev5dCol   = dev_from_5d_pct > 0 ? "#22c55e" : dev_from_5d_pct < 0 ? "#ef4444" : "#6b7280"
  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ background: "#0a1628", border: "1px solid #1a2535", borderRadius: 8,
        padding: "10px 12px", marginBottom: divergence ? 8 : 0 }}>
        <div style={{ fontSize: 9, fontWeight: 700, color: "#4b5563",
          textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 8 }}>Brent Price Context</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
          <div>
            <div style={{ fontSize: 9, color: "#374151", marginBottom: 3 }}>vs 5-day avg</div>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#9ca3af" }}>${avg_5d != null ? avg_5d.toFixed(2) : "—"}</div>
            <div style={{ fontSize: 12, fontWeight: 800, color: dev5dCol }}>{dev_from_5d_pct != null ? (dev_from_5d_pct > 0 ? "+" : "") + dev_from_5d_pct.toFixed(1) + "%" : "—"}</div>
            <div style={{ fontSize: 9, color: "#374151", marginTop: 2 }}>volatility signal</div>
          </div>
          <div>
            <div style={{ fontSize: 9, color: "#374151", marginBottom: 3 }}>vs 5-week avg</div>
            <div style={{ fontSize: 11, fontWeight: 700, color: "#9ca3af" }}>${avg_5w != null ? avg_5w.toFixed(2) : "—"}</div>
            <div style={{ fontSize: 12, fontWeight: 800, color: dev5wCol }}>{dev_from_5w_pct != null ? (dev_from_5w_pct > 0 ? "+" : "") + dev_from_5w_pct.toFixed(1) + "%" : "—"}</div>
            <div style={{ fontSize: 9, color: "#374151", marginTop: 2 }}>short-term trend</div>
          </div>
          <div>
            <div style={{ fontSize: 9, color: "#374151", marginBottom: 3 }}>trend direction</div>
            <div style={{ fontSize: 20, fontWeight: 900, color: trendCol, lineHeight: 1 }}>{trendArrow}</div>
            <div style={{ fontSize: 11, fontWeight: 700, color: trendCol, marginTop: 2 }}>{momLabel || trend_direction || "—"}</div>
          </div>
        </div>
      </div>
      {divergence && (
        <div style={{ background: divergence.severity === "STRONG" ? "#f9731610" : "#f59e0b0d",
          border: `1px solid ${divergence.severity === "STRONG" ? "#f9731640" : "#f59e0b30"}`,
          borderRadius: 8, padding: "10px 12px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
            <span style={{ fontSize: 11, fontWeight: 800, color: divergence.severity === "STRONG" ? "#f97316" : "#f59e0b" }}>⚡ DIVERGENCE</span>
            <span style={{ fontSize: 9, fontWeight: 700, color: divergence.severity === "STRONG" ? "#f97316" : "#f59e0b",
              background: divergence.severity === "STRONG" ? "#f9731620" : "#f59e0b20", borderRadius: 3, padding: "1px 6px" }}>
              {divergence.severity}
            </span>
          </div>
          <div style={{ fontSize: 11, color: "#9ca3af", lineHeight: 1.5 }}>{divergence.message}</div>
          <div style={{ fontSize: 9, color: "#374151", marginTop: 6, fontStyle: "italic" }}>
            {divergence.type === "BULL_FUNDAMENTAL_BEAR_PRICE"
              ? "Fundamentals leading price — wait for price to confirm."
              : "Price leading fundamentals — rally may be short-lived."}
          </div>
        </div>
      )}
    </div>
  )
}

function TabOverview({ d }) {
  const comp       = d?.composite?.composite     || {}
  const eia        = d?.eia                      || {}
  const fut        = d?.futures?.contracts       || {}
  const layers_raw = d?.composite?.layers        || {}
  const invComp    = d?.inv_signals?.composite   || {}
  const crackComp  = d?.crack_signals?.composite || {}
  const invSigs    = d?.inv_signals?.signals     || {}
  const momentum   = comp.momentum   || null
  const divergence = comp.divergence || null
  const layers = [
    { label: "Inventory",     score: invComp.score != null ? invComp.score / 10 : (eia?.cushing_stocks?.vs_5yr_avg < 0 ? 0.5 : -0.5), label2: invComp.overall_signal || "NO_DATA" },
    { label: "Crack",         score: crackComp.score != null ? crackComp.score / 10 : 0, label2: crackComp.overall_signal || "NO_DATA" },
    { label: "Price Momentum",score: layers_raw.momentum?.available ? (layers_raw.momentum.score / 10) : 0, label2: layers_raw.momentum?.label || "NO_DATA" },
    { label: "Macro",         score: layers_raw.macro?.available ? (layers_raw.macro.score / 10) : 0, label2: layers_raw.macro?.label },
    { label: "Demand/Weather",score: layers_raw.demand?.available ? (layers_raw.demand.score / 10) : 0, label2: layers_raw.demand?.label },
    { label: "EU Gas Storage",score: invSigs.gie_storage?.signal === "BULLISH" ? 0.8 : invSigs.gie_storage?.signal === "BEARISH" ? -0.8 : 0, label2: invSigs.gie_storage?.signal || "NO_DATA" },
    { label: "Positioning",   score: layers_raw.positioning?.available ? (layers_raw.positioning.score / 10) : 0, label2: layers_raw.positioning?.label },
    { label: "News/Sentiment",score: layers_raw.news?.available ? (layers_raw.news.score / 10) : 0, label2: layers_raw.news?.label },
    { label: "Rig Count",     score: d?.rig_count?.signal?.direction === "bullish" ? 0.5 : d?.rig_count?.signal?.direction === "bearish" ? -0.5 : 0, label2: `${d?.rig_count?.signal?.label || "—"} ${d?.rig_count?.latest?.oil_rigs ? `(${d.rig_count.latest.oil_rigs})` : ""}` },
  ]
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
      <Card title="Composite Index">
        <CompositeGauge score={comp.score} label={comp.label} reasons={comp.reasons || []} />
      </Card>
      <Card title="Signal Layers">
        {layers.map((l,i) => {
          const col = l.score > 0 ? "#22c55e" : l.score < 0 ? "#ef4444" : "#374151"
          const isMomentum = l.label === "Price Momentum"
          const momBearishFlag = isMomentum && l.score < -0.2 && (comp.score > 3)
          return (
            <div key={i} style={{ marginBottom: 10,
              padding: momBearishFlag ? "4px 6px" : 0,
              background: momBearishFlag ? "#1a0a0a" : "transparent",
              borderRadius: momBearishFlag ? 4 : 0,
              border: momBearishFlag ? "1px solid #ef444430" : "none" }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 4 }}>
                <span style={{ color: "#9ca3af" }}>
                  {l.label}
                  {l.label2 && <span style={{ color: "#374151", fontSize: 10, marginLeft: 6 }}>{l.label2}</span>}
                  {momBearishFlag && <span style={{ color: "#ef4444", fontSize: 9, marginLeft: 6 }}>↓ bearish outlier</span>}
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
          <PriceCard label="Brent ICE"   price={fut.brent?.price_bbl}       unit="$/bbl" change={fut.brent?.change_pct}       color="#3b82f6" error={!!fut.brent?.error} />
          <PriceCard label="WTI NYMEX"   price={fut.wti?.price_bbl}         unit="$/bbl" change={fut.wti?.change_pct}         color="#60a5fa" error={!!fut.wti?.error} />
          <PriceCard label="RBOB"        price={fut.rbob?.price_bbl}        unit="$/bbl" change={fut.rbob?.change_pct}        color="#f59e0b" error={!!fut.rbob?.error} />
          <PriceCard label="ULSD / HO"   price={fut.heating_oil?.price_bbl} unit="$/bbl" change={fut.heating_oil?.change_pct} color="#f97316" error={!!fut.heating_oil?.error} />
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

function PriceMomentumBar({ history, priceKey, currentPrice, color }) {
  if (!history || history.length < 5 || currentPrice == null) return null
  const histForAvg = history.slice(0, -1).filter(h => h[priceKey] != null)
  const last5  = histForAvg.slice(-5)
  const last35 = histForAvg.slice(-35)
  if (last5.length < 3) return null
  const avg5d = last5.reduce((s, h) => s + h[priceKey], 0) / last5.length
  const avg5w = last35.length >= 5 ? last35.reduce((s, h) => s + h[priceKey], 0) / last35.length : null
  const dev5d = ((currentPrice - avg5d) / avg5d) * 100
  const dev5w = avg5w != null ? ((currentPrice - avg5w) / avg5w) * 100 : null
  const devCol   = v => v == null ? "#6b7280" : v > 0 ? "#22c55e" : v < 0 ? "#ef4444" : "#6b7280"
  const devArrow = v => v == null ? "→" : v > 0.5 ? "▲" : v < -0.5 ? "▼" : "→"
  const trendLabel = dev5w == null ? null : dev5w > 4 ? "UPTREND" : dev5w > 1 ? "mild uptrend" : dev5w > -1 ? "flat" : dev5w > -4 ? "mild downtrend" : "DOWNTREND"
  const trendCol   = dev5w == null ? "#6b7280" : dev5w > 1 ? "#22c55e" : dev5w < -1 ? "#ef4444" : "#6b7280"
  return (
    <div style={{ display: "grid", gridTemplateColumns: avg5w != null ? "1fr 1fr 1fr" : "1fr 1fr",
      gap: 0, borderTop: `1px solid ${color}20`, marginTop: 4 }}>
      <div style={{ padding: "6px 10px", borderRight: "1px solid #0f1e30" }}>
        <div style={{ fontSize: 9, color: "#4b5563", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 2 }}>Live</div>
        <div style={{ fontSize: 13, fontWeight: 800, color, fontFamily: "monospace" }}>${currentPrice.toFixed(2)}</div>
      </div>
      <div style={{ padding: "6px 10px", borderRight: avg5w != null ? "1px solid #0f1e30" : "none" }}>
        <div style={{ fontSize: 9, color: "#4b5563", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 2 }}>
          vs 5-day avg <span style={{ color: "#374151", fontWeight: 400, textTransform: "none" }}>volatility</span>
        </div>
        <div style={{ display: "flex", alignItems: "baseline", gap: 5 }}>
          <span style={{ fontSize: 11, color: "#6b7280", fontFamily: "monospace" }}>${avg5d.toFixed(2)}</span>
          <span style={{ fontSize: 12, fontWeight: 800, color: devCol(dev5d) }}>
            {devArrow(dev5d)}{dev5d > 0 ? "+" : ""}{dev5d.toFixed(1)}%
          </span>
        </div>
      </div>
      {avg5w != null && (
        <div style={{ padding: "6px 10px" }}>
          <div style={{ fontSize: 9, color: "#4b5563", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 2 }}>
            vs 5-week avg <span style={{ color: "#374151", fontWeight: 400, textTransform: "none" }}>trend</span>
          </div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 5 }}>
            <span style={{ fontSize: 11, color: "#6b7280", fontFamily: "monospace" }}>${avg5w.toFixed(2)}</span>
            <span style={{ fontSize: 12, fontWeight: 800, color: devCol(dev5w) }}>
              {devArrow(dev5w)}{dev5w > 0 ? "+" : ""}{dev5w.toFixed(1)}%
            </span>
            {trendLabel && (
              <span style={{ fontSize: 9, fontWeight: 700, color: trendCol, background: trendCol + "20", borderRadius: 3, padding: "1px 5px" }}>
                {trendLabel}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function TabPrices({ d, history }) {
  const fut = d?.futures?.contracts || {}
  const der = d?.crack?.spreads     || {}
  const PRICE_CHARTS = [
    { title: "Brent ICE",          histKey: "brent",       color: "#3b82f6", price: fut.brent?.price_bbl },
    { title: "WTI NYMEX",          histKey: "wti",         color: "#60a5fa", price: fut.wti?.price_bbl },
    { title: "RBOB Gasoline",      histKey: "rbob",        color: "#f59e0b", price: fut.rbob?.price_bbl },
    { title: "ULSD / Heating Oil", histKey: "heating_oil", color: "#f97316", price: fut.heating_oil?.price_bbl },
    { title: "Dubai / Oman",       histKey: "dubai",       color: "#a78bfa", price: fut.dubai?.price_bbl },
  ]
  return (
    <>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
        {PRICE_CHARTS.map(({ title, histKey, color, price }) => (
          <div key={histKey} style={{ display: "flex", flexDirection: "column" }}>
            <SeriesChart title={title} data={prepChartData(history, histKey)} color={color} currentPrice={price} />
            <div style={{ background: "#0d1117", border: "1px solid #1a2535", borderTop: "none", borderRadius: "0 0 10px 10px", overflow: "hidden" }}>
              <PriceMomentumBar history={history} priceKey={histKey} currentPrice={price} color={color} />
            </div>
          </div>
        ))}
      </div>
      <Card title="Key Spreads">
        <Row label="Brent – WTI"    value={fmt(der.brent_wti?.value_bbl)}      unit="$/bbl" signal={der.brent_wti?.signal} note={der.brent_wti?.note} />
        <Row label="3-2-1 Crack"    value={fmt(der.crack_321?.value_bbl)}      unit="$/bbl" signal={der.crack_321?.signal} />
        <Row label="HO – RBOB"      value={fmt(der.ho_rbob_spread?.value_bbl)} unit="$/bbl" signal={der.ho_rbob_spread?.signal} />
        <Row label="Gasoline Crack" value={fmt(der.gasoline_crack?.value_bbl)} unit="$/bbl" signal={der.gasoline_crack?.signal} />
        <Row label="HO Crack"       value={fmt(der.ho_crack?.value_bbl)}       unit="$/bbl" signal={der.ho_crack?.signal} />
      </Card>
    </>
  )
}

function TabSpreads({ d, history }) {
  const der    = d?.crack?.spreads   || {}
  const qs     = d?.quality_spreads  || {}
  const qsHist = d?.qs_history       || []
  const qsList = qs.spreads_list     || []
  const chartable    = qsList.filter(s => s.chartable)
  const nonchartable = qsList.filter(s => !s.chartable)
  const maxAbs = nonchartable.length > 0 ? Math.max(...nonchartable.map(s => Math.abs(s.value || 0)), 1) : 30
  const catLabel = c => c === "light_heavy" ? "Light-Heavy" : c === "sweet_sour" ? "Sweet-Sour" : c === "benchmark" ? "Benchmark" : "Product"
  const catColor = c => c === "light_heavy" ? "#a78bfa" : c === "sweet_sour" ? "#f59e0b" : c === "benchmark" ? "#3b82f6" : "#22c55e"
  const spreadColors = { brent_wti: "#3b82f6", brent_urals: "#f59e0b", wti_wcs: "#a78bfa", naphtha_gasoil: "#22c55e" }
  return (
    <>
      <div style={{ fontSize: 10, fontWeight: 700, color: "#4b5563", letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 8 }}>Crack Spreads — Historical</div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 16 }}>
        <SeriesChart title="3-2-1 Crack Spread" data={prepChartData(history, "crack_321")}      color="#22c55e" currentPrice={der.crack_321?.value_bbl}     currentSignal={der.crack_321?.signal} />
        <SeriesChart title="Gasoline Crack"      data={prepChartData(history, "gasoline_crack")} color="#f59e0b" currentPrice={der.gasoline_crack?.value_bbl} currentSignal={der.gasoline_crack?.signal} />
        <SeriesChart title="HO – RBOB Spread"   data={prepChartData(history, "ho_rbob")}        color="#f97316" currentPrice={der.ho_rbob_spread?.value_bbl} currentSignal={der.ho_rbob_spread?.signal} />
      </div>
      <div style={{ fontSize: 10, fontWeight: 700, color: "#4b5563", letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 8 }}>
        Quality & Grade Spreads — Historical
        <span style={{ fontSize: 9, color: "#374151", fontWeight: 400, marginLeft: 8, textTransform: "none" }}>
          Daily history accumulating from {qsHist[0]?.date || "today"}{qsHist.length > 0 ? ` · ${qsHist.length} days` : ""}
        </span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 16 }}>
        <SeriesChart title="Brent – WTI Spread" data={prepChartData(history, "brent_wti")} color="#3b82f6" unit="$/bbl" currentPrice={der.brent_wti?.value_bbl} currentSignal={der.brent_wti?.signal} />
        <SeriesChart title="WTI – WCS (Canadian Heavy)" data={prepChartData(qsHist, "wti_wcs")} color="#a78bfa" unit="$/bbl" currentPrice={d?.quality_spreads?.spreads?.wti_wcs?.value} currentSignal={d?.quality_spreads?.spreads?.wti_wcs?.signal} />
        {chartable.filter(s => s.id !== "wti_wcs").map((s, i) => (
          <SeriesChart key={s.id} title={s.label} data={prepChartData(qsHist, s.id)} color={spreadColors[s.id] || "#6b7280"} unit="$/bbl" currentPrice={s.value} currentSignal={s.signal} />
        ))}
      </div>
      {nonchartable.length > 0 && (
        <Card title="Additional Spreads — History Building (Paid Data Needed for Charts)" style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 9, color: "#374151", fontStyle: "italic", marginBottom: 10 }}>
            Current values shown. Line charts will be added once paid differential data (Argus/Platts) is integrated.
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {nonchartable.map((s, i) => {
              const val    = s.value ?? 0
              const pct    = Math.abs(val) / maxAbs * 100
              const isPos  = val >= 0
              const barCol = s.signal === "BULLISH" ? "#22c55e" : s.signal === "BEARISH" ? "#ef4444" : "#4b5563"
              return (
                <div key={i}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 3 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <span style={{ fontSize: 11, color: "#9ca3af" }}>{s.label}</span>
                      <span style={{ fontSize: 9, fontWeight: 700, color: catColor(s.category), background: catColor(s.category) + "22", borderRadius: 3, padding: "1px 5px" }}>{catLabel(s.category)}</span>
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <Badge label={s.signal} />
                      <span style={{ fontSize: 13, fontWeight: 800, color: isPos ? "#e5e7eb" : "#ef4444", fontFamily: "monospace", minWidth: 60, textAlign: "right" }}>
                        {val >= 0 ? "+" : ""}{val.toFixed(2)}
                      </span>
                    </div>
                  </div>
                  <div style={{ position: "relative", height: 5, background: "#0a0f1a", borderRadius: 3, overflow: "hidden" }}>
                    <div style={{ position: "absolute", left: "50%", top: 0, bottom: 0, width: 1, background: "#1a2535", zIndex: 1 }} />
                    <div style={{ position: "absolute", top: 0, bottom: 0, width: pct / 2 + "%", background: barCol, borderRadius: 3, opacity: 0.8, ...(isPos ? { left: "50%" } : { right: "50%" }) }} />
                  </div>
                  <div style={{ fontSize: 9, color: "#374151", marginTop: 2 }}>{s.note?.slice(0, 100)}</div>
                </div>
              )
            })}
          </div>
        </Card>
      )}
      <Card title="Signal Reference">
        {[
          ["Brent-WTI > $8","US export bottleneck or North Sea disruption"],
          ["Brent-WTI < $2","US exports flooding Atlantic basin"],
          ["Brent-Urals > $12","Russia sanctions fully effective — wide discount"],
          ["Brent-Urals < $3","Russian discount compressed — sanctions leaking"],
          ["WTI-WCS > $20","Alberta pipeline constraints severe"],
          ["WTI-WCS < $10","Trans Mountain relieving congestion"],
          ["Naphtha-ULSD < -$15","Diesel tight, naphtha/petrochem demand weak"],
          ["Naphtha-ULSD > $0","Naphtha premium — petrochemical demand strong"],
          ["3-2-1 Crack > $20","Product demand tight — crude demand bullish"],
          ["3-2-1 Crack < $10","Margins compressed — refinery runs may fall"],
          ["ULSD Crack > $25","US diesel/heating oil tightness (EIA ULSD proxy)"],
          ["Brent-Maya > $20","Complex refinery upgrading premium elevated"],
        ].map(([k,v],i) => (
          <div key={i} style={{ display:"flex", gap:8, padding:"5px 0", borderBottom:"1px solid #0f1e30", fontSize:11 }}>
            <span style={{ color:"#f59e0b", fontWeight:700, minWidth:190 }}>{k}</span>
            <span style={{ color:"#6b7280" }}>{v}</span>
          </div>
        ))}
      </Card>
    </>
  )
}

function TabInventory({ d }) {
  const eia     = d?.eia                    || {}
  const invSigs = d?.inv_signals?.signals   || {}
  const invComp = d?.inv_signals?.composite || {}
  return (
    <>
      {invComp.score != null && (
        <Card title="Inventory Signal Layer" style={{ marginBottom: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 8 }}>
            <span style={{ fontSize: 32, fontWeight: 900, lineHeight: 1,
              color: invComp.score > 0 ? "#22c55e" : invComp.score < 0 ? "#ef4444" : "#f59e0b" }}>
              {invComp.score > 0 ? "+" : ""}{invComp.score.toFixed(2)}
            </span>
            <div>
              <Badge label={invComp.overall_signal} />
              <div style={{ fontSize: 11, color: "#6b7280", marginTop: 4 }}>{invComp.interpretation}</div>
            </div>
          </div>
          {invComp.components?.map((c, i) => (
            <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center",
              fontSize: 11, padding: "4px 0", borderBottom: "1px solid #0f1e30" }}>
              <span style={{ color: "#9ca3af" }}>{c.label}</span>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <Badge label={c.signal} />
                <span style={{ color: c.score > 0 ? "#22c55e" : c.score < 0 ? "#ef4444" : "#374151",
                  fontWeight: 700, fontFamily: "monospace", minWidth: 24, textAlign: "right" }}>
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
        <Row label="Crude Imports"         value={fmt(eia.crude_imports?.value,2)}     unit="mbd" note={`WoW ${fmt(eia.crude_imports?.wow,2)}`} />
        <Row label="Crude Exports"         value={fmt(eia.crude_exports?.value,2)}     unit="mbd" note={`WoW ${fmt(eia.crude_exports?.wow,2)}`} />
        <Row label="Gasoline Demand"       value={fmt(eia.gasoline_demand?.value,2)}   unit="mbd" note={`WoW ${fmt(eia.gasoline_demand?.wow,2)}`} />
        <Row label="Distillate Demand"     value={fmt(eia.distillate_demand?.value,2)} unit="mbd" note={`WoW ${fmt(eia.distillate_demand?.wow,2)}`} />
      </Card>
      <Card title="Rig Count — Baker Hughes vs EIA DPR" style={{ marginTop: 12 }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
          <div style={{ background: "#0a0f1a", border: "1px solid #1a2535", borderRadius: 8, padding: "12px" }}>
            <div style={{ fontSize: 9, fontWeight: 700, color: "#4b5563", textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 8 }}>Baker Hughes — Weekly (Oil-Directed)</div>
            <div style={{ fontSize: 32, fontWeight: 900, color: "#3b82f6", lineHeight: 1 }}>
              {fmt(d?.rig_count?.latest?.oil_rigs, 0)}<span style={{ fontSize: 11, color: "#374151", marginLeft: 6 }}>oil rigs</span>
            </div>
            <div style={{ fontSize: 11, marginTop: 4, color: (d?.rig_count?.latest?.wow_oil||0) > 0 ? "#ef4444" : "#22c55e" }}>
              {(d?.rig_count?.latest?.wow_oil||0) > 0 ? "▲" : "▼"} {fmt(Math.abs(d?.rig_count?.latest?.wow_oil||0), 0)} WoW
            </div>
            <div style={{ fontSize: 10, color: "#374151", marginTop: 4 }}>{d?.rig_count?.signal?.five_week_trend}</div>
            <div style={{ marginTop: 6 }}><Badge label={d?.rig_count?.signal?.label} /></div>
          </div>
          <div style={{ background: "#0a0f1a", border: "1px solid #1a2535", borderRadius: 8, padding: "12px" }}>
            <div style={{ fontSize: 9, fontWeight: 700, color: "#4b5563", textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 8 }}>EIA DPR — Monthly (7 Shale Regions)</div>
            <div style={{ fontSize: 32, fontWeight: 900, color: "#a78bfa", lineHeight: 1 }}>
              {fmt(d?.duc?.rigs?.total_rigs, 0)}<span style={{ fontSize: 11, color: "#374151", marginLeft: 6 }}>total rigs</span>
            </div>
            <div style={{ fontSize: 10, color: "#374151", marginTop: 4 }}>
              Permian: <span style={{ color: "#e5e7eb", fontWeight: 700 }}>{fmt(d?.duc?.rigs?.by_region?.Permian?.rigs, 0)}</span> rigs
            </div>
          </div>
        </div>
        {d?.duc?.rigs?.by_region && Object.keys(d.duc.rigs.by_region).length > 0 && (
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 9, color: "#4b5563", textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 6 }}>Rigs by Region (EIA DPR)</div>
            {Object.entries(d.duc.rigs.by_region).sort((a,b) => (b[1].rigs||0) - (a[1].rigs||0)).map(([region, data], i) => {
              const pct    = (data.rigs||0) / (d.duc.rigs.total_rigs||1) * 100
              const momCol = (data.mom||0) > 0 ? "#ef4444" : (data.mom||0) < 0 ? "#22c55e" : "#374151"
              return (
                <div key={i} style={{ marginBottom: 5 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, marginBottom: 2 }}>
                    <span style={{ color: "#9ca3af" }}>{region}</span>
                    <div style={{ display: "flex", gap: 12 }}>
                      <span style={{ color: momCol, fontSize: 10 }}>{(data.mom||0) > 0 ? "▲" : (data.mom||0) < 0 ? "▼" : "—"}{Math.abs(data.mom||0)} MoM</span>
                      <span style={{ color: "#e5e7eb", fontWeight: 700, minWidth: 35, textAlign: "right" }}>{fmt(data.rigs, 0)}</span>
                    </div>
                  </div>
                  <div style={{ height: 3, background: "#0a0f1a", borderRadius: 2 }}>
                    <div style={{ width: pct + "%", height: "100%", background: "#a78bfa", borderRadius: 2, opacity: 0.7 }} />
                  </div>
                </div>
              )
            })}
          </div>
        )}
        <div style={{ borderTop: "1px solid #0f1e30", paddingTop: 10 }}>
          <div style={{ fontSize: 9, color: "#4b5563", textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 6 }}>EIA DUC Inventory (Drilled but Uncompleted)</div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 8 }}>
            <span style={{ fontSize: 28, fontWeight: 900, color: "#f59e0b" }}>{fmt(d?.duc?.duc?.total?.duc_latest, 0)}</span>
            <span style={{ fontSize: 11, color: "#374151" }}>wells</span>
            <span style={{ fontSize: 12, fontWeight: 700, color: (d?.duc?.duc?.total?.duc_change||0) > 0 ? "#ef4444" : "#22c55e" }}>
              {(d?.duc?.duc?.total?.duc_change||0) > 0 ? "+" : ""}{fmt(d?.duc?.duc?.total?.duc_change, 0)} MoM
            </span>
            <Badge label={d?.duc?.signal?.overall_signal} />
          </div>
        </div>
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
        <Row label="Macro Signal"     value="" signal={der.macro_composite?.composite_signal} />
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
          : <div style={{ color:"#374151", fontSize:12, padding:"8px 0" }}>Weather data not loaded</div>}
      </Card>
    </>
  )
}

function TabSentiment({ d }) {
  const news      = d?.news              || {}
  const cftc      = d?.cftc             || {}
  const fj        = d?.fj               || {}
  const headlines = news.all_headlines   || []
  const score     = news.news_score?.score ?? null
  const scoreCol  = score > 0 ? "#22c55e" : score < 0 ? "#ef4444" : "#f59e0b"
  const summary   = news.summary         || {}
  const fjHeadlines = fj.headlines     || []
  const fjOilOnly   = fj.oil_headlines || []
  const [fjFilter, setFjFilter] = React.useState("oil")
  const fjShown = fjFilter === "oil" ? fjOilOnly : fjHeadlines
  const sentCol = s => s === "BULLISH" ? "#22c55e" : s === "BEARISH" ? "#ef4444" : "#374151"
  return (
    <>
      {news.primary_releases?.length > 0 && (
        <Card title="★ Primary Source Releases (EIA / OPEC / IEA)" style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 9, color: "#374151", marginBottom: 8 }}>Official releases — credibility weight 1.0 · slow decay</div>
          {news.primary_releases.map((r, i) => (
            <div key={i} style={{ display: "flex", justifyContent: "space-between", gap: 8,
              fontSize: 11, padding: "6px 0", borderBottom: "1px solid #0f1e30", alignItems: "flex-start" }}>
              <div style={{ flex: 1 }}>
                <span style={{ fontSize: 9, fontWeight: 700, color: "#4b5563", background: "#1a2535", borderRadius: 3, padding: "1px 5px", marginRight: 6 }}>{r.source}</span>
                <span style={{ color: "#9ca3af" }}>{r.headline}</span>
              </div>
              <span style={{ color: r.final_score > 0 ? "#22c55e" : r.final_score < 0 ? "#ef4444" : "#6b7280", fontWeight: 700, whiteSpace: "nowrap", fontSize: 12 }}>
                {r.final_score > 0 ? "+" : ""}{Number(r.final_score).toFixed(1)}
              </span>
            </div>
          ))}
        </Card>
      )}
      <Card title="FinancialJuice — Live Headlines" style={{ marginBottom: 12 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
          <div style={{ fontSize: 11, color: "#4b5563" }}>
            {fj.total ? `${fj.total} headlines · ${fj.oil_count} oil-relevant` : "Loading..."}
            {fj.fetched_at && <span style={{ marginLeft: 8, color: "#1f2937" }}>· {new Date(fj.fetched_at).toLocaleTimeString()}</span>}
          </div>
          <div style={{ display: "flex", gap: 4 }}>
            {["oil", "all"].map(f => (
              <button key={f} onClick={() => setFjFilter(f)} style={{
                background: fjFilter === f ? "#00d98b22" : "transparent",
                border: `1px solid ${fjFilter === f ? "#00d98b55" : "#1a2535"}`,
                borderRadius: 6, padding: "3px 10px",
                color: fjFilter === f ? "#00d98b" : "#374151",
                fontSize: 10, fontWeight: 700, cursor: "pointer",
                textTransform: "uppercase", letterSpacing: "0.08em" }}>
                {f === "oil" ? "⚡ Oil/Energy" : "All News"}
              </button>
            ))}
          </div>
        </div>
        <div style={{ maxHeight: 380, overflowY: "auto" }}>
          {fjShown.length === 0 ? (
            <div style={{ color: "#374151", fontSize: 12, padding: "12px 0", textAlign: "center" }}>
              {fj.error ? fj.error : fjFilter === "oil" ? "No oil-relevant headlines yet" : "No headlines loaded"}
            </div>
          ) : fjShown.map((h, i) => (
            <a key={h.guid || i} href={h.link} target="_blank" rel="noopener noreferrer"
              style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between",
                gap: 10, padding: "7px 4px", borderBottom: "1px solid #0f1e30",
                textDecoration: "none", cursor: "pointer", borderRadius: 4 }}
              onMouseEnter={e => e.currentTarget.style.background = "#0a1628"}
              onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
              <span style={{ width: 6, height: 6, borderRadius: "50%", flexShrink: 0, marginTop: 5, background: sentCol(h.sentiment) }} />
              <span style={{ flex: 1, fontSize: 11, color: "#9ca3af", lineHeight: 1.4 }}>{h.title}</span>
              <span style={{ fontSize: 9, color: "#1f2937", whiteSpace: "nowrap", flexShrink: 0, fontFamily: "monospace", marginTop: 2 }}>{h.time_ago}</span>
            </a>
          ))}
        </div>
        <div style={{ display: "flex", gap: 16, marginTop: 8, fontSize: 9, color: "#374151" }}>
          <span><span style={{ color: "#22c55e" }}>●</span> Bullish</span>
          <span><span style={{ color: "#ef4444" }}>●</span> Bearish</span>
          <span><span style={{ color: "#374151" }}>●</span> Neutral</span>
          <span style={{ marginLeft: "auto" }}>Click any headline to open article →</span>
        </div>
      </Card>
      <Card title="RSS News Sentiment" style={{ marginBottom: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 20, marginBottom: 12 }}>
          <div>
            <div style={{ fontSize: 36, fontWeight: 900, color: scoreCol, lineHeight: 1 }}>
              {score != null ? (score > 0 ? "+" : "") + Number(score).toFixed(1) : "—"}
            </div>
            <div style={{ fontSize: 10, color: "#4b5563" }}>{news.news_score?.label || "Composite"}</div>
          </div>
          <div style={{ flex: 1 }}>
            <Row label="Bullish signals" value={summary.bullish_count ?? "—"} />
            <Row label="Bearish signals" value={summary.bearish_count ?? "—"} />
            <Row label="Neutral"         value={summary.neutral_count ?? "—"} />
            <Row label="Geo alerts"      value={summary.geo_alerts    ?? "—"} />
          </div>
        </div>
        {headlines.slice(0, 5).map((h, i) => (
          <div key={i} style={{ display: "flex", justifyContent: "space-between", gap: 8,
            fontSize: 11, color: "#9ca3af", padding: "5px 0", borderBottom: "1px solid #0f1e30" }}>
            <span style={{ flex: 1 }}>{h.title || h.headline}</span>
            <span style={{ color: h.final_score > 0 ? "#22c55e" : h.final_score < 0 ? "#ef4444" : "#6b7280", fontWeight: 700, whiteSpace: "nowrap" }}>
              {h.final_score != null ? (h.final_score > 0 ? "+" : "") + Number(h.final_score).toFixed(1) : "—"}
            </span>
          </div>
        ))}
      </Card>
      <Card title="CFTC Positioning — Speculative">
        <div style={{ fontSize: 10, color: "#4b5563", marginBottom: 10 }}>
          Managed Money net positioning as % of open interest · Published Friday 3:30 PM ET
        </div>
        {cftc.contracts
          ? Object.entries(cftc.contracts).slice(0, 5).map(([k, v]) => (
            <Row key={k} label={v?.label || k} value={fmt(v?.net_pct_of_oi, 1)} unit="% net long" signal={v?.signal}
              note={v?.mm_net_lots != null ? `${v.mm_net_lots > 0 ? "+" : ""}${v.mm_net_lots.toLocaleString()} lots` : undefined} />
          ))
          : <div style={{ color: "#374151", fontSize: 12, padding: "8px 0" }}>CFTC data not loaded</div>}
      </Card>
    </>
  )
}

function TabCurve({ d, curveHistory, curveSel, setCurveSel, curveRange, setCurveRange, regimeHistory }) {
  const curve   = d?.curve  || {}
  const curves  = curve.curves  || {}
  const signals = curve.signals || {}
  const demsup  = d?.demsup?.regimes || {}
  const geoScore = d?.geo?.composite_signal_score ?? null
  const carry   = d?.fred?.derived?.storage_carry?.total_carry_per_bbl_mo || 0.77
  const ch      = curveHistory || []
  const PRODUCTS = [
    { key: "brent", label: "Brent ICE",     color: "#3b82f6" },
    { key: "wti",   label: "WTI NYMEX",     color: "#60a5fa" },
    { key: "rbob",  label: "RBOB Gasoline", color: "#f59e0b" },
    { key: "ho",    label: "ULSD / HO",     color: "#f97316" },
  ]
  const SPREAD_OPTIONS = [
    { label: "M1-M2",  key: "m1_m2",  type: "spread", m1: 0, m2: 1  },
    { label: "M1-M3",  key: "m1_m3",  type: "spread", m1: 0, m2: 2  },
    { label: "M1-M6",  key: "m1_m6",  type: "spread", m1: 0, m2: 5  },
    { label: "M1-M12", key: "m1_m12", type: "spread", m1: 0, m2: 11 },
    { label: "M1 Fly", key: "m1_fly", type: "fly",    m: [0,1,2]    },
    { label: "M3 Fly", key: "m3_fly", type: "fly",    m: [2,3,4]    },
    { label: "M5 Fly", key: "m5_fly", type: "fly",    m: [4,5,6]    },
  ]
  const RANGES = [
    { label: "1M",  days: 21   },
    { label: "3M",  days: 63   },
    { label: "6M",  days: 125  },
    { label: "All", days: 9999 },
  ]
  const getHistKey    = (product, label) => { const opt = SPREAD_OPTIONS.find(o => o.label === label); return opt ? `${product}_${opt.key}` : null }
  const getCurrentVal = (product, label) => {
    const c = curves[product]; const opt = SPREAD_OPTIONS.find(o => o.label === label)
    if (!c || !opt) return null
    if (opt.type === "spread") return c[opt.m1] && c[opt.m2] ? Math.round((c[opt.m1].price - c[opt.m2].price)*100)/100 : null
    const [a,b,cc] = opt.m; return c[a] && c[b] && c[cc] ? Math.round((c[a].price - 2*c[b].price + c[cc].price)*1000)/1000 : null
  }
  const spreadCol    = v => { if (v == null) return "#374151"; if (v > 1.0) return "#22c55e"; if (v > 0.2) return "#86efac"; if (v > -0.2) return "#6b7280"; if (v > -1.5) return "#fca5a5"; return "#ef4444" }
  const structureCol = s => { if (!s) return "#6b7280"; if (s.includes("STRONG_BACK")) return "#22c55e"; if (s.includes("MILD_BACK")) return "#86efac"; if (s === "FLAT") return "#6b7280"; if (s.includes("MILD_CONT")) return "#fca5a5"; return "#ef4444" }
  const demsupCol = label => {
    if (!label) return "#374151"
    if (label.includes("Deep-Backwardation")) return "#22c55e"
    if (label.includes("Backwardation") || label === "Transition-Tightening") return "#86efac"
    if (label === "Flat" || label.includes("Stable")) return "#6b7280"
    if (label.includes("Contango") || label === "Transition-Loosening") return "#fca5a5"
    if (label.includes("Deep-Contango")) return "#ef4444"
    return "#6b7280"
  }
  const scopeCol = scope => scope === "GLOBAL" ? "#f59e0b" : scope === "BROAD" ? "#a78bfa" : "#374151"

  const ProductChart = ({ product, color, label }) => {
    const selLabel   = curveSel[product]
    const rangeLabel = curveRange[product]
    const histKey    = getHistKey(product, selLabel)
    const days       = RANGES.find(r => r.label === rangeLabel)?.days || 63
    const curVal     = getCurrentVal(product, selLabel)
    const curCol     = spreadCol(curVal)
    const sig        = signals[product]
    const strCol     = structureCol(sig?.structure)
    const dsup       = demsup[product]
    const dsupOk     = dsup?.status === "OK"
    const dsupCol    = demsupCol(dsup?.regime_label)
    // Cross-check: GLOBAL/BROAD backwardation consensus from demsup vs this dashboard's
    // independent geo-risk score. Agreement = corroborating signal; a GLOBAL regime with
    // a low geo score suggests a price-only/technical move rather than a news-driven one.
    const crossCheck = (() => {
      if (!dsupOk || !dsup.regime_label) return null
      const isGlobalBack = (dsup.consensus_scope === "GLOBAL" || dsup.consensus_scope === "BROAD")
                            && dsup.regime_label.includes("Backwardation")
      if (!isGlobalBack) return null
      if (geoScore == null) return null
      return geoScore >= 3
        ? { label: "CONFIRMED", note: "Geo risk score corroborates the regime", color: "#22c55e" }
        : { label: "PRICE-ONLY", note: "No matching geopolitical driver — may be positioning/technical", color: "#f59e0b" }
    })()
    const allPts     = ch.filter(r => histKey && r[histKey] != null)
    const pts        = allPts.slice(-days)
    const chartData  = pts.map(r => ({ date: r.date?.slice(5), value: r[histKey] }))
    const vals       = chartData.map(r => r.value).filter(v => v != null)
    const minVal     = vals.length ? Math.min(...vals) : -1
    const maxVal     = vals.length ? Math.max(...vals) :  1
    const hasZero    = minVal < 0 && maxVal > 0
    const CustomTooltip = ({ active, payload, label: lbl }) => {
      if (!active || !payload?.length) return null
      const v = payload[0]?.value
      return (
        <div style={{ background:"#0d1117", border:"1px solid #1a2535", borderRadius:6, padding:"6px 10px", fontSize:11 }}>
          <div style={{ color:"#6b7280", marginBottom:3 }}>{lbl}</div>
          <div style={{ color, fontWeight:700 }}>{selLabel}: {v >= 0 ? "+" : ""}{typeof v === "number" ? v.toFixed(3) : "—"}</div>
        </div>
      )
    }
    return (
      <Card style={{ marginBottom: 0 }}>
        <div style={{ display:"flex", justifyContent:"space-between", alignItems:"flex-start", marginBottom:10 }}>
          <div>
            <div style={{ display:"flex", alignItems:"center", gap:8, marginBottom:4 }}>
              <div style={{ width:8, height:8, borderRadius:"50%", background:color }}/>
              <span style={{ fontSize:12, fontWeight:700, color:"#e5e7eb" }}>{label}</span>
              <span style={{ fontSize:10, fontWeight:700, color:strCol, background:strCol+"22", borderRadius:4, padding:"1px 6px" }}>
                {sig?.structure?.replace(/_/g," ") || "—"}
              </span>
              {dsupOk && (
                <span title={`demsup confidence ${(dsup.confidence_score*100||0).toFixed(0)}% · scope ${dsup.consensus_scope||"—"}`}
                      style={{ fontSize:10, fontWeight:700, color:dsupCol, background:dsupCol+"22", borderRadius:4, padding:"1px 6px" }}>
                  {dsup.regime_label}
                </span>
              )}
              {dsupOk && dsup.consensus_scope && (
                <span style={{ fontSize:9, fontWeight:700, color:scopeCol(dsup.consensus_scope), background:scopeCol(dsup.consensus_scope)+"1a", borderRadius:4, padding:"1px 5px" }}>
                  {dsup.consensus_scope}
                </span>
              )}
              {crossCheck && (
                <span title={crossCheck.note}
                      style={{ fontSize:9, fontWeight:700, color:crossCheck.color, background:crossCheck.color+"1a", borderRadius:4, padding:"1px 5px" }}>
                  {crossCheck.label}
                </span>
              )}
            </div>
            <div style={{ display:"flex", gap:4, flexWrap:"wrap" }}>
              {SPREAD_OPTIONS.map(o => (
                <button key={o.label} onClick={() => setCurveSel(prev => ({...prev, [product]: o.label}))} style={{
                  background: curveSel[product]===o.label ? color+"33" : "transparent",
                  border: `1px solid ${curveSel[product]===o.label ? color : "#1a2535"}`,
                  borderRadius:4, padding:"2px 7px", fontSize:9, fontWeight:700,
                  color: curveSel[product]===o.label ? color : "#4b5563", cursor:"pointer", letterSpacing:"0.05em" }}>
                  {o.label}
                </button>
              ))}
            </div>
          </div>
          <div style={{ textAlign:"right" }}>
            <div style={{ fontSize:22, fontWeight:900, color:curCol, fontFamily:"monospace", lineHeight:1 }}>
              {curVal != null ? (curVal >= 0 ? "+" : "") + curVal.toFixed(3) : "—"}
            </div>
            <div style={{ fontSize:9, color:"#374151", marginBottom:4 }}>$/bbl today</div>
            <div style={{ display:"flex", gap:3, justifyContent:"flex-end" }}>
              {RANGES.map(r => (
                <button key={r.label} onClick={() => setCurveRange(prev => ({...prev, [product]: r.label}))} style={{
                  background: curveRange[product]===r.label ? "#1a2535" : "transparent",
                  border: `1px solid ${curveRange[product]===r.label ? "#374151" : "#0f1e30"}`,
                  borderRadius:4, padding:"2px 6px", fontSize:9, fontWeight:700,
                  color: curveRange[product]===r.label ? "#e5e7eb" : "#374151", cursor:"pointer" }}>
                  {r.label}
                </button>
              ))}
            </div>
          </div>
        </div>
        {chartData.length < 2 ? (
          <div style={{ height:160, display:"flex", alignItems:"center", justifyContent:"center", color:"#1f2937", fontSize:10, fontFamily:"monospace" }}>
            BUILDING HISTORY — RUN curve_backfill.py
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={160}>
            <ComposedChart data={chartData} margin={{ top:4, right:4, left:-20, bottom:0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#0f1e30" />
              <XAxis dataKey="date" tick={{ fontSize:8, fill:"#374151" }} tickLine={false} interval={Math.floor(chartData.length / 5)} />
              <YAxis tick={{ fontSize:8, fill:"#374151" }} tickLine={false} domain={["auto","auto"]} width={48} tickFormatter={v => (v >= 0 ? "+" : "") + v.toFixed(2)} />
              <Tooltip content={<CustomTooltip />} />
              {hasZero && <ReferenceLine y={0} stroke="#374151" strokeDasharray="4 4" />}
              <Line dataKey="value" stroke={color} strokeWidth={2} dot={false} activeDot={{ r:3, fill:color }} name={selLabel} />
            </ComposedChart>
          </ResponsiveContainer>
        )}
        {vals.length > 1 && (() => {
          const mean = vals.reduce((a,b) => a+b, 0) / vals.length
          const sorted = [...vals].sort((a,b) => a-b)
          const p10 = sorted[Math.floor(sorted.length*0.1)]
          const p90 = sorted[Math.floor(sorted.length*0.9)]
          return (
            <div style={{ display:"flex", gap:12, marginTop:6, fontSize:9, color:"#374151" }}>
              <span>Avg: <span style={{ color }}>{mean >= 0 ? "+" : ""}{mean.toFixed(3)}</span></span>
              <span>Min: <span style={{ color:"#ef4444" }}>{sorted[0].toFixed(3)}</span></span>
              <span>Max: <span style={{ color:"#22c55e" }}>{sorted[sorted.length-1].toFixed(3)}</span></span>
              <span>P10: <span style={{ color:"#6b7280" }}>{p10?.toFixed(3)}</span></span>
              <span>P90: <span style={{ color:"#6b7280" }}>{p90?.toFixed(3)}</span></span>
              <span style={{ marginLeft:"auto" }}>{chartData.length}d</span>
            </div>
          )
        })()}
      </Card>
    )
  }
  return (
    <>
      <div style={{ fontSize:9, color:"#374151", marginBottom:12, fontStyle:"italic" }}>
        M1 live (Stooq / Yahoo query2) · M2–M12 synthetic shape · Carry ${carry.toFixed(2)}/bbl/mo
      </div>
      <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:12 }}>
        {PRODUCTS.map(p => <ProductChart key={p.key} product={p.key} color={p.color} label={p.label} />)}
      </div>
      <RegimeHistoryPanel regimeHistory={regimeHistory} demsupCol={demsupCol} />
      <Card title="Signal Reference" style={{ marginTop:12 }}>
        {[
          ["Spread > +1.0","Strong backwardation — physical urgency, prompt scarce"],
          ["Spread +0.2 to +1.0","Mild backwardation — market slightly undersupplied"],
          ["Spread ±0.2","Flat — balanced supply/demand"],
          ["Spread -0.2 to -1.5","Mild contango — storage becoming economic"],
          ["Spread < -1.5","Deep contango — oversupply, storage fills"],
          ["Fly > 0","Hump — near-term tighter than deferred, fading"],
          ["Fly < 0","Trough — deferred months pricing tighter than prompt"],
        ].map(([k,v],i) => (
          <div key={i} style={{ display:"flex", gap:8, padding:"5px 0", borderBottom:"1px solid #0f1e30", fontSize:11 }}>
            <span style={{ color:"#f59e0b", fontWeight:700, minWidth:200 }}>{k}</span>
            <span style={{ color:"#6b7280" }}>{v}</span>
          </div>
        ))}
      </Card>
    </>
  )
}

// Historical regime classification panel — full training-data history per
// product, sourced from demsup's regime classifier (the SAME backend that
// drives the live regime badges above). Shows a colored timeline strip of
// regime periods, plus a level_z_126 line chart, so today's regime can be
// seen in the context of how long regimes typically last and how the
// z-score has behaved historically rather than as an isolated label.
function RegimeHistoryPanel({ regimeHistory, demsupCol }) {
  const REGIME_PRODUCTS = [
    { key: "brent", label: "Brent ICE",    color: "#3b82f6" },
    { key: "wti",   label: "WTI NYMEX",    color: "#60a5fa" },
    { key: "ho",    label: "ULSD / HO",    color: "#f97316" },
    { key: "lgo",   label: "Gasoil (LGO)", color: "#a78bfa" },
  ]
  const [selProduct, setSelProduct] = useState("wti")

  if (!regimeHistory) {
    return (
      <Card title="Regime Classification History" style={{ marginTop:12 }}>
        <div style={{ fontSize:10, color:"#374151", fontFamily:"monospace" }}>Loading historical regime data…</div>
      </Card>
    )
  }

  const entry    = regimeHistory.products?.[selProduct]
  const ok       = entry?.status === "OK"
  const history  = entry?.history  || []
  const segments = entry?.segments || []
  const totalDays = segments.reduce((s,seg) => s + seg.n_days, 0) || 1

  const chartData = history.map(r => ({ date: r.date, z: r.level_z_126 }))

  return (
    <Card title="Regime Classification History" style={{ marginTop:12 }}>
      <div style={{ display:"flex", gap:6, marginBottom:12 }}>
        {REGIME_PRODUCTS.map(p => (
          <button key={p.key} onClick={() => setSelProduct(p.key)} style={{
            background: selProduct===p.key ? p.color+"33" : "transparent",
            border: `1px solid ${selProduct===p.key ? p.color : "#1a2535"}`,
            borderRadius:5, padding:"4px 10px", fontSize:10, fontWeight:700,
            color: selProduct===p.key ? p.color : "#4b5563", cursor:"pointer" }}>
            {p.label}
          </button>
        ))}
      </div>

      {!ok ? (
        <div style={{ fontSize:10, color:"#374151", fontFamily:"monospace" }}>
          {entry?.note || "No regime history available for this product"}
        </div>
      ) : (
        <>
          {/* Colored timeline strip — each block is one contiguous regime period,
              width proportional to how many days that regime lasted. Hovering
              a block shows the exact dates and duration. */}
          <div style={{ marginBottom: 6, fontSize:9, color:"#374151", letterSpacing:"0.06em" }}>
            REGIME TIMELINE · {segments.length} periods over {totalDays} trading days
          </div>
          <div style={{ display:"flex", width:"100%", height:28, borderRadius:5, overflow:"hidden", marginBottom:14 }}>
            {segments.map((seg, i) => {
              const widthPct = (seg.n_days / totalDays) * 100
              const col = demsupCol(seg.regime_label)
              return (
                <div key={i}
                     title={`${seg.regime_label}\n${seg.start_date} → ${seg.end_date} (${seg.n_days}d)`}
                     style={{
                       width: `${widthPct}%`, minWidth: widthPct > 0.3 ? undefined : 1,
                       background: col, opacity: 0.85,
                       borderRight: i < segments.length-1 ? "1px solid #050b14" : "none",
                       cursor: "pointer",
                     }} />
              )
            })}
          </div>

          {/* z-score line chart over the same history, colored by sign so
              extreme backwardation/contango excursions are visually obvious
              against the regime timeline directly above it. */}
          <ResponsiveContainer width="100%" height={180}>
            <ComposedChart data={chartData} margin={{ top:4, right:4, left:-20, bottom:0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#0f1e30" />
              <XAxis dataKey="date" tick={{ fontSize:8, fill:"#374151" }} tickLine={false}
                     interval={Math.floor(chartData.length / 8)} />
              <YAxis tick={{ fontSize:8, fill:"#374151" }} tickLine={false} domain={["auto","auto"]} width={48} />
              <Tooltip content={({active,payload,label}) => {
                if (!active || !payload?.length) return null
                const v = payload[0]?.value
                return (
                  <div style={{ background:"#0d1117", border:"1px solid #1a2535", borderRadius:6, padding:"6px 10px", fontSize:11 }}>
                    <div style={{ color:"#6b7280", marginBottom:3 }}>{label}</div>
                    <div style={{ color:"#e5e7eb", fontWeight:700 }}>z = {v >= 0 ? "+" : ""}{v?.toFixed(3)}</div>
                  </div>
                )
              }} />
              <ReferenceLine y={0} stroke="#374151" strokeDasharray="4 4" />
              <ReferenceLine y={1} stroke="#374151" strokeDasharray="2 2" opacity={0.4} />
              <ReferenceLine y={-1} stroke="#374151" strokeDasharray="2 2" opacity={0.4} />
              <Line dataKey="z" stroke="#f59e0b" strokeWidth={1.5} dot={false} activeDot={{ r:3, fill:"#f59e0b" }} name="level_z_126" />
            </ComposedChart>
          </ResponsiveContainer>
          <div style={{ fontSize:9, color:"#1f2937", marginTop:4 }}>
            level_z_126 — standard deviations from the lagged 126-day M1M2 baseline. Dashed lines at ±1.
          </div>
        </>
      )}
    </Card>
  )
}

function TabSignal({ d }) {
  // signal_engine_fetcher.py output: { signals: { wti, brent, ho, lgo }, note, fetched_at }
  // Each product: { status: "OK"|"INSUFFICIENT_DATA", live: {...} | null, summary: {...} | null }
  const se = d?.signal_engine || {}
  const signals = se.signals || {}

  const PRODUCTS = [
    { key: "brent", label: "Brent ICE",     color: "#3b82f6" },
    { key: "wti",   label: "WTI NYMEX",     color: "#60a5fa" },
    { key: "ho",    label: "ULSD / HO",     color: "#f97316" },
    { key: "lgo",   label: "Gasoil (LGO)",  color: "#a78bfa" },
  ]

  const sigCol = sig => sig === "BUY" ? "#22c55e" : sig === "SELL" ? "#ef4444" : "#6b7280"
  const sigBg  = sig => sigCol(sig) + "1a"

  const SignalCard = ({ product, color, label }) => {
    const entry = signals[product]
    const ok    = entry?.status === "OK"
    const live  = entry?.live
    const summary = entry?.summary

    // "Why" line — mirrors the exact gating cascade in signal_engine.R's
    // run_signal_engine(): warmup -> regime exclusion -> ATR vol gate ->
    // threshold crossing. This text is descriptive only; the actual gating
    // decision was already made server-side by the validated R function —
    // this just explains it, it doesn't recompute it.
    const whyText = (() => {
      if (!ok || !live) return null
      if (live.signal === "FLAT") {
        if (!live.vol_gate_pass) return `Volatility gate blocked (${live.vol_gate})`
        return `|z|=${Math.abs(live.level_z).toFixed(2)} below threshold ${live.threshold?.toFixed(2)}`
      }
      return `z=${live.level_z >= 0 ? "+" : ""}${live.level_z?.toFixed(2)} crossed threshold ${live.threshold?.toFixed(2)} · regime: ${live.regime}`
    })()

    return (
      <Card style={{ marginBottom: 0 }}>
        <div style={{ display:"flex", justifyContent:"space-between", alignItems:"flex-start", marginBottom:10 }}>
          <div style={{ display:"flex", alignItems:"center", gap:8 }}>
            <div style={{ width:8, height:8, borderRadius:"50%", background:color }}/>
            <span style={{ fontSize:12, fontWeight:700, color:"#e5e7eb" }}>{label}</span>
          </div>
          {ok && live ? (
            <span style={{ fontSize:13, fontWeight:900, color:sigCol(live.signal), background:sigBg(live.signal), borderRadius:6, padding:"3px 12px", letterSpacing:"0.05em" }}>
              {live.signal}
            </span>
          ) : (
            <span style={{ fontSize:10, fontWeight:700, color:"#374151", background:"#1a253522", borderRadius:6, padding:"3px 10px" }}>
              INSUFFICIENT DATA
            </span>
          )}
        </div>

        {!ok && (
          <div style={{ fontSize:10, color:"#374151", fontFamily:"monospace" }}>
            {entry?.note || "Signal service unavailable"}
          </div>
        )}

        {ok && live && (
          <>
            <div style={{ fontSize:10, color:"#6b7280", marginBottom:10 }}>{whyText}</div>
            <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr 1fr", gap:8, marginBottom:10 }}>
              <div>
                <div style={{ fontSize:9, color:"#374151" }}>M1M2</div>
                <div style={{ fontSize:14, fontWeight:700, color:"#e5e7eb", fontFamily:"monospace" }}>
                  {live.m1m2 >= 0 ? "+" : ""}{live.m1m2?.toFixed(3)} <span style={{ fontSize:9, color:"#374151" }}>{live.unit}</span>
                </div>
              </div>
              <div>
                <div style={{ fontSize:9, color:"#374151" }}>Z-SCORE</div>
                <div style={{ fontSize:14, fontWeight:700, color:Math.abs(live.level_z) >= live.threshold ? sigCol(live.signal==="FLAT" ? "" : live.signal) : "#e5e7eb", fontFamily:"monospace" }}>
                  {live.level_z >= 0 ? "+" : ""}{live.level_z?.toFixed(3)}
                </div>
              </div>
              <div>
                <div style={{ fontSize:9, color:"#374151" }}>VOL GATE</div>
                <div style={{ fontSize:12, fontWeight:700, color: live.vol_gate_pass ? "#22c55e" : "#ef4444" }}>
                  {live.vol_gate_pass ? "PASS" : "BLOCKED"}
                </div>
              </div>
            </div>
            {live.signal !== "FLAT" && live.hard_stop != null && (
              <div style={{ display:"flex", gap:16, fontSize:10, color:"#6b7280", padding:"6px 0", borderTop:"1px solid #0f1e30" }}>
                <span>Stop dist: <span style={{ color:"#e5e7eb" }}>{live.stop_dist?.toFixed(4)}</span></span>
                <span>Hard stop: <span style={{ color:"#e5e7eb" }}>{live.hard_stop?.toFixed(4)}</span></span>
                <span>ATR mult: <span style={{ color:"#e5e7eb" }}>{live.atr_multiplier}x</span></span>
              </div>
            )}
            <div style={{ fontSize:9, color:"#1f2937", marginTop:6 }}>as of {live.date}</div>
          </>
        )}

        {ok && summary && (
          <div style={{ marginTop:10, paddingTop:10, borderTop:"1px solid #0f1e30" }}>
            <div style={{ fontSize:9, color:"#374151", marginBottom:6, letterSpacing:"0.08em" }}>
              VALIDATED TEST-WINDOW PERFORMANCE
            </div>
            <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr 1fr 1fr", gap:8 }}>
              <div>
                <div style={{ fontSize:9, color:"#374151" }}>TRADES</div>
                <div style={{ fontSize:12, fontWeight:700, color:"#e5e7eb" }}>{summary.n_trades}</div>
              </div>
              <div>
                <div style={{ fontSize:9, color:"#374151" }}>HIT RATE</div>
                <div style={{ fontSize:12, fontWeight:700, color: summary.hit_pct >= 55 ? "#22c55e" : "#f59e0b" }}>{summary.hit_pct}%</div>
              </div>
              <div>
                <div style={{ fontSize:9, color:"#374151" }}>R:R</div>
                <div style={{ fontSize:12, fontWeight:700, color:"#e5e7eb" }}>{summary.rr}</div>
              </div>
              <div>
                <div style={{ fontSize:9, color:"#374151" }}>TOTAL P&L</div>
                <div style={{ fontSize:12, fontWeight:700, color: summary.total_pnl >= 0 ? "#22c55e" : "#ef4444" }}>
                  {summary.total_pnl >= 0 ? "+" : ""}{summary.total_pnl} {summary.unit}
                </div>
              </div>
            </div>
            <div style={{ fontSize:9, color:"#374151", marginTop:6 }}>
              Max DD: <span style={{ color:"#ef4444" }}>{summary.max_dd}</span> · Vol gate: {summary.vol_gate}
            </div>
          </div>
        )}
      </Card>
    )
  }

  return (
    <>
      <div style={{ fontSize:9, color:"#374151", marginBottom:12, fontStyle:"italic" }}>
        Rule-based M1M2 mean-reversion signal · sourced from demsup regime classifier's level_z_126 ·
        not an ML model — deterministic threshold + regime + volatility gate.
        Test-window performance (Jul 2024–May 2026) opened once, per train/validation/test discipline.
      </div>
      <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:12 }}>
        {PRODUCTS.map(p => <SignalCard key={p.key} product={p.key} color={p.color} label={p.label} />)}
      </div>
      <Card title="How This Signal Works" style={{ marginTop:12 }}>
        {[
          ["1. Regime classification", "demsup's regime classifier labels each day (Deep-Backwardation, Easing-Contango, etc.) and computes level_z_126 — how far M1M2 sits from its lagged 126-day baseline, in standard deviations."],
          ["2. Regime gate", "Each product excludes specific regimes shown historically to have no edge (e.g. Transition labels for all products; LCO excludes Deep-Backwardation at 48.7% hit rate; HO excludes Easing-Backwardation at 0% hit rate)."],
          ["3. Volatility gate", "LCO and HO only trade in LOW volatility (ATR14 below a threshold); LGO is inverted — it only trades in HIGH volatility. CL has no volatility gate."],
          ["4. Threshold crossing", "If the regime and vol gates pass, a BUY fires when z < -threshold (spread too depressed) and a SELL fires when z > +threshold (spread too elevated) — mean reversion, not momentum."],
          ["5. Stop & target", "ATR14 × a per-product multiplier sets the hard stop. A trailing stop activates once price moves partway to target."],
        ].map(([k,v],i) => (
          <div key={i} style={{ display:"flex", gap:8, padding:"6px 0", borderBottom:"1px solid #0f1e30", fontSize:11 }}>
            <span style={{ color:"#f59e0b", fontWeight:700, minWidth:160 }}>{k}</span>
            <span style={{ color:"#6b7280" }}>{v}</span>
          </div>
        ))}
      </Card>
    </>
  )
}

function TabGeo({ d }) {
  const geo  = d?.geo || {}
  const agg  = geo.aggregate || {}
  const events      = geo.active_events    || []
  const chokepoints = geo.chokepoints      || []
  const score       = agg.composite        ?? null
  const scoreCol    = score >= 8 ? "#ef4444" : score >= 6 ? "#f97316" : score >= 4 ? "#f59e0b" : "#22c55e"
  const pct         = score != null ? (score / 10) * 100 : 0
  const durationLabel = d => ({ days_weeks:"Days–Weeks", weeks_months:"Weeks–Months", multi_year:"Multi-Year", structural:"Structural" }[d] || d)
  const riskCol = r => ({ CRITICAL:"#ef4444", HIGH:"#f97316", MODERATE:"#f59e0b", LOW:"#22c55e", LOW_RISK:"#22c55e", MODERATE_RISK:"#f59e0b", ELEVATED_RISK:"#f97316", HIGH_RISK:"#ef4444", CRITICAL_RISK:"#ef4444" }[r] || "#6b7280")
  return (
    <>
      <Card title="Geopolitical Risk Score" style={{ marginBottom: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 20, marginBottom: 16 }}>
          <div>
            <div style={{ fontSize: 56, fontWeight: 900, color: scoreCol, lineHeight: 1 }}>{score != null ? score.toFixed(1) : "—"}</div>
            <div style={{ fontSize: 10, color: "#6b7280", marginTop: 2 }}>out of 10.0</div>
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
              <span style={{ fontSize: 14, fontWeight: 700, color: scoreCol, background: scoreCol + "22", borderRadius: 6, padding: "3px 12px" }}>{agg.signal || "—"}</span>
              <span style={{ fontSize: 12, color: "#6b7280" }}>{agg.event_count || 0} active events</span>
            </div>
            <div style={{ height: 8, background: "#1a2535", borderRadius: 4, marginBottom: 8 }}>
              <div style={{ width: pct + "%", height: "100%", background: scoreCol, borderRadius: 4, transition: "width 0.6s" }} />
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, color: "#374151" }}>
              <span>0 — LOW</span><span>5 — MODERATE</span><span>10 — CRITICAL</span>
            </div>
          </div>
        </div>
        <div style={{ background: scoreCol + "12", border: `1px solid ${scoreCol}30`, borderRadius: 8, padding: "10px 14px", marginBottom: 12 }}>
          <div style={{ fontSize: 10, color: "#6b7280", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 4 }}>Implied Price Risk Premium</div>
          <div style={{ fontSize: 20, fontWeight: 800, color: scoreCol }}>${agg.implied_premium?.low}–${agg.implied_premium?.high}/bbl</div>
        </div>
      </Card>
      <Card title="Active Geopolitical Events" style={{ marginBottom: 12 }}>
        {events.length === 0
          ? <div style={{ color: "#374151", fontSize: 12, padding: "8px 0" }}>No active events</div>
          : events.map((ev, i) => {
            const col    = riskCol(ev.signal)
            const comp   = ev.scoring?.composite ?? 0
            const pctBar = (comp / 10) * 100
            return (
              <div key={i} style={{ padding: "12px 0", borderBottom: "1px solid #0f1e30" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 6 }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 3 }}>
                      <span style={{ fontSize: 13, fontWeight: 700, color: "#e5e7eb" }}>{ev.name}</span>
                      <span style={{ fontSize: 10, fontWeight: 700, color: col, background: col + "22", borderRadius: 4, padding: "1px 6px" }}>{ev.signal}</span>
                    </div>
                    <div style={{ fontSize: 10, color: "#6b7280", marginBottom: 3 }}>📍 {ev.region}{ev.chokepoint && <span style={{ color: "#f97316", marginLeft: 8 }}>⚠ {ev.chokepoint}</span>}</div>
                    <div style={{ fontSize: 10, color: "#374151", fontStyle: "italic" }}>{ev.notes}</div>
                  </div>
                  <div style={{ textAlign: "right", marginLeft: 16, flexShrink: 0 }}>
                    <div style={{ fontSize: 24, fontWeight: 900, color: col, lineHeight: 1 }}>{comp.toFixed(1)}</div>
                    <div style={{ fontSize: 9, color: "#374151" }}>/ 10</div>
                  </div>
                </div>
                <div style={{ height: 4, background: "#0a0f1a", borderRadius: 2, marginBottom: 6 }}>
                  <div style={{ width: pctBar + "%", height: "100%", background: col, borderRadius: 2 }} />
                </div>
              </div>
            )
          })}
      </Card>
      <Card title="Global Maritime Chokepoints">
        {chokepoints.map((cp, i) => {
          const col = riskCol(cp.risk_level)
          return (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 12, padding: "8px 0", borderBottom: "1px solid #0f1e30" }}>
              <div style={{ width: 8, height: 8, borderRadius: "50%", background: col, flexShrink: 0 }} />
              <div style={{ flex: 1 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{ fontSize: 12, fontWeight: 600, color: "#e5e7eb" }}>{cp.name}</span>
                  {cp.active_threat && <span style={{ fontSize: 9, fontWeight: 700, color: "#f97316", background: "#f9731622", borderRadius: 3, padding: "1px 5px" }}>⚠ ACTIVE THREAT</span>}
                </div>
              </div>
              <div style={{ textAlign: "right" }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: "#e5e7eb" }}>{cp.flow_mbd > 0 ? cp.flow_mbd + " mbd" : "bypass"}</div>
                <div style={{ fontSize: 9, fontWeight: 700, color: col }}>{cp.risk_level}</div>
              </div>
            </div>
          )
        })}
      </Card>
    </>
  )
}

// ── TabSeasonality — STL decomposition, 4 products ────────────────────────
function TabSeasonality() {
  const MONTHS     = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
  const MONTH_FULL = ["January","February","March","April","May","June",
                      "July","August","September","October","November","December"]

  const [seasonData,  setSeasonData]  = React.useState(null)
  const [loadErr,     setLoadErr]     = React.useState(null)
  const [product,     setProduct]     = React.useState("brent")
  const [viewMode,    setViewMode]    = React.useState("detrended")
  const [yearFrom,    setYearFrom]    = React.useState(2016)
  const [yearTo,      setYearTo]      = React.useState(2026)
  const [showSeasAvg, setShowSeasAvg] = React.useState(true)
  const [highlightYr, setHighlightYr] = React.useState(null)
  const [detailMonth, setDetailMonth] = React.useState(null)
  const chartRef  = React.useRef(null)
  const chartInst = React.useRef(null)

  const ALL_YEARS = Array.from({length: 11}, (_, i) => 2016 + i)

  // All 4 products
  const SERIES = [
    { key: "brent", label: "Brent ICE",  color: "#3b82f6" },
    { key: "wti",   label: "WTI NYMEX",  color: "#22c55e" },
    { key: "rbob",  label: "RBOB",       color: "#f59e0b" },
    { key: "ho",    label: "HO / ULSD",  color: "#ef4444" },
  ]

  React.useEffect(() => {
    fetch("/api/seasonality")
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(d => setSeasonData(d))
      .catch(e => setLoadErr(e.message))
  }, [])

  const YEAR_COLORS = ["#3b82f6","#22c55e","#f59e0b","#ef4444","#a78bfa","#06b6d4","#f97316","#e879f9","#84cc16","#fb923c","#38bdf8"]
  const yearColor = (year, idx) => year === 2026 ? "#ffffff" : YEAR_COLORS[idx % YEAR_COLORS.length]

  const seriesObj = React.useMemo(() => {
    if (!seasonData) return null
    const s = seasonData.series?.[product]
    return s && !s.error ? s : null
  }, [seasonData, product])

  const yearData = React.useMemo(() => {
    if (!seriesObj) return {}
    return viewMode === "detrended" ? seriesObj.detrended_years || {} : seriesObj.raw_years || {}
  }, [seriesObj, viewMode])

  const selectedYears = React.useMemo(() =>
    ALL_YEARS.filter(y => y >= yearFrom && y <= yearTo && yearData[y]),
    [yearData, yearFrom, yearTo]
  )

  const seasonalAvg = seriesObj?.seasonal_avg || null

  React.useEffect(() => {
    if (!window.Chart || !chartRef.current || !seasonData) return
    if (chartInst.current) { chartInst.current.destroy(); chartInst.current = null }
    const datasets = []
    const curProd = SERIES.find(s => s.key === product)
    selectedYears.forEach((year, idx) => {
      const data = yearData[year]; if (!data) return
      const isHigh = highlightYr === year; const isCurr = year === 2026
      const col = yearColor(year, idx)
      datasets.push({ label: String(year), data, borderColor: col, backgroundColor: col + "11",
        borderWidth: isCurr ? 3 : isHigh ? 2.5 : 1.5, pointRadius: isCurr ? 4 : isHigh ? 3 : 2,
        pointHoverRadius: 5, tension: 0.35, fill: false, spanGaps: true,
        order: isCurr ? 0 : isHigh ? 1 : 2 })
    })
    if (showSeasAvg && seasonalAvg && viewMode === "detrended") {
      datasets.push({ label: "STL seasonal avg", data: seasonalAvg, borderColor: "#ffffff",
        backgroundColor: "transparent", borderWidth: 2.5, borderDash: [6, 4],
        pointRadius: 0, pointHoverRadius: 4, tension: 0.35, fill: false, order: 0 })
    }
    chartInst.current = new window.Chart(chartRef.current, {
      type: "line",
      data: { labels: MONTHS, datasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            mode: "index", intersect: false,
            callbacks: {
              title: items => MONTH_FULL[items[0]?.dataIndex] || "",
              label: ctx => {
                const v = ctx.parsed.y; if (v == null) return null
                const sign = v >= 0 ? "+" : ""
                return ` ${ctx.dataset.label}: ${viewMode === "detrended" ? `${sign}$${v.toFixed(2)}` : `$${v.toFixed(2)}`}/bbl`
              }
            },
            backgroundColor: "#0d1117", borderColor: "#1a2535", borderWidth: 1,
            titleColor: "#9ca3af", bodyColor: "#e5e7eb", padding: 10,
          }
        },
        scales: {
          x: { grid: { color: "#0f1e30" }, ticks: { color: "#4b5563", font: { size: 11 } } },
          y: { grid: { color: "#0f1e30" }, ticks: { color: "#4b5563", font: { size: 11 },
            callback: v => viewMode === "detrended" ? (v >= 0 ? "+" : "") + "$" + v : "$" + v } }
        },
        interaction: { mode: "index", intersect: false }, animation: { duration: 200 },
      }
    })
  }, [seasonData, product, selectedYears, highlightYr, showSeasAvg, viewMode])

  const monthDetail = React.useMemo(() => {
    if (detailMonth == null || !yearData) return []
    return selectedYears.map(y => ({ year: y, value: yearData[y]?.[detailMonth] ?? null }))
      .filter(r => r.value != null).sort((a,b) => a.year - b.year)
  }, [detailMonth, selectedYears, yearData])

  const curSeries    = SERIES.find(s => s.key === product)
  const productColor = curSeries?.color || "#3b82f6"
  const productLabel = curSeries?.label || product

  // Check if a product has data or error
  const hasData = key => {
    const s = seasonData?.series?.[key]
    return s && !s.error && s.seasonal_avg
  }

  function yearStats(year) {
    const data = yearData[year]?.filter(v => v != null)
    if (!data?.length) return null
    return { min: Math.min(...data).toFixed(2), max: Math.max(...data).toFixed(2),
      mean: (data.reduce((a,b)=>a+b,0)/data.length).toFixed(2) }
  }

  return (
    <>
      {/* Method banner */}
      <div style={{ background: "#0a0f1a", border: "1px solid #1a2535", borderRadius: 8,
        padding: "9px 14px", marginBottom: 12, fontSize: 10, color: "#4b5563",
        display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
        {seasonData ? (
          <>
            <span style={{ color: "#22c55e", fontWeight: 700 }}>✓ STL decomposition</span>
            <span>· robust=True · period=12 · 10yr window ·</span>
            <span>through <span style={{ color: "#9ca3af" }}>{seasonData.data_through}</span></span>
            <span>· Brent/WTI: <span style={{ color: "#22c55e" }}>github/datasets (direct)</span></span>
            <span>· RBOB/HO: <span style={{ color: "#22c55e" }}>EIA API (direct)</span></span>
            {seriesObj?.resid_std && <span>· resid σ = <span style={{ color: "#f59e0b" }}>${seriesObj.resid_std}/bbl</span></span>}
          </>
        ) : (
          <span style={{ color: loadErr ? "#f59e0b" : "#374151", fontWeight: 700 }}>
            {loadErr ? "⚠ Run: python backend/fetchers/seasonality_fetcher.py" : "Loading…"}
          </span>
        )}
      </div>

      {/* Controls */}
      <div style={{ background: "#0a0f1a", border: "1px solid #1a2535", borderRadius: 8,
        padding: "10px 14px", marginBottom: 12 }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" }}>

          {/* Product toggles — all 4 */}
          <div style={{ display: "flex", gap: 4 }}>
            {SERIES.map(s => {
              const available = !seasonData || hasData(s.key)
              return (
                <button key={s.key} onClick={() => available && setProduct(s.key)}
                  title={!available ? "Data unavailable — check EIA_API_KEY" : ""}
                  style={{
                    padding: "5px 14px", borderRadius: 6, fontSize: 12,
                    cursor: available ? "pointer" : "not-allowed",
                    fontWeight: product === s.key ? 700 : 400,
                    opacity: available ? 1 : 0.4,
                    background: product === s.key ? s.color + "22" : "transparent",
                    border: `1px solid ${product === s.key ? s.color : "#1a2535"}`,
                    color:  product === s.key ? s.color : "#4b5563",
                  }}>{s.label}</button>
              )
            })}
          </div>

          {/* View mode */}
          <div style={{ display: "flex", gap: 4 }}>
            {[["detrended","Detrended (STL)"],["raw","Raw prices"]].map(([m, label]) => (
              <button key={m} onClick={() => setViewMode(m)} style={{
                padding: "5px 12px", borderRadius: 6, fontSize: 11, cursor: "pointer",
                fontWeight: viewMode === m ? 700 : 400,
                background: viewMode === m ? "#1a2535" : "transparent",
                border: `1px solid ${viewMode === m ? "#374151" : "#1a2535"}`,
                color: viewMode === m ? "#e5e7eb" : "#4b5563" }}>{label}</button>
            ))}
          </div>

          {/* Year range */}
          <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "#4b5563" }}>
            <span>From</span>
            <select value={yearFrom} onChange={e => setYearFrom(Number(e.target.value))}
              style={{ background: "#0d1117", border: "1px solid #1a2535", borderRadius: 5, color: "#e5e7eb", fontSize: 12, padding: "3px 6px", cursor: "pointer" }}>
              {ALL_YEARS.filter(y => y <= yearTo).map(y => <option key={y} value={y}>{y}</option>)}
            </select>
            <span>to</span>
            <select value={yearTo} onChange={e => setYearTo(Number(e.target.value))}
              style={{ background: "#0d1117", border: "1px solid #1a2535", borderRadius: 5, color: "#e5e7eb", fontSize: 12, padding: "3px 6px", cursor: "pointer" }}>
              {ALL_YEARS.filter(y => y >= yearFrom).map(y => <option key={y} value={y}>{y}</option>)}
            </select>
          </div>

          {/* Presets */}
          <div style={{ display: "flex", gap: 4 }}>
            {[["5yr",2021,2026],["7yr",2019,2026],["All",2016,2026]].map(([l,f,t]) => (
              <button key={l} onClick={() => { setYearFrom(f); setYearTo(t) }} style={{
                padding: "3px 10px", borderRadius: 5, fontSize: 11, cursor: "pointer",
                background: yearFrom===f && yearTo===t ? "#1a2535" : "transparent",
                border: "1px solid #1a2535", color: "#6b7280" }}>{l}</button>
            ))}
          </div>

          {viewMode === "detrended" && (
            <button onClick={() => setShowSeasAvg(v => !v)} style={{
              padding: "3px 10px", borderRadius: 5, fontSize: 11, cursor: "pointer",
              background: showSeasAvg ? "#ffffff18" : "transparent",
              border: `1px solid ${showSeasAvg ? "#ffffff44" : "#1a2535"}`,
              color: showSeasAvg ? "#ffffff" : "#4b5563" }}>
              STL seasonal avg
            </button>
          )}
        </div>
      </div>

      {/* Chart */}
      <Card style={{ marginBottom: 12 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
          <div>
            <span style={{ fontSize: 13, fontWeight: 700, color: productColor }}>{productLabel}</span>
            <span style={{ fontSize: 11, color: "#374151", marginLeft: 8 }}>
              {viewMode === "detrended" ? "$/bbl above/below STL trend — years directly comparable" : "raw monthly average $/bbl"}
            </span>
          </div>
          <div style={{ fontSize: 10, color: "#374151" }}>Click month label to see year-by-year breakdown ↓</div>
        </div>

        {!seasonData ? (
          <div style={{ height: 300, display: "flex", alignItems: "center", justifyContent: "center",
            color: "#1f2937", fontSize: 11, fontFamily: "monospace" }}>
            {loadErr ? "⚠ SEASONALITY DATA NOT FOUND — run seasonality_fetcher.py" : "LOADING…"}
          </div>
        ) : !seriesObj ? (
          <div style={{ height: 300, display: "flex", alignItems: "center", justifyContent: "center",
            color: "#f59e0b", fontSize: 11, fontFamily: "monospace" }}>
            ⚠ {productLabel} DATA UNAVAILABLE — check EIA_API_KEY in environment
          </div>
        ) : (
          <div style={{ position: "relative", width: "100%", height: 300 }}>
            <canvas ref={chartRef} role="img" aria-label={`Seasonal ${productLabel} price chart by year`} />
          </div>
        )}

        {viewMode === "detrended" && seriesObj && (
          <div style={{ fontSize: 9, color: "#374151", marginTop: 6, fontStyle: "italic" }}>
            Zero = trend baseline. Positive = above trend, negative = below trend. Dashed white = STL seasonal average.
          </div>
        )}

        {seasonData && seriesObj && (
          <div style={{ display: "flex", gap: 2, marginTop: 8 }}>
            {MONTHS.map((m, mi) => (
              <button key={m} onClick={() => setDetailMonth(detailMonth === mi ? null : mi)} style={{
                flex: 1, padding: "4px 0", fontSize: 10, cursor: "pointer", borderRadius: 4,
                background: detailMonth === mi ? productColor + "33" : "transparent",
                border: `1px solid ${detailMonth === mi ? productColor : "#1a2535"}`,
                color: detailMonth === mi ? productColor : "#374151",
                fontWeight: detailMonth === mi ? 700 : 400 }}>{m}</button>
            ))}
          </div>
        )}
      </Card>

      {/* STL seasonal bar chart */}
      {seasonalAvg && viewMode === "detrended" && (
        <Card title="STL Seasonal Component — $/bbl vs detrended trend" style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 9, color: "#374151", marginBottom: 10, fontStyle: "italic" }}>
            Pure seasonal signal · robust=True downweights 2020/2022 outliers · positive = typically above trend
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
            {(() => {
              const maxAbs = Math.max(...seasonalAvg.map(Math.abs), 1)
              return MONTHS.map((m, mi) => {
                const v = seasonalAvg[mi]; const pct = (Math.abs(v) / maxAbs) * 100
                const isPos = v >= 0; const col = isPos ? "#22c55e" : "#ef4444"
                return (
                  <div key={m} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{ fontSize: 11, color: "#6b7280", minWidth: 28 }}>{m}</span>
                    <div style={{ flex: 1, height: 14, background: "#0a0f1a", borderRadius: 3, position: "relative", overflow: "hidden" }}>
                      <div style={{ position: "absolute", left: "50%", top: 0, bottom: 0, width: 1, background: "#1a2535", zIndex: 1 }} />
                      <div style={{ position: "absolute", top: 1, bottom: 1, width: (pct / 2) + "%",
                        background: col, borderRadius: 2, opacity: 0.85, ...(isPos ? { left: "50%" } : { right: "50%" }) }} />
                    </div>
                    <span style={{ fontSize: 11, fontWeight: 700, color: col, minWidth: 52, textAlign: "right", fontFamily: "monospace" }}>
                      {isPos ? "+" : ""}${Math.abs(v).toFixed(2)}
                    </span>
                  </div>
                )
              })
            })()}
          </div>
        </Card>
      )}

      {/* Month detail */}
      {detailMonth != null && monthDetail.length > 0 && (
        <Card title={`${MONTH_FULL[detailMonth]} — ${productLabel} by Year`} style={{ marginBottom: 12 }}>
          {(() => {
            const vals  = monthDetail.map(r => r.value)
            const maxV  = Math.max(...vals); const minV = Math.min(...vals); const range = maxV - minV || 1
            return (
              <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                {monthDetail.map((r, i) => {
                  const pct    = ((r.value - minV) / range) * 100
                  const isMax  = r.value === maxV; const isMin = r.value === minV; const isCurr = r.year === 2026
                  const col    = isMax ? "#ef4444" : isMin ? "#22c55e" : productColor
                  return (
                    <div key={r.year} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <span style={{ fontSize: 11, fontWeight: isCurr ? 700 : 400,
                        color: isCurr ? "#ffffff" : "#6b7280", minWidth: 36, textAlign: "right", fontFamily: "monospace" }}>
                        {r.year}
                      </span>
                      <div style={{ flex: 1, height: 12, background: "#0a0f1a", borderRadius: 3, overflow: "hidden" }}>
                        <div style={{ width: Math.max(pct, 2) + "%", height: "100%", background: col, borderRadius: 3, opacity: 0.85 }} />
                      </div>
                      <span style={{ fontSize: 12, fontWeight: isMax||isMin||isCurr ? 700 : 400,
                        color: isMax ? "#ef4444" : isMin ? "#22c55e" : isCurr ? "#ffffff" : "#9ca3af",
                        minWidth: 60, textAlign: "right", fontFamily: "monospace" }}>
                        {viewMode === "detrended" ? (r.value >= 0 ? "+" : "") + "$" + r.value.toFixed(2) : "$" + r.value.toFixed(2)}
                      </span>
                      {(isMax || isMin || isCurr) && (
                        <span style={{ fontSize: 9, fontWeight: 700, minWidth: 36,
                          color: isMax ? "#ef4444" : isMin ? "#22c55e" : "#ffffff" }}>
                          {isMax ? "PEAK" : isMin ? "LOW" : "NOW"}
                        </span>
                      )}
                    </div>
                  )
                })}
              </div>
            )
          })()}
        </Card>
      )}

      {/* Year legend */}
      {seasonData && seriesObj && (
        <Card title="Year Overview" style={{ marginBottom: 12 }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px,1fr))", gap: 6 }}>
            {[...selectedYears].reverse().map((year, idx) => {
              const stats  = yearStats(year)
              const col    = yearColor(year, selectedYears.length - 1 - idx)
              const isHigh = highlightYr === year
              return (
                <div key={year} onMouseEnter={() => setHighlightYr(year)} onMouseLeave={() => setHighlightYr(null)}
                  style={{ background: isHigh ? col + "18" : "#0a0f1a", border: `1px solid ${isHigh ? col : "#1a2535"}`,
                    borderRadius: 6, padding: "8px 10px", cursor: "pointer", transition: "all 0.12s" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span style={{ fontSize: 13, fontWeight: 700, color: col }}>
                      {year}{year === 2026 && <span style={{ fontSize: 9, color: "#374151", marginLeft: 4, fontWeight: 400 }}>YTD</span>}
                    </span>
                    {stats && <span style={{ fontSize: 10, color: "#6b7280", fontFamily: "monospace" }}>avg ${stats.mean}</span>}
                  </div>
                  {stats && <div style={{ fontSize: 9, color: "#374151", marginTop: 2 }}>${stats.min} – ${stats.max}</div>}
                </div>
              )
            })}
          </div>
        </Card>
      )}

      {/* Seasonal reference */}
      <Card title="Seasonal Reference — OilMacroTrading Framework">
        {[
          ["Mar–May",  "bull", "Crude +$4–10 above trend. Driving season build + post-turnaround demand ramp."],
          ["Feb–May",  "bull", "RBOB crack seasonal peak — most reliable seasonal trade. Long RB vs CL."],
          ["Jun–Aug",  "bull", "Peak US driving + EM power gen. Curve often backwardated."],
          ["Oct–Nov",  "bull", "HO/Gasoil crack peak — European heating season. Long HO crack."],
          ["Sep–Oct",  "bear", "Autumn maintenance. Post-Labour Day gasoline weakness."],
          ["Nov–Dec",  "bear", "Year-end softening. Crude -$3–5 below trend. Low liquidity."],
          ["Jan–Feb",  "neut", "Heating demand supports distillates. Crude near seasonal trough."],
        ].map(([window, dir, note], i) => {
          const col = dir === "bull" ? "#22c55e" : dir === "bear" ? "#ef4444" : "#f59e0b"
          return (
            <div key={i} style={{ display: "flex", gap: 10, padding: "6px 0", borderBottom: "1px solid #0f1e30", fontSize: 11, alignItems: "flex-start" }}>
              <span style={{ color: "#f59e0b", fontWeight: 700, minWidth: 70, flexShrink: 0 }}>{window}</span>
              <span style={{ fontSize: 9, fontWeight: 700, padding: "1px 7px", borderRadius: 10,
                color: col, background: col + "22", minWidth: 52, textAlign: "center", flexShrink: 0 }}>
                {dir === "bull" ? "Bullish" : dir === "bear" ? "Bearish" : "Neutral"}
              </span>
              <span style={{ color: "#4b5563", lineHeight: 1.5 }}>{note}</span>
            </div>
          )
        })}
      </Card>
    </>
  )
}

function CountdownDisplay({ initialSeconds = 30 }) {
  const [sec, setSec] = React.useState(initialSeconds)
  React.useEffect(() => {
    const t = setInterval(() => setSec(s => s > 0 ? s - 1 : initialSeconds), 1000)
    return () => clearInterval(t)
  }, [initialSeconds])
  return <span style={{ fontSize:11, color:"#1f2937" }}>· Refresh in {sec}s</span>
}

export default function App() {
  const [activeTab,    setActiveTab]    = useState("overview")
  const [data,         setData]         = useState(null)
  const [curveHistory, setCurveHistory] = useState([])
  const [regimeHistory, setRegimeHistory] = useState(null)
  const [history,      setHistory]      = useState([])
  const [alerts,       setAlerts]       = useState([])
  const [loading,      setLoading]      = useState(true)
  const [lastUpdate,   setLastUpdate]   = useState(null)

  const [curveSel,   setCurveSel]   = useState({brent:"M1-M2", wti:"M1-M2", rbob:"M1-M2", ho:"M1-M2"})
  const [curveRange, setCurveRange] = useState({brent:"3M",    wti:"3M",    rbob:"3M",    ho:"3M"   })

  const fetchAll = useCallback(async () => {
    try {
      const [all, eia, rig, crack, hist, invSig, crackSig, fj, qs, duc, geo, curve, curveHist, qsHist, demsup, signalEngine] = await Promise.all([
        fetch(`${API}/api/all`).then(r => r.json()),
        fetch(`${API}/api/eia`).then(r => r.json()),
        fetch(`${API}/api/rig-count`).then(r => r.json()).catch(() => null),
        fetch(`${API}/api/crack`).then(r => r.json()).catch(() => null),
        fetch(`${API}/api/history`).then(r => r.json()).catch(() => []),
        fetch(`${API}/api/inventory-signals`).then(r => r.json()).catch(() => null),
        fetch(`${API}/api/crack-signals`).then(r => r.json()).catch(() => null),
        fetch(`${API}/api/financialjuice`).then(r => r.json()).catch(() => null),
        fetch(`${API}/api/quality-spreads`).then(r => r.json()).catch(() => null),
        fetch(`${API}/api/duc`).then(r => r.json()).catch(() => null),
        fetch(`${API}/api/geo-score`).then(r => r.json()).catch(() => null),
        fetch(`${API}/api/curve`).then(r => r.json()).catch(() => null),
        fetch(`${API}/api/curve-history`).then(r => r.json()).catch(() => []),
        fetch(`${API}/api/quality-spreads-history`).then(r => r.json()).catch(() => []),
        fetch(`${API}/api/demsup`).then(r => r.json()).catch(() => null),
        fetch(`${API}/api/signal-engine`).then(r => r.json()).catch(() => null),
      ])
      const merged = {
        ...all, eia, rig_count: rig, crack, inv_signals: invSig,
        crack_signals: crackSig, fj, quality_spreads: qs, duc,
        qs_history: Array.isArray(qsHist) ? qsHist : [],
        geo, curve, demsup, signal_engine: signalEngine,
        curve_history: Array.isArray(curveHist) ? curveHist : [],
      }
      const histArr = Array.isArray(hist) ? hist : []
      setData(merged)
      setCurveHistory(prev => {
        const newCH = Array.isArray(curveHist) ? curveHist : []
        if (prev.length !== newCH.length) return newCH
        if (prev.length === 0) return newCH
        return prev
      })
      setHistory(histArr)
      setLastUpdate(new Date())
      setAlerts(computeAlerts(histArr, merged?.futures?.contracts))
    } catch(e) { console.error(e) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => {
    fetchAll()
    const d = setInterval(fetchAll, 30000)
    return () => clearInterval(d)
  }, [fetchAll])

  // Regime history (full daily series per product, for the Futures Curve tab's
  // historical timeline + z-score chart) is fetched ONCE on mount, not on the
  // 30s polling loop — unlike everything else in fetchAll, this is a large
  // dataset (~1,500+ rows × 4 products) that only changes server-side every
  // 6 hours (job_regime_history's interval in api.py), so re-fetching it every
  // 30 seconds would be pure waste with zero new information most of the time.
  useEffect(() => {
    fetch(`${API}/api/regime-history`).then(r => r.json()).then(setRegimeHistory).catch(() => setRegimeHistory(null))
  }, [])

  const comp     = data?.composite?.composite || {}
  const score    = comp.score ?? null
  const scoreCol = score > 0.5 ? "#22c55e" : score < -0.5 ? "#ef4444" : "#f59e0b"
  const hasCrit  = alerts.some(a => a.severity === "critical")

  return (
    <div style={{ background:"#060d18", minHeight:"100vh", color:"#e5e7eb",
      fontFamily:"'Inter','Segoe UI',system-ui,sans-serif", display:"flex", flexDirection:"column" }}>

      <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between",
        padding:"8px 20px", background:"#0a0f1a",
        borderBottom:"1px solid #0f1e30", position:"sticky", top:0, zIndex:100 }}>
        <div style={{ display:"flex", alignItems:"center", gap:10 }}>
          <span style={{ fontSize:15, fontWeight:800, color:"#00d98b", letterSpacing:"0.05em" }}>⚡ ENERGY SIGNAL</span>
          <span style={{ color:"#0f1e30" }}>|</span>
          <span style={{ width:7, height:7, borderRadius:"50%", display:"inline-block",
            background: loading ? "#f59e0b" : "#22c55e" }} />
          <span style={{ fontSize:11, color:"#4b5563" }}>
            {loading ? "Loading..." : lastUpdate ? `Updated ${lastUpdate.toLocaleTimeString()}` : "Live"}
          </span>
          <CountdownDisplay initialSeconds={30} />
        </div>
        <div style={{ display:"flex", alignItems:"center", gap:6 }}>
          {alerts.length > 0 && (
            <span style={{ fontSize:10, fontWeight:800,
              color: hasCrit ? "#ef4444" : "#f59e0b",
              background: hasCrit ? "#ef444418" : "#f59e0b18",
              border: `0.5px solid ${hasCrit ? "#ef444440" : "#f59e0b40"}`,
              borderRadius:10, padding:"2px 8px", marginRight:4 }}>
              {hasCrit ? "⚠" : "◉"} {alerts.length} ALERT{alerts.length > 1 ? "S" : ""}
            </span>
          )}
          <span style={{ fontSize:11, color:"#4b5563" }}>Composite</span>
          <span style={{ fontSize:16, fontWeight:800, color:scoreCol }}>
            {score != null ? (score > 0 ? "+" : "") + score.toFixed(1) : "—"}
          </span>
          <span style={{ fontSize:11, color:scoreCol, background: scoreCol + "22", borderRadius:10, padding:"1px 8px" }}>
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
            {activeTab === "overview"    && <TabOverview  d={data} />}
            {activeTab === "prices"      && <TabPrices    d={data} history={history} />}
            {activeTab === "spreads"     && <TabSpreads   d={data} history={history} />}
            {activeTab === "inventory"   && <TabInventory d={data} />}
            {activeTab === "macro"       && <TabMacro     d={data} />}
            {activeTab === "sentiment"   && <TabSentiment d={data} />}
            {activeTab === "geo"         && <TabGeo       d={data} />}
            {activeTab === "curve"       && <TabCurve     d={data} curveHistory={curveHistory} curveSel={curveSel} setCurveSel={setCurveSel} curveRange={curveRange} setCurveRange={setCurveRange} regimeHistory={regimeHistory} />}
            {activeTab === "signal"      && <TabSignal    d={data} />}
            {activeTab === "seasonality" && <TabSeasonality />}
          </>
        )}
      </div>

      <div style={{ textAlign:"center", padding:"10px 0", color:"#1a2535",
        fontSize:9, fontFamily:"monospace", borderTop:"1px solid #0f1e30" }}>
        EIA · YAHOO FINANCE · FRED · GIE AGSI+ · OPEN-METEO · CFTC · BAKER HUGHES · ARGUS/PLATTS · APIFY
      </div>
    </div>
  )
}
import { useState, useEffect } from "react"

const CONTRACTS = [
  { key: "brent",       label: "Brent",     unit: "$/bbl", color: "#3b82f6", icon: "🛢" },
  { key: "wti",         label: "WTI",       unit: "$/bbl", color: "#60a5fa", icon: "🛢" },
  { key: "rbob",        label: "RBOB",      unit: "$/bbl", color: "#f59e0b", icon: "⛽" },
  { key: "heating_oil", label: "Heating Oil", unit: "$/bbl", color: "#f97316", icon: "🔥" },
  { key: "henry_hub",   label: "Henry Hub", unit: "$/mmbtu", color: "#a78bfa", icon: "💨" },
  { key: "dubai",       label: "Dubai",     unit: "$/bbl", color: "#34d399", icon: "🛢" },
]

function PriceTile({ contract, data }) {
  if (!data) return (
    <div style={styles.tile}>
      <div style={styles.tileHeader}>
        <span style={styles.tileIcon}>{contract.icon}</span>
        <span style={styles.tileLabel}>{contract.label}</span>
      </div>
      <div style={{ ...styles.tilePrice, color: "#4b5563" }}>—</div>
      <div style={styles.tileUnit}>{contract.unit}</div>
    </div>
  )

  const price     = contract.key === "henry_hub" ? data.raw_price : data.price_bbl
  const change    = data.change_pct
  const isPos     = change > 0
  const isNeg     = change < 0
  const changeCol = isPos ? "#22c55e" : isNeg ? "#ef4444" : "#9ca3af"
  const arrow     = isPos ? "▲" : isNeg ? "▼" : "—"

  return (
    <div style={{ ...styles.tile, borderColor: contract.color + "33" }}>
      <div style={styles.tileHeader}>
        <span style={styles.tileIcon}>{contract.icon}</span>
        <span style={styles.tileLabel}>{contract.label}</span>
        <span style={{ ...styles.tileBadge, color: changeCol }}>
          {arrow} {change != null ? Math.abs(change).toFixed(2) + "%" : "—"}
        </span>
      </div>
      <div style={{ ...styles.tilePrice, color: contract.color }}>
        {price != null ? price.toFixed(2) : "—"}
      </div>
      <div style={styles.tileUnit}>{contract.unit}</div>
      {data.name && (
        <div style={styles.tileSub}>{data.name}</div>
      )}
    </div>
  )
}

export default function PricePanel({ apiBase = "http://localhost:8000" }) {
  const [data,      setData]      = useState(null)
  const [loading,   setLoading]   = useState(true)
  const [error,     setError]     = useState(null)
  const [updatedAt, setUpdatedAt] = useState(null)

  const fetchData = async () => {
    try {
      const r = await fetch(`${apiBase}/api/futures`)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const json = await r.json()
      setData(json.contracts || {})
      setUpdatedAt(json.fetched_at || new Date().toISOString())
      setError(null)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 30000)
    return () => clearInterval(interval)
  }, [])

  // Derived spreads from data
  const brentPrice = data?.brent?.price_bbl
  const wtiPrice   = data?.wti?.price_bbl
  const brentWti   = brentPrice && wtiPrice ? (brentPrice - wtiPrice).toFixed(2) : null

  const rbobPrice  = data?.rbob?.price_bbl
  const crack321   = brentPrice && rbobPrice && data?.heating_oil?.price_bbl
    ? (((2 * rbobPrice) + (1 * data.heating_oil.price_bbl) - (3 * brentPrice)) / 3).toFixed(2)
    : null

  return (
    <div style={styles.panel}>
      {/* Header */}
      <div style={styles.header}>
        <div style={styles.headerLeft}>
          <span style={styles.headerTitle}>Energy Prices</span>
          <span style={{ ...styles.dot, background: error ? "#ef4444" : loading ? "#f59e0b" : "#22c55e" }} />
          <span style={styles.headerSub}>
            {loading ? "Loading..." : error ? `Error: ${error}` : updatedAt ? `Updated ${new Date(updatedAt).toLocaleTimeString()}` : "Live"}
          </span>
        </div>
        <button style={styles.refreshBtn} onClick={fetchData}>↻ Refresh</button>
      </div>

      {/* Price tiles grid */}
      <div style={styles.grid}>
        {CONTRACTS.map(c => (
          <PriceTile key={c.key} contract={c} data={data?.[c.key]} />
        ))}
      </div>

      {/* Derived spreads bar */}
      <div style={styles.spreadsBar}>
        <div style={styles.spreadItem}>
          <span style={styles.spreadLabel}>Brent–WTI</span>
          <span style={{
            ...styles.spreadValue,
            color: brentWti > 8 ? "#ef4444" : brentWti < 2 ? "#22c55e" : "#e5e7eb"
          }}>
            {brentWti != null ? `$${brentWti}/bbl` : "—"}
          </span>
          {brentWti != null && (
            <span style={styles.spreadSignal}>
              {brentWti > 8 ? "⚠ US export bottleneck" : brentWti < 2 ? "↑ US exports high" : "Normal range"}
            </span>
          )}
        </div>
        <div style={styles.spreadDivider} />
        <div style={styles.spreadItem}>
          <span style={styles.spreadLabel}>3-2-1 Crack</span>
          <span style={{
            ...styles.spreadValue,
            color: crack321 > 20 ? "#22c55e" : crack321 < 10 ? "#ef4444" : "#e5e7eb"
          }}>
            {crack321 != null ? `$${crack321}/bbl` : "—"}
          </span>
          {crack321 != null && (
            <span style={styles.spreadSignal}>
              {crack321 > 20 ? "↑ Wide — product demand tight" : crack321 < 10 ? "↓ Compressed — runs may fall" : "Normal range"}
            </span>
          )}
        </div>
      </div>
    </div>
  )
}

const styles = {
  panel: {
    background: "#111827",
    border: "1px solid #1f2937",
    borderRadius: 12,
    padding: "16px",
    marginBottom: 16,
  },
  header: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 14,
  },
  headerLeft: {
    display: "flex",
    alignItems: "center",
    gap: 8,
  },
  headerTitle: {
    fontSize: 15,
    fontWeight: 600,
    color: "#f9fafb",
  },
  dot: {
    width: 7,
    height: 7,
    borderRadius: "50%",
    display: "inline-block",
  },
  headerSub: {
    fontSize: 12,
    color: "#6b7280",
  },
  refreshBtn: {
    background: "transparent",
    border: "1px solid #374151",
    borderRadius: 6,
    color: "#9ca3af",
    fontSize: 12,
    padding: "3px 10px",
    cursor: "pointer",
  },
  grid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
    gap: 10,
    marginBottom: 12,
  },
  tile: {
    background: "#1a2234",
    border: "1px solid #1f2937",
    borderRadius: 10,
    padding: "12px 14px",
    transition: "border-color 0.2s",
  },
  tileHeader: {
    display: "flex",
    alignItems: "center",
    gap: 5,
    marginBottom: 6,
  },
  tileIcon: {
    fontSize: 13,
  },
  tileLabel: {
    fontSize: 12,
    color: "#9ca3af",
    fontWeight: 500,
    flex: 1,
  },
  tileBadge: {
    fontSize: 11,
    fontWeight: 600,
  },
  tilePrice: {
    fontSize: 22,
    fontWeight: 700,
    letterSpacing: "-0.5px",
    lineHeight: 1.1,
  },
  tileUnit: {
    fontSize: 10,
    color: "#4b5563",
    marginTop: 2,
  },
  tileSub: {
    fontSize: 10,
    color: "#6b7280",
    marginTop: 4,
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
  spreadsBar: {
    display: "flex",
    alignItems: "center",
    background: "#0d1117",
    borderRadius: 8,
    padding: "10px 14px",
    gap: 16,
  },
  spreadItem: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    flex: 1,
  },
  spreadLabel: {
    fontSize: 12,
    color: "#6b7280",
    whiteSpace: "nowrap",
  },
  spreadValue: {
    fontSize: 14,
    fontWeight: 700,
  },
  spreadSignal: {
    fontSize: 11,
    color: "#6b7280",
    whiteSpace: "nowrap",
  },
  spreadDivider: {
    width: 1,
    height: 28,
    background: "#1f2937",
  },
}

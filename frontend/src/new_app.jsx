import { useState, useEffect, useCallback } from "react"
import PricePanel from "./panels/PricePanel"

const API = "http://localhost:8000"
const TABS = ["Overview", "Prices", "Inventory", "Cracks", "Macro", "News"]

export default function App() {
  const [tab,       setTab]       = useState("Overview")
  const [allData,   setAllData]   = useState(null)
  const [loading,   setLoading]   = useState(true)
  const [lastUpdate,setLastUpdate]= useState(null)
  const [countdown, setCountdown] = useState(30)

  const fetchAll = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/all`)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const json = await r.json()
      setAllData(json)
      setLastUpdate(new Date())
      setCountdown(30)
    } catch (e) {
      console.error("Fetch failed:", e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchAll()
    const dataInterval = setInterval(fetchAll, 30000)
    const countInterval = setInterval(() => setCountdown(c => c > 0 ? c - 1 : 30), 1000)
    return () => { clearInterval(dataInterval); clearInterval(countInterval) }
  }, [fetchAll])

  const composite = allData?.composite || {}
  const score     = composite.score ?? null
  const scoreCol  = score > 0.5 ? "#22c55e" : score < -0.5 ? "#ef4444" : "#f59e0b"
  const scoreLabel= composite.label || "—"

  return (
    <div style={s.app}>

      {/* Top bar */}
      <div style={s.topBar}>
        <div style={s.topLeft}>
          <span style={s.logo}>⚡ Energy Dashboard</span>
          <span style={s.topSep}>|</span>
          <span style={{ ...s.statusDot, background: loading ? "#f59e0b" : "#22c55e" }} />
          <span style={s.topSub}>
            {loading ? "Loading..." : lastUpdate ? `Updated ${lastUpdate.toLocaleTimeString()}` : "Live"}
          </span>
          <span style={s.topSub}>· Refresh in {countdown}s</span>
        </div>
        <div style={s.topRight}>
          <span style={{ ...s.compositeChip, color: scoreCol, borderColor: scoreCol + "44" }}>
            CI {score != null ? (score > 0 ? "+" : "") + score.toFixed(1) : "—"} {scoreLabel}
          </span>
        </div>
      </div>

      {/* Tab bar */}
      <div style={s.tabBar}>
        {TABS.map(t => (
          <button
            key={t}
            style={{ ...s.tabBtn, ...(tab === t ? s.tabActive : {}) }}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </div>

      {/* Content */}
      <div style={s.content}>
        {tab === "Overview" && (
          <>
            <PricePanel apiBase={API} />
            <div style={s.placeholder}>
              <span style={s.placeholderText}>Inventory Panel — coming next</span>
            </div>
            <div style={s.placeholder}>
              <span style={s.placeholderText}>Composite Index Panel — coming next</span>
            </div>
          </>
        )}
        {tab === "Prices" && (
          <PricePanel apiBase={API} />
        )}
        {tab === "Inventory" && (
          <div style={s.placeholder}>
            <span style={s.placeholderText}>Inventory Panel — coming next</span>
          </div>
        )}
        {tab === "Cracks" && (
          <div style={s.placeholder}>
            <span style={s.placeholderText}>Crack Spread Panel — coming next</span>
          </div>
        )}
        {tab === "Macro" && (
          <div style={s.placeholder}>
            <span style={s.placeholderText}>Macro Panel — coming next</span>
          </div>
        )}
        {tab === "News" && (
          <div style={s.placeholder}>
            <span style={s.placeholderText}>News & Sentiment Panel — coming next</span>
          </div>
        )}
      </div>
    </div>
  )
}

const s = {
  app: {
    background: "#0d1117",
    minHeight: "100vh",
    color: "#e5e7eb",
    fontFamily: "'Inter', 'Segoe UI', sans-serif",
  },
  topBar: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "10px 20px",
    background: "#111827",
    borderBottom: "1px solid #1f2937",
    position: "sticky",
    top: 0,
    zIndex: 100,
  },
  topLeft: {
    display: "flex",
    alignItems: "center",
    gap: 8,
  },
  logo: {
    fontSize: 15,
    fontWeight: 700,
    color: "#f9fafb",
  },
  topSep: {
    color: "#374151",
  },
  statusDot: {
    width: 7,
    height: 7,
    borderRadius: "50%",
    display: "inline-block",
  },
  topSub: {
    fontSize: 12,
    color: "#6b7280",
  },
  topRight: {
    display: "flex",
    alignItems: "center",
    gap: 12,
  },
  compositeChip: {
    fontSize: 13,
    fontWeight: 700,
    border: "1px solid",
    borderRadius: 20,
    padding: "3px 12px",
  },
  tabBar: {
    display: "flex",
    gap: 2,
    padding: "8px 20px 0",
    background: "#111827",
    borderBottom: "1px solid #1f2937",
  },
  tabBtn: {
    background: "transparent",
    border: "none",
    color: "#6b7280",
    fontSize: 13,
    padding: "6px 14px",
    cursor: "pointer",
    borderRadius: "6px 6px 0 0",
    borderBottom: "2px solid transparent",
  },
  tabActive: {
    color: "#f9fafb",
    borderBottom: "2px solid #3b82f6",
    background: "#1a2234",
  },
  content: {
    padding: "16px 20px",
    maxWidth: 1400,
    margin: "0 auto",
  },
  placeholder: {
    background: "#111827",
    border: "1px dashed #1f2937",
    borderRadius: 12,
    padding: "40px 20px",
    textAlign: "center",
    marginBottom: 16,
  },
  placeholderText: {
    color: "#374151",
    fontSize: 13,
  },
}

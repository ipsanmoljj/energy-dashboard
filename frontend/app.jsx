import { useState, useEffect, useCallback } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine
} from "recharts";

const API = "http://localhost:8000/api";
const REFRESH = 30;

const fmt = (v, d = 2, fb = "N/A") =>
  v != null && !isNaN(v) ? Number(v).toFixed(d) : fb;

const scoreColor = s =>
  s >= 6 ? "#00d98b" : s >= 2 ? "#4ade80" : s >= -1 ? "#fbbf24" : s >= -4 ? "#f97316" : "#ef4444";

const sigColor = s => ({
  BULLISH:"#4ade80", BEARISH:"#ef4444", NEUTRAL:"#fbbf24",
  NORMAL:"#4ade80", ALERT:"#f97316", ALERT_HIGH:"#f97316",
  DIESEL_TIGHT:"#f97316", GASOLINE_TIGHT:"#fb923c",
  TIGHT:"#00d98b", INSUFFICIENT_DATA:"#334155",
}[s] || "#94a3b8");

// ── Shared components ──────────────────────────────────────────────────────────

function ChartTip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background:"#0d1a2a", border:"1px solid #1e3045",
      borderRadius:6, padding:"6px 10px" }}>
      <div style={{ color:"#3a5068", fontSize:9, fontFamily:"monospace",
        marginBottom:3 }}>{label}</div>
      {payload.map((p,i) => (
        <div key={i} style={{ color:p.color, fontSize:10, fontFamily:"monospace" }}>
          {p.name}: ${fmt(p.value)}
        </div>
      ))}
    </div>
  );
}

function MiniChart({ data, dataKey, color, height=80 }) {
  if (!data?.length) return (
    <div style={{ height, display:"flex", alignItems:"center",
      justifyContent:"center", color:"#334155", fontSize:10,
      fontFamily:"monospace" }}>NO HISTORY</div>
  );
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top:4, right:4, bottom:0, left:0 }}>
        <Line type="monotone" dataKey={dataKey} stroke={color}
          strokeWidth={1.5} dot={false} isAnimationActive={false} />
        <Tooltip content={<ChartTip />} />
      </LineChart>
    </ResponsiveContainer>
  );
}

function FullChart({ datasets, height=160 }) {
  const merged = {};
  datasets.forEach(({ data, key }) =>
    data?.forEach(d => {
      if (!merged[d.date]) merged[d.date] = { date: d.date?.slice(5) };
      merged[d.date][key] = d.close ?? d.value;
    })
  );
  const cd = Object.values(merged).sort((a,b) => a.date > b.date ? 1 : -1);
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={cd} margin={{ top:4, right:8, bottom:0, left:0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#0f1e30" />
        <XAxis dataKey="date" tick={{ fill:"#334155", fontSize:8, fontFamily:"monospace" }}
          tickLine={false} interval="preserveStartEnd" />
        <YAxis tick={{ fill:"#334155", fontSize:8, fontFamily:"monospace" }}
          tickLine={false} axisLine={false}
          tickFormatter={v => `$${Math.round(v)}`} width={40} />
        <Tooltip content={<ChartTip />} />
        {datasets.map(d => (
          <Line key={d.key} type="monotone" dataKey={d.key} name={d.label}
            stroke={d.color} strokeWidth={1.5} dot={false}
            strokeDasharray={d.dash ? "4 3" : "0"}
            isAnimationActive={false} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

function ScoreRing({ score, label, size=100 }) {
  const r = size*0.4, cx = size/2, cy = size/2;
  const circ = 2 * Math.PI * r;
  const dash = ((score + 10) / 20) * circ;
  return (
    <div style={{ display:"flex", flexDirection:"column",
      alignItems:"center", gap:6 }}>
      <svg width={size} height={size}>
        <circle cx={cx} cy={cy} r={r} fill="none" stroke="#0f1e30" strokeWidth={8}/>
        <circle cx={cx} cy={cy} r={r} fill="none" stroke={scoreColor(score)}
          strokeWidth={8} strokeDasharray={`${dash} ${circ-dash}`}
          strokeDashoffset={circ*0.25} strokeLinecap="round"
          style={{ transition:"stroke-dasharray 0.8s ease" }}/>
        <text x={cx} y={cy-4} textAnchor="middle" fill="#e2e8f0"
          fontSize={size*0.18} fontWeight={600} fontFamily="monospace">
          {score > 0 ? `+${fmt(score,1)}` : fmt(score,1)}
        </text>
        <text x={cx} y={cy+12} textAnchor="middle" fill="#334155"
          fontSize={size*0.08} fontFamily="monospace">/ 10</text>
      </svg>
      {label && (
        <span style={{ color:scoreColor(score), fontFamily:"monospace",
          fontSize:9, fontWeight:600, letterSpacing:"0.14em",
          textTransform:"uppercase" }}>
          {label.replace(/_/g," ")}
        </span>
      )}
    </div>
  );
}

function Stat({ label, value, unit, signal, color }) {
  return (
    <div style={{ display:"flex", justifyContent:"space-between",
      alignItems:"center", padding:"6px 0",
      borderBottom:"1px solid #0d1a2a" }}>
      <span style={{ color:"#4a6a88", fontSize:11 }}>{label}</span>
      <div style={{ display:"flex", alignItems:"center", gap:6 }}>
        <span style={{ color: color || "#c8d8e8",
          fontFamily:"monospace", fontSize:11, fontWeight:500 }}>
          {value}{unit && <span style={{ color:"#334155",
            fontWeight:400, marginLeft:2, fontSize:9 }}>{unit}</span>}
        </span>
        {signal && (
          <span style={{ background:`${sigColor(signal)}22`,
            color:sigColor(signal), fontSize:8, padding:"1px 5px",
            borderRadius:3, fontFamily:"monospace", fontWeight:600 }}>
            {signal.replace(/_/g," ")}
          </span>
        )}
      </div>
    </div>
  );
}

function Badge({ label, signal }) {
  return (
    <span style={{ background:`${sigColor(signal)}22`, color:sigColor(signal),
      fontSize:9, padding:"2px 7px", borderRadius:3,
      fontFamily:"monospace", fontWeight:600 }}>
      {label || signal?.replace(/_/g," ")}
    </span>
  );
}

function SectionTitle({ children }) {
  return (
    <div style={{ fontFamily:"monospace", fontSize:9, color:"#334155",
      textTransform:"uppercase", letterSpacing:"0.14em",
      marginBottom:10, paddingBottom:7, borderBottom:"1px solid #1a2d42" }}>
      {children}
    </div>
  );
}

function Panel({ children, style={} }) {
  return (
    <div style={{ background:"#0d1a2a", border:"1px solid #1a2d42",
      borderRadius:8, padding:"12px 14px", ...style }}>
      {children}
    </div>
  );
}

function buildSpreadH(h1, h2, fn) {
  if (!h1?.length || !h2?.length) return [];
  const m = {};
  h2.forEach(d => { m[d.date] = d.close; });
  return h1.filter(d => m[d.date] != null).map(d => ({
    date: d.date, close: fn(d.close, m[d.date])
  }));
}

function build321H(wtiH, rbobH, hoH) {
  if (!wtiH?.length || !rbobH?.length || !hoH?.length) return [];
  const wm = {}, rm = {};
  rbobH.forEach(d => { rm[d.date] = d.close; });
  wtiH.forEach(d => { wm[d.date] = d.close; });
  return hoH.filter(d => wm[d.date] && rm[d.date]).map(d => ({
    date: d.date,
    close: Math.round(((2*rm[d.date]) + d.close - (3*wm[d.date])) / 3 * 100) / 100,
  }));
}

// ── TABS ──────────────────────────────────────────────────────────────────────

const TABS = [
  { id:"overview",   label:"Overview",   icon:"ti-dashboard" },
  { id:"prices",     label:"Prices",     icon:"ti-chart-line" },
  { id:"spreads",    label:"Spreads",    icon:"ti-git-diff" },
  { id:"inventory",  label:"Inventory",  icon:"ti-database" },
  { id:"macro",      label:"Macro",      icon:"ti-world" },
  { id:"sentiment",  label:"Sentiment",  icon:"ti-mood-happy" },
  { id:"news",       label:"News",       icon:"ti-news" },
];

// ── Tab: Overview ─────────────────────────────────────────────────────────────
function TabOverview({ d }) {
  const comp = d?.composite?.composite || {};
  const layers = d?.composite?.layers || {};
  const alerts = d?.composite?.alerts || [];
  const contracts = d?.futures?.contracts || {};

  return (
    <div style={{ display:"grid", gridTemplateColumns:"220px 1fr", gap:14 }}>
      {/* Left — score + alerts */}
      <div style={{ display:"flex", flexDirection:"column", gap:12 }}>
        <Panel style={{ alignItems:"center", display:"flex",
          flexDirection:"column", gap:12, padding:"20px 14px" }}>
          <ScoreRing score={comp.score ?? 0} label={comp.label} size={120} />
          <div style={{ color:"#334155", fontSize:9, textAlign:"center",
            fontFamily:"system-ui", lineHeight:1.6, maxWidth:170 }}>
            {comp.interpretation?.substring(0,100)}
          </div>
        </Panel>

        {alerts.length > 0 && (
          <div style={{ background:"#1a0900", border:"1px solid #f9731633",
            borderRadius:7, padding:"8px 12px" }}>
            {alerts.map((a,i) => (
              <div key={i} style={{ color:"#fb923c", fontSize:9,
                fontFamily:"monospace", lineHeight:1.6 }}>⚠ {a}</div>
            ))}
          </div>
        )}

        {/* Quick prices */}
        <Panel>
          <SectionTitle>Live Prices</SectionTitle>
          {[
            { k:"brent",       l:"Brent ICE" },
            { k:"wti",         l:"WTI NYMEX" },
            { k:"rbob",        l:"RBOB" },
            { k:"heating_oil", l:"HO/ULSD" },
          ].map(({ k, l }) => {
            const c = contracts[k] || {};
            const up = c.change_pct > 0, dn = c.change_pct < 0;
            return (
              <Stat key={k} label={l}
                value={c.price_bbl != null ? `$${fmt(c.price_bbl)}` : "N/A"}
                color={up ? "#4ade80" : dn ? "#ef4444" : "#c8d8e8"} />
            );
          })}
        </Panel>
      </div>

      {/* Right — layers */}
      <Panel>
        <SectionTitle>Signal Layers — weighted NCI contributions</SectionTitle>
        <div style={{ display:"flex", flexDirection:"column", gap:14 }}>
          {Object.entries(layers).map(([key, layer]) => (
            <div key={key}>
              <div style={{ display:"flex", justifyContent:"space-between",
                alignItems:"center", marginBottom:4 }}>
                <div>
                  <span style={{ fontFamily:"monospace", fontSize:10,
                    color:"#4a6a88", textTransform:"uppercase",
                    letterSpacing:"0.1em" }}>{key}</span>
                  <span style={{ fontFamily:"monospace", fontSize:9,
                    color:"#1e3045", marginLeft:6 }}>
                    ({layer.weight_pct}%)
                  </span>
                </div>
                <div style={{ display:"flex", alignItems:"center", gap:8 }}>
                  <Badge signal={layer.label} />
                  <span style={{ fontFamily:"monospace", fontSize:13,
                    fontWeight:600, color:scoreColor(layer.score ?? 0) }}>
                    {(layer.score ?? 0) > 0
                      ? `+${fmt(layer.score,1)}`
                      : fmt(layer.score,1)}
                  </span>
                </div>
              </div>
              <div style={{ background:"#0a1520", borderRadius:2, height:5 }}>
                <div style={{
                  width:`${Math.abs(layer.score ?? 0) / 10 * 50}%`,
                  height:5, borderRadius:2,
                  background:scoreColor(layer.score ?? 0),
                  marginLeft: (layer.score ?? 0) >= 0 ? "50%" : `${50 - Math.abs(layer.score ?? 0)/10*50}%`,
                  transition:"width 0.6s",
                }} />
              </div>
              {/* Layer detail */}
              <div style={{ display:"grid",
                gridTemplateColumns:"repeat(auto-fit,minmax(160px,1fr))",
                gap:"4px 12px", marginTop:6 }}>
                {Object.entries(layer.details || {}).slice(0,4).map(([dk,dv]) => (
                  dv != null && (
                    <div key={dk} style={{ display:"flex",
                      justifyContent:"space-between",
                      fontSize:9, color:"#334155", fontFamily:"monospace" }}>
                      <span>{dk.replace(/_/g," ")}</span>
                      <span style={{ color:"#4a6a88" }}>
                        {typeof dv === "number" ? fmt(dv,1) : String(dv).substring(0,20)}
                      </span>
                    </div>
                  )
                ))}
              </div>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}

// ── Tab: Prices ───────────────────────────────────────────────────────────────
function TabPrices({ d }) {
  const contracts = d?.futures?.contracts || {};
  const brentH = contracts.brent?.history || [];
  const wtiH   = contracts.wti?.history   || [];
  const rbobH  = contracts.rbob?.history  || [];
  const hoH    = contracts.heating_oil?.history || [];

  const cards = [
    { key:"brent",       label:"Brent ICE",    unit:"usd_per_bbl",  color:"#00d98b" },
    { key:"wti",         label:"WTI NYMEX",    unit:"usd_per_bbl",  color:"#60a5fa" },
    { key:"rbob",        label:"RBOB Gasoline", unit:"usd_per_gal", color:"#fbbf24" },
    { key:"heating_oil", label:"HO / ULSD",    unit:"usd_per_gal",  color:"#f97316" },
  ];

  const histMap = { brent:brentH, wti:wtiH, rbob:rbobH, heating_oil:hoH };

  return (
    <div style={{ display:"flex", flexDirection:"column", gap:14 }}>
      {/* Price cards row */}
      <div style={{ display:"grid", gridTemplateColumns:"repeat(4,1fr)", gap:10 }}>
        {cards.map(({ key, label, color }) => {
          const c = contracts[key] || {};
          const up = c.change_pct > 0, dn = c.change_pct < 0;
          return (
            <Panel key={key}>
              <div style={{ color:"#334155", fontSize:8,
                fontFamily:"monospace", textTransform:"uppercase",
                letterSpacing:"0.1em", marginBottom:4 }}>
                {label}
                {c.estimated && (
                  <span style={{ color:"#f97316", marginLeft:4 }}>~est</span>
                )}
              </div>
              {c.price_bbl != null ? (
                <>
                  <div style={{ color:"#c8d8e8", fontSize:22,
                    fontWeight:600, fontFamily:"monospace" }}>
                    ${fmt(c.price_bbl)}
                    <span style={{ fontSize:8, color:"#334155",
                      marginLeft:3 }}>/bbl</span>
                  </div>
                  <div style={{ color:up?"#4ade80":dn?"#ef4444":"#94a3b8",
                    fontSize:10, fontFamily:"monospace", marginTop:3 }}>
                    {up?"▲":dn?"▼":"─"} {fmt(Math.abs(c.change_pct ?? 0), 2)}%
                  </div>
                  <div style={{ color:"#334155", fontSize:8,
                    fontFamily:"monospace", marginTop:2 }}>
                    {c.source || "yahoo"}
                  </div>
                </>
              ) : (
                <div style={{ color:"#334155", fontSize:12,
                  fontFamily:"monospace", marginTop:6 }}>UNAVAILABLE</div>
              )}
            </Panel>
          );
        })}
      </div>

      {/* Crude chart */}
      <Panel>
        <div style={{ display:"flex", justifyContent:"space-between",
          alignItems:"center", marginBottom:10 }}>
          <SectionTitle>Crude Oil — 30 day history</SectionTitle>
          <div style={{ display:"flex", gap:12 }}>
            {[{l:"Brent",c:"#00d98b"},{l:"WTI",c:"#60a5fa"}].map(x => (
              <div key={x.l} style={{ display:"flex", alignItems:"center", gap:4 }}>
                <div style={{ width:14, height:2, background:x.c, borderRadius:1 }} />
                <span style={{ fontSize:9, color:"#334155",
                  fontFamily:"monospace" }}>{x.l}</span>
              </div>
            ))}
          </div>
        </div>
        <FullChart height={160} datasets={[
          { key:"brent", label:"Brent", color:"#00d98b", data:brentH },
          { key:"wti",   label:"WTI",   color:"#60a5fa", data:wtiH },
        ]} />
      </Panel>

      {/* Products chart */}
      <Panel>
        <div style={{ display:"flex", justifyContent:"space-between",
          alignItems:"center", marginBottom:10 }}>
          <SectionTitle>Refined Products — 30 day history</SectionTitle>
          <div style={{ display:"flex", gap:12 }}>
            {[{l:"RBOB",c:"#fbbf24"},{l:"HO/ULSD",c:"#f97316"}].map(x => (
              <div key={x.l} style={{ display:"flex", alignItems:"center", gap:4 }}>
                <div style={{ width:14, height:2, background:x.c, borderRadius:1 }} />
                <span style={{ fontSize:9, color:"#334155",
                  fontFamily:"monospace" }}>{x.l}</span>
              </div>
            ))}
          </div>
        </div>
        <FullChart height={160} datasets={[
          { key:"rbob", label:"RBOB", color:"#fbbf24", data:rbobH },
          { key:"ho",   label:"HO",   color:"#f97316", dash:true, data:hoH },
        ]} />
      </Panel>
    </div>
  );
}

// ── Tab: Spreads ──────────────────────────────────────────────────────────────
function TabSpreads({ d }) {
  const crack = d?.crack || {};
  const contracts = d?.futures?.contracts || {};
  const spreads = crack.spreads || {};
  const derived = d?.futures?.derived || {};

  const brentH = contracts.brent?.history || [];
  const wtiH   = contracts.wti?.history   || [];
  const rbobH  = contracts.rbob?.history  || [];
  const hoH    = contracts.heating_oil?.history || [];

  const crack321H = build321H(wtiH, rbobH, hoH);
  const bwtiH     = buildSpreadH(brentH, wtiH, (b,w) => Math.round((b-w)*100)/100);
  const hoRbobH   = buildSpreadH(hoH, rbobH, (h,r) => Math.round((h-r)*100)/100);

  const spreadCards = [
    { key:"crack_321",      label:"3-2-1 Crack",        color:"#00d98b", hist:crack321H },
    { key:"gasoline_crack", label:"Gasoline Crack",      color:"#fbbf24", hist:[] },
    { key:"brent_wti",      label:"Brent − WTI",         color:"#60a5fa", hist:bwtiH },
    { key:"ho_rbob_spread", label:"HO − RBOB",           color:"#f97316", hist:hoRbobH },
    { key:"ho_crack",       label:"HO Crack vs Brent",   color:"#a78bfa", hist:[] },
  ];

  return (
    <div style={{ display:"flex", flexDirection:"column", gap:14 }}>
      {/* NCI crack summary */}
      <Panel>
        <div style={{ display:"flex", alignItems:"center",
          justifyContent:"space-between" }}>
          <div>
            <SectionTitle>Crack Spread Engine</SectionTitle>
            <div style={{ color:"#c8d8e8", fontSize:13,
              fontFamily:"monospace" }}>
              NCI Crack: <span style={{ color:scoreColor(crack?.nci_crack?.score??0),
                fontSize:18, fontWeight:600 }}>
                {(crack?.nci_crack?.score??0) > 0
                  ? `+${fmt(crack?.nci_crack?.score,1)}`
                  : fmt(crack?.nci_crack?.score,1)}
              </span>
              <span style={{ fontSize:10, color:"#334155",
                marginLeft:6 }}>[{crack?.nci_crack?.label}]</span>
            </div>
            <div style={{ color:"#334155", fontSize:9, marginTop:4,
              fontFamily:"system-ui" }}>
              {crack?.nci_crack?.interpretation?.substring(0,120)}
            </div>
          </div>
          <div style={{ textAlign:"right" }}>
            <div style={{ color:"#4a6a88", fontSize:8,
              fontFamily:"monospace", marginBottom:3 }}>SEASON</div>
            <div style={{ color:"#00d98b", fontFamily:"monospace",
              fontSize:11, fontWeight:600 }}>
              {crack?.seasonal?.phase?.replace(/_/g," ")}
            </div>
            <div style={{ color:"#334155", fontFamily:"monospace",
              fontSize:8, marginTop:2 }}>
              {crack?.seasonal?.dominant_product} dominant
            </div>
          </div>
        </div>
      </Panel>

      {/* Spread cards grid */}
      <div style={{ display:"grid",
        gridTemplateColumns:"repeat(auto-fit,minmax(240px,1fr))",
        gap:10 }}>
        {spreadCards.map(({ key, label, color, hist }) => {
          const sp = spreads[key] || {};
          return (
            <Panel key={key}>
              <div style={{ display:"flex", justifyContent:"space-between",
                alignItems:"flex-start", marginBottom:8 }}>
                <div>
                  <div style={{ color:"#334155", fontSize:8,
                    fontFamily:"monospace", textTransform:"uppercase",
                    letterSpacing:"0.1em", marginBottom:3 }}>{label}</div>
                  <div style={{ color:color, fontSize:20,
                    fontFamily:"monospace", fontWeight:600 }}>
                    {sp.value_bbl != null
                      ? `$${fmt(sp.value_bbl)}`
                      : "N/A"}
                    <span style={{ fontSize:8, color:"#334155",
                      marginLeft:2 }}>/bbl</span>
                  </div>
                </div>
                <Badge signal={sp.signal} />
              </div>
              {hist.length > 0 && (
                <MiniChart data={hist} dataKey="close" color={color} height={70} />
              )}
              {sp.note && (
                <div style={{ color:"#334155", fontSize:8,
                  fontFamily:"system-ui", marginTop:6,
                  lineHeight:1.5 }}>
                  {sp.note.substring(0,80)}{sp.note.length > 80 ? "…" : ""}
                </div>
              )}
            </Panel>
          );
        })}
      </div>

      {/* Forward curve */}
      <Panel>
        <SectionTitle>Forward Curve Shape (proxy)</SectionTitle>
        <div style={{ display:"grid", gridTemplateColumns:"180px 1fr", gap:14 }}>
          <div style={{ textAlign:"center", padding:"10px 0" }}>
            <div style={{ fontSize:20, fontFamily:"monospace", fontWeight:600,
              color:scoreColor(crack?.forward_curve?.score??0), marginBottom:6 }}>
              {crack?.forward_curve?.estimated_shape || "N/A"}
            </div>
            <div style={{ color:"#334155", fontSize:9, lineHeight:1.5 }}>
              {crack?.forward_curve?.note}
            </div>
          </div>
          <div>
            {crack?.forward_curve?.signals?.map((s,i) => (
              <div key={i} style={{ color:"#4a6a88", fontSize:9,
                fontFamily:"system-ui", padding:"3px 0",
                borderBottom:"1px solid #0a1520" }}>
                • {s}
              </div>
            ))}
          </div>
        </div>
      </Panel>
    </div>
  );
}

// ── Tab: Inventory ────────────────────────────────────────────────────────────
function TabInventory({ d }) {
  const inv = d?.inventory || {};
  const stocks  = inv.stocks  || {};
  const vs5yr   = inv.vs_5yr  || {};
  const dc      = inv.days_cover || {};
  const flows   = inv.production_flows || {};
  const wow     = inv.wow_changes || {};
  const scores  = inv.component_scores || {};

  const scoreCards = [
    { label:"Days of Cover",   score:scores.days_cover,     val:`${fmt(dc.current,1)} days`,  note:`5yr: ${fmt(dc.five_yr_avg,1)} | crit: 54` },
    { label:"Cushing",         score:scores.cushing,        val:`${fmt(stocks.cushing_mmbbls,1)} mmbbls`, note:`${fmt(stocks.cushing_util_pct,1)}% capacity` },
    { label:"Distillate",      score:scores.distillate_5yr, val:`${fmt(vs5yr?.distillate?.deviation_pct,1)}% vs 5yr`, note:`${fmt(vs5yr?.distillate?.current_mmbbls,1)} mmbbls` },
    { label:"Gasoline",        score:scores.gasoline_5yr,   val:`${fmt(vs5yr?.gasoline?.deviation_pct,1)}% vs 5yr`,   note:`${fmt(vs5yr?.gasoline?.current_mmbbls,1)} mmbbls` },
    { label:"WoW Surprise",    score:scores.wow_surprise,   val:`${fmt(wow?.total_crude?.surprise,2)} mmbbls`, note:`act: ${fmt(wow?.total_crude?.actual,2)} vs exp: ${fmt(wow?.total_crude?.expected,2)}` },
    { label:"Refinery Util",   score:scores.refinery_util,  val:`${fmt(flows.refinery_util_pct,1)}%`, note:`${fmt(flows.crude_production_mbd,2)} mbd prod` },
  ];

  return (
    <div style={{ display:"flex", flexDirection:"column", gap:14 }}>
      {/* NCI bar */}
      <Panel>
        <div style={{ display:"flex", alignItems:"center",
          justifyContent:"space-between" }}>
          <div>
            <SectionTitle>Inventory Signal</SectionTitle>
            <div style={{ color:"#c8d8e8", fontSize:13, fontFamily:"monospace" }}>
              NCI Inventory: <span style={{ color:scoreColor(inv?.nci_inventory?.score??0),
                fontSize:18, fontWeight:600 }}>
                {(inv?.nci_inventory?.score??0)>0
                  ? `+${fmt(inv?.nci_inventory?.score,1)}`
                  : fmt(inv?.nci_inventory?.score,1)}
              </span>
              <span style={{ fontSize:10, color:"#334155", marginLeft:6 }}>
                [{inv?.nci_inventory?.label}]
              </span>
            </div>
          </div>
          <div style={{ display:"flex", gap:8 }}>
            <Badge signal={inv?.nci_inventory?.crude_direction} />
          </div>
        </div>
      </Panel>

      {/* Score cards */}
      <div style={{ display:"grid",
        gridTemplateColumns:"repeat(3,1fr)", gap:10 }}>
        {scoreCards.map(({ label, score, val, note }) => (
          <Panel key={label}>
            <div style={{ color:"#334155", fontSize:8,
              fontFamily:"monospace", textTransform:"uppercase",
              letterSpacing:"0.1em", marginBottom:4 }}>{label}</div>
            <div style={{ display:"flex", justifyContent:"space-between",
              alignItems:"flex-end" }}>
              <div>
                <div style={{ color:"#c8d8e8", fontSize:17,
                  fontFamily:"monospace", fontWeight:600 }}>{val}</div>
                <div style={{ color:"#334155", fontSize:8,
                  fontFamily:"system-ui", marginTop:2 }}>{note}</div>
              </div>
              <div style={{ display:"flex", flexDirection:"column",
                alignItems:"flex-end", gap:4 }}>
                <span style={{ fontFamily:"monospace", fontSize:14,
                  fontWeight:600, color:scoreColor(score??0) }}>
                  {(score??0)>0 ? `+${score}` : score}
                </span>
                <div style={{ width:36, height:36 }}>
                  <ScoreRing score={(score??0)*2} size={36} />
                </div>
              </div>
            </div>
          </Panel>
        ))}
      </div>

      {/* Detailed stats */}
      <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:10 }}>
        <Panel>
          <SectionTitle>Stock Levels</SectionTitle>
          <Stat label="Total Crude" value={fmt(stocks.total_crude_mmbbls,1)} unit="mmbbls" />
          <Stat label="Cushing" value={fmt(stocks.cushing_mmbbls,1)} unit="mmbbls"
            signal={vs5yr?.cushing?.signal} />
          <Stat label="Gasoline" value={fmt(vs5yr?.gasoline?.current_mmbbls,1)} unit="mmbbls"
            signal={vs5yr?.gasoline?.signal} />
          <Stat label="Distillate" value={fmt(vs5yr?.distillate?.current_mmbbls,1)} unit="mmbbls"
            signal={vs5yr?.distillate?.signal} />
          <Stat label="Days Cover" value={fmt(dc.current,1)} unit="days"
            color={dc.current < 54 ? "#00d98b" : "#c8d8e8"} />
        </Panel>
        <Panel>
          <SectionTitle>Production & Flows</SectionTitle>
          <Stat label="Crude Production" value={fmt(flows.crude_production_mbd,3)} unit="mbd" />
          <Stat label="Refinery Util" value={fmt(flows.refinery_util_pct,1)} unit="%" />
          <Stat label="Crude Imports" value={fmt(flows.crude_imports_mbd,3)} unit="mbd" />
          <Stat label="Crude Exports" value={fmt(flows.crude_exports_mbd,3)} unit="mbd" />
          <Stat label="Gasoline Demand" value={fmt(flows.gasoline_demand_mbd,3)} unit="mbd" />
          <Stat label="Distillate Demand" value={fmt(flows.distillate_demand_mbd,3)} unit="mbd" />
        </Panel>
      </div>
    </div>
  );
}

// ── Tab: Macro ────────────────────────────────────────────────────────────────
function TabMacro({ d }) {
  const fred    = d?.fred    || {};
  const gie     = d?.gie     || {};
  const weather = d?.weather || {};
  const series  = fred.series || {};
  const gieRegs = gie.regions || {};
  const wComp   = weather.composite || {};

  return (
    <div style={{ display:"flex", flexDirection:"column", gap:14 }}>
      <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr 1fr", gap:10 }}>
        {/* Macro rates */}
        <Panel>
          <SectionTitle>Macro Rates</SectionTitle>
          {[
            { k:"dxy_broad",    l:"DXY Dollar Index" },
            { k:"sofr",         l:"SOFR" },
            { k:"fed_funds",    l:"Fed Funds Rate" },
            { k:"us_10y_yield", l:"10Y Treasury" },
          ].map(({ k, l }) => {
            const s = series[k] || {};
            return (
              <Stat key={k} label={l}
                value={fmt(s.latest, 2)} unit="%"
                signal={s.wow < 0 ? "BULLISH" : s.wow > 0 ? "BEARISH" : "NEUTRAL"} />
            );
          })}
          <div style={{ marginTop:8, padding:"8px 10px",
            background:"#0a1520", borderRadius:5 }}>
            <div style={{ color:"#334155", fontSize:8, fontFamily:"monospace",
              marginBottom:4 }}>STORAGE CARRY COST</div>
            <div style={{ color:"#c8d8e8", fontSize:14,
              fontFamily:"monospace", fontWeight:600 }}>
              ${fmt(fred.derived?.storage_carry?.total_carry_per_bbl_mo, 2)}
              <span style={{ fontSize:8, color:"#334155", marginLeft:2 }}>/bbl/mo</span>
            </div>
          </div>
        </Panel>

        {/* EU Gas Storage */}
        <Panel>
          <SectionTitle>EU Gas Storage (GIE AGSI+)</SectionTitle>
          {Object.entries(gieRegs).map(([k,v]) => (
            <div key={k} style={{ marginBottom:10 }}>
              <div style={{ display:"flex", justifyContent:"space-between",
                alignItems:"center", marginBottom:3 }}>
                <span style={{ color:"#4a6a88", fontSize:10, textTransform:"capitalize" }}>
                  {k}
                </span>
                <div style={{ display:"flex", alignItems:"center", gap:6 }}>
                  <span style={{ fontFamily:"monospace", fontSize:11,
                    fontWeight:500, color:"#c8d8e8" }}>
                    {fmt(v.fill_pct,1)}%
                  </span>
                  <Badge signal={v.signal} />
                </div>
              </div>
              <div style={{ background:"#0a1520", borderRadius:2, height:4 }}>
                <div style={{ width:`${v.fill_pct||0}%`, height:4,
                  borderRadius:2, background:sigColor(v.signal),
                  transition:"width 0.6s" }} />
              </div>
            </div>
          ))}
          <div style={{ marginTop:6 }}>
            <Stat label="Composite" value={gie.composite?.signal || "N/A"} />
          </div>
        </Panel>

        {/* Weather */}
        <Panel>
          <SectionTitle>Weather Demand (HDD/CDD)</SectionTitle>
          <div style={{ marginBottom:10 }}>
            <Stat label="Composite Signal" value={wComp.signal || "N/A"}
              signal={wComp.signal} />
            <Stat label="Weighted CDD 7d" value={fmt(wComp.weighted_cdd_7d,1)} />
            <Stat label="Weighted HDD 7d" value={fmt(wComp.weighted_hdd_7d,1)} />
          </div>
          <SectionTitle>By Location</SectionTitle>
          {Object.entries(weather.locations || {}).map(([k,v]) => (
            <Stat key={k}
              label={k.replace(/_/g," ")}
              value={`${fmt(v.cdd_7d_forecast,0)}/${fmt(v.hdd_7d_forecast,0)}`}
              unit="CDD/HDD"
              signal={v.signal} />
          ))}
        </Panel>
      </div>
    </div>
  );
}

// ── Tab: Sentiment ────────────────────────────────────────────────────────────
function TabSentiment({ d }) {
  const cftc     = d?.cftc     || {};
  const cftcC    = cftc.contracts || {};
  const comp     = cftc.composite || {};

  return (
    <div style={{ display:"flex", flexDirection:"column", gap:14 }}>
      <Panel>
        <div style={{ display:"flex", justifyContent:"space-between",
          alignItems:"center" }}>
          <div>
            <SectionTitle>CFTC COT Positioning</SectionTitle>
            <div style={{ color:"#334155", fontSize:9,
              fontFamily:"monospace" }}>
              Report date: {cftc.report_date || "N/A"}
            </div>
          </div>
          <Badge signal={comp.signal} />
        </div>
      </Panel>

      <div style={{ display:"grid",
        gridTemplateColumns:"repeat(auto-fit,minmax(240px,1fr))",
        gap:10 }}>
        {Object.entries(cftcC).map(([key, c]) => {
          const pct = c?.net_pct_of_oi ?? 0;
          const barW = Math.min(Math.abs(pct) / 30 * 50, 50);
          return (
            <Panel key={key}>
              <div style={{ color:"#334155", fontSize:8,
                fontFamily:"monospace", textTransform:"uppercase",
                letterSpacing:"0.1em", marginBottom:6 }}>
                {key.replace(/_/g," ")}
              </div>
              <div style={{ display:"flex", justifyContent:"space-between",
                alignItems:"center", marginBottom:8 }}>
                <div>
                  <span style={{ fontFamily:"monospace", fontSize:16,
                    fontWeight:600, color:sigColor(c?.signal) }}>
                    {fmt(pct,1)}%
                  </span>
                  <span style={{ fontSize:8, color:"#334155",
                    marginLeft:3 }}>of OI</span>
                </div>
                <Badge signal={c?.signal} />
              </div>
              {/* Net position bar */}
              <div style={{ background:"#0a1520", borderRadius:2, height:5,
                position:"relative" }}>
                <div style={{ position:"absolute", left:"50%",
                  width:1, height:5, background:"#1e3045" }} />
                <div style={{
                  position:"absolute",
                  left: pct >= 0 ? "50%" : `${50-barW}%`,
                  width:`${barW}%`, height:5, borderRadius:2,
                  background:pct >= 0 ? "#4ade80" : "#ef4444",
                }} />
              </div>
              <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr",
                gap:"4px 10px", marginTop:8 }}>
                <Stat label="MM Net Lots"
                  value={c?.mm_net_lots != null
                    ? c.mm_net_lots.toLocaleString() : "N/A"} />
                <Stat label="Open Interest"
                  value={c?.open_interest != null
                    ? Math.round(c.open_interest/1000) + "k" : "N/A"} />
              </div>
              {c?.signal_note && (
                <div style={{ color:"#334155", fontSize:8,
                  fontFamily:"system-ui", marginTop:6, lineHeight:1.5 }}>
                  {c.signal_note.substring(0,80)}
                </div>
              )}
            </Panel>
          );
        })}
      </div>

      {/* Crowding warnings */}
      {(comp.crowded_longs?.length > 0 || comp.crowded_shorts?.length > 0) && (
        <Panel>
          <SectionTitle>Crowding Warnings</SectionTitle>
          {comp.crowded_longs?.length > 0 && (
            <div style={{ color:"#f97316", fontSize:10,
              fontFamily:"monospace", padding:"4px 0" }}>
              ⚠ Crowded longs: {comp.crowded_longs.join(", ")} — mean-reversion risk
            </div>
          )}
          {comp.crowded_shorts?.length > 0 && (
            <div style={{ color:"#4ade80", fontSize:10,
              fontFamily:"monospace", padding:"4px 0" }}>
              ↑ Crowded shorts: {comp.crowded_shorts.join(", ")} — short squeeze risk
            </div>
          )}
        </Panel>
      )}
    </div>
  );
}

// ── Tab: News ────────────────────────────────────────────────────────────────
function TabNews({ d }) {
  const news     = d?.news      || {};
  const score    = news?.news_score || {};
  const summary  = news?.summary   || {};
  const bullish  = news?.top_bullish  || [];
  const bearish  = news?.top_bearish  || [];
  const geoAlerts= news?.geo_risk_alerts || [];
  const all      = news?.all_headlines   || [];

  const scoreColor = s =>
    s >= 3 ? "#4ade80" : s >= 1 ? "#86efac" : s <= -3 ? "#ef4444" : s <= -1 ? "#f97316" : "#fbbf24";

  return (
    <div style={{ display:"flex", flexDirection:"column", gap:14 }}>

      {/* Score + summary bar */}
      <div style={{ display:"grid", gridTemplateColumns:"200px 1fr", gap:14 }}>
        <Panel style={{ display:"flex", flexDirection:"column",
          alignItems:"center", justifyContent:"center", gap:10, padding:"18px" }}>
          <div style={{ color:"#334155", fontSize:8, fontFamily:"monospace",
            textTransform:"uppercase", letterSpacing:"0.14em" }}>
            News Score
          </div>
          <div style={{ fontSize:42, fontFamily:"monospace", fontWeight:600,
            color: scoreColor(score.score ?? 0) }}>
            {(score.score ?? 0) > 0
              ? `+${fmt(score.score, 1)}`
              : fmt(score.score, 1)}
          </div>
          <Badge signal={score.label} />
          <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr 1fr",
            gap:6, width:"100%", marginTop:4 }}>
            {[
              { l:"Bullish", v:summary.bullish_count, c:"#4ade80" },
              { l:"Bearish", v:summary.bearish_count, c:"#ef4444" },
              { l:"Geo Alerts", v:summary.geo_alerts, c:"#f97316" },
            ].map(x => (
              <div key={x.l} style={{ textAlign:"center",
                background:"#0a1520", borderRadius:5, padding:"6px 4px" }}>
                <div style={{ color:x.c, fontFamily:"monospace",
                  fontSize:16, fontWeight:600 }}>{x.v ?? 0}</div>
                <div style={{ color:"#334155", fontSize:7 }}>{x.l}</div>
              </div>
            ))}
          </div>
        </Panel>

        {/* Geo risk alerts */}
        <Panel>
          <SectionTitle>Geopolitical Risk Alerts</SectionTitle>
          {geoAlerts.length === 0 ? (
            <div style={{ color:"#334155", fontSize:11,
              fontFamily:"monospace", padding:"20px 0", textAlign:"center" }}>
              No active geopolitical alerts
            </div>
          ) : (
            geoAlerts.map((g, i) => (
              <div key={i} style={{
                background:"#1a0900", border:"1px solid #f9731644",
                borderRadius:6, padding:"10px 12px", marginBottom:8,
              }}>
                <div style={{ display:"flex", justifyContent:"space-between",
                  alignItems:"flex-start", marginBottom:5 }}>
                  <span style={{ color:"#fb923c", fontSize:10,
                    fontFamily:"monospace", flex:1, lineHeight:1.5 }}>
                    ⚠ {g.headline}
                  </span>
                  <span style={{ color:"#f97316", fontFamily:"monospace",
                    fontSize:14, fontWeight:600, marginLeft:12,
                    whiteSpace:"nowrap" }}>
                    +${g.geo_risk?.implied_premium_bbl}/bbl
                  </span>
                </div>
                <div style={{ display:"flex", gap:10 }}>
                  <span style={{ color:"#334155", fontSize:8,
                    fontFamily:"monospace" }}>
                    Risk score: {g.geo_risk?.composite_score}
                  </span>
                  <span style={{ color:"#334155", fontSize:8,
                    fontFamily:"monospace" }}>
                    Spare cap used: {g.geo_risk?.spare_capacity_mbd} mbd
                  </span>
                </div>
              </div>
            ))
          )}
        </Panel>
      </div>

      {/* Bullish + Bearish headlines */}
      <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:14 }}>
        <Panel>
          <SectionTitle>Top Bullish Headlines</SectionTitle>
          {bullish.length === 0 ? (
            <div style={{ color:"#334155", fontSize:10,
              fontFamily:"monospace", padding:"10px 0" }}>
              No bullish headlines in window
            </div>
          ) : bullish.map((h, i) => (
            <div key={i} style={{
              borderBottom:"1px solid #0a1520", padding:"8px 0",
            }}>
              <div style={{ display:"flex", justifyContent:"space-between",
                alignItems:"flex-start", gap:8 }}>
                <div style={{ flex:1 }}>
                  <div style={{ color:"#c8d8e8", fontSize:11,
                    lineHeight:1.5, marginBottom:3 }}>
                    {h.headline}
                  </div>
                  <div style={{ display:"flex", gap:8 }}>
                    <span style={{ color:"#334155", fontSize:8,
                      fontFamily:"monospace" }}>{h.source}</span>
                    <span style={{ color:"#334155", fontSize:8,
                      fontFamily:"monospace" }}>{h.signal_type}</span>
                  </div>
                </div>
                <span style={{ color:"#4ade80", fontFamily:"monospace",
                  fontSize:13, fontWeight:600, whiteSpace:"nowrap" }}>
                  +{fmt(h.final_score, 1)}
                </span>
              </div>
            </div>
          ))}
        </Panel>

        <Panel>
          <SectionTitle>Top Bearish Headlines</SectionTitle>
          {bearish.length === 0 ? (
            <div style={{ color:"#334155", fontSize:10,
              fontFamily:"monospace", padding:"10px 0" }}>
              No bearish headlines in window
            </div>
          ) : bearish.map((h, i) => (
            <div key={i} style={{
              borderBottom:"1px solid #0a1520", padding:"8px 0",
            }}>
              <div style={{ display:"flex", justifyContent:"space-between",
                alignItems:"flex-start", gap:8 }}>
                <div style={{ flex:1 }}>
                  <div style={{ color:"#c8d8e8", fontSize:11,
                    lineHeight:1.5, marginBottom:3 }}>
                    {h.headline}
                  </div>
                  <div style={{ display:"flex", gap:8 }}>
                    <span style={{ color:"#334155", fontSize:8,
                      fontFamily:"monospace" }}>{h.source}</span>
                    <span style={{ color:"#334155", fontSize:8,
                      fontFamily:"monospace" }}>{h.signal_type}</span>
                  </div>
                </div>
                <span style={{ color:"#ef4444", fontFamily:"monospace",
                  fontSize:13, fontWeight:600, whiteSpace:"nowrap" }}>
                  {fmt(h.final_score, 1)}
                </span>
              </div>
            </div>
          ))}
        </Panel>
      </div>

      {/* Live news feed panel */}
      <Panel>
        <SectionTitle>
          Live News Feed — {summary.oil_relevant ?? 0} oil-relevant headlines
          <span style={{ color:"#334155", marginLeft:8, fontSize:8 }}>
            (last {news.lookback_hours ?? 4}h · {summary.total_fetched ?? 0} total fetched)
          </span>
        </SectionTitle>
        <div style={{ maxHeight:400, overflowY:"auto" }}>
          {all.length === 0 ? (
            <div style={{ color:"#334155", fontSize:11,
              fontFamily:"monospace", padding:"20px 0", textAlign:"center" }}>
              No headlines loaded — run news_fetcher.py
            </div>
          ) : all.map((h, i) => (
            <div key={i} style={{
              display:"flex", alignItems:"flex-start", gap:10,
              padding:"7px 0", borderBottom:"1px solid #0a1520",
            }}>
              {/* Direction indicator */}
              <div style={{
                width:3, borderRadius:1, alignSelf:"stretch", flexShrink:0,
                background: h.direction === "BULLISH" ? "#4ade80"
                          : h.direction === "BEARISH" ? "#ef4444" : "#334155",
              }} />
              <div style={{ flex:1, minWidth:0 }}>
                <div style={{ color:"#c8d8e8", fontSize:11,
                  lineHeight:1.5 }}>
                  {h.headline}
                </div>
                <div style={{ display:"flex", gap:8, marginTop:3,
                  flexWrap:"wrap" }}>
                  <span style={{ color:"#334155", fontSize:8,
                    fontFamily:"monospace" }}>{h.source}</span>
                  {h.published && (
                    <span style={{ color:"#334155", fontSize:8,
                      fontFamily:"monospace" }}>
                      {new Date(h.published).toLocaleTimeString()}
                    </span>
                  )}
                  <span style={{
                    background:`${h.direction === "BULLISH" ? "#4ade80"
                      : h.direction === "BEARISH" ? "#ef4444" : "#334155"}22`,
                    color: h.direction === "BULLISH" ? "#4ade80"
                         : h.direction === "BEARISH" ? "#ef4444" : "#475569",
                    fontSize:7, padding:"1px 4px", borderRadius:2,
                    fontFamily:"monospace",
                  }}>{h.signal_type}</span>
                  {h.geo_risk && (
                    <span style={{ background:"#f9731622",
                      color:"#f97316", fontSize:7,
                      padding:"1px 4px", borderRadius:2,
                      fontFamily:"monospace" }}>
                      GEO +${h.geo_risk.implied_premium_bbl}/bbl
                    </span>
                  )}
                </div>
              </div>
              <span style={{
                fontFamily:"monospace", fontSize:11, fontWeight:600,
                color: h.direction === "BULLISH" ? "#4ade80"
                     : h.direction === "BEARISH" ? "#ef4444" : "#475569",
                whiteSpace:"nowrap",
              }}>
                {h.final_score > 0 ? `+${fmt(h.final_score,1)}`
                  : fmt(h.final_score,1)}
              </span>
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}

// ── Main App ──────────────────────────────────────────────────────────────────
export default function App() {
  const [data,       setData]    = useState(null);
  const [loading,    setLoading] = useState(true);
  const [error,      setError]   = useState(null);
  const [lastUpdate, setLast]    = useState(null);
  const [tick,       setTick]    = useState(REFRESH);
  const [activeTab,  setTab]     = useState("overview");

  const fetchData = useCallback(async () => {
    try {
      const r = await fetch(`${API}/all`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setData(await r.json());
      setLast(new Date());
      setError(null);
    } catch(e) { setError(e.message); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    fetchData();
    const t = setInterval(fetchData, REFRESH * 1000);
    return () => clearInterval(t);
  }, [fetchData]);

  useEffect(() => {
    setTick(REFRESH);
    const t = setInterval(() => setTick(p => p > 0 ? p-1 : REFRESH), 1000);
    return () => clearInterval(t);
  }, [lastUpdate]);

  const comp = data?.composite?.composite || {};

  return (
    <div style={{ background:"#060b14", minHeight:"100vh",
      color:"#c8d8e8", fontFamily:"system-ui,sans-serif" }}>

      {/* Top bar */}
      <div style={{ background:"#0b1424", borderBottom:"1px solid #1a2535",
        padding:"10px 22px", display:"flex", justifyContent:"space-between",
        alignItems:"center", position:"sticky", top:0, zIndex:100 }}>
        <div style={{ display:"flex", alignItems:"center", gap:10 }}>
          <div style={{ width:7, height:7, borderRadius:"50%",
            background: error?"#ef4444":"#00d98b" }} />
          <span style={{ fontFamily:"monospace", fontSize:12, fontWeight:600,
            letterSpacing:"0.18em", color:"#c8d8e8" }}>
            ENERGY MARKETS DASHBOARD
          </span>
        </div>
        <div style={{ display:"flex", alignItems:"center", gap:16 }}>
          {!loading && comp.score != null && (
            <span style={{ fontFamily:"monospace", fontSize:11, fontWeight:600,
              color:scoreColor(comp.score) }}>
              NCI {comp.score > 0 ? `+${fmt(comp.score,1)}` : fmt(comp.score,1)} [{comp.label?.replace(/_/g," ")}]
            </span>
          )}
          {error && (
            <span style={{ color:"#ef4444", fontSize:9,
              fontFamily:"monospace" }}>{error}</span>
          )}
          <span style={{ color:"#334155", fontSize:9,
            fontFamily:"monospace" }}>↻ {tick}s</span>
          {lastUpdate && (
            <span style={{ color:"#334155", fontSize:9,
              fontFamily:"monospace" }}>
              {lastUpdate.toLocaleTimeString()}
            </span>
          )}
        </div>
      </div>

      {/* Tab bar */}
      <div style={{ background:"#0b1424", borderBottom:"1px solid #1a2535",
        padding:"0 22px", display:"flex", gap:0 }}>
        {TABS.map(tab => (
          <button key={tab.id} onClick={() => setTab(tab.id)}
            style={{ background:"none", border:"none",
              borderBottom: activeTab === tab.id
                ? "2px solid #00d98b" : "2px solid transparent",
              padding:"10px 16px", cursor:"pointer",
              fontFamily:"monospace", fontSize:10,
              color: activeTab === tab.id ? "#00d98b" : "#334155",
              letterSpacing:"0.12em", textTransform:"uppercase",
              transition:"all 0.15s", display:"flex",
              alignItems:"center", gap:6 }}>
            <i className={`ti ${tab.icon}`}
              style={{ fontSize:14 }} aria-hidden="true" />
            {tab.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div style={{ padding:"16px 22px", maxWidth:1400, margin:"0 auto" }}>
        {loading ? (
          <div style={{ display:"flex", alignItems:"center",
            justifyContent:"center", height:300, color:"#00d98b",
            fontFamily:"monospace", fontSize:12, letterSpacing:"0.2em" }}>
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
            {activeTab === "news"       && <TabNews      d={data} />}
          </>
        )}
      </div>

      <div style={{ textAlign:"center", padding:"10px 0",
        color:"#1a2535", fontSize:8, fontFamily:"monospace",
        borderTop:"1px solid #0f1e30" }}>
        EIA · STOOQ · YAHOO FINANCE · FRED · GIE AGSI+ · OPEN-METEO · CFTC
        {comp.score >= 7 && " · ⚡ STRONG BUY ACTIVE"}
      </div>
    </div>
  );
}

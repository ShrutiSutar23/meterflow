import { useState, useEffect } from "react";
import { billingAPI } from "../services/axios";
import useAuthStore from "../store/authStore";

function Row({ label, value, big = false, indent = false }) {
  return (
    <div style={{ display:"flex", justifyContent:"space-between", padding:"9px 0", borderBottom:"1px solid #0d1e30", paddingLeft: indent?16:0 }}>
      <span style={{ fontSize:13, color: indent?"#556677":"#aaccee" }}>{label}</span>
      <span style={{ fontSize: big?18:14, fontWeight: big?700:500, color: big?"#00ff88":"#e0e8f0", fontFamily:"monospace" }}>{value}</span>
    </div>
  );
}

function UsageBar({ used, limit }) {
  const pct = limit > 0 ? Math.min((used/limit)*100, 100) : 0;
  const color = pct >= 100 ? "#ff4444" : pct >= 80 ? "#ffaa00" : "#00ff88";
  return (
    <div>
      <div style={{ display:"flex", justifyContent:"space-between", marginBottom:8, fontSize:13 }}>
        <span style={{ color:"#aaccee" }}>{used.toLocaleString()} / {limit.toLocaleString()}</span>
        <span style={{ color, fontWeight:600 }}>{pct.toFixed(1)}%</span>
      </div>
      <div style={{ background:"#1a2535", borderRadius:6, height:10, overflow:"hidden" }}>
        <div style={{ width:`${pct}%`, height:"100%", background:`linear-gradient(90deg,${color}88,${color})`, transition:"width 0.5s ease" }} />
      </div>
      {pct >= 80 && (
        <p style={{ color: pct>=100?"#ff6666":"#ffbb44", fontSize:12, marginTop:8 }}>
          {pct>=100 ? "⚠️ Limit exceeded — requests are being blocked. Upgrade your plan." : `⚠️ ${(100-pct).toFixed(1)}% remaining this month.`}
        </p>
      )}
    </div>
  );
}

const TAB = ["overview","invoices","plans","simulator"];
const STATUS_COLOR = { paid:"#00ff88", failed:"#ff4444", pending:"#ffaa00" };

export default function BillingPage() {
  const { user } = useAuthStore();
  const [tab, setTab]         = useState("overview");
  const [summary, setSummary] = useState(null);
  const [invoices, setInvoices] = useState([]);
  const [plans, setPlans]     = useState([]);
  const [loading, setLoading] = useState(true);
  const [simReq, setSimReq]   = useState(50000);
  const [simPlan, setSimPlan] = useState("starter");
  const [simRes, setSimRes]   = useState(null);
  const [simLoad, setSimLoad] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const [s, inv, p] = await Promise.all([
          billingAPI.getSummary().catch(()=>({data:{}})),
          billingAPI.getInvoices().catch(()=>({data:{invoices:[]}})),
          billingAPI.getPlans().catch(()=>({data:{plans:[]}})),
        ]);
        setSummary(s.data);
        setInvoices(inv.data?.invoices || []);
        setPlans(p.data?.plans || []);
      } catch {}
      finally { setLoading(false); }
    })();
  }, []);

  const simulate = async () => {
    setSimLoad(true);
    try { const r = await billingAPI.simulateBill(simReq, simPlan); setSimRes(r.data); }
    catch {}
    finally { setSimLoad(false); }
  };

  const b = summary?.billing || {};
  const u = summary?.user    || {};

  const tabBtn = (t) => ({
    background:"none", border:"none",
    borderBottom: tab===t ? "2px solid #00ff88" : "2px solid transparent",
    color: tab===t ? "#00ff88" : "#556677",
    padding:"9px 18px", cursor:"pointer", fontSize:13, fontWeight: tab===t?600:400,
  });

  if (loading) return <div style={{ padding:32, color:"#445566", fontSize:13 }}>Loading billing…</div>;

  return (
    <div style={{ padding:32, maxWidth:960 }}>
      <h1 style={{ fontSize:22, color:"#e0e8f0", margin:"0 0 4px" }}>Billing</h1>
      <p style={{ color:"#445566", fontSize:13, margin:"0 0 24px" }}>
        {(u.plan || user?.plan || "free").toUpperCase()} plan · {new Date().toLocaleDateString("en-US",{month:"long",year:"numeric"})}
      </p>

      {/* Tabs */}
      <div style={{ borderBottom:"1px solid #1a2535", display:"flex", marginBottom:24 }}>
        {TAB.map(t => <button key={t} style={tabBtn(t)} onClick={() => setTab(t)}>{t.charAt(0).toUpperCase()+t.slice(1)}</button>)}
      </div>

      {/* Overview */}
      {tab==="overview" && (
        <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:20 }}>
          <div style={{ background:"#0a1628", border:"1px solid #1a2535", borderRadius:12, padding:24 }}>
            <div style={{ fontSize:11, color:"#445566", letterSpacing:"2px", marginBottom:16 }}>MONTHLY USAGE</div>
            <UsageBar used={b.total_requests||0} limit={u.monthly_limit||10000} />
          </div>
          <div style={{ background:"#0a1628", border:"1px solid #1a2535", borderRadius:12, padding:24 }}>
            <div style={{ fontSize:11, color:"#445566", letterSpacing:"2px", marginBottom:16 }}>ESTIMATED BILL</div>
            <Row label="Plan"         value={(u.plan||"free").toUpperCase()} />
            <Row label="Base cost"    value={`$${(b.base_cost_usd||0).toFixed(2)}`} indent />
            <Row label="Included"     value={(b.included_requests||0).toLocaleString()} indent />
            {(b.billable_requests||0)>0 && <Row label="Overage" value={`+$${(b.overage_cost_usd||0).toFixed(2)}`} indent />}
            <Row label="Total due"    value={`$${(b.total_cost_usd||0).toFixed(2)}`} big />
          </div>
        </div>
      )}

      {/* Invoices */}
      {tab==="invoices" && (
        <div style={{ background:"#0a1628", border:"1px solid #1a2535", borderRadius:12, overflow:"hidden" }}>
          <table style={{ width:"100%", borderCollapse:"collapse", fontSize:13 }}>
            <thead>
              <tr style={{ background:"#060e1a" }}>
                {["Period","Requests","Amount","Status"].map(h=>(
                  <th key={h} style={{ padding:"12px 20px", textAlign:"left", color:"#445566", fontSize:11, letterSpacing:"1px", fontWeight:500, textTransform:"uppercase" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {invoices.length===0 ? (
                <tr><td colSpan={4} style={{ padding:"32px 20px", textAlign:"center", color:"#334455" }}>
                  No invoices yet. First invoice generates on the 1st of next month.
                </td></tr>
              ) : invoices.map((inv,i) => (
                <tr key={i} style={{ borderTop:"1px solid #0d1e30" }}>
                  <td style={{ padding:"13px 20px", color:"#aaccee" }}>{inv.billing_month}</td>
                  <td style={{ padding:"13px 20px", fontFamily:"monospace", color:"#e0e8f0" }}>{(inv.total_requests||0).toLocaleString()}</td>
                  <td style={{ padding:"13px 20px", fontFamily:"monospace", color:"#e0e8f0" }}>${(inv.total_cost_usd||0).toFixed(2)}</td>
                  <td style={{ padding:"13px 20px" }}>
                    <span style={{ fontSize:11, fontWeight:700, padding:"3px 8px", borderRadius:4, background:`${STATUS_COLOR[inv.status]||"#ffaa00"}20`, color:STATUS_COLOR[inv.status]||"#ffaa00" }}>
                      {(inv.status||"pending").toUpperCase()}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Plans */}
      {tab==="plans" && (
        <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fit,minmax(200px,1fr))", gap:12 }}>
          {plans.length===0 ? <p style={{color:"#445566"}}>Loading plans…</p> : plans.map((p,i)=>{
            const cur = p.name===(u.plan||user?.plan);
            return (
              <div key={i} style={{ background: cur?"#0d2040":"#0a1628", border:`1px solid ${cur?"#00ff8840":"#1a2535"}`, borderRadius:12, padding:20 }}>
                {cur && <div style={{ fontSize:10, color:"#00ff88", fontWeight:700, letterSpacing:"1px", marginBottom:8 }}>CURRENT</div>}
                <div style={{ fontSize:15, fontWeight:700, color:"#e0e8f0", textTransform:"capitalize", marginBottom:4 }}>{p.name}</div>
                <div style={{ fontSize:22, fontWeight:700, color:"#00ff88", fontFamily:"monospace", marginBottom:4 }}>
                  ${p.monthly_base_usd}<span style={{ fontSize:12, color:"#445566" }}>/mo</span>
                </div>
                <div style={{ fontSize:11, color:"#445566", marginBottom:12 }}>+${p.overage_per_1000_usd}/1k over limit</div>
                {(p.features||[]).map((f,j)=>(
                  <div key={j} style={{ fontSize:12, color:"#667788", padding:"3px 0" }}>✓ {f}</div>
                ))}
              </div>
            );
          })}
        </div>
      )}

      {/* Simulator */}
      {tab==="simulator" && (
        <div style={{ maxWidth:460 }}>
          <p style={{ color:"#667788", fontSize:13, marginTop:0, lineHeight:1.7 }}>
            Enter a request count and plan to see what your bill would be.
          </p>
          <div style={{ background:"#0a1628", border:"1px solid #1a2535", borderRadius:12, padding:24 }}>
            <label style={{ fontSize:11, color:"#445566", letterSpacing:"1px", display:"block", marginBottom:6 }}>MONTHLY REQUESTS</label>
            <input type="number" value={simReq} onChange={e=>setSimReq(Number(e.target.value))}
              style={{ width:"100%", background:"#060e1a", border:"1px solid #1a2535", borderRadius:8, padding:"9px 12px", color:"#e0e8f0", fontSize:14, fontFamily:"monospace", outline:"none", boxSizing:"border-box", marginBottom:14 }} />
            <label style={{ fontSize:11, color:"#445566", letterSpacing:"1px", display:"block", marginBottom:6 }}>PLAN</label>
            <select value={simPlan} onChange={e=>setSimPlan(e.target.value)}
              style={{ width:"100%", background:"#060e1a", border:"1px solid #1a2535", borderRadius:8, padding:"9px 12px", color:"#e0e8f0", fontSize:13, outline:"none", marginBottom:16 }}>
              {["free","starter","pro","enterprise"].map(p=><option key={p} value={p}>{p.charAt(0).toUpperCase()+p.slice(1)}</option>)}
            </select>
            <button onClick={simulate} disabled={simLoad}
              style={{ width:"100%", background:"linear-gradient(135deg,#00ff88,#00aaff)", border:"none", borderRadius:8, padding:12, color:"#000", fontWeight:700, fontSize:13, cursor:"pointer" }}>
              {simLoad ? "Calculating…" : "Calculate Bill →"}
            </button>
            {simRes && (
              <div style={{ marginTop:20 }}>
                <div style={{ height:1, background:"#1a2535", margin:"16px 0" }} />
                <Row label="Plan"          value={(simRes.plan||"").toUpperCase()} />
                <Row label="Total requests" value={(simRes.total_requests||0).toLocaleString()} />
                <Row label="Included"      value={(simRes.included_requests||0).toLocaleString()} indent />
                <Row label="Overage"       value={(simRes.billable_requests||0).toLocaleString()} indent />
                <Row label="Base cost"     value={`$${(simRes.base_cost_usd||0).toFixed(2)}`} indent />
                <Row label="Overage cost"  value={`$${(simRes.overage_cost_usd||0).toFixed(2)}`} indent />
                <Row label="Total"         value={`$${(simRes.total_cost_usd||0).toFixed(2)}`} big />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

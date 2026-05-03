import { useState, useEffect } from "react";
import { keyAPI } from "../services/axios";

function Badge({ text, color }) {
  return <span style={{ background:`${color}20`, color, fontSize:10, fontWeight:700, padding:"3px 8px", borderRadius:4 }}>{text}</span>;
}

function Modal({ keyData, onClose }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(keyData.full_key);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <div style={{ position:"fixed", inset:0, background:"#000c", display:"flex", alignItems:"center", justifyContent:"center", zIndex:999 }}>
      <div style={{ background:"#0a1628", border:"1px solid #00ff8840", borderRadius:16, padding:32, maxWidth:540, width:"90%" }}>
        <div style={{ fontSize:28, marginBottom:8 }}>🗝️</div>
        <h2 style={{ color:"#00ff88", margin:"0 0 8px", fontSize:18 }}>API Key Created</h2>
        <p style={{ color:"#ff8844", fontSize:13, margin:"0 0 20px", lineHeight:1.6 }}>
          ⚠️ Copy this key NOW — it will never be shown again.
        </p>
        <div style={{ background:"#060e1a", border:"1px solid #1a2535", borderRadius:8, padding:"12px 16px", marginBottom:16, display:"flex", alignItems:"center", gap:12 }}>
          <code style={{ fontSize:13, color:"#00ff88", wordBreak:"break-all", flex:1 }}>{keyData.full_key}</code>
          <button onClick={copy} style={{ background: copied?"#00ff8820":"#1a2535", border:"none", borderRadius:6, padding:"6px 14px", color: copied?"#00ff88":"#aaccee", cursor:"pointer", fontSize:12, flexShrink:0 }}>
            {copied ? "✓ Copied!" : "Copy"}
          </button>
        </div>
        <div style={{ display:"flex", gap:8, flexWrap:"wrap", marginBottom:20 }}>
          <Badge text={(keyData.environment||"live").toUpperCase()} color="#00aaff" />
          {(keyData.scopes||[]).map(s => <Badge key={s} text={s} color="#667788" />)}
        </div>
        <button onClick={onClose} style={{ width:"100%", background:"#1a2535", border:"none", borderRadius:8, padding:12, color:"#aaccee", cursor:"pointer", fontSize:13 }}>
          I've saved the key — Close
        </button>
      </div>
    </div>
  );
}

function CreateForm({ onCreated, onCancel }) {
  const [form, setForm] = useState({ name:"", description:"", environment:"live", rate_limit_per_minute:60 });
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  const inp = { width:"100%", background:"#060e1a", border:"1px solid #1a2535", borderRadius:8, padding:"9px 12px", color:"#e0e8f0", fontSize:13, outline:"none", boxSizing:"border-box", marginBottom:10 };

  const submit = async () => {
    if (!form.name.trim()) return setErr("Name is required");
    setLoading(true); setErr("");
    try {
      const res = await keyAPI.create(form);
      onCreated(res.data);
    } catch(e) {
      setErr(e.response?.data?.detail || "Failed to create key");
    } finally { setLoading(false); }
  };

  return (
    <div style={{ background:"#0d2040", border:"1px solid #00aaff30", borderRadius:12, padding:24, marginBottom:24 }}>
      <h3 style={{ color:"#e0e8f0", margin:"0 0 16px", fontSize:15 }}>Create New API Key</h3>
      {err && <div style={{ color:"#ff6666", fontSize:12, marginBottom:10 }}>{err}</div>}
      <input style={inp} placeholder="Key name (e.g. Production Backend)" value={form.name} onChange={e=>setForm(p=>({...p,name:e.target.value}))} />
      <input style={inp} placeholder="Description (optional)" value={form.description} onChange={e=>setForm(p=>({...p,description:e.target.value}))} />
      <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:10, marginBottom:10 }}>
        <select style={{...inp, marginBottom:0}} value={form.environment} onChange={e=>setForm(p=>({...p,environment:e.target.value}))}>
          <option value="live">🟢 Live</option>
          <option value="test">🧪 Test</option>
        </select>
        <input type="number" style={{...inp,marginBottom:0}} placeholder="Req/min limit" value={form.rate_limit_per_minute} onChange={e=>setForm(p=>({...p,rate_limit_per_minute:+e.target.value}))} />
      </div>
      <div style={{ display:"flex", gap:10, marginTop:6 }}>
        <button onClick={submit} disabled={loading} style={{ background:"linear-gradient(135deg,#00ff88,#00aaff)", border:"none", borderRadius:8, padding:"9px 22px", color:"#000", fontWeight:700, cursor:"pointer", fontSize:13 }}>
          {loading ? "Creating…" : "Generate Key"}
        </button>
        <button onClick={onCancel} style={{ background:"transparent", border:"1px solid #1a2535", borderRadius:8, padding:"9px 18px", color:"#667788", cursor:"pointer", fontSize:13 }}>
          Cancel
        </button>
      </div>
    </div>
  );
}

export default function APIKeysPage() {
  const [keys, setKeys]         = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [newKey, setNewKey]     = useState(null);
  const [loading, setLoading]   = useState(true);
  const [revoking, setRevoking] = useState(null);

  const load = async () => {
    try { const r = await keyAPI.list(); setKeys(r.data || []); }
    catch {}
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const handleRevoke = async (id, name) => {
    if (!window.confirm(`Revoke "${name}"? This cannot be undone.`)) return;
    setRevoking(id);
    try { await keyAPI.revoke(id); load(); }
    catch {}
    finally { setRevoking(null); }
  };

  const activeCount = keys.filter(k => k.is_active).length;

  return (
    <div style={{ padding:32, maxWidth:900 }}>
      {newKey && <Modal keyData={newKey} onClose={() => setNewKey(null)} />}

      <div style={{ display:"flex", justifyContent:"space-between", alignItems:"flex-end", marginBottom:24 }}>
        <div>
          <h1 style={{ margin:0, fontSize:22, color:"#e0e8f0" }}>API Keys</h1>
          <p style={{ margin:"4px 0 0", color:"#445566", fontSize:13 }}>{activeCount} active key{activeCount !== 1 ? "s" : ""}</p>
        </div>
        {!showForm && (
          <button onClick={() => setShowForm(true)} style={{ background:"linear-gradient(135deg,#00ff88,#00aaff)", border:"none", borderRadius:8, padding:"9px 18px", color:"#000", fontWeight:700, cursor:"pointer", fontSize:13 }}>
            + Create Key
          </button>
        )}
      </div>

      {showForm && <CreateForm onCreated={d => { setNewKey(d); setShowForm(false); load(); }} onCancel={() => setShowForm(false)} />}

      {loading ? (
        <p style={{ color:"#445566", fontSize:13 }}>Loading keys…</p>
      ) : keys.length === 0 ? (
        <div style={{ background:"#0a1628", border:"1px dashed #1a2535", borderRadius:12, padding:48, textAlign:"center" }}>
          <div style={{ fontSize:32, marginBottom:12 }}>🗝️</div>
          <p style={{ color:"#445566", fontSize:14 }}>No API keys yet. Create one to get started.</p>
        </div>
      ) : (
        <div style={{ display:"flex", flexDirection:"column", gap:10 }}>
          {keys.map(key => (
            <div key={key.id} style={{ background:"#0a1628", border:`1px solid ${key.is_active?"#1a2535":"#1a0808"}`, borderRadius:12, padding:20, opacity: key.is_active?1:0.55 }}>
              <div style={{ display:"flex", justifyContent:"space-between", alignItems:"flex-start" }}>
                <div style={{ flex:1 }}>
                  <div style={{ display:"flex", alignItems:"center", gap:8, marginBottom:6 }}>
                    <span style={{ fontWeight:700, color:"#e0e8f0", fontSize:15 }}>{key.name}</span>
                    <Badge text={(key.environment||"live").toUpperCase()} color={key.environment==="live"?"#00ff88":"#ffaa00"} />
                    {!key.is_active && <Badge text="REVOKED" color="#ff4444" />}
                  </div>
                  <code style={{ fontSize:12, color:"#445566", background:"#060e1a", padding:"3px 10px", borderRadius:4 }}>
                    {key.key_prefix}••••••••••••
                  </code>
                  <div style={{ display:"flex", gap:20, marginTop:10, flexWrap:"wrap" }}>
                    <span style={{ fontSize:12, color:"#445566" }}>{(key.total_requests||0).toLocaleString()} requests</span>
                    <span style={{ fontSize:12, color:"#445566" }}>{key.rate_limit_per_minute} req/min</span>
                    {key.last_used_at && <span style={{ fontSize:12, color:"#445566" }}>Last used: {new Date(key.last_used_at).toLocaleDateString()}</span>}
                  </div>
                </div>
                {key.is_active && (
                  <button onClick={() => handleRevoke(key.id, key.name)} disabled={revoking===key.id}
                    style={{ background:"transparent", border:"1px solid #1a2535", borderRadius:6, padding:"6px 14px", color:"#667788", cursor:"pointer", fontSize:12, marginLeft:16, flexShrink:0 }}>
                    {revoking===key.id ? "…" : "Revoke"}
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

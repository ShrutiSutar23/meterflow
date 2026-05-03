// frontend/src/pages/Logs.jsx
import { useState, useEffect, useCallback } from "react";
import { logsAPI } from "../services/axios";

const METHOD_COLOR = {
  GET: "#00cc88", POST: "#0088ff",
  DELETE: "#ff4444", PATCH: "#ffaa00", PUT: "#aa44ff",
};
const statusColor = (c) => c >= 500 ? "#ff4444" : c >= 400 ? "#ffaa00" : "#00ff88";

function FilterBar({ filters, setFilters, onSearch }) {
  const inp = {
    background: "#0a1628", border: "1px solid #1a2535", borderRadius: 8,
    padding: "8px 12px", color: "#e0e8f0", fontSize: 12,
    fontFamily: "monospace", outline: "none",
  };
  return (
    <div style={{ display: "flex", gap: 10, marginBottom: 16, flexWrap: "wrap" }}>
      <input
        style={{ ...inp, flex: 1, minWidth: 180 }}
        placeholder="Filter by endpoint…"
        value={filters.endpoint}
        onChange={e => setFilters(f => ({ ...f, endpoint: e.target.value }))}
      />
      <select
        style={{ ...inp }}
        value={filters.status_code}
        onChange={e => setFilters(f => ({ ...f, status_code: e.target.value }))}
      >
        <option value="">All status codes</option>
        <option value="200">200 OK</option>
        <option value="400">400 Bad Request</option>
        <option value="401">401 Unauthorized</option>
        <option value="404">404 Not Found</option>
        <option value="429">429 Rate Limited</option>
        <option value="500">500 Server Error</option>
      </select>
      <button
        onClick={onSearch}
        style={{
          ...inp, cursor: "pointer", background: "#0d2040",
          border: "1px solid #00aaff40", color: "#00aaff", padding: "8px 18px",
        }}
      >
        Search
      </button>
    </div>
  );
}

function DetailPanel({ log, onClose }) {
  if (!log) return null;
  const rows = [
    ["Request ID",     log.request_id],
    ["Endpoint",       log.endpoint],
    ["Method",         log.method],
    ["Status Code",    log.status_code],
    ["Response Time",  log.response_time_ms != null ? `${log.response_time_ms}ms` : "—"],
    ["IP Address",     log.ip_address || "—"],
    ["Timestamp",      log.timestamp ? new Date(log.timestamp).toLocaleString() : "—"],
    ["API Key",        log.api_key_id ? `${log.api_key_id.slice(0,8)}…` : "JWT auth"],
  ];
  return (
    <div style={{
      position: "fixed", right: 0, top: 0, bottom: 0, width: 420,
      background: "#0a1628", borderLeft: "1px solid #1a2535",
      overflowY: "auto", zIndex: 100, padding: 24,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 20 }}>
        <span style={{ fontSize: 14, fontWeight: 600, color: "#e0e8f0" }}>Request Detail</span>
        <button onClick={onClose} style={{ background: "none", border: "none", color: "#445566", fontSize: 20, cursor: "pointer" }}>×</button>
      </div>
      {rows.map(([label, val]) => (
        <div key={label} style={{ padding: "9px 0", borderBottom: "1px solid #0d1e30" }}>
          <div style={{ fontSize: 10, color: "#445566", letterSpacing: "1px", textTransform: "uppercase", marginBottom: 3 }}>{label}</div>
          <div style={{ fontSize: 13, color: "#aaccee", wordBreak: "break-all" }}>{String(val)}</div>
        </div>
      ))}
      {log.error_message && (
        <div style={{ marginTop: 16, background: "#1a0808", border: "1px solid #ff444430", borderRadius: 8, padding: 12 }}>
          <div style={{ fontSize: 11, color: "#ff6666", marginBottom: 6 }}>ERROR</div>
          <div style={{ fontSize: 12, color: "#ff8888" }}>{log.error_message}</div>
        </div>
      )}
    </div>
  );
}

export default function LogsPage() {
  const [logs,    setLogs]    = useState([]);
  const [total,   setTotal]   = useState(0);
  const [page,    setPage]    = useState(1);
  const [pages,   setPages]   = useState(1);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [filters, setFilters] = useState({ endpoint: "", status_code: "" });

  const PAGE_SIZE = 50;

  const fetchLogs = useCallback(async (p = 1) => {
    setLoading(true);
    try {
      const params = { page: p, page_size: PAGE_SIZE };
      if (filters.endpoint)    params.endpoint     = filters.endpoint;
      if (filters.status_code) params.status_code  = Number(filters.status_code);
      const res = await logsAPI.list(params);
      setLogs(res.data?.logs || []);
      setTotal(res.data?.total || 0);
      setPages(res.data?.total_pages || 1);
      setPage(p);
    } catch { setLogs([]); }
    finally { setLoading(false); }
  }, [filters]);

  useEffect(() => { fetchLogs(1); }, []);

  const openDetail = async (log) => {
    try {
      const r = await logsAPI.getDetail(log.request_id);
      setSelected(r.data);
    } catch { setSelected(log); }
  };

  return (
    <div style={{ padding: 32, fontFamily: "monospace", marginRight: selected ? 420 : 0, transition: "margin 0.2s" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginBottom: 20 }}>
        <div>
          <h1 style={{ color: "#e0e8f0", fontSize: 22, margin: "0 0 4px" }}>Request Logs</h1>
          <p style={{ color: "#445566", fontSize: 13, margin: 0 }}>
            {total.toLocaleString()} total · page {page} of {pages}
          </p>
        </div>
        <button onClick={() => fetchLogs(page)} style={{ background: "#0a1628", border: "1px solid #1a2535", borderRadius: 8, padding: "7px 14px", color: "#667788", fontSize: 12, cursor: "pointer", fontFamily: "monospace" }}>
          ↻ Refresh
        </button>
      </div>

      <FilterBar filters={filters} setFilters={setFilters} onSearch={() => fetchLogs(1)} />

      {loading ? (
        <p style={{ color: "#445566", fontSize: 13 }}>Loading logs…</p>
      ) : (
        <>
          <div style={{ background: "#0a1628", border: "1px solid #1a2535", borderRadius: 12, overflow: "hidden" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr style={{ background: "#060e1a" }}>
                  {["Method", "Endpoint", "Status", "Latency", "Time"].map(h => (
                    <th key={h} style={{ padding: "10px 16px", textAlign: "left", color: "#445566", fontSize: 10, letterSpacing: "1px", fontWeight: 500, textTransform: "uppercase" }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {logs.length === 0 ? (
                  <tr><td colSpan={5} style={{ padding: "32px 16px", textAlign: "center", color: "#334455" }}>No logs found.</td></tr>
                ) : logs.map((log, i) => (
                  <tr key={i} onClick={() => openDetail(log)}
                    style={{ borderTop: "1px solid #0d1e30", cursor: "pointer", background: selected?.request_id === log.request_id ? "#0d2040" : "transparent" }}>
                    <td style={{ padding: "10px 16px" }}>
                      <span style={{ background: `${METHOD_COLOR[log.method] || "#667788"}20`, color: METHOD_COLOR[log.method] || "#667788", fontSize: 10, fontWeight: 700, padding: "2px 6px", borderRadius: 3 }}>
                        {log.method}
                      </span>
                    </td>
                    <td style={{ padding: "10px 16px", color: "#aaccee", maxWidth: 280, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {log.endpoint}
                    </td>
                    <td style={{ padding: "10px 16px" }}>
                      <span style={{ color: statusColor(log.status_code), fontWeight: 600 }}>{log.status_code}</span>
                    </td>
                    <td style={{ padding: "10px 16px", color: "#667788" }}>
                      {log.response_time_ms != null ? `${log.response_time_ms}ms` : "—"}
                    </td>
                    <td style={{ padding: "10px 16px", color: "#445566" }}>
                      {log.timestamp ? new Date(log.timestamp).toLocaleTimeString() : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {pages > 1 && (
            <div style={{ display: "flex", gap: 8, marginTop: 16, justifyContent: "center" }}>
              <button disabled={page <= 1} onClick={() => fetchLogs(page - 1)}
                style={{ background: "#0a1628", border: "1px solid #1a2535", borderRadius: 6, padding: "6px 14px", color: page<=1?"#334455":"#aaccee", cursor: page<=1?"default":"pointer", fontFamily: "monospace", fontSize: 12 }}>
                ← Prev
              </button>
              <span style={{ color: "#445566", fontSize: 12, padding: "6px 12px" }}>{page} / {pages}</span>
              <button disabled={page >= pages} onClick={() => fetchLogs(page + 1)}
                style={{ background: "#0a1628", border: "1px solid #1a2535", borderRadius: 6, padding: "6px 14px", color: page>=pages?"#334455":"#aaccee", cursor: page>=pages?"default":"pointer", fontFamily: "monospace", fontSize: 12 }}>
                Next →
              </button>
            </div>
          )}
        </>
      )}

      <DetailPanel log={selected} onClose={() => setSelected(null)} />
    </div>
  );
}

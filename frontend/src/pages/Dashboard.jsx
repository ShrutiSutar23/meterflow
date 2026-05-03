// frontend/src/pages/Dashboard.jsx
/**
 * Dashboard Page — Protected Route
 * ==================================
 * Only accessible when isAuthenticated is true.
 * If token is missing, App.jsx redirects to /login automatically.
 *
 * Shows:
 *   - Welcome message with username
 *   - Key account stats (plan, requests used, API keys)
 *   - Logout button
 *   - Quick links to all sections
 */

import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import {
  LineChart, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from "recharts";
import useAuthStore from "../store/authStore";
import { analyticsAPI, billingAPI, keyAPI } from "../services/axios";

// ── Stat Card ──────────────────────────────────────────────────────────────────
function StatCard({ icon, label, value, sub, accent = "#00ff88" }) {
  return (
    <div style={{
      background: "#0a1628",
      border: `1px solid ${accent}22`,
      borderRadius: 14,
      padding: "20px 24px",
      flex: 1,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div style={{ fontSize: 11, color: "#556677", letterSpacing: "1px", textTransform: "uppercase", marginBottom: 10 }}>
            {label}
          </div>
          <div style={{ fontSize: 30, fontWeight: 700, color: accent, fontFamily: "monospace", lineHeight: 1 }}>
            {value}
          </div>
          {sub && <div style={{ fontSize: 12, color: "#445566", marginTop: 6 }}>{sub}</div>}
        </div>
        <span style={{ fontSize: 26, opacity: 0.8 }}>{icon}</span>
      </div>
    </div>
  );
}

// ── Quick Link Card ────────────────────────────────────────────────────────────
function QuickLink({ icon, title, desc, onClick }) {
  const [hovered, setHovered] = useState(false);
  return (
    <div
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        background: hovered ? "#0d1e35" : "#0a1628",
        border: `1px solid ${hovered ? "#00ff8840" : "#1a2535"}`,
        borderRadius: 12,
        padding: "18px 20px",
        cursor: "pointer",
        transition: "all 0.18s",
        flex: 1,
      }}
    >
      <div style={{ fontSize: 24, marginBottom: 8 }}>{icon}</div>
      <div style={{ fontSize: 14, fontWeight: 600, color: "#e0e8f0", marginBottom: 4 }}>{title}</div>
      <div style={{ fontSize: 12, color: "#445566", lineHeight: 1.5 }}>{desc}</div>
    </div>
  );
}

// ── Dashboard ──────────────────────────────────────────────────────────────────
export default function Dashboard() {
  const { user, logout } = useAuthStore();
  const navigate         = useNavigate();

  const [stats,   setStats]   = useState(null);
  const [volume,  setVolume]  = useState([]);
  const [keyCount, setKeyCount] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const [billRes, volRes, keyRes] = await Promise.allSettled([
          billingAPI.getSummary(),
          analyticsAPI.getVolume(14),
          keyAPI.list(),
        ]);

        if (billRes.status === "fulfilled") setStats(billRes.value.data);
        if (volRes.status  === "fulfilled") setVolume(volRes.value.data?.data || []);
        if (keyRes.status  === "fulfilled") {
          const keys = keyRes.value.data || [];
          setKeyCount(keys.filter(k => k.is_active).length);
        }
      } catch {}
      finally { setLoading(false); }
    };
    load();
  }, []);

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  const billing = stats?.billing || {};
  const plan    = (user?.plan || "free").toUpperCase();
  const reqUsed = (billing.total_requests || user?.requests_this_month || 0).toLocaleString();
  const reqLimit = (user?.monthly_request_limit || 10000).toLocaleString();
  const estBill = `$${(billing.total_cost_usd || 0).toFixed(2)}`;

  return (
    <div style={{ padding: "36px 40px", maxWidth: 1100 }}>

      {/* ── Header ── */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 36 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 26, fontWeight: 800, color: "#e0e8f0" }}>
            Welcome back, {user?.username || user?.email?.split("@")[0] || "Developer"} 👋
          </h1>
          <p style={{ margin: "7px 0 0", color: "#445566", fontSize: 14 }}>
            <span style={{ background: "#00ff8818", color: "#00ff88", padding: "2px 10px", borderRadius: 20, fontSize: 12, fontWeight: 600 }}>
              {plan} PLAN
            </span>
            {" "}· {new Date().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric" })}
          </p>
        </div>

        <button
          onClick={handleLogout}
          style={{
            background: "transparent",
            border: "1px solid #1a2535",
            borderRadius: 9,
            padding: "9px 20px",
            color: "#556677",
            fontSize: 13,
            fontWeight: 500,
            cursor: "pointer",
            transition: "all 0.2s",
          }}
          onMouseEnter={e => { e.target.style.borderColor = "#ff444460"; e.target.style.color = "#ff6666"; }}
          onMouseLeave={e => { e.target.style.borderColor = "#1a2535";   e.target.style.color = "#556677"; }}
        >
          Sign Out
        </button>
      </div>

      {/* ── KPI Row ── */}
      <div style={{ display: "flex", gap: 16, marginBottom: 32 }}>
        <StatCard icon="📊" label="Requests This Month" value={reqUsed}     sub={`of ${reqLimit} included`} accent="#00ff88" />
        <StatCard icon="💳" label="Estimated Bill"       value={estBill}    sub="current month"              accent="#ffaa00" />
        <StatCard icon="🗝️"  label="Active API Keys"     value={loading ? "—" : (keyCount ?? 0)} sub="click to manage"  accent="#00aaff" />
        <StatCard icon="📋" label="Plan"                  value={plan}       sub="click to upgrade"           accent="#aa44ff" />
      </div>

      {/* ── Volume Chart ── */}
      <div style={{ background: "#0a1628", border: "1px solid #1a2535", borderRadius: 14, padding: "24px 28px", marginBottom: 32 }}>
        <div style={{ fontSize: 11, color: "#445566", letterSpacing: "2px", textTransform: "uppercase", marginBottom: 16 }}>
          Request Volume — Last 14 Days
        </div>
        {volume.length > 0 ? (
          <ResponsiveContainer width="100%" height={210}>
            <LineChart data={volume} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1a2535" />
              <XAxis
                dataKey="period"
                tick={{ fill: "#445566", fontSize: 11 }}
                tickFormatter={v => v.slice(5)}
              />
              <YAxis tick={{ fill: "#445566", fontSize: 11 }} />
              <Tooltip
                contentStyle={{ background: "#0d1e30", border: "1px solid #1a2535", borderRadius: 8, fontSize: 12 }}
                labelStyle={{ color: "#aaccee" }}
              />
              <Legend wrapperStyle={{ fontSize: 12, color: "#556677" }} />
              <Line type="monotone" dataKey="total"  name="Requests" stroke="#00ff88" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="errors" name="Errors"   stroke="#ff4444" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <div style={{ height: 210, display: "flex", alignItems: "center", justifyContent: "center", color: "#334455", fontSize: 13 }}>
            {loading ? "Loading chart…" : "No data yet — make your first API call to see volume here."}
          </div>
        )}
      </div>

      {/* ── Quick Links ── */}
      <div style={{ fontSize: 11, color: "#445566", letterSpacing: "2px", textTransform: "uppercase", marginBottom: 14 }}>
        Quick Navigation
      </div>
      <div style={{ display: "flex", gap: 14 }}>
        <QuickLink icon="🗝️"  title="API Keys"  desc="Create, manage and revoke your API keys"    onClick={() => navigate("/keys")}    />
        <QuickLink icon="💳" title="Billing"   desc="View invoices, plans, and usage summary"   onClick={() => navigate("/billing")} />
        <QuickLink icon="📋" title="Logs"      desc="Browse all your API request logs"          onClick={() => navigate("/logs")}    />
      </div>

    </div>
  );
}

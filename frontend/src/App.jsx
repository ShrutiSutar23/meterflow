// frontend/src/App.jsx
/**
 * App — Router + Layout + Protected Routes
 * ==========================================
 * Routes:
 *   /login    → LoginPage   (public)
 *   /signup   → SignupPage  (public)
 *   /dashboard → Dashboard  (protected)
 *   /keys      → APIKeys    (protected)
 *   /billing   → Billing    (protected)
 *   /logs      → Logs       (protected)
 *   /*         → redirect to /dashboard
 */

import { useEffect } from "react";
import {
  BrowserRouter, Routes, Route,
  Navigate, Link, useLocation,
} from "react-router-dom";
import useAuthStore from "./store/authStore";

// Pages
import { LoginPage, SignupPage } from "./pages/LoginPage";
import Dashboard   from "./pages/Dashboard";
import APIKeysPage from "./pages/APIKeys";
import BillingPage from "./pages/Billing";
import LogsPage    from "./pages/Logs";

// ── ProtectedRoute ────────────────────────────────────────────────────────
function ProtectedRoute({ children }) {
  const { isAuthenticated } = useAuthStore();
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return children;
}

// ── Sidebar ────────────────────────────────────────────────────────────────────
function Sidebar() {
  const { user, logout } = useAuthStore();
  const { pathname }     = useLocation();

  const links = [
    { to: "/dashboard", icon: "📊", label: "Dashboard" },
    { to: "/keys",      icon: "🗝️",  label: "API Keys"  },
    { to: "/billing",   icon: "💳", label: "Billing"   },
    { to: "/logs",      icon: "📋", label: "Logs"      },
  ];

  return (
    <aside style={{
      width: 224,
      minHeight: "100vh",
      background: "#080d18",
      borderRight: "1px solid #1a2535",
      display: "flex",
      flexDirection: "column",
      flexShrink: 0,
    }}>
      {/* Logo */}
      <div style={{
        padding: "22px 20px",
        borderBottom: "1px solid #1a2535",
        display: "flex",
        alignItems: "center",
        gap: 10,
      }}>
        <span style={{ fontSize: 20 }}>⚡</span>
        <span style={{
          fontSize: 16, fontWeight: 800, letterSpacing: "-0.3px",
          background: "linear-gradient(90deg, #00ff88, #00aaff)",
          WebkitBackgroundClip: "text",
          WebkitTextFillColor: "transparent",
        }}>
          MeterFlow
        </span>
      </div>

      {/* Nav */}
      <nav style={{ flex: 1, padding: "16px 10px" }}>
        {links.map(({ to, icon, label }) => {
          const active = pathname === to;
          return (
            <Link
              key={to}
              to={to}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: "10px 13px",
                borderRadius: 9,
                marginBottom: 3,
                background:   active ? "#0d2040" : "transparent",
                color:        active ? "#00ff88" : "#556677",
                fontSize: 13,
                fontWeight:   active ? 600 : 400,
                transition: "all 0.15s",
                textDecoration: "none",
              }}
            >
              <span>{icon}</span>
              <span>{label}</span>
            </Link>
          );
        })}
      </nav>

      {/* User footer */}
      <div style={{ padding: "16px 16px 20px", borderTop: "1px solid #1a2535" }}>
        <div style={{
          fontSize: 11, color: "#445566", marginBottom: 2,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>
          {user?.email}
        </div>
        <div style={{ fontSize: 11, color: "#2d3f52", marginBottom: 12 }}>
          {(user?.plan || "free").toUpperCase()} plan
        </div>
        <button
          onClick={logout}
          style={{
            width: "100%",
            background: "transparent",
            border: "1px solid #1a2535",
            borderRadius: 7,
            padding: "8px 0",
            color: "#445566",
            fontSize: 12,
            cursor: "pointer",
            transition: "all 0.2s",
          }}
          onMouseEnter={e => { e.target.style.color = "#ff6666"; e.target.style.borderColor = "#ff444450"; }}
          onMouseLeave={e => { e.target.style.color = "#445566"; e.target.style.borderColor = "#1a2535"; }}
        >
          Sign Out
        </button>
      </div>
    </aside>
  );
}

// ── App Layout (with sidebar) ──────────────────────────────────────────────────
function AppLayout({ children }) {
  return (
    <div style={{ display: "flex", minHeight: "100vh", background: "#070c14", color: "#e0e8f0" }}>
      <Sidebar />
      <main style={{ flex: 1, overflowY: "auto" }}>{children}</main>
    </div>
  );
}

// ── App ────────────────────────────────────────────────────────────────────────
export default function App() {
  const { isAuthenticated } = useAuthStore();

  return (
    <BrowserRouter>
      <Routes>
        {/* Public */}
        <Route path="/login"  element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />

        {/* Protected — require login */}
        <Route path="/dashboard" element={
          <ProtectedRoute>
            <AppLayout><Dashboard /></AppLayout>
          </ProtectedRoute>
        } />
        <Route path="/keys" element={
          <ProtectedRoute>
            <AppLayout><APIKeysPage /></AppLayout>
          </ProtectedRoute>
        } />
        <Route path="/billing" element={
          <ProtectedRoute>
            <AppLayout><BillingPage /></AppLayout>
          </ProtectedRoute>
        } />
        <Route path="/logs" element={
          <ProtectedRoute>
            <AppLayout><LogsPage /></AppLayout>
          </ProtectedRoute>
        } />

        {/* Catch-all — redirect to dashboard (or login if not authenticated) */}
        <Route path="*" element={
          isAuthenticated
            ? <Navigate to="/dashboard" replace />
            : <Navigate to="/login"     replace />
        } />
      </Routes>
    </BrowserRouter>
  );
}

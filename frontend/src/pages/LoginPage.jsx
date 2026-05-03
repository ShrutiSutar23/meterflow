// frontend/src/pages/LoginPage.jsx
/**
 * Login Page
 * ===========
 * The form collects EMAIL and PASSWORD from the user.
 *
 * IMPORTANT — Backend requires x-www-form-urlencoded:
 *   FastAPI's OAuth2PasswordRequestForm reads "username" and "password"
 *   from form-encoded body. The "username" field holds the email value.
 *   This mapping is done inside authAPI.login() in axios.js:
 *
 *     formData.append("username", email);   ← email goes here
 *     formData.append("password", password);
 *
 *   The user sees "Email" label but the backend receives it as "username".
 *   This is the OAuth2 spec — not a bug.
 */

import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import useAuthStore from "../store/authStore";

// ── Reusable components ────────────────────────────────────────────────────────

function Logo() {
  return (
    <div style={{ textAlign: "center", marginBottom: 32 }}>
      <div style={{ fontSize: 40, marginBottom: 10 }}>⚡</div>
      <h1 style={{
        margin: 0, fontSize: 26, fontWeight: 800, letterSpacing: "-0.5px",
        background: "linear-gradient(90deg, #00ff88, #00aaff)",
        WebkitBackgroundClip: "text",
        WebkitTextFillColor: "transparent",
      }}>
        MeterFlow
      </h1>
      <p style={{ color: "#445566", fontSize: 13, margin: "6px 0 0" }}>
        Usage-Based API Billing Platform
      </p>
    </div>
  );
}

function FormField({ label, type = "text", value, onChange, placeholder, autoComplete }) {
  return (
    <div style={{ marginBottom: 18 }}>
      <label style={{
        display: "block", fontSize: 11, fontWeight: 600,
        color: "#556677", letterSpacing: "1.2px",
        textTransform: "uppercase", marginBottom: 7,
      }}>
        {label}
      </label>
      <input
        type={type}
        value={value}
        onChange={onChange}
        placeholder={placeholder}
        autoComplete={autoComplete}
        required
        style={{
          width: "100%",
          background: "#060e1a",
          border: "1.5px solid #1a2535",
          borderRadius: 9,
          padding: "12px 16px",
          color: "#e0e8f0",
          fontSize: 14,
          outline: "none",
          boxSizing: "border-box",
          transition: "border-color 0.2s",
        }}
        onFocus={e  => e.target.style.borderColor = "#00ff8866"}
        onBlur={e   => e.target.style.borderColor = "#1a2535"}
      />
    </div>
  );
}

function ErrorAlert({ message }) {
  if (!message) return null;
  return (
    <div style={{
      background: "#1c0a0a",
      border: "1px solid #ff444455",
      borderRadius: 8,
      padding: "11px 16px",
      marginBottom: 20,
      color: "#ff7777",
      fontSize: 13,
      lineHeight: 1.5,
    }}>
      ⚠️ {message}
    </div>
  );
}

// ── Login Page ─────────────────────────────────────────────────────────────────
export function LoginPage() {
  const [email,    setEmail]    = useState("");
  const [password, setPassword] = useState("");

  const { login, isLoading, error, clearError } = useAuthStore();
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    clearError();

    // authAPI.login() internally does:
    //   URLSearchParams: username=<email>&password=<password>
    //   Content-Type: application/x-www-form-urlencoded
    const result = await login({ email, password });
    if (result.success) {
      navigate("/dashboard");
    }
  };

  return (
    <div style={{
      minHeight: "100vh",
      background: "linear-gradient(160deg, #04080f 0%, #070c14 50%, #04080f 100%)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      padding: 20,
    }}>
      <div style={{
        background: "#0a1628",
        border: "1px solid #1a2535",
        borderRadius: 18,
        padding: "44px 40px",
        width: "100%",
        maxWidth: 420,
        boxShadow: "0 20px 60px #00000066",
      }}>
        <Logo />

        <ErrorAlert message={error} />

        <form onSubmit={handleSubmit}>
          {/*
           * This input is labeled "Email" for the user.
           * But authAPI.login() maps this to the "username" field
           * in the URLSearchParams body — required by FastAPI OAuth2.
           */}
          <FormField
            label="Email Address"
            type="text"
            value={email}
            onChange={e => setEmail(e.target.value)}
            placeholder="Enter Username or Email"
            autoComplete="username"
          />

          <FormField
            label="Password"
            type="password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            placeholder="Enter your password"
            autoComplete="current-password"
          />

          <div style={{ textAlign: "right", marginTop: -8, marginBottom: 24 }}>
            <Link to="/forgot-password" style={{ fontSize: 12, color: "#445566" }}>
              Forgot password?
            </Link>
          </div>

          <button
            type="submit"
            disabled={isLoading}
            style={{
              width: "100%",
              background: isLoading
                ? "#1a2535"
                : "linear-gradient(135deg, #00ff88, #00aaff)",
              border: "none",
              borderRadius: 9,
              padding: "14px 0",
              color: isLoading ? "#445566" : "#000",
              fontSize: 15,
              fontWeight: 700,
              cursor: isLoading ? "not-allowed" : "pointer",
              transition: "all 0.2s",
              letterSpacing: "0.3px",
            }}
          >
            {isLoading ? "Signing in…" : "Sign In →"}
          </button>
        </form>

        <div style={{
          marginTop: 28,
          paddingTop: 20,
          borderTop: "1px solid #1a2535",
          textAlign: "center",
          fontSize: 13,
          color: "#445566",
        }}>
          Don't have an account?{" "}
          <Link to="/signup" style={{ color: "#00aaff", fontWeight: 600 }}>
            Sign up free
          </Link>
        </div>
      </div>
    </div>
  );
}

// ── Signup Page ────────────────────────────────────────────────────────────────
export function SignupPage() {
  const [form, setForm] = useState({
    full_name: "",
    email:     "",
    username:  "",
    password:  "",
  });

  const { signup, isLoading, error, clearError } = useAuthStore();
  const navigate = useNavigate();

  const update = (field) => (e) => setForm(prev => ({ ...prev, [field]: e.target.value }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    clearError();
    const result = await signup(form);
    if (result.success) {
      navigate("/dashboard");
    }
  };

  return (
    <div style={{
      minHeight: "100vh",
      background: "linear-gradient(160deg, #04080f 0%, #070c14 50%, #04080f 100%)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      padding: 20,
    }}>
      <div style={{
        background: "#0a1628",
        border: "1px solid #1a2535",
        borderRadius: 18,
        padding: "44px 40px",
        width: "100%",
        maxWidth: 440,
        boxShadow: "0 20px 60px #00000066",
      }}>
        <Logo />
        <p style={{ textAlign: "center", color: "#667788", fontSize: 13, marginTop: -22, marginBottom: 28 }}>
          Start free — 10,000 API calls/month included
        </p>

        <ErrorAlert message={error} />

        <form onSubmit={handleSubmit}>
          <FormField
            label="Full Name"
            value={form.full_name}
            onChange={update("full_name")}
            placeholder="John Developer"
            autoComplete="name"
          />
          <FormField
            label="Email Address"
            type="email"
            value={form.email}
            onChange={update("email")}
            placeholder="you@example.com"
            autoComplete="email"
          />
          <FormField
            label="Username"
            value={form.username}
            onChange={update("username")}
            placeholder="john_dev (letters, numbers, _ -)"
            autoComplete="username"
          />
          <FormField
            label="Password"
            type="password"
            value={form.password}
            onChange={update("password")}
            placeholder="Min 8 chars + 1 number"
            autoComplete="new-password"
          />

          <button
            type="submit"
            disabled={isLoading}
            style={{
              width: "100%",
              marginTop: 4,
              background: isLoading
                ? "#1a2535"
                : "linear-gradient(135deg, #00ff88, #00aaff)",
              border: "none",
              borderRadius: 9,
              padding: "14px 0",
              color: isLoading ? "#445566" : "#000",
              fontSize: 15,
              fontWeight: 700,
              cursor: isLoading ? "not-allowed" : "pointer",
              transition: "all 0.2s",
            }}
          >
            {isLoading ? "Creating account…" : "Get Started Free →"}
          </button>
        </form>

        <div style={{
          marginTop: 28,
          paddingTop: 20,
          borderTop: "1px solid #1a2535",
          textAlign: "center",
          fontSize: 13,
          color: "#445566",
        }}>
          Already have an account?{" "}
          <Link to="/login" style={{ color: "#00aaff", fontWeight: 600 }}>
            Sign in
          </Link>
        </div>
      </div>
    </div>
  );
}

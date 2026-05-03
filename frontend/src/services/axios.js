/**
 * Axios Configuration File
 * =========================
 * Central place for ALL API calls.
 */

import axios from "axios";

// ── Base instance ──────────────────────────────────────────────────────────────
const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "/api/v1",
  timeout: 15000,
  headers: {
    "Content-Type": "application/json",
  },
});

// ── Request interceptor — attach JWT token ─────────────────────────────────────
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem("mf_access_token");
    if (token) {
      config.headers["Authorization"] = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// ── Response interceptor — auto token refresh on 401 ──────────────────────────
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;

    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true;

      const refreshToken = localStorage.getItem("mf_refresh_token");
      if (!refreshToken) {
        _forceLogout();
        return Promise.reject(error);
      }

      try {
        const refreshRes = await axios.post(
          `${api.defaults.baseURL}/auth/refresh`,
          { refresh_token: refreshToken },
          { headers: { "Content-Type": "application/json" } }
        );

        const newAccessToken  = refreshRes.data.access_token;
        const newRefreshToken = refreshRes.data.refresh_token;

        localStorage.setItem("mf_access_token",  newAccessToken);
        localStorage.setItem("mf_refresh_token", newRefreshToken);

        originalRequest.headers["Authorization"] = `Bearer ${newAccessToken}`;
        return api(originalRequest);

      } catch {
        _forceLogout();
        return Promise.reject(error);
      }
    }

    return Promise.reject(error);
  }
);

function _forceLogout() {
  localStorage.removeItem("mf_access_token");
  localStorage.removeItem("mf_refresh_token");
  window.location.href = "/login";
}

// ══════════════════════════════════════════════════════════════════════════════
// AUTH API
// ══════════════════════════════════════════════════════════════════════════════
export const authAPI = {

  /**
   * LOGIN — sends JSON payload
   * Backend expects: { email, password } as JSON
   */
  login: async (credentials) => {
    const response = await api.post("/auth/login", credentials);

    localStorage.setItem("mf_access_token",  response.data.access_token);
    localStorage.setItem("mf_refresh_token", response.data.refresh_token || "");

    return response.data;
  },

  /**
   * SIGNUP — sends regular JSON
   */
  signup: async (payload) => {
    const response = await api.post("/auth/signup", payload);
    return response.data;
  },

  /**
   * LOGOUT
   */
  logout: async () => {
    try {
      await api.post("/auth/logout");
    } catch {
      // Silent fail
    }
    localStorage.removeItem("mf_access_token");
    localStorage.removeItem("mf_refresh_token");
  },

  /**
   * GET ME
   */
  getMe: () => api.get("/auth/me"),

  /**
   * REFRESH
   */
  refresh: (refreshToken) =>
    api.post("/auth/refresh", { refresh_token: refreshToken }),
};

// ══════════════════════════════════════════════════════════════════════════════
// API KEYS
// ══════════════════════════════════════════════════════════════════════════════
export const keyAPI = {
  list:   ()      => api.get("/keys/"),
  create: (data)  => api.post("/keys/", data),
  revoke: (id)    => api.delete(`/keys/${id}`),
  verify: (key)   => api.post("/keys/verify", null, { params: { x_api_key: key } }),
};

// ══════════════════════════════════════════════════════════════════════════════
// BILLING
// ══════════════════════════════════════════════════════════════════════════════
export const billingAPI = {
  getSummary:   ()               => api.get("/billing/summary"),
  getInvoices:  ()               => api.get("/billing/invoices"),
  getPlans:     ()               => api.get("/billing/plans"),
  simulateBill: (requests, plan) => api.post(`/billing/simulate?requests=${requests}&plan=${plan}`),
};

// ══════════════════════════════════════════════════════════════════════════════
// ANALYTICS
// ══════════════════════════════════════════════════════════════════════════════
export const analyticsAPI = {
  getDashboard: ()                                     => api.get("/analytics/dashboard"),
  getVolume:    (days = 30, gran = "day") => api.get(`/analytics/volume?days=${days}&granularity=${gran}`),
  getLatency:   (hours = 24)                           => api.get(`/analytics/latency?hours=${hours}`),
  getErrors:    (days = 7)                             => api.get(`/analytics/errors?days=${days}`),
  getEndpoints: (days = 7)                             => api.get(`/analytics/endpoints?days=${days}`),
};

// ══════════════════════════════════════════════════════════════════════════════
// LOGS
// ══════════════════════════════════════════════════════════════════════════════
export const logsAPI = {
  list:      (params = {}) => api.get("/logs", { params }),
  getDetail: (requestId)   => api.get(`/logs/${requestId}`),
};

// ══════════════════════════════════════════════════════════════════════════════
// ORGANIZATIONS
// ══════════════════════════════════════════════════════════════════════════════
export const orgAPI = {
  list:         ()                    => api.get("/orgs/"),
  create:       (data)                => api.post("/orgs/", data),
  get:          (slug)                => api.get(`/orgs/${slug}`),
  invite:       (slug, data)          => api.post(`/orgs/${slug}/members/invite`, data),
  acceptInvite: (token)               => api.post(`/orgs/invites/${token}/accept`),
  members:      (slug)                => api.get(`/orgs/${slug}/members`),
  removeMember: (slug, userId)        => api.delete(`/orgs/${slug}/members/${userId}`),
};

export default api;
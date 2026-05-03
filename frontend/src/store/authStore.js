// frontend/src/store/authStore.js
/**
 * Global Auth State — Zustand
 * ============================
 * Stores: user profile, isAuthenticated, loading, error
 * Persists: user + isAuthenticated to localStorage (survives page refresh)
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";
import { authAPI } from "../services/axios";

const useAuthStore = create(
  persist(
    (set, get) => ({
      // ── State ────────────────────────────────────────────────────────────────
      user: null,
      isAuthenticated: false,
      isLoading: false,
      error: null,

      // ── Login ─────────────────────────────────────────────────────────────────
      login: async ({ email, password }) => {
        set({ isLoading: true, error: null });
        try {
          await authAPI.login({ email, password });
          const meRes = await authAPI.getMe();
          set({ user: meRes.data, isAuthenticated: true, isLoading: false });
          return { success: true };
        } catch (err) {
          const detail = err.response?.data?.detail;
          const msg = Array.isArray(detail)
            ? detail.map((d) => d.msg).join(", ")
            : detail || "Invalid credentials. Please try again.";
          set({ error: msg, isLoading: false });
          return { success: false, error: msg };
        }
      },

      // ── Signup ────────────────────────────────────────────────────────────────
      signup: async (data) => {
        set({ isLoading: true, error: null });
        try {
          await authAPI.signup(data);
          // Auto-login after successful signup
          return await get().login({ email: data.email, password: data.password });
        } catch (err) {
          const detail = err.response?.data?.detail;
          const msg = Array.isArray(detail)
            ? detail.map((d) => d.msg).join(", ")
            : detail || "Signup failed. Please try again.";
          set({ error: msg, isLoading: false });
          return { success: false, error: msg };
        }
      },

      // ── Logout ────────────────────────────────────────────────────────────────
      logout: async () => {
        try {
          await authAPI.logout();
        } catch (err) {
          console.error("Logout error:", err);
        } finally {
          set({ user: null, isAuthenticated: false, error: null, isLoading: false });
        }
      },

      // ── Fetch current user (used on app load) ─────────────────────────────────
      fetchMe: async () => {
        const token = localStorage.getItem("mf_access_token");
        if (!token) {
          set({ user: null, isAuthenticated: false });
          return;
        }
        try {
          const res = await authAPI.getMe();
          set({ user: res.data, isAuthenticated: true });
        } catch {
          set({ user: null, isAuthenticated: false });
        }
      },

      // ── Helpers ───────────────────────────────────────────────────────────────
      clearError: () => set({ error: null }),
    }),
    {
      name: "mf-auth-store",
      partialize: (state) => ({
        user: state.user,
        isAuthenticated: state.isAuthenticated,
      }),
    }
  )
);

export default useAuthStore;
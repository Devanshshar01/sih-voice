/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Exact CloudPilot SaaS Aesthetic Palette (Purple/Violet Glow + Crisp Light Canvas)
        cloudPilot: {
          dark: "#080B11",
          violet: "#7C3AED",
          indigo: "#6366F1",
          purple: "#A855F7",
          pink: "#EC4899",
          softBg: "#F8FAFC",
          cardBorder: "#E2E8F0",
        },
        // Exact Brand Foundation: Blue Forensic Intelligence + CloudPilot Hybrids
        blueWhale: {
          DEFAULT: "#080B11",
          deep: "#05070B",
          surface: "#121824",
        },
        inkjet: {
          DEFAULT: "#1E293B",
          light: "#334155",
          dark: "#0F172A",
        },
        sailing: {
          DEFAULT: "#7C3AED",
          hover: "#8B5CF6",
          glow: "rgba(124, 58, 237, 0.35)",
        },
        shallowSea: {
          DEFAULT: "#94A3B8",
          muted: "#64748B",
          border: "#E2E8F0",
        },
        ephemeralBlue: {
          DEFAULT: "#FFFFFF",
          bright: "#F8FAFC",
        },
        // Base Palette Mapping
        forensic: {
          bg: "#FFFFFF",        // Crisp White Canvas
          surface: "#FFFFFF",   // Pure White Card
          panel: "#F8FAFC",     // Soft Slate Panel
          panelHover: "#F1F5F9",// Slate Hover
          accent: "#7C3AED",    // Violet Primary Accent
          accentMuted: "rgba(124, 58, 237, 0.12)",
          muted: "#64748B",     // Secondary text
          border: "#E2E8F0",    // Crisp light border
          borderBright: "#7C3AED",
          text: "#0F172A",      // Dark primary text
        },
        // Backward-compatible color aliases
        ink: {
          950: "#080B11",
          900: "#FFFFFF",
          850: "#F8FAFC",
          800: "#F1F5F9",
          750: "#E2E8F0",
          700: "#E2E8F0",
          600: "#CBD5E1",
          500: "#7C3AED",
          400: "#64748B",
          300: "#0F172A",
        },
        paper: {
          DEFAULT: "#0F172A",
          dim: "#475569",
          muted: "#64748B",
          bright: "#0F172A",
        },
        mute: {
          DEFAULT: "#64748B",
          dim: "#475569",
        },
        signal: {
          DEFAULT: "#7C3AED",
          dim: "#64748B",
          bg: "rgba(124, 58, 237, 0.08)",
          border: "rgba(124, 58, 237, 0.25)",
        },
        // Security States (Restrained semantic colors)
        safe: {
          DEFAULT: "#10B981",   // Emerald
          dim: "#059669",
          bg: "#ECFDF5",
          border: "#A7F3D0",
        },
        warn: {
          DEFAULT: "#F59E0B",   // Amber
          dim: "#D97706",
          bg: "#FFFBEB",
          border: "#FDE68A",
        },
        danger: {
          DEFAULT: "#EF4444",   // Red
          dim: "#DC2626",
          bg: "#FEF2F2",
          border: "#FECACA",
        },
        degraded: {
          DEFAULT: "#D97706",
          bg: "#FFFBEB",
          border: "#FDE68A",
        },
        offline: {
          DEFAULT: "#64748B",
          bg: "#F8FAFC",
          border: "#E2E8F0",
        },
        intel: {
          DEFAULT: "#7C3AED",
          dim: "#64748B",
          bg: "rgba(124, 58, 237, 0.08)",
          border: "rgba(124, 58, 237, 0.20)",
        },
      },
      fontFamily: {
        sans: ["'Plus Jakarta Sans'", "ui-sans-serif", "system-ui", "-apple-system", "sans-serif"],
        mono: ["'JetBrains Mono'", "ui-monospace", "monospace"],
      },
      boxShadow: {
        none: "none",
        panel: "0 10px 30px -5px rgba(15, 23, 35, 0.75), 0 0 0 1px rgba(163, 184, 202, 0.18)",
        elevated: "0 20px 45px -10px rgba(15, 23, 35, 0.90), 0 0 0 1px rgba(163, 184, 202, 0.25)",
        signal: "0 0 20px -3px rgba(137, 159, 188, 0.35)",
        "glow-danger": "0 0 20px -2px rgba(239, 68, 68, 0.35)",
        "glow-safe": "0 0 20px -3px rgba(16, 185, 129, 0.30)",
        "glow-warn": "0 0 20px -3px rgba(245, 158, 11, 0.30)",
      },
      keyframes: {
        sweep: {
          "0%": { transform: "translateX(-100%)" },
          "100%": { transform: "translateX(100%)" },
        },
        pulseRing: {
          "0%, 100%": { opacity: "1", transform: "scale(1)" },
          "50%": { opacity: "0.4", transform: "scale(0.96)" },
        },
        scanner: {
          "0%": { top: "0%" },
          "50%": { top: "100%" },
          "100%": { top: "0%" },
        },
      },
      animation: {
        sweep: "sweep 2.4s linear infinite",
        pulseRing: "pulseRing 2s ease-in-out infinite",
        scanner: "scanner 4s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Base Palette: Clean Financial Light / Pearl & Navy
        forensic: {
          bg: "#F8FAFC",        // Pearl canvas / Slate 50
          surface: "#FFFFFF",   // Pure white cards / panels
          panel: "#F1F5F9",     // Soft Slate 100 panel surfaces
          panelHover: "#E2E8F0",// Slate 200 hover
          accent: "#2563EB",    // Royal Cobalt Blue accent
          accentMuted: "rgba(37, 99, 235, 0.10)",
          muted: "#64748B",     // Secondary text / metadata / borders
          border: "#E2E8F0",    // Crisp light border
          borderBright: "#CBD5E1", // Slate 300 border
          text: "#0F172A",      // Deep Navy / Slate 900 primary text
        },
        // Backward-compatible color aliases for Pearl & Navy Light theme
        ink: {
          950: "#F8FAFC",       // Pearl Canvas
          900: "#FFFFFF",       // White card surface
          850: "#F1F5F9",       // Elevated Slate panel
          800: "#E2E8F0",       // Hover surface
          750: "#CBD5E1",
          700: "#E2E8F0",       // Border
          600: "#CBD5E1",
          500: "#2563EB",       // Royal Blue Accent
          400: "#64748B",       // Slate Muted Text
          300: "#0F172A",       // Deep Navy Primary Text
        },
        paper: {
          DEFAULT: "#0F172A",   // Primary Navy Text
          dim: "#475569",       // Slate 600
          muted: "#64748B",     // Slate 500
          bright: "#0F172A",    // Deep Navy
        },
        mute: {
          DEFAULT: "#64748B",
          dim: "#475569",
        },
        signal: {
          DEFAULT: "#2563EB",   // Royal Blue Accent
          dim: "#64748B",
          bg: "rgba(37, 99, 235, 0.08)",
          border: "rgba(37, 99, 235, 0.25)",
        },
        // Security States (Restrained semantic colors for light background)
        safe: {
          DEFAULT: "#059669",   // Emerald 600
          dim: "#047857",
          bg: "#ECFDF5",        // Soft Emerald 50
          border: "#A7F3D0",    // Emerald 200
        },
        warn: {
          DEFAULT: "#D97706",   // Amber 600
          dim: "#B45309",
          bg: "#FFFBEB",        // Soft Amber 50
          border: "#FDE68A",    // Amber 200
        },
        danger: {
          DEFAULT: "#DC2626",   // Red 600
          dim: "#B91C1C",
          bg: "#FEF2F2",        // Soft Red 50
          border: "#FECACA",    // Red 200
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
          DEFAULT: "#2563EB",
          dim: "#64748B",
          bg: "rgba(37, 99, 235, 0.08)",
          border: "rgba(37, 99, 235, 0.20)",
        },
      },
      fontFamily: {
        sans: ["'Plus Jakarta Sans'", "ui-sans-serif", "system-ui", "-apple-system", "sans-serif"],
        mono: ["'JetBrains Mono'", "ui-monospace", "monospace"],
      },
      boxShadow: {
        none: "none",
        panel: "0 1px 3px 0 rgba(15, 23, 42, 0.06), 0 1px 2px -1px rgba(15, 23, 42, 0.04), 0 0 0 1px #E2E8F0",
        elevated: "0 10px 25px -5px rgba(15, 23, 42, 0.08), 0 8px 10px -6px rgba(15, 23, 42, 0.04), 0 0 0 1px #CBD5E1",
        signal: "0 0 15px -3px rgba(37, 99, 235, 0.25)",
        "glow-danger": "0 0 15px -2px rgba(220, 38, 38, 0.25)",
        "glow-safe": "0 0 15px -3px rgba(5, 150, 105, 0.25)",
        "glow-warn": "0 0 15px -3px rgba(217, 119, 6, 0.25)",
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

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#090d14",
          900: "#0e131d",
          850: "#131926",
          800: "#172030",
          750: "#1d283c",
          700: "#24324a",
          600: "#2e3f5c",
          500: "#445a80",
          400: "#657d9f",
          300: "#93a6c2",
        },
        paper: {
          DEFAULT: "#f1f5f9",
          dim: "#94a3b8",
          muted: "#64748b",
          bright: "#ffffff",
        },
        mute: {
          DEFAULT: "#7e8f9f",
          dim: "#4e5e70",
        },
        signal: {
          DEFAULT: "#00e5ff",
          dim: "#00b4d8",
          bg: "rgba(0, 229, 255, 0.08)",
          border: "rgba(0, 229, 255, 0.25)",
        },
        safe: {
          DEFAULT: "#10b981",
          dim: "#059669",
          bg: "rgba(16, 185, 129, 0.08)",
          border: "rgba(16, 185, 129, 0.25)",
        },
        warn: {
          DEFAULT: "#f59e0b",
          dim: "#d97706",
          bg: "rgba(245, 158, 11, 0.08)",
          border: "rgba(245, 158, 11, 0.25)",
        },
        danger: {
          DEFAULT: "#f43f5e",
          dim: "#e11d48",
          bg: "rgba(244, 63, 94, 0.08)",
          border: "rgba(244, 63, 94, 0.28)",
        },
        intel: {
          DEFAULT: "#818cf8",
          dim: "#6366f1",
          bg: "rgba(129, 140, 248, 0.08)",
          border: "rgba(129, 140, 248, 0.25)",
        },
      },
      fontFamily: {
        sans: ["'Plus Jakarta Sans'", "ui-sans-serif", "system-ui", "-apple-system", "sans-serif"],
        mono: ["'JetBrains Mono'", "ui-monospace", "monospace"],
      },
      boxShadow: {
        none: "none",
        panel: "0 10px 30px -5px rgba(0,0,0,0.6), 0 0 0 1px rgba(255,255,255,0.03)",
        elevated: "0 16px 40px -8px rgba(0,0,0,0.7), 0 0 0 1px rgba(255,255,255,0.05)",
        signal: "0 0 15px -3px rgba(0,240,255,0.25)",
        "glow-danger": "0 0 20px -3px rgba(239,68,68,0.30)",
        "glow-safe": "0 0 20px -3px rgba(16,185,129,0.30)",
        "glow-warn": "0 0 20px -3px rgba(245,158,11,0.30)",
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

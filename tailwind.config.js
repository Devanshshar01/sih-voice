/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Exact Image Palette Tokens
        deepBlue: {
          DEFAULT: "#2A4D88",
          hover: "#213D6C",
          bg: "rgba(42, 77, 136, 0.08)",
          border: "rgba(42, 77, 136, 0.25)",
        },
        concerto: {
          DEFAULT: "#D9D9D8",
          light: "#F0F0EF",
          dark: "#C6C6C4",
        },
        glacialSalt: {
          DEFAULT: "#B1BBC8",
          light: "#CBD3DD",
          dark: "#95A1B2",
        },
        // Base Palette Mapping
        forensic: {
          bg: "#E8EAEF",        // Soft Concerto / Glacial tint canvas
          surface: "#FFFFFF",   // Pure white card surface
          panel: "#D9D9D8",     // Concerto panel background
          panelHover: "#B1BBC8",// Glacial Salt hover
          accent: "#2A4D88",    // Deep Blue primary accent
          accentMuted: "rgba(42, 77, 136, 0.12)",
          muted: "#4A5B70",     // Muted Deep Glacial Salt text
          border: "#B1BBC8",    // Glacial Salt border
          borderBright: "#2A4D88",
          text: "#122138",      // Midnight Navy primary text
        },
        // Backward-compatible color aliases
        ink: {
          950: "#E8EAEF",       // Canvas
          900: "#FFFFFF",       // White card surface
          850: "#D9D9D8",       // Concerto panel
          800: "#B1BBC8",       // Glacial Salt hover
          750: "#B1BBC8",
          700: "#B1BBC8",       // Border
          600: "#B1BBC8",
          500: "#2A4D88",       // Deep Blue Accent
          400: "#4A5B70",       // Glacial Salt Muted Text
          300: "#122138",       // Midnight Navy Primary Text
        },
        paper: {
          DEFAULT: "#122138",   // Midnight Navy Primary Text
          dim: "#2A4D88",       // Deep Blue
          muted: "#4A5B70",     // Muted Glacial Salt
          bright: "#122138",
        },
        mute: {
          DEFAULT: "#4A5B70",
          dim: "#2A4D88",
        },
        signal: {
          DEFAULT: "#2A4D88",   // Deep Blue Accent
          dim: "#4A5B70",
          bg: "rgba(42, 77, 136, 0.08)",
          border: "rgba(42, 77, 136, 0.25)",
        },
        // Security States (Restrained semantic colors)
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
          DEFAULT: "#4A5B70",
          bg: "#D9D9D8",
          border: "#B1BBC8",
        },
        intel: {
          DEFAULT: "#2A4D88",
          dim: "#4A5B70",
          bg: "rgba(42, 77, 136, 0.08)",
          border: "rgba(42, 77, 136, 0.20)",
        },
      },
      fontFamily: {
        sans: ["'Plus Jakarta Sans'", "ui-sans-serif", "system-ui", "-apple-system", "sans-serif"],
        mono: ["'JetBrains Mono'", "ui-monospace", "monospace"],
      },
      boxShadow: {
        none: "none",
        panel: "0 1px 3px 0 rgba(42, 77, 136, 0.08), 0 1px 2px -1px rgba(42, 77, 136, 0.04), 0 0 0 1px #B1BBC8",
        elevated: "0 10px 25px -5px rgba(42, 77, 136, 0.12), 0 8px 10px -6px rgba(42, 77, 136, 0.06), 0 0 0 1px #B1BBC8",
        signal: "0 0 15px -3px rgba(42, 77, 136, 0.30)",
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

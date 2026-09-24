/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#0D0D0D", // Deep rich black
          900: "#141414", // Surface elevation 1
          850: "#1C1C1C", // Surface elevation 2
          800: "#222222", // Surface elevation hover
          750: "#2B2B2B", // Charcoal container swatch
          700: "#383838", // Subdued border
          600: "#4A4A4A", // Divider line
          500: "#666666", // Medium muted icon/border
          400: "#8E8E8E", // Silver grey swatch
          300: "#B0B0B0", // Light silver grey
        },
        paper: {
          DEFAULT: "#E6E6E6", // Primary light silver text swatch
          dim: "#8E8E8E",     // Secondary text swatch
          muted: "#666666",   // Muted caption text
          bright: "#FFFFFF",  // Pure white highlight
        },
        mute: {
          DEFAULT: "#8E8E8E",
          dim: "#444444",
        },
        signal: {
          DEFAULT: "#E6E6E6",
          dim: "#B0B0B0",
          bg: "rgba(230, 230, 230, 0.08)",
          border: "rgba(230, 230, 230, 0.25)",
        },
        safe: {
          DEFAULT: "#D4D4D4",
          dim: "#999999",
          bg: "rgba(212, 212, 212, 0.08)",
          border: "rgba(212, 212, 212, 0.25)",
        },
        warn: {
          DEFAULT: "#8E8E8E",
          dim: "#666666",
          bg: "rgba(142, 142, 142, 0.08)",
          border: "rgba(142, 142, 142, 0.25)",
        },
        danger: {
          DEFAULT: "#FFFFFF",
          dim: "#CCCCCC",
          bg: "rgba(255, 255, 255, 0.12)",
          border: "rgba(255, 255, 255, 0.40)",
        },
        intel: {
          DEFAULT: "#B0B0B0",
          dim: "#8E8E8E",
          bg: "rgba(176, 176, 176, 0.08)",
          border: "rgba(176, 176, 176, 0.25)",
        },
      },
      fontFamily: {
        sans: ["'Plus Jakarta Sans'", "ui-sans-serif", "system-ui", "-apple-system", "sans-serif"],
        mono: ["'JetBrains Mono'", "ui-monospace", "monospace"],
      },
      boxShadow: {
        none: "none",
        panel: "0 10px 30px -5px rgba(0,0,0,0.85), 0 0 0 1px rgba(230,230,230,0.08)",
        elevated: "0 16px 40px -8px rgba(0,0,0,0.95), 0 0 0 1px rgba(230,230,230,0.14)",
        signal: "0 0 20px -3px rgba(230,230,230,0.30)",
        "glow-danger": "0 0 22px -2px rgba(255,255,255,0.40)",
        "glow-safe": "0 0 20px -3px rgba(212,212,212,0.25)",
        "glow-warn": "0 0 20px -3px rgba(142,142,142,0.25)",
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

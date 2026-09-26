/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Exact Brand Foundation: Blue Forensic Intelligence
        blueWhale: {
          DEFAULT: "#1E3347",
          deep: "#152535",
          surface: "#243A4F",
        },
        inkjet: {
          DEFAULT: "#3F5874",
          light: "#4A6788",
          dark: "#2F445B",
        },
        sailing: {
          DEFAULT: "#899FBC",
          hover: "#A0B4CF",
          glow: "rgba(137, 159, 188, 0.35)",
        },
        shallowSea: {
          DEFAULT: "#A3B8CA",
          muted: "rgba(163, 184, 202, 0.65)",
          border: "rgba(163, 184, 202, 0.22)",
        },
        ephemeralBlue: {
          DEFAULT: "#CCD3E0",
          bright: "#E8ECF4",
        },
        // Base Palette Mapping
        forensic: {
          bg: "#1E3347",        // Blue Whale
          surface: "#3F5874",   // Inkjet
          panel: "#2A4259",     // Elevated Blue Whale / Inkjet surface
          panelHover: "#4A6788",// Inkjet hover
          accent: "#899FBC",    // Sailing primary accent
          accentMuted: "rgba(137, 159, 188, 0.15)",
          muted: "#A3B8CA",     // Shallow Sea secondary text / metadata
          border: "rgba(163, 184, 202, 0.22)", // Shallow Sea border
          borderBright: "#899FBC",
          text: "#CCD3E0",      // Ephemeral Blue primary text
        },
        // Backward-compatible color aliases
        ink: {
          950: "#1E3347",       // Blue Whale
          900: "#243A4F",       // Deep Surface
          850: "#3F5874",       // Inkjet
          800: "#4A6788",       // Inkjet hover
          750: "#2A4259",
          700: "rgba(163, 184, 202, 0.22)",
          600: "rgba(163, 184, 202, 0.35)",
          500: "#899FBC",       // Sailing Accent
          400: "#A3B8CA",       // Shallow Sea Muted Text
          300: "#CCD3E0",       // Ephemeral Blue Primary Text
        },
        paper: {
          DEFAULT: "#CCD3E0",   // Ephemeral Blue
          dim: "#A3B8CA",       // Shallow Sea
          muted: "#899FBC",     // Sailing
          bright: "#E8ECF4",
        },
        mute: {
          DEFAULT: "#A3B8CA",
          dim: "#899FBC",
        },
        signal: {
          DEFAULT: "#899FBC",   // Sailing
          dim: "#A3B8CA",
          bg: "rgba(137, 159, 188, 0.12)",
          border: "rgba(137, 159, 188, 0.30)",
        },
        // Security States (Restrained semantic colors)
        safe: {
          DEFAULT: "#10B981",   // Restrained Green
          dim: "#059669",
          bg: "rgba(16, 185, 129, 0.12)",
          border: "rgba(16, 185, 129, 0.30)",
        },
        warn: {
          DEFAULT: "#F59E0B",   // Restrained Amber
          dim: "#D97706",
          bg: "rgba(245, 158, 11, 0.12)",
          border: "rgba(245, 158, 11, 0.30)",
        },
        danger: {
          DEFAULT: "#EF4444",   // Restrained Red
          dim: "#DC2626",
          bg: "rgba(239, 68, 68, 0.15)",
          border: "rgba(239, 68, 68, 0.35)",
        },
        degraded: {
          DEFAULT: "#D97706",
          bg: "rgba(217, 119, 6, 0.12)",
          border: "rgba(217, 119, 6, 0.25)",
        },
        offline: {
          DEFAULT: "#64748B",
          bg: "rgba(100, 116, 139, 0.12)",
          border: "rgba(100, 116, 139, 0.25)",
        },
        intel: {
          DEFAULT: "#899FBC",
          dim: "#A3B8CA",
          bg: "rgba(137, 159, 188, 0.12)",
          border: "rgba(137, 159, 188, 0.25)",
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

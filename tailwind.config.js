/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#000000",
          900: "#000000",
          800: "#0a0a0a",
          700: "#1c1c1c",
          600: "#2a2a2a",
          500: "#3f3f3f",
        },
        paper: {
          DEFAULT: "#fafafa",
          dim: "#d4d4d4",
        },
        mute: {
          DEFAULT: "#a3a3a3",
          dim: "#737373",
        },
        signal: {
          DEFAULT: "#e5e5e5",
          dim: "#a3a3a3",
          bg: "rgba(255,255,255,0.06)",
        },
        safe: {
          DEFAULT: "#7fb694",
          bg: "rgba(127,182,148,0.08)",
        },
        warn: {
          DEFAULT: "#cfa86b",
          bg: "rgba(207,168,107,0.08)",
        },
        danger: {
          DEFAULT: "#d08580",
          bg: "rgba(208,133,128,0.10)",
        },
      },
      fontFamily: {
        sans: ["'IBM Plex Sans'", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["'IBM Plex Mono'", "ui-monospace", "'SFMono-Regular'", "monospace"],
      },
      boxShadow: {
        none: "none",
        panel: "0 16px 42px rgba(0,0,0,0.45)",
        signal: "none",
      },
      keyframes: {
        sweep: {
          "0%": { transform: "translateX(-100%)" },
          "100%": { transform: "translateX(100%)" },
        },
        pulseRing: {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.45" },
        },
      },
      animation: {
        sweep: "sweep 2.4s linear infinite",
        pulseRing: "pulseRing 1.6s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

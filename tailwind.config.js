/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#080b0e",
          900: "#0d1217",
          800: "#151c23",
          700: "#202a33",
          600: "#2d3944",
          500: "#42515d",
        },
        paper: {
          DEFAULT: "#edf1f3",
          dim: "#c7d0d6",
        },
        mute: {
          DEFAULT: "#8b99a3",
          dim: "#64727c",
        },
        signal: {
          DEFAULT: "#8bb6c8",
          dim: "#5f8798",
          bg: "rgba(139,182,200,0.10)",
        },
        safe: {
          DEFAULT: "#78b79a",
          bg: "rgba(120,183,154,0.10)",
        },
        warn: {
          DEFAULT: "#d5a766",
          bg: "rgba(213,167,102,0.10)",
        },
        danger: {
          DEFAULT: "#db817b",
          bg: "rgba(219,129,123,0.12)",
        },
      },
      fontFamily: {
        sans: ["'IBM Plex Sans'", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["'IBM Plex Mono'", "ui-monospace", "'SFMono-Regular'", "monospace"],
      },
      boxShadow: {
        none: "none",
        panel: "0 16px 42px rgba(0,0,0,0.18)",
        signal: "0 0 0 1px rgba(139,182,200,0.12), 0 10px 28px rgba(0,0,0,0.16)",
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

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#050809",
          900: "#070c10",
          800: "#0f171d",
          700: "#1b262e",
          600: "#25333c",
          500: "#324450",
        },
        paper: {
          DEFAULT: "#e7eef2",
          dim: "#c3ced4",
        },
        mute: {
          DEFAULT: "#7c8d98",
          dim: "#546069",
        },
        signal: {
          DEFAULT: "#4fc3f7",
          dim: "#2a8fbd",
          bg: "rgba(79,195,247,0.10)",
        },
        safe: {
          DEFAULT: "#34d399",
          bg: "rgba(52,211,153,0.10)",
        },
        warn: {
          DEFAULT: "#f5a524",
          bg: "rgba(245,165,36,0.10)",
        },
        danger: {
          DEFAULT: "#f0554a",
          bg: "rgba(240,85,74,0.12)",
        },
      },
      fontFamily: {
        sans: ["'Space Grotesk'", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["'IBM Plex Mono'", "ui-monospace", "'SFMono-Regular'", "monospace"],
      },
      boxShadow: {
        none: "none",
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

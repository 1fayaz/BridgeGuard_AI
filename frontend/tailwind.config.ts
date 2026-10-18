import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "var(--background)",
        foreground: "var(--foreground)",
        // BridgeGuard AI design tokens (from the Main/Bridge/Alerts/Agents/Reports design files).
        navy: "#00325D",
        "navy-deep": "#0B1F3A",
        "navy-text": "#3D5068",
        "navy-muted": "#4B5D73",
        blue: "#0A63B8",
        "blue-bright": "#0081D3",
        "page-bg": "#F1F5F9",
        border: {
          DEFAULT: "#D9E2EC",
          light: "#E3EAF2",
        },
        safe: { DEFAULT: "#097F37", bg: "#E4F4EA", text: "#0B5F2B" },
        watch: { DEFAULT: "#E0A100", bg: "#FFF3D2", text: "#7A5200" },
        warn: { DEFAULT: "#D45A00", bg: "#FFE7D3", text: "#9A4300" },
        urgent: { DEFAULT: "#C62828", bg: "#FDE6E6", text: "#A31F1F" },
        unknown: { DEFAULT: "#6B7B8C", bg: "#EBEEF2", text: "#3D4A59" },
      },
      fontFamily: {
        sans: ["Figtree", "system-ui", "sans-serif"],
        display: ["Montserrat", "sans-serif"],
      },
    },
  },
  plugins: [],
};
export default config;

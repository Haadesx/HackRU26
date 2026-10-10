/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Atkinson Hyperlegible"', "Verdana", "system-ui", "sans-serif"],
      },
      colors: {
        // Brand and surfaces
        sky: "#9CC3EC",
        ice: "#D2E7FB",
        mist: "#E8F1FC",
        page: "#F5F9FD",
        line: "#D8E3F0",
        "line-soft": "#E4ECF5",
        track: "#EEF3F9",
        // Text
        navy: "#1F3A68",
        ink: "#152238",
        "ink-soft": "#46546B",
        "ink-muted": "#66707F",
        // Status
        ok: { DEFAULT: "#22613B", fill: "#DCF1E3", tint: "#E9F5ED", pill: "#8FCFA5" },
        low: { DEFAULT: "#6E4700", fill: "#FCEFCC", tint: "#FDF5DC", pill: "#F2CF6B", line: "#EFCF7D" },
        urgent: { DEFAULT: "#9A1F14", fill: "#FBDCD6", tint: "#FDE8E4", pill: "#EE9A8E", line: "#F0A79C" },
      },
      borderRadius: { card: "18px" },
      boxShadow: {
        dialog: "0 24px 60px rgba(21, 34, 56, 0.3)",
      },
    },
  },
  plugins: [],
};

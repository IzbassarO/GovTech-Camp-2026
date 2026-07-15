import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/app/**/*.{ts,tsx}",
    "./src/components/**/*.{ts,tsx}",
    "./src/lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Deep navy for navigation / brand surfaces.
        navy: {
          950: "#0b1220",
          900: "#0f172a",
          800: "#1e293b",
          700: "#334155",
        },
        // Restrained teal accent.
        accent: {
          50: "#effcfa",
          100: "#c9f3ec",
          500: "#14b8a6",
          600: "#0d9488",
          700: "#0f766e",
        },
      },
      fontFamily: {
        sans: [
          "var(--font-inter)",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
      },
      boxShadow: {
        card: "0 1px 2px rgba(15, 23, 42, 0.06), 0 1px 3px rgba(15, 23, 42, 0.04)",
        drawer: "-8px 0 24px rgba(15, 23, 42, 0.12)",
      },
    },
  },
  plugins: [],
};

export default config;

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
        // Deliberate, self-hosted-free system stack: zero network requests at
        // build or runtime, so the demo never depends on an external font CDN.
        // Every platform in this list has strong Cyrillic coverage.
        sans: [
          "ui-sans-serif",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
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

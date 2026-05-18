import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./lib/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      // ------------------------------------------------------------------
      // Color tokens — reference CSS custom properties from globals.css.
      // "rgb(var(...) / <alpha-value>)" enables Tailwind opacity modifiers
      // (e.g. bg-bg-base/80) to work correctly with CSS variables.
      // ------------------------------------------------------------------
      colors: {
        // Surfaces
        "bg-base":     "rgb(var(--color-bg-base)     / <alpha-value>)",
        "bg-elevated": "rgb(var(--color-bg-elevated) / <alpha-value>)",
        "pane-bg":     "rgb(var(--color-pane-bg)     / <alpha-value>)",

        // Text
        "text-primary":   "rgb(var(--color-text-primary)   / <alpha-value>)",
        "text-secondary": "rgb(var(--color-text-secondary) / <alpha-value>)",
        "text-tertiary":  "rgb(var(--color-text-tertiary)  / <alpha-value>)",
        "text-muted":     "rgb(var(--color-text-muted)     / <alpha-value>)",
        "text-ghost":     "rgb(var(--color-text-ghost)     / <alpha-value>)",
        "text-label":     "rgb(var(--color-text-label)     / <alpha-value>)",

        // Borders
        "border-subtle":  "rgb(var(--color-border-subtle)  / <alpha-value>)",
        "border-default": "rgb(var(--color-border-default) / <alpha-value>)",
        "border-strong":  "rgb(var(--color-border-strong)  / <alpha-value>)",

        // Accent
        "accent":           "rgb(var(--color-accent)          / <alpha-value>)",
        "accent-hover":     "rgb(var(--color-accent-hover)    / <alpha-value>)",
        "accent-strong":    "rgb(var(--color-accent-strong)   / <alpha-value>)",
        "accent-emphasis":  "rgb(var(--color-accent-emphasis) / <alpha-value>)",
        "accent-border":    "rgb(var(--color-accent-border)   / <alpha-value>)",
        "accent-faint":     "rgb(var(--color-accent-faint)    / <alpha-value>)",
        "accent-soft":      "rgb(var(--color-accent-soft)     / <alpha-value>)",

        // States
        "error-bg":       "rgb(var(--color-error-bg)       / <alpha-value>)",
        "error-border":   "rgb(var(--color-error-border)   / <alpha-value>)",
        "error-text":     "rgb(var(--color-error-text)     / <alpha-value>)",
        "warning-bg":     "rgb(var(--color-warning-bg)     / <alpha-value>)",
        "warning-border": "rgb(var(--color-warning-border) / <alpha-value>)",
        "warning-text":   "rgb(var(--color-warning-text)   / <alpha-value>)",
        "warning-icon":   "rgb(var(--color-warning-icon)   / <alpha-value>)",
        "warning-strong": "rgb(var(--color-warning-strong) / <alpha-value>)",
      },

      // ------------------------------------------------------------------
      // Border radius — override to route through CSS vars.
      // Values match Tailwind's defaults exactly; the override means Phase
      // 2b can change all radii by editing --radius-* in globals.css.
      // ------------------------------------------------------------------
      borderRadius: {
        md: "var(--radius-md)", // 0.375rem — inputs, buttons
        lg: "var(--radius-lg)", // 0.5rem   — larger containers
      },

      // ------------------------------------------------------------------
      // Shadows — semantic aliases referencing CSS vars.
      // ------------------------------------------------------------------
      boxShadow: {
        subtle:   "var(--shadow-subtle)",
        raised:   "var(--shadow-raised)",
        floating: "var(--shadow-floating)",
      },
    },
  },
  plugins: [],
};

export default config;

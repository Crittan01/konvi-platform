import type { Config } from "tailwindcss"

const config = {
  // darkMode removido (F1 2026-07-04): no existe theming oscuro — decisión
  // founder: diferir dark mode a post-Platform Console. Re-agregar cuando
  // exista el bloque .dark + toggle reales.
  content: [
    './pages/**/*.{ts,tsx}',
    './components/**/*.{ts,tsx}',
    './app/**/*.{ts,tsx}',
    './src/**/*.{ts,tsx}',
  ],
  prefix: "",
  theme: {
    extend: {
      fontFamily: {
        // BLOQUE E: incluir las fuentes de emoji a color en el stack `sans`. `body` usa
        // `font-sans` (layout.tsx) y Tailwind lo resuelve a ESTA lista → sin las fuentes de
        // emoji, pisaba el stack de `html` (fix A7 en globals.css) y los emojis se veían como
        // "tofu" (□). Mantener sincronizado con el stack de `html` en globals.css.
        sans: [
          'var(--font-inter)', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto',
          'Apple Color Emoji', 'Segoe UI Emoji', 'Noto Color Emoji', 'Twemoji Mozilla',
          'sans-serif',
        ],
      },
      colors: {
        // F1 2026-07-04: se ELIMINÓ el recode global de emerald/amber 300-500
        // ("+brillo, +saturación") — codificaba la violación de la regla de
        // paleta (shades fluorescentes ilegibles sobre el canvas crema).
        // Regla vigente: sobre fondos CLAROS texto/borders usan shade 700;
        // 300-400 solo sobre superficies OSCURAS (sidebar/topbar).
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      keyframes: {
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
} satisfies Config

export default config

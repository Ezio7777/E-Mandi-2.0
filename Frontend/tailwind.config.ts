import type { Config } from "tailwindcss";
import animate from "tailwindcss-animate";

const v = (n: string) => `hsl(var(--${n}))`;
const pair = (n: string) => ({ DEFAULT: v(n), foreground: v(`${n}-foreground`) });

const config: Config = {
  darkMode: ["class"],
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    container: { center: true, padding: { DEFAULT: "1rem", sm: "1.5rem", lg: "2rem" }, screens: { "2xl": "1400px" } },
    extend: {
      screens: { xs: "375px" },
      colors: {
        border: v("border"), input: v("input"), ring: v("ring"),
        background: v("background"), foreground: v("foreground"),
        surface: { DEFAULT: v("surface"), raised: v("surface-raised") },
        primary: { ...pair("primary"), soft: v("primary-soft") },
        secondary: pair("secondary"), muted: pair("muted"), accent: pair("accent"),
        card: pair("card"), popover: pair("popover"),
        success: pair("success"), warning: pair("warning"), danger: pair("danger"),
        destructive: pair("danger"),
        grade: { a: v("grade-a"), b: v("grade-b"), c: v("grade-c") },
      },
      borderRadius: { lg: "var(--radius)", md: "calc(var(--radius) - 2px)", sm: "calc(var(--radius) - 4px)" },
      fontFamily: {
        sans: ["var(--font-sans)", "var(--font-hindi)", "var(--font-kannada)", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "var(--font-sans)", "system-ui", "sans-serif"],
      },
      minHeight: { touch: "2.75rem" },
      minWidth: { touch: "2.75rem" },
      keyframes: {
        shimmer: { "100%": { transform: "translateX(100%)" } },
        "pulse-ring": { "0%": { transform: "scale(0.9)", opacity: "0.6" }, "100%": { transform: "scale(1.6)", opacity: "0" } },
      },
      animation: { shimmer: "shimmer 1.6s infinite", "pulse-ring": "pulse-ring 1.4s ease-out infinite" },
    },
  },
  plugins: [animate],
};
export default config;

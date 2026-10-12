import { z } from "zod";

const blank = (v: unknown) => (typeof v === "string" && v.trim() === "" ? undefined : v);

const schema = z.object({
  NEXT_PUBLIC_API_URL: z.preprocess(blank, z.string().url().optional()),
  NEXT_PUBLIC_DEMO_MODE: z.preprocess(blank, z.enum(["true", "false"]).optional()),
  NEXT_PUBLIC_WS_URL: z.preprocess(blank, z.string().url().optional()),
  NEXT_PUBLIC_GOOGLE_CLIENT_ID: z.preprocess(blank, z.string().optional()),
  NEXT_PUBLIC_PAYMENT_PUBLIC_KEY: z.preprocess(blank, z.string().optional()),
  NEXT_PUBLIC_APP_ENV: z.enum(["development", "staging", "production"]).default("development"),
});

// Literal reads so Next.js can inline NEXT_PUBLIC_* values.
const parsed = schema.safeParse({
  NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,
  NEXT_PUBLIC_DEMO_MODE: process.env.NEXT_PUBLIC_DEMO_MODE,
  NEXT_PUBLIC_WS_URL: process.env.NEXT_PUBLIC_WS_URL,
  NEXT_PUBLIC_GOOGLE_CLIENT_ID: process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID,
  NEXT_PUBLIC_PAYMENT_PUBLIC_KEY: process.env.NEXT_PUBLIC_PAYMENT_PUBLIC_KEY,
  NEXT_PUBLIC_APP_ENV: process.env.NEXT_PUBLIC_APP_ENV,
});

if (!parsed.success && !process.env.SKIP_ENV_VALIDATION) {
  const issues = parsed.error.issues.map((i) => `  - ${i.path.join(".")}: ${i.message}`).join("\n");
  throw new Error(`Invalid environment configuration:\n${issues}`);
}

const data = parsed.success
  ? parsed.data
  : {
      NEXT_PUBLIC_API_URL: undefined, NEXT_PUBLIC_DEMO_MODE: undefined, NEXT_PUBLIC_WS_URL: undefined,
      NEXT_PUBLIC_GOOGLE_CLIENT_ID: undefined, NEXT_PUBLIC_PAYMENT_PUBLIC_KEY: undefined, NEXT_PUBLIC_APP_ENV: "development" as const,
    };

/**
 * Demo mode = built-in sample data answered inside the browser, no backend needed (e.g. a bare Vercel deploy).
 *  - NEXT_PUBLIC_DEMO_MODE=true  → always demo
 *  - NEXT_PUBLIC_DEMO_MODE=false → always real backend (NEXT_PUBLIC_API_URL required)
 *  - unset                        → demo when no NEXT_PUBLIC_API_URL is configured, real backend otherwise
 */
const demoMode = data.NEXT_PUBLIC_DEMO_MODE === "true" || (data.NEXT_PUBLIC_DEMO_MODE !== "false" && !data.NEXT_PUBLIC_API_URL);

if (!demoMode && !data.NEXT_PUBLIC_API_URL && !process.env.SKIP_ENV_VALIDATION) {
  throw new Error("NEXT_PUBLIC_DEMO_MODE=false requires NEXT_PUBLIC_API_URL to be set.");
}

const apiUrl = (data.NEXT_PUBLIC_API_URL ?? "").replace(/\/+$/, "");

export const env = {
  demoMode,
  apiUrl,
  wsUrl: demoMode ? "" : (data.NEXT_PUBLIC_WS_URL ?? apiUrl.replace(/^http/, "ws")).replace(/\/+$/, ""),
  googleClientId: data.NEXT_PUBLIC_GOOGLE_CLIENT_ID,
  paymentPublicKey: data.NEXT_PUBLIC_PAYMENT_PUBLIC_KEY,
  appEnv: data.NEXT_PUBLIC_APP_ENV,
  isProd: data.NEXT_PUBLIC_APP_ENV === "production",
  isGoogleEnabled: Boolean(data.NEXT_PUBLIC_GOOGLE_CLIENT_ID) && !demoMode,
} as const;

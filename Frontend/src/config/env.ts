import { z } from "zod";

const blank = (v: unknown) => (typeof v === "string" && v.trim() === "" ? undefined : v);

const schema = z.object({
  NEXT_PUBLIC_API_URL: z.string().url(),
  NEXT_PUBLIC_WS_URL: z.preprocess(blank, z.string().url().optional()),
  NEXT_PUBLIC_GOOGLE_CLIENT_ID: z.preprocess(blank, z.string().optional()),
  NEXT_PUBLIC_PAYMENT_PUBLIC_KEY: z.preprocess(blank, z.string().optional()),
  NEXT_PUBLIC_APP_ENV: z.enum(["development", "staging", "production"]).default("development"),
});

// Literal reads so Next.js can inline NEXT_PUBLIC_* values.
const parsed = schema.safeParse({
  NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,
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
      NEXT_PUBLIC_API_URL: "http://localhost:8000",
      NEXT_PUBLIC_WS_URL: undefined,
      NEXT_PUBLIC_GOOGLE_CLIENT_ID: undefined,
      NEXT_PUBLIC_PAYMENT_PUBLIC_KEY: undefined,
      NEXT_PUBLIC_APP_ENV: "development" as const,
    };

const apiUrl = data.NEXT_PUBLIC_API_URL.replace(/\/+$/, "");

export const env = {
  apiUrl,
  wsUrl: (data.NEXT_PUBLIC_WS_URL ?? apiUrl.replace(/^http/, "ws")).replace(/\/+$/, ""),
  googleClientId: data.NEXT_PUBLIC_GOOGLE_CLIENT_ID,
  paymentPublicKey: data.NEXT_PUBLIC_PAYMENT_PUBLIC_KEY,
  appEnv: data.NEXT_PUBLIC_APP_ENV,
  isProd: data.NEXT_PUBLIC_APP_ENV === "production",
  isGoogleEnabled: Boolean(data.NEXT_PUBLIC_GOOGLE_CLIENT_ID),
} as const;

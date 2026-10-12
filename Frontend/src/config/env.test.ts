import { afterEach, describe, expect, it, vi } from "vitest";

async function load(vars: Record<string, string>) {
  vi.resetModules();
  for (const k of ["NEXT_PUBLIC_API_URL", "NEXT_PUBLIC_DEMO_MODE", "NEXT_PUBLIC_WS_URL"]) vi.stubEnv(k, "");
  for (const [k, v] of Object.entries(vars)) vi.stubEnv(k, v);
  return (await import("./env")).env;
}
afterEach(() => vi.unstubAllEnvs());

describe("demo mode selection", () => {
  it("is on when no backend URL is configured (bare Vercel deploy)", async () => {
    const env = await load({});
    expect(env.demoMode).toBe(true);
    expect(env.wsUrl).toBe("");
  });
  it("is off when a backend URL is set", async () => {
    const env = await load({ NEXT_PUBLIC_API_URL: "https://api.example.com/" });
    expect(env.demoMode).toBe(false);
    expect(env.apiUrl).toBe("https://api.example.com");
    expect(env.wsUrl).toBe("wss://api.example.com");
  });
  it("can be forced on even with a backend URL", async () => {
    expect((await load({ NEXT_PUBLIC_API_URL: "https://api.example.com", NEXT_PUBLIC_DEMO_MODE: "true" })).demoMode).toBe(true);
  });
  it("refuses to start in real-backend mode without a URL", async () => {
    await expect(load({ NEXT_PUBLIC_DEMO_MODE: "false" })).rejects.toThrow(/requires NEXT_PUBLIC_API_URL/);
  });
  it("rejects a malformed URL", async () => {
    await expect(load({ NEXT_PUBLIC_API_URL: "not-a-url" })).rejects.toThrow(/Invalid environment/);
  });
});

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { ROLE_PREFIX } from "@/config/routes";
import type { Role } from "@/types";
import { TOURS, tourSteps } from "./tour-steps";

const SRC = join(__dirname, "..", "..");
function files(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f);
    return statSync(p).isDirectory() ? files(p) : /\.(tsx?|ts)$/.test(f) && !/\.test\./.test(f) ? [p] : [];
  });
}
/** Every name that is actually rendered as data-tour="…" (or passed as tourId) somewhere in the app. */
const known = new Set<string>();
for (const f of files(SRC)) {
  for (const line of readFileSync(f, "utf8").split("\n")) {
    if (!/data-tour=|tourId[=:]/.test(line)) continue;
    for (const m of line.matchAll(/"([a-z][a-z0-9-]+)"/g)) known.add(m[1]!);
  }
}

const roles = Object.keys(TOURS) as Role[];

describe("tour definitions", () => {
  it("found the markers in the source (sanity check on this test)", () => {
    expect(known.has("sell-wizard")).toBe(true);
    expect(known.has("nav-dashboard")).toBe(true);
  });

  it.each(roles)("%s: every target and fallback exists in the app", (role) => {
    for (const s of TOURS[role]) {
      if (s.target) expect(known, `${s.id} target "${s.target}"`).toContain(s.target);
      if (s.fallbackTarget) expect(known, `${s.id} fallback "${s.fallbackTarget}"`).toContain(s.fallbackTarget);
    }
  });

  it.each(roles)("%s: ids are unique and routes stay inside the role's area", (role) => {
    const ids = TOURS[role].map((s) => s.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const s of TOURS[role]) if (s.route) expect(s.route.startsWith(ROLE_PREFIX[role])).toBe(true);
  });

  it("farmer wizard goals only ever move forward through the sell flow and stay in range", () => {
    const goals = TOURS.farmer.filter((s) => s.wizard).map((s) => s.wizard!.goal);
    expect(goals).toEqual([...goals].sort((a, b) => a - b));
    expect(goals.every((g) => g >= 0 && g <= 7)).toBe(true);
    for (const s of TOURS.farmer.filter((x) => x.wizard)) expect(s.route).toBe("/farmer/sell");
  });

  it("steps that describe a later screen actually drive the wizard there", () => {
    const byId = Object.fromEntries(TOURS.farmer.map((s) => [s.id, s]));
    expect(byId.f4!.wizard!.goal).toBe(4); // AI grading
    expect(byId.f5!.wizard!.goal).toBe(5); // price
    expect(byId.f6!.wizard!.goal).toBe(6); // review
    expect(byId.f3!.wizard!.sample).toBe(true);
  });

  it("the buyer requirement step fills the form, and demo-only steps are filtered out against a real backend", () => {
    expect(TOURS.buyer.find((s) => s.id === "b2")!.fill).toBe("requirement");
    expect(TOURS.buyer.some((s) => s.demoOnly)).toBe(true);
    // The unit-test environment has a backend URL configured, i.e. NOT demo mode:
    expect(tourSteps("buyer").some((s) => s.demoOnly)).toBe(false);
    expect(tourSteps("buyer")).toHaveLength(TOURS.buyer.length - TOURS.buyer.filter((s) => s.demoOnly).length);
  });
});

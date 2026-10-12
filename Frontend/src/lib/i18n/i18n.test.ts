import { describe, expect, it } from "vitest";
import { dictionaries, translate } from "./index";

const flatten = (o: unknown, prefix = ""): [string, string][] =>
  Object.entries(o as Record<string, unknown>).flatMap(([k, v]) =>
    typeof v === "string" ? [[`${prefix}${k}`, v] as [string, string]] : flatten(v, `${prefix}${k}.`),
  );

describe("i18n dictionaries", () => {
  const en = flatten(dictionaries.en);
  it.each(["hi", "kn"] as const)("%s has exactly the same keys as English and no empty strings", (loc) => {
    const other = flatten(dictionaries[loc]);
    expect(other.map(([k]) => k).sort()).toEqual(en.map(([k]) => k).sort());
    expect(other.filter(([, v]) => v.trim() === "")).toEqual([]);
  });
  it("translates and falls back to English for an unknown key", () => {
    expect(translate("hi", "nav.dashboard")).toBe("डैशबोर्ड");
    expect(translate("en", "nav.dashboard")).toBe("Dashboard");
    expect(translate("kn", "nope.missing" as never)).toBe("nope.missing");
  });
});

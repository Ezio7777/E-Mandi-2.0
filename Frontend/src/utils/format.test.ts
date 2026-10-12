import { describe, expect, it } from "vitest";
import { compactNumber, formatDate, formatNumber, formatINRCompact, formatKg, formatPerKg, formatPercent } from "./format";

describe("format utils", () => {
  it("formats price per kg without trailing decimals for whole rupees", () => {
    expect(formatPerKg(32)).toBe("₹32/kg");
    expect(formatPerKg(32.5)).toBe("₹32.50/kg");
  });
  it("formats quantity with Indian digit grouping", () => {
    expect(formatKg(125000)).toBe("1,25,000 kg");
  });
  it("formats ratios as percentages", () => {
    expect(formatPercent(0.94)).toBe("94%");
  });
  it("returns a dash for invalid dates", () => {
    expect(formatDate("nope")).toBe("—");
  });
});

describe("formatINRCompact", () => {
  it("shortens large rupee values", () => {
    expect(formatINRCompact(18450000)).toMatch(/1\.8\s?Cr/);
  });
});

describe("formatNumber", () => {
  it("caps long decimals at two places", () => {
    expect(formatNumber(27.333333333333332)).toBe("27.33");
    expect(formatNumber(14.666666666666666)).toBe("14.67");
  });
  it("drops trailing zeros and keeps Indian grouping", () => {
    expect(formatNumber(32)).toBe("32");
    expect(formatNumber(32.5)).toBe("32.5");
    expect(formatNumber(125000.256)).toBe("1,25,000.26");
  });
  it("is safe for NaN / Infinity", () => {
    expect(formatNumber(Number.NaN)).toBe("0");
  });
});

describe("compactNumber", () => {
  it("never abbreviates thousands (avoids 'T' being read as trillion)", () => {
    expect(compactNumber(1284)).toBe("1,284");
    expect(compactNumber(99999)).toBe("99,999");
  });
  it("abbreviates from one lakh upward", () => {
    expect(compactNumber(250000)).toMatch(/2\.5L/);
  });
});

import { describe, expect, it } from "vitest";
import { cropSchema, priceSchema, quantitySchema } from "./sell.schema";

describe("sell-crop schemas", () => {
  it("requires a crop name", () => expect(cropSchema.safeParse({ crop: " " }).success).toBe(false));
  it("coerces quantity from text input", () => expect(quantitySchema.parse({ quantityKg: "500" }).quantityKg).toBe(500));
  it("rejects zero and oversized quantities", () => {
    expect(quantitySchema.safeParse({ quantityKg: 0 }).success).toBe(false);
    expect(quantitySchema.safeParse({ quantityKg: 200000 }).success).toBe(false);
  });
  it("rejects negative prices", () => expect(priceSchema.safeParse({ pricePerKg: -1 }).success).toBe(false));
});

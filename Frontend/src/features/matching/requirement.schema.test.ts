import { describe, expect, it } from "vitest";
import { requirementSchema } from "./requirement.schema";

const base = { crop: "Tomato", quantityKg: "500", desiredGrade: "A", destination: "Bangalore", deliveryDate: "2999-01-01", maxBudget: "20000" };

describe("requirementSchema", () => {
  it("accepts a valid requirement and coerces numbers", () => {
    const r = requirementSchema.parse(base);
    expect(r.quantityKg).toBe(500);
  });
  it("rejects past delivery dates", () => expect(requirementSchema.safeParse({ ...base, deliveryDate: "2000-01-01" }).success).toBe(false));
  it("rejects invalid grade", () => expect(requirementSchema.safeParse({ ...base, desiredGrade: "D" }).success).toBe(false));
});

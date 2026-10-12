import { describe, expect, it } from "vitest";
import { validateFile } from "./upload.schema";

const file = (type: string, size: number) => new File([new Uint8Array(size)], "crop.jpg", { type });

describe("validateFile", () => {
  it("accepts a small jpeg", () => expect(validateFile(file("image/jpeg", 1000))).toBeNull());
  it("rejects unsupported types", () => expect(validateFile(file("application/pdf", 1000))).toMatch(/JPG, PNG or WebP/));
  it("rejects oversized photos", () => expect(validateFile(file("image/png", 9 * 1024 * 1024))).toMatch(/larger than/));
});

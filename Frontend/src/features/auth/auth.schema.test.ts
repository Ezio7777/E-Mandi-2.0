import { describe, expect, it } from "vitest";
import { loginSchema, otpSchema, phoneSchema } from "./auth.schema";

describe("auth schemas", () => {
  it("rejects malformed email", () => {
    expect(loginSchema.safeParse({ email: "abc", password: "x" }).success).toBe(false);
  });
  it("accepts valid credentials", () => {
    expect(loginSchema.safeParse({ email: "a@b.in", password: "x" }).success).toBe(true);
  });
  it("validates Indian mobile numbers", () => {
    expect(phoneSchema.safeParse({ phone: "9876543210" }).success).toBe(true);
    expect(phoneSchema.safeParse({ phone: "1234567890" }).success).toBe(false);
  });
  it("requires a 6-digit OTP", () => {
    expect(otpSchema.safeParse({ code: "12345" }).success).toBe(false);
    expect(otpSchema.safeParse({ code: "123456" }).success).toBe(true);
  });
});

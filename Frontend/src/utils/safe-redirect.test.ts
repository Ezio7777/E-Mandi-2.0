import { describe, expect, it } from "vitest";
import { resolveNext } from "./safe-redirect";

describe("resolveNext", () => {
  it("allows a path inside the user's own area", () => {
    expect(resolveNext("/farmer/orders/12", "farmer")).toBe("/farmer/orders/12");
  });
  it("falls back to role home when next is missing", () => {
    expect(resolveNext(null, "buyer")).toBe("/buyer/marketplace");
  });
  it("blocks another role's area", () => {
    expect(resolveNext("/admin/users", "farmer")).toBe("/farmer/dashboard");
  });
  it("blocks open redirects", () => {
    expect(resolveNext("//evil.com", "admin")).toBe("/admin/analytics");
    expect(resolveNext("https://evil.com", "admin")).toBe("/admin/analytics");
    expect(resolveNext("/\\evil.com", "admin")).toBe("/admin/analytics");
  });
  it("does not match on a shared string prefix", () => {
    expect(resolveNext("/farmerx/secret", "farmer")).toBe("/farmer/dashboard");
  });
});
